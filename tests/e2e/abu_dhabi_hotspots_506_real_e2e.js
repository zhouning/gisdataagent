const { chromium } = require('@playwright/test');

const BASE_URL = process.env.GIS_AGENT_E2E_URL || 'http://127.0.0.1:8001';
const SCREENSHOT = process.env.GIS_AGENT_E2E_SCREENSHOT
  || '/tmp/abu-dhabi-hotspots-506-layer.png';

async function clickVisibleText(page, selector, text) {
  const locator = page.locator(selector, { hasText: text }).filter({ visible: true }).first();
  await locator.waitFor({ state: 'visible', timeout: 30_000 });
  await locator.click();
}

async function main() {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  await context.addInitScript(() => localStorage.setItem('gda.locale', 'zh-CN'));
  const page = await context.newPage();

  try {
    const login = await context.request.post(`${BASE_URL}/login`, {
      form: { username: 'admin', password: 'admin123' },
    });
    if (!login.ok()) throw new Error(`login failed: HTTP ${login.status()}`);

    const catalogResponse = await context.request.get(
      `${BASE_URL}/api/abu-dhabi/flood/hotspots/latest-506/catalog`,
    );
    if (!catalogResponse.ok()) {
      throw new Error(`catalog API failed: HTTP ${catalogResponse.status()}`);
    }
    const catalog = await catalogResponse.json();
    if (catalog.inventory?.record_count !== 506) {
      throw new Error(`catalog returned ${catalog.inventory?.record_count} records instead of 506`);
    }

    const mapResponse = await context.request.get(
      `${BASE_URL}/api/abu-dhabi/flood/hotspots/latest-506/map`,
    );
    if (!mapResponse.ok()) throw new Error(`map API failed: HTTP ${mapResponse.status()}`);
    const geojson = await mapResponse.json();
    if (geojson.type !== 'FeatureCollection' || geojson.features?.length !== 506) {
      throw new Error(`map API did not return 506 GeoJSON features`);
    }

    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await page.locator('.app-header').waitFor({ state: 'visible', timeout: 30_000 });
    await clickVisibleText(page, '.data-panel-group', '分析与模型');
    await clickVisibleText(page, '.data-panel-section', '世界模型');
    await clickVisibleText(page, '.data-panel-tab', '阿布扎比 · 暴雨内涝世界模型');

    const workbench = page.locator('.abu-flood-tab');
    await workbench.waitFor({ state: 'visible', timeout: 30_000 });
    await workbench.locator('.abu-flood-stage', { hasText: '数据与输入' }).first().click();
    await page.waitForFunction(() => {
      const layer = window.__lastMapUpdate?.layers?.find((item) => (
        String(item.name || '').includes('客户最新城市积水关键点')
      ));
      return layer?.type === 'categorized'
        && layer?.category_column === 'priority'
        && layer?.visible !== false
        && layer?.geojsonData?.features?.length === 506;
    }, undefined, { timeout: 60_000 });

    const map3d = page.locator('.map-3d-container');
    if (await map3d.isVisible()) {
      const layerToggle = map3d.locator('button', { hasText: '图层' }).first();
      await layerToggle.waitFor({ state: 'visible', timeout: 30_000 });
      await layerToggle.click();
      await map3d.locator('label', {
        hasText: '客户最新城市积水关键点（506 条）',
      }).first().waitFor({ state: 'visible', timeout: 30_000 });
    } else {
      const layerToggle = page.locator('.layer-control-toggle').first();
      await layerToggle.waitFor({ state: 'visible', timeout: 30_000 });
      await layerToggle.click();
      await page.locator('.layer-control-name', {
        hasText: '客户最新城市积水关键点（506 条）',
      }).first().waitFor({ state: 'visible', timeout: 30_000 });
    }

    const cityResult = await page.evaluate(() => {
      const layer = window.__lastMapUpdate?.layers?.find((item) => (
        String(item.name || '').includes('客户最新城市积水关键点')
      ));
      const priorityCounts = (layer?.geojsonData?.features || []).reduce((counts, feature) => {
        const priority = feature?.properties?.priority || 'unknown';
        counts[priority] = (counts[priority] || 0) + 1;
        return counts;
      }, {});
      return {
        layerName: layer?.name,
        layerType: layer?.type,
        categoryColumn: layer?.category_column,
        visible: layer?.visible !== false,
        featureCount: layer?.geojsonData?.features?.length || 0,
        priorityCounts,
        canvasCount: document.querySelectorAll('.map-3d-container canvas').length,
      };
    });

    if (cityResult.priorityCounts['Very Important'] !== 151
      || cityResult.priorityCounts.Important !== 355) {
      throw new Error(`unexpected priority counts: ${JSON.stringify(cityResult.priorityCounts)}`);
    }
    if (cityResult.canvasCount < 1) throw new Error('map did not create a WebGL canvas');

    await clickVisibleText(page, '.data-panel-tab', 'Al Bateen · 高精度内涝推演');
    await page.locator('[data-testid="al-bateen-high-resolution-tab"]')
      .waitFor({ state: 'visible', timeout: 30_000 });
    await page.waitForFunction(() => {
      const update = window.__lastMapUpdate;
      const layer = update?.layers?.find((item) => (
        String(item.name || '').includes('客户最新城市积水关键点')
      ));
      return update?.summary?.layer_group === 'al_bateen_high_resolution_flood'
        && layer?.type === 'categorized'
        && layer?.category_column === 'priority'
        && layer?.visible !== false
        && layer?.geojsonData?.features?.length === 506;
    }, undefined, { timeout: 60_000 });

    const alBateenMap3d = page.locator('.map-3d-container');
    if (await alBateenMap3d.isVisible()) {
      const layerLabel = alBateenMap3d.locator('label', {
        hasText: '客户最新城市积水关键点（506 条）',
      }).first();
      if (!(await layerLabel.isVisible())) {
        await alBateenMap3d.locator('button', { hasText: '图层' }).first().click();
      }
      await layerLabel.waitFor({ state: 'visible', timeout: 30_000 });
    } else {
      const layerLabel = page.locator('.layer-control-name', {
        hasText: '客户最新城市积水关键点（506 条）',
      }).first();
      if (!(await layerLabel.isVisible())) await page.locator('.layer-control-toggle').first().click();
      await layerLabel.waitFor({ state: 'visible', timeout: 30_000 });
    }

    const alBateenResult = await page.evaluate(() => {
      const update = window.__lastMapUpdate;
      const layer = update?.layers?.find((item) => (
        String(item.name || '').includes('客户最新城市积水关键点')
      ));
      return {
        layerGroup: update?.summary?.layer_group,
        layerName: layer?.name,
        featureCount: layer?.geojsonData?.features?.length || 0,
        visible: layer?.visible !== false,
        mapLayerNames: (update?.layers || []).map((item) => item.name),
      };
    });
    await page.screenshot({ path: SCREENSHOT, fullPage: false });

    process.stdout.write(JSON.stringify({
      status: 'passed',
      catalogRecordCount: catalog.inventory.record_count,
      apiFeatureCount: geojson.features.length,
      cityWorldModel: cityResult,
      alBateenWorldModel: alBateenResult,
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
