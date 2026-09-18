const { chromium } = require('@playwright/test');

const BASE_URL = process.env.GIS_AGENT_E2E_URL || 'http://127.0.0.1:8013';
const OUT_DIR = process.env.GIS_AGENT_E2E_OUTPUT_DIR || '/tmp';

async function clickVisibleText(page, selector, text) {
  const locator = page.locator(selector, { hasText: text }).filter({ visible: true }).first();
  await locator.waitFor({ state: 'visible', timeout: 30_000 });
  await locator.click();
}

async function waitForMap(page, predicateSource, label) {
  await page.waitForFunction(
    ({ source }) => {
      const update = window.__lastMapUpdate || null;
      return Boolean(update && Function('update', `return (${source})(update)`)(update));
    },
    { source: predicateSource },
    { timeout: 60_000 },
  );
  await page.waitForTimeout(2_000);
  const update = await page.evaluate(() => window.__lastMapUpdate || null);
  if (!update?.layers?.length) throw new Error(`${label}: map update has no layers`);
  return update;
}

async function waitForTimelineFrame(page, update, label) {
  const timeline = update.layers.find((layer) => layer.scenarioTimeline)?.scenarioTimeline;
  if (!timeline?.runId) throw new Error(`${label}: timeline run id is missing`);
  await page.waitForFunction(
    ({ runId }) => Array.isArray(window.__abuFloodLoadedFrames)
      && window.__abuFloodLoadedFrames.some((frame) => (
        frame.runId === runId && Number(frame.nodeFeatureCount || frame.totalNodeCount || 0) > 0
      )),
    { runId: timeline.runId },
    { timeout: 90_000 },
  );
  await page.waitForTimeout(1_500);
  return page.evaluate(
    ({ runId }) => window.__abuFloodLoadedFrames.find((frame) => frame.runId === runId),
    { runId: timeline.runId },
  );
}

async function waitForRenderedSwmmFrame(page, update) {
  const timeline = update.layers.find((layer) => layer.scenarioTimeline?.kind === 'swmm-node')?.scenarioTimeline;
  if (!timeline?.runId) throw new Error('stage 2: SWMM timeline run id is missing');
  await page.waitForFunction(
    ({ runId }) => Array.isArray(window.__abuFloodRenderedFrames)
      && window.__abuFloodRenderedFrames.some((frame) => (
        frame.runId === runId
        && Number(frame.nodeFeatureCount || 0) > 0
        && Number(frame.renderedLayerCount || 0) > 0
        && Number(frame.renderedPointCount || 0) > 0
      )),
    { runId: timeline.runId },
    { timeout: 90_000 },
  );
  return page.evaluate(
    ({ runId }) => window.__abuFloodRenderedFrames.find((frame) => frame.runId === runId),
    { runId: timeline.runId },
  );
}

async function inspectGwmFrameGeometry(page, update, timeIndex) {
  const timeline = update.layers.find((layer) => layer.scenarioTimeline?.kind === 'gwm-surface-cell')?.scenarioTimeline;
  if (!timeline?.endpoint) throw new Error('stage 4: GWM timeline endpoint is missing');
  return page.evaluate(async ({ endpoint, timeIndex: index }) => {
    const separator = endpoint.includes('?') ? '&' : '?';
    const response = await fetch(`${endpoint}${separator}time_index=${encodeURIComponent(String(index))}`, {
      credentials: 'include',
    });
    if (!response.ok) throw new Error(`GWM geometry request failed: ${response.status}`);
    const payload = await response.json();
    const features = Array.isArray(payload?.features) ? payload.features : [];
    const polygons = features.filter((feature) => (
      feature?.geometry?.type === 'Polygon'
      && Array.isArray(feature.geometry.coordinates?.[0])
      && feature.geometry.coordinates[0].length >= 4
    ));
    return {
      featureCount: features.length,
      polygonCount: polygons.length,
      uniqueCellCount: new Set(features.map((feature) => feature?.properties?.cell_id)).size,
      timelineStepMinutes: Number(payload?.metadata?.timeline?.step_minutes || 0),
      timeIndex: Number(payload?.metadata?.time_index),
    };
  }, { endpoint: timeline.endpoint, timeIndex });
}

async function selectStage(workbench, label) {
  const stage = workbench.locator('.abu-flood-stage', { hasText: label }).first();
  await stage.click();
  await stage.waitFor({ state: 'visible' });
}

