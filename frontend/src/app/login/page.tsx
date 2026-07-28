"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
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
import { useAuth } from "@/lib/auth/auth-context";
import { ApiError } from "@/lib/api/client";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [tenantId, setTenantId] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (!tenantId.trim() || !email.trim() || !password) {
      setError("All fields are required.");
      return;
    }

    setSubmitting(true);
    try {
      await login({ tenantId: tenantId.trim(), email: email.trim(), password });
      router.push("/portal");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Something went wrong. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center px-4 py-16">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Sign in to Kureha</CardTitle>
          <CardDescription>
            Enter your clinic and credentials to continue.
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit} noValidate>
          <CardContent className="flex flex-col gap-4">
            {error ? (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
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
                disabled, never a fake/mocked Google flow. */}
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
    </div>
  );
}
