"use client";

import { useState, type FormEvent } from "react";
import { IconBrandGoogle } from "@tabler/icons-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";

export interface CredentialsLoginValues {
  tenantId: string;
  email: string;
  password: string;
}

export interface CredentialsLoginCardProps {
  title: string;
  description: string;
  /** Caller-supplied error, e.g. the backend's login-failure message. */
  error: string | null;
  submitting: boolean;
  onSubmit: (values: CredentialsLoginValues) => void;
}

/**
 * Shared tenant/email/password credentials card, extracted from tasks.md
 * 14.1's original `/login/page.tsx` (this task, 15.1, is its second real
 * caller: `/staff/login/page.tsx`) -- per `frontend/AGENTS.md`'s "extract
 * repeated UI into shared components... avoid duplicated implementations".
 * Purely presentational: owns only field state + client-side "all fields
 * required" validation; the caller owns the actual `login()` call, its own
 * post-login navigation/role-check, and any server-side error to display
 * (`error` prop).
 */
export function CredentialsLoginCard({
  title,
  description,
  error,
  submitting,
  onSubmit,
}: CredentialsLoginCardProps) {
  const [tenantId, setTenantId] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidationError(null);

    if (!tenantId.trim() || !email.trim() || !password) {
      setValidationError("All fields are required.");
      return;
    }

    onSubmit({ tenantId: tenantId.trim(), email: email.trim(), password });
  }

  const displayedError = validationError ?? error;

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <form onSubmit={handleSubmit} noValidate>
        <CardContent className="flex flex-col gap-4">
          {displayedError ? (
            <Alert variant="destructive">
              <AlertDescription>{displayedError}</AlertDescription>
            </Alert>
          ) : null}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="tenant-id">Clinic / Tenant ID</Label>
            <Input
              id="tenant-id"
              name="tenant-id"
              value={tenantId}
              onChange={(event) => setTenantId(event.target.value)}
              autoComplete="organization"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              name="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              name="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
            />
          </div>
        </CardContent>
        <CardFooter className="flex flex-col gap-3">
          <Button type="submit" className="w-full" disabled={submitting}>
            {submitting ? "Signing in..." : "Sign in"}
          </Button>
          {/* No federated-login request contract exists on the backend yet
              (see auth.py's own docstring) -- rendered visibly but
              disabled, never a fake/mocked Google flow. Same for both the
              patient and staff login cards. */}
          <Button
            type="button"
            variant="outline"
            className="w-full"
            disabled
            title="Google sign-in is not available yet"
          >
            <IconBrandGoogle aria-hidden="true" />
            Sign in with Google (coming soon)
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}
