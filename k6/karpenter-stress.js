// KEDA가 많은 Worker Pod를 생성하게 만들어 Karpenter Node 확장을 유도하는 고부하 테스트입니다.
import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL, JSON_HEADERS, durationEnv, numberEnv } from './lib/config.js';

// 기본 초당 100건이며 실제 EKS 용량과 KEDA 최대 Replica를 확인한 뒤 조정해야 합니다.
const queueRate = numberEnv('QUEUE_RATE', 100);

export const options = {
  scenarios: {
    pending_pod_pressure: {
      // 일정한 높은 도착률로 Queue를 빠르게 늘려 Worker Pod의 리소스 수요를 만듭니다.
      executor: 'constant-arrival-rate',
      rate: queueRate,
      timeUnit: '1s',
      duration: durationEnv('TEST_DURATION', '5m'),
      preAllocatedVUs: Math.max(50, queueRate),
      maxVUs: Math.max(200, queueRate * 2),
    },
  },
  thresholds: {
    // 인프라 확장 직전의 일시 지연을 고려해 일반 테스트보다 허용 범위를 넓게 설정합니다.
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<1000'],
    checks: ['rate>0.95'],
  },
};

export default function () {
  // 각 작업의 처리 시간을 1초로 지정해 Worker 처리량보다 Queue 증가량이 커지도록 합니다.
  const response = http.post(
    `${BASE_URL}/api/queue/join`,
    JSON.stringify({ job_type: 'karpenter-stress', payload: { processing_seconds: 1 } }),
    JSON_HEADERS,
  );
  // Queue API가 요청을 정상적으로 수락했는지 확인합니다.
  check(response, { 'stress queue join accepted': (r) => r.status === 200 });
}
