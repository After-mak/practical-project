// 생성 부하를 중지한 뒤 Worker가 Queue를 0까지 비우는지 관찰하는 Scale-in 테스트입니다.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Gauge } from 'k6/metrics';
import { BASE_URL, DEFAULT_THRESHOLDS, durationEnv } from './lib/config.js';

// 매 조회 시점의 Queue Length를 기록하며 Gauge의 마지막 값으로 종료 조건을 판정합니다.
const queueLength = new Gauge('observed_queue_length');
const processingLength = new Gauge('observed_processing_length');

export const options = {
  // 상태 조회 자체가 부하가 되지 않도록 한 명의 VU만 사용합니다.
  vus: 1,
  duration: durationEnv('TEST_DURATION', '2m'),
  thresholds: {
    ...DEFAULT_THRESHOLDS,
    // 테스트 종료 시 마지막 Queue Length가 0이 아니면 k6가 실패 코드로 종료됩니다.
    observed_queue_length: ['value==0'],
    observed_processing_length: ['value==0'],
  },
};

export default function () {
  // Worker가 소비하는 동안 Queue 상태를 2초마다 조회합니다.
  const response = http.get(`${BASE_URL}/api/queue/status`);
  const valid = check(response, { 'queue status is 200': (r) => r.status === 200 });
  if (valid) {
    // HTTP 응답이 정상일 때만 Queue Length를 Gauge에 기록합니다.
    queueLength.add(response.json('queue_length'));
    processingLength.add(response.json('processing_length'));
  }
  sleep(2);
}
