output "kek_secret_arn" {
  value = aws_secretsmanager_secret.kek.arn
}

output "google_oauth_secret_arn" {
  value = aws_secretsmanager_secret.google_oauth.arn
}

output "supabase_secret_arn" {
  value = aws_secretsmanager_secret.supabase.arn
}

output "anthropic_api_key_secret_arn" {
  value = aws_secretsmanager_secret.anthropic_api_key.arn
}

output "identity_access_token_secret_arn" {
  value = aws_secretsmanager_secret.identity_access_token_secret.arn
}

output "calendar_oauth_state_secret_arn" {
  value = aws_secretsmanager_secret.calendar_oauth_state_secret.arn
}
