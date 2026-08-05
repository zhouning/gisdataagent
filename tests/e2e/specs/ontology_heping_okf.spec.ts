import { expect, test } from '@playwright/test';

const BASE_URL = process.env.GIS_AGENT_E2E_URL || 'http://127.0.0.1:8000';
const QUERY = '运行和平村用地转换辅助预审，并在地图上展示结果。';

test('ontology scenario uses an attested OKF computation before map display', async ({ page }) => {
  test.setTimeout(180_000);
  const managedUser = !process.env.GIS_AGENT_E2E_PASSWORD;
  const usernameValue = managedUser
    ? `okf_e2e_${Date.now()}`
    : (process.env.GIS_AGENT_E2E_USER || 'admin');
  const passwordValue = managedUser
    ? `OkfE2E_${Date.now()}_Pass`
    : String(process.env.GIS_AGENT_E2E_PASSWORD);

  if (managedUser) {
    const registration = await page.request.post(`${BASE_URL}/auth/register`, {
      data: {
        username: usernameValue,
        password: passwordValue,
        display_name: 'OKF E2E',
        email: '',
      },
    });
    expect(registration.ok()).toBeTruthy();
    expect((await registration.json()).status).toBe('success');
  }

  try {
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });

    const username = page.locator('#username');
    if (await username.isVisible()) {
      await username.fill(usernameValue);
      await page.locator('#password').fill(passwordValue);
      await page.getByRole('button', { name: '登录' }).click();
    }
    await expect(page.locator('.app-header')).toBeVisible({ timeout: 30_000 });

    const chatInput = page.getByPlaceholder('输入消息... (Enter 发送)');
    await expect(chatInput).toBeVisible({ timeout: 30_000 });
    await page.waitForTimeout(3_000);
    await chatInput.fill(QUERY);
    await expect(page.locator('.btn-send')).toBeEnabled();
    await page.locator('.btn-send').click();

    const answer = page.locator(
      '.chat-message.assistant .message-content',
      { hasText: '识别 445 个变化地块' },
    );
    await expect(answer).toBeVisible({ timeout: 120_000 });
    await expect(answer).toContainText('执行证明：OKF 0.2 计算契约验证通过');
    await expect(answer).toContainText('地图已加载 3 个结果图层');
    await expect(answer).not.toContainText('未识别到具体的质检模板');

    const mapPayload = await page.waitForFunction(
      () => (window as any).__lastMapUpdate?.layers?.length === 3
        ? (window as any).__lastMapUpdate
        : null,
      undefined,
      { timeout: 30_000 },
    );
    expect((await mapPayload.jsonValue()).layers.map((layer: any) => layer.name)).toEqual([
      '和平村 · 规划变化地块',
      '和平村 · 空间约束',
      '和平村 · 建设用地管制区',
    ]);

    const demo = page.locator('.nr-demo-shell');
    await expect(demo).toBeVisible({ timeout: 30_000 });
    await expect(demo.getByText('OKF 0.2 计算证明通过', { exact: false })).toBeVisible();

    const validation = await page.request.get(`${BASE_URL}/api/ontology/okf?validate=1`);
    expect(validation.ok()).toBeTruthy();
    expect((await validation.json()).valid).toBe(true);

    const contract = await page.request.get(
      `${BASE_URL}/api/ontology/okf?path=computations/heping-land-conversion-precheck.md`,
    );
    expect(contract.ok()).toBeTruthy();
    expect(await contract.text()).toContain('type: Attested Computation');
  } finally {
    if (managedUser) {
      await page.request.delete(`${BASE_URL}/api/user/account`, {
        data: { password: passwordValue },
      });
    }
  }
});
