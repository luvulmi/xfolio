import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import type { Draft } from './api';

const session = { operator: { email: 'operator@example.invalid', display_name: '시험 운영자' }, mode: 'reviewed', csrf_token: 'test-csrf' };
function sample(overrides: Partial<Draft> = {}): Draft {
  return {
    id: 'edition-local-test', target_date: '2026-10-28', edition: 'PM', version: 2,
    decision_revision: 4, status: 'validated', news_count: 1, mode: 'reviewed', synthetic: false,
    validation: { status: 'passed', blocking_reasons: [] }, expires_at: '2099-10-28T09:10:00Z',
    posts: [{ position: 1, kind: 'news', text: '격리된 UI 시험 문안', evidence_ids: ['test-evidence'], evidence: [{ id: 'test-evidence', source: 'Fixture News', url: 'https://example.invalid/test', text: '허용 근거의 시험 발췌', claims: [{ subject: '가상기업', period: '2026-Q3' }] }] }],
    allowed_actions: ['approve', 'hold'], publication: { posts: [] }, ...overrides,
  };
}
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
function openApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  const view = render(<QueryClientProvider client={client}><App /></QueryClientProvider>);
  return { ...view, client };
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); location.hash = ''; });

describe('운영자 편성 검토', () => {
  it('401이면 데이터나 승인 UI 대신 Google 로그인으로 안내한다', async () => {
    const fetcher = vi.fn().mockResolvedValue(json({ error: { code: 'UNAUTHENTICATED' } }, 401));
    vi.stubGlobal('fetch', fetcher);
    openApp();
    expect(await screen.findByRole('link', { name: 'Google로 로그인' })).toHaveAttribute('href', '/api/auth/login');
    expect(screen.queryByRole('button', { name: '편성 전체 승인' })).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('빈 목록을 정상 수집으로 표시하지 않고 summary의 상태를 따로 보여준다', async () => {
    vi.stubGlobal('fetch', vi.fn(async (path: string) => {
      if (path === '/api/auth/me') return json(session);
      if (path.startsWith('/api/drafts?')) return json({ items: [], next_cursor: null });
      return json({ collection: { status: 'partial' }, alerts: { open: 1, failed: 0 } });
    }));
    openApp();
    expect(await screen.findByText('표시할 편성이 없습니다')).toBeInTheDocument();
    expect(screen.getByText('수집 불완전')).toBeInTheDocument();
    expect(screen.getByText(/빈 목록은 수집 성공을 뜻하지 않습니다/)).toBeInTheDocument();
  });

  it('synthetic 자료의 실제 승인 버튼을 차단한다', async () => {
    location.hash = '#/drafts/edition-local-test';
    vi.stubGlobal('fetch', vi.fn(async (path: string) => path === '/api/auth/me' ? json(session) : json(sample({ synthetic: true }))));
    openApp();
    expect(await screen.findByRole('button', { name: '편성 전체 승인' })).toBeDisabled();
    expect(screen.getByText('합성 시험 자료 · 실제 게시 예약 불가')).toBeInTheDocument();
  });

  it('backend per-post 근거와 게시 state를 표시하고 알림 미연결을 정상0건으로 숨기지 않는다', async () => {
    location.hash = '#/drafts/edition-local-test';
    vi.stubGlobal('fetch', vi.fn(async (path: string) => path === '/api/auth/me' ? json(session) : json(sample({ publication: { posts: [{ position: 1, state: 'unknown' }] } }))));
    openApp();
    expect(await screen.findByText('허용 근거의 시험 발췌')).toBeInTheDocument();
    expect(screen.getByText('글 1 · 결과 불명')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /원문 확인/ })).toHaveAttribute('href', 'https://example.invalid/test');
  });

  it('근거를 표시할 수 없으면 validation 통과 표시와 별개로 승인을 막는다', async () => {
    location.hash = '#/drafts/edition-local-test';
    vi.stubGlobal('fetch', vi.fn(async (path: string) => path === '/api/auth/me' ? json(session) : json(sample({ posts: [{ position: 1, kind: 'news', text: '근거 누락', evidence_ids: [] }] }))));
    openApp();
    expect(await screen.findByRole('button', { name: '편성 전체 승인' })).toBeDisabled();
  });

  it('현재 서버에 기록된 보류 사유를 새 입력과 구분해 표시한다', async () => {
    location.hash = '#/drafts/edition-local-test';
    vi.stubGlobal('fetch', vi.fn(async (path: string) => path === '/api/auth/me' ? json(session) : json(sample({ status: 'held', hold_reason: '기간과 비교 기준을 재확인해야 합니다.', allowed_actions: [] }))));
    openApp();
    expect(await screen.findByRole('heading', { name: '현재 보류 사유' })).toBeInTheDocument();
    expect(screen.getByText('기간과 비교 기준을 재확인해야 합니다.')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '보류 사유' })).toHaveValue('');
    expect(screen.getByRole('button', { name: '편성 전체 승인' })).toBeDisabled();
  });

  it('상세 조회 403을 권한 오류로 안내하고 이전 자료의 승인을 막는다', async () => {
    location.hash = '#/drafts/edition-local-test';
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async (path: string) => {
      if (path === '/api/auth/me') return json(session);
      calls += 1; return calls === 1 ? json(sample()) : json({ error: { code: 'OPERATOR_FORBIDDEN' } }, 403);
    }));
    openApp();
    await screen.findByRole('button', { name: '편성 전체 승인' });
    fireEvent.click(screen.getByRole('button', { name: /최신 상태 확인/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('조회 권한이 없습니다. 승인 동작을 차단했습니다.');
    expect(screen.getByRole('button', { name: '편성 전체 승인' })).toBeDisabled();
  });

  it('409 뒤 최신 버전만 재조회하며 자동으로 재승인하지 않는다', async () => {
    location.hash = '#/drafts/edition-local-test';
    let gets = 0; const mutations: RequestInit[] = [];
    vi.stubGlobal('fetch', vi.fn(async (path: string, options: RequestInit) => {
      if (path === '/api/auth/me') return json(session);
      if (path.endsWith('/decision')) { mutations.push(options); return json({ error: { code: 'VERSION_CONFLICT' } }, 409); }
      gets += 1;
      return json(sample(gets > 1 ? { version: 3, status: 'held', allowed_actions: [] } : {}));
    }));
    openApp();
    const approve = await screen.findByRole('button', { name: '편성 전체 승인' });
    fireEvent.click(approve);
    expect(await screen.findByText(/VERSION_CONFLICT/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: '편성 전체 승인' })).toBeDisabled());
    expect(mutations).toHaveLength(1);
    expect(JSON.parse(mutations[0].body as string)).toEqual({ action: 'approve', expected_version: 2, expected_decision_revision: 4 });
    expect(mutations[0].headers).toMatchObject({ 'X-CSRF-Token': 'test-csrf' });
  });

  it('결정 응답 불명 뒤 먼저 조회하고 명시적 재시도에 같은 키와 본문을 사용한다', async () => {
    location.hash = '#/drafts/edition-local-test';
    const mutations: RequestInit[] = []; const order: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (path: string, options: RequestInit) => {
      order.push(path);
      if (path === '/api/auth/me') return json(session);
      if (path.endsWith('/decision')) { mutations.push(options); if (mutations.length === 1) throw new TypeError('network unavailable'); return json({ status: 'scheduled' }); }
      return json(sample());
    }));
    openApp();
    fireEvent.click(await screen.findByRole('button', { name: '편성 전체 승인' }));
    const retry = await screen.findByRole('button', { name: '같은 요청 다시 확인' });
    await waitFor(() => expect(retry).toBeEnabled());
    expect(screen.getByRole('button', { name: '편성 전체 승인' })).toBeDisabled();
    fireEvent.click(retry);
    await waitFor(() => expect(mutations).toHaveLength(2));
    expect(mutations[0].body).toBe(mutations[1].body);
    expect(mutations[0].headers).toEqual(mutations[1].headers);
    const first = order.findIndex(path => path.endsWith('/decision'));
    expect(order[first + 1]).toBe('/api/drafts/edition-local-test');
  });

  it('최신 상세 조회에 실패하면 이전 데이터가 있어도 승인을 막는다', async () => {
    location.hash = '#/drafts/edition-local-test';
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async (path: string) => {
      if (path === '/api/auth/me') return json(session);
      calls += 1; return calls === 1 ? json(sample()) : json({ error: { code: 'UNAVAILABLE' } }, 503);
    }));
    openApp();
    await screen.findByRole('button', { name: '편성 전체 승인' });
    fireEvent.click(screen.getByRole('button', { name: /최신 상태 확인/ }));
    expect(await screen.findByText(/최신 확인 실패/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '편성 전체 승인' })).toBeDisabled();
  });
});
