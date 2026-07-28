// `output: "export"` builds this SPA with no server, so `NEXT_PUBLIC_*` vars
// are inlined at build time (see frontend/.env.local.example).
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
