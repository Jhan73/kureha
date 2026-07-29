"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/auth-context";
import { ApiError } from "@/lib/api/client";
import {
  CredentialsLoginCard,
  type CredentialsLoginValues,
} from "@/components/auth/credentials-login-card";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(values: CredentialsLoginValues) {
    setError(null);
    setSubmitting(true);
    try {
      await login(values);
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
      <CredentialsLoginCard
        title="Sign in to Kureha"
        description="Enter your clinic and credentials to continue."
        error={error}
        submitting={submitting}
        onSubmit={(values) => void handleSubmit(values)}
      />
    </div>
  );
}
