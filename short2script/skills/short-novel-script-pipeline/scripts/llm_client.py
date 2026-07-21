"""Utilities for the short novel script pipeline."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_BAIDU_ONEAPI_ENV_FILE = "/Users/cjlbd/Desktop/Code/.env-baidu-oneapi-data-0708"
FALLBACK_LLM_SCRIPT = SCRIPT_DIR / "run_baidu_oneapi_claude_opus_4_6.sh"
TRANSIENT_ERROR_MARKERS = (
    "HTTP 429",
    "HTTP 500",
    "HTTP 502",
    "HTTP 503",
    "HTTP 504",
    "Bad Gateway",
    "timed out",
    "JSONDecodeError",
    "Expecting value",
    "empty response",
    "truncated response",
    "incomplete response",
    "non-JSON response",
    "curl: (18)",
    "transfer closed with outstanding read data remaining",
)
BD_DATA_KEY_NAMES = {
    "bddataapikey",
    "bddatallmapikey",
    "bddataapi",
    "apikey",
    "token",
}
BD_DATA_DEFAULT_MAX_TOKENS = "16384"
BD_DATA_STAGE_MAX_TOKENS = {
    "07_episode_planning": "65536",
}
DODO_DEFAULT_MAX_TOKENS = "24000"
DODO_STAGE_MAX_TOKENS = {
    "03_plot_character_extract": "64000",
    "04_adaptation_direction": "64000",
    "05_plot_character_adaptation": "64000",
    "06_script_outline_design": "64000",
    "07_episode_planning": "64000",
    "08_script_body_generation": "16000",
}
BAIDU_ONEAPI_DISABLED_THINKING_STAGES = {
    "02_storyline_understanding",
    "04_adaptation_direction",
    "04a_flashback_screening",
    "04b_dramatic_release_map",
    "05_plot_character_adaptation",
    "06_script_outline_design",
    "07_episode_planning",
    "08_script_body_generation",
}


@dataclass
class LLMResult:
    """Group l l m result behavior."""
    raw: str
    clean: str
    returncode: int
    elapsed_seconds: float
    stderr: str
    attempt_dirs: tuple[str, ...] = ()


def resolve_llm_script(explicit: str | Path | None = None) -> Path:
    """Handle resolve llm script."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("LLM_SCRIPT"):
        candidates.append(Path(os.environ["LLM_SCRIPT"]))
    candidates.append(FALLBACK_LLM_SCRIPT)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    rendered = ", ".join(str(item) for item in candidates)
    raise FileNotFoundError(f"No LLM script found. Checked: {rendered}")


def clean_llm_output(raw: str) -> str:
    """Handle clean llm output."""
    text = raw.strip()
    if "[answer]" in text:
        text = text.split("[answer]", 1)[1].strip()
    text = re.sub(r"\n---\nmodel:.*\Z", "", text, flags=re.S).strip()
    if "</thinking>" in text:
        after_thinking = text.rsplit("</thinking>", 1)[1].strip()
        if after_thinking:
            text = after_thinking
    if text.startswith("<thinking>") or text.startswith("[thinking]"):
        fence = re.search(r"```(?:json)?\s*(?:\{|\[)", text, flags=re.I)
        if fence:
            text = text[fence.start() :].strip()
        else:
            root = re.search(r"(?m)^[ \t]*(?:\{|\[)", text)
            if root:
                text = text[root.start() :].strip()
    return text


