import { describe, expect, it } from "vitest";
import { isStaffRole, STAFF_ROLES } from "../roles";

describe("isStaffRole", () => {
  it("returns true for each staff role (reception, professional, admin)", () => {
    expect(isStaffRole("reception")).toBe(true);
    expect(isStaffRole("professional")).toBe(true);
    expect(isStaffRole("admin")).toBe(true);
  });

  it("returns false for the patient role", () => {
    expect(isStaffRole("patient")).toBe(false);
  });

  it("returns false for an unknown/unexpected role string", () => {
    expect(isStaffRole("some-future-role")).toBe(false);
  });
});

describe("STAFF_ROLES", () => {
  it("lists exactly the three staff roles the backend's chat router recognizes", () => {
    expect([...STAFF_ROLES].sort()).toEqual(["admin", "professional", "reception"]);
  });
});
