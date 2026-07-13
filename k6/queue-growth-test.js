// Queue Length를 빠르게 증가시켜 KEDA Scale-Out 조건을 만드는 테스트입니다.
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

export const options = {
  stages: [
    { duration: '30s', target: 10 },
    { duration: '1m', target: 30 },
    { duration: '30s', target: 10 },
    { duration: '10s', target: 0 },
  ],
};

export default function () {
  const res = http.post(`${BASE_URL}/api/queue/join`);

  check(res, {
    'status is 200': (r) => r.status === 200,
  });

  sleep(1);
}
