import { goto } from '$app/navigation';
import { api } from '$lib/api/client';
import { ApiError } from '$lib/api/errors';
import type { paths } from '$lib/api/schema';
import { clearToken, loadToken, saveToken } from '$lib/auth/token';

export type CurrentUser =
  paths['/auth/me']['get']['responses'][200]['content']['application/json'];

let user = $state<CurrentUser | null>(null);
let ready = $state(false);

export function currentUser(): CurrentUser | null {
  return user;
}

export function authReady(): boolean {
  return ready;
}

export async function refreshUser(): Promise<void> {
  if (!loadToken()) {
    user = null;
    ready = true;
    return;
  }
  try {
    const { data, error } = await api.GET('/auth/me');
    if (error || !data) {
      throw error ?? new ApiError(0, 'unexpected empty response from /auth/me');
    }
    user = data;
  } catch (err) {
    if (err instanceof ApiError && err.kind === 'unauthorized') {
      clearToken();
      user = null;
    } else {
      throw err;
    }
  } finally {
    ready = true;
  }
}

export async function login(email: string, password: string): Promise<void> {
  const { data, error } = await api.POST('/auth/login', {
    body: { email, password }
  });
  if (error || !data) {
    throw error ?? new ApiError(0, 'unexpected empty response from /auth/login');
  }
  saveToken(data.access_token);
  await refreshUser();
}

export async function register(
  name: string,
  email: string,
  password: string
): Promise<void> {
  const { error } = await api.POST('/auth/register', {
    body: { name, email, password }
  });
  if (error) throw error;
}

export function logout(): void {
  clearToken();
  user = null;
  ready = true;
  void goto('/login');
}
