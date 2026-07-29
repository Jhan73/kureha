import { useState } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "../auth-context";
import { saveRefreshToken } from "../refresh-token-storage";
import type { TokenResponse } from "../../api/types";

vi.mock("../../api/client", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return {
    ...actual,
    login: vi.fn(),
    refresh: vi.fn(),
    logout: vi.fn(),
  };
});

import { login as apiLogin, logout as apiLogout, refresh as apiRefresh } from "../../api/client";

const tokens: TokenResponse = {
  access_token: "access-1",
  refresh_token: "refresh-1",
  user_id: "user-1",
  role: "patient",
};

const rotatedTokens: TokenResponse = {
  access_token: "access-2",
  refresh_token: "refresh-2",
  user_id: "user-1",
  role: "patient",
};

function Harness() {
  const { accessToken, user, login, logout, silentRefresh } = useAuth();
  const [refreshResult, setRefreshResult] = useState("pending");
  return (
    <div>
      <span data-testid="access-token">{accessToken ?? "none"}</span>
      <span data-testid="user">{user ? `${user.userId}:${user.role}` : "none"}</span>
      <span data-testid="refresh-result">{refreshResult}</span>
      <button
        onClick={() => {
          void login({ tenantId: "tenant-1", email: "a@example.com", password: "secret" });
        }}
      >
        login
      </button>
      <button
        onClick={() => {
          void logout();
        }}
      >
        logout
      </button>
      <button
        onClick={async () => {
          const ok = await silentRefresh();
          setRefreshResult(String(ok));
        }}
      >
        silent-refresh
      </button>
    </div>
  );
}

describe("AuthProvider", () => {
  beforeEach(() => {
    vi.mocked(apiLogin).mockReset();
    vi.mocked(apiRefresh).mockReset();
    vi.mocked(apiLogout).mockReset();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("login() populates in-memory auth state and persists the refresh token", async () => {
    vi.mocked(apiLogin).mockResolvedValueOnce(tokens);
    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>,
    );

    await act(async () => {
      fireEvent.click(screen.getByText("login"));
    });

    expect(screen.getByTestId("access-token").textContent).toBe("access-1");
    expect(screen.getByTestId("user").textContent).toBe("user-1:patient");
    expect(window.localStorage.getItem("kureha.refresh_token")).toBe("refresh-1");
  });

  it("login() resolves with the freshly authenticated user (tasks.md 15.1: lets a caller act on the resolved role immediately, no stale-closure re-render needed)", async () => {
    vi.mocked(apiLogin).mockResolvedValueOnce(tokens);
    let resolvedUser: { userId: string; role: string } | null = null;

    function ResolvingHarness() {
      const { login } = useAuth();
      return (
        <button
          onClick={() => {
            void login({ tenantId: "tenant-1", email: "a@example.com", password: "secret" }).then(
              (user) => {
                resolvedUser = user;
              },
            );
          }}
        >
          login
        </button>
      );
    }

    render(
      <AuthProvider>
        <ResolvingHarness />
      </AuthProvider>,
    );

    await act(async () => {
      fireEvent.click(screen.getByText("login"));
    });

    expect(resolvedUser).toEqual({ userId: "user-1", role: "patient" });
  });

  it("logout() clears in-memory state and the persisted refresh token", async () => {
    vi.mocked(apiLogin).mockResolvedValueOnce(tokens);
    vi.mocked(apiLogout).mockResolvedValueOnce(undefined);
    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>,
    );

    await act(async () => {
      fireEvent.click(screen.getByText("login"));
    });
    await act(async () => {
      fireEvent.click(screen.getByText("logout"));
    });

    expect(apiLogout).toHaveBeenCalledWith({
      accessToken: "access-1",
      refreshToken: "refresh-1",
    });
    expect(screen.getByTestId("access-token").textContent).toBe("none");
    expect(screen.getByTestId("user").textContent).toBe("none");
    expect(window.localStorage.getItem("kureha.refresh_token")).toBeNull();
  });

  it("silentRefresh() restores auth state from a persisted refresh token", async () => {
    saveRefreshToken("refresh-1");
    vi.mocked(apiRefresh).mockResolvedValueOnce(rotatedTokens);
    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>,
    );

    await act(async () => {
      fireEvent.click(screen.getByText("silent-refresh"));
    });

    expect(apiRefresh).toHaveBeenCalledWith("refresh-1");
    expect(screen.getByTestId("access-token").textContent).toBe("access-2");
    expect(screen.getByTestId("refresh-result").textContent).toBe("true");
    expect(window.localStorage.getItem("kureha.refresh_token")).toBe("refresh-2");
  });

  it("silentRefresh() returns false without calling the API when no refresh token is stored", async () => {
    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>,
    );

    await act(async () => {
      fireEvent.click(screen.getByText("silent-refresh"));
    });

    expect(apiRefresh).not.toHaveBeenCalled();
    expect(screen.getByTestId("refresh-result").textContent).toBe("false");
    expect(screen.getByTestId("access-token").textContent).toBe("none");
  });

  it("silentRefresh() clears state and returns false when the backend rejects the refresh token", async () => {
    saveRefreshToken("refresh-1");
    vi.mocked(apiRefresh).mockRejectedValueOnce(new Error("revoked"));
    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>,
    );

    await act(async () => {
      fireEvent.click(screen.getByText("silent-refresh"));
    });

    expect(screen.getByTestId("refresh-result").textContent).toBe("false");
    expect(screen.getByTestId("access-token").textContent).toBe("none");
    expect(window.localStorage.getItem("kureha.refresh_token")).toBeNull();
  });
});
