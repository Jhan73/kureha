#!/usr/bin/env bash
# Creates the S3 bucket for the SPA's static assets (design.md §20.1, §22.2).
set -euo pipefail

awslocal s3 mb s3://kureha-spa-dev
