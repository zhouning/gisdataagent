const { chromium } = require('@playwright/test');

const BASE_URL = process.env.GIS_AGENT_E2E_URL || 'http://127.0.0.1:5173';
const SCREENSHOT = process.env.GIS_AGENT_E2E_SCREENSHOT
  || '/tmp/abu-dhabi-flood-stage1-mvt.png';

async function clickVisibleText(page, selector, text) {
  const locator = page.locator(selector, { hasText: text }).filter({ visible: true }).first();
  await locator.waitFor({ state: 'visible', timeout: 30_000 });
  await locator.click();
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();
  const tileResponses = [];
  const hotspotResponses = [];
  const failedRequests = [];

  page.on('response', (response) => {
    if (response.url().includes('/api/tiles/abu-stormwater-')) {
      tileResponses.push({ status: response.status(), url: response.url() });
    }
    if (response.url().includes('/api/abu-dhabi/flood/customer-hotspots/bootstrap')) {
      hotspotResponses.push({ status: response.status(), url: response.url() });
    }
  });
  page.on('requestfailed', (request) => {
    failedRequests.push({ url: request.url(), error: request.failure()?.errorText || '' });
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
    const dataStage = workbench.locator('.abu-flood-stage', { hasText: '数据与准入' }).first();
    await dataStage.click();
    const mapAction = workbench.locator('button.abu-flood-map-action', { hasText: '当前阶段图层' });
    await mapAction.waitFor({ state: 'visible', timeout: 30_000 });
    await page.waitForFunction(() => {
      const button = [...document.querySelectorAll('.abu-flood-tab button.abu-flood-map-action')]
        .find((candidate) => (candidate.textContent || '').includes('当前阶段图层'));
      return button && !button.disabled;
    }, undefined, { timeout: 30_000 });
    const pipelineTileResponse = page.waitForResponse((response) => (
      response.url().includes('/api/tiles/abu-stormwater-pipelines-v1/')
      && response.url().endsWith('.pbf')
      && response.status() === 200
    ), { timeout: 90_000 });
    const nodeTileResponse = page.waitForResponse((response) => (
      response.url().includes('/api/tiles/abu-stormwater-nodes-v1/')
      && response.url().endsWith('.pbf')
      && response.status() === 200
    ), { timeout: 90_000 });
    await mapAction.click();
    await Promise.all([pipelineTileResponse, nodeTileResponse]);
    // Large point tiles finish decoding after the HTTP response completes.
    // Give deck.gl time to upload both full-resolution MVT layers to WebGL.
    await page.waitForTimeout(10_000);

    const mapUpdate = await page.evaluate(() => window.__lastMapUpdate || null);
    const pipelineLayer = mapUpdate?.layers?.find((layer) => (
      layer.layer_id === 'abu-stormwater-pipelines-v1'
    ));
    const nodeLayer = mapUpdate?.layers?.find((layer) => (
      layer.layer_id === 'abu-stormwater-nodes-v1'
    ));
    const hotspotLayer = mapUpdate?.layers?.find((layer) => (
      layer.layer_id === 'abu-dhabi-customer-hotspots-506'
    ));
    if (!pipelineLayer || pipelineLayer.type !== 'mvt') {
      throw new Error(`stage 1 did not publish the pipeline MVT layer: ${JSON.stringify(mapUpdate)}`);
    }
    if (!nodeLayer || nodeLayer.type !== 'mvt' || nodeLayer.visible === false) {
      throw new Error(`stage 1 did not publish a visible node MVT layer: ${JSON.stringify(mapUpdate)}`);
    }
    if (!hotspotLayer || hotspotLayer.type !== 'bubble' || hotspotLayer.geojsonData?.features?.length !== 506) {
      throw new Error(`stage 1 did not publish the 506-point customer hotspot layer: ${JSON.stringify(mapUpdate)}`);
    }
    const hotspotIds = hotspotLayer.geojsonData.features.map((feature) => Number(feature.properties?.hotspot_id));
    if (new Set(hotspotIds).size !== 506 || Math.min(...hotspotIds) !== 1 || Math.max(...hotspotIds) !== 506) {
      throw new Error('customer hotspot IDs are not the complete unique range 1-506');
    }
    if (hotspotLayer.geojsonData.features.some((feature) => feature.geometry?.type !== 'Point')) {
      throw new Error('customer hotspot layer contains non-point auxiliary geometry');
    }
    const hotspotUiRow = workbench.locator('[data-map-layer-id="abu-dhabi-customer-hotspots-506"]');
    await hotspotUiRow.waitFor({ state: 'visible', timeout: 30_000 });
    if (!(await hotspotUiRow.textContent())?.includes('506')) {
      throw new Error('customer hotspot UI row does not identify the 506-point layer');
    }
    if (!hotspotResponses.some((item) => item.status === 200)) {
      throw new Error(`customer hotspot API did not return HTTP 200: ${JSON.stringify(hotspotResponses)}`);
    }
    if (failedRequests.some((item) => (
      (item.url.includes('stormwater') || item.url.includes('.fgb'))
      && item.error !== 'net::ERR_ABORTED'
    ))) {
      throw new Error(`stormwater map request failed: ${JSON.stringify(failedRequests)}`);
    }
    if (tileResponses.filter((item) => item.status === 200).length === 0) {
      throw new Error(`no successful MVT response: ${JSON.stringify(tileResponses)}`);
    }

    await page.locator('.language-switcher select').selectOption('en-US');
    await page.waitForTimeout(1_000);
    await workbench.locator('[data-stage-key="data"]').click();
    await workbench.locator('.abu-flood-map-section button.abu-flood-map-action').click();
    await page.waitForTimeout(1_000);
    const translatedTooltipLabels = await page.evaluate(() => {
      const update = window.__lastMapUpdate || {};
      return (update.layers || [])
        .filter((layer) => layer.layer_id === 'abu-dhabi-customer-hotspots-506')
        .flatMap((layer) => Object.values(layer.tooltip_labels || {}));
    });
    if (translatedTooltipLabels.some((label) => /[\u3400-\u9fff]/u.test(label))) {
      throw new Error(`English tooltip labels still contain Chinese: ${translatedTooltipLabels.join(' | ')}`);
    }

    const layerControlButton = page.locator('.map-3d-container button', { hasText: 'Layers' }).first();
    await layerControlButton.click();
    const hotspotLayerControl = page.locator('.map-3d-container label', { hasText: 'Customer static flood hotspots (506)' }).first();
    await hotspotLayerControl.waitFor({ state: 'visible', timeout: 30_000 });
    const hotspotLayerToggleChecked = await hotspotLayerControl.locator('input[type="checkbox"]').isChecked();
    if (!hotspotLayerToggleChecked) throw new Error('customer hotspot layer is not enabled in the map layer control');

    await page.screenshot({ path: SCREENSHOT, fullPage: false });
    console.log(JSON.stringify({
      layer: pipelineLayer,
      nodeLayer,
      hotspotLayer: {
        name: hotspotLayer.name,
        type: hotspotLayer.type,
        layerId: hotspotLayer.layer_id,
        featureCount: hotspotLayer.geojsonData.features.length,
        categoryColumn: hotspotLayer.category_column,
        categoryColors: hotspotLayer.category_colors,
      },
      successfulTileCount: tileResponses.filter((item) => item.status === 200).length,
      tileResponses,
      hotspotResponses,
      failedRequests,
      translatedTooltipLabels,
      hotspotLayerControlVisible: true,
      hotspotLayerToggleChecked,
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
