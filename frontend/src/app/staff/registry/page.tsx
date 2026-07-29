"use client";

import Link from "next/link";
import { RequireStaffAuth } from "@/lib/auth/require-staff-auth";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";

/**
 * Staff registry + shift management (tasks.md 15.2) -- **deliberately a
 * documented gap notice, not a CRUD UI.** Investigated first, per this
 * task's own explicit instruction ("no new backend endpoints... if an
 * endpoint you need doesn't exist, flag it explicitly, don't invent one"):
 *
 * `backend/app/modules/staff/` has real domain/use-case/repository layers
 * (`RegisterStaff`/`DeactivateStaff`/`CreateShift`/`EditShift`,
 * `StaffRepositoryPort`/`ShiftRepositoryPort`) and they ARE wired into the
 * LangGraph copilot's `persist_and_audit` dispatch table (tasks.md 11.5,
 * `platform/inbound/graph/nodes/persist_and_audit.py`'s `staff:register` /
 * `staff:deactivate` / `shift:create` / `shift:edit` `ActionKey`s) -- but
 * `backend/app/platform/inbound/api/routers/` has ONLY FOUR routers
 * (`auth`, `appointments`, `calendar/oauth`, `chat` -- confirmed via
 * `app/main.py`'s `create_app()`, which `include_router`s exactly these
 * four and nothing else). There is NO REST route for staff/shift at all --
 * not create, not deactivate, not edit, and not even a read/list endpoint
 * (`StaffRepositoryPort`/`ShiftRepositoryPort` don't expose a `list_*`
 * method either, so a GET endpoint isn't even a thin wrapper away).
 *
 * This is categorically different from tasks.md 14.2's flagged gap (a
 * missing GET/list convenience alongside four REAL, working POST routes) --
 * here there is ZERO REST surface for this capability. Building a form that
 * submits to a non-existent endpoint would be pure dead UI; per this
 * change's own "no channel-specific bypass logic" / "don't invent
 * behavior" convention (already applied identically in tasks.md 14.6's own
 * consent-flow gap note), the correct scope is this honest notice, plus a
 * pointer to the copilot chat (tasks.md 15.3) -- the ONLY currently
 * functional path to these 4 use cases for an authorized staff user, via
 * natural language, subject to the exact same `AuthorizeAction`/RLS
 * enforcement the future direct routes would also need.
 *
 * **Recommended follow-up** (not built here, scope belongs to a backend
 * task): a `backend/app/platform/inbound/api/routers/staff.py` mirroring
 * `scheduling.py`'s shape (`POST /staff/register`, `POST
 * /staff/{id}/deactivate`, `POST /staff/{id}/shifts`, `PATCH
 * /staff/shifts/{id}`), wired to the composition root's already-existing
 * `build_register_staff`/`build_deactivate_staff`/`build_create_shift`/
 * `build_edit_shift` factories (`persist_and_audit.py` already imports
 * them) -- plus new `list_by_site`-shaped methods on
 * `StaffRepositoryPort`/`ShiftRepositoryPort` and a `GET /staff`/`GET
 * /staff/{id}/shifts` pair, none of which exist today.
 */
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
