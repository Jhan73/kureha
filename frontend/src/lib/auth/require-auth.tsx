"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "./auth-context";

/** Client-only guard (static export has no Middleware); silent refresh before redirect. */
export function RequireAuth({
  children,
  redirectTo = "/login",
}: {
  children: ReactNode;
  redirectTo?: string;
}) {
  const { accessToken, silentRefresh } = useAuth();
  const router = useRouter();
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
