import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRouter } from "next/navigation";
import StaffDashboardPage from "../page";
import { useAuth } from "@/lib/auth/auth-context";
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
    silentRefresh: vi.fn().mockResolvedValue(false),
    authorizedFetch: vi.fn(),
    ...overrides,
  });
}

describe("StaffDashboardPage", () => {
  const replace = vi.fn();

  beforeEach(() => {
    replace.mockReset();
    vi.mocked(useRouter).mockReturnValue({
      replace,
      push: vi.fn(),
      back: vi.fn(),
      forward: vi.fn(),
      refresh: vi.fn(),
      prefetch: vi.fn(),
    });
  });

  it("redirects to /staff/login (through RequireStaffAuth) when unauthenticated", async () => {
    mockAuth({ accessToken: null, silentRefresh: vi.fn().mockResolvedValue(false) });

    render(<StaffDashboardPage />);

    expect(screen.queryByText(/welcome/i)).toBeNull();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/staff/login"));
  });

  it("greets the staff user by role and links to the copilot chat and registry views", async () => {
    mockAuth({ accessToken: "access-1", user: { userId: "user-1", role: "reception" } });

    render(<StaffDashboardPage />);

    expect(await screen.findByText(/welcome, reception/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /chat with tony/i })).toHaveAttribute(
      "href",
      "/staff/chat",
    );
    expect(screen.getByRole("link", { name: /staff registry.*shifts/i })).toHaveAttribute(
      "href",
      "/staff/registry",
    );
  });

  it("logs out via the real logout call when the log out button is clicked", async () => {
    const logout = vi.fn();
    mockAuth({ accessToken: "access-1", user: { userId: "user-1", role: "admin" }, logout });

    render(<StaffDashboardPage />);

    await screen.findByText(/welcome, admin/i);
    fireEvent.click(screen.getByRole("button", { name: /log out/i }));

    expect(logout).toHaveBeenCalledTimes(1);
  });
});
