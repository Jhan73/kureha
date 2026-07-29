"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "./auth-context";
import { RequireAuth } from "./require-auth";
import { isStaffRole } from "./roles";

/**
 * Role-gated variant of `RequireAuth` for the staff copilot dashboard
 * (tasks.md 15.1). Layers on top of `RequireAuth` (reused unchanged, not
 * duplicated) with `redirectTo="/staff/login"` so an unauthenticated staff
 * visitor lands on the staff login page, not the patient one.
 *
 * Once a token IS present, `StaffRoleGate` below additionally checks
 * `user.role` against `isStaffRole` (`reception`/`professional`/`admin`) --
 * a patient's own valid session must never render staff-only content. This
 * is the coarsest legitimate staff/patient signal the backend already
 * returns (`TokenResponse.role`, `POST /auth/login`); see this module's own
 * closure note in tasks.md for why a finer-grained, per-action
 * `allowed_actions` gate is a flagged, NOT-YET-AVAILABLE backend gap (no
 * `GET /me/permissions`-shaped endpoint exists to wrap
 * `ListAllowedActions`/`AuthorizationPort` for the frontend today).
 */
function StaffRoleGate({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const router = useRouter();
  const authorized = user !== null && isStaffRole(user.role);

  useEffect(() => {
    if (user && !authorized) {
      void logout();
      router.replace("/staff/login");
    }
  }, [user, authorized, logout, router]);

  if (!authorized) {
    return (
      <div role="status" className="flex flex-1 items-center justify-center py-24">
        <span className="text-sm text-muted-foreground">Loading...</span>
      </div>
    );
  }

  return <>{children}</>;
}

export function RequireStaffAuth({ children }: { children: ReactNode }) {
  return (
    <RequireAuth redirectTo="/staff/login">
      <StaffRoleGate>{children}</StaffRoleGate>
    </RequireAuth>
  );
}
