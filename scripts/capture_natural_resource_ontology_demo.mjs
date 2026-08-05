import { createHmac } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import process from 'node:process';
import { chromium } from 'playwright';

const baseUrl = process.env.DEMO_BASE_URL || 'http://127.0.0.1:5175';
const secret = process.env.CHAINLIT_AUTH_SECRET || 'local_ontology_demo_secret_20260804_replace_in_production';
const outputDir = process.env.DEMO_CAPTURE_DIR || 'docs/reports/natural_resource_ontology_demo_acceptance';

function base64url(value) {
  return Buffer.from(JSON.stringify(value)).toString('base64url');
}

function demoToken(role = 'analyst', identifier = 'ontology-demo') {
  const now = Math.floor(Date.now() / 1000);
  const header = base64url({ alg: 'HS256', typ: 'JWT' });
  const payload = base64url({
    identifier,
    display_name: role === 'admin' ? '平台管理员' : '本体演示用户',
    metadata: { role },
    iat: now,
    exp: now + 60 * 60,
  });
  const signature = createHmac('sha256', secret).update(`${header}.${payload}`).digest('base64url');
  return `${header}.${payload}.${signature}`;
}

async function openDemo(page) {
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
  await page.locator('.app-container').waitFor({ timeout: 20_000 });
  const mobileData = page.locator('.mobile-tab-btn').filter({ hasText: '数据' });
  if (await mobileData.isVisible().catch(() => false)) await mobileData.click();
  await page.locator('button.data-panel-group').filter({ hasText: '智能分析' }).click();
  await page.locator('button.data-panel-tab').filter({ hasText: '本体应用' }).click();
  await page.locator('.nr-demo-shell, .nr-demo-state').waitFor({ timeout: 20_000 });
  const errorState = page.locator('.nr-demo-state.error');
  if (await errorState.isVisible().catch(() => false)) {
    throw new Error(`demo load failed: ${await errorState.textContent()}`);
  }
  await page.locator('.nr-demo-value-journey').waitFor();
}

async function diagnostics(page) {
  return page.evaluate(() => {
    const visible = (element) => {
      const style = getComputedStyle(element);
      const box = element.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0;
    };
    const clipped = [...document.querySelectorAll('.nr-demo-shell button, .nr-demo-journey-grid article, .nr-demo-inline-kpis > div, .nr-demo-finding, .nr-demo-quality-grid > div')]
      .filter(visible)
      .filter((element) => element.scrollWidth > element.clientWidth + 3)
      .map((element) => ({ text: element.textContent?.trim().slice(0, 80), client: element.clientWidth, scroll: element.scrollWidth }));
    return {
      viewport: [innerWidth, innerHeight],
      horizontalOverflow: document.documentElement.scrollWidth - innerWidth,
      clipped,
      errorBoundary: document.querySelectorAll('.error-boundary').length,
      mapPaths: document.querySelectorAll('.leaflet-overlay-pane svg path').length,
      mapTiles: [...document.querySelectorAll('.leaflet-tile-pane img')].filter(visible).length,
      demoTextLength: document.querySelector('.nr-demo-shell')?.textContent?.trim().length || 0,
    };
  });
}

await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1728, height: 1050 }, deviceScaleFactor: 1 });
await context.addCookies([{ name: 'access_token', value: demoToken(), url: baseUrl, httpOnly: true, sameSite: 'Lax' }]);
const page = await context.newPage();
const consoleErrors = [];
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text());
});
page.on('pageerror', (error) => consoleErrors.push(error.message));

await openDemo(page);
await page.waitForTimeout(1200);
await page.screenshot({ path: `${outputDir}/01-heping-ready-desktop.png`, fullPage: true });

await page.getByRole('button', { name: '执行语义分析' }).click();
await page.getByText('分析完成', { exact: true }).waitFor({ timeout: 12_000 });
await page.screenshot({ path: `${outputDir}/02-heping-results-desktop.png`, fullPage: true });
const desktopResults = await diagnostics(page);

