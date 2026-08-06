"use client";

import Link from "next/link";
import { RequireStaffAuth } from "@/lib/auth/require-staff-auth";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";

// Documented gap: no REST for staff/shifts; do not invent a CRUD form.
function RegistryGapNotice() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-4 py-16 text-center">
      <h1 className="text-2xl font-semibold">Staff registry & shifts</h1>
      <Alert variant="destructive" className="max-w-md text-left">
        <AlertTitle>Not available yet</AlertTitle>
        <AlertDescription>
          Direct registry and shift-management views are not available yet
          -- the backend does not expose a REST endpoint to create,
          deactivate, list staff, or create/edit shifts (only the internal
          copilot chat can reach these actions today, subject to the same
          permission checks a future direct view would use). Use the chat
          below to register staff or manage shifts in the meantime.
        </AlertDescription>
      </Alert>
      <Link href="/staff/chat" className={buttonVariants({ variant: "outline" })}>
        Chat with Tony
      </Link>
    </div>
  );
}

export default function StaffRegistryPage() {
  return (
    <RequireStaffAuth>
      <RegistryGapNotice />
    </RequireStaffAuth>
  );
}
