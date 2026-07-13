// Queue Length의 증가와 감소를 한 실행에서 만들어 KEDA Scale-Out/Scale-In을 검증합니다.
import http from 'k6/http';
import { check, sleep } from 'k6';
import exec from 'k6/execution';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const GROWTH_PHASE_MS = 3 * 60 * 1000;

export const options = {
  stages: [
    { duration: '1m', target: 20 },
    { duration: '2m', target: 50 },
    { duration: '1m', target: 20 },
    { duration: '30s', target: 0 },
  ],
};

export default function () {
  // 테스트 시작 후 경과 시간이 증가 구간(3분) 안에 있는지 확인합니다.
  // currentTestRunDuration은 현재 테스트가 실행된 시간을 밀리초 단위로 제공합니다.
  const isGrowthPhase = exec.instance.currentTestRunDuration < GROWTH_PHASE_MS;

  // 증가 구간에는 70% 확률로 join을 호출하고, 이후 감소 구간에는 join 비율을 20%로 낮춥니다.
  // 감소 구간에서는 나머지 80%가 process 요청이 되어 Queue Length가 줄어드는 흐름을 만듭니다.
  const joinRatio = isGrowthPhase ? 0.7 : 0.2;

  // 0 이상 1 미만의 난수를 생성하고 현재 join 비율과 비교해 호출할 API를 선택합니다.
  const endpoint = Math.random() < joinRatio
    // 난수가 join 비율보다 작으면 사용자가 대기열에 들어오는 요청을 선택합니다.
    ? '/api/queue/join'
    // 그렇지 않으면 대기열 항목을 처리하는 요청을 선택합니다.
    : '/api/queue/process';

  // 환경에 맞는 BASE_URL과 선택한 API 경로를 합쳐 POST 요청을 전송합니다.
  const res = http.post(`${BASE_URL}${endpoint}`);

  // 서버 응답이 HTTP 200인지 검사하고 결과를 k6 checks 통계에 기록합니다.
  check(res, {
    // 콜백의 r은 위에서 전송한 HTTP 요청의 응답 객체입니다.
    'status is 200': (r) => r.status === 200,
  });

  // 각 가상 사용자가 다음 요청을 보내기 전에 1초 동안 대기하도록 합니다.
  sleep(1);
}