await page.locator('button[title="查看证据"]').first().click();
await page.getByText('版本化证据', { exact: true }).waitFor({ timeout: 10_000 });
await page.screenshot({ path: `${outputDir}/03-heping-evidence-desktop.png`, fullPage: true });
const desktopEvidence = await diagnostics(page);

await page.locator('.nr-demo-scenario-switch button').filter({ hasText: '土地利用结构调整' }).click();
await page.getByText(/让统计表中的地类变化能够回到具体地块/).waitFor({ timeout: 12_000 });
await page.getByRole('button', { name: '执行语义分析' }).click();
await page.getByText(/结构表显示农用地净增 9\.06 公顷/).waitFor({ timeout: 12_000 });
await page.screenshot({ path: `${outputDir}/04-banzhu-adjustment-desktop.png`, fullPage: true });
const desktopBanzhu = await diagnostics(page);

await page.setViewportSize({ width: 430, height: 932 });
await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
await openDemo(page);
await page.waitForTimeout(900);
await page.screenshot({ path: `${outputDir}/05-heping-ready-mobile.png`, fullPage: true });
const mobileData = await diagnostics(page);

await page.locator('.mobile-tab-btn').filter({ hasText: '地图' }).click();
await page.locator('.leaflet-container').waitFor({ timeout: 10_000 });
await page.waitForTimeout(800);
await page.screenshot({ path: `${outputDir}/06-heping-map-mobile.png`, fullPage: true });
const mobileMap = await diagnostics(page);

await page.setViewportSize({ width: 1728, height: 1050 });
await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
await page.locator('.app-container').waitFor({ timeout: 20_000 });
await page.locator('button.data-panel-group').filter({ hasText: '智能分析' }).click();
await page.locator('button.data-panel-tab').filter({ hasText: '本体模型' }).click();
await page.locator('.ontology-workbench').waitFor({ timeout: 20_000 });
await page.locator('.ontology-header').waitFor();
await page.waitForTimeout(900);
await page.screenshot({ path: `${outputDir}/07-ontology-model-desktop.png`, fullPage: true });
const ontologyModel = await page.evaluate(() => ({
  horizontalOverflow: document.documentElement.scrollWidth - innerWidth,
  errorBoundary: document.querySelectorAll('.error-boundary').length,
  nodeCount: document.querySelectorAll('.ontology-node').length,
  headerBackground: getComputedStyle(document.querySelector('.ontology-header')).backgroundColor,
  platformBackground: getComputedStyle(document.querySelector('.app-header')).backgroundColor,
}));

const adminContext = await browser.newContext({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1 });
await adminContext.addCookies([{ name: 'access_token', value: demoToken('admin', 'ontology-admin'), url: baseUrl, httpOnly: true, sameSite: 'Lax' }]);
const adminPage = await adminContext.newPage();
adminPage.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text());
});
adminPage.on('pageerror', (error) => consoleErrors.push(error.message));
await adminPage.route('**/api/platform/branding', route => route.fulfill({
  status: 200,
  contentType: 'application/json',
  body: JSON.stringify({
    platform_name: 'Geospatial Data Agent',
    platform_subtitle: 'AI-Native Geospatial Data Platform',
    updated_by: null,
    updated_at: null,
  }),
}));
await adminPage.route('**/api/admin/platform-branding', async route => {
  const values = route.request().postDataJSON();
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ ...values, updated_by: 'ontology-admin', updated_at: new Date().toISOString() }),
  });
});
await adminPage.goto(baseUrl, { waitUntil: 'domcontentloaded' });
await adminPage.locator('.app-container').waitFor({ timeout: 20_000 });
await adminPage.locator('.header-admin-btn').click();
await adminPage.getByRole('button', { name: '系统配置', exact: true }).click();
await adminPage.getByRole('textbox', { name: /^平台名称/ }).fill('宁夏时空数据智能平台');
await adminPage.getByRole('textbox', { name: /^平台副标题/ }).fill('自然资源时空数据智能底座');
await adminPage.getByRole('button', { name: '保存配置' }).click();
await adminPage.getByText(/已保存并同步到登录页/).waitFor({ timeout: 10_000 });
await adminPage.locator('.app-logo-text').filter({ hasText: '宁夏时空数据智能平台' }).waitFor();
await adminPage.screenshot({ path: `${outputDir}/08-platform-branding-admin-desktop.png`, fullPage: true });
const adminBranding = await adminPage.evaluate(() => ({
  title: document.title,
  headerName: document.querySelector('.app-logo-text')?.textContent?.trim(),
  horizontalOverflow: document.documentElement.scrollWidth - innerWidth,
}));
await adminContext.close();

