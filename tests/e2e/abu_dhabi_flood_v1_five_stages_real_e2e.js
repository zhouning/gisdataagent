const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('@playwright/test');

const BASE_URL = process.env.GIS_AGENT_E2E_URL || 'http://127.0.0.1:8000';
const ARTIFACT_DIR = process.env.GIS_AGENT_E2E_ARTIFACT_DIR
  || path.resolve(process.cwd(), 'artifacts/abu_dhabi_flood_v1_five_stages');
const RETURN_PERIODS = [2, 5, 10, 25, 50, 100];

function apiPath(url) {
  try {
    return new URL(url).pathname;
  } catch {
    return url;
  }
}

function isTrainingEndpoint(url) {
  const segments = apiPath(url).toLowerCase().split('/').filter(Boolean);
  return segments.some(segment => [
    'train', 'training', 'fit', 'finetune', 'fine-tune', 'retrain', 'retraining',
  ].includes(segment));
}

async function waitForMapUpdate(page, predicate, label, timeout = 120_000) {
  await page.waitForFunction(
    ({ expectedLabel }) => {
      const update = window.__lastMapUpdate;
      if (!update) return false;
      if (expectedLabel === 'stage1') {
        const ids = (update.layers || []).map(layer => layer.layer_id);
        return ids.includes('abu-stormwater-pipelines-v1')
          && ids.includes('abu-stormwater-nodes-v1');
      }
      if (expectedLabel === 'stage2') {
        return update.summary?.source_status === 'interactive_swmm_run_result';
      }
      if (expectedLabel === 'stage3') {
        return update.summary?.source_status === 'customer_dtm5m_citywide_2d_result';
      }
      if (expectedLabel === 'stage4') {
        return update.summary?.source_status === 'gwm_r1_trained_event_rollout';
      }
      if (expectedLabel === 'stage5') {
        return update.summary?.source_status === 'customer_historical_replay_validation';
      }
      if (expectedLabel === 'sentinel') {
        return update.summary?.source_status === 'sentinel2_external_holdout_observation';
      }
      return false;
    },
    { expectedLabel: label },
    { timeout },
  );
  const update = await page.evaluate(() => window.__lastMapUpdate || null);
  assert.ok(predicate(update), `${label} map contract failed: ${JSON.stringify(update)}`);
  return update;
}

async function screenshot(page, name) {
  const target = path.join(ARTIFACT_DIR, `${name}.png`);
  await page.screenshot({ path: target, fullPage: false });
  return target;
}

async function readPipelineProgress(workbench) {
  return workbench.evaluate(root => {
    const ring = root.querySelector('.abu-flood-readiness-ring');
    const stages = [...root.querySelectorAll('.abu-flood-stage')].map(stage => ({
      key: stage.getAttribute('data-stage-key'),
      progress: stage.getAttribute('data-stage-progress'),
      iconProgress: stage.querySelector('[data-stage-progress-icon]')?.getAttribute('data-stage-progress-icon'),
    }));
    return {
      completedCount: Number(ring?.getAttribute('data-completed-stages') || -1),
      totalCount: Number(ring?.getAttribute('data-total-stages') || -1),
      ringText: ring?.textContent?.replace(/\s+/g, ' ').trim() || '',
      stages,
    };
  });
}

function assertPipelineProgressConsistent(progress, label) {
  const completeStages = progress.stages.filter(stage => stage.progress === 'complete');
  assert.equal(progress.totalCount, progress.stages.length,
    `${label}: readiness total does not match pipeline stage count`);
  assert.equal(progress.completedCount, completeStages.length,
    `${label}: readiness count does not match completed pipeline icons`);
  progress.stages.forEach(stage => {
    assert.equal(stage.iconProgress, stage.progress,
      `${label}: ${stage.key} card and icon progress disagree`);
  });
}

