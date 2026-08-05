# Supabase Setup for Kureha

Step-by-step guide to provision and configure the Supabase project that backs Kureha's `AuthPort` (identity module). This is an operational runbook, not an architecture doc — for the *why*, see `openspec/changes/kureha-mvp/design.md` §17.2 (ADR-14) and §17 (ADR-15).

## Scope: what Supabase is (and isn't) used for

Supabase is used **standalone, as an IdP only** — Auth (GoTrue), nothing else:

- Handles credential mechanics: email/password hashing, "Sign in with Google" federation, anti brute-force, invite emails, password-reset emails.
- **Never** stores clinical data. Kureha's own database (RLS, `users`, `patients`, `appointments`, ...) lives entirely in AWS RDS and never migrates to Supabase Postgres.
- Kureha does **not** forward Supabase's own JWT to clients. `backend/app/modules/identity/adapters/outbound/auth/supabase_auth_adapter.py` is the *only* code in the system that talks to the Supabase API; on a successful Supabase authentication, Kureha mints its **own** short-lived access token + opaque refresh token (ADR-15) so revocation/logout never depends on Supabase's admin API.
- The frontend never calls Supabase directly — there is no `@supabase/supabase-js` client anywhere in `frontend/`. All auth traffic goes through Kureha's own `POST /auth/*` routes.

Because of that standalone posture, the usual reason to pick Supabase (`auth.uid()` inside Postgres RLS policies) does not apply here — see ADR-14 for the full tradeoff. Keep that in mind: **do not** wire Supabase Postgres, Supabase RLS, or the Supabase JS client into this project. If a future task seems to need that, it contradicts the current architecture decision — flag it, don't just add it.

## Prerequisites

- A Supabase account (free tier is sufficient for local dev/staging — see "Free tier considerations" below).
- Access to edit this repo's `.env.local` (gitignored; copy from `.env.local.example` if you haven't).

## 1. Create the project

