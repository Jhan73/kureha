"""user_credentials table for identity module authn resolution

Task 4.1-4.3 (openspec/changes/kureha-mvp/tasks.md, Phase 4). Design.md §17.3
states Kureha "resuelve el subject del IdP a una fila users", but neither
§4.1's `users` table nor any later migration carries a column to hold the
IdP's stable subject id or the email used to look it up in the first place --
`users` has no `email` column at all (8fc0dc6f958d), and PR 3's own review
note on the RLS migration (613f9ea3526f, point 3) already flagged this
explicitly as an open gap: "esto NO resuelve el identity-bootstrap
'chicken-and-egg' problem... la resolucion inicial de `users` por `sub`
externo... es arquitectura de Phase 4/5 (identity module), fuera de alcance
[de PR 3]."

DEVIATION FROM DESIGN.MD, FLAGGED NOT SILENTLY APPLIED: this migration adds a
new table, `user_credentials`, rather than `ALTER TABLE users ADD COLUMN
email/auth_subject/...`. Rationale:

- `users` is core-identity schema (Phase 2/PR 2), not owned by any single
  business module -- `staff_members`, `patients`, and RLS policies across
  several already-merged PRs all reference it. The identity module (a
  business module, tasks.md Phase 4) should not need to reopen/ALTER a
  foundational table it does not own to add columns only it reads/writes.
- A dedicated table keeps the authn-resolution concern (email, federated
  subject, email-verification timestamp) inside `modules/identity`'s own
  schema footprint, consistent with the hexagonal module boundary
  (backend/AGENTS.md: "governance/business modules never import another
  module's internals" -- the schema-ownership analogue of that rule).
- `UNIQUE(tenant_id, user_id)` keeps this MVP-scoped to one set of
  credentials per `users` row (matches design.md §17's single-IdP-per-user
  model; no multi-provider linking beyond the single Google<->password
  linking scenario the `user-authentication` spec describes).

Columns:
- `email`: the lookup key for both password login (`AuthPort.verify_password`
  takes an email) and federated-login account-linking (spec "Email
  Verification for Account Linking"). `NOT NULL` -- every authenticatable
  `users` row (patient or staff) must have exactly one email to resolve
  against; a `users` row with no self-service login capability (e.g. a staff
  member not yet invited) simply has no `user_credentials` row at all.
- `auth_subject`: the IdP's stable subject (`sub` claim), set once a Google
  sign-in links to this row (first-time or via explicit confirmation, spec
  "Google email matches an existing password account"). Nullable: a
  password-only account has no federated subject until/unless it links one.
  Plain `UNIQUE(tenant_id, auth_subject)` (not partial) is correct here --
  Postgres treats every NULL as distinct for a multi-column UNIQUE
  constraint, so any number of password-only rows with `auth_subject IS
  NULL` coexist without conflict; only a real, non-null subject collision is
  rejected.
- `email_verified_at`: NULL until verified. A federated (Google) email is
  pre-verified by the IdP -- callers set this at link time from
  `AuthnResult.email_verified`. A password-signup email starts NULL (spec
  "Unverified email blocks full access"); the verification-completion write
  path itself is out of Phase 4's task scope (tasks.md 4.1-4.6 lists
  "email-verification/account-linking flow" only for the Google-matches-
  existing-account scenario, not a general signup+verify endpoint), so no
  UPDATE-to-verified use case ships in this migration/PR.

RLS: same "tenant-only, system-tier" shape as `user_sessions_tenant`
(613f9ea3526f) -- this table is resolved by the identity module's pre-auth
lookup (`Login`/federated sign-in), which runs before any `app.*` GUC is
known (the same chicken-and-egg problem `user_sessions`' policy docstring
already documents) via the elevated `app.db.engine` connection (bypasses RLS
entirely, same as Alembic itself), never through a per-role request path.
The tenant-only policy here is a defense-in-depth backstop for the
`app_runtime` role in case anything ever *does* query this table under a
normal per-request connection -- it is not the primary access-control
mechanism for pre-auth resolution (that's "you're on `app_user`/elevated
or you can't resolve identity before authenticating at all", enforced by
the adapter wiring in the composition root -- see
`app/modules/identity/adapters/outbound/postgres/user_directory.py`'s module
docstring).

Revision ID: 9f1c4a7b2e3d
Revises: adacb9d7fd59
Create Date: 2026-07-14 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9f1c4a7b2e3d'
down_revision: Union[str, Sequence[str], None] = 'adacb9d7fd59'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE user_credentials (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          user_id uuid NOT NULL,
          email text NOT NULL,
          auth_subject text,
          email_verified_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id),
          UNIQUE (tenant_id, user_id),
          UNIQUE (tenant_id, email),
          UNIQUE (tenant_id, auth_subject)
        )
        """
    )

    op.execute("ALTER TABLE user_credentials ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_credentials FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY user_credentials_tenant ON user_credentials FOR ALL
          USING (current_setting('app.tenant_id')::uuid = tenant_id)
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY user_credentials_tenant ON user_credentials")
    op.execute("ALTER TABLE user_credentials NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_credentials DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE user_credentials")
