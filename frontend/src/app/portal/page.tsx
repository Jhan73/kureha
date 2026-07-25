"use client";

import { RequireAuth } from "@/lib/auth/require-auth";
import { useAuth } from "@/lib/auth/auth-context";
import { Button } from "@/components/ui/button";

function PortalContent() {
  const { user, logout } = useAuth();

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-4 py-16 text-center">
      <h1 className="text-2xl font-semibold">
        Welcome{user ? `, ${user.role}` : ""}
      </h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        This is a placeholder landing page. Self-service scheduling and the
        embedded chat ship in a later batch.
      </p>
      <Button variant="outline" onClick={() => void logout()}>
        Log out
      </Button>
    </div>
  );
}

// Placeholder post-login landing page (14.2/14.3 build the real self-service
// views here later) and the first real consumer of `RequireAuth`.
export default function PortalPage() {
  return (
    <RequireAuth>
      <PortalContent />
    </RequireAuth>
  );
}
