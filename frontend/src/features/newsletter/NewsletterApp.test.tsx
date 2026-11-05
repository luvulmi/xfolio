import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { App } from '../../app/App';
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const session = { operator: { email: 'owner@example.invalid' }, mode: 'auto', csrf_token: 'test-csrf' };
const settings = { revision: 1, morning_enabled: true, paused: false, intraday_enabled: false, close_enabled: false };
function mount() { const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); return render(<QueryClientProvider client={client}><App /></QueryClientProvider>); }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); location.hash = ''; });

it('기본화면은5메뉴·휴장 미발송과 미관측 상태를 표시한다', async () => {
  vi.stubGlobal('fetch', vi.fn(async (path: string) => path === '/api/auth/me' ? json(session) : json({ market_open: false, settings, watchlist: { codes: ['360750'] }, newsletters: [] })));
  mount(); await screen.findByRole('heading', { name: '대시보드' });
  expect(screen.getByRole('navigation', { name: '메뉴' }).querySelectorAll('a')).toHaveLength(5);
  expect(await screen.findByText('휴장 · 발송 없음')).toBeInTheDocument();
  expect(screen.getByText(/원장 기록 없음은 실비 0원을 뜻하지/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '편성 전체 승인' })).not.toBeInTheDocument();
});

it('대시보드는원장상태·가격시각·뉴스실패·실제송신불명을DB응답대로표시한다', async () => {
  const body = { market_open: true, settings, watchlist: { codes: ['360750'] }, newsletters: [],
    budget: { status: 'over_limit', month: '2026-11', confirmed_krw: '800', reserved_krw: '300', estimated_krw: '100', committed_krw: '1200', remaining_krw: '0', limit_krw: '1000', record_count: 3, limit_source: 'server_configuration' },
    price_freshness: { status: 'attention', provenance: 'live', expected_trade_date: '2026-11-04', comparison_trade_date: '2026-11-03', items: [{ code: '360750', status: 'superseded', provenance: 'live', trade_date: '2026-11-04', price_as_of: null, retrieved_at: '2026-11-05T07:51:00+09:00', scheduled_close: '2026-11-04T15:30:00+09:00', version: 1, change_available: false }] },
    news_collection: { status: 'partial', current: true, as_of: '2026-11-05T07:50:00+09:00', selected_count: 1, retained_selected_count: 1, synthetic: false, provenance: 'live', sources: [{ provider: 'Finnhub', status: 'failed', errors: ['request_budget_exhausted'] }] },
    deliveries: { status: 'observed', attention: [{ id: 'd1' }], recent: [{ id: 'd1', target_date: '2026-11-05', slot: 'morning', status: 'unknown', transport_mode: 'live', updated_at: '2026-11-05T08:00:00+09:00' }] },
    worker: { status: 'skipped', reason: 'market_closed', recorded_at: '2026-11-05T08:00:00+09:00' } };
  vi.stubGlobal('fetch', vi.fn(async (path: string) => path === '/api/auth/me' ? json(session) : json(body)));
  mount(); expect(await screen.findByText('예산 초과')).toBeInTheDocument();
  expect(screen.getByText('800원')).toBeInTheDocument();
  expect(screen.getByText('최신 정정으로 대체됨')).toBeInTheDocument();
  expect(screen.getByText('미제공')).toBeInTheDocument();
  expect(screen.getByText(/제공 지연 미측정/)).toBeInTheDocument();
  expect(screen.getByText(/Finnhub · 실패 request_budget_exhausted/)).toBeInTheDocument();
  expect(screen.getByText('결과 불명')).toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('확인이 필요한 발송 1건');
  expect(screen.getByRole('link', { name: '2026-11-05 · morning' })).toHaveAttribute('href', '#/deliveries/d1');
});

it('08시전준비진행상태를발송단계와구분해표시한다', async () => {
  vi.stubGlobal('fetch', vi.fn(async (path: string) => path === '/api/auth/me' ? json(session) : json({ market_open: true, settings, watchlist: { codes: ['360750'] }, newsletters: [], worker: { stage: 'preparation', status: 'running', reason: null, recorded_at: '2026-11-05T07:50:00+09:00' } })));
  mount();
  expect(await screen.findByText(/준비·수집 진행 중/)).toBeInTheDocument();
  expect(screen.queryByText(/발송 worker/)).not.toBeInTheDocument();
});

