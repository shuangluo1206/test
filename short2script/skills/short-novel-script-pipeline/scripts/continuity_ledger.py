"""Utilities for the short novel script pipeline."""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


LEDGER_SCHEMA_VERSION = "continuity_ledger_v2"
EPISODE_DELTA_SCHEMA_VERSION = "08_episode_delta_v2"
VALID_OPERATIONS = {"add", "update", "resolve", "retire"}
ACTIVE_STATUS = "active"
ACTIVE_DIGEST_WINDOW = 8


def new_ledger(
    *,
    canonical_story_lock: dict[str, Any] | None = None,
    prop_registry: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Handle new ledger."""
    registry = {
        str(item.get("prop_id", "")).strip(): copy.deepcopy(item)
        for item in prop_registry or []
        if isinstance(item, dict) and str(item.get("prop_id", "")).strip()
    }
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "canonical_story_lock": copy.deepcopy(canonical_story_lock or {}),
        "audience_facts": {},
        "character_knowledge": {},
        "private_facts": {},
        "foreshadowing": {},
        "open_threads": {},
        "props": {},
        "prop_registry": registry,
        "history": [],
        "operation_warnings": [],
        "rejected_deltas": [],
        "state_blocks": [],
        "generated_episodes": [],
        "completed_transaction_digest": [],
        "completed_effect_digest": [],
        "next_episode_bridge": "",
        "last_scene_state": {},
    }


def materialize_prop_registry_for_episode(
    ledger: dict[str, Any],
    *,
    episode_num: int,
    prop_registry: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Materialize canonical prop state before the first episode that may mutate it."""

    next_ledger = copy.deepcopy(ledger)
    registry = next_ledger.setdefault("prop_registry", {})
    for item in prop_registry or []:
        if not isinstance(item, dict):
            continue
        prop_id = str(item.get("prop_id", "")).strip()
        if prop_id:
            registry[prop_id] = copy.deepcopy(item)
    props = next_ledger.setdefault("props", {})
    history = next_ledger.setdefault("history", [])
    for prop_id, item in registry.items():
        if prop_id in props or not isinstance(item, dict):
            continue
        try:
            activation_episode = int(
                item.get("activation_episode", item.get("created_episode", 0)) or 0
            )
        except (TypeError, ValueError):
            continue
        if activation_episode <= 0 or activation_episode > int(episode_num):
            continue
        initial_state = item.get("initial_state")
        if not isinstance(initial_state, dict):
            continue
        record = {
            "id": prop_id,
            "prop_id": prop_id,
            "prop_name": item.get("prop_name", ""),
            "entity_kind": item.get("entity_kind", ""),
            "holder": initial_state.get("holder", ""),
            "location": initial_state.get("location", ""),
            "status": initial_state.get("status", ""),
            "lifecycle_status": ACTIVE_STATUS,
            "activated_episode": activation_episode,
            "updated_episode": activation_episode,
            "evidence": "stage05 canonical prop initial state",
        }
        props[prop_id] = record
        history.append(
            {
                "episode_num": activation_episode,
                "category": "props",
                "record_id": prop_id,
                "operation": "materialize",
                "requested_operation": "materialize",
                "previous": None,
                "current": copy.deepcopy(record),
                "evidence": "stage05 canonical prop initial state",
            }
        )
    return next_ledger


def _legacy_id(prefix: str, *parts: Any) -> str:
    """Handle legacy id."""
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"LEGACY_{prefix}_{digest}"


def _as_string_list(value: Any) -> list[str]:
    """Handle as string list."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _legacy_fact_changes(value: Any, *, prefix: str) -> list[dict[str, str]]:
    """Handle legacy fact changes."""
    changes: list[dict[str, str]] = []
    for detail in _as_string_list(value):
        changes.append(
            {
                "fact_id": _legacy_id(prefix, detail),
                "operation": "add",
                "detail": detail,
                "evidence": "legacy clean migration",
            }
        )
    return changes


def normalize_episode_delta(output: dict[str, Any]) -> dict[str, Any]:
    """Return a v2 episode envelope while accepting legacy 08 snapshots."""

    if output.get("schema_version") == EPISODE_DELTA_SCHEMA_VERSION:
        return copy.deepcopy(output)

    state = output.get("state_update") if isinstance(output.get("state_update"), dict) else {}
    continuity = output.get("continuity_update") if isinstance(output.get("continuity_update"), dict) else {}

    audience_source = continuity.get("audience_known", state.get("audience_known", []))
    private_source = continuity.get("writer_private", [])
    character_source = continuity.get("character_known", {})
    character_changes: list[dict[str, str]] = []
    if isinstance(character_source, dict):
        for character_name, raw_items in character_source.items():
            for detail in _as_string_list(raw_items):
                character_changes.append(
                    {
                        "character_name": str(character_name),
                        "fact_id": _legacy_id("CHAR", character_name, detail),
                        "operation": "add",
                        "detail": detail,
                        "evidence": "legacy clean migration",
                    }
                )

    foreshadowing_changes: list[dict[str, str]] = []
    for item in continuity.get("foreshadowing_status", []) or []:
        if not isinstance(item, dict):
            continue
        foreshadowing_changes.append(
            {
                "id": str(item.get("id", "")).strip() or _legacy_id("FORESHADOW", item),
                "operation": "update",
                "detail": str(item.get("detail", item.get("status", ""))),
            }
        )

    prop_changes: list[dict[str, str]] = []
    for item in continuity.get("prop_state_updates", []) or []:
        if not isinstance(item, dict):
            continue
        prop_changes.append(
            {
                "prop_id": str(item.get("prop_id", "")).strip(),
                "operation": "update",
                "holder": str(item.get("holder", "")),
                "location": str(item.get("location", "")),
                "status": str(item.get("status", "")),
                "evidence": str(item.get("change_evidence", "")),
            }
        )

    completed = continuity.get("completed_beat_ids", continuity.get("completed_beats", []))
    bridge = str(
        state.get("next_episode_bridge", "")
        or continuity.get("next_episode_bridge", "")
        or state.get("next_hook", "")
    )
    return {
        "schema_version": EPISODE_DELTA_SCHEMA_VERSION,
        "final_script": str(output.get("final_script", "")),
        "state_update": {
            "audience_fact_changes": _legacy_fact_changes(audience_source, prefix="AUD"),
            "character_knowledge_changes": character_changes,
            "private_fact_changes": _legacy_fact_changes(private_source, prefix="PRIVATE"),
            "next_episode_bridge": bridge,
        },
        "continuity_update": {
            "completed_beat_ids": _as_string_list(completed),
            "completed_effect_evidence": [],
            "foreshadowing_changes": foreshadowing_changes,
            "open_thread_changes": [],
            "prop_state_changes": prop_changes,
            "last_scene_state": copy.deepcopy(continuity.get("last_scene_state", {})),
            "scene_boundary_check": copy.deepcopy(continuity.get("scene_boundary_check", {})),
            "narration_device_usage": copy.deepcopy(continuity.get("narration_device_usage", {})),
        },
    }


def _apply_change(
    records: dict[str, Any],
    *,
    record_id: str,
    operation: str,
    payload: dict[str, Any],
    episode_num: int,
    history: list[dict[str, Any]],
    operation_warnings: list[dict[str, Any]],
    category: str,
) -> None:
    """Handle apply change."""
    if operation not in VALID_OPERATIONS:
        raise ValueError(f"unsupported ledger operation at {category}.{record_id}: {operation}")
    previous = copy.deepcopy(records.get(record_id))
    if operation == "update" and previous is None:
        raise ValueError(
            f"ledger update requires existing record at {category}.{record_id}"
        )
    elif operation in {"resolve", "retire"} and previous is None:
        raise ValueError(
            f"ledger {operation} requires existing record at {category}.{record_id}"
        )
    elif operation == "add" and previous is not None:
        raise ValueError(
            f"ledger add requires new record at {category}.{record_id}"
        )
    if previous and previous.get("lifecycle_status") in {"resolved", "retired"}:
        raise ValueError(
            f"ledger terminal record cannot change again at {category}.{record_id}"
        )
    next_record = copy.deepcopy(previous or {"id": record_id})
    next_record.update(payload)
    lifecycle_status = (
        "resolved" if operation == "resolve" else "retired" if operation == "retire" else ACTIVE_STATUS
    )
    next_record["lifecycle_status"] = lifecycle_status
    if "status" not in payload:
        next_record["status"] = lifecycle_status
    next_record["updated_episode"] = episode_num
    records[record_id] = next_record
    history.append(
        {
            "episode_num": episode_num,
            "category": category,
            "record_id": record_id,
            "operation": operation,
            "requested_operation": operation,
            "previous": previous,
            "current": copy.deepcopy(next_record),
            "evidence": payload.get("evidence", ""),
        }
    )


def delta_operation_findings(
    ledger: dict[str, Any],
    *,
    output: dict[str, Any],
) -> list[dict[str, Any]]:
    """Handle delta operation findings."""
    delta = normalize_episode_delta(output)
    findings: list[dict[str, Any]] = []

    def inspect(
        records: dict[str, Any],
        *,
        item: dict[str, Any],
        record_id: str,
        category: str,
    ) -> None:
        """Handle inspect."""
        operation = str(item.get("operation", "")).strip()
        if operation not in VALID_OPERATIONS:
            findings.append(
                {
                    "severity": "BLOCK",
                    "check": "ledger_operation",
                    "category": category,
                    "record_id": record_id,
                    "issue": "unsupported_operation",
                    "operation": operation,
                }
            )
            return
        previous = records.get(record_id)
        if operation == "update" and previous is None:
            findings.append(
                {
                    "severity": "BLOCK",
                    "check": "ledger_operation",
                    "category": category,
                    "record_id": record_id,
                    "issue": "update_missing_record",
                }
            )
        if operation in {"resolve", "retire"} and previous is None:
            findings.append(
                {
                    "severity": "BLOCK",
                    "check": "ledger_operation",
                    "category": category,
                    "record_id": record_id,
                    "issue": f"{operation}_missing_record",
                }
            )
        if operation == "add" and previous is not None:
            findings.append(
                {
                    "severity": "BLOCK",
                    "check": "ledger_operation",
                    "category": category,
                    "record_id": record_id,
                    "issue": "add_existing_record",
                }
            )
        if (
            isinstance(previous, dict)
            and previous.get("lifecycle_status") in {"resolved", "retired"}
        ):
            findings.append(
                {
                    "severity": "BLOCK",
                    "check": "ledger_operation",
                    "category": category,
                    "record_id": record_id,
                    "issue": (
                        "terminal_record_reactivation"
                        if operation in {"add", "update"}
                        else "terminal_record_changed_again"
                    ),
                    "previous_status": previous.get("lifecycle_status"),
                }
            )

    state = delta.get("state_update", {})
    for key, category in (
        ("audience_fact_changes", "audience_facts"),
        ("private_fact_changes", "private_facts"),
    ):
        records = ledger.get(category, {}) if isinstance(ledger.get(category), dict) else {}
        for item in state.get(key, []) or []:
            if isinstance(item, dict):
                inspect(
                    records,
                    item=item,
                    record_id=str(item.get("fact_id", "")).strip(),
                    category=category,
                )
    for item in state.get("character_knowledge_changes", []) or []:
        if not isinstance(item, dict):
            continue
        character = str(item.get("character_name", "")).strip()
        records = (
            (ledger.get("character_knowledge", {}) or {}).get(character, {})
            if isinstance(ledger.get("character_knowledge"), dict)
            else {}
        )
        inspect(
            records if isinstance(records, dict) else {},
            item=item,
            record_id=str(item.get("fact_id", "")).strip(),
            category=f"character_knowledge.{character}",
        )
    continuity = delta.get("continuity_update", {})
    for key, id_key, category in (
        ("foreshadowing_changes", "id", "foreshadowing"),
        ("open_thread_changes", "thread_id", "open_threads"),
        ("prop_state_changes", "prop_id", "props"),
    ):
        records = ledger.get(category, {}) if isinstance(ledger.get(category), dict) else {}
        for item in continuity.get(key, []) or []:
            if isinstance(item, dict):
                inspect(
                    records,
                    item=item,
                    record_id=str(item.get(id_key, "")).strip(),
                    category=category,
                )
    return findings


def merge_episode_delta(
    ledger: dict[str, Any],
    *,
    episode: dict[str, Any],
    output: dict[str, Any],
    collect_invalid_operations: bool = False,
    commit_status: str = "COMMITTED",
) -> dict[str, Any]:
    """Handle merge episode delta."""
    delta = normalize_episode_delta(output)
    operation_findings = delta_operation_findings(ledger, output=delta)
    if operation_findings:
        if collect_invalid_operations:
            return record_uncommitted_episode(
                ledger,
                episode=episode,
                output=delta,
                findings=operation_findings,
                commit_status="STATE_UNCOMMITTED",
            )
        raise ValueError(f"episode delta cannot be committed: {operation_findings[0]}")
    next_ledger = copy.deepcopy(ledger)
    if next_ledger.get("schema_version") != LEDGER_SCHEMA_VERSION:
        migrated = new_ledger(
            canonical_story_lock=next_ledger.get("canonical_story_lock", {}),
            prop_registry=list((next_ledger.get("prop_registry") or {}).values())
            if isinstance(next_ledger.get("prop_registry"), dict)
            else [],
        )
        migrated.update({key: value for key, value in next_ledger.items() if key in migrated})
        next_ledger = migrated

    episode_num = int(episode.get("episode_num", 0))
    history = next_ledger.setdefault("history", [])
    operation_warnings = next_ledger.setdefault("operation_warnings", [])
    state = delta["state_update"]
    continuity = delta["continuity_update"]

    def apply_change(
        records: dict[str, Any],
        *,
        record_id: str,
        operation: str,
        payload: dict[str, Any],
        category: str,
    ) -> None:
        """Handle apply change."""
        _apply_change(
            records,
            record_id=record_id,
            operation=operation,
            payload=payload,
            episode_num=episode_num,
            history=history,
            operation_warnings=operation_warnings,
            category=category,
        )

    for item in state.get("audience_fact_changes", []):
        apply_change(
            next_ledger.setdefault("audience_facts", {}),
            record_id=str(item.get("fact_id", "")).strip(),
            operation=str(item.get("operation", "")).strip(),
            payload={"detail": item.get("detail", ""), "evidence": item.get("evidence", "")},
            category="audience_facts",
        )
    for item in state.get("private_fact_changes", []):
        apply_change(
            next_ledger.setdefault("private_facts", {}),
            record_id=str(item.get("fact_id", "")).strip(),
            operation=str(item.get("operation", "")).strip(),
            payload={"detail": item.get("detail", ""), "evidence": item.get("evidence", "")},
            category="private_facts",
        )
    for item in state.get("character_knowledge_changes", []):
        character = str(item.get("character_name", "")).strip()
        records = next_ledger.setdefault("character_knowledge", {}).setdefault(character, {})
        apply_change(
            records,
            record_id=str(item.get("fact_id", "")).strip(),
            operation=str(item.get("operation", "")).strip(),
            payload={"detail": item.get("detail", ""), "evidence": item.get("evidence", "")},
            category=f"character_knowledge.{character}",
        )

    for key, id_key, category in (
        ("foreshadowing_changes", "id", "foreshadowing"),
        ("open_thread_changes", "thread_id", "open_threads"),
        ("prop_state_changes", "prop_id", "props"),
    ):
        records = next_ledger.setdefault(category, {})
        for item in continuity.get(key, []):
            record_id = str(item.get(id_key, "")).strip()
            payload = {name: value for name, value in item.items() if name not in {id_key, "operation"}}
            apply_change(
                records,
                record_id=record_id,
                operation=str(item.get("operation", "")).strip(),
                payload=payload,
                category=category,
            )

    next_ledger["next_episode_bridge"] = state.get("next_episode_bridge", "")
    next_ledger["last_scene_state"] = copy.deepcopy(continuity.get("last_scene_state", {}))
    next_ledger.setdefault("completed_transaction_digest", []).append(
        {
            "episode_num": episode_num,
            "transaction_ids": copy.deepcopy(continuity.get("completed_beat_ids", [])),
        }
    )
    next_ledger.setdefault("completed_effect_digest", []).append(
        {
            "episode_num": episode_num,
            "effect_ids": [
                str(item.get("effect_id", "")).strip()
                for item in continuity.get("completed_effect_evidence", []) or []
                if isinstance(item, dict) and str(item.get("effect_id", "")).strip()
            ],
        }
    )
    next_ledger.setdefault("generated_episodes", []).append(
        {
            "episode_num": episode_num,
            "title": episode.get("title", ""),
            "final_script": delta.get("final_script", ""),
            "completed_beat_ids": copy.deepcopy(continuity.get("completed_beat_ids", [])),
            "next_episode_bridge": state.get("next_episode_bridge", ""),
            "last_scene_state": copy.deepcopy(continuity.get("last_scene_state", {})),
            "delta_commit_status": commit_status,
        }
    )
    return next_ledger


def record_uncommitted_episode(
    ledger: dict[str, Any],
    *,
    episode: dict[str, Any],
    output: dict[str, Any],
    findings: list[dict[str, Any]],
    commit_status: str = "STATE_UNCOMMITTED",
) -> dict[str, Any]:
    """Handle record uncommitted episode."""
    next_ledger = copy.deepcopy(ledger)
    delta = normalize_episode_delta(output)
    episode_num = int(episode.get("episode_num", 0))
    next_ledger.setdefault("rejected_deltas", []).append(
        {
            "episode_num": episode_num,
            "findings": copy.deepcopy(findings),
            "proposed_delta": copy.deepcopy(delta),
        }
    )
    next_ledger.setdefault("state_blocks", []).append(
        {
            "episode_num": episode_num,
            "commit_status": commit_status,
            "findings": copy.deepcopy(findings),
        }
    )
    next_ledger.setdefault("generated_episodes", []).append(
        {
            "episode_num": episode_num,
            "title": episode.get("title", ""),
            "final_script": delta.get("final_script", ""),
            "completed_beat_ids": [],
            "proposed_completed_beat_ids": copy.deepcopy(
                (delta.get("continuity_update") or {}).get("completed_beat_ids", [])
            ),
            "next_episode_bridge": (delta.get("state_update") or {}).get(
                "next_episode_bridge", ""
            ),
            "last_scene_state": copy.deepcopy(
                (delta.get("continuity_update") or {}).get("last_scene_state", {})
            ),
            "delta_commit_status": commit_status,
        }
    )
    return next_ledger


def record_rejected_episode(
    ledger: dict[str, Any],
    *,
    episode: dict[str, Any],
    output: dict[str, Any],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Handle record rejected episode."""
    return record_uncommitted_episode(
        ledger,
        episode=episode,
        output=output,
        findings=findings,
        commit_status="REJECTED",
    )


def active_view(ledger: dict[str, Any]) -> dict[str, Any]:
    """Handle active view."""
    def active_records(value: Any) -> Any:
        """Handle active records."""
        if not isinstance(value, dict):
            return {}
        active: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(item, dict):
                continue
            lifecycle_status = item.get("lifecycle_status")
            if lifecycle_status is None:
                legacy_status = item.get("status", ACTIVE_STATUS)
                lifecycle_status = (
                    legacy_status
                    if legacy_status in {ACTIVE_STATUS, "resolved", "retired"}
                    else ACTIVE_STATUS
                )
            if lifecycle_status == ACTIVE_STATUS:
                active[key] = copy.deepcopy(item)
        return active

    character_view: dict[str, Any] = {}
    for character, records in (ledger.get("character_knowledge") or {}).items():
        active = active_records(records)
        if active:
            character_view[str(character)] = active
    return {
        "audience_facts": active_records(ledger.get("audience_facts")),
        "character_knowledge": character_view,
        "private_facts": active_records(ledger.get("private_facts")),
        "foreshadowing": active_records(ledger.get("foreshadowing")),
        "open_threads": active_records(ledger.get("open_threads")),
        "props": active_records(ledger.get("props")),
        "next_episode_bridge": ledger.get("next_episode_bridge", ""),
        "last_scene_state": copy.deepcopy(ledger.get("last_scene_state", {})),
        "completed_transaction_digest": copy.deepcopy(
            (ledger.get("completed_transaction_digest", []) or [])[-ACTIVE_DIGEST_WINDOW:]
        ),
        "completed_effect_digest": copy.deepcopy(
            (ledger.get("completed_effect_digest", []) or [])[-ACTIVE_DIGEST_WINDOW:]
        ),
        "state_block_count": len(ledger.get("state_blocks", []) or []),
    }
