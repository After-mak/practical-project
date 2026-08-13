import http from 'k6/http';
import { check } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const REQUIRED_ENV = ['BASE_URL', 'RUN_ID', 'PHASE', 'SCENARIO_NAME', 'TEST_USERNAME', 'TEST_PASSWORD'];
const RUN_PHASES = new Set(['pre', 'post', 'smoke', 'pilot']);
const PROFILE = (__ENV.PROFILE || (__ENV.PHASE === 'smoke' ? 'smoke' : 'long')).toLowerCase();
const TIME_SCALE = numberEnv('TIME_SCALE', 1, 0.001);
const CYCLES = integerEnv('CYCLES', 1, 1);
const LOW_RPS = integerEnv('LOW_RPS', 1, 1);
const NORMAL_RPS = integerEnv('NORMAL_RPS', 10, 1);
const PEAK_RPS = integerEnv('PEAK_RPS', 25, 1);
const SPIKE_RPS = integerEnv('SPIKE_RPS', 40, 1);
const RECOVERY_RPS = integerEnv('RECOVERY_RPS', 3, 1);
const MAX_VUS = integerEnv('MAX_VUS', Math.max(100, SPIKE_RPS * 4), SPIKE_RPS);
const PAYMENT_PERCENT = numberEnv('PAYMENT_PERCENT', 0, 0, 100);
const PAYMENT_AMOUNT = __ENV.PAYMENT_AMOUNT || '0.01';
const BASE_URL = (__ENV.BASE_URL || '').replace(/\/$/, '');

validateEnvironment();

const offeredFlows = new Counter('boa_offered_flows');
const offeredRequests = new Counter('boa_offered_requests');
const successfulRequests = new Counter('boa_successful_requests');
const systemFailures = new Counter('boa_system_failures');
const businessFailures = new Counter('boa_business_failures');
const intentional4xx = new Counter('boa_intentional_4xx');
const flowSuccess = new Rate('boa_flow_success');
const e2eLatency = new Trend('boa_e2e_latency_ms', true);

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  discardResponseBodies: false,
  scenarios: buildScenarios(),
  tags: {
    run_id: __ENV.RUN_ID,
    phase: __ENV.PHASE,
    scenario: __ENV.SCENARIO_NAME,
    version: __ENV.SCENARIO_VERSION || 'v1',
  },
};

function numberEnv(name, fallback, min, max = Number.POSITIVE_INFINITY) {
  const raw = __ENV[name];
  const value = raw === undefined || raw === '' ? fallback : Number(raw);
  if (!Number.isFinite(value) || value < min || value > max) {
    throw new Error(`${name} must be between ${min} and ${max}; got '${raw}'`);
  }
  return value;
}

function integerEnv(name, fallback, min, max = Number.POSITIVE_INFINITY) {
  const value = numberEnv(name, fallback, min, max);
  if (!Number.isInteger(value)) {
    throw new Error(`${name} must be an integer; got '${value}'`);
  }
  return value;
}

function validateEnvironment() {
  const missing = REQUIRED_ENV.filter((name) => !__ENV[name]);
  if (missing.length > 0) {
    throw new Error(`missing required environment variables: ${missing.join(', ')}`);
  }
  if (!RUN_PHASES.has(__ENV.PHASE)) {
    throw new Error(`PHASE must be one of ${Array.from(RUN_PHASES).join(', ')}`);
  }
  if (!['smoke', 'long'].includes(PROFILE)) {
    throw new Error(`PROFILE must be smoke or long; got '${PROFILE}'`);
  }
  if (NORMAL_RPS < LOW_RPS || PEAK_RPS < NORMAL_RPS || SPIKE_RPS < PEAK_RPS) {
    throw new Error('RPS values must satisfy LOW <= NORMAL <= PEAK <= SPIKE');
  }
  if (PAYMENT_PERCENT > 0 && !__ENV.TEST_RECIPIENT_ACCOUNT) {
    throw new Error('TEST_RECIPIENT_ACCOUNT is required when PAYMENT_PERCENT is greater than zero');
  }
}

function seconds(baseSeconds) {
  return Math.max(1, Math.round(baseSeconds * TIME_SCALE));
}

function duration(baseSeconds) {
  return `${seconds(baseSeconds)}s`;
}

function scenario(name, startSeconds, executor, rate, baseDuration, extra = {}) {
  const peakRate = extra.targetRate ? Math.max(rate, extra.targetRate) : rate;
  const definition = {
    executor,
    exec: 'bankFlow',
    startTime: `${startSeconds}s`,
    timeUnit: '1s',
    preAllocatedVUs: Math.min(MAX_VUS, Math.max(10, Math.ceil(peakRate * 1.5))),
    maxVUs: MAX_VUS,
    tags: { traffic_phase: name },
  };
  if (executor === 'ramping-arrival-rate') {
    definition.startRate = rate;
    definition.stages = [{ target: extra.targetRate, duration: duration(baseDuration) }];
  } else {
    definition.rate = rate;
    definition.duration = duration(baseDuration);
  }
  return definition;
}

