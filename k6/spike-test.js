// 낮은 정상 트래픽 뒤 CPU 부하 요청을 급격히 늘렸다가 종료해 Spike 구간을 만듭니다.
import http from 'k6/http';
import { check } from 'k6';
import {
  BASE_URL,
  TEST_HEADERS,
  durationEnv,
  numberEnv,
} from './lib/config.js';

const spikeRate = numberEnv('SPIKE_RATE', 10);

export const options = {
  scenarios: {
    spike: {
      executor: 'ramping-arrival-rate',
      startRate: 1,
      timeUnit: '1s',
      preAllocatedVUs: Math.max(10, spikeRate),
      maxVUs: Math.max(50, spikeRate * 3),
      stages: [
        { target: 1, duration: durationEnv('WARMUP_DURATION', '1m') },
        { target: spikeRate, duration: durationEnv('RAMP_DURATION', '30s') },
        { target: spikeRate, duration: durationEnv('SPIKE_DURATION', '2m') },
        { target: 1, duration: durationEnv('RECOVERY_DURATION', '1m') },
        { target: 0, duration: '30s' },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<3000'],
    checks: ['rate>0.99'],
  },
};

export default function () {
  const response = http.get(`${BASE_URL}/api/cpu`, TEST_HEADERS);
  check(response, { 'spike status is 200': (r) => r.status === 200 });
}
