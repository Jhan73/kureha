// Storage decision (tasks.md 14.1, deliberately NOT dictated by spec/design):
// the access token stays in-memory only (never persisted, per the
// "access-token-in-memory strategy" wording), but the refresh token IS
// persisted to `localStorage`. Rationale: the backend returns the refresh
// token as plain JSON (no httpOnly cookie the browser manages for us), so an
// in-memory-only refresh token would force a full re-login on every page
// reload for a credential meant to survive ~30 days across sessions -- too
// aggressive for the UX this MVP wants. This accepts the standard
// localStorage XSS-exposure tradeoff, mitigated by the backend's own
// rotation-with-reuse-detection (design.md §17.4 ADR-15): replaying an
// already-rotated refresh token revokes the whole session chain, so a
// stolen-and-used token is detected, not silently accepted forever.
const REFRESH_TOKEN_KEY = "kureha.refresh_token";

export function loadRefreshToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function saveRefreshToken(token: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(REFRESH_TOKEN_KEY, token);
}

export function clearRefreshToken(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(REFRESH_TOKEN_KEY);
}
