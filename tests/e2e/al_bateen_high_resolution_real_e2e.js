const { chromium } = require('@playwright/test');

const BASE_URL = process.env.GIS_AGENT_E2E_URL || 'http://127.0.0.1:8013';
const OUT_DIR = process.env.GIS_AGENT_E2E_OUTPUT_DIR || '/tmp';

async function clickVisibleText(page, selector, text) {
  const locator = page.locator(selector, { hasText: text }).filter({ visible: true }).first();
  await locator.waitFor({ state: 'visible', timeout: 30_000 });
  await locator.click();
}

async function main() {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  await context.addInitScript(() => localStorage.setItem('gda.locale', 'en-US'));
  const page = await context.newPage();
  const browserDiagnostics = [];
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') {
      browserDiagnostics.push(`[console:${message.type()}] ${message.text()}`);
    }
  });
  page.on('pageerror', (error) => browserDiagnostics.push(`[pageerror] ${error.message}`));
  page.on('requestfailed', (request) => {
    if (request.url().includes('/api/abu-dhabi/flood/al-bateen/')) {
      browserDiagnostics.push(`[requestfailed] ${request.method()} ${request.url()} ${request.failure()?.errorText || ''}`);
    }
  });
  page.on('response', (response) => {
    if (response.url().includes('/api/abu-dhabi/flood/al-bateen/')) {
      browserDiagnostics.push(`[response] ${response.status()} ${response.url()}`);
    }
  });

  try {
    const login = await context.request.post(`${BASE_URL}/login`, {
      form: { username: 'admin', password: 'admin123' },
    });
    if (!login.ok()) throw new Error(`login failed: HTTP ${login.status()}`);

    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await page.locator('.app-header').waitFor({ state: 'visible', timeout: 30_000 });
    await clickVisibleText(page, '.data-panel-group', 'Analysis & Models');
    await clickVisibleText(page, '.data-panel-section', 'World Models');

    const worldModelTab = page.locator('.data-panel-tab', {
      hasText: 'Abu Dhabi · Stormwater flood world model',
    }).first();
    const alBateenTab = page.locator('.data-panel-tab', {
      hasText: 'Al Bateen · High-resolution flood simulation',
    }).first();
    await worldModelTab.waitFor({ state: 'visible', timeout: 30_000 });
    await alBateenTab.waitFor({ state: 'visible', timeout: 30_000 });

    const order = await page.locator('.data-panel-tab').evaluateAll((items) => items.map((item) => item.textContent || ''));
    const worldModelIndex = order.findIndex((label) => label.includes('Abu Dhabi · Stormwater flood world model'));
    const alBateenIndex = order.findIndex((label) => label.includes('Al Bateen · High-resolution flood simulation'));
    if (worldModelIndex < 0 || alBateenIndex !== worldModelIndex + 1) {
      throw new Error('Al Bateen tab is not immediately adjacent to the Abu Dhabi flood world-model tab');
    }

    const statusResponsePromise = page.waitForResponse(
      (response) => response.url().includes('/api/abu-dhabi/flood/al-bateen/status'),
      { timeout: 30_000 },
    );
    await alBateenTab.click();
    const statusResponse = await statusResponsePromise;
    if (!statusResponse.ok()) throw new Error(`status API failed: HTTP ${statusResponse.status()}`);
    const status = await statusResponse.json();
    if (status.status !== 'ready') throw new Error(`workflow is not ready: ${status.status}`);
    if (status.model?.uses_citywide_250m_gwm !== false || status.model?.uses_250m_interpolation !== false) {
      throw new Error('workflow incorrectly depends on the citywide 250 m GWM');
    }
    if (!Array.isArray(status.assets) || status.assets.some((asset) => !asset.ready)) {
      throw new Error('one or more local high-resolution assets are not ready');
    }
    const libraryResponse = await context.request.get(`${BASE_URL}/api/abu-dhabi/flood/al-bateen/library`);
    if (!libraryResponse.ok()) throw new Error(`precomputed library API failed: HTTP ${libraryResponse.status()}`);
    const library = await libraryResponse.json();
    if (library.available_combination_count < 11 || library.expected_combination_count !== 12) {
      throw new Error(`unexpected precomputed library coverage: ${JSON.stringify(library)}`);
    }

    const workbench = page.locator('[data-testid="al-bateen-high-resolution-tab"]');
    await workbench.waitFor({ state: 'visible', timeout: 30_000 });
    await workbench.getByText('Al Bateen High-Resolution Flood Simulation').waitFor({ state: 'visible' });
    await workbench.getByRole('button', { name: 'Run Al Bateen high-resolution simulation' }).waitFor({ state: 'visible' });
    await workbench.getByText('Independent of the 250 m GWM result').waitFor({ state: 'visible' });
    try {
      await page.waitForFunction(({ hasCompletedRun }) => {
        const update = window.__lastMapUpdate;
        if (update?.summary?.layer_group !== 'al_bateen_high_resolution_flood') return false;
        if (!(update.layers?.[0]?.geojsonData?.features?.length > 0)) return false;
        const hotspotLayer = update.layers?.find((layer) => (
          String(layer.name || '').includes('Customer latest urban-flood critical points')
        ));
        if (hotspotLayer?.geojsonData?.features?.length !== 506 || hotspotLayer?.visible === false) return false;
        if (!hasCompletedRun) return update.layers?.[0]?.name === 'Al Bateen · Model boundary';
        return update.layers?.[1]?.name?.includes('Dynamic flood depth')
          && update.layers?.[1]?.geojsonData?.features?.length > 0
          && Number(update.layers?.[1]?.geojsonData?.features?.[0]?.properties?.time_minutes) > 0;
      }, { hasCompletedRun: status.latest_run?.status === 'completed' }, { timeout: 60_000 });
    } catch (error) {
      const diagnostic = await page.evaluate(() => ({
        mapUpdate: window.__lastMapUpdate ? {
          summary: window.__lastMapUpdate.summary,
          layers: (window.__lastMapUpdate.layers || []).map((layer) => ({
            name: layer.name,
            featureCount: layer.geojsonData?.features?.length || 0,
            timeMinutes: layer.geojsonData?.metadata?.time_minutes,
          })),
        } : null,
        visibleText: document.querySelector('[data-testid="al-bateen-high-resolution-tab"]')?.textContent || '',
      }));
      throw new Error(`${error.message}\nBrowser diagnostics:\n${browserDiagnostics.join('\n')}\nRuntime state:\n${JSON.stringify(diagnostic, null, 2)}`);
    }
    const mapUpdate = await page.evaluate(() => window.__lastMapUpdate);
    const hotspotLayer = mapUpdate.layers.find((layer) => (
      String(layer.name || '').includes('Customer latest urban-flood critical points')
    ));

    let finalWetCells = 0;
    let finalTimeMinutes = 0;
    if (status.latest_run?.status === 'completed') {
      const timelineSlider = workbench.locator('.al-bateen-timeline-controls input[type="range"]');
      await timelineSlider.waitFor({ state: 'visible', timeout: 30_000 });
      const finalFrameIndex = await timelineSlider.getAttribute('max');
      await timelineSlider.fill(String(finalFrameIndex));
      await page.waitForFunction(() => {
        const update = window.__lastMapUpdate;
        const dynamicLayer = update?.layers?.[1];
        return dynamicLayer?.geojsonData?.features?.length === 4
          && Number(dynamicLayer.geojsonData.features[0]?.properties?.time_minutes) === 5940;
      }, null, { timeout: 60_000 });
      const finalMapUpdate = await page.evaluate(() => window.__lastMapUpdate);
      finalWetCells = finalMapUpdate.layers[1].geojsonData.features.length;
      finalTimeMinutes = Number(finalMapUpdate.layers[1].geojsonData.features[0].properties.time_minutes);
    }

    const rp2Cell10 = library.entries.find((entry) => (
      Number(entry.return_period_years) === 2 && Number(entry.cell_size_m) === 10
    ));
    if (!rp2Cell10) throw new Error('2-year 10 m precomputed result is missing');
    const returnPeriodSelect = workbench.locator('label', { hasText: 'Design-storm return period' }).locator('select');
    const cellSizeSelect = workbench.locator('label', { hasText: '2D compute grid' }).locator('select');
    await returnPeriodSelect.selectOption('2');
    await cellSizeSelect.selectOption('10');
    await page.waitForFunction(({ runId }) => {
      const update = window.__lastMapUpdate;
      const dynamic = update?.layers?.find((layer) => layer.name?.includes('Dynamic flood depth'));
      return update?.summary?.event_id === runId
        && update?.summary?.layer_group === 'al_bateen_high_resolution_flood'
        && dynamic?.geojsonData?.features?.length > 0;
    }, { runId: rp2Cell10.run_id }, { timeout: 60_000 });
    await workbench.getByText(rp2Cell10.run_id).waitFor({ state: 'visible', timeout: 30_000 });
    const selectedTimelineSlider = workbench.locator('.al-bateen-timeline-controls input[type="range"]');
    await selectedTimelineSlider.fill(String(Number(rp2Cell10.snapshot_count) - 1));
    await page.waitForFunction(({ runId, timeMinutes }) => {
      const update = window.__lastMapUpdate;
      const dynamic = update?.layers?.find((layer) => layer.name?.includes('Dynamic flood depth'));
      return update?.summary?.event_id === runId
        && Number(dynamic?.geojsonData?.metadata?.time_minutes) === Number(timeMinutes);
    }, {
      runId: rp2Cell10.run_id,
      timeMinutes: rp2Cell10.simulation_duration_minutes,
    }, { timeout: 60_000 });
    const selectedMapUpdate = await page.evaluate(() => window.__lastMapUpdate);
    await page.screenshot({ path: `${OUT_DIR}/al-bateen-high-resolution-tab.png`, fullPage: true });

    process.stdout.write(JSON.stringify({
      status: 'passed',
      workflowStatus: status.status,
      readyAssets: status.assets.length,
      supportedCellSizesM: status.model?.supported_computation_cell_sizes_m,
      mapCenter: mapUpdate.center,
      boundaryFeatures: mapUpdate.layers[0].geojsonData.features.length,
      dynamicWetCells: mapUpdate.layers[1]?.geojsonData?.features?.length || 0,
      customerHotspotFeatures: hotspotLayer?.geojsonData?.features?.length || 0,
      finalWetCells,
      finalTimeMinutes,
      precomputedLibraryAvailable: library.available_combination_count,
      selectedPrecomputedRunId: selectedMapUpdate.summary?.event_id,
      selectedPrecomputedLastTimeMinutes: selectedMapUpdate.layers
        .find((layer) => layer.name?.includes('Dynamic flood depth'))?.geojsonData?.metadata?.time_minutes,
      screenshot: `${OUT_DIR}/al-bateen-high-resolution-tab.png`,
    }, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
