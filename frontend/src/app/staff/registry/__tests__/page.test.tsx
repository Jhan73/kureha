import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRouter } from "next/navigation";
import StaffRegistryPage from "../page";
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

describe("StaffRegistryPage", () => {
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

  it("redirects to /staff/login through RequireStaffAuth when unauthenticated", async () => {
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

    render(<StaffRegistryPage />);

    expect(screen.queryByRole("alert")).toBeNull();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/staff/login"));
  });

  it("shows a real, honest gap notice for an authenticated staff user -- no fake registry/shift form is rendered", async () => {
    mockAuth({ accessToken: "access-1", user: { userId: "staff-1", role: "admin" } });

    render(<StaffRegistryPage />);

    const notice = await screen.findByRole("alert");
    expect(notice).toHaveTextContent(/not available yet/i);
    // No fake CRUD form exists (no name/site/role inputs, no submit button) --
    // this page is explicitly a documented gap, never invented behavior.
    expect(screen.queryByRole("form")).toBeNull();
    expect(screen.queryByRole("button", { name: /register|create|save/i })).toBeNull();
  });

  it("links back to the copilot chat as the only currently functional way to register staff / manage shifts", async () => {
    mockAuth({ accessToken: "access-1", user: { userId: "staff-1", role: "admin" } });

    render(<StaffRegistryPage />);

    await screen.findByRole("alert");
    expect(screen.getByRole("link", { name: /chat with tony/i })).toHaveAttribute(
      "href",
      "/staff/chat",
    );
  });
});