it('대시보드재조회실패시이전상태를정상으로유지하지않는다', async () => {
  let calls = 0;
  vi.stubGlobal('fetch', vi.fn(async (path: string) => {
    if (path === '/api/auth/me') return json(session);
    calls++; return calls === 1 ? json({ market_open: true, settings, watchlist: { codes: ['360750'] }, newsletters: [] }) : json({ error: { code: 'STORAGE_UNAVAILABLE' } }, 503);
  }));
  mount(); await screen.findByText('아침 활성');
  fireEvent.click(screen.getByRole('button', { name: '최신 상태 확인' }));
  await screen.findByRole('alert');
  expect(screen.queryByText('아침 활성')).not.toBeInTheDocument();
});

it('설정 변경에 현재revision과CSRF를 보내고 오후는 비활성화한다', async () => {
  location.hash = '#/settings'; let value = { ...settings }; const changes: RequestInit[] = [];
  vi.stubGlobal('fetch', vi.fn(async (path: string, options: RequestInit) => {
    if (path === '/api/auth/me') return json(session);
    if (options?.method === 'PATCH') { changes.push(options); value = { ...value, paused: true, revision: 2 }; return json(value); }
    return json(value);
  }));
  mount(); const pause = await screen.findByRole('checkbox', { name: '전체 발송 일시 중지' });
  expect(screen.getByRole('checkbox', { name: /14:00/ })).toBeDisabled();
  expect(screen.getByRole('checkbox', { name: /16:00/ })).toBeDisabled();
  await waitFor(() => expect(pause).toBeEnabled()); fireEvent.click(pause);
  await screen.findByText('설정을 저장했습니다.');
  expect(changes).toHaveLength(1);
  expect(JSON.parse(changes[0].body as string)).toEqual({ expected_revision: 1, paused: true });
  expect(changes[0].headers).toMatchObject({ 'X-CSRF-Token': 'test-csrf' });
  expect(await screen.findByText('현재 설정 v2')).toBeInTheDocument();
});

it('설정409는자동재시도하지않고최신revision을조회한다', async () => {
  location.hash = '#/settings'; let changed = false; let calls = 0;
  vi.stubGlobal('fetch', vi.fn(async (path: string, options: RequestInit) => {
    if (path === '/api/auth/me') return json(session);
    if (options?.method === 'PATCH') { calls++; changed = true; return json({ error: { code: 'REVISION_CONFLICT' } }, 409); }
    return json({ ...settings, revision: changed ? 3 : 1 });
  }));
  mount(); const pause = await screen.findByRole('checkbox', { name: '전체 발송 일시 중지' });
  await waitFor(() => expect(pause).toBeEnabled()); fireEvent.click(pause);
  expect(await screen.findByRole('alert')).toHaveTextContent('REVISION_CONFLICT');
  expect(await screen.findByText('현재 설정 v3')).toBeInTheDocument(); expect(calls).toBe(1);
});

it('발송이력미연결을정상0건으로표시하지않는다', async () => {
  location.hash = '#/deliveries';
  vi.stubGlobal('fetch', vi.fn(async (path: string) => path === '/api/auth/me' ? json(session) : json({ error: { code: 'DELIVERIES_NOT_CONNECTED' } }, 503)));
  mount(); expect(await screen.findByRole('alert')).toHaveTextContent('자동 전송 기능 연결 후');
  expect(screen.queryByText('발송 기록이 없습니다. 전송 성공을 뜻하지 않습니다.')).not.toBeInTheDocument();
});

it('관심종목순서변경은기존revision과CSRF로저장한다', async () => {
  location.hash = '#/watchlist'; const writes: RequestInit[] = [];
  const watch = { revision: 2, codes: ['360750', '379810'], max_active: 10, items: [{ code: '360750', name: 'ETF A', currency: 'KRW' }, { code: '379810', name: 'ETF B', currency: 'KRW' }] };
  vi.stubGlobal('fetch', vi.fn(async (path: string, options: RequestInit) => { if (path === '/api/auth/me') return json(session); if (options?.method === 'PUT') writes.push(options); return json(watch); }));
  mount(); const down = await screen.findByRole('button', { name: 'ETF A 아래로' });
  await waitFor(() => expect(down).toBeEnabled()); fireEvent.click(down);
  await screen.findByText('관심 종목을 저장했습니다.');
  expect(JSON.parse(writes[0].body as string)).toEqual({ expected_revision: 2, codes: ['379810', '360750'] });
  expect(writes[0].headers).toMatchObject({ 'X-CSRF-Token': 'test-csrf' });
});
