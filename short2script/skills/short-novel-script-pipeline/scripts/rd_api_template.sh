#!/bin/bash
set -euo pipefail

# RD usage:
#   export LLM_API_KEY="<token>"
#   python3 skills/short-novel-script-pipeline/scripts/pipeline_runner.py \
#     --novel <novel.txt> \
#     --run-config configs/company_vote_fire_40ep.json \
#     --run-id <run_id> \
#     --generate-episodes 40 \
#     --llm-script skills/short-novel-script-pipeline/scripts/rd_api_template.sh \
#     --timeout 2400
#
# This template intentionally contains no API key and does not read local .env files.
# Customize endpoint/model/env vars in RD runtime or CI, not in the checked-in script.

: "${LLM_API_KEY:=${LLM_TOKEN:-}}"
if [ -z "${LLM_API_KEY}" ]; then
  echo "Error: set LLM_API_KEY or LLM_TOKEN before running rd_api_template.sh." >&2
  exit 1
fi
export LLM_API_KEY

export LLM_ENDPOINT="${LLM_ENDPOINT:-https://api.example.com/v1/messages}"
export LLM_MODEL="${LLM_MODEL:-Claude Sonnet 4.6}"
export LLM_EFFORT_LEVELS="${LLM_EFFORT_LEVELS:-high medium low}"
export LLM_MAX_TOKENS="${LLM_MAX_TOKENS:-24000}"
export CURL_MAX_TIME="${CURL_MAX_TIME:-2400}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
exec "${SCRIPT_DIR}/claude_sonnet46_pipeline.sh" "$@"
