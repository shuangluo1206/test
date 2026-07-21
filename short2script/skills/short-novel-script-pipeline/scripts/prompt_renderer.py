"""Utilities for the short novel script pipeline."""
from __future__ import annotations

import json
import re
from typing import Any

import llm_schema_localization


PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*|[\u4e00-\u9fff][\u4e00-\u9fffa-zA-Z0-9_]*)\}")


def stringify(value: Any) -> str:
    """Handle stringify."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def stringify_for_prompt(root_key: str, value: Any) -> str:
    """Handle stringify for prompt."""
    return stringify(llm_schema_localization.localize_prompt_value(root_key, value))


def render_template(template: str, values: dict[str, Any]) -> str:
    """Handle render template."""
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        """Handle replace."""
        placeholder = match.group(1)
        key = llm_schema_localization.canonical_placeholder_name(placeholder)
        if key not in values:
            missing.append(placeholder)
            return match.group(0)
        return stringify_for_prompt(key, values[key])

    rendered = PLACEHOLDER_RE.sub(replace, template)
    if missing:
        raise ValueError(f"missing prompt value(s): {', '.join(sorted(set(missing)))}")
    return rendered
