const { chromium } = require('@playwright/test');

const BASE_URL = process.env.GIS_AGENT_E2E_URL || 'http://127.0.0.1:8013';
const SCREENSHOT = process.env.GIS_AGENT_E2E_SCREENSHOT
  || '/tmp/abu-dhabi-flood-stage1-mvt.png';

async function clickVisibleText(page, selector, text) {
  const locator = page.locator(selector, { hasText: text }).filter({ visible: true }).first();
  await locator.waitFor({ state: 'visible', timeout: 30_000 });
  await locator.click();
}

async function main() {
  // Use the locally installed Chrome so this offline demo check never
  // downloads a Playwright-managed browser at the customer site.
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  await context.addInitScript(() => localStorage.setItem('gda.locale', 'zh-CN'));
  const page = await context.newPage();
  const tileResponses = [];
  const failedRequests = [];
  const browserErrors = [];

  page.on('response', (response) => {
    if (response.url().includes('/api/tiles/abu-stormwater-')) {
      tileResponses.push({ status: response.status(), url: response.url() });
    }
  });
  page.on('requestfailed', (request) => {
    failedRequests.push({ url: request.url(), error: request.failure()?.errorText || '' });
  });
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') {
      browserErrors.push(`${message.type()}: ${message.text()}`);
    }
  });

  try {
    const login = await context.request.post(`${BASE_URL}/login`, {
      form: { username: 'admin', password: 'admin123' },
    });
    if (!login.ok()) throw new Error(`login failed: HTTP ${login.status()}`);

    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await page.locator('.app-header').waitFor({ state: 'visible', timeout: 30_000 });
    await clickVisibleText(page, '.data-panel-group', '分析与模型');
    await clickVisibleText(page, '.data-panel-section', '世界模型');
    await clickVisibleText(page, '.data-panel-tab', '阿布扎比 · 暴雨内涝世界模型');

    const workbench = page.locator('.abu-flood-tab');
    await workbench.waitFor({ state: 'visible', timeout: 30_000 });
    await workbench.locator('.abu-flood-stage', { hasText: '数据与输入' }).first().click();
    const mapAction = workbench.locator('button.abu-flood-map-action', {
      hasText: /在地图上展示当前阶段|重新发送当前阶段图层到地图/,
    }).first();
    await mapAction.waitFor({ state: 'visible', timeout: 30_000 });
    await page.waitForFunction(() => {
      const buttons = [...document.querySelectorAll('.abu-flood-tab button.abu-flood-map-action')];
      return buttons.some((button) => (
        ((button.textContent || '').includes('在地图上展示当前阶段')
          || (button.textContent || '').includes('重新发送当前阶段图层到地图'))
        && !button.disabled
      ));
    }, undefined, { timeout: 30_000 });

    await mapAction.click();
    await page.waitForFunction(() => (
      window.__lastMapUpdate?.layers?.some((layer) => (
        layer.layer_id === 'abu-stormwater-pipelines-v1'
      ))
      && window.__lastMapUpdate?.layers?.some((layer) => (
        layer.layer_id === 'abu-stormwater-nodes-v1'
      ))
    ), undefined, { timeout: 30_000 });
    const tileDeadline = Date.now() + 120_000;
    while (Date.now() < tileDeadline) {
      const pipelineReady = tileResponses.some((item) => (
        item.status === 200 && item.url.includes('/api/tiles/abu-stormwater-pipelines-v1/')
      ));
      const nodesReady = tileResponses.some((item) => (
        item.status === 200 && item.url.includes('/api/tiles/abu-stormwater-nodes-v1/')
      ));
      if (pipelineReady && nodesReady) break;
      await page.waitForTimeout(1_000);
    }
    // Allow deck.gl to upload the decoded vectors after the HTTP responses.
    await page.waitForTimeout(5_000);

    const result = await page.evaluate(() => {
      const update = window.__lastMapUpdate || null;
      return {
        update,
        canvasCount: document.querySelectorAll('.map-3d-container canvas').length,
      };
    });
    const pipelineLayer = result.update?.layers?.find((layer) => (
      layer.layer_id === 'abu-stormwater-pipelines-v1'
    ));
    const nodeLayer = result.update?.layers?.find((layer) => (
      layer.layer_id === 'abu-stormwater-nodes-v1'
    ));
    await page.screenshot({ path: SCREENSHOT, fullPage: false });
    if (!pipelineLayer || pipelineLayer.type !== 'mvt') {
      throw new Error(`stage 1 did not publish the pipeline MVT layer: ${JSON.stringify(result.update)}`);
    }
    if (!nodeLayer || nodeLayer.type !== 'mvt' || nodeLayer.visible === false) {
      throw new Error(`stage 1 did not publish a visible node MVT layer: ${JSON.stringify(result.update)}`);
    }
    if (result.update.center?.[0] !== 24.46 || result.update.center?.[1] !== 54.45) {
      throw new Error(`stage 1 opened at the wrong center: ${JSON.stringify(result.update.center)}`);
    }
    if (result.canvasCount < 1) throw new Error('3D map did not create a WebGL canvas');
    if (failedRequests.some((item) => (
      item.url.includes('/api/tiles/abu-stormwater-')
      && item.error !== 'net::ERR_ABORTED'
    ))) {
      throw new Error(`stormwater tile request failed: ${JSON.stringify(failedRequests)}`);
    }
    if (!tileResponses.some((item) => (
      item.status === 200 && item.url.includes('/api/tiles/abu-stormwater-pipelines-v1/')
    ))) {
      throw new Error(`no successful pipeline tile response: ${JSON.stringify({ tileResponses, failedRequests, browserErrors })}`);
    }
    if (!tileResponses.some((item) => (
      item.status === 200 && item.url.includes('/api/tiles/abu-stormwater-nodes-v1/')
    ))) {
      throw new Error(`no successful node tile response: ${JSON.stringify({ tileResponses, failedRequests, browserErrors })}`);
    }

    console.log(JSON.stringify({
      pipelineLayer,
      nodeLayer,
      canvasCount: result.canvasCount,
      successfulTileCount: tileResponses.filter((item) => item.status === 200).length,
      tileResponses,
      browserErrors,
      screenshot: SCREENSHOT,
    }, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
