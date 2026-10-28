import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

const session = { operator: { email: 'operator@example.invalid', display_name: '격리 브라우저 시험' }, mode: 'reviewed', csrf_token: 'browser-test-csrf' };
const draft = {
  id: 'browser-test-edition', target_date: '2026-10-28', edition: 'PM', version: 2, decision_revision: 4,
  status: 'validated', news_count: 1, mode: 'reviewed', synthetic: false,
  scheduled_at: '2099-10-28T09:00:00Z', expires_at: '2099-10-28T09:10:00Z', frozen_at: '2099-10-28T08:45:00Z',
  validation: { status: 'passed', blocking_reasons: [] }, allowed_actions: ['approve', 'hold'],
  posts: [{ position: 1, kind: 'news', text: '격리된 브라우저에서만 사용하는 계약 시험 문안입니다.', evidence_ids: ['browser-evidence'], evidence: [{ id: 'browser-evidence', source: 'Fixture News', url: 'https://example.invalid/fixture', text: '시험 전용 합성 근거. 외부 게시 입력으로 사용할 수 없습니다.', published_at: '2099-10-28T06:00:00Z', collected_at: '2099-10-28T06:05:00Z' }] }],
  publication: { posts: [] },
};

async function mockReads(page: Page, getDraft = () => draft) {
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/auth/me') return route.fulfill({ json: session });
    if (url.pathname === '/api/operations/summary') return route.fulfill({ json: { collection: { status: 'complete' }, usage: { estimated_krw: 0, reserved_krw: 0, confirmed_krw: 0, monthly_limit_krw: 50_000 }, alerts: { status: 'not_implemented', open: 0, failed: 0 } } });
    if (url.pathname === '/api/drafts') return route.fulfill({ json: { items: [getDraft()], next_cursor: null } });
    if (url.pathname === '/api/drafts/browser-test-edition') return route.fulfill({ json: getDraft() });
    return route.fulfill({ status: 500, json: { error: { code: 'UNEXPECTED_TEST_ROUTE' } } });
  });
}

test('미인증은 Google 로그인으로 안내한다', async ({ page }) => {
  await page.route('**/api/**', route => route.fulfill({ status: 401, json: { error: { code: 'UNAUTHENTICATED' } } }));
  await page.goto('/');
  await expect(page.getByRole('link', { name: 'Google로 로그인' })).toHaveAttribute('href', '/api/auth/login');
  await expect(page.getByRole('button', { name: '편성 전체 승인' })).toHaveCount(0);
});

test('목록에서 상세 근거와 독립 글 구성을 확인한다', async ({ page }) => {
  await mockReads(page);
  await page.goto('/');
  await expect(page.getByText('알림 미연결')).toBeVisible();
  await page.getByRole('link', { name: '검토 →' }).click();
  await expect(page.getByText('사건별 독립 글')).toBeVisible();
  await expect(page.getByText('시험 전용 합성 근거. 외부 게시 입력으로 사용할 수 없습니다.')).toBeVisible();
  await expect(page.getByRole('button', { name: '편성 전체 승인' })).toBeEnabled();
  await page.screenshot({ path: 'test-results/review-detail.png', fullPage: true });
});

test('409 뒤 최신 버전은 표시하고 자동 재승인하지 않는다', async ({ page }) => {
  let changed = false; let mutations = 0;
  await mockReads(page, () => changed ? { ...draft, version: 3, status: 'held', allowed_actions: [] } : draft);
  await page.route('**/api/drafts/browser-test-edition/decision', async route => {
    mutations += 1; changed = true;
    expect(route.request().postDataJSON()).toEqual({ action: 'approve', expected_version: 2, expected_decision_revision: 4 });
    await route.fulfill({ status: 409, json: { error: { code: 'VERSION_CONFLICT' } } });
  });
  await page.goto('/#/drafts/browser-test-edition');
  await page.getByRole('button', { name: '편성 전체 승인' }).click();
  await expect(page.getByRole('alert')).toContainText('VERSION_CONFLICT');
  await expect(page.getByRole('button', { name: '편성 전체 승인' })).toBeDisabled();
  expect(mutations).toBe(1);
});

test('응답 불명은 최신 조회 후 동일한 키와 본문으로만 명시 재시도한다', async ({ page }) => {
  await mockReads(page);
  const attempts: { key: string | undefined; body: unknown }[] = [];
  await page.route('**/api/drafts/browser-test-edition/decision', async route => {
    attempts.push({ key: route.request().headers()['idempotency-key'], body: route.request().postDataJSON() });
    if (attempts.length === 1) return route.abort('failed');
    return route.fulfill({ json: { status: 'scheduled', replayed: true } });
  });
  await page.goto('/#/drafts/browser-test-edition');
  await page.getByRole('button', { name: '편성 전체 승인' }).click();
  await expect(page.getByRole('button', { name: '편성 전체 승인' })).toBeDisabled();
  await page.getByRole('button', { name: '같은 요청 다시 확인' }).click();
  await expect(page.getByRole('alert')).toContainText('결정 요청을 확인했습니다');
  expect(attempts).toHaveLength(2);
  expect(attempts[0]).toEqual(attempts[1]);
});
