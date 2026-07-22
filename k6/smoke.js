// 배포 직후 핵심 엔드포인트가 최소 기능을 수행하는지 빠르게 확인하는 Smoke Test입니다.
import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL, DEFAULT_THRESHOLDS } from './lib/config.js';

export const options = {
  // 한 명의 가상 사용자가 한 번만 실행하므로 시스템에 거의 부하를 주지 않습니다.
  vus: 1,
  iterations: 1,
  thresholds: DEFAULT_THRESHOLDS,
};

export default function () {
  // 프로세스 상태, Redis 준비 상태, 일반 API, Prometheus 메트릭을 한 번에 확인합니다.
  const health = http.get(`${BASE_URL}/health`);
  const ready = http.get(`${BASE_URL}/ready`);
  const normal = http.get(`${BASE_URL}/api/normal`);
  const metrics = http.get(`${BASE_URL}/metrics`);

  check(health, { 'health is 200': (r) => r.status === 200 });
  check(ready, { 'ready is 200': (r) => r.status === 200 });
  check(normal, { 'normal is 200': (r) => r.status === 200 });
  check(metrics, {
    'metrics is 200': (r) => r.status === 200,
    // KEDA가 사용할 Queue Length 메트릭이 실제 응답에 포함되는지도 검사합니다.
    'queue metric exists': (r) => r.body.includes('sample_queue_length'),
  });
}
