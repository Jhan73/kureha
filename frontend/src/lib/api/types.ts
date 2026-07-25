// Shape of the backend's `TokenResponse` (see
// backend/app/platform/inbound/api/routers/auth.py). Field names stay in
// snake_case to mirror the wire format exactly -- no client-side renaming.
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  user_id: string;
  role: string;
}

export interface LoginParams {
  tenantId: string;
  email: string;
  password: string;
}
