"""Utilities for the short novel script pipeline."""
from __future__ import annotations

import copy
import re
from typing import Any


LIVE_CHARACTER_MODE = "live_character"
PROCESS_MODE = "process"


def release_id_for_episode(episode_num: int) -> str:
    """Handle release id for episode."""
    return f"DR_EP{int(episode_num):03d}"


def target_by_episode(release_map: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    """Handle target by episode."""
    output: dict[int, dict[str, Any]] = {}
    for item in (release_map or {}).get("episode_dramatic_targets", []) or []:
        if not isinstance(item, dict):
            continue
        try:
            episode_num = int(item.get("episode_num", 0))
        except (TypeError, ValueError):
            continue
        if episode_num > 0:
            output[episode_num] = copy.deepcopy(item)
    return output


def slice_release_map(
    release_map: dict[str, Any] | None,
    *,
    start_episode: int,
    end_episode: int,
) -> dict[str, Any]:
    """Handle slice release map."""
    source = release_map or {}
    return {
        "release_overview": copy.deepcopy(source.get("release_overview", {})),
        "episode_dramatic_targets": [
            copy.deepcopy(item)
            for item in source.get("episode_dramatic_targets", []) or []
            if isinstance(item, dict)
            and start_episode <= int(item.get("episode_num", 0) or 0) <= end_episode
        ],
        "capacity_bridge_units": [
            copy.deepcopy(item)
            for item in source.get("capacity_bridge_units", []) or []
            if isinstance(item, dict)
            and isinstance(item.get("episode_range"), dict)
            and int(item["episode_range"].get("start", 0) or 0) <= end_episode
            and int(item["episode_range"].get("end", 0) or 0) >= start_episode
        ],
        "opening_gate": copy.deepcopy(source.get("opening_gate", {})),
    }


def validate_release_structure(data: dict[str, Any], *, target_episodes: int) -> None:
    """Handle validate release structure."""
    targets = data.get("episode_dramatic_targets")
    if not isinstance(targets, list):
        raise ValueError("04b_dramatic_release_map.episode_dramatic_targets must be a list")
    actual_episode_nums = [
        int(item.get("episode_num", 0))
        for item in targets
        if isinstance(item, dict)
    ]
    expected_episode_nums = list(range(1, int(target_episodes) + 1))
    if actual_episode_nums != expected_episode_nums:
        raise ValueError(
            "04b_dramatic_release_map episode numbers must be exactly "
            f"1-{target_episodes}, got {actual_episode_nums}"
        )
    actual_ids = [str(item.get("release_id", "")).strip() for item in targets]
    expected_ids = [release_id_for_episode(item) for item in expected_episode_nums]
    if actual_ids != expected_ids:
        raise ValueError(
            "04b_dramatic_release_map release ids must be deterministic, "
            f"expected {expected_ids}, got {actual_ids}"
        )


def validate_release_slice(
    data: dict[str, Any],
    *,
    start_episode: int,
    end_episode: int,
) -> None:
    """Handle validate release slice."""
    targets = data.get("episode_dramatic_targets")
    if not isinstance(targets, list):
        raise ValueError("04b_dramatic_release_map.episode_dramatic_targets must be a list")
    expected_episode_nums = list(range(int(start_episode), int(end_episode) + 1))
    actual_episode_nums = [
        int(item.get("episode_num", 0))
        for item in targets
        if isinstance(item, dict)
    ]
    if actual_episode_nums != expected_episode_nums:
        raise ValueError(
            "04b dramatic release slice episode numbers must be exactly "
            f"{start_episode}-{end_episode}, got {actual_episode_nums}"
        )
    expected_ids = [release_id_for_episode(item) for item in expected_episode_nums]
    actual_ids = [str(item.get("release_id", "")).strip() for item in targets]
    if actual_ids != expected_ids:
        raise ValueError(
            "04b dramatic release slice ids must be deterministic, "
            f"expected {expected_ids}, got {actual_ids}"
        )


def audit_release_map(
    data: dict[str, Any],
    *,
    target_episodes: int,
    source_fact_ledger: list[dict[str, Any]] | None = None,
    canonical_story_lock: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Handle audit release map."""
    findings: list[dict[str, Any]] = []
    targets = [
        item
        for item in data.get("episode_dramatic_targets", []) or []
        if isinstance(item, dict)
    ]
    first_three = targets[:3]
    first_five = targets[:5]
    live_count = sum(
        str(item.get("confrontation_mode", "")).strip() == LIVE_CHARACTER_MODE
        for item in first_three
    )
    if len(first_three) == 3 and live_count < 2:
        findings.append(
            {
                "severity": "WARN",
                "check": "opening_live_obstacle_density",
                "issue": "first_three_require_two_live_character_obstacles",
                "expected_minimum": 2,
                "actual": live_count,
            }
        )
    process_only_episodes = [
        int(item.get("episode_num", 0))
        for item in first_five
        if bool(item.get("process_only"))
        or str(item.get("confrontation_mode", "")).strip() == PROCESS_MODE
    ]
    if process_only_episodes:
        findings.append(
            {
                "severity": "WARN",
                "check": "opening_process_density",
                "issue": "first_five_require_zero_process_only_episodes",
                "episodes": process_only_episodes,
            }
        )
    if any(
        right == left + 1
        for left, right in zip(process_only_episodes, process_only_episodes[1:])
    ):
        findings.append(
            {
                "severity": "WARN",
                "check": "opening_process_streak",
                "issue": "process_only_episodes_must_not_be_adjacent",
                "episodes": process_only_episodes,
            }
        )
    if first_five and int(first_five[-1].get("episode_num", 0) or 0) == 5 and 5 in process_only_episodes:
        previous_fact_ids = {
            str(fact_id)
            for item in first_five[:-1]
            for fact_id in item.get("source_fact_ids", []) or []
        }
        episode_five_fact_ids = {
            str(fact_id) for fact_id in first_five[-1].get("source_fact_ids", []) or []
        }
        if not episode_five_fact_ids or episode_five_fact_ids.issubset(previous_fact_ids):
            findings.append(
                {
                    "severity": "WARN",
                    "check": "opening_process_tail_stall",
                    "issue": "episode_five_process_only_repeats_existing_source_facts",
                    "episode_num": 5,
                    "source_fact_ids": sorted(episode_five_fact_ids),
                }
            )

    def normalized(value: Any) -> str:
        """Handle normalized."""
        return re.sub(r"[\s\W_]+", "", str(value or "")).lower()

    for field in ("visible_result", "hook"):
        previous = ""
        previous_episode = 0
        for item in targets:
            current = normalized(item.get(field))
            episode_num = int(item.get("episode_num", 0))
            if current and current == previous:
                findings.append(
                    {
                        "severity": "WARN",
                        "check": "adjacent_dramatic_release_repetition",
                        "issue": f"adjacent_{field}_repeated",
                        "episode_pair": [previous_episode, episode_num],
                    }
                )
            previous = current
            previous_episode = episode_num

    overview = data.get("release_overview", {}) or {}
    try:
        capacity_gap = int(overview.get("capacity_gap", 0))
    except (TypeError, ValueError):
        capacity_gap = 0
    bridge_units = [
        item
        for item in data.get("capacity_bridge_units", []) or []
        if isinstance(item, dict)
    ]
    if capacity_gap > 0 and not bridge_units:
        findings.append(
            {
                "severity": "WARN",
                "check": "capacity_bridge",
                "issue": "positive_capacity_gap_requires_bridge_units",
                "capacity_gap": capacity_gap,
            }
        )
    fact_by_id = {
        str(item.get("fact_id", "")).strip(): item
        for item in source_fact_ledger or []
        if isinstance(item, dict) and str(item.get("fact_id", "")).strip()
    }
    story_lock = canonical_story_lock or {}
    character_names = [
        str(item).strip()
        for item in story_lock.get("character_names", []) or []
        if str(item).strip()
    ]
    protagonist = str(story_lock.get("protagonist", "")).strip()
    for target in targets:
        target_text = " ".join(
            str(target.get(field, ""))
            for field in (
                "desire",
                "obstacle",
                "choice",
                "immediate_cost",
                "visible_result",
                "hook",
                "required_event_function",
            )
        )
        for fact_id in target.get("source_fact_ids", []) or []:
            fact = fact_by_id.get(str(fact_id))
            if fact is None and fact_by_id:
                findings.append(
                    {
                        "severity": "WARN",
                        "check": "source_fact_binding",
                        "issue": "unknown_source_fact_id",
                        "episode_num": target.get("episode_num"),
                        "source_fact_id": fact_id,
                    }
                )
                continue
            if fact is None:
                continue
            actor = str(fact.get("actor", "")).strip()
            if actor in character_names and actor not in target_text and not (
                actor == protagonist and "主角" in target_text
            ):
                findings.append(
                    {
                        "severity": "WARN",
                        "check": "source_fact_binding",
                        "issue": "source_fact_actor_not_preserved",
                        "episode_num": target.get("episode_num"),
                        "source_fact_id": fact_id,
                        "expected_actor": actor,
                    }
                )
            object_text = str(fact.get("object", ""))
            missing_objects = [
                name for name in character_names if name in object_text and name not in target_text
            ]
            if missing_objects:
                findings.append(
                    {
                        "severity": "WARN",
                        "check": "source_fact_binding",
                        "issue": "source_fact_character_object_not_preserved",
                        "episode_num": target.get("episode_num"),
                        "source_fact_id": fact_id,
                        "missing_character_objects": missing_objects,
                    }
                )
    return {
        "status": "WARN" if findings else "PASS",
        "target_episodes": int(target_episodes),
        "target_count": len(targets),
        "findings": findings,
    }


def event_alignment_findings(
    event_pool: list[dict[str, Any]],
    *,
    release_map: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Handle event alignment findings."""
    targets = target_by_episode(release_map)
    findings: list[dict[str, Any]] = []
    for index, event in enumerate(event_pool):
        if not isinstance(event, dict):
            continue
        window = event.get("episode_window") or {}
        try:
            start = int(window.get("start", 0))
            end = int(window.get("end", 0))
        except (AttributeError, TypeError, ValueError):
            continue
        expected = [targets[episode]["release_id"] for episode in range(start, end + 1) if episode in targets]
        actual = [str(item) for item in event.get("dramatic_target_ids", []) or []]
        if actual != expected:
            findings.append(
                {
                    "severity": "WARN",
                    "check": "event_dramatic_release_alignment",
                    "path": f"event_pool[{index}].dramatic_target_ids",
                    "event_id": event.get("id"),
                    "expected": expected,
                    "actual": actual,
                }
            )
    return findings


def episode_alignment_findings(
    episode_outlines: list[dict[str, Any]],
    *,
    release_map: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Handle episode alignment findings."""
    targets = target_by_episode(release_map)
    findings: list[dict[str, Any]] = []
    for index, episode in enumerate(episode_outlines):
        if not isinstance(episode, dict):
            continue
        try:
            episode_num = int(episode.get("episode_num", 0))
        except (TypeError, ValueError):
            continue
        expected = str((targets.get(episode_num) or {}).get("release_id", ""))
        actual = str(episode.get("dramatic_target_id", ""))
        if expected and actual != expected:
            findings.append(
                {
                    "severity": "WARN",
                    "check": "episode_dramatic_release_alignment",
                    "path": f"episode_outlines[{index}].dramatic_target_id",
                    "episode_num": episode_num,
                    "expected": expected,
                    "actual": actual,
                }
            )
    return findings
