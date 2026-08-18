# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# CI/CD Test: Trigger automated ECR build and GitOps tag update

"""Web service for frontend
"""

# Module imports
import concurrent.futures
import datetime
import json
import logging
import os
import socket
import threading
import uuid
from decimal import Decimal, DecimalException
import time
from time import sleep

import requests
from requests.exceptions import HTTPError, RequestException
import jwt
import redis
from redis.exceptions import RedisError
from flask import Flask, abort, jsonify, make_response, redirect, \
    render_template, request, url_for

from opentelemetry import trace
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.propagate import set_global_textmap
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.propagators.cloud_trace_propagator import CloudTraceFormatPropagator
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.jinja2 import Jinja2Instrumentor

# Local imports
from api_call import ApiCall, ApiRequest
from traced_thread_pool_executor import TracedThreadPoolExecutor

# Local constants
BALANCE_NAME = "balance"
CONTACTS_NAME = "contacts"
TRANSACTION_LIST_NAME = "transaction_list"

# pylint: disable-msg=too-many-locals
# pylint: disable-msg=too-many-branches
def create_app():
    """Flask application factory to create instances
    of the Frontend Flask App
    """
    app = Flask(__name__)

    # Disabling unused-variable for lines with route decorated functions
    # as pylint thinks they are unused
    # pylint: disable=unused-variable
    @app.route('/version', methods=['GET'])
    def version():
        """
        Service version endpoint
        """
        return os.environ.get('VERSION'), 200

    @app.route('/ready', methods=['GET'])
    def readiness():
        """
        Readiness probe
        """
        return 'ok', 200

    @app.route('/whereami', methods=['GET'])
    def whereami():
        """
        Returns the cluster name + zone name where this Pod is running.

        """
        return "Cluster: " + cluster_name + ", Pod: " + pod_name + ", Zone: " + pod_zone, 200

    # =========================================================================
    # [1] Redis 대기열 (Waiting Room) 환경 변수 및 설정
    # =========================================================================
    # helm차트로 다운받은 redis의 환경변수 받아오는 블럭
    redis_host = os.getenv('REDIS_HOST', 'localhost')
    redis_port = int(os.getenv('REDIS_PORT', 6379))
    redis_db = int(os.getenv('REDIS_DB', 0))
    redis_password = os.getenv('REDIS_PASSWORD', '')
    redis_tls_enabled = os.getenv('REDIS_TLS_ENABLED', 'false').lower() == 'true'

    # waiting_queue_key: 대기 중인 사용자의 번호표(토큰)들이 순서대로 줄을 서 있는 Redis List 이름입니다.
    #  개별 키 "active:{token}" 방식으로 변경 (개별 TTL 적용)
    waiting_queue_key = os.getenv('REDIS_WAITING_QUEUE_KEY', 'bank-frontend-waiting-queue')
    slots_per_pod = int(os.getenv('SLOTS_PER_POD', '20'))       # pod 1개당 허용 동시 접속자 수
    heartbeat_pod_name = os.getenv('HOSTNAME', socket.gethostname())  # heartbeat 전용 pod 식별자
    frontend_pods_key = 'frontend-pods-alive'                    # 살아있는 pod 목록 prefix
    enable_waiting_room = os.getenv('ENABLE_WAITING_ROOM', 'true').lower() == 'true'
    user_session_ttl = int(os.getenv('USER_SESSION_TTL', '60'))  # 사용자 세션 TTL (초), 기본 60초

    # =========================================================================
    # [2] Redis 연결 클라이언트 생성 함수 (싱글톤 커넥션 풀 적용)
    # 매 요청마다 새 클라이언트를 만들지 않고, 1개의 클라이언트(풀)를 재사용합니다.
    # =========================================================================
    _redis_client = None

    def get_redis_client():
        nonlocal _redis_client
        if _redis_client is not None:
            return _redis_client

        try:
            _redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                password=redis_password if redis_password else None,
                ssl=redis_tls_enabled,
                socket_timeout=2.0,
                connect_timeout=2.0,
                decode_responses=True
            )
            return _redis_client
        except Exception as exc:
            app.logger.warning('Failed to connect to Redis: %s', exc)
            return None

    # =========================================================================
    # Pod Heartbeat: 10초마다 Redis에 이 pod의 생존 신호를 등록
    # TTL=30초 → pod 죽으면 30초 후 자동 삭제 → pod 수 자동 반영
    # =========================================================================
    ACTIVE_USERS_SET_KEY = 'active-users-set'
    def _pod_heartbeat():
        r = get_redis_client()
        while True:
            try:
                if not r:
                    r = get_redis_client()  # 연결 실패 시에만 재연결 시도
                if r:
                    # pod 생존 신호
                    r.setex(f"{frontend_pods_key}:{heartbeat_pod_name}", 30, "1")
                    # active-users-set 에서 만료된 토큰 정리 (SCARD 정확도 유지)
                    members = r.smembers(ACTIVE_USERS_SET_KEY)
                    if members:
                        expired = [m for m in members if not r.exists(f"active:{m}")]
                        if expired:
                            r.srem(ACTIVE_USERS_SET_KEY, *expired)
            except Exception as exc:
                app.logger.warning('Pod heartbeat error: %s', exc)
                r = None  # 에러 시 다음 루프에서 재연결
            sleep(10)

    heartbeat_thread = threading.Thread(target=_pod_heartbeat, daemon=True)
    heartbeat_thread.start()

    # =========================================================================
    # [3] 사용자별 대기열 순번 및 진입 가능 여부 체크 핵심 로직
    # =========================================================================
    def check_waiting_status(user_token):
        """
        user_token 값으로 현재 바로 입장 가능한지 기다려야 하는지 판별
        Redis 장애 시 에러 상태(passed=False, position=-1)로 반환
        """
        # 대기열 기능이 꺼져있거나 토큰이 없으면 즉시 통과
        if not enable_waiting_room or not user_token:
            return True, 0

        r = get_redis_client()
        
        # Redis 연결에 실패한 경우사용자 진입 차단
        if not r:
            return False, -1

        try:
            # [개별 TTL] 이미 서비스 이용 중인 사용자인지 확인 (개인 키 존재 여부)
            active_key = f"active:{user_token}"
            if r.exists(active_key):
                r.expire(active_key, user_session_ttl)  # 개인 TTL 연장
                return True, 0

            # [동적 MAX] 살아있는 pod 수 × slots_per_pod으로 현재 허용 인원 계산
            _, pod_keys = r.scan(0, match=f"{frontend_pods_key}:*", count=20)
            pod_count = max(len(pod_keys), 1)
            current_max = pod_count * slots_per_pod
            # heartbeat가 10초마다 만료 멤버 정리 → 항상 정확한 값 유지
            active_count = r.scard(ACTIVE_USERS_SET_KEY)
            # 사용자가 이미 대기열 줄에 있는지 확인
            pos = r.zrank(waiting_queue_key, user_token)

            if pos is not None:
                # 내 순서가 활성 이용자 여유 빈자리에 들어갈 만큼 앞 순서라면 입장 승인
                if pos < (current_max - active_count):
                    r.zrem(waiting_queue_key, user_token) # 대기 줄에서 제거
                    r.setex(active_key, user_session_ttl, "1")  # 개인 TTL로 입장 등록
                    r.sadd(ACTIVE_USERS_SET_KEY, user_token)   # Set에 입장 멤버 추가
                    return True, 0
                # 아직 순서가 안 되었으면 (False, 1-indexed 대기 순번) 반환
                return False, pos + 1
            else:
                # 처음 접속한 신규 사용자: 활성 빈자리가 있고 대기 줄이 전혀 없으면 즉시 입장
                if active_count < current_max and r.zcard(waiting_queue_key) == 0:
                    r.setex(active_key, user_session_ttl, "1")  # 개인 TTL로 즉시 입장
                    r.sadd(ACTIVE_USERS_SET_KEY, user_token)   # Set에 입장 멤버 추가
                    return True, 0
                else:
                    # 빈자리가 없으면 대기 줄 맨 뒤에 등록 (시간을 점수로 사용)
                    r.zadd(waiting_queue_key, {user_token: time.time()})
                    new_pos = r.zcard(waiting_queue_key)
                    return False, new_pos
        except Exception as exc:
            app.logger.warning('Redis queue error: %s', exc)
            return False, -1 # 에러 발생 시 프론트엔드 차단

    # =========================================================================
    # [4] 모든 웹 요청 진입 전 대기열 검사 미들웨어 (before_request)
    # =========================================================================
    @app.before_request
    def handle_waiting_room():
        """사용자가 웹페이지의 특정 라우트에 접근할 때 진입 전에 자동으로 대기 상태를 검사합니다."""
        # 헬스체크, 정적 파일(CSS/JS), 대기 화면 등은 대기열 검사에서 제외(Bypass)
        bypass_paths = ['/version', '/ready', '/whereami', '/waiting', '/api/waiting/status', '/static']
        if any(request.path.startswith(path) for path in bypass_paths):
            return None

        # 브라우저 쿠키에서 번호표(waiting_token)를 가져옴 (없으면 새로 UUID 발급)
        user_waiting_token = request.cookies.get('waiting_token')
        if not user_waiting_token:
            user_waiting_token = str(uuid.uuid4())

        passed, pos = check_waiting_status(user_waiting_token)
        
        # Redis 장애 등으로 -1이 반환되었을 경우 503 에러 안내 페이지 반환
        if not passed and pos == -1:
            return make_response("현재 서비스 이용자가 너무 많거나 시스템 점검 중입니다. 잠시 후 다시 접속해주세요.", 503)

        # 아직 입장 순서가 아니면 대기 안내 페이지('/waiting')로 리다이렉트
        if not passed:
            resp = make_response(redirect(url_for('waiting_page', target=request.path)))
            resp.set_cookie('waiting_token', user_waiting_token, max_age=86400)
            return resp

        # 입장 승인된 사용자는 다음 단계로 진행
        request.user_waiting_token = user_waiting_token
        return None

    # =========================================================================
    # [5] 응답 반환 시 대기표 쿠키(waiting_token)를 브라우저에 구워주는 후처리
    # =========================================================================
    @app.after_request
    def set_waiting_token_cookie(response):
        if hasattr(request, 'user_waiting_token') and request.user_waiting_token:
            response.set_cookie('waiting_token', request.user_waiting_token, max_age=86400)
        return response

    # =========================================================================
    # [6] 대기 순번 및 대기 화면 UI 렌더링 라우트 (/waiting)
    # =========================================================================
    @app.route('/waiting', methods=['GET'])
    def waiting_page():
        token = request.cookies.get('waiting_token')
        if not token:
            token = str(uuid.uuid4())

        passed, pos = check_waiting_status(token)
        target = request.args.get('target', '/home')
        
        if not passed and pos == -1:
            return make_response("현재 서비스 이용자가 너무 많거나 시스템 점검 중입니다. 잠시 후 다시 접속해주세요.", 503)

        # 대기 중에 내 순서가 되면 원래 접속하려던 페이지(target)로 자동 이동
        if passed:
            resp = make_response(redirect(target))
            resp.set_cookie('waiting_token', token, max_age=86400)
            return resp

        # 대기 중이면 대기 순번과 함께 waiting.html 화면 표시
        resp = make_response(render_template(
            'waiting.html',
            bank_name=os.getenv('BANK_NAME', 'Bank of Anthos'),
            token=token,
            position=pos,
            estimated_seconds=pos * 2,
            redirect_url=target
        ))
        resp.set_cookie('waiting_token', token, max_age=86400)
        return resp

    # =========================================================================
    # [7] 대기 화면에서 JavaScript가 실시간으로 대기 순번을 조회하는 AJAX API
    # =========================================================================
    @app.route('/api/waiting/status', methods=['GET'])
    def waiting_status():
        token = request.args.get('token') or request.cookies.get('waiting_token')
        if not token:
            return jsonify({'passed': True, 'position': 0})

        passed, pos = check_waiting_status(token)
        return jsonify({'passed': passed, 'position': pos})

    @app.route("/")
    def root():
        """
        Renders home page or login page, depending on authentication status.
        """
        token = request.cookies.get(app.config['TOKEN_NAME'])
        if not verify_token(token):
            return login_page()
        return home()

    @app.route("/home")
    def home():
        """
        Renders home page. Redirects to /login if token is not valid
        """
        token = request.cookies.get(app.config['TOKEN_NAME'])
        if not verify_token(token):
            # user isn't authenticated
            app.logger.debug('User isn\'t authenticated. Redirecting to login page.')
            return redirect(url_for('login_page',
                                    _external=True,
                                    _scheme=app.config['SCHEME']))
        token_data = decode_token(token)
        display_name = token_data['name']
        username = token_data['user']
        account_id = token_data['acct']

        hed = {'Authorization': 'Bearer ' + token}

        api_calls = [
            # get balance
            ApiCall(display_name=BALANCE_NAME,
                    api_request=ApiRequest(url=f'{app.config["BALANCES_URI"]}/{account_id}',
                                           headers=hed,
                                           timeout=app.config['BACKEND_TIMEOUT']),
                    logger=app.logger),
            # get history
            ApiCall(display_name=TRANSACTION_LIST_NAME,
                    api_request=ApiRequest(url=f'{app.config["HISTORY_URI"]}/{account_id}',
                                           headers=hed,
                                           timeout=app.config['BACKEND_TIMEOUT']),
                    logger=app.logger),
            # get contacts
            ApiCall(display_name=CONTACTS_NAME,
                    api_request=ApiRequest(url=f'{app.config["CONTACTS_URI"]}/{username}',
                                           headers=hed,
                                           timeout=app.config['BACKEND_TIMEOUT']),
                    logger=app.logger)
        ]

        api_response = {BALANCE_NAME: None,
                        TRANSACTION_LIST_NAME: None,
                        CONTACTS_NAME: []}

        tracer = trace.get_tracer(__name__)
        with TracedThreadPoolExecutor(tracer, max_workers=3) as executor:
            futures = []

            future_to_api_call = {
                executor.submit(api_call.make_call):
                    api_call for api_call in api_calls
            }

            for future in concurrent.futures.as_completed(future_to_api_call):
                if future.result():
                    api_call = future_to_api_call[future]
                    api_response[api_call.display_name] = future.result().json()

        _populate_contact_labels(account_id,
                                 api_response[TRANSACTION_LIST_NAME],
                                 api_response[CONTACTS_NAME])

        return render_template('index.html',
                               account_id=account_id,
                               balance=api_response[BALANCE_NAME],
                               bank_name=os.getenv('BANK_NAME', 'Bank of Anthos'),
                               cluster_name=cluster_name,
                               contacts=api_response[CONTACTS_NAME],
                               cymbal_logo=os.getenv('CYMBAL_LOGO', 'false'),
                               history=api_response[TRANSACTION_LIST_NAME],
                               message=request.args.get('msg', None),
                               name=display_name,
                               platform=platform,
                               platform_display_name=platform_display_name,
                               pod_name=pod_name,
                               pod_zone=pod_zone)

    def _populate_contact_labels(account_id, transactions, contacts):
        """
        Populate contact labels for the passed transactions.

        Side effect:
            Take each transaction and set the 'accountLabel' field with the label of
            the contact each transaction was associated with. If there was no
            associated contact, set 'accountLabel' to None.
            If any parameter is None, nothing happens.

        Params: account_id - the account id for the user owning the transaction list
                transactions - a list of transactions as key/value dicts
                            [{transaction1}, {transaction2}, ...]
                contacts - a list of contacts as key/value dicts
                        [{contact1}, {contact2}, ...]
        """
        app.logger.debug('Populating contact labels.')
        if account_id is None or transactions is None or contacts is None:
            return

        # Map contact accounts to their labels. If no label found, default to None.
        contact_map = {c['account_num']: c.get('label') for c in contacts}

        # Populate the 'accountLabel' field. If no match found, default to None.
        for trans in transactions:
            if trans['toAccountNum'] == account_id:
                trans['accountLabel'] = contact_map.get(trans['fromAccountNum'])
            elif trans['fromAccountNum'] == account_id:
                trans['accountLabel'] = contact_map.get(trans['toAccountNum'])

    @app.route('/payment', methods=['POST'])
    def payment():
        """
        Submits payment request to ledgerwriter service

        Fails if:
        - token is not valid
        - basic validation checks fail
        - response code from ledgerwriter is not 201
        """
        token = request.cookies.get(app.config['TOKEN_NAME'])
        if not verify_token(token):
            # user isn't authenticated
            app.logger.error('Error submitting payment: user is not authenticated.')
            return abort(401)
        try:
            account_id = decode_token(token)['acct']
            recipient = request.form['account_num']
            if recipient == 'add':
                recipient = request.form['contact_account_num']
                label = request.form.get('contact_label', None)
                if label:
                    # new contact. Add to contacts list
                    _add_contact(label,
                                 recipient,
                                 app.config['LOCAL_ROUTING'],
                                 False)

            user_input = request.form['amount']
            payment_amount = int(Decimal(user_input) * 100)
            transaction_data = {"fromAccountNum": account_id,
                                "fromRoutingNum": app.config['LOCAL_ROUTING'],
                                "toAccountNum": recipient,
                                "toRoutingNum": app.config['LOCAL_ROUTING'],
                                "amount": payment_amount,
                                "uuid": request.form['uuid']}
            _submit_transaction(transaction_data)
            app.logger.info('Payment initiated successfully.')
            return redirect(code=303,
                            location=url_for('home',
                                             msg='Payment successful',
                                             _external=True,
                                             _scheme=app.config['SCHEME']))

        except requests.exceptions.RequestException as err:
            app.logger.error('Error submitting payment: %s', str(err))
        except UserWarning as warn:
            app.logger.error('Error submitting payment: %s', str(warn))
            msg = 'Payment failed: {}'.format(str(warn))
            return redirect(url_for('home',
                                    msg=msg,
                                    _external=True,
                                    _scheme=app.config['SCHEME']))
        except (ValueError, DecimalException) as num_err:
            app.logger.error('Error submitting payment: %s', str(num_err))
            msg = 'Payment failed: {} is not a valid number'.format(user_input)

        return redirect(url_for('home',
                                msg='Payment failed',
                                _external=True,
                                _scheme=app.config['SCHEME']))

    @app.route('/deposit', methods=['POST'])
    def deposit():
        """
        Submits deposit request to ledgerwriter service

        Fails if:
        - token is not valid
        - routing number == local routing number
        - response code from ledgerwriter is not 201
        """
        token = request.cookies.get(app.config['TOKEN_NAME'])
        if not verify_token(token):
            # user isn't authenticated
            app.logger.error('Error submitting deposit: user is not authenticated.')
            return abort(401)
        try:
            # get account id from token
            account_id = decode_token(token)['acct']
            if request.form['account'] == 'add':
                external_account_num = request.form['external_account_num']
                external_routing_num = request.form['external_routing_num']
                if external_routing_num == app.config['LOCAL_ROUTING']:
                    raise UserWarning("invalid routing number")
                external_label = request.form.get('external_label', None)
                if external_label:
                    # new contact. Add to contacts list
                    _add_contact(external_label,
                                 external_account_num,
                                 external_routing_num,
                                 True)
            else:
                account_details = json.loads(request.form['account'])
                external_account_num = account_details['account_num']
                external_routing_num = account_details['routing_num']

            transaction_data = {"fromAccountNum": external_account_num,
                                "fromRoutingNum": external_routing_num,
                                "toAccountNum": account_id,
                                "toRoutingNum": app.config['LOCAL_ROUTING'],
                                "amount": int(Decimal(request.form['amount']) * 100),
                                "uuid": request.form['uuid']}
            _submit_transaction(transaction_data)
            app.logger.info('Deposit submitted successfully.')
            return redirect(code=303,
                            location=url_for('home',
                                             msg='Deposit successful',
                                             _external=True,
                                             _scheme=app.config['SCHEME']))

        except requests.exceptions.RequestException as err:
            app.logger.error('Error submitting deposit: %s', str(err))
        except UserWarning as warn:
            app.logger.error('Error submitting deposit: %s', str(warn))
            msg = 'Deposit failed: {}'.format(str(warn))
            return redirect(url_for('home',
                                    msg=msg,
                                    _external=True,
                                    _scheme=app.config['SCHEME']))

        return redirect(url_for('home',
                                msg='Deposit failed',
                                _external=True,
                                _scheme=app.config['SCHEME']))

    def _submit_transaction(transaction_data):
        app.logger.debug('Submitting transaction.')
        token = request.cookies.get(app.config['TOKEN_NAME'])
        hed = {'Authorization': 'Bearer ' + token,
               'content-type': 'application/json'}
        resp = requests.post(url=app.config["TRANSACTIONS_URI"],
                             data=jsonify(transaction_data).data,
                             headers=hed,
                             timeout=app.config['BACKEND_TIMEOUT'])
        try:
            resp.raise_for_status()  # Raise on HTTP Status code 4XX or 5XX
        except requests.exceptions.HTTPError as http_request_err:
            raise UserWarning(resp.text) from http_request_err
        # Short delay to allow the transaction to propagate to balancereader
        # and transaction-history
        sleep(0.25)

    def _add_contact(label, acct_num, routing_num, is_external_acct=False):
        """
        Submits a new contact to the contact service.

        Raise: UserWarning  if the response status is 4xx or 5xx.
        """
        app.logger.debug('Adding new contact.')
        token = request.cookies.get(app.config['TOKEN_NAME'])
        hed = {'Authorization': 'Bearer ' + token,
               'content-type': 'application/json'}
        contact_data = {
            'label': label,
            'account_num': acct_num,
            'routing_num': routing_num,
            'is_external': is_external_acct
        }
        token_data = decode_token(token)
        url = '{}/{}'.format(app.config["CONTACTS_URI"], token_data['user'])
        resp = requests.post(url=url,
                             data=jsonify(contact_data).data,
                             headers=hed,
                             timeout=app.config['BACKEND_TIMEOUT'])
        try:
            resp.raise_for_status()  # Raise on HTTP Status code 4XX or 5XX
        except requests.exceptions.HTTPError as http_request_err:
            raise UserWarning(resp.text) from http_request_err

    @app.route("/login", methods=['GET'])
    def login_page():
        """
        Renders login page. Redirects to /home if user already has a valid token.
        If this is an oauth flow, then redirect to a consent form.
        """
        token = request.cookies.get(app.config['TOKEN_NAME'])
        response_type = request.args.get('response_type')
        client_id = request.args.get('client_id')
        app_name = request.args.get('app_name')
        redirect_uri = request.args.get('redirect_uri')
        state = request.args.get('state')
        if ('REGISTERED_OAUTH_CLIENT_ID' in os.environ and
            'ALLOWED_OAUTH_REDIRECT_URI' in os.environ and
                response_type == 'code'):
            app.logger.debug('Login with response_type=code')
            if client_id != os.environ['REGISTERED_OAUTH_CLIENT_ID']:
                return redirect(url_for('login',
                                        msg='Error: Invalid client_id',
                                        _external=True,
                                        _scheme=app.config['SCHEME']))
            if redirect_uri != os.environ['ALLOWED_OAUTH_REDIRECT_URI']:
                return redirect(url_for('login',
                                        msg='Error: Invalid redirect_uri',
                                        _external=True,
                                        _scheme=app.config['SCHEME']))
            if verify_token(token):
                app.logger.debug('User already authenticated. Redirecting to /consent')
                return make_response(redirect(url_for('consent',
                                                      state=state,
                                                      redirect_uri=redirect_uri,
                                                      app_name=app_name,
                                                      _external=True,
                                                      _scheme=app.config['SCHEME'])))
        else:
            if verify_token(token):
                # already authenticated
                app.logger.debug('User already authenticated. Redirecting to /home')
                return redirect(url_for('home',
                                        _external=True,
                                        _scheme=app.config['SCHEME']))

        return render_template('login.html',
                               app_name=app_name,
                               bank_name=os.getenv('BANK_NAME', 'Bank of Anthos'),
                               cluster_name=cluster_name,
                               cymbal_logo=os.getenv('CYMBAL_LOGO', 'false'),
                               default_password=os.getenv('DEFAULT_PASSWORD', ''),
                               default_user=os.getenv('DEFAULT_USERNAME', ''),
                               message=request.args.get('msg', None),
                               platform=platform,
                               platform_display_name=platform_display_name,
                               pod_name=pod_name,
                               pod_zone=pod_zone,
                               redirect_uri=redirect_uri,
                               response_type=response_type,
                               state=state)

    @app.route('/login', methods=['POST'])
    def login():
        """
        Submits login request to userservice and saves resulting token

        Fails if userservice does not accept input username and password
        """
        return _login_helper(request.form['username'],
                             request.form['password'],
                             request.args)

    def _login_helper(username, password, request_args):
        try:
            app.logger.debug('Logging in.')
            req = requests.get(url=app.config["LOGIN_URI"],
                               params={'username': username, 'password': password},
                               timeout=app.config['BACKEND_TIMEOUT']*2)
            req.raise_for_status()  # Raise on HTTP Status code 4XX or 5XX

            # login success
            token = req.json()['token']
            claims = decode_token(token)
            max_age = claims['exp'] - claims['iat']

            if ('response_type' in request_args and
                'state' in request_args and
                'redirect_uri' in request_args and
                    request_args['response_type'] == 'code'):
                resp = make_response(redirect(url_for('consent',
                                                      state=request_args['state'],
                                                      redirect_uri=request_args['redirect_uri'],
                                                      app_name=request_args['app_name'],
                                                      _external=True,
                                                      _scheme=app.config['SCHEME'])))
            else:
                resp = make_response(redirect(url_for('home',
                                                      _external=True,
                                                      _scheme=app.config['SCHEME'])))
            resp.set_cookie(app.config['TOKEN_NAME'], token, max_age=max_age)
            app.logger.info('Successfully logged in.')
            return resp
        except (RequestException, HTTPError) as err:
            app.logger.error('Error logging in: %s', str(err))
        return redirect(url_for('login',
                                msg='Login Failed',
                                _external=True,
                                _scheme=app.config['SCHEME']))

    @app.route("/consent", methods=['GET'])
    def consent_page():
        """Renders consent page.

        Retrieves auth code if the user has
        already logged in and consented.
        """
        redirect_uri = request.args.get('redirect_uri')
        state = request.args.get('state')
        app_name = request.args.get('app_name')
        token = request.cookies.get(app.config['TOKEN_NAME'])
        consented = request.cookies.get(app.config['CONSENT_COOKIE'])
        if verify_token(token):
            if consented == "true":
                app.logger.debug('User consent already granted.')
                resp = _auth_callback_helper(state, redirect_uri, token)
                return resp

            return render_template('consent.html',
                                   app_name=app_name,
                                   bank_name=os.getenv('BANK_NAME', 'Bank of Anthos'),
                                   cluster_name=cluster_name,
                                   cymbal_logo=os.getenv('CYMBAL_LOGO', 'false'),
                                   platform=platform,
                                   platform_display_name=platform_display_name,
                                   pod_name=pod_name,
                                   pod_zone=pod_zone,
                                   redirect_uri=redirect_uri,
                                   state=state)

        return make_response(redirect(url_for('login',
                                              response_type="code",
                                              state=state,
                                              redirect_uri=redirect_uri,
                                              app_name=app_name,
                                              _external=True,
                                              _scheme=app.config['SCHEME'])))

    @app.route('/consent', methods=['POST'])
    def consent():
        """
        Check consent, write cookie if yes, and redirect accordingly
        """
        consent = request.args['consent']
        state = request.args['state']
        redirect_uri = request.args['redirect_uri']
        token = request.cookies.get(app.config['TOKEN_NAME'])

        app.logger.debug('Checking consent. consent: %s', consent)

        if consent == "true":
            app.logger.info('User consent granted.')
            resp = _auth_callback_helper(state, redirect_uri, token)
            resp.set_cookie(app.config['CONSENT_COOKIE'], 'true')
        else:
            app.logger.info('User consent denied.')
            resp = make_response(redirect(redirect_uri + '#error=access_denied', 302))
        return resp

    def _auth_callback_helper(state, redirect_uri, token):
        try:
            app.logger.debug('Retrieving authorization code.')
            callback_response = requests.post(url=redirect_uri,
                                              data={'state': state, 'id_token': token},
                                              timeout=app.config['BACKEND_TIMEOUT'],
                                              allow_redirects=False)
            if callback_response.status_code == requests.codes.found:
                app.logger.info('Successfully retrieved auth code.')
                location = callback_response.headers['Location']
                return make_response(redirect(location, 302))

            app.logger.error('Unexpected response status: %s', callback_response.status_code)
            return make_response(redirect(redirect_uri + '#error=server_error', 302))
        except requests.exceptions.RequestException as err:
            app.logger.error('Error retrieving auth code: %s', str(err))
        return make_response(redirect(redirect_uri + '#error=server_error', 302))

    @app.route("/signup", methods=['GET'])
    def signup_page():
        """
        Renders signup page. Redirects to /login if token is not valid
        """
        token = request.cookies.get(app.config['TOKEN_NAME'])
        if verify_token(token):
            # already authenticated
            app.logger.debug('User already authenticated. Redirecting to /home')
            return redirect(url_for('home',
                                    _external=True,
                                    _scheme=app.config['SCHEME']))
        return render_template('signup.html',
                               bank_name=os.getenv('BANK_NAME', 'Bank of Anthos'),
                               cluster_name=cluster_name,
                               cymbal_logo=os.getenv('CYMBAL_LOGO', 'false'),
                               platform=platform,
                               platform_display_name=platform_display_name,
                               pod_name=pod_name,
                               pod_zone=pod_zone)

    @app.route("/signup", methods=['POST'])
    def signup():
        """
        Submits signup request to userservice

        Fails if userservice does not accept input form data
        """
        try:
            # create user
            app.logger.debug('Creating new user.')
            resp = requests.post(url=app.config["USERSERVICE_URI"],
                                 data=request.form,
                                 timeout=app.config['BACKEND_TIMEOUT'])
            if resp.status_code == 201:
                # user created. Attempt login
                app.logger.info('New user created.')
                return _login_helper(request.form['username'],
                                     request.form['password'],
                                     request.args)
        except requests.exceptions.RequestException as err:
            app.logger.error('Error creating new user: %s', str(err))
        return redirect(url_for('login',
                                msg='Error: Account creation failed',
                                _external=True,
                                _scheme=app.config['SCHEME']))

    @app.route('/logout', methods=['POST'])
    def logout():
        """
        Logs out user by deleting token cookie and redirecting to login page
        """
        app.logger.info('Logging out.')
        resp = make_response(redirect(url_for('login_page',
                                              _external=True,
                                              _scheme=app.config['SCHEME'])))
        resp.delete_cookie(app.config['TOKEN_NAME'])
        resp.delete_cookie(app.config['CONSENT_COOKIE'])
        return resp

    def decode_token(token):
        return jwt.decode(algorithms='RS256',
                          jwt=token,
                          options={"verify_signature": False})

    def verify_token(token):
        """
        Validates token using userservice public key
        """
        app.logger.debug('Verifying token.')
        if token is None:
            return False
        try:
            jwt.decode(algorithms='RS256',
                       jwt=token,
                       key=app.config['PUBLIC_KEY'],
                       options={"verify_signature": True})
            app.logger.debug('Token verified.')
            return True
        except jwt.exceptions.InvalidTokenError as err:
            app.logger.error('Error validating token: %s', str(err))
            return False

    # register html template formatters
    def format_timestamp_day(timestamp):
        """ Format the input timestamp day in a human readable way """
        # TODO: time zones?
        date = datetime.datetime.strptime(timestamp, app.config['TIMESTAMP_FORMAT'])
        return date.strftime('%d')

    def format_timestamp_month(timestamp):
        """ Format the input timestamp month in a human readable way """
        # TODO: time zones?
        date = datetime.datetime.strptime(timestamp, app.config['TIMESTAMP_FORMAT'])
        return date.strftime('%b')

    def format_currency(int_amount):
        """ Format the input currency in a human readable way """
        if int_amount is None:
            return '$---'
        amount_str = '${:0,.2f}'.format(abs(Decimal(int_amount)/100))
        if int_amount < 0:
            amount_str = '-' + amount_str
        return amount_str

    # set up global variables
    app.config["TRANSACTIONS_URI"] = 'http://{}/transactions'.format(
        os.environ.get('TRANSACTIONS_API_ADDR'))
    app.config["USERSERVICE_URI"] = 'http://{}/users'.format(
        os.environ.get('USERSERVICE_API_ADDR'))
    app.config["BALANCES_URI"] = 'http://{}/balances'.format(
        os.environ.get('BALANCES_API_ADDR'))
    app.config["HISTORY_URI"] = 'http://{}/transactions'.format(
        os.environ.get('HISTORY_API_ADDR'))
    app.config["LOGIN_URI"] = 'http://{}/login'.format(
        os.environ.get('USERSERVICE_API_ADDR'))
    app.config["CONTACTS_URI"] = 'http://{}/contacts'.format(
        os.environ.get('CONTACTS_API_ADDR'))
    app.config['PUBLIC_KEY'] = open(os.environ.get('PUB_KEY_PATH'), 'r').read()
    app.config['LOCAL_ROUTING'] = os.getenv('LOCAL_ROUTING_NUM')
    # timeout in seconds for calls to the backend
    app.config['BACKEND_TIMEOUT'] = int(os.getenv('BACKEND_TIMEOUT', '4'))
    app.config['TOKEN_NAME'] = 'token'
    app.config['CONSENT_COOKIE'] = 'consented'
    app.config['TIMESTAMP_FORMAT'] = '%Y-%m-%dT%H:%M:%S.%f%z'
    app.config['SCHEME'] = os.environ.get('SCHEME', 'http')

    # where am I?
    metadata_server = os.getenv('METADATA_SERVER', 'metadata.google.internal')
    metadata_url = f'http://{metadata_server}/computeMetadata/v1/'
    metadata_headers = {'Metadata-Flavor': 'Google'}

    # get GKE cluster name
    cluster_name = os.getenv('CLUSTER_NAME', 'unknown')
    try:
        req = requests.get(metadata_url + 'instance/attributes/cluster-name',
                           headers=metadata_headers,
                           timeout=app.config['BACKEND_TIMEOUT'])
        if req.ok:
            cluster_name = str(req.text)
    except (RequestException, HTTPError) as err:
        app.logger.warning(
            "Unable to retrieve cluster name from metadata server %s.", metadata_server)

    # get GKE pod name
    pod_name = "unknown"
    pod_name = socket.gethostname()

    # get GKE node zone
    pod_zone = os.getenv('POD_ZONE', 'unknown')
    try:
        req = requests.get(metadata_url + 'instance/zone',
                           headers=metadata_headers,
                           timeout=app.config['BACKEND_TIMEOUT'])
        if req.ok:
            pod_zone = str(req.text.split("/")[3])
    except (RequestException, HTTPError) as err:
        app.logger.warning("Unable to retrieve zone from metadata server %s.", metadata_server)

    # register formater functions
    app.jinja_env.globals.update(format_currency=format_currency)
    app.jinja_env.globals.update(format_timestamp_month=format_timestamp_month)
    app.jinja_env.globals.update(format_timestamp_day=format_timestamp_day)

    # Set up logging
    app.logger.handlers = logging.getLogger('gunicorn.error').handlers
    app.logger.setLevel(logging.getLogger('gunicorn.error').level)
    app.logger.info('Starting frontend service.')

    # Set up tracing and export spans to Cloud Trace.
    if os.environ['ENABLE_TRACING'] == "true":
        app.logger.info("✅ Tracing enabled.")
        trace.set_tracer_provider(TracerProvider())
        cloud_trace_exporter = CloudTraceSpanExporter()
        trace.get_tracer_provider().add_span_processor(
            BatchSpanProcessor(cloud_trace_exporter)
        )
        set_global_textmap(CloudTraceFormatPropagator())
        # Add tracing auto-instrumentation for Flask, jinja and requests
        FlaskInstrumentor().instrument_app(app)
        RequestsInstrumentor().instrument()
        Jinja2Instrumentor().instrument()
    else:
        app.logger.info("🚫 Tracing disabled.")

    platform = os.getenv('ENV_PLATFORM', None)
    platform_display_name = None
    if platform is not None:
        platform = platform.lower()
        if platform not in ['alibaba', 'aws', 'azure', 'gcp', 'local', 'onprem']:
            app.logger.error("Platform '%s' not supported, defaulting to None", platform)
            platform = None
        else:
            app.logger.info("Platform is set to '%s'", platform)
            if platform == 'alibaba':
                platform_display_name = "Alibaba Cloud"
            elif platform == 'aws':
                platform_display_name = "AWS"
            elif platform == 'azure':
                platform_display_name = "Azure"
            elif platform == 'gcp':
                platform_display_name = "Google Cloud"
            elif platform == 'local':
                platform_display_name = "Local"
            elif platform == 'onprem':
                platform_display_name = "On-Premises"
    else:
        app.logger.info("ENV_PLATFORM environment variable is not set")

    return app


if __name__ == "__main__":
    # Create an instance of flask server when called directly
    FRONTEND = create_app()
    FRONTEND.run()
