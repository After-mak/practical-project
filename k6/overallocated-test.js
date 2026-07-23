// 높은 Request를 가진 전용 Deployment에 낮고 안정적인 부하를 제공해 KRR 데이터를 만듭니다.
import http from 'k6/http';
import { check } from 'k6';
import {
  BASE_URL,
  DEFAULT_THRESHOLDS,
  durationEnv,
  numberEnv,
} from './lib/config.js';

const requestRate = numberEnv('REQUEST_RATE', 2);

export const options = {
  scenarios: {
    overallocated: {
      executor: 'constant-arrival-rate',
      rate: requestRate,
      timeUnit: '1s',
      duration: durationEnv('TEST_DURATION', '30m'),
      preAllocatedVUs: Math.max(2, requestRate),
      maxVUs: Math.max(10, requestRate * 2),
    },
  },
  thresholds: DEFAULT_THRESHOLDS,
};

export default function () {
  const response = http.get(`${BASE_URL}/api/normal`);
  check(response, { 'overallocated status is 200': (r) => r.status === 200 });
}