async function main() {
  fs.mkdirSync(ARTIFACT_DIR, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1600, height: 1000 },
    locale: 'zh-CN',
  });
  const page = await context.newPage();

  const requests = [];
  const responses = [];
  const failedRequests = [];
  const consoleErrors = [];
  const evidence = {
    baseUrl: BASE_URL,
    startedAt: new Date().toISOString(),
    stage1: {},
    stage2: { loaded: [] },
    stage3: { oneWayLoaded: [], bidirectional: null },
    stage4: {},
    stage5: {},
    pipeline: {},
    screenshots: [],
  };

  page.on('request', request => {
    requests.push({
      method: request.method(),
      url: request.url(),
      postData: request.postData() || null,
      at: new Date().toISOString(),
    });
  });
  page.on('response', response => {
    responses.push({
      method: response.request().method(),
      status: response.status(),
      url: response.url(),
      at: new Date().toISOString(),
    });
  });
  page.on('requestfailed', request => {
    failedRequests.push({
      method: request.method(),
      url: request.url(),
      error: request.failure()?.errorText || 'unknown request failure',
    });
  });
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });

  try {
    const login = await context.request.post(`${BASE_URL}/login`, {
      form: { username: 'admin', password: 'admin123' },
    });
    assert.equal(login.status(), 200, `login failed: HTTP ${login.status()}`);

    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await page.locator('.app-header').waitFor({ state: 'visible', timeout: 60_000 });
    const languageSelect = page.locator('.language-switcher select');
    if (await languageSelect.count()) await languageSelect.selectOption('zh-CN');

    const analysisGroup = page.locator('.data-panel-group', { hasText: /分析|智能分析/ }).first();
    await analysisGroup.click();
    const worldModelSection = page.locator('.data-panel-section', { hasText: '世界模型' }).first();
    if (await worldModelSection.count()) await worldModelSection.click();
    await page.locator('.data-panel-tab', { hasText: '阿布扎比 · 暴雨内涝世界模型' }).click();

    const workbench = page.locator('.abu-flood-tab');
    await workbench.waitFor({ state: 'visible', timeout: 60_000 });
    await page.waitForFunction(() => (
      document.querySelectorAll('.abu-flood-stage[data-stage-progress="complete"]').length === 5
    ), undefined, { timeout: 120_000 });
    const initialPipeline = await readPipelineProgress(workbench);
    assertPipelineProgressConsistent(initialPipeline, 'initial pipeline');
    assert.deepEqual(
      initialPipeline.stages.filter(stage => stage.progress === 'complete').map(stage => stage.key).sort(),
      ['data', 'gwm', 'surface', 'swmm', 'validation'],
      'initial pipeline should show all five stage capabilities/results ready',
    );
    evidence.pipeline.initial = initialPipeline;

    // Stage 1: real customer-network MVT layers must reach the shared map.
    const stage1 = workbench.locator('.abu-flood-stage', { hasText: '数据与准入' }).first();
    await stage1.click();
    const stage1MapButton = workbench.locator('.abu-flood-map-section button.abu-flood-map-action').first();
    await stage1MapButton.waitFor({ state: 'visible' });
    await page.waitForFunction(() => {
      const button = document.querySelector('.abu-flood-map-section button.abu-flood-map-action');
      return button && !button.disabled;
    }, undefined, { timeout: 60_000 });
    const pipelineTileAlreadyLoaded = responses.some(response => (
      response.url.includes('/api/tiles/abu-stormwater-pipelines-v1/')
      && response.url.endsWith('.pbf')
      && response.status === 200
    ));
    const nodeTileAlreadyLoaded = responses.some(response => (
      response.url.includes('/api/tiles/abu-stormwater-nodes-v1/')
      && response.url.endsWith('.pbf')
      && response.status === 200
    ));
    const pipelineTile = pipelineTileAlreadyLoaded ? Promise.resolve() : page.waitForResponse(response => (
      response.url().includes('/api/tiles/abu-stormwater-pipelines-v1/')
      && response.url().endsWith('.pbf')
      && response.status() === 200
    ), { timeout: 120_000 });
    const nodeTile = nodeTileAlreadyLoaded ? Promise.resolve() : page.waitForResponse(response => (
      response.url().includes('/api/tiles/abu-stormwater-nodes-v1/')
      && response.url().endsWith('.pbf')
      && response.status() === 200
    ), { timeout: 120_000 });
    await stage1MapButton.click();
    await Promise.all([pipelineTile, nodeTile]);
    const stage1Map = await waitForMapUpdate(
      page,
      update => {
        const pipeline = update?.layers?.find(layer => layer.layer_id === 'abu-stormwater-pipelines-v1');
        const nodes = update?.layers?.find(layer => layer.layer_id === 'abu-stormwater-nodes-v1');
        return pipeline?.type === 'mvt' && nodes?.type === 'mvt' && nodes.visible !== false;
      },
      'stage1',
    );
    evidence.stage1 = {
      mapSourceStatus: stage1Map.summary?.source_status,
      layerIds: stage1Map.layers.map(layer => layer.layer_id).filter(Boolean),
    };
    evidence.screenshots.push(await screenshot(page, '01-stage1-customer-network-mvt'));

    // Stage 2: exercise every registered return-period result through the UI.
    // Deliberately never click the adjacent "Run SWMM Simulation" action.
    await workbench.locator('.abu-flood-stage', { hasText: '一维雨水管网' }).first().click();
    const scenarioSection = workbench.locator('.abu-flood-scenario-section');
    const stage2PeriodSelect = scenarioSection.locator('label', { hasText: '设计重现期' }).locator('select').first();
    const precomputedButton = scenarioSection.locator('button.abu-flood-precomputed-action');
    await precomputedButton.waitFor({ state: 'visible', timeout: 60_000 });

    for (const period of RETURN_PERIODS) {
      await stage2PeriodSelect.selectOption(String(period));
      await page.waitForFunction(() => {
        const button = document.querySelector('.abu-flood-precomputed-action');
        return button && !button.disabled;
      }, undefined, { timeout: 60_000 });

      const runResponsePromise = page.waitForResponse(response => {
        const pathname = apiPath(response.url());
        return response.request().method() === 'GET'
          && /^\/api\/abu-dhabi\/flood\/scenarios\/[^/]+$/.test(pathname)
          && response.status() === 200;
      }, { timeout: 120_000 });
      const bootstrapResponsePromise = page.waitForResponse(response => {
        const pathname = apiPath(response.url());
        return response.request().method() === 'GET'
          && /^\/api\/abu-dhabi\/flood\/scenarios\/[^/]+\/map\/bootstrap$/.test(pathname)
          && response.status() === 200;
      }, { timeout: 120_000 });

      await precomputedButton.click();
      const [runResponse, bootstrapResponse] = await Promise.all([
        runResponsePromise,
        bootstrapResponsePromise,
      ]);
      const [run, bootstrap] = await Promise.all([
        runResponse.json(),
        bootstrapResponse.json(),
      ]);
      assert.ok(run.run_id, `stage 2 ${period}-year result has no run_id`);
      assert.ok(['completed', 'completed_with_warnings'].includes(String(run.status)),
        `stage 2 ${period}-year run is not completed: ${run.status}`);
      assert.equal(bootstrap.metadata?.run_id, run.run_id,
        `stage 2 ${period}-year bootstrap/run mismatch`);
      assert.ok(Number(bootstrap.metadata?.timeline?.period_count || 0) > 0,
        `stage 2 ${period}-year result has no timeline`);
      assert.ok(Number(bootstrap.metadata?.total_node_result_count
        || bootstrap.metadata?.timeline?.total_node_count || 0) > 0,
      `stage 2 ${period}-year result has no node results`);

      await page.waitForFunction(() => {
        const button = document.querySelector('.abu-flood-precomputed-action');
        return button && !button.disabled;
      }, undefined, { timeout: 180_000 });
      const mapUpdate = await waitForMapUpdate(
        page,
        update => update?.summary?.source_status === 'interactive_swmm_run_result'
          && update.layers?.some(layer => layer.scenarioTimeline?.runId === run.run_id),
        'stage2',
        180_000,
      );
      evidence.stage2.loaded.push({
        returnPeriodYears: period,
        runId: run.run_id,
        status: run.status,
        timelineFrames: Number(bootstrap.metadata.timeline.period_count),
        nativeNodeCount: Number(bootstrap.metadata?.total_node_result_count
          || bootstrap.metadata?.timeline?.total_node_count || 0),
        mapSourceStatus: mapUpdate.summary.source_status,
      });
    }
    evidence.screenshots.push(await screenshot(page, '02-stage2-precomputed-swmm'));

    // Stage 3: inspect the invocation UI, then load all registered one-way
    // products and the independent 100-year synchronous two-way validation.
    await workbench.locator('.abu-flood-stage', { hasText: '二维地表水动力' }).first().click();
    const surfaceWorkspace = workbench.locator('.abu-flood-surface-workspace');
    await surfaceWorkspace.getByRole('tab', { name: '二维模型调用' }).click();
    await assert.doesNotReject(async () => {
      await surfaceWorkspace.getByLabel('二维求解器').waitFor({ state: 'visible' });
      await surfaceWorkspace.getByLabel('耦合方式').waitFor({ state: 'visible' });
      await surfaceWorkspace.getByLabel('计算网格（m）').waitFor({ state: 'visible' });
      await surfaceWorkspace.getByLabel('陆地 Manning n').waitFor({ state: 'visible' });
      await surfaceWorkspace.getByLabel('海边界水位（m）').waitFor({ state: 'visible' });
    }, 'stage 3 invocation parameters are not visible');
    assert.equal(await surfaceWorkspace.getByRole('button', { name: '提交二维计算' }).count(), 1,
      'stage 3 invocation action is missing');

    await surfaceWorkspace.getByRole('tab', { name: '已算结果' }).click();
    const surfaceResults = surfaceWorkspace.locator('.abu-flood-precomputed-surface-page');
    const sourceSelect = surfaceResults.locator('label', { hasText: '成果来源' }).locator('select');
    const surfacePeriodSelect = surfaceResults.locator('label', { hasText: '设计重现期' }).locator('select');
    const surfaceLoadButton = surfaceResults.getByRole('button', { name: '加载到地图' });

    await sourceSelect.selectOption('return_period_one_way');
    for (const period of RETURN_PERIODS) {
      await surfacePeriodSelect.selectOption(String(period));
      const responsePromise = page.waitForResponse(response => {
        if (response.request().method() !== 'GET' || response.status() !== 200) return false;
        const url = new URL(response.url());
        return url.pathname === '/api/abu-dhabi/flood/public-citywide-2d/bootstrap'
          && url.searchParams.get('return_period_years') === String(period)
          && url.searchParams.get('result_source') === 'return_period_one_way';
      }, { timeout: 120_000 });
      await surfaceLoadButton.click();
      const response = await responsePromise;
      const payload = await response.json();
      assert.equal(Number(payload.metadata?.return_period_years), period,
        `stage 3 returned the wrong one-way period for ${period}`);
      assert.equal(payload.metadata?.result_variant, 'return_period_one_way',
        `stage 3 ${period}-year result is not the one-way registered variant`);
      assert.equal(payload.metadata?.model_configuration?.execution_mode, 'registered_precomputed_result',
        `stage 3 ${period}-year result is not registered/precomputed`);
      assert.equal(payload.maximum_depth?.type, 'FeatureCollection');
      assert.ok(payload.maximum_depth.features.length > 0,
        `stage 3 ${period}-year maximum-depth layer is empty`);
      assert.ok(Number(payload.metadata?.timeline?.period_count || 0) > 0,
        `stage 3 ${period}-year timeline is empty`);
      await surfaceResults.getByText(`${period} 年一遇单向登记成果已加载`, { exact: false })
        .waitFor({ state: 'visible', timeout: 60_000 });
      const mapUpdate = await waitForMapUpdate(
        page,
        update => update?.summary?.source_status === 'customer_dtm5m_citywide_2d_result'
          && update.layers?.some(layer => Number(layer.scenarioTimeline?.periodCount || 0) > 0),
        'stage3',
      );
      evidence.stage3.oneWayLoaded.push({
        returnPeriodYears: period,
        runId: payload.metadata.timeline.run_id,
        cellCount: Number(payload.metadata.timeline.total_cell_count),
        timelineFrames: Number(payload.metadata.timeline.period_count),
        maximumDepthM: Number(payload.metadata.maximum_depth_m),
        mapSourceStatus: mapUpdate.summary.source_status,
      });
    }

    await sourceSelect.selectOption('bidirectional_validation');
    assert.equal(await surfacePeriodSelect.inputValue(), '100',
      'bidirectional validation did not lock to the 100-year event');
    const bidirectionalResponsePromise = page.waitForResponse(response => {
      if (response.request().method() !== 'GET' || response.status() !== 200) return false;
      const url = new URL(response.url());
      return url.pathname === '/api/abu-dhabi/flood/public-citywide-2d/bootstrap'
        && url.searchParams.get('return_period_years') === '100'
        && url.searchParams.get('result_source') === 'bidirectional_validation';
    }, { timeout: 120_000 });
    await surfaceLoadButton.click();
    const bidirectionalResponse = await bidirectionalResponsePromise;
    const bidirectional = await bidirectionalResponse.json();
    assert.equal(bidirectional.metadata?.result_variant, 'bidirectional_validation');
    assert.equal(bidirectional.metadata?.model_configuration?.execution_mode, 'registered_precomputed_result');
    assert.equal(Number(bidirectional.metadata?.return_period_years), 100);
    assert.equal(Number(bidirectional.metadata?.coupling_summary?.window_count), 36);
    assert.equal(Number(bidirectional.metadata?.coupling_summary?.interface_count), 141840);
    assert.ok(Number(bidirectional.metadata?.coupling_summary?.total_swmm_to_anuga_m3) > 0);
    assert.ok(Number(bidirectional.metadata?.coupling_summary?.total_anuga_to_swmm_m3) > 0);
    assert.ok(Number(bidirectional.metadata?.timeline?.period_count || 0) > 0);
    await surfaceResults.getByText('100 年一遇同步双向数值验证成果已加载', { exact: false })
      .waitFor({ state: 'visible', timeout: 60_000 });
    await waitForMapUpdate(
      page,
      update => update?.summary?.source_status === 'customer_dtm5m_citywide_2d_result'
        && update.layers?.some(layer => Number(layer.scenarioTimeline?.periodCount || 0) > 0),
      'stage3',
    );
    evidence.stage3.bidirectional = {
      runId: bidirectional.metadata.timeline.run_id,
      returnPeriodYears: Number(bidirectional.metadata.return_period_years),
      timelineFrames: Number(bidirectional.metadata.timeline.period_count),
      cellCount: Number(bidirectional.metadata.timeline.total_cell_count),
      exchangeWindows: Number(bidirectional.metadata.coupling_summary.window_count),
      interfaces: Number(bidirectional.metadata.coupling_summary.interface_count),
      swmmToAnugaM3: Number(bidirectional.metadata.coupling_summary.total_swmm_to_anuga_m3),
      anugaToSwmmM3: Number(bidirectional.metadata.coupling_summary.total_anuga_to_swmm_m3),
    };
    evidence.screenshots.push(await screenshot(page, '03-stage3-bidirectional-precomputed'));

    // Stage 4: invoke the frozen historical-event GWM from the page. This is
    // inference/rollout only. No training endpoint or training UI is allowed.
    await workbench.locator('.abu-flood-stage', { hasText: 'GWM 快速推演层' }).first().click();
    const gwmControl = workbench.locator('.abu-flood-gwm-control');
    await gwmControl.getByRole('tab', { name: '历史事件 GWM R1' }).click();
    const eventSelect = gwmControl.locator('label', { hasText: '历史降雨场次' }).locator('select');
    await page.waitForFunction(() => {
      const select = document.querySelector('.abu-flood-gwm-control label select');
      return select && !select.disabled && select.options.length > 0 && Boolean(select.value);
    }, undefined, { timeout: 60_000 });
    const options = await eventSelect.locator('option').evaluateAll(nodes => nodes.map(node => ({
      value: node.value,
      text: node.textContent || '',
    })));
    const externalHoldout = options.find(option => option.text.includes('外部留出')) || options[0];
    assert.ok(externalHoldout?.value, 'stage 4 has no registered event for inference');
    await eventSelect.selectOption(externalHoldout.value);
    assert.equal(await gwmControl.getByRole('button', { name: /训练|拟合|调参/ }).count(), 0,
      'stage 4 exposes a forbidden training/tuning action');

    const rolloutStartedAt = Date.now();
    const rolloutResponsePromise = page.waitForResponse(response => (
      apiPath(response.url()) === '/api/abu-dhabi/flood/gwm/trained/rollout'
      && response.request().method() === 'POST'
    ), { timeout: 180_000 });
    const gwmMapResponsePromise = page.waitForResponse(response => (
      /^\/api\/abu-dhabi\/flood\/gwm\/trained\/runs\/[^/]+\/map$/.test(apiPath(response.url()))
      && response.request().method() === 'GET'
    ), { timeout: 180_000 });
    const gwmTimelineResponsePromise = page.waitForResponse(response => (
      /^\/api\/abu-dhabi\/flood\/gwm\/trained\/runs\/[^/]+\/map\/timeseries$/.test(apiPath(response.url()))
      && response.request().method() === 'GET'
    ), { timeout: 180_000 });

    await gwmControl.getByRole('button', { name: '推理历史积水过程' }).click();
    const rolloutResponse = await rolloutResponsePromise;
    assert.ok([200, 201, 202].includes(rolloutResponse.status()),
      `stage 4 rollout failed: HTTP ${rolloutResponse.status()}`);
    const createdRollout = await rolloutResponse.json();
    assert.ok(String(createdRollout.run_id || '').startsWith('trained-gwm-'),
      `stage 4 did not create a new trained-gwm Run ID: ${JSON.stringify(createdRollout)}`);
    const [gwmMapResponse, gwmTimelineResponse] = await Promise.all([
      gwmMapResponsePromise,
      gwmTimelineResponsePromise,
    ]);
    assert.equal(gwmMapResponse.status(), 200);
    assert.equal(gwmTimelineResponse.status(), 200);
    await gwmControl.getByText('历史事件 GWM R1 时间轴已就绪', { exact: false })
      .waitFor({ state: 'visible', timeout: 180_000 });
    const stage4Map = await waitForMapUpdate(
      page,
      update => update?.summary?.source_status === 'gwm_r1_trained_event_rollout'
        && update.layers?.some(layer => layer.scenarioTimeline?.runId === createdRollout.run_id),
      'stage4',
      180_000,
    );
    assert.ok(Date.now() >= rolloutStartedAt, 'stage 4 rollout clock is invalid');
    evidence.stage4 = {
      eventId: externalHoldout.value,
      externalHoldout: externalHoldout.text.includes('外部留出'),
      runId: createdRollout.run_id,
      postStatus: rolloutResponse.status(),
      mapStatus: gwmMapResponse.status(),
      timelineStatus: gwmTimelineResponse.status(),
      mapSourceStatus: stage4Map.summary.source_status,
      timelineFrames: Number(stage4Map.layers.find(layer => layer.scenarioTimeline)?.scenarioTimeline?.periodCount || 0),
    };
    await page.waitForFunction(() => (
      document.querySelector('.abu-flood-stage[data-stage-key="gwm"]')?.getAttribute('data-stage-progress') === 'complete'
    ), undefined, { timeout: 60_000 });
    const postGwmPipeline = await readPipelineProgress(workbench);
    assertPipelineProgressConsistent(postGwmPipeline, 'post-GWM pipeline');
    assert.equal(postGwmPipeline.completedCount, 5,
      'all five pipeline icons should be complete after the live frozen-GWM rollout');
    evidence.pipeline.afterStage4 = postGwmPipeline;
    evidence.screenshots.push(await screenshot(page, '04-stage4-live-frozen-gwm-rollout'));

    // Stage 5: reload the read-only historical replay, verify its temporal
    // map, then verify the independent Sentinel-2 external observation layer.
    const historicalTimelinePromise = page.waitForResponse(response => (
      apiPath(response.url()) === '/api/abu-dhabi/flood/validation/historical-replay/timeseries'
      && response.request().method() === 'GET'
      && response.status() === 200
    ), { timeout: 180_000 });
    await workbench.locator('.abu-flood-stage', { hasText: '验证与交付' }).first().click();
    const validationControl = workbench.locator('.abu-flood-gwm-control');
    const refreshReplay = validationControl.getByRole('button', { name: '加载 / 刷新历史重演结果' });
    await refreshReplay.waitFor({ state: 'visible', timeout: 60_000 });
    const replayBootstrapPromise = page.waitForResponse(response => (
      apiPath(response.url()) === '/api/abu-dhabi/flood/validation/historical-replay/bootstrap'
      && response.request().method() === 'GET'
    ), { timeout: 120_000 });
    await refreshReplay.click();
    const replayBootstrapResponse = await replayBootstrapPromise;
    assert.equal(replayBootstrapResponse.status(), 200);
    const replay = await replayBootstrapResponse.json();
    assert.equal(replay.maximum_depth?.type, 'FeatureCollection');
    assert.ok(replay.maximum_depth.features.length > 0, 'stage 5 replay maximum-depth layer is empty');
    assert.ok(Number(replay.metadata?.timeline?.period_count || 0) > 0, 'stage 5 replay timeline is empty');
    assert.ok(Number(replay.metadata?.timeline?.total_cell_count || 0) > 0, 'stage 5 replay cell count is zero');
    await validationControl.getByText('历史重演已加载；地图和时间轴已就绪', { exact: false })
      .waitFor({ state: 'visible', timeout: 120_000 });
    const replayTimelineResponse = await historicalTimelinePromise;
    assert.equal(replayTimelineResponse.status(), 200);
    const stage5Map = await waitForMapUpdate(
      page,
      update => update?.summary?.source_status === 'customer_historical_replay_validation'
        && update.layers?.some(layer => Number(layer.scenarioTimeline?.periodCount || 0) > 0),
      'stage5',
      180_000,
    );

    const observationTab = workbench.getByRole('button', { name: '2024 历史观测验证' });
    await observationTab.click();
    await workbench.getByText('观测产品质检通过', { exact: false })
      .waitFor({ state: 'visible', timeout: 120_000 });
    await workbench.getByText('外部留出集', { exact: false }).first()
      .waitFor({ state: 'visible', timeout: 60_000 });
    const showObservation = workbench.getByRole('button', { name: '在地图上查看观测积水' });
    await showObservation.click();
    const sentinelMap = await waitForMapUpdate(
      page,
      update => update?.summary?.source_status === 'sentinel2_external_holdout_observation'
        && update.layers?.some(layer => layer.geojsonData?.type === 'FeatureCollection'),
      'sentinel',
      120_000,
    );
    evidence.stage5 = {
      runId: replay.metadata?.timeline?.run_id,
      timelineFrames: Number(replay.metadata?.timeline?.period_count || 0),
      cellCount: Number(replay.metadata?.timeline?.total_cell_count || 0),
      maximumDepthM: Number(replay.metadata?.results?.maximum_depth_m || 0),
      replayMapSourceStatus: stage5Map.summary.source_status,
      sentinelMapSourceStatus: sentinelMap.summary.source_status,
      sentinelFeatureCount: Number(sentinelMap.layers?.[0]?.geojsonData?.features?.length || 0),
    };
    const finalPipeline = await readPipelineProgress(workbench);
    assertPipelineProgressConsistent(finalPipeline, 'final pipeline');
    assert.equal(finalPipeline.completedCount, 5,
      'final readiness count should remain aligned with five completed pipeline icons');
    evidence.pipeline.final = finalPipeline;
    evidence.screenshots.push(await screenshot(page, '05-stage5-sentinel-external-holdout'));

    // Hard safety/audit assertions across the complete browser session.
    const stage2ExecutionPosts = requests.filter(request => (
      request.method === 'POST'
      && apiPath(request.url) === '/api/abu-dhabi/flood/scenarios'
    ));
    const stage3ExecutionPosts = requests.filter(request => (
      request.method === 'POST'
      && apiPath(request.url) === '/api/abu-dhabi/flood/surface/runs'
    ));
    const rolloutPosts = requests.filter(request => (
      request.method === 'POST'
      && apiPath(request.url) === '/api/abu-dhabi/flood/gwm/trained/rollout'
    ));
    const trainingRequests = requests.filter(request => isTrainingEndpoint(request.url));
    const criticalHttpErrors = responses.filter(response => (
      apiPath(response.url).startsWith('/api/abu-dhabi/flood/')
      && response.status >= 400
    ));
    const criticalRequestFailures = failedRequests.filter(request => (
      apiPath(request.url).startsWith('/api/abu-dhabi/flood/')
      && request.error !== 'net::ERR_ABORTED'
    ));

    assert.deepEqual(stage2ExecutionPosts, [],
      `forbidden live stage-2 execution occurred: ${JSON.stringify(stage2ExecutionPosts)}`);
    assert.deepEqual(stage3ExecutionPosts, [],
      `forbidden live stage-3 execution occurred: ${JSON.stringify(stage3ExecutionPosts)}`);
    assert.equal(rolloutPosts.length, 1,
      `expected exactly one live frozen-GWM rollout POST, got ${rolloutPosts.length}`);
    assert.deepEqual(trainingRequests, [],
      `forbidden training endpoint was called: ${JSON.stringify(trainingRequests)}`);
    assert.deepEqual(criticalHttpErrors, [],
      `flood API returned errors: ${JSON.stringify(criticalHttpErrors)}`);
    assert.deepEqual(criticalRequestFailures, [],
      `flood API request failed: ${JSON.stringify(criticalRequestFailures)}`);
    assert.equal(evidence.stage2.loaded.length, 6, 'not all six stage-2 results loaded');
    assert.equal(evidence.stage3.oneWayLoaded.length, 6, 'not all six stage-3 one-way results loaded');

    evidence.finishedAt = new Date().toISOString();
    evidence.audit = {
      totalRequests: requests.length,
      floodApiResponses: responses.filter(response => apiPath(response.url).startsWith('/api/abu-dhabi/flood/')).length,
      forbiddenStage2ExecutionPosts: stage2ExecutionPosts.length,
      forbiddenStage3ExecutionPosts: stage3ExecutionPosts.length,
      frozenGwmRolloutPosts: rolloutPosts.length,
      trainingRequests: trainingRequests.length,
      criticalHttpErrors,
      criticalRequestFailures,
      consoleErrors,
    };

    const reportPath = path.join(ARTIFACT_DIR, 'five-stage-e2e-report.json');
    fs.writeFileSync(reportPath, `${JSON.stringify(evidence, null, 2)}\n`, 'utf8');
    process.stdout.write(`${JSON.stringify({ ok: true, reportPath, evidence }, null, 2)}\n`);
  } catch (error) {
    const failureScreenshot = path.join(ARTIFACT_DIR, 'failure.png');
    await page.screenshot({ path: failureScreenshot, fullPage: false }).catch(() => {});
    const failureReport = {
      ok: false,
      failedAt: new Date().toISOString(),
      error: error?.stack || String(error),
      evidence,
      requests,
      responses,
      failedRequests,
      consoleErrors,
      failureScreenshot,
    };
    fs.writeFileSync(
      path.join(ARTIFACT_DIR, 'five-stage-e2e-failure.json'),
      `${JSON.stringify(failureReport, null, 2)}\n`,
      'utf8',
    );
    throw error;
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  process.stderr.write(`${error?.stack || error}\n`);
  process.exitCode = 1;
});
