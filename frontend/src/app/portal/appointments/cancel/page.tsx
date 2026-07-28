"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { RequireAuth } from "@/lib/auth/require-auth";
import { useAuth } from "@/lib/auth/auth-context";
import { cancelAppointment } from "@/lib/api/scheduling";
import { ApiError } from "@/lib/api/client";
import type { AppointmentResponse } from "@/lib/api/types";
import { AppointmentSummary } from "@/components/appointments/appointment-summary";
import { Button, buttonVariants } from "@/components/ui/button";
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

function CancelForm() {
  const { authorizedFetch } = useAuth();
  const [appointmentId, setAppointmentId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [cancelled, setCancelled] = useState<AppointmentResponse | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setCancelled(null);

    if (!appointmentId.trim()) {
      setError("Appointment ID is required.");
      return;
    }

    setSubmitting(true);
    try {
      const appointment = await cancelAppointment(authorizedFetch, appointmentId.trim());
      setCancelled(appointment);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Something went wrong. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-1 items-start justify-center px-4 py-16">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Cancel an appointment</CardTitle>
          <CardDescription>
            This immediately cancels the appointment -- this action cannot be
            undone from this form.
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit} noValidate>
          <CardContent className="flex flex-col gap-4">
            {error ? (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            {cancelled ? (
              <Alert>
                <AlertDescription>
                  Appointment cancelled.
                  <AppointmentSummary appointment={cancelled} />
                </AlertDescription>
              </Alert>
            ) : null}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="appointment-id">Appointment ID</Label>
              <Input
                id="appointment-id"
                name="appointment-id"
                value={appointmentId}
                onChange={(event) => setAppointmentId(event.target.value)}
              />
            </div>
          </CardContent>
          <CardFooter className="flex flex-col gap-3">
            <Button type="submit" variant="destructive" className="w-full" disabled={submitting}>
              {submitting ? "Cancelling..." : "Cancel appointment"}
            </Button>
            <Link
              href="/portal"
              className={buttonVariants({ variant: "outline", className: "w-full" })}
            >
              Back to portal
            </Link>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}

export default function CancelPage() {
  return (
    <RequireAuth>
      <CancelForm />
    </RequireAuth>
  );
}
