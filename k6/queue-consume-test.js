// 쌓여 있는 Queue Length를 감소시켜 KEDA Scale-In 조건을 만드는 테스트입니다.
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

export const options = {
  vus: 10,
  duration: '1m',
};

export default function () {
  const res = http.post(`${BASE_URL}/api/queue/process`);

  check(res, {
    'status is 200': (r) => r.status === 200,
  });

  sleep(1);
}
