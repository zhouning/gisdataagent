const assert = require('node:assert/strict');
const { chromium } = require('@playwright/test');

const BASE_URL = process.env.GIS_AGENT_E2E_URL || 'http://127.0.0.1:8000';

function assertCleanEnglish(value, label) {
  assert.ok(!value.includes('model metadata'), `${label} contains the legacy placeholder: ${value}`);
  assert.ok(!value.includes('untranslated field'), `${label} contains an untranslated-field placeholder: ${value}`);
  assert.ok(!/[\u3400-\u9fff]/u.test(value), `${label} contains untranslated Chinese: ${value}`);
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();
  try {
    const login = await context.request.post(`${BASE_URL}/login`, {
      form: { username: 'admin', password: 'admin123' },
    });
    assert.equal(login.status(), 200);
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await page.locator('.app-header').waitFor({ state: 'visible', timeout: 60_000 });
    await page.locator('.data-panel-group', { hasText: /Analysis|分析|智能分析/ }).first().click();
    const worldModelSection = page.locator('.data-panel-section', { hasText: /World Model|世界模型/ }).first();
    if (await worldModelSection.count()) await worldModelSection.click();
    await page.locator('.data-panel-tab', { hasText: '阿布扎比 · 暴雨内涝世界模型' }).click();

    const workbench = page.locator('.abu-flood-tab');
    await workbench.waitFor({ state: 'visible', timeout: 60_000 });
    await page.locator('.language-switcher select').selectOption('en-US');
    await workbench.locator('.abu-flood-stage', { hasText: /2D surface hydrodynamics|二维地表水动力/ }).click();

    const detail = workbench.locator('.abu-flood-detail-panel');
    await detail.getByRole('tab', { name: '2D model invocation' }).click();
    const invocationText = await detail.locator('.abu-flood-surface-workspace').innerText();
    assertCleanEnglish(invocationText, 'phase-3 invocation UI');
    assert.ok(invocationText.includes('Solver and 1D input'));
    assert.ok(invocationText.includes('Terrain, grid and roughness'));
    assert.ok(invocationText.includes('Exchange and double-counting controls'));
    assert.ok(invocationText.includes('Boundary and run settings'));
    assert.ok(invocationText.includes('Submit 2D calculation'));

    await detail.getByRole('tab', { name: 'Precomputed results' }).click();
    const resultText = await detail.locator('.abu-flood-surface-workspace').innerText();
    assertCleanEnglish(resultText, 'phase-3 precomputed-result UI');
    assert.ok(resultText.includes('Registered 2D results'));
    assert.ok(resultText.includes('Result source'));
    assert.ok(resultText.includes('Registered-result run receipt'));
    assert.ok(resultText.includes('Capability boundary'));

    const load = detail.getByRole('button', { name: 'Load onto map' });
    await load.click();
    await page.waitForFunction(() => window.__lastMapUpdate?.summary?.source_status === 'customer_dtm5m_citywide_2d_result', undefined, { timeout: 120_000 });
    const presentation = await page.evaluate(() => {
      const update = window.__lastMapUpdate || {};
      return {
        summary: update.summary,
        layers: (update.layers || []).map(layer => ({
          name: layer.name,
          legend_title: layer.legend_title,
          tooltip_labels: layer.tooltip_labels,
        })),
      };
    });
    assert.ok(!JSON.stringify(presentation).includes('model metadata'), 'phase-3 raw map contract contains the legacy placeholder');

    const map3d = page.locator('.map-3d-container');
    await map3d.waitFor({ state: 'visible', timeout: 120_000 });
    await map3d.getByRole('button', { name: 'Layers' }).click();
    const renderedMapText = await map3d.innerText();
    assertCleanEnglish(renderedMapText, 'phase-3 rendered map UI');
    assert.ok(renderedMapText.includes('2D result · Customer 5 m DTM citywide land-surface maximum flood depth · 100-year return period'));
    assert.ok(renderedMapText.includes('Citywide dynamic land-surface 2D flood depth (m) · customer DTM primary result'));

    process.stdout.write(`${JSON.stringify({
      ok: true,
      invocationHasLegacyPlaceholder: invocationText.includes('model metadata'),
      resultsHaveLegacyPlaceholder: resultText.includes('model metadata'),
      mapHasLegacyPlaceholder: renderedMapText.includes('model metadata'),
      renderedMapHasChinese: /[\u3400-\u9fff]/u.test(renderedMapText),
    }, null, 2)}\n`);
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
