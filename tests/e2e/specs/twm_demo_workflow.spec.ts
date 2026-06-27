import { test, expect, type APIResponse, type Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const TARGET_URL = process.env.GIS_AGENT_E2E_URL || 'http://127.0.0.1:8000/';
const SCREENSHOT_DIR = process.env.GIS_AGENT_E2E_SCREENSHOT_DIR
  || path.resolve(__dirname, '../screenshots');

function uniqueUser() {
  const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  return {
    username: `twm_demo_${suffix}`,
    password: 'TwmDemo12345',
  };
}

async function registerUser(request: any, username: string, password: string) {
  const response = await request.post(new URL('/auth/register', TARGET_URL).toString(), {
    data: {
      username,
      password,
      display_name: 'TWM 演示操作员',
      email: `${username}@example.com`,
    },
  });
  expect(response.status()).toBe(200);
  const payload = await response.json();
  expect(payload.status).toBe('success');
}

async function login(page: Page, username: string, password: string) {
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded' });
  await page.locator('#username').fill(username);
  await page.locator('#password').fill(password);
  await page.getByRole('button', { name: '登录' }).click();
  await expect(page.locator('.app-header')).toBeVisible({ timeout: 30000 });
}

function expectJsonResponse(response: APIResponse, expectedPath: string) {
  expect(response.url()).toContain(expectedPath);
  expect(response.status(), `${expectedPath} returned ${response.status()}`).toBe(200);
}

async function responseJsonOrNull(response: APIResponse) {
  try {
    return await response.json();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message.includes('Request content was evicted from inspector cache')) {
      return null;
    }
    throw error;
  }
}

async function expectNoTwmError(page: Page) {
  await expect(page.locator('.twm-alert.error')).toHaveCount(0);
}

type BBox = [number, number, number, number];

const BISHAN_MULTI_ADMIN_BBOX: BBox = [
  106.15218221100008,
  29.667518609000066,
  106.36753971400003,
  29.886844144000065,
];

function bboxIntersects(a: BBox, b: BBox) {
  return a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1];
}

async function captureLastMapUpdateBbox(page: Page): Promise<BBox> {
  return page.evaluate(() => {
    const bbox: Array<number | null> = [null, null, null, null];
    const update = (coords: any) => {
      if (
        Array.isArray(coords)
        && coords.length >= 2
        && typeof coords[0] === 'number'
        && typeof coords[1] === 'number'
      ) {
        bbox[0] = bbox[0] === null ? coords[0] : Math.min(bbox[0], coords[0]);
        bbox[1] = bbox[1] === null ? coords[1] : Math.min(bbox[1], coords[1]);
        bbox[2] = bbox[2] === null ? coords[0] : Math.max(bbox[2], coords[0]);
        bbox[3] = bbox[3] === null ? coords[1] : Math.max(bbox[3], coords[1]);
        return;
      }
      if (Array.isArray(coords)) {
        for (const item of coords) update(item);
      }
    };
    for (const layer of (window as any).__twmLastMapUpdate?.layers || []) {
      for (const feature of layer.geojsonData?.features || []) {
        update(feature.geometry?.coordinates);
      }
    }
    if (bbox.some(value => value === null)) {
      throw new Error('last map update has no GeoJSON bbox');
    }
    return bbox as BBox;
  });
}

async function captureLastMapUpdateLayerNames(page: Page): Promise<string[]> {
  return page.evaluate(() => ((window as any).__twmLastMapUpdate?.layers || []).map((layer: any) => String(layer.name || '')));
}

function isIgnorableConsoleError(message: string) {
  return message.includes('Failed to load resource')
    || (
      message.includes('Unauthorized')
      && message.includes('/assets/index-')
    );
}

