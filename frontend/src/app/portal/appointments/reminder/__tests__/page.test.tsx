import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRouter } from "next/navigation";
import ReminderPage from "../page";
import { useAuth } from "@/lib/auth/auth-context";
import type { AuthContextValue } from "@/lib/auth/auth-context";
import { sendReminder } from "@/lib/api/scheduling";
import { ApiError } from "@/lib/api/client";

vi.mock("@/lib/auth/auth-context", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/auth/auth-context")>(
      "@/lib/auth/auth-context",
    );
  return { ...actual, useAuth: vi.fn() };
});
vi.mock("@/lib/api/scheduling", () => ({
  sendReminder: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: vi.fn() }));

function mockAuth(overrides: Partial<AuthContextValue>) {
  vi.mocked(useAuth).mockReturnValue({
    accessToken: "access-1",
    user: { userId: "user-1", role: "patient" },
    login: vi.fn(),
    logout: vi.fn(),
    silentRefresh: vi.fn().mockResolvedValue(false),
    authorizedFetch: vi.fn(),
    ...overrides,
  });
}

describe("ReminderPage", () => {
  beforeEach(() => {
    vi.mocked(useRouter).mockReturnValue({
      push: vi.fn(),
      replace: vi.fn(),
      back: vi.fn(),
      forward: vi.fn(),
      refresh: vi.fn(),
      prefetch: vi.fn(),
    });
  });

  it("redirects to /login through RequireAuth when unauthenticated", async () => {
    const replace = vi.fn();
    vi.mocked(useRouter).mockReturnValue({
      push: vi.fn(),
      replace,
      back: vi.fn(),
      forward: vi.fn(),
      refresh: vi.fn(),
      prefetch: vi.fn(),
    });
    mockAuth({ accessToken: null, silentRefresh: vi.fn().mockResolvedValue(false) });

    render(<ReminderPage />);

    expect(screen.queryByLabelText(/appointment id/i)).toBeNull();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  it("validates that the appointment id is required before submitting", () => {
    mockAuth({});
    render(<ReminderPage />);

    fireEvent.click(screen.getByRole("button", { name: /send reminder/i }));

    expect(screen.getByText(/appointment id is required/i)).toBeInTheDocument();
    expect(sendReminder).not.toHaveBeenCalled();
  });

  it("submits the form and shows delivery status on success", async () => {
    const authorizedFetch = vi.fn();
    mockAuth({ authorizedFetch });
    vi.mocked(sendReminder).mockResolvedValueOnce({ delivered: true });

    render(<ReminderPage />);
    fireEvent.change(screen.getByLabelText(/appointment id/i), {
      target: { value: "appt-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send reminder/i }));

    await waitFor(() => expect(sendReminder).toHaveBeenCalledWith(authorizedFetch, "appt-1"));
    expect(await screen.findByText(/reminder delivered/i)).toBeInTheDocument();
  });

  it("shows delivered: false distinctly from a delivered reminder", async () => {
    mockAuth({});
    vi.mocked(sendReminder).mockResolvedValueOnce({ delivered: false });

    render(<ReminderPage />);
    fireEvent.change(screen.getByLabelText(/appointment id/i), {
      target: { value: "appt-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send reminder/i }));

    expect(await screen.findByText(/reminder could not be delivered/i)).toBeInTheDocument();
  });

  it("shows the backend's error message on failure", async () => {
    mockAuth({});
    vi.mocked(sendReminder).mockRejectedValueOnce(new ApiError(404, "Appointment not found"));

    render(<ReminderPage />);
    fireEvent.change(screen.getByLabelText(/appointment id/i), {
      target: { value: "does-not-exist" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send reminder/i }));

    expect(await screen.findByText("Appointment not found")).toBeInTheDocument();
  });

  it("blocks submission and shows the consent message when the backend denies for missing consent", async () => {
    mockAuth({});
    vi.mocked(sendReminder).mockRejectedValueOnce(
      new ApiError(403, "You must accept the informed consent before continuing."),
    );

    render(<ReminderPage />);
    fireEvent.change(screen.getByLabelText(/appointment id/i), {
      target: { value: "appt-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send reminder/i }));

    expect(
      await screen.findByText("You must accept the informed consent before continuing."),
    ).toBeInTheDocument();
  });
});
