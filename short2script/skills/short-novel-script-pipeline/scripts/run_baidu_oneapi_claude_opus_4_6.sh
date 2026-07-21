#!/usr/bin/env bash
set -euo pipefail

# Baidu OneAPI Anthropic-compatible Claude Opus 4.6 runner.
# Default env file is intentionally outside the repository; do not commit keys.
#
# Expected runtime:
# - model: Claude Opus 4.6
# - max_tokens: 128000
# - thinking.type: adaptive
# - output_config.effort: high

ENV_FILE="${BAIDU_ONEAPI_ENV_FILE:-/Users/cjlbd/Desktop/Code/.env-baidu-oneapi-data-0708}"
[ -f "${ENV_FILE}" ] || { printf 'Missing env file: %s\n' "${ENV_FILE}" >&2; exit 1; }

ENV_PARSED="$(
  python3 - "${ENV_FILE}" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
values = {}
for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or line.startswith(";"):
        continue
    if line.startswith("export "):
        line = line[len("export "):].strip()
    if "=" not in line:
        continue
    name, value = line.split("=", 1)
    name = name.strip()
    value = value.strip().strip('"').strip("'")
    values[name] = value

base_url = values.get("BASE_URL") or values.get("base_url") or ""
api_key = (
    values.get("ONEAPI_API_KEY")
    or values.get("oneapi_api_key")
    or values.get("API_KEY")
    or values.get("api_key")
    or ""
)
print(base_url)
print(api_key)
PY
)"
BASE_URL="${BASE_URL:-$(printf '%s\n' "${ENV_PARSED}" | sed -n '1p')}"
ONEAPI_API_KEY="${ONEAPI_API_KEY:-$(printf '%s\n' "${ENV_PARSED}" | sed -n '2p')}"
[ -n "${BASE_URL}" ] || { printf 'Missing BASE_URL/base_url in %s\n' "${ENV_FILE}" >&2; exit 1; }
[ -n "${ONEAPI_API_KEY}" ] || { printf 'Missing ONEAPI_API_KEY in %s\n' "${ENV_FILE}" >&2; exit 1; }

BASE_URL="${BASE_URL%/}"
case "${BASE_URL}" in
  */messages) ENDPOINT="${BASE_URL}" ;;
  */v1) ENDPOINT="${BASE_URL}/messages" ;;
  *) ENDPOINT="${BASE_URL}/v1/messages" ;;
esac
MODEL="${BAIDU_ONEAPI_MODEL:-Claude Opus 4.6}"
MAX_TOKENS="${BAIDU_ONEAPI_MAX_TOKENS:-128000}"
THINKING_TYPE="${BAIDU_ONEAPI_THINKING_TYPE:-adaptive}"
EFFORT="${BAIDU_ONEAPI_EFFORT:-high}"
CURL_MAX_TIME="${CURL_MAX_TIME:-2400}"
STREAM="${BAIDU_ONEAPI_STREAM:-1}"

if [ "$#" -gt 0 ]; then
  PROMPT="$*"
else
  PROMPT="$(cat)"
fi

[ -n "${PROMPT}" ] || { printf 'Error: empty prompt.\n' >&2; exit 1; }

ATTEMPT_DIR="${LLM_ATTEMPT_DIR:-}"
if [ -n "${ATTEMPT_DIR}" ]; then
  mkdir -p "${ATTEMPT_DIR}"
  chmod 700 "${ATTEMPT_DIR}"
  WORK_DIR="${ATTEMPT_DIR}"
else
  WORK_DIR="$(mktemp -d)"
  cleanup() {
    rm -rf "${WORK_DIR}"
  }
  trap cleanup EXIT
fi

BODY_FILE="${WORK_DIR}/body.json"
RESPONSE_FILE="${WORK_DIR}/response.json"
HEADER_FILE="${WORK_DIR}/response.headers"

PROMPT="${PROMPT}" MODEL="${MODEL}" MAX_TOKENS="${MAX_TOKENS}" THINKING_TYPE="${THINKING_TYPE}" EFFORT="${EFFORT}" STREAM="${STREAM}" python3 <<'PY' > "${BODY_FILE}"
import json
import os

stream = os.environ["STREAM"].strip().lower() not in {"", "0", "false", "no", "off"}
payload = {
    "model": os.environ["MODEL"],
    "max_tokens": int(os.environ["MAX_TOKENS"]),
    "thinking": {"type": os.environ["THINKING_TYPE"]},
    "output_config": {"effort": os.environ["EFFORT"]},
    "messages": [
        {"role": "user", "content": os.environ["PROMPT"]},
    ],
}
if stream:
    payload["stream"] = True
print(json.dumps(payload, ensure_ascii=False))
PY
chmod 600 "${BODY_FILE}"

