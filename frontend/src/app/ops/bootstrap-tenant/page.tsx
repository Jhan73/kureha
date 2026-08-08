"use client";

import { useState, type FormEvent } from "react";
import { ApiError, bootstrapTenant, retryAdminInvite } from "@/lib/api/client";
import type { TenantBootstrapResponse } from "@/lib/api/types";
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
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

function errorMessageFor(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.status) {
      case 401:
        return "Operator key is missing or invalid.";
      case 409:
        return "That tenant already exists.";
      case 422:
        return error.message || "Check the form: some fields are invalid.";
      case 429:
        return "Too many bootstrap attempts for this operator key. Try again later.";
      default:
        return error.message || "Something went wrong. Please try again.";
    }
  }
  return "Something went wrong. Please try again.";
}

export default function BootstrapTenantPage() {
  const [operatorKey, setOperatorKey] = useState("");
  const [name, setName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [siteName, setSiteName] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TenantBootstrapResponse | null>(null);

  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setRetryError(null);

    if (!operatorKey.trim() || !name.trim() || !adminEmail.trim()) {
      setError("Operator key, tenant name, and admin email are required.");
      return;
    }

    setSubmitting(true);
    try {
      const response = await bootstrapTenant(
        {
          name: name.trim(),
          adminEmail: adminEmail.trim(),
          tenantId: tenantId.trim() || undefined,
          siteName: siteName.trim() || undefined,
        },
        operatorKey.trim(),
      );
      setResult(response);
    } catch (err) {
      setError(errorMessageFor(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRetryInvite() {
    if (!result) {
      return;
    }
    setRetryError(null);
    setRetrying(true);
    try {
      const response = await retryAdminInvite(
        result.tenant_id,
        {
          siteId: result.site_id,
          adminUserId: result.admin_user_id,
          adminEmail: result.admin_email,
        },
        operatorKey.trim(),
      );
      setResult({ ...result, credential_status: response.credential_status });
    } catch (err) {
      setRetryError(errorMessageFor(err));
    } finally {
      setRetrying(false);
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center px-4 py-16">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Bootstrap tenant</CardTitle>
          <CardDescription>
            Internal Kureha ops tool. Creates a tenant, its first site, and its admin
            user. Not for tenant self-service.
          </CardDescription>
        </CardHeader>
        <form onSubmit={(event) => void handleSubmit(event)} noValidate>
          <CardContent className="flex flex-col gap-4">
            {error ? (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="operator-key">Operator key</Label>
              <Input
                id="operator-key"
                name="operator-key"
                type="password"
                value={operatorKey}
                onChange={(event) => setOperatorKey(event.target.value)}
                autoComplete="off"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="tenant-name">Tenant name</Label>
              <Input
                id="tenant-name"
                name="tenant-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="admin-email">Admin email</Label>
              <Input
                id="admin-email"
                name="admin-email"
                type="email"
                value={adminEmail}
                onChange={(event) => setAdminEmail(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="tenant-id">Tenant ID (optional)</Label>
              <Input
                id="tenant-id"
                name="tenant-id"
                value={tenantId}
                onChange={(event) => setTenantId(event.target.value)}
                placeholder="Auto-generated if left blank"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="site-name">Site name (optional)</Label>
              <Input
                id="site-name"
                name="site-name"
                value={siteName}
                onChange={(event) => setSiteName(event.target.value)}
              />
            </div>
          </CardContent>
          <CardFooter className="flex flex-col gap-3">
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Bootstrapping..." : "Bootstrap tenant"}
            </Button>
          </CardFooter>
        </form>

        {result ? (
          <CardContent className="flex flex-col gap-3 border-t pt-4">
            <Alert>
              <AlertTitle>Tenant created</AlertTitle>
              <AlertDescription>
                <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1">
                  <dt className="text-muted-foreground">Tenant ID</dt>
                  <dd>{result.tenant_id}</dd>
                  <dt className="text-muted-foreground">Site ID</dt>
                  <dd>{result.site_id}</dd>
                  <dt className="text-muted-foreground">Admin user ID</dt>
                  <dd>{result.admin_user_id}</dd>
                  <dt className="text-muted-foreground">Admin email</dt>
                  <dd>{result.admin_email}</dd>
                </dl>
              </AlertDescription>
            </Alert>
            {result.credential_status === "invite_failed" ? (
              <Alert variant="destructive">
                <AlertTitle>Invite failed</AlertTitle>
                <AlertDescription>
                  The tenant and admin were created, but the invite email could not be
                  sent. Retry the invite without re-running bootstrap.
                </AlertDescription>
              </Alert>
            ) : null}
            {retryError ? (
              <Alert variant="destructive">
                <AlertDescription>{retryError}</AlertDescription>
              </Alert>
            ) : null}
            {result.credential_status === "invite_failed" ? (
              <Button
                type="button"
                variant="outline"
                className="w-full"
                disabled={retrying}
                onClick={() => void handleRetryInvite()}
              >
                {retrying ? "Retrying..." : "Retry invite"}
              </Button>
            ) : null}
          </CardContent>
        ) : null}
      </Card>
    </div>
  );
}
