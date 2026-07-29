import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRouter } from "next/navigation";
import StaffLoginPage from "../page";
import { useAuth } from "@/lib/auth/auth-context";
import { ApiError } from "@/lib/api/client";
import type { AuthContextValue } from "@/lib/auth/auth-context";

vi.mock("@/lib/auth/auth-context", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/auth/auth-context")>(
      "@/lib/auth/auth-context",
    );
  return { ...actual, useAuth: vi.fn() };
});
vi.mock("next/navigation", () => ({ useRouter: vi.fn() }));

function mockAuth(overrides: Partial<AuthContextValue>) {
  vi.mocked(useAuth).mockReturnValue({
    accessToken: null,
    user: null,
    login: vi.fn(),
    logout: vi.fn(),
    silentRefresh: vi.fn(),
    authorizedFetch: vi.fn(),
    ...overrides,
  });
}

function fillForm({
  tenantId,
  email,
  password,
}: {
  tenantId?: string;
  email?: string;
  password?: string;
}) {
  if (tenantId !== undefined) {
    fireEvent.change(screen.getByLabelText(/clinic \/ tenant id/i), {
      target: { value: tenantId },
    });
  }
  if (email !== undefined) {
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: email } });
  }
  if (password !== undefined) {
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: password } });
  }
}

describe("StaffLoginPage", () => {
  const push = vi.fn();

  beforeEach(() => {
    push.mockReset();
    vi.mocked(useRouter).mockReturnValue({
      push,
      replace: vi.fn(),
      back: vi.fn(),
      forward: vi.fn(),
      refresh: vi.fn(),
      prefetch: vi.fn(),
    });
  });

  it("renders a staff-specific title and the tenant/email/password fields", () => {
    mockAuth({});
    render(<StaffLoginPage />);

    expect(screen.getByText(/sign in to kureha staff/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/clinic \/ tenant id/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });

  it("redirects to /staff on success for a reception/professional/admin role", async () => {
    const login = vi.fn().mockResolvedValueOnce({ userId: "user-1", role: "reception" });
    mockAuth({ login });
    render(<StaffLoginPage />);

    fillForm({ tenantId: "tenant-1", email: "reception@example.com", password: "secret" });
    fireEvent.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() =>
      expect(login).toHaveBeenCalledWith({
        tenantId: "tenant-1",
        email: "reception@example.com",
        password: "secret",
      }),
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/staff"));
  });

  it("rejects a successfully-authenticated PATIENT account, logs out, and does not redirect to /staff", async () => {
    const login = vi.fn().mockResolvedValueOnce({ userId: "patient-1", role: "patient" });
    const logout = vi.fn().mockResolvedValueOnce(undefined);
    mockAuth({ login, logout });
    render(<StaffLoginPage />);

    fillForm({ tenantId: "tenant-1", email: "patient@example.com", password: "secret" });
    fireEvent.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => expect(login).toHaveBeenCalled());
    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText(/this portal is for staff accounts only/i),
    ).toBeInTheDocument();
    expect(push).not.toHaveBeenCalledWith("/staff");
  });

  it("shows the backend's error message and does not redirect on login failure", async () => {
    const login = vi.fn().mockRejectedValueOnce(new ApiError(401, "Invalid credentials"));
    mockAuth({ login });
    render(<StaffLoginPage />);

    fillForm({ tenantId: "tenant-1", email: "a@example.com", password: "wrong" });
    fireEvent.click(screen.getByRole("button", { name: /^sign in$/i }));

    expect(await screen.findByText("Invalid credentials")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
