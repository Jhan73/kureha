# Remote state backend -- MANDATORY before any real `terraform apply`.
#
# `modules/rds` composes plaintext DB credentials/DSNs into Terraform state
# by design (see modules/rds/main.tf's own comment on that tradeoff);
# `modules/secrets` generates internal signing secrets the same way. Local
# state (the Terraform default) would put those secrets on whatever
# machine/CI runner applies this config, unencrypted, with no locking --
# not acceptable for anything touching real patient-adjacent infrastructure
# (Ley 29733).
#
# Left commented out here because this repo does not yet own a
# pre-existing S3 bucket + DynamoDB table for state -- an operator must
# provision those out-of-band (or via a small separate bootstrap Terraform
# config, deliberately not this one, to avoid a chicken-and-egg dependency
# on the backend it's trying to create) before uncommenting this block and
# running `terraform init -migrate-state`.
#
# terraform {
#   backend "s3" {
#     bucket         = "kureha-terraform-state"
#     key            = "kureha-mvp/prod/terraform.tfstate"
#     region         = "us-east-1"
#     dynamodb_table = "kureha-terraform-locks"
#     encrypt        = true
#   }
# }
