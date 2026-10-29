import { expect, test } from '@playwright/test';

test('실제 HTTPS·FastAPI·PostgreSQL 세션으로 조회·합성 차단·보류·로그아웃한다', async ({ page, context, baseURL }) => {
  const requests: string[] = [];
  page.on('request', request => requests.push(request.url()));
  await page.goto('/');
  await expect(page.getByRole('link', { name: 'Google로 로그인' })).toBeVisible();
  await page.getByRole('link', { name: 'Google로 로그인' }).click();
  await expect(page.getByRole('heading', { name: '편성 검토' })).toBeVisible();
  await expect(page.getByText('격리 PostgreSQL 브라우저 시험')).toBeVisible();
  const cookies = await context.cookies();
  const sessionCookie = cookies.find(cookie => cookie.name === 'xfolio_session');
  expect(sessionCookie).toMatchObject({ secure: true, httpOnly: true, sameSite: 'Lax', path: '/api' });
  expect(cookies.find(cookie => cookie.name === 'xfolio_oidc_flow')).toBeUndefined();
  await page.locator('a[href="#/drafts/browser-pm"]').click();
  await expect(page.getByText('합성 시험 자료 · 실제 게시 예약 불가')).toBeVisible();
  await expect(page.getByRole('button', { name: '편성 전체 승인' })).toBeDisabled();
  await expect(page.getByText('표시 가능한 상세 근거가 없습니다. 연결 근거와 검증 결과를 확인하세요.')).toBeVisible();

  const me = await (await page.request.get('/api/auth/me')).json();
  const detail = await (await page.request.get('/api/drafts/browser-pm')).json();
  const body = { action: 'approve', expected_version: detail.version, expected_decision_revision: detail.decision_revision };
  const blocked = await page.request.post('/api/drafts/browser-pm/decision', {
    headers: { Origin: baseURL!, 'X-CSRF-Token': me.csrf_token, 'Idempotency-Key': 'live-synthetic-approve' }, data: body,
  });
  expect(blocked.status()).toBe(409);
  expect((await blocked.json()).error.code).toBe('MODE_BLOCKED');
  const missingCsrf = await page.request.post('/api/drafts/browser-pm/decision', {
    headers: { Origin: baseURL!, 'Idempotency-Key': 'live-csrf-reject' },
    data: { action: 'hold', expected_version: detail.version, expected_decision_revision: detail.decision_revision, reason: '보류 시험' },
  });
  expect(missingCsrf.status()).toBe(403);
  const wrongOrigin = await page.request.post('/api/drafts/browser-pm/decision', {
    headers: { Origin: 'https://evil.invalid', 'X-CSRF-Token': me.csrf_token, 'Idempotency-Key': 'live-origin-reject' },
    data: { action: 'hold', expected_version: detail.version, expected_decision_revision: detail.decision_revision, reason: '보류 시험' },
  });
  expect(wrongOrigin.status()).toBe(403);

  await page.getByRole('textbox', { name: '보류 사유' }).fill('합성 자료이며 실뉴스 권한 확인 전입니다.');
  const holdResponse = page.waitForResponse(response => response.url().endsWith('/api/drafts/browser-pm/decision') && response.request().method() === 'POST');
  await page.getByRole('button', { name: '보류', exact: true }).click();
  expect((await holdResponse).status()).toBe(200);
  await expect(page.getByText('보류된 버전은 다시 승인할 수 없습니다. CLI에서 새 버전을 만들고 검증한 뒤 재승인하세요.')).toBeVisible();
  await expect(page.getByRole('heading', { name: '현재 보류 사유' })).toBeVisible();
  await expect(page.locator('.hold-reason p')).toHaveText('합성 자료이며 실뉴스 권한 확인 전입니다.');
  const held = await (await page.request.get('/api/drafts/browser-pm')).json();
  expect(held.status).toBe('held');
  expect(held.decision_revision).toBe(detail.decision_revision + 1);
  expect(held.hold_reason).toBe('합성 자료이며 실뉴스 권한 확인 전입니다.');
  expect(held.publication.posts).toEqual([]);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: 'test-results/live-api-held.png', fullPage: true });

  await page.getByRole('button', { name: '로그아웃' }).click();
  await expect(page.getByRole('link', { name: 'Google로 로그인' })).toBeVisible();
  expect((await page.request.get('/api/auth/me')).status()).toBe(401);
  expect((await context.cookies()).find(cookie => cookie.name === 'xfolio_session')).toBeUndefined();
  expect(requests.every(url => url.startsWith(baseURL!))).toBe(true);
});

test('생성·의미·길이 검사를 거친 CPI 편성을 실제 API에서 승인하고 철회한다', async ({ page, baseURL }) => {
  // API와 브라우저 시각만 시험용 17:50으로 맞춘다. 외부 게시 도구는 없다.
  const day = new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' });
  await page.clock.install({ time: new Date(`${day}T17:50:00+09:00`) });
  const requests: string[] = [];
  page.on('request', request => requests.push(request.url()));
  await page.goto('/');
  await page.getByRole('link', { name: 'Google로 로그인' }).click();
  await expect(page.getByRole('heading', { name: '편성 검토' })).toBeVisible();
  const listing = await (await page.request.get('/api/drafts')).json();
  const candidate = listing.items.find((row: { id: string }) => row.id !== 'browser-pm');
  expect(candidate).toBeDefined();
  await page.goto(`/#/drafts/${candidate.id}`);
  await expect(page.getByText('검증: 통과')).toBeVisible();
  await expect(page.locator('.post-heading small')).toHaveText(/\d+ \/ 280/);
  await expect(page.locator('.post-text')).toContainText('발표일(미국 동부)');
  await expect(page.locator('.evidence-panel')).toContainText('BLS');
  const approve = page.getByRole('button', { name: '편성 전체 승인' });
  await expect(approve).toBeEnabled();
  const approvedResponse = page.waitForResponse(response => response.url().endsWith(`/api/drafts/${candidate.id}/decision`) && response.request().method() === 'POST');
  await approve.click();
  expect((await approvedResponse).status()).toBe(200);
  await expect(page.getByRole('button', { name: '승인 철회·보류' })).toBeVisible();
  const scheduled = await (await page.request.get(`/api/drafts/${candidate.id}`)).json();
  expect(scheduled.status).toBe('scheduled');
  expect(scheduled.publication.posts).toMatchObject([{ state: 'reserved', x_id: null }]);
  await page.reload();
  await expect(page.getByRole('button', { name: '승인 철회·보류' })).toBeVisible();
  await page.screenshot({ path: 'test-results/live-api-cpi-approved.png', fullPage: true });
  await page.getByRole('textbox', { name: '보류 사유' }).fill('정상 승인 후 철회 시험');
  await expect(page.getByRole('button', { name: '승인 철회·보류' })).toBeEnabled();
  await page.getByRole('button', { name: '승인 철회·보류' }).click();
  await expect(page.getByRole('heading', { name: '현재 보류 사유' })).toBeVisible();
  const held = await (await page.request.get(`/api/drafts/${candidate.id}`)).json();
  expect(held.status).toBe('held');
  expect(held.publication.posts).toMatchObject([{ state: 'cancelled', x_id: null }]);
  expect(requests.every(url => url.startsWith(baseURL!))).toBe(true);
});
