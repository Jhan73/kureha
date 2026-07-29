"use client";

import { RequireStaffAuth } from "@/lib/auth/require-staff-auth";
import { ChatWidget } from "@/components/chat/chat-widget";

/**
 * Internal staff copilot chat (tasks.md 15.3, spec `internal-staff-copilot`).
 * Reuses `<ChatWidget>` VERBATIM -- zero changes needed. `ChatWidget` was
 * already fully channel-agnostic from tasks.md 14.3 onward: it only calls
 * `useAuth().authorizedFetch` + `streamChat(... { message, clientRandomUuid
 * })` against `POST /chat/stream`, the SAME endpoint for both channels. The
 * `patient_chat` vs `staff_copilot` distinction (design.md §8.6: "mismo
 * patron... la unica diferencia es que el `user_id` en la key es el del
 * staff") is resolved entirely server-side, from the caller's own
 * authenticated `role` (`chat.py`'s `_channel_for`) -- never a client-sent
 * field, so there is nothing for this page or `ChatWidget` to pass or
 * declare. The `thread_id` mechanism (in-memory `crypto.randomUUID()`,
 * never persisted) is identical for both channels too (design.md §8.6's own
 * "Copilot de staff — mismo mecanismo" paragraph).
 *
 * The only thing this page adds on top of `/portal/chat/page.tsx` is the
 * route guard: `<RequireStaffAuth>` instead of `<RequireAuth>`, so a
 * patient's own valid session is redirected to `/staff/login` rather than
 * rendering the copilot (see `require-staff-auth.tsx`).
 */
export default function StaffChatPage() {
  return (
    <RequireStaffAuth>
      <div className="flex flex-1 items-start justify-center px-4 py-16">
        <ChatWidget />
      </div>
    </RequireStaffAuth>
  );
}
