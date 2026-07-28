"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { RequireAuth } from "@/lib/auth/require-auth";
import { useAuth } from "@/lib/auth/auth-context";
import { sendReminder } from "@/lib/api/scheduling";
import { ApiError } from "@/lib/api/client";
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

function ReminderForm() {
  const { authorizedFetch } = useAuth();
  const [appointmentId, setAppointmentId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [delivered, setDelivered] = useState<boolean | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setDelivered(null);

    if (!appointmentId.trim()) {
      setError("Appointment ID is required.");
      return;
    }

    setSubmitting(true);
    try {
      const result = await sendReminder(authorizedFetch, appointmentId.trim());
      setDelivered(result.delivered);
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
          <CardTitle>Request a reminder</CardTitle>
          <CardDescription>
            Send a confirmation reminder for an upcoming appointment.
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit} noValidate>
          <CardContent className="flex flex-col gap-4">
            {error ? (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            {delivered !== null ? (
              <Alert variant={delivered ? "default" : "destructive"}>
                <AlertDescription>
                  {delivered
                    ? "Reminder delivered."
                    : "Reminder could not be delivered right now. It will be retried per policy."}
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
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Sending..." : "Send reminder"}
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

export default function ReminderPage() {
  return (
    <RequireAuth>
      <ReminderForm />
    </RequireAuth>
  );
}