Dashboard: [supabase.com/dashboard](https://supabase.com/dashboard) → **New project** → pick an organization, name (e.g. `kureha-dev`), a database password, and a region. `Kureha625@*`

> The project's own Postgres database is provisioned automatically but **Kureha never uses it** (see Scope above) — you can ignore it entirely once the project is up. Only the Auth service matters.

design.md §22.6 calls out that dev and production must be **separate Supabase projects** — don't reuse a dev project's credentials for staging/prod.

## 2. Get your API credentials

Dashboard → **Project Settings → API** (newer projects show this under **API Keys**, with `publishable`/`secret` naming replacing the older `anon`/`service_role` naming — both key pairs work identically for Kureha's purposes; if your project shows the new names, `publishable` = `anon`, `secret` = `service_role`).

Copy three values into `.env.local` at the repo root:

| Dashboard value | `.env.local` variable | `Settings` field (`backend/app/config.py`) |
|---|---|---|
| Project URL | `SUPABASE_URL` | `supabase_url` |
| `anon` / `publishable` key | `SUPABASE_ANON_KEY` | `supabase_anon_key` |
| `service_role` / `secret` key | `SUPABASE_SERVICE_ROLE_KEY` | `supabase_service_role_key` |

**`SUPABASE_SERVICE_ROLE_KEY` is admin-privileged — it bypasses GoTrue's own row-level authorization and can act as any user.** It is read only by the backend process (used exclusively by `SupabaseAuthAdapter.invite_user`, the staff-invite flow). Never expose it to the frontend, never commit it — `.env.local` is already gitignored, and there is no safe placeholder value for it (unlike other secrets in this repo, `config.py` deliberately leaves its default as `None` rather than an "obviously fake" dev string, to avoid it being mistaken for a real key if ever copy-pasted).

## 3. Email/password provider

Dashboard → **Authentication → Providers → Email**. Enabled by default — leave it on, Kureha's `/auth/login` (password grant) and `/staff/register` (invite) both depend on it.

**Recommended hardening, not strictly required for correctness:** under **Authentication → Providers → Email**, consider disabling **"Allow new users to sign up"**. Kureha never calls Supabase's self-serve signup endpoint — staff accounts are created only via `POST /staff/register` → `SupabaseAuthAdapter.invite_user` (admin-triggered invite), and patient self-registration isn't implemented yet (`PostgresUserDirectory.provision_patient_user` is a deliberate `NotImplementedError`, see that method's docstring). If someone signs up directly against Supabase outside of Kureha's own flow, `Login.with_password`/`with_google` will still deny them (`UnmappedIdentityError`, no matching `users` row in Kureha's own DB) — so this isn't a security hole today, but disabling self-serve signup removes the dangling capability entirely rather than relying on that second check.

## 4. Google federated login ("Sign in with Google")

Dashboard → **Authentication → Providers → Google**.

1. In [Google Auth Platform](https://console.cloud.google.com/auth/clients) → **Create OAuth client ID** → application type **Web application**.
2. **Authorized JavaScript origins**: your frontend's origin(s) — `http://localhost:3000` for local dev, plus the real domain once deployed.
3. **Authorized redirect URIs**: your Supabase project's callback URL, shown on the same Google provider page in the Supabase Dashboard (`https://<project-ref>.supabase.co/auth/v1/callback`; for local Supabase CLI dev it's `http://127.0.0.1:54321/auth/v1/callback`).
4. Copy the generated **Client ID** and **Client Secret** into the Google provider page in the Supabase Dashboard, and enable the provider.

Kureha's `SupabaseAuthAdapter.verify_federated` calls `POST /auth/v1/token?grant_type=id_token` with `{"provider": "google", "id_token": ...}` — this is the same underlying call `supabase-js`'s `signInWithIdToken` makes, so a frontend using Google's own Sign-In button (One Tap, GSI button, etc.) to obtain a raw Google ID token and posting it to Kureha's own login route is enough; no `supabase-js` dependency is needed client-side.

**Hard boundary, don't confuse the two:** this is a *separate* OAuth client from the one used for Google Calendar sync (`CalendarSyncPort`/`calendar_oauth.py`) — different scopes (`openid email` vs `calendar.events`), different token stores, different consent screens. Never reuse credentials or tokens between the two (ADR-11/12, design.md §17.2).

## 5. Custom SMTP (required before real usage — see "Free tier considerations")

Dashboard → **Project Settings → Authentication → SMTP Settings** (or via the Management API):

```bash
export SUPABASE_ACCESS_TOKEN="<personal access token from supabase.com/dashboard/account/tokens>"
export PROJECT_REF="<your-project-ref>"

curl -X PATCH "https://api.supabase.com/v1/projects/$PROJECT_REF/config/auth" \
  -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "smtp_admin_email": "no-reply@your-domain.example",
    "smtp_host": "smtp.your-provider.example",
    "smtp_port": 587,
    "smtp_user": "your-smtp-user",
    "smtp_pass": "your-smtp-password",
    "smtp_sender_name": "Kureha"
  }'
```

Any SMTP-compatible provider works (Resend, SendGrid, Mailgun, etc.). Pick one with a free tier generous enough for staff invites + password resets during dev/pilot.

## 6. Redirect URLs for invite / password-reset emails — flagged gap

Dashboard → **Authentication → URL Configuration**: set **Site URL** and add the frontend's invite-completion and password-reset pages to **Redirect URLs**.

**This is currently unconfigured in code, not silently working — read before shipping to staff.** `SupabaseAuthAdapter.invite_user`/`start_password_reset` (the code behind `/staff/register` and `/auth/password-reset/request`) call GoTrue's `/auth/v1/invite` and `/auth/v1/recover` with **no `redirect_to` parameter**. Per Supabase's own docs, when no `redirect_to` is set (or it isn't in the allowlist), the email link falls back to whatever **Site URL** is configured for the project — it will **not** automatically point at whatever frontend page is meant to catch the invite/recovery token. Until a future revision threads a real `redirect_to` through both calls, set **Site URL** to the frontend's login page as a safe fallback, and treat "the invite/reset email lands on the right frontend screen" as unverified.

## 7. Verify against a real project before relying on this in production

`supabase_auth_adapter.py`'s own module docstring flags that `invite_user`'s and `complete_password_reset`'s request/response shapes were written against GoTrue's documented API, **never smoke-tested against a real Supabase project** (this dev environment has no reachable Supabase instance). Specifically unverified:

- Whether `POST /auth/v1/invite`'s response is the bare `User` object (assumed) or wrapped as `{"user": ...}`.
- Whether `PUT /auth/v1/user` (password-reset confirm) responds the same way.

Before the first real staff invite goes out: run both flows once against your actual Supabase project and confirm the adapter parses the real response without a `KeyError`.

## Free tier considerations

The free tier itself is generous enough for this project's scale (50,000 MAU, 2 active projects — see design.md ADR-14's own "gratis hasta decenas de miles de MAU" assumption). The one real blocker is **email**: Supabase's built-in mailer is capped at **2 emails/hour** and is explicitly not meant for production use. Since `/staff/register` and `/auth/password-reset/request` both depend on an email actually being delivered, **step 5 (custom SMTP) is required**, not optional, the moment you need more than two invites/resets in the same hour — which will happen the first time more than one staff member gets provisioned in a sitting.

## `.env.local` reference

```bash
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_ANON_KEY=<anon/publishable key>
SUPABASE_SERVICE_ROLE_KEY=<service_role/secret key>
```

All three are read once at process start via `backend/app/config.py`'s `Settings` (pydantic-settings, `env_file=".env.local"`). No frontend env vars are needed — the frontend never talks to Supabase directly.