async function main() {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  await context.addInitScript(() => {
    localStorage.setItem('gda.locale', 'zh-CN');
    window.__abuFloodLoadedFrames = [];
    window.__abuFloodRenderedFrames = [];
    window.addEventListener('swmm-scenario-frame-loaded', (event) => {
      window.__abuFloodLoadedFrames.push(event.detail || {});
    });
    window.addEventListener('swmm-scenario-frame-rendered', (event) => {
      window.__abuFloodRenderedFrames.push(event.detail || {});
    });
  });
  const page = await context.newPage();
  const responses = [];
  const failures = [];
  page.on('response', (response) => {
    const url = response.url();
    if (url.includes('/api/abu-dhabi/flood/')) responses.push({ status: response.status(), url });
  });
  page.on('requestfailed', (request) => {
    if (request.url().includes('/api/abu-dhabi/flood/')) {
      failures.push({ url: request.url(), error: request.failure()?.errorText || '' });
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

    await selectStage(workbench, '一维雨水管网');
    const stage2 = await waitForMap(
      page,
      "update => update.layers.some(layer => layer.scenarioTimeline?.kind === 'swmm-node')",
      'stage 2',
    );
    const stage2Frame = await waitForTimelineFrame(page, stage2, 'stage 2');
    const stage2RenderedFrame = await waitForRenderedSwmmFrame(page, stage2);
    await page.screenshot({ path: `${OUT_DIR}/abu-dhabi-flood-stage2.png` });

    await selectStage(workbench, '二维地表水动力');
    const stage3 = await waitForMap(
      page,
      "update => update.layers.some(layer => layer.scenarioTimeline?.kind === 'surface-cell')",
      'stage 3',
    );
    const stage3Frame = await waitForTimelineFrame(page, stage3, 'stage 3');
    await page.screenshot({ path: `${OUT_DIR}/abu-dhabi-flood-stage3.png` });

    await selectStage(workbench, 'GWM 快速推演层');
    const stage4 = await waitForMap(
      page,
      "update => update.layers.some(layer => layer.scenarioTimeline?.kind === 'gwm-surface-cell' && layer.type === 'choropleth' && Array.isArray(layer.geojsonData?.features) && layer.geojsonData.features.length > 0)",
      'stage 4',
    );
    const stage4Timeline = stage4.layers.find((layer) => layer.scenarioTimeline?.kind === 'gwm-surface-cell')?.scenarioTimeline;
    if (!stage4Timeline?.endpoint?.includes('/api/abu-dhabi/flood/gwm/trained/runs/')) {
      throw new Error(`stage 4: unexpected trained GWM endpoint ${stage4Timeline?.endpoint || 'missing'}`);
    }
    if (Number(stage4Timeline.reportStepMinutes) !== 5) {
      throw new Error(`stage 4: expected 5-minute GWM steps, received ${stage4Timeline.reportStepMinutes}`);
    }
    const stage4Frame = await waitForTimelineFrame(page, stage4, 'stage 4');
    const stage4Geometry = await inspectGwmFrameGeometry(page, stage4, stage4Frame.timeIndex);
    if (
      stage4Geometry.featureCount < 1
      || stage4Geometry.polygonCount !== stage4Geometry.featureCount
      || stage4Geometry.uniqueCellCount < 1
    ) {
      throw new Error('stage 4: GWM frame has no drawable citywide polygon-grid geometry');
    }
    if (stage4Geometry.timelineStepMinutes !== 5) {
      throw new Error(`stage 4: GWM response is not a 5-minute timeline (${stage4Geometry.timelineStepMinutes})`);
    }
    await page.screenshot({ path: `${OUT_DIR}/abu-dhabi-flood-stage4.png` });

    await selectStage(workbench, '验证与交付');
    const stage5 = await waitForMap(
      page,
      "update => update.layers.some(layer => layer.scenarioTimeline?.kind === 'surface-cell') && update.layers.some(layer => /Customer current urban-flood hotspots|客户当前城市内涝热点/.test(String(layer.name)))",
      'stage 5',
    );
    const stage5Frame = await waitForTimelineFrame(page, stage5, 'stage 5');
    await page.screenshot({ path: `${OUT_DIR}/abu-dhabi-flood-stage5.png` });

    await selectStage(workbench, '数据与输入');
    const explorer = workbench.locator('[data-testid="abu-flood-hotspot-explorer"]');
    await explorer.waitFor({ state: 'visible', timeout: 30_000 });
    await explorer.locator('button', { hasText: 'ADM 历史热点' }).click();
    const historyMap = await waitForMap(
      page,
      "update => update.layers.some(layer => String(layer.name).includes('历史热点') && layer.visible !== false) && update.layers.some(layer => String(layer.name).includes('当前暴雨内涝热点') && layer.visible === false)",
      'historical hotspot inventory',
    );
    const historyRows = await explorer.locator('.abu-flood-hotspot-row:not(.header)').count();
    if (historyRows < 1) throw new Error('historical hotspot browser has no visible records');
    await page.screenshot({ path: `${OUT_DIR}/abu-dhabi-flood-history-hotspots.png` });

    await selectStage(workbench, '验证与交付');
    await page.locator('.language-switcher select').selectOption('en-US');
    const reportButton = workbench.locator('button', { hasText: 'Open decision-support report' }).first();
    await reportButton.waitFor({ state: 'visible', timeout: 30_000 });
    const popupPromise = page.waitForEvent('popup');
    await reportButton.click();
    const report = await popupPromise;
    await report.waitForLoadState('domcontentloaded');
    const reportText = await report.locator('body').innerText();
    if (!reportText.includes('Customer urban flood-hotspot inventory') || !reportText.includes('ADM historical hotspots')) {
      throw new Error('phase 5 report does not expose the customer current/history hotspot summary');
    }
    if (/[㐀-鿿]/u.test(reportText)) {
      throw new Error('phase 5 English report still contains Han characters');
    }
    await report.screenshot({ path: `${OUT_DIR}/abu-dhabi-flood-stage5-report-en.png` });
    await report.close();

    const summarize = (update) => ({
      title: update.summary?.title,
      center: update.center,
      zoom: update.zoom,
      layers: update.layers.map((layer) => ({
        name: layer.name,
        type: layer.type,
        visible: layer.visible !== false,
        timelineKind: layer.scenarioTimeline?.kind || null,
        featureCount: layer.geojsonData?.features?.length ?? null,
      })),
    });
    console.log(JSON.stringify({
      stage2: summarize(stage2),
      stage2Frame,
      stage2RenderedFrame,
      stage3: summarize(stage3),
      stage3Frame,
      stage4: summarize(stage4),
      stage4Frame,
      stage4Geometry,
      stage5: summarize(stage5),
      stage5Frame,
      history: { ...summarize(historyMap), visibleRows: historyRows },
      reportChecks: {
        language: 'en-US',
        hasCustomerHotspotInventory: true,
        hasAdmHistory: true,
        containsHanCharacters: false,
      },
      responses: responses.filter((item) => item.status >= 400),
      failures,
    }, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
