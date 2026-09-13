import { test, expect, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const SCREENSHOT_DIR = path.resolve(__dirname, '../screenshots/twm-executive-demo');

async function login(page: Page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.locator('#username').fill(process.env.GIS_AGENT_E2E_USERNAME || 'admin');
  await page.locator('#password').fill(process.env.GIS_AGENT_E2E_PASSWORD || 'admin123');
  await page.getByRole('button', { name: '登录' }).click();
  await expect(page.locator('.app-header')).toBeVisible({ timeout: 30_000 });
}

async function openTwm(page: Page) {
  await page.locator('.data-panel-group', { hasText: '智能分析' }).click();
  await page.locator('.data-panel-tab', { hasText: 'TWM' }).click();
  await expect(page.locator('.twm-title')).toContainText('国土空间世界模型', { timeout: 30_000 });
  await expect(page.getByRole('tab', { name: '汇报演示' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('[data-testid="twm-executive-demo"]')).toBeVisible({ timeout: 30_000 });
}

async function expectNoBriefingOverflow(page: Page) {
  const overflows = await page.locator('[data-testid="twm-executive-demo"]').evaluate((root) => {
    const rootRect = root.getBoundingClientRect();
    return Array.from(root.querySelectorAll<HTMLElement>(':scope > *'))
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return rect.left < rootRect.left - 2 || rect.right > rootRect.right + 2;
      })
      .map((element) => ({ className: element.className, rect: element.getBoundingClientRect().toJSON() }));
  });
  expect(overflows).toEqual([]);
}

test('presents an evidence-gated TWM briefing and keeps detailed workspaces reachable', async ({ page }) => {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  page.on('pageerror', error => pageErrors.push(error.message));

  await login(page);
  const reportResponsePromise = page.waitForResponse(response => response.url().includes('/api/twm/executive-demo-report'));
  await openTwm(page);
  const reportResponse = await reportResponsePromise;
  expect(reportResponse.status()).toBe(200);
  const report = await reportResponse.json();
  expect(report.status).toBe('controlled_demo_ready');
  expect(report.positioning.production_claim_supported).toBe(false);

  const briefing = page.locator('[data-testid="twm-executive-demo"]');
  await expect(briefing).toContainText('受控演示就绪，生产效果尚未验证');
  await expect(briefing).toContainText('生产主张未开放');
  await expect(briefing).toContainText('GWM 在世界模型谱系中的位置');
  await expect(page.locator('[data-testid="twm-gwm-definition"]')).toContainText('不是给通用世界模型追加经纬度特征');
  await expect(page.locator('[data-testid="twm-gwm-definition"]')).toContainText('对象 + 场 + CRS');
  await expect(page.locator('[data-testid="twm-simulator-mechanism"]')).toContainText('组合式状态转移与写回协议');
  await expect(page.locator('[data-testid="twm-simulator-mechanism"]')).toContainText('状态写回');
  await expect(page.locator('[data-testid="twm-simulator-mechanism"]')).toContainText('GeoSOS-FLUS');
  await expect(page.locator('[data-testid="twm-simulator-mechanism"]')).toContainText('不自动等于政策因果识别');
  await expect(briefing).toContainText('Dynamic Action-Conditioned Multi-scale Geospatial Kernel');
  await expect(page.locator('[data-testid="twm-paper9-evidence"]')).toContainText('四川省内江市东兴区');
  await expect(page.locator('[data-testid="twm-paper9-evidence"]')).toContainText('重庆市璧山区');
  await expect(page.locator('[data-testid="twm-foundation-evidence"]')).toContainText('22,401');
  await expect(page.locator('[data-testid="twm-foundation-evidence"]')).toContainText('21,603');
  await expect(page.locator('[data-testid="twm-foundation-evidence"]')).toContainText('生产观测历史');
  await expect(page.locator('[data-testid="twm-event-compilation"]')).toContainText('官方供地事件');
  await expect(page.locator('[data-testid="twm-event-compilation"]')).toContainText('训练准入');
  await expect(page.locator('[data-testid="twm-benchmark-evidence"]')).toContainText('0/10');
  await expect(page.locator('[data-testid="twm-benchmark-evidence"]')).toContainText('训练输入准入');
  await expect(briefing).toContainText('当前不能宣称');
  await expect(briefing).toContainText('省级试点的最小数据闭环');
  await expectNoBriefingOverflow(page);

  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'desktop-1920.png') });

  await page.getByRole('button', { name: '查看数据依据' }).click();
  await expect(page.getByRole('tab', { name: '数据依据' })).toHaveAttribute('aria-selected', 'true');
  await page.getByRole('tab', { name: '汇报演示' }).click();
  await page.getByRole('button', { name: '进入操作推演' }).click();
  await expect(page.getByRole('tab', { name: '操作推演' })).toHaveAttribute('aria-selected', 'true');
  await page.getByRole('tab', { name: '汇报演示' }).click();
  await page.getByRole('button', { name: '进入地图联动' }).click();
  await expect(page.getByRole('tab', { name: '总览地图' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.twm-map-story')).toContainText('地图联动');

  await page.getByRole('tab', { name: '汇报演示' }).click();
  await page.setViewportSize({ width: 1200, height: 900 });
  await openTwm(page);
  await expect(briefing).toBeVisible();
  await expectNoBriefingOverflow(page);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'narrow-1200.png') });

  expect(pageErrors).toEqual([]);
  const unexpectedConsoleErrors = consoleErrors.filter(message => (
    !message.includes('Failed to load resource')
    && !(message.includes('Unauthorized') && message.includes('/assets/index-'))
  ));
  expect(unexpectedConsoleErrors).toEqual([]);
});
