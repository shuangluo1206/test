"""Utilities for the short novel script pipeline."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any


SCENE_TIME_ALIAS_MAP = {
    "日": "日",
    "白": "日",
    "白天": "日",
    "上午": "日",
    "中午": "日",
    "下午": "日",
    "清晨": "日",
    "早上": "日",
    "夜": "夜",
    "夜晚": "夜",
    "晚上": "夜",
    "晚": "夜",
    "深夜": "夜",
    "凌晨": "夜",
    "傍晚": "傍晚",
    "黄昏": "傍晚",
}
LOOSE_SCENE_HEADING_RE = re.compile(
    r"^\s*(?P<episode>\d+)\s*-\s*(?P<scene>\d+)\s+(?P<location>.+)\s+(?P<time>\S+)\s+(?P<space>内|外)\s*$"
)


def normalize_scene_time_token(value: Any) -> str:
    """Handle normalize scene time token."""
    text = str(value or "").strip()
    return SCENE_TIME_ALIAS_MAP.get(text, text)


def _normalize_scene_heading_line(line: str) -> str:
    """Handle normalize scene heading line."""
    match = LOOSE_SCENE_HEADING_RE.match(line)
    if not match:
        return line
    normalized_time = normalize_scene_time_token(match.group("time"))
    if not normalized_time:
        return line
    return (
        f"{int(match.group('episode'))}-{int(match.group('scene'))}"
        f"    {match.group('location').strip()}    {normalized_time}    {match.group('space')}"
    )


def _extract_json_text(text: str) -> str:
    """Handle extract json text."""
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S | re.I)
    if fence:
        return fence.group(1).strip()
    stripped = text.strip()
    object_start = stripped.find("{")
    object_end = stripped.rfind("}")
    array_start = stripped.find("[")
    array_end = stripped.rfind("]")
    if object_start != -1 and object_end > object_start:
        return stripped[object_start : object_end + 1]
    if array_start != -1 and array_end > array_start:
        return stripped[array_start : array_end + 1]
    return stripped


def _sha256_text(text: str) -> str:
    """Handle sha256 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_json_payload_with_report(text: str) -> tuple[Any, dict[str, Any]]:
    """Handle parse json payload with report."""
    operations: list[dict[str, Any]] = []
    content_discarded = False

    def apply_operation(payload: str, operation: str, transform: Any) -> str:
        """Handle apply operation."""
        updated = transform(payload)
        if updated != payload:
            operations.append(
                {
                    "operation": operation,
                    "before_sha256": _sha256_text(payload),
                    "after_sha256": _sha256_text(updated),
                }
            )
        return updated

    payload = apply_operation(text, "extract_json_fence_or_wrapper", _extract_json_text)
    payload = apply_operation(
        payload,
        "normalize_structural_punctuation",
        _normalize_json_structural_punctuation,
    )
    payload = apply_operation(
        payload,
        "remove_trailing_commas",
        lambda value: re.sub(r",\s*([}\]])", r"\1", value),
    )
    payload = apply_operation(
        payload,
        "remove_extra_event_close_before_child_beats",
        lambda value: re.sub(
            r'(\}\s*)\}\s*,\s*("(?:子情节点|child_beats)"\s*:)',
            r"\1, \2",
            value,
        ),
    )
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        repaired = apply_operation(
            payload,
            "close_chapter_summaries_before_key_events",
            _close_chapter_summaries_before_key_events,
        )
        try:
            parsed = json.loads(repaired)
        except json.JSONDecodeError:
            repaired = apply_operation(
                repaired,
                "escape_unescaped_string_quotes",
                _escape_unescaped_string_quotes,
            )
            try:
                parsed = json.loads(repaired)
            except json.JSONDecodeError as exc:
                repaired = apply_operation(
                    repaired,
                    "remove_extra_object_close_between_fields",
                    lambda value: _remove_extra_object_close_between_fields(value, error_pos=exc.pos),
                )
                try:
                    parsed = json.loads(repaired)
                except json.JSONDecodeError as exc:
                    candidate = _remove_extra_object_close_before_array_field(repaired, error_pos=exc.pos)
                    if candidate != repaired:
                        candidate_operation = {
                            "operation": "remove_extra_object_close_before_array_field",
                            "before_sha256": _sha256_text(repaired),
                            "after_sha256": _sha256_text(candidate),
                        }
                    else:
                        candidate_operation = None
                    try:
                        parsed = json.loads(candidate)
                        if candidate_operation:
                            operations.append(candidate_operation)
                        repaired = candidate
                    except json.JSONDecodeError:
                        repaired = apply_operation(
                            repaired,
                            "close_chapter_summaries_before_key_events",
                            _close_chapter_summaries_before_key_events,
                        )
                        try:
                            parsed = json.loads(repaired)
                        except json.JSONDecodeError:
                            before_drop = repaired
                            repaired = apply_operation(
                                repaired,
                                "drop_truncated_mapping_trace_tail",
                                _drop_truncated_mapping_trace_tail,
                            )
                            content_discarded = repaired != before_drop
                            parsed = json.loads(repaired)
        payload = repaired

    report = {
        "status": "WARN" if operations else "PASS",
        "before_sha256": _sha256_text(text),
        "after_sha256": _sha256_text(payload),
        "operation_count": len(operations),
        "operations": operations,
        "content_discarded": content_discarded,
    }
    return parsed, report


