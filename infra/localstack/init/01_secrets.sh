#!/usr/bin/env bash
# Creates the KEK secret in LocalStack Secrets Manager for local dev.
#
# The KEK (Key Encryption Key) wraps the DEKs used to envelope-encrypt
# calendar_credentials and refresh tokens (design.md ADR-12, §7.4). In
# production this secret lives in AWS Secrets Manager, provisioned outside
# of application code; here it's a fixed dev-only value so local runs are
# reproducible. NEVER reuse this value outside local development.
set -euo pipefail

awslocal secretsmanager create-secret \
  --name kureha/dev/kek \
  --secret-string '{"kek_base64":"TBnaThNXqzXXZiFWiPL8bicqY1kgpef/gpwBGGn3QeY=","version":1}'
