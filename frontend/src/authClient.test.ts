import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  PasswordLoginError,
  getPasswordLoginErrorKey,
  passwordLogin,
} from './authClient';
import { setLocale } from './i18n';

afterEach(async () => {
  vi.unstubAllGlobals();
  await setLocale('zh-CN');
});

describe('password login i18n', () => {
  it('sends the selected locale to the Chainlit login endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);
    await setLocale('ar-AE');

    const formData = new FormData();
    formData.append('username', 'admin');
    formData.append('password', 'secret');
    await passwordLogin(formData);

    expect(fetchMock).toHaveBeenCalledWith('/login', expect.objectContaining({
      method: 'POST',
      credentials: 'include',
      body: formData,
      headers: {
        'Accept-Language': 'ar-AE',
        'X-Locale': 'ar-AE',
      },
    }));
  });

  it('keeps server details internal and maps failures to locale keys', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: 'Invalid credentials' }),
      { status: 401, headers: { 'Content-Type': 'application/json' } },
    )));

    const failure = await passwordLogin(new FormData()).catch(error => error);
    expect(failure).toBeInstanceOf(PasswordLoginError);
    expect(failure).toMatchObject({ status: 401, detail: 'Invalid credentials' });
    expect(getPasswordLoginErrorKey(failure)).toBe('auth.loginFailed');
    expect(getPasswordLoginErrorKey(new PasswordLoginError(429))).toBe('auth.tooManyAttempts');
    expect(getPasswordLoginErrorKey(new TypeError('fetch failed'))).toBe('auth.networkError');
  });
});
