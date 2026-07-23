// 일정한 정상 트래픽으로 CPU·Memory·응답시간의 KRR 기준 구간을 생성합니다.
import http from 'k6/http';
import { check } from 'k6';
import {
  BASE_URL,
  DEFAULT_THRESHOLDS,
  durationEnv,
  numberEnv,
} from './lib/config.js';

const requestRate = numberEnv('REQUEST_RATE', 10);

export const options = {
  scenarios: {
    baseline: {
      executor: 'constant-arrival-rate',
      rate: requestRate,
      timeUnit: '1s',
      duration: durationEnv('TEST_DURATION', '10m'),
      preAllocatedVUs: Math.max(5, requestRate),
      maxVUs: Math.max(20, requestRate * 2),
    },
  },
  thresholds: DEFAULT_THRESHOLDS,
};

export default function () {
  const response = http.get(`${BASE_URL}/api/normal`);
  check(response, { 'baseline status is 200': (r) => r.status === 200 });
}
