import { getLocaleHeaders } from './i18n';

export class PasswordLoginError extends Error {
  readonly status: number;
  readonly detail?: string;

  constructor(status: number, detail?: string) {
    super(detail || `Password login failed with HTTP ${status}`);
    this.name = 'PasswordLoginError';
    this.status = status;
    this.detail = detail;
  }
}

export type PasswordLoginErrorKey =
  | 'auth.loginFailed'
  | 'auth.networkError'
  | 'auth.tooManyAttempts';

export function getPasswordLoginErrorKey(error: unknown): PasswordLoginErrorKey {
  if (error instanceof PasswordLoginError && error.status === 429) {
    return 'auth.tooManyAttempts';
  }
  if (error instanceof TypeError) return 'auth.networkError';
  return 'auth.loginFailed';
}

/**
 * Submit the Chainlit password login form with the active UI locale.
 * ChainlitAPI.passwordAuth does not expose request headers, so the locale
 * must be attached here for the backend locale middleware to see it.
 */
export async function passwordLogin(formData: FormData): Promise<unknown> {
  const response = await fetch('/login', {
    method: 'POST',
    credentials: 'include',
    headers: getLocaleHeaders(),
    body: formData,
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload?.detail === 'string'
      ? payload.detail
      : typeof payload?.message === 'string'
        ? payload.message
        : undefined;
    throw new PasswordLoginError(response.status, detail);
  }
  return payload;
}
