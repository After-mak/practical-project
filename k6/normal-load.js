// 정상 API의 기준 응답 시간과 실패율을 측정하는 단계형 일반 부하 테스트입니다.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, DEFAULT_THRESHOLDS } from './lib/config.js';

export const options = {
  // 워밍업 → 부하 증가 → 유지 → 감소 → 종료 순서로 트래픽을 변경합니다.
  stages: [
    { duration: '30s', target: 5 },
    { duration: '1m', target: 10 },
    { duration: '3m', target: 10 },
    { duration: '1m', target: 5 },
    { duration: '30s', target: 0 },
  ],
  thresholds: DEFAULT_THRESHOLDS,
};

export default function () {
  // CPU나 메모리 부하를 의도적으로 만들지 않는 기준선 API만 호출합니다.
  const response = http.get(`${BASE_URL}/api/normal`);
  check(response, { 'normal status is 200': (r) => r.status === 200 });
  sleep(1); // 각 VU가 초당 약 1회 요청하도록 간격을 둡니다.
}
