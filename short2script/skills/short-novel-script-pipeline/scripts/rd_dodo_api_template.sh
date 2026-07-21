#!/bin/bash
set -euo pipefail

# RD usage:
#   export DODO_API_KEY="<token>"
#   python3 skills/short-novel-script-pipeline/scripts/pipeline_runner.py \
#     --novel <novel.txt> \
#     --run-config configs/company_vote_fire_40ep.json \
#     --run-id <run_id> \
#     --generate-episodes 40 \
#     --llm-script skills/short-novel-script-pipeline/scripts/rd_dodo_api_template.sh \
#     --timeout 2400
#
# This template intentionally contains no API key and does not read local .env files.
# Customize endpoint/model/env vars in RD runtime or CI, not in the checked-in script.

: "${DODO_API_KEY:=${DODO_TOKEN:-}}"
if [ -z "${DODO_API_KEY}" ]; then
  echo "Error: set DODO_API_KEY or DODO_TOKEN before running rd_dodo_api_template.sh." >&2
  exit 1
fi
export DODO_API_KEY

export DODO_ENDPOINT="${DODO_ENDPOINT:-https://oneapi-comate.baidu-int.com/v1/messages}"
export DODO_MODEL="${DODO_MODEL:-Claude Sonnet 4.6}"
export DODO_EFFORT_LEVELS="${DODO_EFFORT_LEVELS:-high medium low}"
export DODO_MAX_TOKENS="${DODO_MAX_TOKENS:-24000}"
export CURL_MAX_TIME="${CURL_MAX_TIME:-2400}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
exec "${SCRIPT_DIR}/dodo_sonnet46_pipeline.sh" "$@"
