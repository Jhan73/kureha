"use client";

import Link from "next/link";
import { RequireStaffAuth } from "@/lib/auth/require-staff-auth";
import { useAuth } from "@/lib/auth/auth-context";
import { Button, buttonVariants } from "@/components/ui/button";

// **`allowed_actions`-driven UI, flagged gap (tasks.md 15.1):** every staff
// user sees the SAME two links below regardless of their individual
// `action-based-rbac` permissions -- the coarsest signal available today is
// "is this user a staff member at all" (`RequireStaffAuth`'s own role
// check), not per-action visibility. No backend endpoint exposes
// `ListAllowedActions`/`allowed_actions` to the frontend (it currently only
// feeds `resolve_toolset` inside the LangGraph copilot, design.md §5.4) --
// building fine-grained nav gating against a non-existent contract would be
// exactly the kind of invented behavior this change's own conventions
// forbid. A future `GET /me/permissions`-shaped endpoint wrapping
// `ListAllowedActions` would let this page hide, e.g., the registry link
// for a `professional` role that lacks `staff:register`/`shift:create`.
const STAFF_LINKS = [
  { href: "/staff/chat", label: "Chat with Tony" },
  { href: "/staff/registry", label: "Staff registry & shifts" },
] as const;

function StaffDashboardContent() {
  const { user, logout } = useAuth();

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-4 py-16 text-center">
      <h1 className="text-2xl font-semibold">
        Welcome{user ? `, ${user.role}` : ""}
      </h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        Manage staff and shifts, or chat with Tony for scheduling and
        administrative help.
      </p>
      <nav className="flex w-full max-w-xs flex-col gap-2">
        {STAFF_LINKS.map(({ href, label }) => (
          <Link key={href} href={href} className={buttonVariants({ variant: "outline" })}>
            {label}
          </Link>
        ))}
      </nav>
      <Button variant="outline" onClick={() => void logout()}>
        Log out
      </Button>
    </div>
  );
}

// Staff copilot dashboard landing page (tasks.md 15.1), the staff
// equivalent of `/portal/page.tsx` -- `<RequireStaffAuth>`-wrapped instead
// of `<RequireAuth>` so only reception/professional/admin sessions render
// this content.
export default function StaffDashboardPage() {
  return (
    <RequireStaffAuth>
      <StaffDashboardContent />
    </RequireStaffAuth>
  );
}