def decode_process_text(value: str | bytes | None) -> str:
    """Handle decode process text."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def is_transient_error(message: str) -> bool:
    """Handle is transient error."""
    return any(marker in message for marker in TRANSIENT_ERROR_MARKERS)


def is_bd_data_script(llm_script: Path) -> bool:
    """Handle is bd data script."""
    return llm_script.name == "bd-data-chat.sh"


def is_dodo_pipeline_script(llm_script: Path) -> bool:
    """Handle is dodo pipeline script."""
    return llm_script.name in {"dodo_sonnet46_pipeline.sh", "rd_dodo_api_template.sh"}


def is_baidu_oneapi_opus_script(llm_script: Path) -> bool:
    """Handle is baidu oneapi opus script."""
    return llm_script.name == "run_baidu_oneapi_claude_opus_4_6.sh"


def build_llm_command(llm_script: Path, prompt: str) -> list[str]:
    """Handle build llm command."""
    if is_bd_data_script(llm_script):
        return ["bash", str(llm_script), "gemini"]
    if is_dodo_pipeline_script(llm_script) or is_baidu_oneapi_opus_script(llm_script):
        return ["bash", str(llm_script)]
    return ["bash", str(llm_script), prompt]


def build_llm_stdin(llm_script: Path, prompt: str) -> bytes | None:
    """Handle build llm stdin."""
    if is_bd_data_script(llm_script) or is_dodo_pipeline_script(llm_script) or is_baidu_oneapi_opus_script(llm_script):
        return prompt.encode("utf-8")
    return None


def llm_runtime_options(llm_script: Path | None, *, stage_id: str | None = None) -> dict[str, str]:
    """Handle llm runtime options."""
    if llm_script is not None and is_baidu_oneapi_opus_script(llm_script):
        default_thinking_type = "disabled" if stage_id in BAIDU_ONEAPI_DISABLED_THINKING_STAGES else "adaptive"
        return {
            "preset": "baidu-oneapi-claude-opus-4.6",
            "transport": "shell_stdin",
            "model": os.environ.get("BAIDU_ONEAPI_MODEL", "Claude Opus 4.6"),
            "max_tokens": os.environ.get("BAIDU_ONEAPI_MAX_TOKENS", "128000"),
            "thinking.type": os.environ.get("BAIDU_ONEAPI_THINKING_TYPE", default_thinking_type),
            "output_config.effort": os.environ.get("BAIDU_ONEAPI_EFFORT", "high"),
            "stream": os.environ.get("BAIDU_ONEAPI_STREAM", "1"),
            "env_file": os.environ.get("BAIDU_ONEAPI_ENV_FILE", DEFAULT_BAIDU_ONEAPI_ENV_FILE),
        }
    if llm_script is not None and is_dodo_pipeline_script(llm_script):
        default_max_tokens = DODO_STAGE_MAX_TOKENS.get(
            stage_id or "",
            os.environ.get("DODO_MAX_TOKENS", DODO_DEFAULT_MAX_TOKENS),
        )
        return {
            "preset": "dodo-sonnet-4.6",
            "transport": "shell_stdin",
            "EFFORT_LEVELS": os.environ.get("DODO_EFFORT_LEVELS", os.environ.get("EFFORT_LEVELS", "high")),
            "MAX_TOKENS": os.environ.get("DODO_MAX_TOKENS", default_max_tokens),
            "DODO_MAX_TOKENS": os.environ.get("DODO_MAX_TOKENS", default_max_tokens),
            "DODO_EFFORT": os.environ.get("DODO_EFFORT", "high"),
            "DODO_ENABLE_THINKING": os.environ.get("DODO_ENABLE_THINKING", "0"),
            "DODO_THINKING_DISPLAY": os.environ.get("DODO_THINKING_DISPLAY", "hidden"),
        }
    if llm_script is None or not is_bd_data_script(llm_script):
        return {}
    default_max_tokens = BD_DATA_STAGE_MAX_TOKENS.get(
        stage_id or "",
        os.environ.get("BD_DATA_MAX_TOKENS", BD_DATA_DEFAULT_MAX_TOKENS),
    )
    stage_env_key = ""
    if stage_id:
        stage_env_key = "BD_DATA_MAX_TOKENS_" + re.sub(r"[^A-Za-z0-9]+", "_", stage_id).upper()
    return {
        "preset": "gemini",
        "transport": "direct_http",
        "BD_DATA_MODEL": os.environ.get("BD_DATA_MODEL", "gemini-3.1-pro-preview"),
        "BD_DATA_MAX_TOKENS": (
                os.environ.get(stage_env_key, default_max_tokens) if stage_env_key else default_max_tokens
            ),
        "BD_DATA_REASONING_EFFORT": os.environ.get("BD_DATA_REASONING_EFFORT", "high"),
    }


def build_llm_env(llm_script: Path, *, stage_id: str | None = None) -> dict[str, str]:
    """Handle build llm env."""
    env = os.environ.copy()
    options = llm_runtime_options(llm_script, stage_id=stage_id)
    for key, value in options.items():
        if key not in {"preset", "transport"}:
            env.setdefault(key, value)
    if is_baidu_oneapi_opus_script(llm_script):
        env.setdefault("BAIDU_ONEAPI_MODEL", options["model"])
        env.setdefault("BAIDU_ONEAPI_MAX_TOKENS", options["max_tokens"])
        env.setdefault("BAIDU_ONEAPI_THINKING_TYPE", options["thinking.type"])
        env.setdefault("BAIDU_ONEAPI_EFFORT", options["output_config.effort"])
        env.setdefault("BAIDU_ONEAPI_STREAM", options["stream"])
        env.setdefault("BAIDU_ONEAPI_ENV_FILE", options["env_file"])
    return env


def clean_env_value(value: str) -> str:
    """Handle clean env value."""
    text = value.strip()
    if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')):
        text = text[1:-1]
    if text.lower().startswith("bearer "):
        text = text.split(None, 1)[1]
    return text.strip()


def read_bd_data_key_from_file(env_file: Path) -> str:
    """Handle read bd data key from file."""
    if not env_file.exists():
        return ""
    fallback = ""
    for raw in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        normalized = "".join(ch for ch in name.lower() if ch.isalnum())
        cleaned = clean_env_value(value)
        if normalized in BD_DATA_KEY_NAMES and cleaned:
            return cleaned
        if not fallback and cleaned.startswith("sk-"):
            fallback = cleaned
    return fallback


def resolve_bd_data_api_key(llm_script: Path) -> str:
    """Handle resolve bd data api key."""
    api_key = os.environ.get("BD_DATA_API_KEY") or os.environ.get("BD_DATA_LLM_API_KEY") or ""
    if api_key:
        return api_key
    api_key = read_bd_data_key_from_file(llm_script.parent / ".env")
    if api_key:
        return api_key
    env_file = os.environ.get("BD_DATA_ENV_FILE", "")
    return read_bd_data_key_from_file(Path(env_file)) if env_file else ""


def endpoint_from_base(base: str) -> str:
    """Handle endpoint from base."""
    clean = base.rstrip("/")
    if clean.endswith("/chat/completions"):
        return clean
    return f"{clean}/chat/completions"


def resolve_bd_data_endpoint() -> str:
    """Handle resolve bd data endpoint."""
    endpoint = os.environ.get("BD_DATA_ENDPOINT")
    if endpoint:
        return endpoint.rstrip("/")
    return endpoint_from_base(os.environ.get("BD_DATA_BASE_URL", "http://yy.dbh.baidu-int.com/v1"))


def build_bd_data_payload(prompt: str, llm_script: Path, *, stage_id: str | None = None) -> dict[str, object]:
    """Handle build bd data payload."""
    options = llm_runtime_options(llm_script, stage_id=stage_id)
    payload: dict[str, object] = {
        "model": options["BD_DATA_MODEL"],
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": int(options["BD_DATA_MAX_TOKENS"]),
    }
    reasoning_effort = options.get("BD_DATA_REASONING_EFFORT", "")
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    max_completion_tokens = os.environ.get("BD_DATA_MAX_COMPLETION_TOKENS")
    if max_completion_tokens:
        payload["max_completion_tokens"] = int(max_completion_tokens)
    return payload


def extract_bd_data_text(data: dict[str, object]) -> tuple[str, str]:
    """Handle extract bd data text."""
    texts: list[str] = []
    reasoning: list[str] = []
    for choice in data.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message") or {}
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str) and content:
            texts.append(content)
        reasoning_content = message.get("reasoning_content")
        if isinstance(reasoning_content, str) and reasoning_content:
            reasoning.append(reasoning_content)
    if not texts:
        finish_reasons = [
            str(choice.get("finish_reason", ""))
            for choice in data.get("choices") or []
            if isinstance(choice, dict)
        ]
        if any(reason == "length" for reason in finish_reasons):
            usage = data.get("usage", {})
            raise RuntimeError(
                "BD-DATA API returned empty content with finish_reason=length; "
                f"usage={json.dumps(usage, ensure_ascii=False)}"
            )
    stdout = "\n".join(texts) if texts else json.dumps(data, ensure_ascii=False, indent=2)
    stderr = ""
    if reasoning:
        stderr = "[reasoning_content]\n" + "\n".join(reasoning)
    return stdout, stderr


def call_bd_data_api(prompt: str, *, llm_script: Path, timeout: int, stage_id: str | None = None) -> tuple[str, str]:
    """Handle call bd data api."""
    api_key = resolve_bd_data_api_key(llm_script)
    if not api_key:
        raise RuntimeError("缺少 BD-DATA API Key。请设置 BD_DATA_API_KEY，或确认 bd-data env 文件存在。")
    endpoint = resolve_bd_data_endpoint()
    payload = build_bd_data_payload(prompt, llm_script, stage_id=stage_id)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        raw = exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"BD-DATA API request failed: {exc.reason}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Error: non-JSON response, HTTP {status}\n{raw}") from exc
    if not 200 <= status < 300 or data.get("error"):
        raise RuntimeError(f"Error: BD-DATA API HTTP {status}\n{json.dumps(data, ensure_ascii=False, indent=2)}")
    return extract_bd_data_text(data)


def call_bd_data_llm(
    prompt: str,
    *,
    llm_script: Path,
    timeout: int,
    retries: int,
    stage_id: str | None = None,
) -> LLMResult:
    """Handle call bd data llm."""
    started = time.time()
    attempts = retries + 1
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            stdout, stderr = call_bd_data_api(prompt, llm_script=llm_script, timeout=timeout, stage_id=stage_id)
            clean = clean_llm_output(stdout)
            if clean and not clean.startswith("Error:"):
                elapsed = round(time.time() - started, 2)
                if attempt > 1:
                    stderr = f"retried_attempts={attempt - 1}\n{stderr}".strip()
                return LLMResult(raw=stdout, clean=clean, returncode=0, elapsed_seconds=elapsed, stderr=stderr)
            last_error = clean or "BD-DATA API returned empty content"
        except RuntimeError as exc:
            last_error = str(exc)
        if attempt >= attempts or not is_transient_error(last_error):
            break
        time.sleep(min(30, 5 * attempt))
    raise RuntimeError(last_error)


def call_llm(
    prompt: str,
    *,
    llm_script: Path,
    cwd: Path,
    timeout: int = 1800,
    retries: int = 2,
    stage_id: str | None = None,
    attempts_dir: Path | None = None,
) -> LLMResult:
    """Handle call llm."""
    if is_bd_data_script(llm_script):
        return call_bd_data_llm(prompt, llm_script=llm_script, timeout=timeout, retries=retries, stage_id=stage_id)

    started = time.time()
    attempts = retries + 1
    last_error = ""
    attempt_dirs: list[str] = []
    for attempt in range(1, attempts + 1):
        attempt_dir = attempts_dir / f"llm_attempt_{attempt:02d}" if attempts_dir else None
        env = build_llm_env(llm_script, stage_id=stage_id)
        if attempt_dir is not None:
            attempt_dir.mkdir(parents=True, exist_ok=False)
            env["LLM_ATTEMPT_DIR"] = str(attempt_dir)
            attempt_dirs.append(str(attempt_dir))
        proc = subprocess.run(
            build_llm_command(llm_script, prompt),
            cwd=str(cwd),
            capture_output=True,
            input=build_llm_stdin(llm_script, prompt),
            text=False,
            timeout=timeout,
            env=env,
        )
        stdout = decode_process_text(proc.stdout)
        stderr = decode_process_text(proc.stderr)
        if attempt_dir is not None:
            (attempt_dir / "client_stdout.txt").write_text(stdout, encoding="utf-8")
            (attempt_dir / "client_stderr.txt").write_text(stderr, encoding="utf-8")
            (attempt_dir / "client_result.json").write_text(
                json.dumps(
                    {
                        "attempt": attempt,
                        "returncode": proc.returncode,
                        "stage_id": stage_id,
                        "stdout_chars": len(stdout),
                        "stderr_chars": len(stderr),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        clean = clean_llm_output(stdout)
        if proc.returncode == 0 and not clean.startswith("Error:"):
            elapsed = round(time.time() - started, 2)
            if attempt > 1:
                stderr = f"retried_attempts={attempt - 1}\n{stderr}".strip()
            return LLMResult(
                raw=stdout,
                clean=clean,
                returncode=proc.returncode,
                elapsed_seconds=elapsed,
                stderr=stderr,
                attempt_dirs=tuple(attempt_dirs),
            )
        last_error = (
            (
                (
                    clean
                    if clean.startswith("Error:")
                    else f"LLM call failed with returncode={proc.returncode}: {stderr.strip()}"
                )
            )
        )
        if attempt >= attempts or not is_transient_error(last_error):
            break
        time.sleep(min(30, 5 * attempt))
    raise RuntimeError(last_error)