def parse_json_payload(text: str) -> Any:
    """Handle parse json payload."""
    parsed, _ = parse_json_payload_with_report(text)
    return parsed


def _normalize_json_structural_punctuation(text: str) -> str:
    """Handle normalize json structural punctuation."""
    result: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if char == "\\" and in_string:
            result.append(char)
            escaped = not escaped
            continue
        if char == '"' and not escaped:
            in_string = not in_string
            result.append(char)
            continue
        escaped = False
        if not in_string and char == "，":
            result.append(",")
        elif not in_string and char == "：":
            result.append(":")
        else:
            result.append(char)
    return "".join(result)


def _replace_match_near_error(
    text: str,
    pattern: str,
    replacement: str,
    *,
    error_pos: int | None,
) -> str:
    """Handle replace match near error."""
    for match in re.finditer(pattern, text):
        if error_pos is not None and not (match.start() <= error_pos <= match.end()):
            continue
        return text[: match.start()] + match.expand(replacement) + text[match.end() :]
    return text


def _remove_extra_object_close_between_fields(text: str, *, error_pos: int | None = None) -> str:
    """Handle remove extra object close between fields."""
    repaired = _replace_match_near_error(
        text,
        r'("\s*)\n\s*}\s*,\s*\n\s*("[^"]+"\s*:)',
        r"\1,\n  \2",
        error_pos=error_pos,
    )
    if repaired != text:
        return repaired
    return _replace_match_near_error(
        text,
        r'(\}\s*)\}\s*,\s*("[^"]+"\s*:)',
        r"\1, \2",
        error_pos=error_pos,
    )


def _remove_extra_object_close_before_array_field(text: str, *, error_pos: int | None = None) -> str:
    """Handle remove extra object close before array field."""
    return _replace_match_near_error(
        text,
        r'(\}\s*)\}\s*(\]\s*,\s*"[^"]+"\s*:)',
        r"\1\2",
        error_pos=error_pos,
    )


def _close_chapter_summaries_before_key_events(text: str) -> str:
    """Handle close chapter summaries before key events."""
    for chapter_key, event_key in (
        ("chapter_summaries", "key_events"),
        ("章节梗概", "关键事件"),
    ):
        if f'"{chapter_key}"' not in text or f'"{event_key}"' not in text:
            continue
        repaired = re.sub(
            rf'(\n\s*}}\s*),\s*\n(\s*"{re.escape(event_key)}"\s*:)',
            r"\1\n  ],\n\2",
            text,
            count=1,
        )
        return re.sub(r"(\]\s*)\n\s*\]\s*(\n\s*}\s*)\Z", r"\1\2", repaired)
    return text


def _drop_truncated_mapping_trace_tail(text: str) -> str:
    """Handle drop truncated mapping trace tail."""
    for field_name in ("mapping_trace", "映射链路"):
        if f'"{field_name}"' not in text:
            continue
        if re.search(rf'"{re.escape(field_name)}"\s*:\s*\[.*\]\s*}}\s*$', text, flags=re.S):
            return text
        match = re.search(rf',?\s*"{re.escape(field_name)}"\s*:\s*\[', text)
        if not match:
            return text
        prefix = re.sub(r",\s*$", "", text[: match.start()].rstrip())
        return f'{prefix},\n  "{field_name}": []\n}}'
    return text


def _escape_unescaped_string_quotes(text: str) -> str:
    """Handle escape unescaped string quotes."""
    result: list[str] = []
    in_string = False
    escaped = False
    length = len(text)
    for idx, char in enumerate(text):
        if char == "\\" and in_string:
            result.append(char)
            escaped = not escaped
            continue
        if in_string and char == "\n":
            result.append("\\n")
            escaped = False
            continue
        if in_string and char == "\r":
            result.append("\\r")
            escaped = False
            continue
        if in_string and char == "\t":
            result.append("\\t")
            escaped = False
            continue
        if char == '"' and not escaped:
            if not in_string:
                in_string = True
                result.append(char)
            else:
                next_non_space = ""
                for lookahead in range(idx + 1, length):
                    if not text[lookahead].isspace():
                        next_non_space = text[lookahead]
                        break
                if next_non_space in {":", ",", "}", "]", ""}:
                    in_string = False
                    result.append(char)
                else:
                    result.append('\\"')
            escaped = False
            continue
        result.append(char)
        escaped = False
    return "".join(result)


def clean_final_script(text: str) -> str:
    """Handle clean final script."""
    value = str(text).strip()
    markers = ["# 第", "第1集", "第1场", "第一场", "【第"]
    starts = [idx for marker in markers if (idx := value.find(marker)) >= 0]
    if starts:
        value = value[min(starts) :].strip()
    cleaned_lines: list[str] = []
    blocked_prefixes = ("模型理解", "创作说明", "以下是剧本", "下面是剧本", "分析：", "说明：")
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append(line)
            continue
        if any(stripped.startswith(prefix) for prefix in blocked_prefixes):
            continue
        cleaned_lines.append(_normalize_scene_heading_line(line))
    return "\n".join(cleaned_lines).strip()
