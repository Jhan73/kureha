#!/usr/bin/env bash
# Creates the SNS topic used for audit hash-chain tamper/heartbeat alerts
# (design.md ADR-19, §4.3).
set -euo pipefail

awslocal sns create-topic --name kureha-audit-alerts-dev
