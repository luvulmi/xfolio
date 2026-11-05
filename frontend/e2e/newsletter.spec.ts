import { expect, test } from '@playwright/test';

test('5메뉴에서설정중지와관심종목검색을수행한다', async ({ page }) => {
  let settings = { revision: 1, morning_enabled: true, paused: false, intraday_enabled: false, close_enabled: false };
  const watch = { revision: 1, codes: ['360750'], max_active: 10, items: [{ code: '360750', name: '시험 ETF', currency: 'KRW', market: 'KRX', eligible: true }] };
  const writes: unknown[] = [];
  await page.route('**/api/**', async route => {
    const req = route.request(); const url = new URL(req.url());
    if (url.pathname === '/api/auth/me') return route.fulfill({ json: { operator: '시험 운영자', csrf_token: 'csrf', mode: 'auto' } });
    if (url.pathname === '/api/newsletter-operations/summary') return route.fulfill({ json: { market_open: false, settings, watchlist: watch, newsletters: [] } });
    if (url.pathname === '/api/notification-settings') {
      if (req.method() === 'PATCH') { expect(req.headers()['x-csrf-token']).toBe('csrf'); writes.push(req.postDataJSON()); settings = { ...settings, paused: true, revision: 2 }; }
      return route.fulfill({ json: settings });
    }
    if (url.pathname === '/api/watchlist') return route.fulfill({ json: watch });
    if (url.pathname === '/api/instruments') return route.fulfill({ json: { items: watch.items } });
    return route.fulfill({ json: { items: [] } });
  });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '대시보드' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: '메뉴' }).getByRole('link')).toHaveCount(5);
  await expect(page.getByText('휴장 · 발송 없음')).toBeVisible();
  await page.getByRole('link', { name: '알림 설정', exact: true }).click();
  await page.getByRole('checkbox', { name: '전체 발송 일시 중지' }).click();
  await expect(page.getByText('현재 설정 v2')).toBeVisible();
  await expect(page.getByRole('checkbox', { name: '전체 발송 일시 중지' })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: /14:00/ })).toBeDisabled();
  expect(writes).toEqual([{ expected_revision: 1, paused: true }]);
  await page.getByRole('link', { name: '관심 종목', exact: true }).click();
  await page.getByRole('textbox', { name: '종목명 또는 코드' }).fill('360750');
  await page.getByRole('button', { name: '검색', exact: true }).click();
  await expect(page.getByRole('button', { name: '활성 종목', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '편성 전체 승인' })).toHaveCount(0);
  await page.screenshot({ path: 'test-results/newsletter-watchlist.png', fullPage: true });
});
