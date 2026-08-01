// CPU 연산 API를 호출해 CPU 사용량 급증과 응답 시간 변화를 관찰하는 테스트입니다.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, DEFAULT_THRESHOLDS, TEST_HEADERS } from './lib/config.js';

export const options = {
  // 적은 VU로 시작해 10 VU까지 올린 뒤 빠르게 부하를 종료합니다.
  stages: [
    { duration: '20s', target: 2 },
    { duration: '40s', target: 10 },
    { duration: '20s', target: 0 },
  ],
  thresholds: {
    ...DEFAULT_THRESHOLDS,
    // CPU 부하 API는 의도적으로 무거우므로 일반 API보다 p95 허용 시간을 넓게 둡니다.
    http_req_duration: ['p(95)<3000'],
  },
};

export default function () {
  // 서버에서 반복 연산을 수행하는 엔드포인트를 호출합니다.
  const response = http.get(`${BASE_URL}/api/cpu`, TEST_HEADERS);
  check(response, { 'cpu status is 200': (r) => r.status === 200 });
  sleep(0.5); // CPU를 계속 점유하지 않도록 요청 사이에 짧은 간격을 둡니다.
}
