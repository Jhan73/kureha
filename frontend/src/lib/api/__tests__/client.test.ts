import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  createAuthorizedFetch,
  login,
  logout,
  refresh,
} from "../client";
import { API_BASE_URL } from "../config";
import type { TokenResponse } from "../types";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const tokens: TokenResponse = {
  access_token: "access-1",
  refresh_token: "refresh-1",
  user_id: "user-1",
  role: "patient",
};

describe("login", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts credentials to /auth/login and returns the token response", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, tokens));

    const result = await login({
      tenantId: "tenant-1",
      email: "a@example.com",
      password: "secret",
    });

    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE_URL}/auth/login`,
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          tenant_id: "tenant-1",
          email: "a@example.com",
          password: "secret",
        }),
      }),
    );
    expect(result).toEqual(tokens);
  });

  it("throws an ApiError with the backend's user_message on failure", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse(401, { user_message: "Invalid credentials" }),
    );

    await expect(
      login({ tenantId: "tenant-1", email: "a@example.com", password: "wrong" }),
    ).rejects.toMatchObject(new ApiError(401, "Invalid credentials"));
  });
});

describe("refresh", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the refresh token to /auth/refresh and returns new tokens", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, tokens));

    const result = await refresh("refresh-1");

    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE_URL}/auth/refresh`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ refresh_token: "refresh-1" }),
      }),
    );
    expect(result).toEqual(tokens);
  });
});

describe("logout", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the access token as a bearer header and the refresh token in the body", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 204 }));

    await logout({ accessToken: "access-1", refreshToken: "refresh-1" });

    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE_URL}/auth/logout`,
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer access-1",
        }),
        body: JSON.stringify({ refresh_token: "refresh-1" }),
      }),
    );
  });
});

describe("createAuthorizedFetch", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("attaches the current access token as a bearer header", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, { ok: true }));

    const authorizedFetch = createAuthorizedFetch({
      getAccessToken: () => "access-1",
      getRefreshToken: () => "refresh-1",
      onTokensRefreshed: vi.fn(),
      onAuthFailure: vi.fn(),
    });

    await authorizedFetch("/appointments/schedule", { method: "POST" });

    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE_URL}/appointments/schedule`,
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer access-1" }),
      }),
    );
  });

  it("on a 401, refreshes once and retries the original request", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(401, { error_code: "unauthenticated" }))
      .mockResolvedValueOnce(jsonResponse(200, tokens)) // /auth/refresh
      .mockResolvedValueOnce(jsonResponse(200, { ok: true })); // retried request

    const onTokensRefreshed = vi.fn();
    const authorizedFetch = createAuthorizedFetch({
      getAccessToken: () => "stale-access",
      getRefreshToken: () => "refresh-1",
      onTokensRefreshed,
      onAuthFailure: vi.fn(),
    });

    const response = await authorizedFetch("/appointments/schedule", {
      method: "POST",
    });

    expect(fetch).toHaveBeenCalledTimes(3);
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      `${API_BASE_URL}/auth/refresh`,
      expect.objectContaining({ body: JSON.stringify({ refresh_token: "refresh-1" }) }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      `${API_BASE_URL}/appointments/schedule`,
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: `Bearer ${tokens.access_token}` }),
      }),
    );
    expect(onTokensRefreshed).toHaveBeenCalledWith(tokens);
    expect(response.status).toBe(200);
  });

  it("dedupes two concurrent 401s into a single refresh call", async () => {
    let nonRefreshCalls = 0;
    vi.mocked(fetch).mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) {
        return Promise.resolve(jsonResponse(200, tokens));
      }
      nonRefreshCalls += 1;
      return Promise.resolve(
        nonRefreshCalls <= 2 ? jsonResponse(401, {}) : jsonResponse(200, { ok: true }),
      );
    });

    const authorizedFetch = createAuthorizedFetch({
      getAccessToken: () => "stale-access",
      getRefreshToken: () => "refresh-1",
      onTokensRefreshed: vi.fn(),
      onAuthFailure: vi.fn(),
    });

    const [a, b] = await Promise.all([
      authorizedFetch("/appointments/schedule", { method: "POST" }),
      authorizedFetch("/appointments/cancel", { method: "POST" }),
    ]);

    const refreshCalls = vi
      .mocked(fetch)
      .mock.calls.filter(([input]) => String(input).endsWith("/auth/refresh"));
    expect(refreshCalls).toHaveLength(1);
    expect(a.status).toBe(200);
    expect(b.status).toBe(200);
  });

  it("does not retry twice: a 401 on the retried request calls onAuthFailure instead of looping", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(401, {})) // original
      .mockResolvedValueOnce(jsonResponse(200, tokens)) // refresh
      .mockResolvedValueOnce(jsonResponse(401, {})); // retried request still 401

    const onAuthFailure = vi.fn();
    const authorizedFetch = createAuthorizedFetch({
      getAccessToken: () => "stale-access",
      getRefreshToken: () => "refresh-1",
      onTokensRefreshed: vi.fn(),
      onAuthFailure,
    });

    const response = await authorizedFetch("/appointments/schedule", {
      method: "POST",
    });

    expect(fetch).toHaveBeenCalledTimes(3);
    expect(onAuthFailure).toHaveBeenCalledTimes(1);
    expect(response.status).toBe(401);
  });

  it("calls onAuthFailure and does not attempt the request when there is no refresh token", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(401, {}));

    const onAuthFailure = vi.fn();
    const authorizedFetch = createAuthorizedFetch({
      getAccessToken: () => "stale-access",
      getRefreshToken: () => null,
      onTokensRefreshed: vi.fn(),
      onAuthFailure,
    });

    const response = await authorizedFetch("/appointments/schedule", {
      method: "POST",
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(onAuthFailure).toHaveBeenCalledTimes(1);
    expect(response.status).toBe(401);
  });
});
