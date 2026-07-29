import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRouter } from "next/navigation";
import { RequireAuth } from "../require-auth";
import { useAuth } from "../auth-context";
import type { AuthContextValue } from "../auth-context";

vi.mock("../auth-context", () => ({ useAuth: vi.fn() }));
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

describe("RequireAuth", () => {
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

  it("redirects to /login when there is no access token and silent refresh fails", async () => {
    mockAuth({ accessToken: null, silentRefresh: vi.fn().mockResolvedValue(false) });

    render(
      <RequireAuth>
        <div>Protected</div>
      </RequireAuth>,
    );

    expect(screen.queryByText("Protected")).toBeNull();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("Protected")).toBeNull();
  });

  it("redirects to a caller-supplied redirectTo instead of /login when provided", async () => {
    mockAuth({ accessToken: null, silentRefresh: vi.fn().mockResolvedValue(false) });

    render(
      <RequireAuth redirectTo="/staff/login">
        <div>Protected</div>
      </RequireAuth>,
    );

    expect(screen.queryByText("Protected")).toBeNull();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/staff/login"));
  });

  it("renders protected content immediately when an access token is already present", async () => {
    mockAuth({ accessToken: "access-1" });

    render(
      <RequireAuth>
        <div>Protected</div>
      </RequireAuth>,
    );

    expect(await screen.findByText("Protected")).toBeDefined();
    expect(replace).not.toHaveBeenCalled();
  });

  it("silently refreshes and renders protected content when a persisted refresh token yields a new access token", async () => {
    mockAuth({ accessToken: null, silentRefresh: vi.fn().mockResolvedValue(true) });

    render(
      <RequireAuth>
        <div>Protected</div>
      </RequireAuth>,
    );

    expect(screen.queryByText("Protected")).toBeNull();
    expect(await screen.findByText("Protected")).toBeDefined();
    expect(replace).not.toHaveBeenCalled();
  });

  it("shows a loading state while the auth check is pending, never flashing protected content", async () => {
    let resolveRefresh: (value: boolean) => void = () => {};
    const pending = new Promise<boolean>((resolve) => {
      resolveRefresh = resolve;
    });
    mockAuth({ accessToken: null, silentRefresh: vi.fn().mockReturnValue(pending) });

    render(
      <RequireAuth>
        <div>Protected</div>
      </RequireAuth>,
    );

    expect(screen.queryByText("Protected")).toBeNull();
    expect(screen.getByRole("status")).toBeDefined();

    await act(async () => {
      resolveRefresh(true);
      await pending;
    });

    expect(await screen.findByText("Protected")).toBeDefined();
  });
});
