import { expect, test } from '@playwright/test';

test('실제 HTTPS·API·DB로 준비·발송 결과와 비용을 조회하고 중지한다', async ({ page, baseURL }) => {
  const requests: string[] = [];
  page.on('request', request => requests.push(request.url()));
  await page.goto('/');
  await page.getByRole('link', { name: 'Google로 로그인' }).click();
  await page.waitForURL(url => url.pathname === '/' && !url.search);
  await expect(page.getByRole('heading', { name: '대시보드', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '이번 달 비용' })).toBeVisible();
  await expect(page.getByText('기준 거래일 일치', { exact: true }).first()).toBeVisible();
  const summary = await (await page.request.get('/api/newsletter-operations/summary')).json();
  expect(summary.budget.record_count).toBe(1);
  expect(summary.price_freshness.status).toBe('current');
  expect(summary.news_collection.selected_count).toBe(3);
  expect(summary.deliveries.recent[0].status).toBe('confirmed');
  await page.screenshot({ path: 'test-results/t07-dashboard.png', fullPage: true });

  await page.getByRole('link', { name: '뉴스레터', exact: true }).click();
  const newsletter = await (await page.request.get('/api/newsletters')).json();
  await page.goto(`/#/newsletters/${newsletter.items[0].id}`);
  await expect(page.locator('pre')).toContainText('XFolio 아침 뉴스레터');
  await expect(page.locator('pre')).toContainText('360750');

  await page.goto(`/#/deliveries/${summary.deliveries.recent[0].id}`);
  await expect(page.getByRole('heading', { name: '발송 상세' })).toBeVisible();
  await expect(page.getByText('전송 확인', { exact: true }).first()).toBeVisible();
  await page.goto('/#/settings');
  const pause = page.getByRole('checkbox', { name: '전체 발송 일시 중지' });
  const saved = page.waitForResponse(response =>
    response.url().endsWith('/api/notification-settings') && response.request().method() === 'PATCH',
  );
  await pause.click();
  expect((await saved).status()).toBe(200);
  await expect(pause).toBeChecked();
  await expect(page.getByRole('status')).toContainText('저장');
  expect((await (await page.request.get('/api/notification-settings')).json()).paused).toBe(true);
  await page.goto('/#/');
  await expect(page.getByText('전체 일시 중지', { exact: true })).toBeVisible();
  expect(requests.every(url => url.startsWith(baseURL!))).toBe(true);
});
