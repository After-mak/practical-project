// 모든 신규 k6 시나리오에서 공통으로 사용하는 실행 설정입니다.
// BASE_URL을 지정하지 않으면 로컬 FastAPI 주소를 기본값으로 사용합니다.
export const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
export const LOAD_TEST_TOKEN = __ENV.LOAD_TEST_TOKEN || '';

// 일반적인 테스트의 공통 성공 기준입니다.
// HTTP 실패율 1% 미만, p95 응답 시간 500ms 미만, check 성공률 99% 초과를 요구합니다.
export const DEFAULT_THRESHOLDS = {
  http_req_failed: ['rate<0.01'],
  http_req_duration: ['p(95)<500'],
  checks: ['rate>0.99'],
};

// 숫자형 환경변수를 읽습니다. 값이 없거나 0 이하이면 안전한 기본값을 반환합니다.
export function numberEnv(name, fallback) {
  const value = Number(__ENV[name]);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

// 실행 시간처럼 k6 duration 형식을 사용하는 환경변수를 읽습니다.
export function durationEnv(name, fallback) {
  return __ENV[name] || fallback;
}

// Queue 등록 요청에서 JSON 본문을 전달하기 위한 공통 HTTP 헤더입니다.
export const TEST_HEADERS = {
  headers: LOAD_TEST_TOKEN ? { 'X-Test-Token': LOAD_TEST_TOKEN } : {},
};
export const JSON_HEADERS = {
  headers: {
    'Content-Type': 'application/json',
    ...(LOAD_TEST_TOKEN ? { 'X-Test-Token': LOAD_TEST_TOKEN } : {}),
  },
};
