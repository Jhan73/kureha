# Secrets Manager (design.md §20.1/§20.3, ADR-12/ADR-14/ADR-15): KEK, Google
# OAuth client, IdP (Supabase) credentials, plus the internal signing
# secrets `backend/app/config.py` requires a production override for.
#
# RDS master/app_runtime credentials and the composed DATABASE_URL/
# RUNTIME_DATABASE_URL secrets live in `modules/rds` instead (they are
# intrinsically tied to the DB instance Terraform creates there), not here.
#
# **External creds (KEK, Google OAuth, Supabase): Terraform creates the
# secret CONTAINER with an obviously-fake placeholder value only.** The real
# sensitive payload is populated out-of-band (`aws secretsmanager
# put-secret-value`, outside any VCS-tracked Terraform state/config) --
# mirrors `infra/localstack/init/01_secrets.sh`'s own "NEVER reuse this
# value outside local development" posture, but for a REAL secret this time.
# `lifecycle.ignore_changes` stops a future `terraform apply` from ever
# reverting an operator's real value back to the placeholder.
#
# **Internal signing/HMAC secrets (access-token JWT secret, OAuth CSRF
# state secret): Terraform generates these itself** via `random_password` --
# they are not external third-party credentials with an out-of-band
# rotation dependency, so Terraform owning their generation is safe and
# conventional. Same caveat as `modules/rds`: their plaintext ends up in
# Terraform state, which is why an encrypted remote backend with restricted
# IAM access is mandatory (see envs/prod/backend.tf).
#
# **Anthropic API key: not named anywhere in design.md §20's Secrets Manager
# table**, a real omission discovered while wiring this module (the LLM
# provider, `backend/app/config.py`'s `anthropic_api_key`, has no secret
# without it) -- added here pragmatically, flagged in tasks.md's closure
# note rather than silently worked around.

resource "aws_secretsmanager_secret" "kek" {
  name                    = "${var.name_prefix}/kek"
  description             = "AES-256-GCM Key Encryption Key wrapping calendar_credentials/refresh_token DEKs (design.md ADR-12). Real value set out-of-band."
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "kek" {
  secret_id     = aws_secretsmanager_secret.kek.id
  secret_string = jsonencode({ kek_base64 = "CHANGE_ME_OUT_OF_BAND", version = 1 })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "google_oauth" {
  name                    = "${var.name_prefix}/google-oauth"
  description             = "Google Calendar OAuth2 client credentials (design.md §7.3). Real value set out-of-band."
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "google_oauth" {
  secret_id     = aws_secretsmanager_secret.google_oauth.id
  secret_string = jsonencode({ client_id = "CHANGE_ME_OUT_OF_BAND", client_secret = "CHANGE_ME_OUT_OF_BAND" })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# Matches backend/app/config.py: supabase_url, supabase_publishable_key, supabase_secret_key.
resource "aws_secretsmanager_secret" "supabase" {
  name                    = "${var.name_prefix}/supabase"
  description             = "Supabase Auth IdP URL + publishable/secret API keys (current keys, not legacy anon/service_role)."
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "supabase" {
  secret_id = aws_secretsmanager_secret.supabase.id
  secret_string = jsonencode({
    url              = "CHANGE_ME_OUT_OF_BAND"
    publishable_key  = "CHANGE_ME_OUT_OF_BAND"
    secret_key       = "CHANGE_ME_OUT_OF_BAND"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name                    = "${var.name_prefix}/anthropic-api-key"
  description             = "LLM provider API key (backend/app/config.py Settings.anthropic_api_key) -- not named in design.md §20's Secrets Manager table, added here as a flagged gap-fill. Real value set out-of-band."
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "anthropic_api_key" {
  secret_id     = aws_secretsmanager_secret.anthropic_api_key.id
  secret_string = "CHANGE_ME_OUT_OF_BAND"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "random_password" "identity_access_token_secret" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "identity_access_token_secret" {
  name                    = "${var.name_prefix}/identity-access-token-secret"
  description             = "Kureha access-JWT signing secret (design.md ADR-15). Terraform-generated."
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "identity_access_token_secret" {
  secret_id     = aws_secretsmanager_secret.identity_access_token_secret.id
  secret_string = random_password.identity_access_token_secret.result
}

resource "random_password" "calendar_oauth_state_secret" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "calendar_oauth_state_secret" {
  name                    = "${var.name_prefix}/calendar-oauth-state-secret"
  description             = "HMAC secret for Google Calendar OAuth2 anti-CSRF state (design.md §7.3). Terraform-generated."
  recovery_window_in_days = var.recovery_window_in_days
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "calendar_oauth_state_secret" {
  secret_id     = aws_secretsmanager_secret.calendar_oauth_state_secret.id
  secret_string = random_password.calendar_oauth_state_secret.result
}
