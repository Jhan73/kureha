#!/usr/bin/env bash
# Creates the CloudWatch log group used by the API and the LangGraph runtime
# (design.md §22.2).
set -euo pipefail

awslocal logs create-log-group --log-group-name /kureha/api/dev
