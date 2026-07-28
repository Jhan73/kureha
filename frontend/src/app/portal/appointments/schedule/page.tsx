"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { RequireAuth } from "@/lib/auth/require-auth";
import { useAuth } from "@/lib/auth/auth-context";
import { scheduleAppointment } from "@/lib/api/scheduling";
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

function ScheduleForm() {
  const { authorizedFetch } = useAuth();
  const [patientId, setPatientId] = useState("");
  const [professionalId, setProfessionalId] = useState("");
  const [siteId, setSiteId] = useState("");
  const [availabilityId, setAvailabilityId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [created, setCreated] = useState<AppointmentResponse | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setCreated(null);

    if (
      !patientId.trim() ||
      !professionalId.trim() ||
      !siteId.trim() ||
      !availabilityId.trim()
    ) {
      setError("All fields are required.");
      return;
    }

    setSubmitting(true);
    try {
      const appointment = await scheduleAppointment(authorizedFetch, {
        patientId: patientId.trim(),
        professionalId: professionalId.trim(),
        siteId: siteId.trim(),
        availabilityId: availabilityId.trim(),
      });
      setCreated(appointment);
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
          <CardTitle>Schedule an appointment</CardTitle>
          <CardDescription>
            Book a new appointment for an available slot.
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit} noValidate>
          <CardContent className="flex flex-col gap-4">
            {error ? (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            {created ? (
              <Alert>
                <AlertDescription>
                  Appointment created.
                  <AppointmentSummary appointment={created} />
                </AlertDescription>
              </Alert>
            ) : null}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="patient-id">Patient ID</Label>
              <Input
                id="patient-id"
                name="patient-id"
                value={patientId}
                onChange={(event) => setPatientId(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="professional-id">Professional ID</Label>
              <Input
                id="professional-id"
                name="professional-id"
                value={professionalId}
                onChange={(event) => setProfessionalId(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="site-id">Site ID</Label>
              <Input
                id="site-id"
                name="site-id"
                value={siteId}
                onChange={(event) => setSiteId(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="availability-id">Availability ID</Label>
              <Input
                id="availability-id"
                name="availability-id"
                value={availabilityId}
                onChange={(event) => setAvailabilityId(event.target.value)}
              />
            </div>
          </CardContent>
          <CardFooter className="flex flex-col gap-3">
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Scheduling..." : "Schedule appointment"}
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

export default function SchedulePage() {
  return (
    <RequireAuth>
      <ScheduleForm />
    </RequireAuth>
  );
}
