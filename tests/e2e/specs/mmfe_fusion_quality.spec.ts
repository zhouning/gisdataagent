import { test, expect, type Page, type APIResponse } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const TARGET_URL = process.env.GIS_AGENT_E2E_URL || 'http://127.0.0.1:8000/';
const AUTH_CREDENTIALS = {
  username: process.env.GIS_AGENT_E2E_USER || 'admin',
  password: process.env.GIS_AGENT_E2E_PASSWORD || 'admin123',
};
const SCREENSHOT_DIR = process.env.GIS_AGENT_E2E_SCREENSHOT_DIR
  || path.resolve(__dirname, '../screenshots');

async function login(page: Page) {
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded' });
  await page.locator('#username').fill(AUTH_CREDENTIALS.username);
  await page.locator('#password').fill(AUTH_CREDENTIALS.password);
  await page.getByRole('button', { name: '登录' }).click();
  await expect(page.locator('.app-header')).toBeVisible({ timeout: 20000 });
}

test.describe('MMFE fusion quality panel', () => {
  test('shows real fusion operation and quality detail', async ({ page }) => {
    const operationResponses: APIResponse[] = [];
    const detailResponses: APIResponse[] = [];
    const readinessResponses: APIResponse[] = [];
    page.on('response', (response) => {
      if (response.url().includes('/api/fusion/operations')) {
        operationResponses.push(response);
      }
      if (response.url().includes('/api/fusion/quality/4')) {
        detailResponses.push(response);
      }
      if (response.url().includes('/api/fusion/mmfe/readiness')) {
        readinessResponses.push(response);
      }
    });

    await login(page);

    await page.locator('.data-panel-group', { hasText: '平台运营' }).click();
    await page.locator('.data-panel-tab', { hasText: '融合质量' }).click();

    await expect(page.getByRole('heading', { name: '融合质量监控' })).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole('heading', { name: 'MMFE 语义融合就绪' })).toBeVisible({ timeout: 10000 });
    await expect(page.locator('text=验证就绪 是')).toBeVisible();
    await expect(page.locator('text=生产就绪 否')).toBeVisible();
    await expect(page.locator('text=标准源')).toBeVisible();
    await expect(page.locator('text=值域审计')).toBeVisible();
    await expect(page.locator('text=语义图谱')).toBeVisible();
    await expect(page.locator('text=TWM 状态输入')).toBeVisible();

    const readiness = readinessResponses.at(-1);
    expect(readiness?.status()).toBe(200);
    const readinessPayload = await readiness!.json();
    expect(readinessPayload.summary.validation_ready).toBe(true);
    expect(readinessPayload.summary.production_ready).toBe(false);
    expect(readinessPayload.core_surfaces.some((item: { check_id: string; status: string }) => (
      item.check_id === 'semantic_graph' && item.status === 'pass'
    ))).toBeTruthy();

    await expect(page.locator('tbody tr', { hasText: '#4' })).toContainText('zonal_statistics', { timeout: 10000 });
    await expect(page.locator('tbody tr', { hasText: '#4' })).toContainText('0.65');

    const latestOps = operationResponses.at(-1);
    expect(latestOps?.status()).toBe(200);
    const operationsPayload = await latestOps!.json();
    expect(operationsPayload.items.some((item: { id: number; strategy: string }) => (
      item.id === 4 && item.strategy === 'zonal_statistics'
    ))).toBeTruthy();

    await page.locator('tbody tr', { hasText: '#4' }).click();
    await expect(page.getByRole('heading', { name: '操作 #4 详情' })).toBeVisible({ timeout: 10000 });
    await expect(page.locator('text=质量分数:')).toBeVisible();
    await expect(page.locator('text=0.6500')).toBeVisible();
    await expect(page.locator('text=可解释性元数据:')).toBeVisible();

    const detail = detailResponses.at(-1);
    expect(detail?.status()).toBe(200);
    const detailPayload = await detail!.json();
    expect(detailPayload.operation_id).toBe(4);
    expect(detailPayload.quality_score).toBe(0.65);
    expect(detailPayload.explainability.explainability_path).toContain('fusion_quality_heatmap_bdda2263.geojson');

    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'mmfe_fusion_quality_e2e.png'),
      fullPage: true,
    });
  });
});
