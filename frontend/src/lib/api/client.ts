import { API_BASE_URL } from "./config";
import type {
  AdminInviteResponse,
  BootstrapTenantParams,
  LoginParams,
  RetryAdminInviteParams,
  TenantBootstrapResponse,
  TokenResponse,
} from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function parseJsonOrThrow<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = response.statusText || "Request failed";
    try {
      const body = await response.json();
      message = body?.user_message ?? body?.detail ?? message;
    } catch {
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

export async function bootstrapTenant(
  params: BootstrapTenantParams,
  operatorKey: string,
): Promise<TenantBootstrapResponse> {
  const response = await fetch(`${API_BASE_URL}/ops/tenants/bootstrap`, {
    method: "POST",
    headers: jsonHeaders({ "X-Kureha-Ops-Key": operatorKey }),
    body: JSON.stringify({
      name: params.name,
      admin_email: params.adminEmail,
      tenant_id: params.tenantId || undefined,
      site_name: params.siteName || undefined,
    }),
  });
  return parseJsonOrThrow<TenantBootstrapResponse>(response);
}

export async function retryAdminInvite(
  tenantId: string,
  params: RetryAdminInviteParams,
  operatorKey: string,
): Promise<AdminInviteResponse> {
  const response = await fetch(`${API_BASE_URL}/ops/tenants/${tenantId}/admin-invite`, {
    method: "POST",
    headers: jsonHeaders({ "X-Kureha-Ops-Key": operatorKey }),
    body: JSON.stringify({
      site_id: params.siteId,
      admin_user_id: params.adminUserId,
      admin_email: params.adminEmail,
    }),
  });
  return parseJsonOrThrow<AdminInviteResponse>(response);
}

export type AuthorizedFetch = (path: string, init?: RequestInit) => Promise<Response>;

export interface AuthorizedFetchDeps {
  getAccessToken: () => string | null;
  getRefreshToken: () => string | null;
  onTokensRefreshed: (tokens: TokenResponse) => void;
  onAuthFailure: () => void;
}

/** One silent refresh-then-retry on 401; concurrent 401s share one in-flight refresh (rotation). */
export function createAuthorizedFetch(deps: AuthorizedFetchDeps): AuthorizedFetch {
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

  const authorizedFetch: AuthorizedFetch = async (path, init) => {
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
      // Still 401 after refresh: real auth failure, never retry refresh again.
      deps.onAuthFailure();
    }
    return retried;
  };

  return authorizedFetch;
}