curl_metrics="$(
  curl -sS "${ENDPOINT}" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -H "x-api-key: ${ONEAPI_API_KEY}" \
    -H "Authorization: Bearer ${ONEAPI_API_KEY}" \
    -H "anthropic-version: 2023-06-01" \
    --max-time "${CURL_MAX_TIME}" \
    --data-binary @"${BODY_FILE}" \
    -D "${HEADER_FILE}" \
    -o "${RESPONSE_FILE}" \
    -w '%{http_code}\n%{content_type}\n%{time_starttransfer}\n%{time_total}'
)"
response_status="$(printf '%s\n' "${curl_metrics}" | sed -n '1p')"
response_content_type="$(printf '%s\n' "${curl_metrics}" | sed -n '2p')"
response_first_token_seconds="$(printf '%s\n' "${curl_metrics}" | sed -n '3p')"
response_total_seconds="$(printf '%s\n' "${curl_metrics}" | sed -n '4p')"

if [ -n "${ATTEMPT_DIR}" ]; then
  python3 - "${HEADER_FILE}" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8", errors="replace")
text = re.sub(r"(?im)^(set-cookie|authorization|x-api-key):.*$", r"\1: [REDACTED]", text)
path.write_text(text, encoding="utf-8")
PY
fi

case "${response_status}" in
  2*) ;;
  *)
    printf 'OneAPI HTTP %s\n' "${response_status}" >&2
    cat "${RESPONSE_FILE}" >&2
    exit 1
    ;;
esac

HTTP_STATUS="${response_status}" CONTENT_TYPE="${response_content_type}" FIRST_TOKEN_SECONDS="${response_first_token_seconds}" TOTAL_SECONDS="${response_total_seconds}" ATTEMPT_DIR="${ATTEMPT_DIR}" python3 - "${RESPONSE_FILE}" <<'PY'
import json
import os
import pathlib
import sys

raw = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")

def collect_from_json(obj):
    if isinstance(obj, dict) and "error" in obj:
        print(json.dumps(obj["error"], ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
    texts = []
    for item in (obj.get("content") or []) if isinstance(obj, dict) else []:
        if isinstance(item, dict) and item.get("type") == "text":
            texts.append(item.get("text", ""))
    for choice in (obj.get("choices") or []) if isinstance(obj, dict) else []:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message") or {}
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            texts.append(message["content"])
        delta = choice.get("delta") or {}
        if isinstance(delta, dict) and isinstance(delta.get("content"), str):
            texts.append(delta["content"])
    return texts

texts = []
stop_reasons = []
saw_sse = False
saw_terminal_event = False
event_count = 0
try:
    response = json.loads(raw)
    texts.extend(collect_from_json(response))
    if isinstance(response, dict) and response.get("stop_reason"):
        stop_reasons.append(str(response["stop_reason"]))
        saw_terminal_event = True
except json.JSONDecodeError:
    saw_sse = True
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        event_count += 1
        if isinstance(event, dict) and event.get("type") == "message_stop":
            saw_terminal_event = True
        if isinstance(event, dict) and "error" in event:
            print(json.dumps(event["error"], ensure_ascii=False), file=sys.stderr)
            raise SystemExit(1)
        if isinstance(event, dict):
            event_delta = event.get("delta") or {}
            if isinstance(event_delta, dict) and event_delta.get("stop_reason"):
                stop_reasons.append(str(event_delta["stop_reason"]))
            if event.get("stop_reason"):
                stop_reasons.append(str(event["stop_reason"]))
        delta = event.get("delta") if isinstance(event, dict) else None
        if isinstance(delta, dict):
            if delta.get("type") in {None, "text_delta"} and isinstance(delta.get("text"), str):
                texts.append(delta["text"])
            if isinstance(delta.get("content"), str):
                texts.append(delta["content"])
        content_block = event.get("content_block") if isinstance(event, dict) else None
        if isinstance(content_block, dict) and content_block.get("type") == "text":
            texts.append(content_block.get("text", ""))
        texts.extend(collect_from_json(event) if isinstance(event, dict) else [])

answer = "".join(texts).strip()
attempt_dir = os.environ.get("ATTEMPT_DIR", "")
parser_result = {
    "http_status": os.environ.get("HTTP_STATUS", ""),
    "content_type": os.environ.get("CONTENT_TYPE", ""),
    "first_token_seconds": os.environ.get("FIRST_TOKEN_SECONDS", ""),
    "total_seconds": os.environ.get("TOTAL_SECONDS", ""),
    "event_count": event_count,
    "saw_sse": saw_sse,
    "saw_terminal_event": saw_terminal_event,
    "stop_reasons": stop_reasons,
    "answer_chars": len(answer),
}
if attempt_dir:
    pathlib.Path(attempt_dir, "transport_parser_result.json").write_text(
        json.dumps(parser_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

if "max_tokens" in stop_reasons:
    print("Error: truncated response from OneAPI (stop_reason=max_tokens)", file=sys.stderr)
    print(raw, file=sys.stderr)
    raise SystemExit(1)
elif not saw_terminal_event:
    print("Error: incomplete response from OneAPI (missing terminal event)", file=sys.stderr)
    print(raw, file=sys.stderr)
    raise SystemExit(1)
elif answer:
    print(answer)
else:
    print("Error: empty response from OneAPI", file=sys.stderr)
    print(raw, file=sys.stderr)
    raise SystemExit(1)
PY
