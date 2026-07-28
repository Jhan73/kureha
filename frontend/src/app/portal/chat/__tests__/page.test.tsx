import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRouter } from "next/navigation";
import ChatPage from "../page";
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

describe("ChatPage", () => {
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

    render(<ChatPage />);

    expect(screen.queryByLabelText(/message/i)).toBeNull();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  it("renders the chat widget when authenticated", async () => {
    mockAuth({ accessToken: "access-1", user: { userId: "user-1", role: "patient" } });

    render(<ChatPage />);

    expect(await screen.findByLabelText(/message/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send/i })).toBeInTheDocument();
  });
});
