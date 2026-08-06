# Supabase setup for Kureha

This guide walks you through every value needed so Kureha can use Supabase Auth as its identity provider (IdP).

You do **not** need to change application source code for a normal setup. You fill the [Supabase Dashboard](https://supabase.com/dashboard) and the repo-root file `.env.local`. The backend reads those env vars via `backend/app/config.py` (`Settings`) and passes them into `SupabaseAuthAdapter`.

Architecture background (why Supabase is IdP-only): `openspec/changes/kureha-mvp/design.md` §17.

---

## Before you start

| Fact | Detail |
|---|---|
| What Supabase is used for | Auth only (email/password, invites, password reset, optional Google ID-token verify) |
| What Supabase is **not** used for | Postgres, Storage, Realtime, Edge Functions, `@supabase/supabase-js` in the frontend |
| Where secrets live | Repo root `.env.local` (gitignored). Template: `.env.local.example` |
| Where code reads them | `backend/app/config.py` → `composition_root.py` → `supabase_auth_adapter.py` |
| Frontend | Never talks to Supabase. No Supabase env vars in `frontend/` |
| Environments | Use **separate** Supabase projects for local/dev and production |

Create `.env.local` once if missing:

```bash
cp .env.local.example .env.local
```

After any change to `.env.local`, **restart the backend** (settings load at process start).

---

## Quick path

1. Create a Supabase project.
2. Copy **Project URL**, **publishable key**, and **secret key** into `.env.local`.
3. Set **Site URL** and **Redirect URLs** in the Dashboard; set `FRONTEND_BASE_URL` in `.env.local`.
4. Email provider: on; public sign-up: off.
5. (Optional) Google provider.
6. (Required for real invites) Custom SMTP.
7. Restart backend → run the checklist at the end.

---

## How to read each section

Every value below uses the same shape:

- **How to get it** — clicks in the Dashboard (or Google Cloud).
- **Format** — what a correct value looks like (and what to avoid).
- **Where to put it** — `.env.local`, Dashboard only, or both.
- **Used by** — which Kureha behavior needs it.

---

## 1. Create the project

1. Open [supabase.com/dashboard](https://supabase.com/dashboard) and sign in.
2. Click **New project**.
3. Fill the form:

| Dashboard field | What to enter |
|---|---|
| Organization | Your org (create one if needed) |
| Project name | e.g. `kureha-dev` or `kureha-prod` |
| Database password | Strong password; store in a password manager. Kureha **never** connects to this database |
| Region | Closest to your users / API |

4. Wait until the project is ready.

Ignore the project’s Postgres after creation. Only Auth settings matter for Kureha.

---

## 2. `SUPABASE_URL`

### How to get it

1. Open your project in the Dashboard.
2. Open **Connect** (project home) **or** **Project Settings → Data API**.
3. Copy **Project URL**.

Direct pattern: `https://supabase.com/dashboard/project/<project-ref>/settings/api`

### Format

| | Example |
|---|---|
| Correct | `https://abcdefghijklmnop.supabase.co` |
| Wrong | Missing `https://`, trailing path (`/rest/v1`), or `http://` on cloud projects |

`<project-ref>` is the short id in the hostname (also visible in the browser URL while you are inside the project).

### Where to put it

| Place | Action |
|---|---|
| `.env.local` (repo root) | `SUPABASE_URL=https://<project-ref>.supabase.co` |
| Application code | **No change.** Mapped to `Settings.supabase_url` in `backend/app/config.py` |
| Frontend | Not used |

### Used by

Every Supabase Auth HTTP call (login, invite, recover, password update). Base URL for `SupabaseAuthAdapter`.

---

## 3. `SUPABASE_PUBLISHABLE_KEY`

Use the **current** publishable key. Do **not** use Legacy `anon` JWT keys ([API keys guide](https://supabase.com/docs/guides/getting-started/api-keys); legacy keys deprecated by end of 2026).

### How to get it

1. **Project Settings → API Keys**  
   `https://supabase.com/dashboard/project/<project-ref>/settings/api-keys`
2. Open the **API Keys** tab (not **Legacy API Keys**).
3. If there is no publishable key yet, click **Create new API Keys**.
4. Copy the **Publishable** key (`sb_publishable_...`).

### Format

| | Example |
|---|---|
| Correct | `sb_publishable_eyJ...` (starts with `sb_publishable_`) |
| Wrong | Long JWT from **Legacy API Keys** labeled `anon` |
| Wrong | A `sb_secret_...` key (that is the secret key) |

### Where to put it

| Place | Action |
|---|---|
| `.env.local` | `SUPABASE_PUBLISHABLE_KEY=sb_publishable_...` |
| Application code | **No change.** Mapped to `Settings.supabase_publishable_key` |
| Frontend | **Never.** Not a public Next.js env var in this repo |

### Used by

Password login, start password-reset, Google ID-token verify. Sent as the `apikey` header on those GoTrue calls.

---

## 4. `SUPABASE_SECRET_KEY`

Elevated key. Backend only. Never commit, never put in the frontend, never paste into chat logs.

Use the **current** secret key. Do **not** use Legacy `service_role` JWT keys.

### How to get it

1. Same page: **Project Settings → API Keys** → **API Keys** tab.
2. Under **Secret keys**, copy (or create) a secret key (`sb_secret_...`).
3. Reveal/copy carefully; treat it like a root password.

### Format

| | Example |
|---|---|
| Correct | `sb_secret_...` (starts with `sb_secret_`) |
| Wrong | Legacy `service_role` JWT from **Legacy API Keys** |
| Wrong | The publishable key |

### Where to put it

| Place | Action |
|---|---|
| `.env.local` | `SUPABASE_SECRET_KEY=sb_secret_...` |
| Application code | **No change.** Mapped to `Settings.supabase_secret_key` → `SupabaseAuthAdapter(secret_key=...)` |
| Frontend | **Forbidden** |
| Production (AWS) | Secrets Manager JSON key `secret_key` → ECS env `SUPABASE_SECRET_KEY` (see `infra/terraform/modules/secrets` and `ecs`) |

### Used by

Staff invite only: `POST /staff/register` → `invite_user` → GoTrue `POST /auth/v1/invite` with `apikey` + `Authorization: Bearer <secret>`.

---

## 5. `FRONTEND_BASE_URL`

Not a Supabase secret. It is the public origin of the Kureha SPA. The backend builds invite / password-reset `redirect_to` URLs from it.

### How to get it

You choose it; it must match how users open the frontend:

| Environment | Value |
|---|---|
| Local (`next dev`) | `http://localhost:3000` |
| Production | Your real SPA origin, e.g. `https://app.example.com` |

No trailing slash.

### Format

| | Example |
|---|---|
| Correct | `http://localhost:3000` |
| Correct | `https://app.example.com` |
| Wrong | `http://localhost:3000/` (trailing slash) |
| Wrong | `localhost:3000` (missing scheme) |

### Where to put it

| Place | Action |
|---|---|
| `.env.local` | `FRONTEND_BASE_URL=http://localhost:3000` |
| Application code | **No change.** Mapped to `Settings.frontend_base_url` |
| Also required | Same origin should appear in `CORS_ALLOWED_ORIGINS` (comma-separated list in `.env.local` / `Settings.cors_allowed_origins`) |
| Supabase Dashboard | The concrete redirect URLs derived from this value must be allow-listed (next section) |

### Used by

| Flow | `redirect_to` the backend sends |
|---|---|
| Staff invite | `{FRONTEND_BASE_URL}/staff/login` |
| Password reset request | `{FRONTEND_BASE_URL}` |

---

## 6. Site URL (Dashboard only)

Default redirect when GoTrue has no usable `redirect_to`. Still set it correctly so fallbacks are safe.

### How to get it / where to click

**Authentication → URL Configuration**  
`https://supabase.com/dashboard/project/<project-ref>/auth/url-configuration`

### Format / what to enter

| Environment | Site URL |
|---|---|
| Local | `http://localhost:3000` |
| Production | `https://app.example.com` |

Same rules as `FRONTEND_BASE_URL` (scheme + host + optional port; no trailing slash).

### Where to put it

| Place | Action |
|---|---|
| Supabase Dashboard | Field **Site URL** |
| `.env.local` / code | Not stored as its own env var; keep it equal to `FRONTEND_BASE_URL` |

### Used by

Fallback for Auth email links. Official docs: [Redirect URLs](https://supabase.com/docs/guides/auth/redirect-urls).

---

## 7. Redirect URLs (Dashboard only)

Allow-list of URLs GoTrue may redirect to after invite / recovery links. If a URL is missing here, Supabase ignores `redirect_to` and falls back to Site URL.

### How to get it / where to click

Same page: **Authentication → URL Configuration** → **Redirect URLs** → add each URL → save.

### Format / what to enter

Add **exact** URLs Kureha sends (minimum):

**Local**

```text
http://localhost:3000
http://localhost:3000/staff/login
```

Optional for local experiments: `http://localhost:3000/**`

**Production**

```text
https://app.example.com
https://app.example.com/staff/login
```

### Where to put it

| Place | Action |
|---|---|
| Supabase Dashboard | Redirect URLs list only |
| `.env.local` | Not a separate variable; keep `FRONTEND_BASE_URL` in sync with these entries |
| Application code | **No change.** Adapter already sends `redirect_to` |

### Used by

Invite and password-reset emails. Without these entries, redirects break silently.

### Note

Dedicated “set password” / “confirm reset” pages that consume the token from the URL are still a separate frontend gap. Allow-list the URLs anyway so GoTrue accepts them.

---

## 8. Email provider (Dashboard only)

### How to get it / where to click

**Authentication → Providers → Email**

### What to set

| Setting | Value | Why |
|---|---|---|
| Enable Email provider | **On** | Password login, invites, resets |
| Confirm email | Leave default unless you have a reason | Invite link handles staff confirmation |
| Allow new users to sign up | **Off** (recommended) | Kureha never uses public Supabase signup; staff come from `POST /staff/register` |

### Where to put it

Dashboard only. No `.env.local` entry. No code change.

### Used by

All email/password Auth flows in Kureha.

---

## 9. Google provider (optional)

Only if you need “Sign in with Google”. Kureha verifies a Google **ID token** on the server; the browser must obtain that token (e.g. Google Identity Services) and send it to Kureha’s login API — not to Supabase JS.

This Google OAuth client is **not** the Calendar sync client (`CALENDAR_GOOGLE_*`).

### A. Values from Google Cloud

#### How to get them

1. Open [Google Auth Platform → Clients](https://console.cloud.google.com/auth/clients).
2. **Create OAuth client ID** → application type **Web application**.
3. Fill:

| Field | Local | Production |
|---|---|---|
| Name | e.g. `Kureha Auth Dev` | e.g. `Kureha Auth Prod` |
| Authorized JavaScript origins | `http://localhost:3000` | `https://app.example.com` |
| Authorized redirect URIs | `https://<project-ref>.supabase.co/auth/v1/callback` | Same pattern for the prod project ref |

4. Copy **Client ID** and **Client Secret**.

#### Format

| Value | Format |
|---|---|
| Client ID | `….apps.googleusercontent.com` |
| Client Secret | Opaque string from Google Cloud (not a Supabase key) |

#### Where to put them

| Place | Action |
|---|---|
| Supabase Dashboard | Paste into Google provider (next step) |
| Kureha `.env.local` | **Not** as `SUPABASE_*`. Do not reuse as `CALENDAR_GOOGLE_*` |
| Application code | No Supabase-side code change for enabling the provider |

### B. Enable in Supabase

#### How to get it / where to click

**Authentication → Providers → Google** → enable → paste Client ID + Client Secret → save.

#### Where to put it

Dashboard only for provider enablement.

### Used by

`SupabaseAuthAdapter.verify_federated` → `POST /auth/v1/token?grant_type=id_token`.

---

## 10. Custom SMTP (Dashboard — required before real invites)

Built-in Supabase mail is capped (~2 emails/hour). Staff invite and password reset need real delivery → configure SMTP early.

### How to get it / where to click

**Project Settings → Authentication** → **SMTP Settings** (label may say Auth / SMTP).

Get host/user/password from your email provider (Resend, SendGrid, Mailgun, SES, …).

### Format / fields

| Field | Example format |
|---|---|
| Sender email | `no-reply@your-domain.example` (verified domain at your provider) |
| Sender name | `Kureha` |
| Host | Provider SMTP hostname |
| Port | Usually `587` (STARTTLS); follow provider docs |
| Username | SMTP user or API user |
| Password | SMTP password or API key |

### Where to put it

| Place | Action |
|---|---|
| Supabase Dashboard | SMTP Settings form |
| `.env.local` / Kureha code | **Not stored.** Supabase sends the mail |

### Optional Management API

Personal access token: [Account → Access Tokens](https://supabase.com/dashboard/account/tokens).

```bash
export SUPABASE_ACCESS_TOKEN="<personal-access-token>"
export PROJECT_REF="<project-ref>"

curl -X PATCH "https://api.supabase.com/v1/projects/$PROJECT_REF/config/auth" \
  -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "smtp_admin_email": "no-reply@your-domain.example",
    "smtp_host": "smtp.your-provider.example",
    "smtp_port": "587",
    "smtp_user": "your-smtp-user",
    "smtp_pass": "your-smtp-password",
    "smtp_sender_name": "Kureha"
  }'
```

---

## 11. Full `.env.local` example (local)

After copying from `.env.local.example`, the Supabase-related block should look like:

```bash
SUPABASE_URL=https://abcdefghijklmnop.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
SUPABASE_SECRET_KEY=sb_secret_...
FRONTEND_BASE_URL=http://localhost:3000
```

Then restart the backend.

**You do not edit Python/TS source** for these values in normal setup. Wiring already exists:

| Env var | Settings field | Consumed in |
|---|---|---|
| `SUPABASE_URL` | `supabase_url` | `SupabaseAuthAdapter(base_url=...)` |
| `SUPABASE_PUBLISHABLE_KEY` | `supabase_publishable_key` | `SupabaseAuthAdapter(api_key=...)` |
| `SUPABASE_SECRET_KEY` | `supabase_secret_key` | `SupabaseAuthAdapter(secret_key=...)` (invites) |
| `FRONTEND_BASE_URL` | `frontend_base_url` | Invite / reset `redirect_to` builders in `composition_root.py` |

---

## 12. Checklist

- [ ] Separate Supabase project for this environment (not shared with prod).
- [ ] `SUPABASE_URL` is `https://<ref>.supabase.co`.
- [ ] `SUPABASE_PUBLISHABLE_KEY` starts with `sb_publishable_` (not legacy `anon` JWT).
- [ ] `SUPABASE_SECRET_KEY` starts with `sb_secret_` (not legacy `service_role` JWT).
- [ ] `FRONTEND_BASE_URL` matches Site URL (no trailing slash).
- [ ] Redirect URLs include `{FRONTEND_BASE_URL}` and `{FRONTEND_BASE_URL}/staff/login`.
- [ ] Email provider on; public sign-up off.
- [ ] (If Google) provider enabled; Cloud origins/callback correct.
- [ ] Custom SMTP saved before bulk invites.
- [ ] Backend restarted after editing `.env.local`.
- [ ] `POST /auth/login` works for a Kureha-mapped user.
- [ ] `POST /staff/register` sends invite mail.
- [ ] `POST /auth/password-reset/request` delivers mail.

Before first production invite: run invite + password-reset confirm once against the real project and confirm the adapter parses live JSON (no `KeyError` on `id` / `email`).

---

## Related files

| File | Role |
|---|---|
| `.env.local.example` | Template for env names |
| `backend/app/config.py` | `Settings` field definitions |
| `backend/app/composition_root.py` | Wires adapter + redirect URLs |
| `backend/app/modules/identity/adapters/outbound/auth/supabase_auth_adapter.py` | GoTrue HTTP calls |
| `infra/terraform/modules/secrets` | Prod Secrets Manager shape (`url`, `publishable_key`, `secret_key`) |
| `docs/tenant-admin-provisioning.md` | Staff invite product flow |
