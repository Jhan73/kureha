import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppointmentSummary } from "../appointment-summary";
import type { AppointmentResponse } from "@/lib/api/types";

const appointment: AppointmentResponse = {
  id: "appt-1",
  tenant_id: "tenant-1",
  site_id: "site-1",
  patient_id: "patient-1",
  professional_id: "prof-1",
  starts_at: "2026-08-01T10:00:00.000Z",
  ends_at: "2026-08-01T10:30:00.000Z",
  status: "scheduled",
};

describe("AppointmentSummary", () => {
  it("renders the appointment id, status, professional, and site", () => {
    render(<AppointmentSummary appointment={appointment} />);

    expect(screen.getByText("appt-1")).toBeInTheDocument();
    expect(screen.getByText("scheduled")).toBeInTheDocument();
    expect(screen.getByText("prof-1")).toBeInTheDocument();
    expect(screen.getByText("site-1")).toBeInTheDocument();
  });
});
