const fs = require('fs');
const path = require('path');
const { chromium } = require('@playwright/test');

const BASE_URL = process.env.GIS_AGENT_E2E_URL || 'http://127.0.0.1:8000';
const USERNAME = process.env.GIS_AGENT_E2E_USERNAME || 'admin';
const PASSWORD = process.env.GIS_AGENT_E2E_PASSWORD || 'admin123';
const OUTPUT_DIR = process.env.GIS_AGENT_E2E_SCREENSHOT_DIR
  || path.join('/tmp', 'gisdataagent-semantic-governance-e2e');

async function main() {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
  const consoleErrors = [];
  const governanceResponses = [];
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('response', response => {
    if (response.url().includes('/api/semantic/governance/')) {
      governanceResponses.push({ url: response.url(), status: response.status() });
    }
  });

  try {
    const login = await page.context().request.post(`${BASE_URL}/login`, {
      form: { username: USERNAME, password: PASSWORD },
    });
    if (login.status() !== 200) throw new Error(`login failed: ${login.status()}`);
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await page.locator('.app-header').waitFor({ state: 'visible', timeout: 30_000 });
    await page.getByRole('button', { name: '数据面板' }).click();
    await page.locator('.data-panel').waitFor({ state: 'visible', timeout: 30_000 });
    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent('gda-workspace-update', { detail: { tab: 'semantic' } }));
    });

    const semanticTab = page.locator('.semantic-layer-tab');
    await semanticTab.waitFor({ state: 'visible', timeout: 30_000 });
    await semanticTab.getByRole('button', { name: /业务模型/ }).click();
    const panel = page.locator('.abu-admin-panel');
    await panel.waitFor({ state: 'visible', timeout: 30_000 });
    await panel.getByRole('heading', { name: '指标治理总览' }).waitFor({ state: 'visible' });
    await panel.getByText('合同总数').waitFor({ state: 'visible' });
    await panel.getByText('180', { exact: true }).first().waitFor({ state: 'visible' });
    await panel.getByText(/abu-dhabi-liveability_data_20260730-v45-/).waitFor({ state: 'visible' });

    await panel.locator('select').selectOption('metric_contracts');
    const contractId = 'LIVEABILITY_FACILITY_COUNT_BY_STAGE_TYPE_V4';
    const searchInput = panel.locator('.abu-config-search input');
    await searchInput.fill(contractId);
    const searchResponse = page.waitForResponse(response => (
      response.url().includes('/api/semantic/governance/metric_contracts?')
      && new URL(response.url()).searchParams.get('search') === contractId
    ));
    await panel.locator('.abu-config-search button').click();
    await searchResponse;
    await panel.getByText('LIVEABILITY_FACILITY_COUNT_BY_STAGE_TYPE_V4', { exact: true })
      .waitFor({ state: 'visible', timeout: 30_000 });
    await panel.getByRole('button', { name: '新建' }).click();
    const editor = panel.locator('.abu-admin-editor');
    await editor.waitFor({ state: 'visible', timeout: 10_000 });
    await editor.getByText('新建指标合同', { exact: true }).waitFor({ state: 'visible' });
    await editor.getByRole('button', { name: '取消' }).click();
    await editor.waitFor({ state: 'hidden', timeout: 10_000 });

    const screenshot = path.join(OUTPUT_DIR, 'metric-governance.png');
    await panel.screenshot({ path: screenshot });
    const failedRequests = governanceResponses.filter(response => response.status >= 400);
    const result = {
      status: failedRequests.length || consoleErrors.length ? 'failed' : 'passed',
      metricContractVisible: true,
      metricContractId: contractId,
      governanceRequests: governanceResponses,
      failedRequests,
      consoleErrors,
      screenshot,
    };
    console.log(JSON.stringify(result, null, 2));
    if (failedRequests.length || consoleErrors.length) process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
