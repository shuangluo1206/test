#!/bin/bash
set -euo pipefail

TOKEN="${LLM_API_KEY:-${LLM_TOKEN:-}}"
MODEL="${LLM_MODEL:-Claude Sonnet 4.6}"
MAX_TOKENS="${LLM_MAX_TOKENS:-${MAX_TOKENS:-24000}}"
CURL_MAX_TIME="${CURL_MAX_TIME:-2400}"
EFFORT_LEVELS="${LLM_EFFORT_LEVELS:-${EFFORT_LEVELS:-${LLM_EFFORT:-high}}}"
LLM_ENABLE_THINKING="${LLM_ENABLE_THINKING:-0}"
LLM_THINKING_DISPLAY="${LLM_THINKING_DISPLAY:-hidden}"
ENDPOINT="${LLM_ENDPOINT:-https://api.example.com/v1/messages}"

if [ -n "${1:-}" ]; then
  PROMPT="$*"
else
  PROMPT="$(cat)"
fi

if [ -z "${TOKEN}" ]; then
  echo "Error: set LLM_API_KEY or LLM_TOKEN before running the LLM pipeline script." >&2
  exit 1
fi

if [ -z "${PROMPT}" ]; then
  echo "Error: empty prompt." >&2
  exit 1
fi

WORK_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

make_body() {
  local effort="$1"
  python3 - "${MODEL}" "${MAX_TOKENS}" "${effort}" "${LLM_ENABLE_THINKING}" "${LLM_THINKING_DISPLAY}" "${PROMPT}" <<'PY'
import json
import sys

model = sys.argv[1]
max_tokens = int(sys.argv[2])
effort = sys.argv[3]
enable_thinking = sys.argv[4].strip().lower()
display = sys.argv[5]
prompt = sys.argv[6]

payload = {
    "model": model,
    "max_tokens": max_tokens,
    "output_config": {
        "effort": effort,
    },
    "messages": [
        {
            "role": "user",
            "content": prompt,
        }
    ],
}
if enable_thinking not in {"", "0", "false", "no", "off"}:
    payload["thinking"] = {
        "type": "adaptive",
        "display": display,
    }

print(json.dumps(payload, ensure_ascii=False))
PY
}

write_curl_config() {
  local config_file="$1"
  local body_file="$2"
  python3 - "${config_file}" "${ENDPOINT}" "${TOKEN}" "${CURL_MAX_TIME}" "${body_file}" <<'PY'
import json
import pathlib
import sys

config_file, endpoint, token, curl_max_time, body_file = sys.argv[1:6]
int(curl_max_time)

def q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)

lines = [
    f"url = {q(endpoint)}",
    "request = \"POST\"",
    f"header = {q('Content-Type: application/json')}",
    f"header = {q('Authorization: Bearer ' + token)}",
    f"header = {q('anthropic-version: 2023-06-01')}",
    f"max-time = {curl_max_time}",
    f"data-binary = @{body_file}",
]
pathlib.Path(config_file).write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

parse_response() {
  local response_file="$1"
  python3 - "${response_file}" <<'PY'
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if "error" in data:
    err = data["error"]
    message = err.get("message", err) if isinstance(err, dict) else err
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)

thinking_blocks = []
text_blocks = []

def add_text(value, target):
    if isinstance(value, str) and value:
        target.append(value)

content = data.get("content")
if isinstance(content, list):
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "thinking":
            add_text(item.get("thinking") or item.get("text"), thinking_blocks)
        elif item.get("type") == "text":
            add_text(item.get("text"), text_blocks)
elif isinstance(content, str):
    add_text(content, text_blocks)

for choice in data.get("choices") or []:
    if not isinstance(choice, dict):
        continue
    message = choice.get("message") or {}
    if isinstance(message, dict):
        add_text(message.get("reasoning_content"), thinking_blocks)
        add_text(message.get("content"), text_blocks)

if thinking_blocks:
    print("[thinking]")
    print("\n".join(thinking_blocks))
    print("\n[answer]")

answer = "\n".join(text_blocks).strip()
if answer:
    print(answer)
else:
    print(json.dumps(data, ensure_ascii=False, indent=2))

usage = data.get("usage") or {}
input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", "?"))
output_tokens = usage.get("output_tokens", usage.get("completion_tokens", "?"))
model_name = data.get("model", "?")
stop_reason = data.get("stop_reason", "?")
print(f"\n---\nmodel: {model_name} | stop: {stop_reason} | {input_tokens}in/{output_tokens}out")
PY
}

is_fallback_error() {
  local response_file="$1"
  python3 - "${response_file}" <<'PY'
import json
import pathlib
import sys

try:
    data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)

err = data.get("error") if isinstance(data, dict) else None
if not err:
    raise SystemExit(1)

if isinstance(err, dict):
    message = str(err.get("message", ""))
else:
    message = str(err)

needles = (
    "effort",
    "thinking",
    "output_config",
    "adaptive",
    "unsupported",
    "invalid",
)
raise SystemExit(0 if any(item in message.lower() for item in needles) else 1)
PY
}

last_response="${WORK_DIR}/last-response.json"
last_effort=""
for effort in ${EFFORT_LEVELS}; do
  last_effort="${effort}"
  body_file="${WORK_DIR}/body-${effort}.json"
  config_file="${WORK_DIR}/curl-${effort}.conf"
  response_file="${WORK_DIR}/response-${effort}.json"

  make_body "${effort}" > "${body_file}"
  chmod 600 "${body_file}"
  write_curl_config "${config_file}" "${body_file}"
  chmod 600 "${config_file}"

  if curl -sS -K "${config_file}" > "${response_file}"; then
    cp "${response_file}" "${last_response}"
    if parse_response "${response_file}"; then
      if [ "${effort}" != "high" ]; then
        echo "Note: effort fallback used: ${effort}" >&2
      fi
      exit 0
    fi
    if ! is_fallback_error "${response_file}"; then
      exit 1
    fi
    echo "Warning: effort=${effort} failed, trying next thinking effort." >&2
  else
    echo "Error: request failed at effort=${effort}." >&2
    exit 1
  fi
done

echo "Error: all effort levels failed. Last effort: ${last_effort}" >&2
cat "${last_response}" >&2
exit 1
