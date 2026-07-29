import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRouter } from "next/navigation";
import { RequireStaffAuth } from "../require-staff-auth";
import { useAuth } from "../auth-context";
import type { AuthContextValue } from "../auth-context";

vi.mock("../auth-context", async () => {
  const actual =
    await vi.importActual<typeof import("../auth-context")>("../auth-context");
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

describe("RequireStaffAuth", () => {
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

  it("redirects to /staff/login (not /login) when there is no access token", async () => {
    mockAuth({ accessToken: null, silentRefresh: vi.fn().mockResolvedValue(false) });

    render(
      <RequireStaffAuth>
        <div>Staff area</div>
      </RequireStaffAuth>,
    );

    expect(screen.queryByText("Staff area")).toBeNull();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/staff/login"));
  });

  it("renders protected content for each staff role (reception, professional, admin)", async () => {
    for (const role of ["reception", "professional", "admin"]) {
      mockAuth({ accessToken: "access-1", user: { userId: "user-1", role } });

      const { unmount } = render(
        <RequireStaffAuth>
          <div>Staff area</div>
        </RequireStaffAuth>,
      );

      expect(await screen.findByText("Staff area")).toBeInTheDocument();
      unmount();
    }
  });

  it("logs out and redirects to /staff/login when an authenticated PATIENT loads a staff page", async () => {
    const logout = vi.fn();
    mockAuth({ accessToken: "access-1", user: { userId: "patient-1", role: "patient" }, logout });

    render(
      <RequireStaffAuth>
        <div>Staff area</div>
      </RequireStaffAuth>,
    );

    expect(screen.queryByText("Staff area")).toBeNull();
    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/staff/login"));
  });
});
