// 장시간 일정 부하를 유지해 메모리 누수와 성능 저하 여부를 찾는 Soak Test입니다.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, DEFAULT_THRESHOLDS, durationEnv, numberEnv } from './lib/config.js';

export const options = {
  // VUS와 TEST_DURATION을 환경변수로 조절하며 기본값은 10 VU, 30분입니다.
  vus: numberEnv('VUS', 10),
  duration: durationEnv('TEST_DURATION', '30m'),
  thresholds: DEFAULT_THRESHOLDS,
};

export default function () {
  // 부하 자체의 변수가 적도록 정상 API만 반복 호출합니다.
  const response = http.get(`${BASE_URL}/api/normal`);
  check(response, { 'soak request is 200': (r) => r.status === 200 });
  sleep(1); // 각 VU의 요청 속도를 초당 약 1회로 제한합니다.
}
