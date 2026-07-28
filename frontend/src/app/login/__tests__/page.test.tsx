import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRouter } from "next/navigation";
import LoginPage from "../page";
import { useAuth } from "../../../lib/auth/auth-context";
import { ApiError } from "../../../lib/api/client";
import type { AuthContextValue } from "../../../lib/auth/auth-context";

vi.mock("../../../lib/auth/auth-context", () => ({ useAuth: vi.fn() }));
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
    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: email },
    });
  }
  if (password !== undefined) {
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: password },
    });
  }
}

describe("LoginPage", () => {
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

  it("renders tenant, email, and password fields and a disabled Google sign-in button", () => {
    mockAuth({});
    render(<LoginPage />);

    expect(screen.getByLabelText(/clinic \/ tenant id/i)).toBeDefined();
    expect(screen.getByLabelText(/email/i)).toBeDefined();
    expect(screen.getByLabelText(/password/i)).toBeDefined();

    const googleButton = screen.getByRole("button", { name: /sign in with google/i });
    expect(googleButton).toBeDisabled();
  });

  it("shows a validation error and does not call login when fields are empty", async () => {
    const login = vi.fn();
    mockAuth({ login });
    render(<LoginPage />);

    fireEvent.click(screen.getByRole("button", { name: /^sign in$/i }));

    expect(await screen.findByText(/all fields are required/i)).toBeDefined();
    expect(login).not.toHaveBeenCalled();
  });

  it("submits credentials and redirects to /portal on success", async () => {
    const login = vi.fn().mockResolvedValueOnce(undefined);
    mockAuth({ login });
    render(<LoginPage />);

    fillForm({ tenantId: "tenant-1", email: "a@example.com", password: "secret" });
    fireEvent.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() =>
      expect(login).toHaveBeenCalledWith({
        tenantId: "tenant-1",
        email: "a@example.com",
        password: "secret",
      }),
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/portal"));
  });

  it("shows the backend's error message and does not redirect on login failure", async () => {
    const login = vi.fn().mockRejectedValueOnce(new ApiError(401, "Invalid credentials"));
    mockAuth({ login });
    render(<LoginPage />);

    fillForm({ tenantId: "tenant-1", email: "a@example.com", password: "wrong" });
    fireEvent.click(screen.getByRole("button", { name: /^sign in$/i }));

    expect(await screen.findByText("Invalid credentials")).toBeDefined();
    expect(push).not.toHaveBeenCalled();
  });
});
