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
  /** In-memory only — never persisted. */
  accessToken: string | null;
  user: AuthUser | null;
  /** Returns the user; context state updates only on the next render. */
  login: (params: LoginParams) => Promise<AuthUser>;
  logout: () => Promise<void>;
  /** Mint access token from persisted refresh token; returns success. */
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
  const [refreshToken, setRefreshToken] = useState<string | null>(null);

  const applyTokens = useCallback((tokens: TokenResponse): AuthUser => {
    const nextUser = userFromTokens(tokens);
    setAccessToken(tokens.access_token);
    setUser(nextUser);
    setRefreshToken(tokens.refresh_token);
    saveRefreshToken(tokens.refresh_token);
    return nextUser;
  }, []);

  const clearAuth = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    setRefreshToken(null);
    clearRefreshToken();
  }, []);

  const login = useCallback(
    async (params: LoginParams): Promise<AuthUser> => {
      const tokens = await apiLogin(params);
      return applyTokens(tokens);
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
        // Best-effort revoke: clear local state regardless, never block logout.
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
