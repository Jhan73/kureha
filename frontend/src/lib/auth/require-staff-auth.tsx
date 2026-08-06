"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "./auth-context";
import { RequireAuth } from "./require-auth";
import { isStaffRole } from "./roles";

// Auth alone is not enough; role is the only staff/patient signal today.
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