test.describe('TWM prototype demo workflow', () => {
  test('runs the interactive TWM frontend flow from login to planning comparison', async ({ page, request }) => {
    test.setTimeout(8 * 60 * 1000);

    const { username, password } = uniqueUser();
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];

    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });
    page.on('pageerror', (error) => pageErrors.push(error.message));

    await registerUser(request, username, password);
    await login(page, username, password);

    await page.locator('.data-panel-group', { hasText: '智能分析' }).click();
    await page.locator('.data-panel-tab', { hasText: 'TWM' }).click();

    await expect(page.locator('.twm-title')).toContainText('国土空间世界模型', { timeout: 30000 });
    await expect(page.getByRole('tab', { name: '总览地图' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('tab', { name: '数据证据' })).toBeVisible();
    await expect(page.getByRole('tab', { name: '操作推演' })).toBeVisible();
    await expect(page.getByRole('tab', { name: '技术载荷' })).toBeVisible();
    await expect(page.locator('.twm-map-story')).toContainText('地图联动');
    await expect(page.locator('.twm-claim-matrix-panel')).toHaveCount(0);
    await page.evaluate(() => {
      const current = (window as any).__handleMapUpdate;
      (window as any).__twmLastMapUpdate = null;
      (window as any).__handleMapUpdate = (cfg: any) => {
        (window as any).__twmLastMapUpdate = cfg;
        if (typeof current === 'function') return current(cfg);
        return undefined;
      };
    });
    await page.getByRole('tab', { name: '数据证据' }).click();
    await expect(page.locator('.twm-data-browser-panel')).toContainText('数据基础浏览器');
    await expect(page.locator('.twm-data-browser-panel')).toContainText('当前结论');
    await page.getByRole('button', { name: '浏览 璧山多行政单元评估样例' }).click();
    await expect(page.locator('.twm-data-browser-panel')).toContainText('twm_bishan_multi_admin_eval');
    await expect(page.locator('.twm-data-browser-panel')).toContainText('22,401');
    await expect(page.locator('.twm-data-browser-panel')).toContainText('空间图层目录', { timeout: 30000 });
    await expect(page.locator('.twm-data-browser-panel')).toContainText('parcel_current.geojson');
    await expect(page.locator('.twm-data-browser-panel')).toContainText('可直接叠加');
    await expect(page.locator('.twm-data-browser-panel')).toContainText('字段');
    await expect(page.locator('.twm-data-browser-panel')).toContainText('XMMC');
    await expect(page.locator('.twm-data-browser-panel')).toContainText('样例');
    await expect(page.locator('.twm-data-browser-panel')).toContainText('tables/rule_evaluation.csv');
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
    await page.locator('.twm-spatial-catalog-panel').scrollIntoViewIfNeeded();
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'twm_spatial_catalog.png'),
      fullPage: true,
    });
    const [singleLayerPreviewResponse] = await Promise.all([
      page.waitForResponse((response) => (
        response.url().includes('/api/twm/data-foundation-map-preview/twm_bishan_multi_admin_eval')
        && response.url().includes('max_features_per_layer=all')
        && response.url().includes('layer=synthetic_projects.geojson')
        && response.request().method() === 'GET'
      ), { timeout: 60000 }),
      page.getByRole('button', { name: '上图 synthetic_projects.geojson' }).click(),
    ]);
    expectJsonResponse(singleLayerPreviewResponse, '/data-foundation-map-preview/');
    const singleLayerPreviewPayload = await responseJsonOrNull(singleLayerPreviewResponse);
    if (singleLayerPreviewPayload) {
      expect(singleLayerPreviewPayload.layer_count).toBe(1);
      expect(singleLayerPreviewPayload.total_source_feature_count).toBe(90);
      expect(singleLayerPreviewPayload.total_preview_feature_count).toBe(90);
      expect(singleLayerPreviewPayload.map_overlay_readiness?.status).toBe('ready');
      expect(singleLayerPreviewPayload.layers?.[0]?.name).toBe('synthetic_projects.geojson');
    }
    await expect(page.locator('.twm-data-browser-panel')).toContainText('已联动图层 synthetic_projects.geojson');
    expect(bboxIntersects(await captureLastMapUpdateBbox(page), BISHAN_MULTI_ADMIN_BBOX)).toBe(true);
    const dataMapPreviewResponsePromise = page.waitForResponse((response) => (
      response.url().includes('/api/twm/data-foundation-map-preview/twm_bishan_multi_admin_eval')
      && response.url().includes('max_features_per_layer=all')
      && response.request().method() === 'GET'
    ), { timeout: 60000 });
    await page.getByRole('button', { name: '全量加载空间数据' }).click();
    const dataMapPreviewResponse = await dataMapPreviewResponsePromise;
    expectJsonResponse(dataMapPreviewResponse, '/data-foundation-map-preview/');
    const dataMapPreviewPayload = await responseJsonOrNull(dataMapPreviewResponse);
    if (dataMapPreviewPayload) {
      expect(dataMapPreviewPayload.layers?.length).toBeGreaterThan(0);
      expect(dataMapPreviewPayload.delivery_mode).toBe('full_geojson');
      expect(dataMapPreviewPayload.total_preview_feature_count).toBe(dataMapPreviewPayload.total_source_feature_count);
      expect(dataMapPreviewPayload.map_overlay_readiness?.status).toBe('ready');
      expect(dataMapPreviewPayload.map_overlay_readiness?.blocked_layer_count).toBe(0);
      expect(dataMapPreviewPayload.layers.every((layer: any) => layer.crs_diagnostic?.map_overlay_ready === true)).toBe(true);
    }
    await expect(page.locator('.twm-data-browser-panel')).toContainText('已全量联动');
    await expect(page.locator('.twm-data-browser-panel')).toContainText('坐标诊断');
    await expect(page.locator('.twm-data-browser-panel')).toContainText('可直接叠加');
    expect(bboxIntersects(await captureLastMapUpdateBbox(page), BISHAN_MULTI_ADMIN_BBOX)).toBe(true);
    await page.getByRole('button', { name: '隐藏图层 parcel_current.geojson' }).click();
    let dataFoundationLayerNames = await captureLastMapUpdateLayerNames(page);
    expect(dataFoundationLayerNames).toHaveLength(5);
    expect(dataFoundationLayerNames.some(name => name.includes('parcel_current.geojson'))).toBe(false);
    await page.getByRole('button', { name: '显示图层 parcel_current.geojson' }).click();
    dataFoundationLayerNames = await captureLastMapUpdateLayerNames(page);
    expect(dataFoundationLayerNames).toHaveLength(6);
    expect(dataFoundationLayerNames.some(name => name.includes('parcel_current.geojson'))).toBe(true);
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'twm_data_browser.png'),
      fullPage: true,
    });
    await page.evaluate(() => {
      (window as any).__twmLastMapUpdate = null;
    });
    await page.getByRole('button', { name: '浏览 一张图村庄规划标准样例' }).click();
    await expect(page.locator('.twm-data-browser-panel')).toContainText('需 CRS 转换');
    const projectedPreviewResponsePromise = page.waitForResponse((response) => (
      response.url().includes('/api/twm/data-foundation-map-preview/twm_one_map_village_standard_sample')
      && response.url().includes('max_features_per_layer=all')
      && response.request().method() === 'GET'
    ), { timeout: 60000 });
    await page.getByRole('button', { name: '全量加载空间数据' }).click();
    const projectedPreviewResponse = await projectedPreviewResponsePromise;
    expectJsonResponse(projectedPreviewResponse, '/data-foundation-map-preview/');
    const projectedPreviewPayload = await responseJsonOrNull(projectedPreviewResponse);
    if (projectedPreviewPayload) {
      expect(projectedPreviewPayload.map_overlay_readiness?.status).toBe('blocked');
      expect(projectedPreviewPayload.map_overlay_readiness?.warning_codes).toContain('requires_crs_conversion');
      expect(projectedPreviewPayload.layers.some((layer: any) => layer.crs_diagnostic?.map_overlay_ready === false)).toBe(true);
    }
    await expect(page.locator('.twm-data-browser-panel')).toContainText('需 CRS 转换');
    expect(await page.evaluate(() => (window as any).__twmLastMapUpdate)).toBeNull();
    await page.getByRole('button', { name: '浏览 璧山多行政单元评估样例' }).click();
    await expect(page.locator('.twm-data-browser-panel')).toContainText('twm_bishan_multi_admin_eval');
    await expect(page.locator('.twm-claim-matrix-panel')).toContainText('生产声明');
    await expect(page.locator('.twm-data-foundation-panel')).toContainText('生产观察历史');
    await expect(page.locator('.twm-data-foundation-panel')).toContainText('完整数据清单');
    await expect(page.locator('.twm-data-foundation-panel')).toContainText('twm_bishan_multi_admin_eval');
    await expect(page.locator('.twm-data-foundation-panel')).toContainText('tables/approval_records.csv');
    await expect(page.locator('.twm-data-foundation-panel')).toContainText('问题-数据适配');
    await expect(page.locator('.twm-data-foundation-panel')).toContainText('自动审批通过/不通过');
    await expect(page.locator('.twm-data-foundation-panel')).toContainText('来源报告');
    await expect(page.locator('.twm-data-foundation-panel')).toContainText('twm_data_foundation_health.md');
    await page.locator('.twm-data-detail-section', { hasText: '完整数据清单' }).scrollIntoViewIfNeeded();
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'twm_data_evidence.png'),
      fullPage: true,
    });
    await page.getByRole('tab', { name: '操作推演' }).click();
    await expect(page.locator('.twm-section', { hasText: '工作空间' })).toBeVisible();
    await expect(page.locator('.twm-section', { hasText: '业务推演' })).toBeVisible();
    await page.getByRole('tab', { name: '总览地图' }).click();
    await page.getByRole('button', { name: '定位审查区' }).click();
    await expect(page.locator('.twm-map-story')).toContainText('已联动：审查区定位');
    expect(bboxIntersects(await captureLastMapUpdateBbox(page), BISHAN_MULTI_ADMIN_BBOX)).toBe(true);
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'twm_overview_locate.png'),
      fullPage: true,
    });
    await expectNoTwmError(page);

    await page.getByRole('tab', { name: '操作推演' }).click();
    await page.getByRole('button', { name: '璧山演示' }).click();
    const projectName = `TWM 自然资源部演示 ${Date.now()}`;
    await page.locator('label').filter({ hasText: '项目名' }).locator('input').fill(projectName);

    const createResponsePromise = page.waitForResponse((response) => (
      response.url().endsWith('/api/twm/projects') && response.request().method() === 'POST'
    ), { timeout: 30000 });
    await page.getByRole('button', { name: '创建项目' }).click();
    const createResponse = await createResponsePromise;
    expectJsonResponse(createResponse, '/api/twm/projects');
    const projectPayload = await createResponse.json();
    expect(projectPayload.id).toBeTruthy();
    await expect(page.locator('label').filter({ hasText: '选择项目' }).locator('select')).toContainText(projectName, { timeout: 30000 });
    await expectNoTwmError(page);

    const buildResponsePromise = page.waitForResponse((response) => (
      response.url().includes('/api/twm/projects/')
      && response.url().endsWith('/build-state')
      && response.request().method() === 'POST'
    ), { timeout: 90000 });
    await page.getByRole('button', { name: '构建状态' }).click();
    const buildResponse = await buildResponsePromise;
    expectJsonResponse(buildResponse, '/build-state');
    const buildPayload = await responseJsonOrNull(buildResponse);
    if (buildPayload) {
      expect(buildPayload.state_version?.id).toBeTruthy();
      expect(buildPayload.state_version?.object_count).toBeGreaterThan(100);
      expect(buildPayload.state_version?.relation_count).toBeGreaterThan(100);
    }
    await expect(page.locator('.twm-state-summary')).toContainText('对象', { timeout: 30000 });
    await expect(page.locator('.twm-state-summary')).toContainText('关系', { timeout: 30000 });
    await expectNoTwmError(page);

    const evaluateResponsePromise = page.waitForResponse((response) => (
      response.url().includes('/api/twm/states/')
      && response.url().endsWith('/evaluate-rules')
      && response.request().method() === 'POST'
    ), { timeout: 60000 });
    await page.getByRole('button', { name: '检查业务规则' }).click();
    const evaluateResponse = await evaluateResponsePromise;
    expectJsonResponse(evaluateResponse, '/evaluate-rules');
    const evaluatePayload = await responseJsonOrNull(evaluateResponse);
    if (evaluatePayload) {
      expect(evaluatePayload.summary?.hit_count).toBeGreaterThan(0);
      expect(evaluatePayload.summary?.evidence_item_count).toBeGreaterThan(0);
    }
    await expect(page.locator('.twm-hit-list')).toContainText(/TWM-|rule|空间|风险/i, { timeout: 30000 });
    await page.getByRole('tab', { name: '总览地图' }).click();
    await expect(page.locator('.twm-map-story')).toContainText('已联动：风险命中');
    expect(bboxIntersects(await captureLastMapUpdateBbox(page), BISHAN_MULTI_ADMIN_BBOX)).toBe(true);
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'twm_overview_risk.png'),
      fullPage: true,
    });
    await page.getByRole('tab', { name: '操作推演' }).click();
    await expectNoTwmError(page);

    const forecastResponsePromise = page.waitForResponse((response) => (
      response.url().includes('/api/twm/states/')
      && response.url().endsWith('/forecast')
      && response.request().method() === 'POST'
    ), { timeout: 60000 });
    await page.getByRole('button', { name: '风险预测' }).click();
    const forecastResponse = await forecastResponsePromise;
    expectJsonResponse(forecastResponse, '/forecast');
    const forecastPayload = await responseJsonOrNull(forecastResponse);
    if (forecastPayload) {
      expect(forecastPayload.forecast || forecastPayload.constraint_violation_probability !== undefined).toBeTruthy();
    }
    await expect(page.locator('.twm-results-grid')).toContainText('规划收益', { timeout: 30000 });
    await expectNoTwmError(page);

    const validationResponsePromise = page.waitForResponse((response) => (
      response.url().includes('/api/twm/states/')
      && response.url().endsWith('/validation-report')
      && response.request().method() === 'POST'
    ), { timeout: 60000 });
    await page.getByRole('button', { name: '验证口径' }).click();
    const validationResponse = await validationResponsePromise;
    expectJsonResponse(validationResponse, '/validation-report');
    const validationPayload = await responseJsonOrNull(validationResponse);
    if (validationPayload) {
      expect(validationPayload.summary?.claim_ladder || validationPayload.stages).toBeTruthy();
    }
    await expect(page.locator('.twm-stage-list')).toBeVisible({ timeout: 30000 });
    await expectNoTwmError(page);

    const auditResponsePromise = page.waitForResponse((response) => (
      response.url().includes('/api/twm/states/')
      && response.url().endsWith('/audit-report')
      && response.request().method() === 'GET'
    ), { timeout: 60000 });
    await page.getByRole('button', { name: '证据审计' }).click();
    const auditResponse = await auditResponsePromise;
    expectJsonResponse(auditResponse, '/audit-report');
    const auditPayload = await responseJsonOrNull(auditResponse);
    if (auditPayload) {
      expect(auditPayload.evidence_gate_summary?.evidence_item_count).toBeGreaterThan(0);
    }
    await expectNoTwmError(page);

    const candidatesResponsePromise = page.waitForResponse((response) => (
      response.url().includes('/api/twm/states/')
      && response.url().endsWith('/farmland-layout-candidates')
      && response.request().method() === 'POST'
    ), { timeout: 60000 });
    await page.getByRole('button', { name: '载入候选' }).click();
    const candidatesResponse = await candidatesResponsePromise;
    expectJsonResponse(candidatesResponse, '/farmland-layout-candidates');
    const candidatesPayload = await responseJsonOrNull(candidatesResponse);
    if (candidatesPayload) {
      expect(candidatesPayload.summary?.candidate_count).toBeGreaterThan(0);
    }
    await expectNoTwmError(page);

    const beamResponsePromise = page.waitForResponse((response) => (
      response.url().includes('/api/twm/states/')
      && response.url().endsWith('/farmland-layout-optimization-beam-plan')
      && response.request().method() === 'POST'
    ), { timeout: 60000 });
    await page.getByRole('button', { name: '方案比选' }).click();
    const beamResponse = await beamResponsePromise;
    expectJsonResponse(beamResponse, '/farmland-layout-optimization-beam-plan');
    const beamPayload = await responseJsonOrNull(beamResponse);
    if (beamPayload) {
      const selectedCandidate = beamPayload.beam_plan?.selected?.candidate_id
        || beamPayload.selected?.candidate_id
        || beamPayload.selection_audit?.selected_candidate_id
        || beamPayload.top_actions?.[0]?.candidate_id;
      expect(selectedCandidate).toBeTruthy();
    }
    await expect(page.locator('.twm-results-grid')).toContainText('推荐方案', { timeout: 30000 });
    await page.getByRole('tab', { name: '总览地图' }).click();
    await expect(page.locator('.twm-map-story')).toContainText('已联动：推荐方案');
    expect(bboxIntersects(await captureLastMapUpdateBbox(page), BISHAN_MULTI_ADMIN_BBOX)).toBe(true);
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'twm_overview_plan.png'),
      fullPage: true,
    });
    await expectNoTwmError(page);

    await page.getByRole('tab', { name: '数据证据' }).click();
    const comparisonResponsePromise = page.waitForResponse((response) => (
      response.url().endsWith('/api/twm/baseline-comparison-report')
      && response.request().method() === 'POST'
    ), { timeout: 60000 });
    await page.getByRole('button', { name: '基线对比' }).click();
    const comparisonResponse = await comparisonResponsePromise;
    expectJsonResponse(comparisonResponse, '/api/twm/baseline-comparison-report');
    const comparisonPayload = await responseJsonOrNull(comparisonResponse);
    if (comparisonPayload) {
      expect(comparisonPayload.metric_comparisons?.length).toBeGreaterThan(0);
    }
    await expect(page.locator('.twm-baseline-report')).toContainText(/TWM|基线/, { timeout: 30000 });
    await expectNoTwmError(page);

    await page.getByRole('tab', { name: '总览地图' }).click();
    await expect(page.locator('.twm-map-story')).toContainText('已联动：推荐方案');

    await page.getByRole('tab', { name: '技术载荷' }).click();
    await expect(page.locator('.twm-json-panel')).toContainText('最新技术载荷', { timeout: 30000 });
    await page.locator('.twm-json-panel summary').click();
    await expect(page.locator('.twm-json-panel pre')).toContainText(/[{}]|schema|status/, { timeout: 30000 });
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'twm_payload.png'),
      fullPage: true,
    });

    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'twm_demo_workflow.png'),
      fullPage: true,
    });

    await expect.poll(() => pageErrors, { timeout: 1000 }).toEqual([]);
    expect(consoleErrors.filter((item) => !isIgnorableConsoleError(item))).toEqual([]);
  });
});
