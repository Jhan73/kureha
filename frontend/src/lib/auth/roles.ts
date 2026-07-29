// Mirrors `backend/app/platform/inbound/api/routers/chat.py`'s
// `_STAFF_ROLES` frozenset (`{"reception", "professional", "admin"}`) --
// the same set the backend uses to pick the `staff_copilot` channel over
// `patient_chat` (design.md §8.6: "role del staff en lugar de patient_id").
// Not a cross-directory import (frontend/backend stay independently
// deployable per AGENTS.md) -- this is a deliberately duplicated constant,
// kept in sync by convention/review, the same way the wire-format types in
// `lib/api/types.ts` mirror backend Pydantic models without importing them.
export const STAFF_ROLES = ["reception", "professional", "admin"] as const;

export type StaffRole = (typeof STAFF_ROLES)[number];

export function isStaffRole(role: string): role is StaffRole {
  return (STAFF_ROLES as readonly string[]).includes(role);
}
