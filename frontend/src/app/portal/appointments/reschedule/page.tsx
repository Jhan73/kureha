"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { RequireAuth } from "@/lib/auth/require-auth";
import { useAuth } from "@/lib/auth/auth-context";
import { rescheduleAppointment } from "@/lib/api/scheduling";
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

function RescheduleForm() {
  const { authorizedFetch } = useAuth();
  const [appointmentId, setAppointmentId] = useState("");
  const [newAvailabilityId, setNewAvailabilityId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [updated, setUpdated] = useState<AppointmentResponse | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setUpdated(null);

    if (!appointmentId.trim() || !newAvailabilityId.trim()) {
      setError("All fields are required.");
      return;
    }

    setSubmitting(true);
    try {
      const appointment = await rescheduleAppointment(authorizedFetch, {
        appointmentId: appointmentId.trim(),
        newAvailabilityId: newAvailabilityId.trim(),
      });
      setUpdated(appointment);
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
          <CardTitle>Reschedule an appointment</CardTitle>
          <CardDescription>
            Move an existing appointment to a different available slot.
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit} noValidate>
          <CardContent className="flex flex-col gap-4">
            {error ? (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            {updated ? (
              <Alert>
                <AlertDescription>
                  Appointment rescheduled.
                  <AppointmentSummary appointment={updated} />
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
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="new-availability-id">New availability ID</Label>
              <Input
                id="new-availability-id"
                name="new-availability-id"
                value={newAvailabilityId}
                onChange={(event) => setNewAvailabilityId(event.target.value)}
              />
            </div>
          </CardContent>
          <CardFooter className="flex flex-col gap-3">
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Rescheduling..." : "Reschedule appointment"}
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

export default function ReschedulePage() {
  return (
    <RequireAuth>
      <RescheduleForm />
    </RequireAuth>
  );
}
