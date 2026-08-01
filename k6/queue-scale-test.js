// Queue 증가와 소진 관측을 한 실행에 묶어 KEDA 1→3→1 회귀 테스트를 재현합니다.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Gauge } from 'k6/metrics';
import {
  BASE_URL,
  JSON_HEADERS,
  durationEnv,
  numberEnv,
} from './lib/config.js';

const queueRate = numberEnv('QUEUE_RATE', 20);
const loadDuration = durationEnv('LOAD_DURATION', '30s');
const drainDuration = durationEnv('DRAIN_DURATION', '8m');
const processingSeconds = numberEnv('PROCESSING_SECONDS', 0.25);
const queueLength = new Gauge('observed_queue_length');
const processingLength = new Gauge('observed_processing_length');

export const options = {
  scenarios: {
    queue_growth: {
      executor: 'constant-arrival-rate',
      exec: 'enqueue',
      rate: queueRate,
      timeUnit: '1s',
      duration: loadDuration,
      preAllocatedVUs: Math.max(10, queueRate),
      maxVUs: Math.max(50, queueRate * 2),
    },
    queue_drain: {
      executor: 'constant-vus',
      exec: 'observe',
      vus: 1,
      startTime: loadDuration,
      duration: drainDuration,
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    checks: ['rate>0.99'],
    observed_queue_length: ['value==0'],
    observed_processing_length: ['value==0'],
  },
};

export function enqueue() {
  const response = http.post(
    `${BASE_URL}/api/queue/join`,
    JSON.stringify({
      job_type: 'keda-scale-test',
      payload: { processing_seconds: processingSeconds },
    }),
    JSON_HEADERS,
  );
  check(response, { 'queue join status is 200': (r) => r.status === 200 });
}

export function observe() {
  const response = http.get(`${BASE_URL}/api/queue/status`);
  const valid = check(response, { 'queue status is 200': (r) => r.status === 200 });
  if (valid) {
    queueLength.add(response.json('queue_length'));
    processingLength.add(response.json('processing_length'));
  }
  sleep(2);
}

export default enqueue;