export function buildScenarios() {
  const phases = PROFILE === 'smoke'
    ? [
        ['low', 'constant-arrival-rate', LOW_RPS, 300],
        ['normal', 'constant-arrival-rate', NORMAL_RPS, 600],
        ['peak', 'constant-arrival-rate', PEAK_RPS, 300],
        ['spike', 'constant-arrival-rate', SPIKE_RPS, 300],
        ['recovery', 'constant-arrival-rate', RECOVERY_RPS, 300],
      ]
    : [
        ['low', 'constant-arrival-rate', LOW_RPS, 600],
        ['ramp_up', 'ramping-arrival-rate', LOW_RPS, 900, NORMAL_RPS],
        ['normal', 'constant-arrival-rate', NORMAL_RPS, 1200],
        ['peak', 'constant-arrival-rate', PEAK_RPS, 600],
        ['spike', 'constant-arrival-rate', SPIKE_RPS, 300],
        ['ramp_down', 'ramping-arrival-rate', PEAK_RPS, 600, RECOVERY_RPS],
        ['recovery', 'constant-arrival-rate', RECOVERY_RPS, 600],
      ];

  const scenarios = {};
  let offset = 0;
  for (let cycle = 1; cycle <= CYCLES; cycle += 1) {
    for (const [name, executorName, rate, baseDuration, targetRate] of phases) {
      const key = `cycle_${cycle}_${name}`;
      scenarios[key] = scenario(name, offset, executorName, rate, baseDuration, { targetRate });
      offset += seconds(baseDuration);
    }
  }
  return scenarios;
}

function request(method, path, body, params, flow, classify4xx = "business") {
  offeredRequests.add(1, { flow });
  const response = http.request(method, `${BASE_URL}${path}`, body, {
    ...params,
    tags: { ...(params && params.tags ? params.tags : {}), flow },
  });

  if (response.status === 0 || response.status >= 500) {
    systemFailures.add(1, { flow, status: String(response.status) });
  } else if (response.status >= 400 && classify4xx === 'intentional') {
    intentional4xx.add(1, { flow, status: String(response.status) });
  } else if (response.status >= 400) {
    businessFailures.add(1, { flow, status: String(response.status) });
  } else {
    successfulRequests.add(1, { flow, status: String(response.status) });
  }
  return response;
}

function login() {
  const response = request(
    'POST',
    '/login',
    { username: __ENV.TEST_USERNAME, password: __ENV.TEST_PASSWORD },
    { redirects: 0 },
    'login',
  );
  const ok = check(response, {
    'login redirects to home': (r) => r.status === 302 && (r.headers.Location || '').includes('/home'),
    'login returns token cookie': () => Boolean(http.cookieJar().cookiesForURL(BASE_URL).token),
  });
  if (!ok) {
    businessFailures.add(1, { flow: 'login_validation' });
  }
  return ok;
}

function ensureAuthenticated() {
  if (http.cookieJar().cookiesForURL(BASE_URL).token) {
    return true;
  }
  return login();
}

function uuidV4() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const random = Math.random() * 16 | 0;
    const value = char === 'x' ? random : (random & 0x3 | 0x8);
    return value.toString(16);
  });
}

function overview() {
  let response = request('GET', '/home', null, { redirects: 0 }, 'overview');
  if (response.status === 302 && (response.headers.Location || '').includes('/login')) {
    http.cookieJar().clear(BASE_URL);
    if (!login()) return false;
    response = request('GET', '/home', null, { redirects: 0 }, 'overview_retry');
  }
  e2eLatency.add(response.timings.duration, { flow: 'overview' });
  const ok = check(response, {
    'overview status is 200': (r) => r.status === 200,
    'balance is rendered': (r) => r.body && r.body.includes('Current Balance'),
    'transaction history is rendered': (r) => r.body && r.body.includes('Transaction History'),
    'backend data has no render error': (r) => r.body && !r.body.includes('Could Not Load'),
  });
  if (!ok && response.status < 500) {
    businessFailures.add(1, { flow: 'overview_validation' });
  }
  return ok;
}
function payment() {
  const response = request(
    'POST',
    '/payment',
    {
      account_num: __ENV.TEST_RECIPIENT_ACCOUNT,
      amount: PAYMENT_AMOUNT,
      uuid: uuidV4(),
    },
    { redirects: 0 },
    'payment',
    'intentional',
  );
  const ok = check(response, {
    'payment redirects after accepted request': (r) => r.status === 303,
    'payment success location returned': (r) => (r.headers.Location || '').includes('Payment+successful'),
  });
  if (!ok && response.status < 400) {
    businessFailures.add(1, { flow: 'payment_validation' });
  }
  return ok;
}

export function bankFlow() {
  offeredFlows.add(1, { flow: 'bank_flow' });
  const started = Date.now();
  let ok = ensureAuthenticated() && overview();
  if (ok && PAYMENT_PERCENT > 0 && Math.random() * 100 < PAYMENT_PERCENT) {
    ok = payment() && overview();
  }
  e2eLatency.add(Date.now() - started, { flow: 'bank_flow' });
  flowSuccess.add(ok, { flow: 'bank_flow' });
}

function scenarioSchedule() {
  return Object.entries(options.scenarios).map(([name, item]) => ({
    name,
    traffic_phase: item.tags.traffic_phase,
    start_time: item.startTime,
    duration: item.duration || item.stages.map((stage) => stage.duration).join('+'),
    rate: item.rate || item.startRate,
    target_rate: item.stages ? item.stages[item.stages.length - 1].target : item.rate,
  }));
}

export function handleSummary(data) {
  const summary = {
    schema_version: '1.0',
    run_id: __ENV.RUN_ID,
    phase: __ENV.PHASE,
    scenario: __ENV.SCENARIO_NAME,
    scenario_version: __ENV.SCENARIO_VERSION || 'v1',
    profile: PROFILE,
    time_scale: TIME_SCALE,
    cycles: CYCLES,
    scenario_schedule: scenarioSchedule(),
    finished_at: new Date().toISOString(),
    metrics: data.metrics,
  };
  const rendered = `${JSON.stringify(summary, null, 2)}\n`;
  return { stdout: rendered, '/results/summary.json': rendered };
}
