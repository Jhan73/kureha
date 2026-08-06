"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/auth-context";
import { ApiError } from "@/lib/api/client";
import { isStaffRole } from "@/lib/auth/roles";
import {
  CredentialsLoginCard,
  type CredentialsLoginValues,
} from "@/components/auth/credentials-login-card";

const NOT_STAFF_MESSAGE =
  "This portal is for staff accounts only (reception, professional, or admin).";

export default function StaffLoginPage() {
  const { login, logout } = useAuth();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(values: CredentialsLoginValues) {
    setError(null);
    setSubmitting(true);
    try {
      const user = await login(values);
      if (isStaffRole(user.role)) {
        router.push("/staff");
      } else {
        await logout();
        setError(NOT_STAFF_MESSAGE);
      }
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
        title="Sign in to Kureha Staff"
        description="Reception, professional, and admin accounts only."
        error={error}
        submitting={submitting}
        onSubmit={(values) => void handleSubmit(values)}
      />
    </div>
  );
}
