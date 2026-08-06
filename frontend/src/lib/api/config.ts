// Inlined at build time: `output: "export"` leaves no server to read env vars at runtime.
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
