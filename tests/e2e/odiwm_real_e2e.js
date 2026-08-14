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

async function login(page) {
  const response = await page.context().request.post(`${BASE_URL}/login`, {
    form: { username: USERNAME, password: PASSWORD },
  });
  if (response.status() !== 200) {
    throw new Error(`login failed with HTTP ${response.status()}`);
  }
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  await page.locator('.app-header').waitFor({ state: 'visible', timeout: 30_000 });
}

async function openWorkspace(page) {
  await page.getByRole('button', { name: '数据面板' }).click();
  await page.locator('.data-panel').waitFor({ state: 'visible', timeout: 30_000 });
}

async function main() {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const consoleErrors = [];
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });

  try {
    console.log('login');
    await login(page);
    await openWorkspace(page);

    console.log('verify menu path and irrigation ontology');
    await page.getByRole('button', { name: /标准与语义/ }).click();
    await page.getByRole('button', { name: /语义模型/ }).click();
    await page.getByRole('button', { name: '本体模型' }).click();
    const ontology = page.locator('.ontology-workbench');
    await ontology.waitFor({ state: 'visible', timeout: 30_000 });
    const selector = ontology.locator('.ontology-profile-select select');
    await selector.waitFor({ state: 'visible', timeout: 30_000 });
    const options = await selector.locator('option').allTextContents();
    if (!options.some(option => option.includes('灌区与水利'))) {
      throw new Error(`irrigation ontology is missing from registry selector: ${options}`);
    }
    await selector.selectOption('irrigation-district-water');
    await page.getByText('灌区与水利工程本体', { exact: true })
      .waitFor({ state: 'visible', timeout: 30_000 });
    const ontologyShot = path.join(OUTPUT_DIR, 'irrigation-ontology.png');
    await page.screenshot({ path: ontologyShot });

    const result = {
      menuPath: ['标准与语义', '语义模型', '本体模型'],
      ontologyOptions: options,
      selectedOntology: await selector.inputValue(),
      ontologyShot,
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
