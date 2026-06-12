import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

/**
 * Professional E2E Test Suite for GIS Data Agent
 * This suite tests the critical path of:
 * Login -> User Query -> Data Result Visualization
 */

const TARGET_URL = process.env.GIS_AGENT_E2E_URL || 'http://127.0.0.1:8000/';
const AUTH_CREDENTIALS = {
  username: process.env.GIS_AGENT_E2E_USER || 'admin',
  password: process.env.GIS_AGENT_E2E_PASSWORD || 'admin'
};
const SCREENSHOT_DIR = process.env.GIS_AGENT_E2E_SCREENSHOT_DIR
  || path.resolve(__dirname, '../screenshots');

test.describe('GIS Data Agent - End-to-End Business Flow', () => {

  // Setup shared test context
  test.beforeEach(async ({ page }) => {
    await page.goto(TARGET_URL, { waitUntil: 'networkidle' });
  });

  test('Critical Path: Authentication and Data Discovery Query', async ({ page } ) => {
    // 1. --- AUTHENTICATION PHASE ---
    console.log('[Test] Starting Authentication Phase...');

    // Locate username/password fields using robust locators (role + name)
    const usernameField = page.getByRole('textbox', { name: '用户名' });
    const passwordField = page.locator('#password');

    await usernameField.fill(AUTH_CREDENTIALS.username);
    await passwordField.fill(AUTH_CREDENTIALS.password);

    // Click the login button
    const loginButton = page.getByRole('button', { name: '登录' });
    await loginButton.click();

    // Verify Login Success by checking for the presence of Dashboard header
    const dashboardHeader = page.locator('.app-header');
    await expect(dashboardHeader).toBeVisible({ timeout: 20000 });
    console.log('[Test] Authentication Successful. Dashboard loaded.');

    // Take a snapshot of the initial logged-in state
    if (!fs.existsSync(SCREENSHOT_DIR)) {
      fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
    }
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'post_login_dashboard.png') });

    // 2. --- INTERACTION PHASE (The "Query" step) ---
    console.log('[Test] Starting Data Query Phase...');

    // Locate the Chat Input Area via role or placeholder
    const chatInput = page.getByRole('textbox', { name: /输入消息/i });
    const queryText = '我有哪些数据？';

    await chatInput.fill(queryText);
    await page.keyboard.press('Enter');

    // 3. --- VERIFICATION PHASE (DOM + Visual) ---
    console.log('[Test] Waiting for Agent response...');

    // Wait for a message container to appear or update
    const messageContainer = page.locator('.message-content').last();
    await messageContainer.waitFor({ state: 'visible', timeout: 45000 });

    // Verification A: DOM Check - Ensure the response is not an error
    const messageText = await messageContainer.innerText();
    console.log(`[Test] Agent Response Detected: "${messageText}"`);

    expect(messageText).not.toBe('');
    if (messageText.includes('错误') || messageText.includes('失败')) {
      throw new Error(`Agent returned an error message: ${messageText}`);
    }

    // Verification B: Visual Check - Capturing the "Evidence" for Multimodal Analysis
    const screenshotPath = path.join(SCREENSHOT_DIR, 'query_result_visual.png');
    await page.screenshot({ path: screenshotPath }); await page.waitForTimeout(5000);
    console.log(`[Test] Visual evidence captured at: ${screenshotPath}`);

    console.log('[Test] E2E Test Scenario Completed Successfully!');
  });
});
