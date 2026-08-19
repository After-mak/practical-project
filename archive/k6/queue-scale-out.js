// Worker 처리 속도보다 빠르게 Redis Queue에 작업을 등록해 KEDA Scale-out을 유도합니다.
import http from 'k6/http';
import { check } from 'k6';
import {
  BASE_URL,
  DEFAULT_THRESHOLDS,
  JSON_HEADERS,
  durationEnv,
  numberEnv,
} from './lib/config.js';

// 초당 Queue 등록 건수이며 -e QUEUE_RATE=<값>으로 변경할 수 있습니다.
const queueRate = numberEnv('QUEUE_RATE', 20);

export const options = {
  scenarios: {
    queue_growth: {
      // VU 수가 아니라 초당 도착률을 고정해 재현 가능한 Queue 증가 속도를 만듭니다.
      executor: 'constant-arrival-rate',
      rate: queueRate,
      timeUnit: '1s',
      duration: durationEnv('TEST_DURATION', '2m'), // -e TEST_DURATION=30s 형식으로 변경합니다.
      preAllocatedVUs: Math.max(10, queueRate),
      maxVUs: Math.max(50, queueRate * 2),
    },
  },
  thresholds: DEFAULT_THRESHOLDS,
};

export default function () {
  // Worker가 처리할 작업 유형과 샘플 처리 시간을 JSON으로 Queue API에 전달합니다.
  const response = http.post(
    `${BASE_URL}/api/queue/join`,
    JSON.stringify({ job_type: 'scale-test', payload: { processing_seconds: 0.25 } }),
    JSON_HEADERS,
  );
  // 등록 API가 HTTP 200이 아니면 공통 check Threshold에 의해 테스트가 실패합니다.
  check(response, { 'queue join status is 200': (r) => r.status === 200 });
}
