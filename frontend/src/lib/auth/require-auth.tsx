"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "./auth-context";

/**
 * Client-side route guard. `output: "export"` has no server, so Next.js
 * Middleware isn't available -- this is the equivalent boundary: on mount,
 * check in-memory auth state and, if absent, attempt a silent refresh from
 * the persisted refresh token before deciding to redirect to `/login`.
 * Shows a loading state while that check resolves so protected content is
 * never flashed then yanked away. Reusable by any page (14.2/14.3 wrap it too).
 *
 * `redirectTo` (tasks.md 15.1) defaults to `/login` (the patient portal's
 * own entry point, unchanged behavior for every pre-existing caller) but is
 * overridable so `RequireStaffAuth` (`require-staff-auth.tsx`) can send an
 * unauthenticated staff-area visitor to `/staff/login` instead -- the same
 * component, just parameterized rather than duplicated.
 */
export function RequireAuth({
  children,
  redirectTo = "/login",
}: {
  children: ReactNode;
  redirectTo?: string;
}) {
  const { accessToken, silentRefresh } = useAuth();
  const router = useRouter();
  // Only the outcome of an in-flight/completed silent refresh lives in local
  // state -- the "already authenticated" case is derived straight from
  // `accessToken` at render time so no setState call is ever needed
  // synchronously inside the effect body (only after the awaited refresh).
  const [refreshedSuccessfully, setRefreshedSuccessfully] = useState(false);

  useEffect(() => {
    if (accessToken) {
      return;
    }
    let cancelled = false;
    void (async () => {
      const refreshed = await silentRefresh();
      if (cancelled) {
        return;
      }
      if (refreshed) {
        setRefreshedSuccessfully(true);
      } else {
        router.replace(redirectTo);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [accessToken, silentRefresh, router, redirectTo]);

  if (accessToken || refreshedSuccessfully) {
    return <>{children}</>;
  }

  return (
    <div role="status" className="flex flex-1 items-center justify-center py-24">
      <span className="text-sm text-muted-foreground">Loading...</span>
    </div>
  );
}
