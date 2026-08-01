// 요청이 거의 없는 장시간 구간을 만들어 유휴 Replica와 기본 리소스 사용량을 관측합니다.
import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL, DEFAULT_THRESHOLDS, durationEnv } from './lib/config.js';

export const options = {
  scenarios: {
    idle: {
      executor: 'constant-arrival-rate',
      rate: 1,
      timeUnit: '30s',
      duration: durationEnv('TEST_DURATION', '30m'),
      preAllocatedVUs: 1,
      maxVUs: 2,
    },
  },
  thresholds: DEFAULT_THRESHOLDS,
};

export default function () {
  const response = http.get(`${BASE_URL}/api/normal`);
  check(response, { 'idle probe status is 200': (r) => r.status === 200 });
}
