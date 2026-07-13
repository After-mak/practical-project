// 여러 api 섞어서 테스트
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

export const options = {
  stages: [
    { duration: '30s', target: 10 },
    { duration: '1m', target: 20 },
    { duration: '30s', target: 5 },
    { duration: '10s', target: 0 },
  ],
};

export default function () {
  const endpoints = [
    '/api/normal',
    '/api/cpu',
    '/api/memory',
    '/api/slow',
    '/api/error',
  ];

  const endpoint = endpoints[Math.floor(Math.random() * endpoints.length)];
  const res = http.get(`${BASE_URL}${endpoint}`);

  check(res, {
    'response received': (r) => r.status >= 200 && r.status < 500,
  });

  sleep(1);
}
