// 요청마다 일시적인 메모리 할당을 발생시켜 Pod 메모리 변화를 관찰하는 테스트입니다.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, DEFAULT_THRESHOLDS } from './lib/config.js';

export const options = {
  // 5 VU가 1분 동안 일정한 메모리 부하를 만듭니다.
  vus: 5,
  duration: '1m',
  thresholds: DEFAULT_THRESHOLDS,
};

export default function () {
  // 응답이 끝나면 함수 내부 메모리는 회수 대상이 되므로 지속 누수 테스트와는 구분합니다.
  const response = http.get(`${BASE_URL}/api/memory`);
  check(response, { 'memory status is 200': (r) => r.status === 200 });
  sleep(1); // 과도한 로컬 메모리 사용을 피하기 위해 호출 간격을 둡니다.
}
