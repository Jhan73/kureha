"use client";

import Link from "next/link";
import { RequireStaffAuth } from "@/lib/auth/require-staff-auth";
import { useAuth } from "@/lib/auth/auth-context";
import { Button, buttonVariants } from "@/components/ui/button";

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

export default function StaffDashboardPage() {
  return (
    <RequireStaffAuth>
      <StaffDashboardContent />
    </RequireStaffAuth>
  );
}
