import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CredentialsLoginCard } from "../credentials-login-card";

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

describe("CredentialsLoginCard", () => {
  it("renders the given title/description and tenant/email/password fields", () => {
    render(
      <CredentialsLoginCard
        title="Sign in to Kureha Staff"
        description="For clinic staff only."
        error={null}
        submitting={false}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByText(/sign in to kureha staff/i)).toBeInTheDocument();
    expect(screen.getByText(/for clinic staff only\./i)).toBeInTheDocument();
    expect(screen.getByLabelText(/clinic \/ tenant id/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });

  it("shows a validation error and does not call onSubmit when fields are empty", () => {
    const onSubmit = vi.fn();
    render(
      <CredentialsLoginCard
        title="Sign in"
        description="desc"
        error={null}
        submitting={false}
        onSubmit={onSubmit}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /^sign in$/i }));

    expect(screen.getByText(/all fields are required/i)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("calls onSubmit with trimmed field values when the form is valid", () => {
    const onSubmit = vi.fn();
    render(
      <CredentialsLoginCard
        title="Sign in"
        description="desc"
        error={null}
        submitting={false}
        onSubmit={onSubmit}
      />,
    );

    fillForm({ tenantId: " tenant-1 ", email: " a@example.com ", password: "secret" });
    fireEvent.click(screen.getByRole("button", { name: /^sign in$/i }));

    expect(onSubmit).toHaveBeenCalledWith({
      tenantId: "tenant-1",
      email: "a@example.com",
      password: "secret",
    });
  });

  it("renders the caller-supplied error message (e.g. backend login failure) via an alert", () => {
    render(
      <CredentialsLoginCard
        title="Sign in"
        description="desc"
        error="Invalid credentials"
        submitting={false}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Invalid credentials");
  });

  it("disables the submit button and shows a submitting label while submitting", () => {
    render(
      <CredentialsLoginCard
        title="Sign in"
        description="desc"
        error={null}
        submitting
        onSubmit={vi.fn()}
      />,
    );

    const button = screen.getByRole("button", { name: /signing in/i });
    expect(button).toBeDisabled();
  });
});
