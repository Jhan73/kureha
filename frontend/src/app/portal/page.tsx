"use client";

import Link from "next/link";
import { RequireAuth } from "@/lib/auth/require-auth";
import { useAuth } from "@/lib/auth/auth-context";
import { Button, buttonVariants } from "@/components/ui/button";

const APPOINTMENT_LINKS = [
  { href: "/portal/appointments/schedule", label: "Schedule an appointment" },
  { href: "/portal/appointments/reschedule", label: "Reschedule an appointment" },
  { href: "/portal/appointments/cancel", label: "Cancel an appointment" },
  { href: "/portal/appointments/reminder", label: "Request a reminder" },
  { href: "/portal/chat", label: "Chat with Tony" },
] as const;

function PortalContent() {
  const { user, logout } = useAuth();

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-4 py-16 text-center">
      <h1 className="text-2xl font-semibold">
        Welcome{user ? `, ${user.role}` : ""}
      </h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        Manage your own appointments below, or chat with Tony for
        administrative help.
      </p>
      <nav className="flex w-full max-w-xs flex-col gap-2">
        {APPOINTMENT_LINKS.map(({ href, label }) => (
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

export default function PortalPage() {
  return (
    <RequireAuth>
      <PortalContent />
    </RequireAuth>
  );
}
