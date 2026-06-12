import { test, expect } from '@playwright/test';

test('test', async ({ page }) => {
  const targetUrl = process.env.GIS_AGENT_E2E_URL || 'http://127.0.0.1:8000/';
  const username = process.env.GIS_AGENT_E2E_USER || 'admin';
  const password = process.env.GIS_AGENT_E2E_PASSWORD || 'admin';

  await page.goto(targetUrl);
  await page.getByRole('textbox', { name: '用户名' }).click();
  await page.getByRole('textbox', { name: '用户名' }).fill(username);
  await page.getByRole('textbox', { name: '用户名' }).press('Tab');
  await page.getByRole('textbox', { name: '密码' }).fill(password);
  await page.getByRole('textbox', { name: '密码' }).press('Enter');
  await page.getByRole('button', { name: '登录' }).click();
});