const loginContext = await browser.newContext({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1 });
const loginPage = await loginContext.newPage();
await loginPage.route('**/api/platform/branding', route => route.fulfill({
  status: 200,
  contentType: 'application/json',
  body: JSON.stringify({
    platform_name: '宁夏时空数据智能平台',
    platform_subtitle: '自然资源时空数据智能底座',
    updated_by: 'ontology-admin',
    updated_at: new Date().toISOString(),
  }),
}));
await loginPage.goto(baseUrl, { waitUntil: 'domcontentloaded' });
await loginPage.locator('.login-brand-title').filter({ hasText: '宁夏时空数据智能平台' }).waitFor({ timeout: 20_000 });
await loginPage.screenshot({ path: `${outputDir}/09-platform-branding-login-desktop.png`, fullPage: true });
const loginBranding = await loginPage.evaluate(() => ({
  title: document.title,
  name: document.querySelector('.login-brand-title')?.textContent?.trim(),
  subtitle: document.querySelector('.login-brand-subtitle')?.textContent?.trim(),
  horizontalOverflow: document.documentElement.scrollWidth - innerWidth,
}));
await loginContext.close();

await browser.close();

const result = {
  baseUrl,
  captures: 9,
  desktopResults,
  desktopEvidence,
  desktopBanzhu,
  mobileData,
  mobileMap,
  ontologyModel,
  adminBranding,
  loginBranding,
  consoleErrors: consoleErrors.filter(message =>
    !message.includes('Failed to load resource')
    && !(message.includes('TypeError: Failed to fetch') && message.includes('@chainlit_react-client'))
  ),
};

if (result.consoleErrors.length) throw new Error(`browser errors: ${JSON.stringify(result.consoleErrors)}`);
for (const item of [desktopResults, desktopEvidence, desktopBanzhu, mobileData, mobileMap]) {
  if (item.errorBoundary) throw new Error(`error boundary rendered: ${JSON.stringify(item)}`);
  if (item.horizontalOverflow > 2) throw new Error(`horizontal overflow: ${JSON.stringify(item)}`);
  if (item.clipped.length) throw new Error(`clipped demo controls: ${JSON.stringify(item.clipped)}`);
}
if (desktopResults.mapPaths < 100 || mobileMap.mapPaths < 100) {
  throw new Error(`map overlay is blank: desktop=${desktopResults.mapPaths}, mobile=${mobileMap.mapPaths}`);
}
if (ontologyModel.errorBoundary || ontologyModel.horizontalOverflow > 2 || ontologyModel.nodeCount < 1) {
  throw new Error(`ontology model validation failed: ${JSON.stringify(ontologyModel)}`);
}
if (ontologyModel.headerBackground !== ontologyModel.platformBackground) {
  throw new Error(`ontology model theme mismatch: ${JSON.stringify(ontologyModel)}`);
}
if (
  adminBranding.title !== '宁夏时空数据智能平台'
  || adminBranding.headerName !== '宁夏时空数据智能平台'
  || adminBranding.horizontalOverflow > 2
) {
  throw new Error(`admin branding validation failed: ${JSON.stringify(adminBranding)}`);
}
if (
  loginBranding.title !== '宁夏时空数据智能平台'
  || loginBranding.name !== '宁夏时空数据智能平台'
  || loginBranding.subtitle !== '自然资源时空数据智能底座'
  || loginBranding.horizontalOverflow > 2
) {
  throw new Error(`login branding validation failed: ${JSON.stringify(loginBranding)}`);
}
await writeFile(`${outputDir}/acceptance.json`, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
console.log(JSON.stringify(result, null, 2));
