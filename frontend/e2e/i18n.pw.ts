import { expect, test, type Page } from '@playwright/test';

const HAN = /[\u3400-\u9fff]/u;

async function mockBackend(page: Page) {
  await page.route('**/auth/config', (route) => route.fulfill({ json: { requireLogin: false } }));
  await page.route('**/user', (route) => route.fulfill({ status: 401, json: { detail: 'Unauthorized' } }));
  await page.route('**/api/platform/branding', (route) => route.fulfill({
    json: { platform_name: 'GIS Data Agent', platform_subtitle: 'Geospatial intelligence' },
  }));
  await page.route('**/api/config/basemaps', (route) => route.fulfill({
    json: {
      basemaps: [
        { name: '高德地图', tile_url: 'https://example.invalid/{z}/{x}/{y}.png' },
        { name: '天地图', tile_url: 'https://example.invalid/{z}/{x}/{y}.png' },
      ],
    },
  }));
  await page.route('**/api/workspace/navigation', (route) => route.fulfill({
    status: 401,
    json: { error: 'Unauthorized' },
  }));
  await page.route('https://**/*', (route) => route.abort());
}

test('login language switcher sets locale, direction, and persistence', async ({ page }) => {
  await mockBackend(page);
  await page.route('**/auth/config', (route) => route.fulfill({ json: { requireLogin: true } }));
  await page.goto('/');
  await page.locator('.login-card').waitFor();

  await page.locator('.language-switcher select').selectOption('en-US');
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US');
  await expect(page.locator('html')).toHaveAttribute('dir', 'ltr');
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();

  await page.locator('.language-switcher select').selectOption('ar-AE');
  await expect(page.locator('html')).toHaveAttribute('lang', 'ar-AE');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await expect(page.getByRole('heading', { name: 'مرحباً بعودتك' })).toBeVisible();
  await expect(page.evaluate(() => localStorage.getItem('gda.locale'))).resolves.toBe('ar-AE');
  await expect(page.context().cookies()).resolves.toEqual(expect.arrayContaining([
    expect.objectContaining({ name: 'gda.locale', value: 'ar-AE' }),
  ]));

  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('lang', 'ar-AE');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
});

test('workbench localizes navigation and provider aliases in English and Arabic', async ({ page }) => {
  await mockBackend(page);
  await page.goto('/');
  await page.locator('.app-container').waitFor();

  await page.locator('.language-switcher select').selectOption('en-US');
  await expect(page.locator('.data-panel-group').first()).toContainText('Data resources');
  await page.locator('.basemap-switcher-toggle').click();
  const englishMenu = await page.locator('.basemap-switcher-menu').innerText();
  expect(englishMenu).toContain('Gaode Maps');
  expect(englishMenu).toContain('Tianditu Vector');
  expect(englishMenu.split('\n').some((line) => HAN.test(line) && line.trim() !== '中文')).toBe(false);

  await page.locator('.language-switcher select').selectOption('ar-AE');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  const arabicMenu = await page.locator('.basemap-switcher-menu').innerText();
  expect(arabicMenu).toContain('خرائط غاوده');
  expect(arabicMenu).toContain('تيانديتو المتجهة');
  const arabicBody = await page.locator('body').innerText();
  expect(arabicBody.split('\n').some((line) => HAN.test(line) && line.trim() !== '中文')).toBe(false);
});
