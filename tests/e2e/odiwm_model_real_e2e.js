const fs = require('fs');
const path = require('path');
const { chromium } = require('@playwright/test');

const BASE_URL = process.env.GIS_AGENT_E2E_URL || 'http://127.0.0.1:8000';
const USERNAME = process.env.GIS_AGENT_E2E_USERNAME;
const PASSWORD = process.env.GIS_AGENT_E2E_PASSWORD;
if (!USERNAME || !PASSWORD) {
  throw new Error('GIS_AGENT_E2E_USERNAME and GIS_AGENT_E2E_PASSWORD are required');
}
const OUTPUT_DIR = process.env.GIS_AGENT_E2E_SCREENSHOT_DIR
  || path.resolve(__dirname, 'artifacts/odiwm-real-e2e');

async function main() {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', message => {
    if (message.type() === 'error') {
      consoleErrors.push(message.text());
      console.error(`browser console: ${message.text()}`);
    }
  });
  page.on('pageerror', error => console.error(`browser pageerror: ${error.stack || error.message}`));
  page.on('response', response => {
    if (response.url().includes('/api/irrigation-world-model/')) {
      console.log(`API ${response.request().method()} ${response.status()} ${response.url()}`);
    }
  });
  page.on('requestfailed', request => {
    if (request.url().includes('/api/irrigation-world-model/')) {
      console.error(`API failed ${request.url()}: ${request.failure()?.errorText}`);
    }
  });

  try {
    console.log('authenticate');
    const loginResponse = await context.request.post(`${BASE_URL}/login`, {
      form: { username: USERNAME, password: PASSWORD },
    });
    if (loginResponse.status() !== 200) {
      throw new Error(`login failed with HTTP ${loginResponse.status()}`);
    }

    console.log('open standalone workspace');
    const pageResponse = await page.goto(`${BASE_URL}/odiwm-demo`, {
      waitUntil: 'domcontentloaded',
      timeout: 8_000,
    });
    console.log(`workspace HTTP ${pageResponse?.status()} URL ${page.url()}`);
    if (pageResponse?.status() !== 200) {
      throw new Error(`ODIWM workspace returned HTTP ${pageResponse?.status()}`);
    }

    const workspace = page.locator('.odiwm-demo-shell');
    await workspace.waitFor({ state: 'visible', timeout: 8_000 });
    console.log('workspace mounted');
    try {
      await page.getByRole('button', { name: '运行推演' })
        .waitFor({ state: 'visible', timeout: 8_000 });
    } catch (error) {
      console.error(`workspace content: ${(await workspace.innerText()).slice(0, 500)}`);
      throw error;
    }
    const runId = workspace.locator('.odiwm-context-card').nth(3).locator('strong');
    const runIdBefore = await runId.innerText();
    const responsePromise = page.waitForResponse(response => (
      response.request().method() === 'POST'
      && response.url().endsWith('/api/irrigation-world-model/run')
    ), { timeout: 8_000 });

    console.log(`click run ${runIdBefore}`);
    await page.getByRole('button', { name: '运行推演' }).click();
    const runResponse = await responsePromise;
    console.log(`run HTTP ${runResponse.status()}`);
    const responsePayload = await runResponse.json();
    if (runResponse.status() !== 201) {
      throw new Error(`world-model run failed with HTTP ${runResponse.status()}`);
    }

    const runIdAfter = responsePayload?.run?.run_id;
    await page.waitForFunction(expected => {
      const current = document.querySelector('.odiwm-context-card:nth-child(4) strong');
      return current?.textContent?.trim() === expected;
    }, runIdAfter, { timeout: 8_000 });

    const model = responsePayload.run.model;
    const evidence = model.numerical_evidence;
    if (model.model_id !== 'manning-kinematic-storage-network') {
      throw new Error(`unexpected model: ${model.model_id}`);
    }
    if (evidence.timestep_count < 1 || evidence.operator_admitted !== false) {
      throw new Error(`invalid numerical evidence: ${JSON.stringify(evidence)}`);
    }
    if (runIdAfter === runIdBefore) {
      throw new Error(`run id did not change: ${runIdBefore}`);
    }

    const screenshot = path.join(OUTPUT_DIR, 'irrigation-world-model-run.png');
    await page.screenshot({ path: screenshot });
    const result = {
      loginHttpStatus: loginResponse.status(),
      runHttpStatus: runResponse.status(),
      runIdBefore,
      runIdAfter,
      modelId: model.model_id,
      modelClass: model.model_class,
      timestepCount: evidence.timestep_count,
      runtimeMs: evidence.runtime_ms,
      operatorAdmitted: evidence.operator_admitted,
      selectedCandidate: responsePayload.run.planner.selected_mode,
      maximumResidualVolumeM3: Math.max(...responsePayload.run.results.map(result => (
        Math.abs(result.residualVolumeM3)
      ))),
      screenshot,
      consoleErrors,
    };
    console.log(JSON.stringify(result, null, 2));
    if (consoleErrors.length) process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
