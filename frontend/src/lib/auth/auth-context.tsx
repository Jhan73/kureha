"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  createAuthorizedFetch,
  login as apiLogin,
  logout as apiLogout,
  refresh as apiRefresh,
} from "../api/client";
import type { LoginParams, TokenResponse } from "../api/types";
import {
  clearRefreshToken,
  loadRefreshToken,
  saveRefreshToken,
} from "./refresh-token-storage";

export interface AuthUser {
  userId: string;
  role: string;
}

export interface AuthContextValue {
  /** In-memory only, per tasks.md 14.1's "access-token-in-memory strategy" -- never persisted. */
  accessToken: string | null;
  user: AuthUser | null;
  login: (params: LoginParams) => Promise<void>;
  logout: () => Promise<void>;
  /** Attempts to mint a new access token from the persisted refresh token. Returns whether it succeeded. */
  silentRefresh: () => Promise<boolean>;
  authorizedFetch: (path: string, init?: RequestInit) => Promise<Response>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function userFromTokens(tokens: TokenResponse): AuthUser {
  return { userId: tokens.user_id, role: tokens.role };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  // Tracked in state (not a ref) so every closure that reads it -- direct or
  // via useMemo/useCallback -- always sees the value from the render that
  // produced it, no `ref.current`-during-render lint hazard.
  const [refreshToken, setRefreshToken] = useState<string | null>(null);

  const applyTokens = useCallback((tokens: TokenResponse) => {
    setAccessToken(tokens.access_token);
    setUser(userFromTokens(tokens));
    setRefreshToken(tokens.refresh_token);
    saveRefreshToken(tokens.refresh_token);
  }, []);

  const clearAuth = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    setRefreshToken(null);
    clearRefreshToken();
  }, []);

  const login = useCallback(
    async (params: LoginParams) => {
      const tokens = await apiLogin(params);
      applyTokens(tokens);
    },
    [applyTokens],
  );

  const logout = useCallback(async () => {
    const currentRefreshToken = refreshToken ?? loadRefreshToken();
    if (accessToken && currentRefreshToken) {
      try {
        await apiLogout({
          accessToken,
          refreshToken: currentRefreshToken,
        });
      } catch {
        // Best-effort revoke: still clear local state below regardless --
        // the access token is short-lived anyway, and there is no recovery
        // action worth blocking the user's own logout on.
      }
    }
    clearAuth();
  }, [accessToken, refreshToken, clearAuth]);

  const silentRefresh = useCallback(async (): Promise<boolean> => {
    const storedRefreshToken = refreshToken ?? loadRefreshToken();
    if (!storedRefreshToken) {
      return false;
    }
    try {
      const tokens = await apiRefresh(storedRefreshToken);
      applyTokens(tokens);
      return true;
    } catch {
      clearAuth();
      return false;
    }
  }, [refreshToken, applyTokens, clearAuth]);

  const authorizedFetch = useMemo(
    () =>
      createAuthorizedFetch({
        getAccessToken: () => accessToken,
        getRefreshToken: () => refreshToken ?? loadRefreshToken(),
        onTokensRefreshed: applyTokens,
        onAuthFailure: clearAuth,
      }),
    [accessToken, refreshToken, applyTokens, clearAuth],
  );

  const value = useMemo<AuthContextValue>(
    () => ({ accessToken, user, login, logout, silentRefresh, authorizedFetch }),
    [accessToken, user, login, logout, silentRefresh, authorizedFetch],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
