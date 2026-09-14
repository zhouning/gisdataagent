const fs = require('fs');
const path = require('path');
const { chromium } = require('@playwright/test');

const BASE_URL = process.env.GIS_AGENT_E2E_URL || 'http://127.0.0.1:8000';
const USERNAME = process.env.GIS_AGENT_E2E_USERNAME || 'admin';
const PASSWORD = process.env.GIS_AGENT_E2E_PASSWORD || 'admin123';
const OUTPUT_DIR = process.env.GIS_AGENT_E2E_SCREENSHOT_DIR
  || path.resolve(__dirname, 'artifacts/dmt-ontology-workbench');

async function main() {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const consoleErrors = [];
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });

  try {
    const login = await page.context().request.post(`${BASE_URL}/login`, {
      form: { username: USERNAME, password: PASSWORD },
    });
    if (login.status() !== 200) throw new Error(`login failed: ${login.status()}`);
    await page.goto(`${BASE_URL}/ontology-model`, { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await page.locator('.ontology-workbench').waitFor({ state: 'visible', timeout: 30_000 });
    const selector = page.locator('.ontology-profile-select select');
    await selector.waitFor({ state: 'visible', timeout: 30_000 });
    const options = await selector.locator('option').allTextContents();
    if (!options.some(option => option.includes('DMT'))) {
      throw new Error(`DMT ontology profile is missing: ${options}`);
    }

    console.log('select DMT');
    await selector.selectOption('abu-dhabi-dmt-gis');
    await page.getByText('Abu Dhabi DMT 城市与市政 GIS 本体', { exact: true })
      .waitFor({ state: 'visible', timeout: 30_000 });
    const browserShot = path.join(OUTPUT_DIR, 'dmt-ontology-browser-desktop.png');
    await page.screenshot({ path: browserShot, fullPage: true });

    console.log('open modeling');
    await page.getByRole('button', { name: '草稿编辑' }).click();
    const modeling = page.locator('.ontology-modeling-panel');
    await modeling.waitFor({ state: 'visible', timeout: 30_000 });
    const modelingShot = path.join(OUTPUT_DIR, 'dmt-ontology-modeling-desktop.png');
    await page.screenshot({ path: modelingShot, fullPage: true });

    const result = {
      profileOptions: options,
      selectedTitle: await page.locator('.ontology-title').innerText(),
      modelingVisible: await modeling.isVisible(),
      dmtOntologyVisible: options.some(option => option.includes('DMT')),
      browserShot,
      modelingShot,
      consoleErrors: consoleErrors.slice(0, 10),
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
