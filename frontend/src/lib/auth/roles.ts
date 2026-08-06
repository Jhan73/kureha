// Mirrors backend `_STAFF_ROLES`; keep in sync by review (independently deployable).
export const STAFF_ROLES = ["reception", "professional", "admin"] as const;

export type StaffRole = (typeof STAFF_ROLES)[number];

export function isStaffRole(role: string): role is StaffRole {
  return (STAFF_ROLES as readonly string[]).includes(role);
}
