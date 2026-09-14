const fs = require('fs');
const path = require('path');
const { chromium } = require('@playwright/test');

const BASE_URL = process.env.GIS_AGENT_E2E_URL || 'http://127.0.0.1:8000';
const USERNAME = process.env.GIS_AGENT_E2E_USERNAME || 'admin';
const PASSWORD = process.env.GIS_AGENT_E2E_PASSWORD || 'admin123';
const QUESTION = '@Liveability 按设施类型和阶段统计设施数量。';
const OUTPUT_DIR = process.env.GIS_AGENT_E2E_SCREENSHOT_DIR
  || path.join('/tmp', 'gisdataagent-liveability-facility-count-e2e');

async function main() {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const consoleErrors = [];
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });

  try {
    const login = await page.context().request.post(`${BASE_URL}/login`, {
      form: { username: USERNAME, password: PASSWORD },
    });
    if (login.status() !== 200) throw new Error(`login failed: ${login.status()}`);
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await page.getByText('Welcome, Administrator! (admin)', { exact: true }).waitFor({
      state: 'visible', timeout: 45_000,
    });
    const input = page.locator('.chat-input-container textarea');
    await input.waitFor({ state: 'visible', timeout: 30_000 });
    await input.fill(QUESTION);
    await page.waitForFunction(() => {
      const button = document.querySelector('.chat-input-container .btn-send');
      return Boolean(button && !(button instanceof HTMLButtonElement && button.disabled));
    }, undefined, { timeout: 30_000 });
    await page.locator('.chat-input-container .btn-send').click();
    await page.locator('.chat-message.user', { hasText: QUESTION }).waitFor({
      state: 'visible', timeout: 10_000,
    });

    const answer = page.locator('.nl2sql-answer').last();
    try {
      await answer.waitFor({ state: 'visible', timeout: 60_000 });
    } catch (error) {
      const messages = await page.locator('.chat-message').evaluateAll(nodes => nodes.map(node => ({
        className: node.className,
        text: (node.textContent || '').slice(0, 1000),
        metadata: node.getAttribute('data-metadata'),
      })));
      const screenshot = path.join(OUTPUT_DIR, 'facility-count-render-failure.png');
      await page.screenshot({ path: screenshot, fullPage: true });
      throw new Error(`NL2SQL presentation was not rendered: ${JSON.stringify({ messages, screenshot })}`, { cause: error });
    }
    const answerText = (await answer.textContent()) || '';
    if (/需要澄清|未执行 SQL|clarify_before_any_execution/.test(answerText)) {
      throw new Error(`question was incorrectly clarified instead of executed: ${answerText}`);
    }
    const tableButton = answer.getByRole('button', { name: '表格' });
    if (await tableButton.count()) await tableButton.click();
    const rows = answer.locator('.nl2sql-result-table tbody tr');
    await rows.first().waitFor({ state: 'visible', timeout: 30_000 });
    const renderedRows = await rows.count();
    if (renderedRows < 1) throw new Error('facility-count result table is empty');
    const tableText = (await answer.locator('.nl2sql-result-table').textContent()) || '';
    if (!tableText.includes('生命周期阶段') || !tableText.includes('设施类型') || !tableText.includes('数量')) {
      throw new Error(`unexpected facility-count columns: ${tableText}`);
    }

    await answer.locator('.nl2sql-evidence summary').click();
    const evidence = (await answer.locator('.nl2sql-evidence').textContent()) || '';
    for (const required of [
      'LIVEABILITY_FACILITY_COUNT_BY_STAGE_TYPE_V4',
      'liveability_data_20260730/public',
      'abu-dhabi-liveability_data_20260730-v45-',
      'SELECT stage, facility_type',
      'COUNT(facility_uuid)',
    ]) {
      if (!evidence.includes(required)) throw new Error(`missing execution evidence: ${required}`);
    }

    const screenshot = path.join(OUTPUT_DIR, 'facility-count-answer.png');
    await answer.screenshot({ path: screenshot });
    const result = {
      status: consoleErrors.length ? 'failed' : 'passed',
      question: QUESTION,
      renderedRows,
      contractId: 'LIVEABILITY_FACILITY_COUNT_BY_STAGE_TYPE_V4',
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
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
