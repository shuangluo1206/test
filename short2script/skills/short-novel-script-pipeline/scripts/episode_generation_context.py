"""Utilities for the short novel script pipeline."""
from __future__ import annotations

import json
from typing import Any

import continuity_ledger
import dramatic_release


FUTURE_RESERVATION_MAX_CHARS = 1000
RECENT_FULL_SCRIPT_COUNT = 3


def compact_episode_execution_sheet(
    episode: dict[str, Any],
    *,
    transaction_contract: dict[str, Any] | None = None,
    dramatic_target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Handle compact episode execution sheet."""
    scene_plan: list[dict[str, Any]] = []
    for item in episode.get("scene_plan", []) or []:
        if not isinstance(item, dict):
            continue
        scene_plan.append(
            {
                key: item.get(key)
                for key in (
                    "scene_no",
                    "location",
                    "time",
                    "space",
                    "appearing_character_names",
                    "scene_purpose",
                    "scene_boundary_reason",
                    "visible_space_tokens",
                )
                if key in item
            }
        )

    density = episode.get("target_script_density", {})
    compact_density = {}
    if isinstance(density, dict):
        compact_density = {
            key: density.get(key)
            for key in (
                "target_range_chars",
                "minimum_effective_chars",
                "maximum_chars",
                "must_cover_beats",
                "optional_compression_beats",
                "scene_char_budgets",
            )
            if key in density
        }

    compact_transaction_contract: dict[str, Any] = {}
    if isinstance(transaction_contract, dict):
        episode_num = int(transaction_contract.get("episode_num", episode.get("episode_num", 0)) or 0)
        compact_transaction_contract = {
            "assigned_event_id": transaction_contract.get("assigned_event_id"),
            "authorized_transaction_ids": transaction_contract.get("authorized_transaction_ids", []),
            "authorized_transactions": transaction_contract.get("authorized_transactions", []),
            "forbidden_future_transactions": [
                {
                    "transaction_id": item.get("transaction_id"),
                    "owner_event_id": item.get("owner_event_id"),
                    "owner_episode": item.get("owner_episode"),
                    "effect_ids": [
                        effect.get("effect_id")
                        for effect in item.get("effects", []) or []
                        if isinstance(effect, dict) and effect.get("effect_id")
                    ],
                }
                for item in transaction_contract.get("forbidden_future_transactions", []) or []
                if isinstance(item, dict)
                and int(item.get("owner_episode", 0) or 0) <= episode_num + 5
            ],
        }

    return {
        key: value
        for key, value in {
            "episode_num": episode.get("episode_num"),
            "title": episode.get("title", ""),
            "opening_beat": episode.get("opening_beat", ""),
            "closing_beat": episode.get("closing_beat", ""),
            "next_episode_start_state": episode.get("next_episode_start_state", ""),
            "event_ids": episode.get("event_ids", []),
            "consumed_child_beat_ids": episode.get("consumed_child_beat_ids", []),
            "required_character_names": episode.get("required_character_names", []),
            "scene_plan": scene_plan,
            "narration_device_plan": episode.get("narration_device_plan", {}),
            "target_script_density": compact_density,
            "prop_continuity_plan": episode.get("prop_continuity_plan", []),
            "source_fact_ids": episode.get("source_fact_ids", []),
            "story_time": episode.get("story_time", {}),
            "dramatic_target_id": episode.get("dramatic_target_id", ""),
            "dramatic_target": dramatic_target or {},
            "transaction_contract": compact_transaction_contract,
        }.items()
        if value not in (None, "", [], {})
        or key in {"event_ids", "consumed_child_beat_ids", "prop_continuity_plan"}
    }


def _future_reservations(episode_outlines: list[dict[str, Any]], episode_index: int) -> list[dict[str, Any]]:
    """Handle future reservations."""
    reservations: list[dict[str, Any]] = []
    for item in episode_outlines[episode_index + 1 : episode_index + 6]:
        reservations.append(
            {
                "episode_num": item.get("episode_num"),
                "event_ids": item.get("event_ids", []),
                "ending_hook": item.get("ending_hook", ""),
                "reserved_fact_ids": item.get("source_fact_ids", []),
            }
        )
    while reservations and len(json.dumps(reservations, ensure_ascii=False)) > FUTURE_RESERVATION_MAX_CHARS:
        last = reservations[-1]
        last["ending_hook"] = str(last.get("ending_hook", ""))[:80]
        if len(json.dumps(reservations, ensure_ascii=False)) <= FUTURE_RESERVATION_MAX_CHARS:
            break
        reservations.pop()
    return reservations


def _relevant_source_facts(
    episode: dict[str, Any],
    *,
    source_fact_ledger: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Handle relevant source facts."""
    wanted = {str(item) for item in episode.get("source_fact_ids", []) or []}
    if not wanted:
        wanted = {str(item) for item in episode.get("adapted_plot_point_ids", []) or []}
    return [item for item in source_fact_ledger if str(item.get("fact_id")) in wanted]


def _compact_source_voice_anchors(items: list[Any] | None) -> list[Any]:
    """Handle compact source voice anchors."""
    output: list[Any] = []
    for item in (items or [])[:6]:
        if isinstance(item, dict):
            output.append(
                {
                    str(key): (str(value)[:140] if isinstance(value, str) else value)
                    for key, value in item.items()
                    if key in {"step", "source_fact", "emotion", "downstream_lock", "detail", "quote"}
                }
            )
        else:
            output.append(str(item)[:140])
    return output


def build_episode_generation_views(
    *,
    episode: dict[str, Any],
    episode_index: int,
    episode_outlines: list[dict[str, Any]],
    ledger: dict[str, Any],
    source_fact_ledger: list[dict[str, Any]] | None = None,
    flashback_screening: dict[str, Any] | None = None,
    protagonist_action_boundary: dict[str, Any] | None = None,
    target_tone: str = "",
    transaction_contract: dict[str, Any] | None = None,
    dramatic_release_map: dict[str, Any] | None = None,
    source_voice_anchors: list[Any] | None = None,
) -> dict[str, Any]:
    """Handle build episode generation views."""
    generated = ledger.get("generated_episodes", [])
    recent_scripts = [
        {
            "episode_num": item.get("episode_num"),
            "title": item.get("title", ""),
            "final_script": item.get("final_script", ""),
        }
        for item in generated[-RECENT_FULL_SCRIPT_COUNT:]
        if isinstance(item, dict)
    ]
    narration_plan = episode.get("narration_device_plan", {})
    approved_ids = {
        str(item)
        for item in (narration_plan.get("approved_flashback_time_deviation_ids", []) or [])
    }
    retained = []
    for item in (flashback_screening or {}).get("retained_time_deviations", []) or []:
        if str(item.get("id")) in approved_ids:
            retained.append(item)
    return {
        "episode_execution_sheet": compact_episode_execution_sheet(
            episode,
            transaction_contract=transaction_contract,
            dramatic_target=dramatic_release.target_by_episode(
                dramatic_release_map
            ).get(int(episode.get("episode_num", 0)), {}),
        ),
        "recent_episode_scripts": recent_scripts,
        "active_continuity_view": continuity_ledger.active_view(ledger),
        "future_event_reservations": _future_reservations(episode_outlines, episode_index),
        "relevant_source_context": {
            "source_facts": _relevant_source_facts(
                episode,
                source_fact_ledger=source_fact_ledger or [],
            ),
            "approved_time_deviations": retained,
            "protagonist_action_boundary": protagonist_action_boundary or {},
            "target_tone": target_tone,
            "source_voice_anchors": _compact_source_voice_anchors(source_voice_anchors),
        },
    }


def prompt_metrics(views: dict[str, Any]) -> dict[str, int | str]:
    """Handle prompt metrics."""
    rendered = {key: json.dumps(value, ensure_ascii=False) for key, value in views.items()}
    total = sum(len(value) for value in rendered.values())
    return {
        "input_view_chars": total,
        "active_continuity_chars": len(rendered.get("active_continuity_view", "")),
        "recent_script_chars": len(rendered.get("recent_episode_scripts", "")),
        "future_reservation_chars": len(rendered.get("future_event_reservations", "")),
        "budget_status": "WARN" if total > 35000 else "TARGET_EXCEEDED" if total > 25000 else "PASS",
    }
