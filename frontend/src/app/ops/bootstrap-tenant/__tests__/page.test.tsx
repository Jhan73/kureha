import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import BootstrapTenantPage from "../page";

function fillRequiredFields() {
  fireEvent.change(screen.getByLabelText(/operator key/i), {
    target: { value: "op-1.secret" },
  });
  fireEvent.change(screen.getByLabelText(/tenant name/i), {
    target: { value: "Clinica Sur" },
  });
  fireEvent.change(screen.getByLabelText(/admin email/i), {
    target: { value: "admin@clinica-sur.pe" },
  });
}

describe("BootstrapTenantPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("submits the form to /ops/tenants/bootstrap with the operator key header and renders the created ids", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        tenant_id: "tenant-1",
        site_id: "site-1",
        admin_user_id: "user-1",
        admin_email: "admin@clinica-sur.pe",
        credential_status: "invited",
      }),
    } as Response);

    render(<BootstrapTenantPage />);
    fillRequiredFields();
    fireEvent.click(screen.getByRole("button", { name: /bootstrap tenant/i }));

    await waitFor(() => expect(screen.getByText("tenant-1")).toBeInTheDocument());

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toContain("/ops/tenants/bootstrap");
    expect((init?.headers as Record<string, string>)["X-Kureha-Ops-Key"]).toBe("op-1.secret");
    const requestBody = JSON.parse(init?.body as string);
    expect(requestBody).toMatchObject({
      name: "Clinica Sur",
      admin_email: "admin@clinica-sur.pe",
    });
    expect(requestBody).not.toHaveProperty("tenant_id");
    expect(screen.queryByText(/invite failed/i)).toBeNull();
  });

  it("does not render a tenant ID field -- the database generates it", () => {
    render(<BootstrapTenantPage />);

    expect(screen.queryByLabelText(/tenant id/i)).toBeNull();
  });

  it("shows an operator-key error on a 401 and does not render a result", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: async () => ({ user_message: "Credenciales invalidas." }),
    } as Response);

    render(<BootstrapTenantPage />);
    fillRequiredFields();
    fireEvent.click(screen.getByRole("button", { name: /bootstrap tenant/i }));

    expect(await screen.findByText(/operator key is missing or invalid/i)).toBeInTheDocument();
    expect(screen.queryByText(/tenant created/i)).toBeNull();
  });

  it("offers a retry-invite action when credential_status is invite_failed, reusing the returned ids without asking the operator to retype them", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        tenant_id: "tenant-1",
        site_id: "site-1",
        admin_user_id: "user-1",
        admin_email: "admin@clinica-sur.pe",
        credential_status: "invite_failed",
      }),
    } as Response);

    render(<BootstrapTenantPage />);
    fillRequiredFields();
    fireEvent.click(screen.getByRole("button", { name: /bootstrap tenant/i }));

    const retryButton = await screen.findByRole("button", { name: /retry invite/i });

    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        tenant_id: "tenant-1",
        admin_user_id: "user-1",
        admin_email: "admin@clinica-sur.pe",
        credential_status: "invited",
      }),
    } as Response);

    fireEvent.click(retryButton);

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /retry invite/i })).toBeNull(),
    );

    const [url, init] = vi.mocked(fetch).mock.calls[1];
    expect(url).toContain("/ops/tenants/tenant-1/admin-invite");
    expect((init?.headers as Record<string, string>)["X-Kureha-Ops-Key"]).toBe("op-1.secret");
    expect(JSON.parse(init?.body as string)).toMatchObject({
      site_id: "site-1",
      admin_user_id: "user-1",
      admin_email: "admin@clinica-sur.pe",
    });
  });
});
