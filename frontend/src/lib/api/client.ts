import { API_BASE_URL } from "./config";
import type { LoginParams, TokenResponse } from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function parseJsonOrThrow<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = response.statusText || "Request failed";
    try {
      const body = await response.json();
      message = body?.user_message ?? body?.detail ?? message;
    } catch {
      // Body wasn't JSON (or was empty) -- fall back to statusText.
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}

function jsonHeaders(extra?: Record<string, string>): Record<string, string> {
  return { "Content-Type": "application/json", ...extra };
}

export async function login(params: LoginParams): Promise<TokenResponse> {
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({
      tenant_id: params.tenantId,
      email: params.email,
      password: params.password,
    }),
  });
  return parseJsonOrThrow<TokenResponse>(response);
}

export async function refresh(refreshToken: string): Promise<TokenResponse> {
  const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  return parseJsonOrThrow<TokenResponse>(response);
}

export async function logout(params: {
  accessToken: string;
  refreshToken: string;
}): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/auth/logout`, {
    method: "POST",
    headers: jsonHeaders({ Authorization: `Bearer ${params.accessToken}` }),
    body: JSON.stringify({ refresh_token: params.refreshToken }),
  });
  if (response.status !== 204 && !response.ok) {
    await parseJsonOrThrow(response);
  }
}

export interface AuthorizedFetchDeps {
  getAccessToken: () => string | null;
  getRefreshToken: () => string | null;
  onTokensRefreshed: (tokens: TokenResponse) => void;
  onAuthFailure: () => void;
}

/**
 * Builds a `fetch` wrapper that attaches `Authorization: Bearer <token>` and,
 * on a 401, attempts exactly ONE silent refresh-then-retry. Two near-
 * simultaneous 401s share a single in-flight refresh call (the backend's
 * refresh-token rotation means a second concurrent call with the same,
 * now-consumed refresh token would otherwise only succeed by luck of the
 * 30-second rotation grace period -- see design.md §17.4 ADR-15).
 */
export function createAuthorizedFetch(deps: AuthorizedFetchDeps) {
  let inFlightRefresh: Promise<TokenResponse | null> | null = null;

  function doRefresh(): Promise<TokenResponse | null> {
    if (inFlightRefresh) {
      return inFlightRefresh;
    }
    const refreshToken = deps.getRefreshToken();
    if (!refreshToken) {
      return Promise.resolve(null);
    }
    inFlightRefresh = refresh(refreshToken)
      .then((tokens) => {
        deps.onTokensRefreshed(tokens);
        return tokens;
      })
      .catch(() => null)
      .finally(() => {
        inFlightRefresh = null;
      });
    return inFlightRefresh;
  }

  function requestWith(
    path: string,
    init: RequestInit | undefined,
    accessToken: string | null,
  ): Promise<Response> {
    const headers: Record<string, string> = {
      ...(init?.headers as Record<string, string> | undefined),
    };
    if (accessToken) {
      headers.Authorization = `Bearer ${accessToken}`;
    }
    return fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  }

  return async function authorizedFetch(
    path: string,
    init?: RequestInit,
  ): Promise<Response> {
    const response = await requestWith(path, init, deps.getAccessToken());
    if (response.status !== 401) {
      return response;
    }

    const tokens = await doRefresh();
    if (!tokens) {
      deps.onAuthFailure();
      return response;
    }

    const retried = await requestWith(path, init, tokens.access_token);
    if (retried.status === 401) {
      // Refresh succeeded but the retried request is still unauthorized --
      // do not loop into a second refresh, this is a real auth failure.
      deps.onAuthFailure();
    }
    return retried;
  };
}
