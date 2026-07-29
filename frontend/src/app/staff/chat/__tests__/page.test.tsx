import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRouter } from "next/navigation";
import StaffChatPage from "../page";
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

describe("StaffChatPage", () => {
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

    render(<StaffChatPage />);

    expect(screen.queryByLabelText(/message/i)).toBeNull();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/staff/login"));
  });

  it("redirects a PATIENT session away, not rendering the copilot", async () => {
    const replace = vi.fn();
    vi.mocked(useRouter).mockReturnValue({
      push: vi.fn(),
      replace,
      back: vi.fn(),
      forward: vi.fn(),
      refresh: vi.fn(),
      prefetch: vi.fn(),
    });
    mockAuth({ accessToken: "access-1", user: { userId: "patient-1", role: "patient" } });

    render(<StaffChatPage />);

    expect(screen.queryByLabelText(/message/i)).toBeNull();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/staff/login"));
  });

  it("renders the SAME ChatWidget used by the patient portal for an authenticated staff user", async () => {
    mockAuth({ accessToken: "access-1", user: { userId: "staff-1", role: "reception" } });

    render(<StaffChatPage />);

    expect(await screen.findByLabelText(/message/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send/i })).toBeInTheDocument();
    expect(screen.getByText(/chat with tony/i)).toBeInTheDocument();
  });
});
