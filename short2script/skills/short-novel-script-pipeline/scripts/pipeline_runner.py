#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utilities for the short novel script pipeline."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import llm_client
import llm_schema_localization
import parsers
import prompt_renderer
import release_preflight
import season_plan_audit
import stage_contracts
import text_io
import validators
import clean_json_to_md
import continuity_ledger as continuity_ledger_v2
import dramatic_release
import episode_generation_context
import event_transactions


PROJECT_ROOT = SCRIPT_DIR.parents[2]
SKILL_ROOT = SCRIPT_DIR.parent
STAGES_PATH = SKILL_ROOT / "references" / "pipeline-stages.json"
DEFAULT_RUNS_DIR = PROJECT_ROOT / "runs"
DEFAULT_MARKET_TAGS = ["强冲突", "反转爽点", "人物成长", "规则反击", "关系拉扯"]
DEFAULT_TARGET_EPISODES = 40
PREVIOUS_CONTEXT_HEAD_CHARS = 600
PREVIOUS_CONTEXT_TAIL_CHARS = 1200
LEDGER_SCRIPT_EXCERPT_CHARS = 500
COMPACT_LEDGER_RECENT_EPISODE_COUNT = 3
COMPACT_LEDGER_TEXT_CLIP_CHARS = 420
PLANNING_TEXT_CLIP_CHARS = 48
SCRIPT_CAMERA_MARKER_RE = re.compile(
    r"[，,]?\s*(?:镜头(?:拉远|推近|推进|停在|停留在|切到|转向|给到|扫过|移向|定格在)|定格)[。.]?"
)
STAGE_EXECUTION_ORDER = [
    "00a_global_config",
    "01_novel_summary",
    "02_storyline_understanding",
    "03_plot_character_extract",
    "04_adaptation_direction",
    "04a_flashback_screening",
    "04b_dramatic_release_map",
    "05_plot_character_adaptation",
    "06_script_outline_design",
    "07_episode_planning",
    "08_script_body_generation",
]
STAGE_BEHAVIOR_VERSIONS = {
    "00a_global_config": "whole_novel_config_recommendation_v1",
    "01_novel_summary": "source_fact_causality_v3",
    "02_storyline_understanding": "adaptation_capacity_v2",
    "03_plot_character_extract": "source_fact_ledger_v3",
    "04_adaptation_direction": "source_fact_preservation_v2",
    "04a_flashback_screening": "time_deviation_screening_v1",
    "04b_dramatic_release_map": "episode_dramatic_causality_fanout_v6",
    "05_plot_character_adaptation": "state_transition_transactions_v13",
    "06_script_outline_design": "variable_blocks_opening_payoff_v3",
    "07_episode_planning": "dramatic_release_registry_join_v32",
    "08_script_body_generation": "atomic_state_effect_evidence_v23",
}
VALIDATION_MODE_COLLECT = "collect"
VALIDATION_MODE_STRICT = "strict"
VALIDATION_MODES = {VALIDATION_MODE_COLLECT, VALIDATION_MODE_STRICT}
DEFAULT_REPORT_ONLY_VALIDATION_CHECKS = {
    "continuity_update_references",
    "continuity_fact_alignment",
    "final_script_quality",
    "prop_state_continuity",
}
HARD_QA_CHECKS = {"episode_numbering"}
COLLECT_WARNING_QA_CHECKS = {
    "episode_motion",
    "asset_references",
    "event_block_alignment",
    "event_window_alignment",
    "epilogue_budget",
    "conflict_mode_streak",
    "pattern_family_streak",
    "adjacent_opening_continuity",
    "completed_prop_continuity",
    "prop_lifecycle_reappearance",
    "prop_state_continuity",
    "continuity_fact_alignment",
    "child_beat_accounting",
    "event_child_beat_alignment",
    "narration_device_budget",
    "flashback_screening_alignment",
    "forbidden_script_idioms",
}
EPISODE_PLANNING_MAX_EPISODES_PER_CALL = 1
DRAMATIC_RELEASE_MAX_EPISODES_PER_CALL = 5
DRAMATIC_RELEASE_CONTRACT_RETRIES = 2
DEFAULT_RUN_CONFIG = {
    "target_episodes": DEFAULT_TARGET_EPISODES,
    "episode_duration_seconds": 90,
    "rewrite_intensity": "balanced",
    "character_background_policy": "minor_adjust",
    "subplot_policy": "moderate",
    "new_character_policy": "controlled",
    "source_preservation_level": "core_plot",
    "source_boundary_mode": "balanced_spark",
    "pacing_controls": validators.DEFAULT_PACING_CONTROLS,
    "market_tags": DEFAULT_MARKET_TAGS,
}
@dataclass
class RunPaths:
    """Group run paths behavior."""
    root: Path
    prompts: Path
    outputs: Path
    parsed: Path
    logs: Path
    manifests: Path
    final: Path
    attempts: Path | None = None


def read_text(path: Path) -> str:
    """Handle read text."""
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    """Handle write text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    """Handle write json."""
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def write_json_atomic(path: Path, data: Any) -> None:
    """Handle write json atomic."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def update_run_state(paths: RunPaths, **changes: Any) -> dict[str, Any]:
    """Handle update run state."""
    path = paths.root / "run_state.json"
    try:
        current = json.loads(read_text(path)) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        current = {}
    current.update(changes)
    current["updated_at"] = datetime.now().isoformat(timespec="seconds")
    write_json_atomic(path, current)
    return current


def write_partial_generation_summary(
    paths: RunPaths,
    *,
    run_id: str,
    target_episodes: int,
    generated_episodes: list[int],
    current_artifact: str,
    failure: dict[str, Any] | None = None,
) -> None:
    """Handle write partial generation summary."""
    continuous_prefix = 0
    for episode_num in sorted(set(generated_episodes)):
        if episode_num == continuous_prefix + 1:
            continuous_prefix = episode_num
        else:
            break
    status = "partial" if generated_episodes else "failed" if failure else "running"
    update_run_state(
        paths,
        status=status,
        target_episodes=target_episodes,
        generated_episodes=generated_episodes,
        generated_episode_count=len(generated_episodes),
        continuous_completed_prefix=continuous_prefix,
        current_artifact=current_artifact,
        last_success_at=datetime.now().isoformat(timespec="seconds") if generated_episodes else "",
        failure=failure,
    )
    generation_status = "PARTIAL" if generated_episodes else "BLOCK" if failure else "RUNNING"
    write_json_atomic(
        paths.final / "qa_summary.json",
        {
            "overall_status": generation_status,
            "generation_status": generation_status,
            "quality_status": "NOT_FINAL",
            "blocking_issues": [failure] if failure else [],
            "warnings": [],
            "target_episodes": target_episodes,
            "generated_episodes": generated_episodes,
            "continuous_completed_prefix": continuous_prefix,
        },
    )
    write_json_atomic(
        paths.final / "run_summary.json",
        {
            "run_id": run_id,
            "generation_status": generation_status,
            "target_episodes": target_episodes,
            "generated_episodes": generated_episodes,
            "continuous_completed_prefix": continuous_prefix,
            "current_artifact": current_artifact,
            "failure": failure,
            "run_root": str(paths.root),
        },
    )


def archive_artifact_pipeline_attempt(
    paths: RunPaths,
    *,
    artifact_id: str,
    attempt: int,
    error: str,
) -> Path | None:
    """Handle archive artifact pipeline attempt."""
    if paths.attempts is None:
        return None
    destination = paths.attempts / artifact_id / f"pipeline_attempt_{attempt:02d}_{time.time_ns()}"
    destination.mkdir(parents=True, exist_ok=False)
    candidates = (
        paths.prompts / f"{artifact_id}.prompt.md",
        paths.outputs / f"{artifact_id}.raw.md",
        paths.outputs / f"{artifact_id}.clean.json",
        paths.logs / f"{artifact_id}.log.json",
        paths.manifests / f"{artifact_id}.manifest.json",
        paths.parsed / "parser_reports" / f"{artifact_id}.json",
        paths.parsed / "localization_reports" / f"{artifact_id}.json",
        paths.parsed / "contract_reports" / f"{artifact_id}.contract_report.json",
    )
    copied: list[str] = []
    for source in candidates:
        if not source.exists():
            continue
        shutil.copy2(source, destination / source.name)
        copied.append(str(source.relative_to(paths.root)))
    write_json(
        destination / "pipeline_attempt.json",
        {"artifact_id": artifact_id, "attempt": attempt, "error": error, "copied_artifacts": copied},
    )
    return destination


def render_clean_md_if_requested(args: argparse.Namespace, run_root: Path) -> None:
    """Handle render clean md if requested."""
    if not bool(getattr(args, "render_clean_md", False)):
        return
    try:
        clean_json_to_md.render_run_clean_json_to_md(run_dir=run_root)
    except Exception as exc:  # pragma: no cover - render layer must not affect run completion
        print(f"WARN: failed to render clean JSON markdown for {run_root}: {exc}", file=sys.stderr)


def finish_run(args: argparse.Namespace, run_root: Path) -> Path:
    """Handle finish run."""
    render_clean_md_if_requested(args, run_root)
    return run_root


def write_contract_report(
    paths: RunPaths,
    *,
    artifact_id: str,
    stage_id: str,
    errors: list[str],
    warnings: list[str],
    checked_paths: list[str],
    contract_profile: str | None = None,
) -> dict[str, Any]:
    """Handle write contract report."""
    report = {
        "artifact_id": artifact_id,
        "stage_id": stage_id,
        "status": "FAIL" if errors else "PASS",
        "errors": errors,
        "warnings": warnings,
        "checked_paths": checked_paths,
    }
    if contract_profile:
        report["contract_profile"] = contract_profile
    write_json(paths.parsed / "contract_reports" / f"{artifact_id}.contract_report.json", report)
    return report


def validate_projection_contract(
    paths: RunPaths,
    *,
    artifact_id: str,
    stage_id: str,
    data: dict[str, Any],
    contract_profile: str | None,
) -> None:
    """Handle validate projection contract."""
    if not contract_profile:
        return
    report = stage_contracts.validate(stage_id, data, profile=contract_profile)
    write_contract_report(
        paths,
        artifact_id=artifact_id,
        stage_id=stage_id,
        errors=report["errors"],
        warnings=report["warnings"],
        checked_paths=report["checked_paths"],
        contract_profile=contract_profile,
    )
    if report["errors"]:
        raise ValueError("; ".join(report["errors"]))


def refresh_localization_summary(paths: RunPaths) -> dict[str, Any]:
    """Handle refresh localization summary."""
    report_dir = paths.parsed / "localization_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []
    for path in sorted(report_dir.glob("*.json")):
        try:
            item = json.loads(read_text(path))
        except (OSError, json.JSONDecodeError):
            continue
        artifact_id = str(item.get("artifact_id", path.stem))
        if path.name != f"{artifact_id}.json":
            continue
        reports.append(
            {
                "artifact_id": artifact_id,
                "stage_id": item.get("stage_id", ""),
                "status": item.get("status", "FAIL"),
            }
        )
    status_counts = {
        status: sum(1 for item in reports if item.get("status") == status)
        for status in ("PASS", "WARN", "FAIL")
    }
    summary = {
        "total_artifacts": len(reports),
        "status_counts": status_counts,
        "artifacts": reports,
    }
    write_json(paths.parsed / "localization_summary.json", summary)
    return summary


def write_localization_report(paths: RunPaths, artifact_id: str, report: dict[str, Any]) -> dict[str, Any]:
    """Handle write localization report."""
    report_dir = paths.parsed / "localization_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {"artifact_id": artifact_id, **report}
    write_json(report_dir / f"{artifact_id}.json", payload)
    refresh_localization_summary(paths)
    return payload


def refresh_parser_summary(paths: RunPaths) -> dict[str, Any]:
    """Handle refresh parser summary."""
    report_dir = paths.parsed / "parser_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = []
    for path in sorted(report_dir.glob("*.json")):
        try:
            item = json.loads(read_text(path))
        except (OSError, json.JSONDecodeError):
            continue
        artifact_id = str(item.get("artifact_id", path.stem))
        if path.name != f"{artifact_id}.json":
            continue
        artifacts.append(
            {
                "artifact_id": artifact_id,
                "stage_id": item.get("stage_id", ""),
                "status": item.get("status", "FAIL"),
                "operation_count": int(item.get("operation_count", 0)),
                "content_discarded": bool(item.get("content_discarded", False)),
            }
        )
    summary = {
        "total_artifacts": len(artifacts),
        "artifacts_repaired": sum(1 for item in artifacts if item["operation_count"]),
        "artifacts_with_discarded_content": sum(1 for item in artifacts if item["content_discarded"]),
        "status_counts": {
            status: sum(1 for item in artifacts if item["status"] == status)
            for status in ("PASS", "WARN", "FAIL")
        },
        "artifacts": artifacts,
    }
    write_json(paths.parsed / "parser_summary.json", summary)
    return summary


def write_parser_report(
    paths: RunPaths,
    *,
    artifact_id: str,
    stage_id: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    """Handle write parser report."""
    report_dir = paths.parsed / "parser_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {"artifact_id": artifact_id, "stage_id": stage_id, **report}
    write_json(report_dir / f"{artifact_id}.json", payload)
    refresh_parser_summary(paths)
    return payload


def unchanged_parser_report(*, source: str) -> dict[str, Any]:
    """Handle unchanged parser report."""
    return {
        "status": "PASS",
        "source": source,
        "before_sha256": "",
        "after_sha256": "",
        "operation_count": 0,
        "operations": [],
        "content_discarded": False,
    }


def refresh_unmapped_fields_summary(paths: RunPaths) -> dict[str, Any]:
    """Handle refresh unmapped fields summary."""
    report_dir = paths.parsed / "unmapped_fields"
    report_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = []
    for path in sorted(report_dir.glob("*.json")):
        try:
            item = json.loads(read_text(path))
        except (OSError, json.JSONDecodeError):
            continue
        artifact_id = str(item.get("artifact_id", path.stem))
        if path.name != f"{artifact_id}.json":
            continue
        artifacts.append(
            {
                "artifact_id": artifact_id,
                "stage_id": item.get("stage_id", ""),
                "status": item.get("status", "FAIL"),
                "field_count": int(item.get("field_count", 0)),
            }
        )
    summary = {
        "total_artifacts": len(artifacts),
        "artifacts_with_unmapped_fields": sum(1 for item in artifacts if item["field_count"]),
        "total_unmapped_fields": sum(item["field_count"] for item in artifacts),
        "artifacts": artifacts,
    }
    write_json(paths.parsed / "unmapped_fields_summary.json", summary)
    return summary


def write_unmapped_fields_report(
    paths: RunPaths,
    *,
    artifact_id: str,
    stage_id: str,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    """Handle write unmapped fields report."""
    report_dir = paths.parsed / "unmapped_fields"
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "artifact_id": artifact_id,
        "stage_id": stage_id,
        "status": "WARN" if fields else "PASS",
        "field_count": len(fields),
        "fields": fields,
    }
    write_json(report_dir / f"{artifact_id}.json", payload)
    refresh_unmapped_fields_summary(paths)
    return payload


def refresh_normalization_summary(paths: RunPaths) -> dict[str, Any]:
    """Handle refresh normalization summary."""
    report_dir = paths.parsed / "normalization_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = []
    for path in sorted(report_dir.glob("*.json")):
        try:
            item = json.loads(read_text(path))
        except (OSError, json.JSONDecodeError):
            continue
        artifact_id = str(item.get("artifact_id", path.stem))
        if path.name != f"{artifact_id}.json":
            continue
        artifacts.append(
            {
                "artifact_id": artifact_id,
                "stage_id": item.get("stage_id", ""),
                "operation_count": int(item.get("operation_count", 0)),
                "changed_paths": item.get("changed_paths", []),
            }
        )
    summary = {
        "total_artifacts": len(artifacts),
        "artifacts_changed": sum(1 for item in artifacts if item["operation_count"]),
        "total_operations": sum(item["operation_count"] for item in artifacts),
        "artifacts": artifacts,
    }
    write_json(paths.parsed / "normalization_summary.json", summary)
    return summary


def write_normalization_report(
    paths: RunPaths,
    *,
    artifact_id: str,
    stage_id: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    """Handle write normalization report."""
    report_dir = paths.parsed / "normalization_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {"artifact_id": artifact_id, "stage_id": stage_id, **report}
    write_json(report_dir / f"{artifact_id}.json", payload)
    refresh_normalization_summary(paths)
    return payload


def append_normalization_operation(
    paths: RunPaths,
    *,
    artifact_id: str,
    stage_id: str,
    operation: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    """Handle append normalization operation."""
    report_path = paths.parsed / "normalization_reports" / f"{artifact_id}.json"
    if report_path.exists():
        try:
            report = json.loads(read_text(report_path))
        except json.JSONDecodeError:
            report = {}
    else:
        report = {}
    changed_paths = sorted(set(_changed_json_paths(before, after)))
    operations = list(report.get("operations", []))
    if changed_paths:
        operations.append({"operation": operation, "changed_paths": changed_paths})
    all_changed_paths = sorted(
        {
            path
            for item in operations
            for path in item.get("changed_paths", [])
        }
    )
    payload = {
        **report,
        "status": "CHANGED" if operations else report.get("status", "UNCHANGED"),
        "before_sha256": report.get("before_sha256")
        or sha256_text(json.dumps(before, ensure_ascii=False, sort_keys=True)),
        "after_sha256": sha256_text(json.dumps(after, ensure_ascii=False, sort_keys=True)),
        "after_projection_sha256": sha256_text(json.dumps(after, ensure_ascii=False, sort_keys=True)),
        "operation_count": len(operations),
        "changed_paths": all_changed_paths,
        "operations": operations,
        "discarded_trace_paths": report.get("discarded_trace_paths", []),
        "discarded_trace_fields": report.get("discarded_trace_fields", []),
    }
    return write_normalization_report(
        paths,
        artifact_id=artifact_id,
        stage_id=stage_id,
        report=payload,
    )


def failed_localization_report(stage_id: str, error: Exception) -> dict[str, Any]:
    """Handle failed localization report."""
    return {
        "stage_id": stage_id,
        "status": "FAIL",
        "translated_key_paths": [],
        "translated_enum_paths": [],
        "english_fallback_paths": [],
        "unknown_key_paths": [],
        "duplicate_equal_paths": [],
        "conflicting_alias_paths": [],
        "parse_error": str(error),
    }


def write_report_only_issue_log(paths: RunPaths, issues: list[dict[str, Any]]) -> None:
    """Handle write report only issue log."""
    existing_path = paths.parsed / "full_run_issue_log.json"
    existing_issues: list[dict[str, Any]] = []
    if existing_path.exists():
        try:
            existing = json.loads(read_text(existing_path))
            if isinstance(existing, dict) and isinstance(existing.get("issues"), list):
                existing_issues = existing["issues"]
        except json.JSONDecodeError:
            existing_issues = []
    merged = existing_issues + issues
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in merged:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    write_json(
        existing_path,
        {
            "run_id": paths.root.name,
            "snapshot_time": datetime.now().isoformat(timespec="seconds"),
            "mode": "report_only_validation",
            "issues": deduped,
        },
    )


def initialize_report_only_issue_log(paths: RunPaths) -> None:
    """Handle initialize report only issue log."""
    write_json(
        paths.parsed / "full_run_issue_log.json",
        {
            "run_id": paths.root.name,
            "snapshot_time": datetime.now().isoformat(timespec="seconds"),
            "mode": "report_only_validation",
            "issues": [],
        },
    )


def normalize_validation_mode(value: str | None) -> str:
    """Handle normalize validation mode."""
    if value in (None, "", VALIDATION_MODE_COLLECT):
        return VALIDATION_MODE_COLLECT
    if value == VALIDATION_MODE_STRICT:
        return VALIDATION_MODE_STRICT
    raise ValueError(f"validation_mode must be one of {sorted(VALIDATION_MODES)}")


def resolve_validation_mode(args: argparse.Namespace) -> str:
    """Handle resolve validation mode."""
    if bool(getattr(args, "strict_validation", False)):
        return VALIDATION_MODE_STRICT
    return normalize_validation_mode(getattr(args, "validation_mode", None))


def validation_mode_from_context(stage_context: dict[str, Any] | None) -> str:
    """Handle validation mode from context."""
    stage_context = stage_context or {}
    if stage_context.get("report_only_validation"):
        return VALIDATION_MODE_COLLECT
    return normalize_validation_mode(stage_context.get("validation_mode"))


def _record_collect_validation_issue(
    *,
    stage_context: dict[str, Any],
    paths: RunPaths | None,
    stage_id: str,
    artifact_id: str | None,
    check_name: str,
    error: Exception,
) -> None:
    """Handle record collect validation issue."""
    issue = {
        "stage": stage_id,
        "artifact_id": artifact_id or stage_id,
        "errors": [{"check": check_name, "error": str(error)}],
    }
    issues = stage_context.get("report_only_issues")
    if isinstance(issues, list):
        issues.append(issue)
    if paths is not None:
        write_report_only_issue_log(paths, [issue])


def _run_stage_semantic_validation(
    *,
    stage_context: dict[str, Any],
    paths: RunPaths | None,
    stage_id: str,
    artifact_id: str | None,
    check_name: str,
    check_fn: Any,
) -> None:
    """Handle run stage semantic validation."""
    try:
        check_fn()
    except Exception as exc:
        if validation_mode_from_context(stage_context) == VALIDATION_MODE_STRICT:
            raise
        _record_collect_validation_issue(
            stage_context=stage_context,
            paths=paths,
            stage_id=stage_id,
            artifact_id=artifact_id,
            check_name=check_name,
            error=exc,
        )


def _require_validation_condition(condition: bool, message: str) -> None:
    """Handle require validation condition."""
    if not condition:
        raise ValueError(message)


def build_manifest_index(paths: RunPaths, *, generated_episodes: list[int]) -> list[str]:
    """Handle build manifest index."""
    generated_episode_nums = {int(item) for item in generated_episodes if str(item).isdigit()}
    entries: list[str] = []
    for path in paths.manifests.glob("*.json"):
        episode_manifest = re.match(r"08_script_body_generation_ep(\d{3})\.manifest\.json$", path.name)
        if episode_manifest and int(episode_manifest.group(1)) not in generated_episode_nums:
            continue
        entries.append(str(path.relative_to(paths.root)))
    return sorted(entries)


def sha256_text(text: str) -> str:
    """Handle sha256 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path: Path | None) -> str:
    """Handle file sha256."""
    if path is None or not path.exists() or not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_json_artifact_sha256(path: Path | None) -> str:
    """Handle clean json artifact sha256."""
    if path is None or not path.exists():
        return ""
    try:
        data = json.loads(read_text(path))
    except (OSError, json.JSONDecodeError):
        return ""
    return sha256_text(json.dumps(data, ensure_ascii=False, sort_keys=True))


def stage_behavior_sha256(stage: dict[str, Any]) -> str:
    """Handle stage behavior sha256."""
    stage_id = str(stage.get("stage_id", ""))
    payload = {
        "stage_id": stage_id,
        "stage_behavior_version": STAGE_BEHAVIOR_VERSIONS.get(stage_id, "base_v1"),
        "stage_config": {key: stage.get(key) for key in ("stage_id", "stage_name", "prompt_file")},
        "parser_sha256": file_sha256(SCRIPT_DIR / "parsers.py"),
        "validator_sha256": file_sha256(SCRIPT_DIR / "validators.py"),
        "stage_contracts_sha256": file_sha256(SCRIPT_DIR / "stage_contracts.py"),
        "prompt_renderer_sha256": file_sha256(SCRIPT_DIR / "prompt_renderer.py"),
        "llm_schema_localization_sha256": file_sha256(SCRIPT_DIR / "llm_schema_localization.py"),
        "continuity_ledger_sha256": (
                file_sha256(SCRIPT_DIR / "continuity_ledger.py") if stage_id == "08_script_body_generation" else ""
            ),
        "episode_generation_context_sha256": (
                (
                    file_sha256(SCRIPT_DIR / "episode_generation_context.py")
                    if stage_id == "08_script_body_generation"
                    else ""
                )
            ),
        "event_transactions_sha256": (
                (
                    file_sha256(SCRIPT_DIR / "event_transactions.py")
                    if stage_id in {"05_plot_character_adaptation", "07_episode_planning", "08_script_body_generation"}
                    else ""
                )
            ),
        "release_preflight_sha256": (
                (
                    file_sha256(SCRIPT_DIR / "release_preflight.py")
                    if stage_id in {"07_episode_planning", "08_script_body_generation"}
                    else ""
                )
            ),
        "season_plan_audit_sha256": (
                (
                    file_sha256(SCRIPT_DIR / "season_plan_audit.py")
                    if stage_id in {"05_plot_character_adaptation", "07_episode_planning"}
                    else ""
                )
            ),
        "dramatic_release_sha256": (
                (
                    file_sha256(SCRIPT_DIR / "dramatic_release.py")
                    if stage_id
                    in {
                        "04b_dramatic_release_map",
                        "05_plot_character_adaptation",
                        "06_script_outline_design",
                        "07_episode_planning",
                        "08_script_body_generation",
                    }
                    else ""
                )
            ),
    }
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def load_stages() -> list[dict[str, Any]]:
    """Handle load stages."""
    return json.loads(read_text(STAGES_PATH))


def stage_map() -> dict[str, dict[str, Any]]:
    """Handle stage map."""
    return {stage["stage_id"]: stage for stage in load_stages()}


def load_run_config(path: str | None) -> dict[str, Any]:
    """Handle load run config."""
    config = json.loads(json.dumps(DEFAULT_RUN_CONFIG, ensure_ascii=False))
    if path:
        loaded = json.loads(read_text(Path(path)))
        for key, value in loaded.items():
            if key == "pacing_controls" and isinstance(value, dict):
                config[key] = {**config.get(key, {}), **value}
            else:
                config[key] = value
    return config


def cli_run_config_overrides(args: argparse.Namespace) -> dict[str, Any]:
    """Handle cli run config overrides."""
    overrides: dict[str, Any] = {}
    scalar_fields = (
        "target_episodes",
        "episode_duration_seconds",
        "rewrite_intensity",
        "character_background_policy",
        "subplot_policy",
        "new_character_policy",
        "source_preservation_level",
    )
    for field in scalar_fields:
        value = getattr(args, field, None)
        if value is not None:
            overrides[field] = int(value) if field in {"target_episodes", "episode_duration_seconds"} else value
    market_tags = getattr(args, "market_tags", None)
    if market_tags:
        overrides["market_tags"] = [item.strip() for item in market_tags.split(",") if item.strip()]
    return overrides


def merge_run_config(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Handle merge run config."""
    config = json.loads(json.dumps(base, ensure_ascii=False))
    for key, value in overlay.items():
        if key == "pacing_controls" and isinstance(value, dict):
            config[key] = {**dict(config.get(key) or {}), **value}
        else:
            config[key] = value
    return config


def build_run_config(
    args: argparse.Namespace,
    *,
    base_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Handle build run config."""
    config = (
        load_run_config(args.run_config)
        if base_config is None
        else merge_run_config(DEFAULT_RUN_CONFIG, base_config)
    )
    config = merge_run_config(config, cli_run_config_overrides(args))
    validators.validate_run_config(config)
    return config


def load_historical_run_config(paths: RunPaths, *, source_sha256: str) -> dict[str, Any] | None:
    """Handle load historical run config."""
    config_path = paths.parsed / "00_run_config.json"
    metadata_path = paths.parsed / "00_source_metadata.json"
    if not config_path.exists() or not metadata_path.exists():
        return None
    try:
        metadata = json.loads(read_text(metadata_path))
        config = json.loads(read_text(config_path))
    except (OSError, json.JSONDecodeError):
        return None
    if str(metadata.get("sha256", "")) != source_sha256:
        return None
    try:
        validators.validate_run_config(config)
    except (TypeError, ValueError):
        return None
    return config


def resolve_global_run_config(
    *,
    args: argparse.Namespace,
    paths: RunPaths,
    stage: dict[str, Any],
    source_text: str,
    source_sha256: str,
    llm_script_path: Path | None,
    allow_history: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Handle resolve global run config."""
    user_overrides = cli_run_config_overrides(args)
    recommendation_adjustments: list[dict[str, Any]] = []
    if getattr(args, "run_config", None) or user_overrides:
        config = build_run_config(args)
        source = "user_config" if getattr(args, "run_config", None) else "user_overrides"
        recommendation_artifact = None
    else:
        historical = load_historical_run_config(paths, source_sha256=source_sha256) if allow_history else None
        if historical is not None:
            config = build_run_config(args, base_config=historical)
            source = "history"
            recommendation_artifact = None
        else:
            recommendation_artifact = call_stage(
                paths,
                stage,
                {
                    "target_episodes": int(user_overrides.get("target_episodes", DEFAULT_TARGET_EPISODES)),
                    "default_run_config": DEFAULT_RUN_CONFIG,
                    "user_overrides": user_overrides,
                    "source_text": source_text,
                },
                dry_run=bool(args.dry_run),
                llm_script_path=llm_script_path,
                timeout=int(args.timeout),
                force_reuse=False,
            )
            validate_stage_output(
                "00a_global_config",
                recommendation_artifact,
                target_episodes=int(user_overrides.get("target_episodes", DEFAULT_TARGET_EPISODES)),
                paths=paths,
                artifact_id="00a_global_config",
            )
            recommended_config = dict(recommendation_artifact["recommended_run_config"])
            if int(recommended_config.get("target_episodes", 0)) != DEFAULT_TARGET_EPISODES:
                recommendation_adjustments.append(
                    {
                        "field": "target_episodes",
                        "recommended_value": recommended_config.get("target_episodes"),
                        "resolved_value": DEFAULT_TARGET_EPISODES,
                        "reason": "system_default_locked_without_user_or_history_config",
                    }
                )
            recommended_config["target_episodes"] = DEFAULT_TARGET_EPISODES
            config = build_run_config(
                args,
                base_config=recommended_config,
            )
            source = "dry_run_recommendation" if args.dry_run else "llm_recommendation"
    resolution = {
        "source": source,
        "model_called": recommendation_artifact is not None and not bool(args.dry_run),
        "novel_sha256": source_sha256,
        "user_overrides": user_overrides,
        "system_locked_values": (
                {"target_episodes": DEFAULT_TARGET_EPISODES} if recommendation_artifact is not None else {}
            ),
        "recommendation_adjustments": recommendation_adjustments,
        "resolved_run_config": config,
        "recommendation_artifact": (
                "outputs/00a_global_config.clean.json" if recommendation_artifact is not None else ""
            ),
    }
    write_json(paths.parsed / "00a_global_config_resolution.json", resolution)
    return config, resolution


def derive_run_config(config: dict[str, Any]) -> dict[str, Any]:
    """Handle derive run config."""
    target = int(config["target_episodes"])
    duration = int(config["episode_duration_seconds"])
    rewrite_intensity = str(config["rewrite_intensity"])
    subplot_policy = str(config["subplot_policy"])
    new_character_policy = str(config["new_character_policy"])
    block_count = validators.expected_block_count_for_target(target)
    scene_ranges = {
        60: {"scenes_per_episode": "1-3", "script_length_chars": "450-800"},
        90: {"scenes_per_episode": "2-4", "script_length_chars": "650-780"},
        120: {"scenes_per_episode": "3-5", "script_length_chars": "700-800"},
    }
    def event_pool_size() -> str:
        """Handle event pool size."""
        if rewrite_intensity == "light":
            low, high = max(14, round(target * 0.35)), min(32, max(20, round(target * 0.50)))
        elif rewrite_intensity == "heavy":
            low, high = max(24, round(target * 0.50)), min(48, max(34, round(target * 0.70)))
        elif target <= 45:
            low, high = 12, 16
        else:
            low, high = max(18, round(target * 0.45)), min(40, max(26, round(target * 0.60)))
        if low > high:
            low = max(1, high - 4)
        return f"{low}-{high}"

    intensity_settings = {
        "light": {
                "event_pool_size": event_pool_size(),
                "foreshadowing_density": "low",
                "source_retention_ratio": "70-80%",
            },
        "balanced": {
                "event_pool_size": event_pool_size(),
                "foreshadowing_density": "medium",
                "source_retention_ratio": "50-65%",
            },
        "heavy": {
                "event_pool_size": event_pool_size(),
                "foreshadowing_density": "high",
                "source_retention_ratio": "35-50%",
            },
    }
    subplot_budget = {"none": 0, "moderate": max(2, block_count // 2), "aggressive": block_count}
    new_character_budget = {"limited": 3, "controlled": 6, "open": 10}
    pacing_controls = {**validators.DEFAULT_PACING_CONTROLS, **dict(config.get("pacing_controls") or {})}
    climax_window = pacing_controls.get("major_climax_window")
    if climax_window == "auto":
        end = max(1, target - 1)
        width = max(4, round(target * 0.08))
        start = max(1, end - width + 1)
        climax_window = f"{start}-{end}"
    return {
        "block_count": block_count,
        "episodes_per_block": f"{target // block_count}-{(target + block_count - 1) // block_count}",
        "subplot_budget": subplot_budget[subplot_policy],
        "new_character_budget": new_character_budget[new_character_policy],
        "epilogue_max_episodes": pacing_controls["epilogue_max_episodes"],
        "event_reuse_max_episodes": pacing_controls["event_reuse_max_episodes"],
        "conflict_mode_streak_limit": pacing_controls["conflict_mode_streak_limit"],
        "major_climax_window": climax_window,
        "cross_block_bridge_max_episodes": pacing_controls["cross_block_bridge_max_episodes"],
        **scene_ranges[duration],
        **intensity_settings[rewrite_intensity],
    }


def base_prompt_values(run_config: dict[str, Any], derived_config: dict[str, Any]) -> dict[str, Any]:
    """Handle base prompt values."""
    return {
        "run_config": run_config,
        "derived_config": derived_config,
        "target_episodes": int(run_config["target_episodes"]),
    }


def build_canonical_story_lock(
    *,
    source_plot_points: list[dict[str, Any]],
    character_bible: list[dict[str, Any]],
    novel_summary: dict[str, Any],
    adaptation_direction: dict[str, Any],
    plot_extract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Handle build canonical story lock."""
    plot_extract = plot_extract or {}
    character_names = [
        str(item.get("name", "")).strip()
        for item in character_bible
        if str(item.get("name", "")).strip()
    ]
    for point in source_plot_points:
        for name in point.get("characters", []):
            clean_name = str(name).strip()
            if clean_name and clean_name not in character_names:
                character_names.append(clean_name)
    protagonist = ""
    for item in character_bible:
        role = str(item.get("role", ""))
        name = str(item.get("name", "")).strip()
        if name and ("主角" in role or "女主" in role):
            protagonist = name
            break
    if not protagonist and character_names:
        protagonist = character_names[0]
    return {
        "protagonist": protagonist,
        "character_names": character_names,
        "source_plot_points": [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "event": item.get("event"),
                "function": item.get("function"),
                "characters": item.get("characters", []),
            }
            for item in source_plot_points
        ],
        "source_fact_ledger": plot_extract.get("source_fact_ledger", []),
        "immutable_elements": novel_summary.get("immutable_elements", []),
        "emotional_debt_chain": plot_extract.get("emotional_debt_chain", novel_summary.get("emotional_debts", [])),
        "character_action_boundaries": plot_extract.get("character_action_boundaries", []),
        "must_keep": adaptation_direction.get("must_keep", []),
        "source_preservation_contract": adaptation_direction.get("source_preservation_contract", {}),
        "protagonist_action_boundary": adaptation_direction.get("protagonist_action_boundary", {}),
        "event_release_principles": adaptation_direction.get("event_release_principles", []),
        "epilogue_budget": adaptation_direction.get("epilogue_budget", {}),
        "forbidden_changes": adaptation_direction.get("forbidden_changes", [])
        + [
            "不得更换主要人物姓名",
            "不得替换源故事首战破局方式，只能在原事件基础上压缩或强化",
            "不得把源故事情绪债改写成无关的新事故",
        ],
        "naming_rule": "正文和分集卡必须使用character_names中的原始姓名；新增人物不得替换原人物功能。",
    }


def collect_allowed_character_names(
    canonical_story_lock: dict[str, Any],
    expanded_character_network: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Handle collect allowed character names."""
    names: list[str] = []
    for name in canonical_story_lock.get("character_names", []):
        clean = str(name).strip()
        if clean and clean not in names:
            names.append(clean)
    for item in expanded_character_network or []:
        clean = str(item.get("name", "")).strip()
        if clean and clean not in names:
            names.append(clean)
    return names


def _clip_planning_text(value: Any, limit: int = PLANNING_TEXT_CLIP_CHARS) -> str:
    """Handle clip planning text."""
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _compact_planning_value(
    value: Any,
    *,
    text_limit: int = PLANNING_TEXT_CLIP_CHARS,
    list_limit: int | None = None,
) -> Any:
    """Handle compact planning value."""
    if isinstance(value, str):
        return _clip_planning_text(value, text_limit)
    if isinstance(value, list):
        items = value if list_limit is None else value[:list_limit]
        return [_compact_planning_value(item, text_limit=text_limit) for item in items]
    if isinstance(value, dict):
        return {key: _compact_planning_value(item, text_limit=text_limit) for key, item in value.items()}
    return value


def _compact_dict_keys(
    item: dict[str, Any],
    keys: list[str],
    *,
    text_limit: int = PLANNING_TEXT_CLIP_CHARS,
) -> dict[str, Any]:
    """Handle compact dict keys."""
    return {
        key: _compact_planning_value(item[key], text_limit=text_limit)
        for key in keys
        if key in item
    }


def compact_source_plot_points_for_planning(source_plot_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle compact source plot points for planning."""
    keys = ["id", "title", "event", "function", "characters", "source_fact_ids"]
    return [_compact_dict_keys(item, keys) for item in source_plot_points if isinstance(item, dict)]


def compact_canonical_story_lock_for_planning(canonical_story_lock: dict[str, Any]) -> dict[str, Any]:
    """Handle compact canonical story lock for planning."""
    keys = [
        "protagonist",
        "character_names",
        "emotional_debt_chain",
        "must_keep",
        "source_preservation_contract",
        "source_fact_ledger",
        "protagonist_action_boundary",
        "epilogue_budget",
        "forbidden_changes",
        "naming_rule",
    ]
    compact = _compact_dict_keys(canonical_story_lock, keys)
    compact["source_plot_points"] = compact_source_plot_points_for_planning(
        canonical_story_lock.get("source_plot_points", [])
    )
    return compact


def compact_event_pool_for_planning(event_pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle compact event pool for planning."""
    keys = [
        "id",
        "title",
        "function",
        "source_plot_point_ids",
        "expansion_type",
        "target_block",
        "episode_window",
        "expected_episode_span",
        "importance_level",
        "conflict_mode",
        "pattern_family",
        "source_anchor",
        "delta_from_source",
        "legal_moral_risk",
        "content_sensitivity_risk",
        "child_beats",
        "source_fact_ids",
        "dramatic_delta",
    ]
    compact_events: list[dict[str, Any]] = []
    for event in event_pool:
        if not isinstance(event, dict):
            continue
        compact = _compact_dict_keys(event, keys)
        compact_events.append(compact)
    return compact_events


def normalize_event_child_beats(data: dict[str, Any]) -> dict[str, Any]:
    """Preserve model semantics; only wrap legacy string beats for diagnostics."""

    events = data.get("event_pool")
    if not isinstance(events, list):
        return data
    normalized_events: list[Any] = []
    changed = False
    for raw_event in events:
        if not isinstance(raw_event, dict):
            normalized_events.append(raw_event)
            continue
        event = dict(raw_event)
        event_id = str(event.get("id", "")).strip() or "UNKNOWN"
        child_beats: list[Any] = []
        for index, raw_beat in enumerate(event.get("child_beats", []) or [], start=1):
            canonical_id = f"E{event_id}-B{index}"
            if isinstance(raw_beat, dict):
                beat = dict(raw_beat)
            else:
                action = str(raw_beat or "").strip()
                beat = {
                    "child_beat_id": canonical_id,
                    "action": action,
                    "completion_evidence": "",
                }
            if beat != raw_beat:
                changed = True
            child_beats.append(beat)
        event["child_beats"] = child_beats
        normalized_events.append(event)
    if not changed:
        return data
    output = dict(data)
    output["event_pool"] = normalized_events
    return output


def _event_child_beat_lookup(
    event_pool: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    """Handle event child beat lookup."""
    by_id: dict[str, dict[str, Any]] = {}
    ids_by_action: dict[str, list[str]] = {}
    for event in event_pool:
        if not isinstance(event, dict):
            continue
        for beat in event.get("child_beats", []) or []:
            if not isinstance(beat, dict):
                continue
            beat_id = str(beat.get("child_beat_id", "")).strip()
            action = str(beat.get("action", "")).strip()
            if not beat_id:
                continue
            by_id[beat_id] = {**beat, "event_id": event.get("id")}
            if action:
                ids_by_action.setdefault(re.sub(r"\s+", "", action), []).append(beat_id)
    return by_id, ids_by_action


def normalize_episode_child_beat_references(
    data: dict[str, Any],
    *,
    event_pool: list[dict[str, Any]],
) -> dict[str, Any]:
    """Handle normalize episode child beat references."""
    episodes = data.get("episode_outlines")
    if not isinstance(episodes, list):
        return data
    beat_by_id, ids_by_action = _event_child_beat_lookup(event_pool)
    normalized: list[Any] = []
    changed = False
    for raw_episode in episodes:
        if not isinstance(raw_episode, dict):
            normalized.append(raw_episode)
            continue
        episode = dict(raw_episode)
        legacy_texts = [
            str(item).strip()
            for item in episode.get("consumed_child_beats", []) or []
            if str(item).strip()
        ]
        ids = [str(item).strip() for item in episode.get("consumed_child_beat_ids", []) or [] if str(item).strip()]
        if not ids:
            for raw_text in legacy_texts:
                matches = ids_by_action.get(re.sub(r"\s+", "", str(raw_text or "").strip()), [])
                if len(matches) == 1 and matches[0] not in ids:
                    ids.append(matches[0])
        texts = (
            (
                (
                    [str(beat_by_id[item].get("action", "")).strip() for item in ids if item in beat_by_id]
                    if ids
                    else legacy_texts
                )
            )
        )
        if episode.get("consumed_child_beat_ids") != ids:
            episode["consumed_child_beat_ids"] = ids
            changed = True
        if episode.get("consumed_child_beats") != texts:
            episode["consumed_child_beats"] = texts
            changed = True
        normalized.append(episode)
    if not changed:
        return data
    output = dict(data)
    output["episode_outlines"] = normalized
    return output


def align_episode_target_script_density_ids(
    data: dict[str, Any],
    *,
    event_pool: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Handle align episode target script density ids."""
    del event_pool
    episodes = data.get("episode_outlines")
    if not isinstance(episodes, list):
        return data
    normalized: list[Any] = []
    changed = False
    for raw_episode in episodes:
        if not isinstance(raw_episode, dict):
            normalized.append(raw_episode)
            continue
        planned_ids = [
            str(item).strip()
            for item in raw_episode.get("consumed_child_beat_ids", []) or []
            if str(item).strip()
        ]
        density = raw_episode.get("target_script_density")
        beats = density.get("must_cover_beats") if isinstance(density, dict) else None
        if not planned_ids or not isinstance(density, dict) or not isinstance(beats, list):
            normalized.append(raw_episode)
            continue
        next_beats = [{"beat_id": planned_id} for planned_id in planned_ids]

        next_budgets = [
            {
                **raw_budget,
                "must_cover_beat_ids": [],
            }
            for raw_budget in density.get("scene_char_budgets", []) or []
            if isinstance(raw_budget, dict)
        ]
        if next_budgets:
            for index, planned_id in enumerate(planned_ids):
                budget_index = min(
                    len(next_budgets) - 1,
                    (index * len(next_budgets)) // len(planned_ids),
                )
                next_budgets[budget_index]["must_cover_beat_ids"].append(planned_id)

        next_density = dict(density)
        next_density["must_cover_beats"] = next_beats
        next_density["scene_char_budgets"] = next_budgets
        if next_density == density:
            normalized.append(raw_episode)
            continue
        next_episode = dict(raw_episode)
        next_episode["target_script_density"] = next_density
        normalized.append(next_episode)
        changed = True
    if not changed:
        return data
    output = dict(data)
    output["episode_outlines"] = normalized
    return output


def compact_character_network_for_planning(network: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle compact character network for planning."""
    keys = ["name", "camp", "function", "relationship_pressure"]
    return [_compact_dict_keys(item, keys) for item in network if isinstance(item, dict)]


def compact_foreshadowing_pool_for_planning(foreshadowing_pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle compact foreshadowing pool for planning."""
    keys = ["id", "setup", "mislead", "payoff", "related_arc"]
    return [_compact_dict_keys(item, keys) for item in foreshadowing_pool if isinstance(item, dict)]


def build_episode_planning_values(
    *,
    prompt_context: dict[str, Any],
    stage_outputs: dict[str, dict[str, Any]],
    canonical_story_lock: dict[str, Any],
    target_episodes: int,
    transaction_schedule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Handle build episode planning values."""
    event_pool = stage_outputs["05_plot_character_adaptation"]["event_pool"]
    schedule = transaction_schedule or event_transactions.build_transaction_schedule(
        event_pool,
        target_episodes=target_episodes,
        prop_registry=stage_outputs["05_plot_character_adaptation"].get("prop_registry", []),
    )
    return {
        **prompt_context,
        "global_outline": stage_outputs["06_script_outline_design"]["global_outline"],
        "longform_blocks": stage_outputs["06_script_outline_design"]["longform_blocks"],
        "phase_breakdown": stage_outputs["06_script_outline_design"]["phase_breakdown"],
        "episode_budget": stage_outputs["06_script_outline_design"]["episode_budget"],
        "event_release_schedule": stage_outputs["06_script_outline_design"]["event_release_schedule"],
        "block_event_plan": stage_outputs["06_script_outline_design"]["block_event_plan"],
        "climax_guardrails": stage_outputs["06_script_outline_design"]["climax_guardrails"],
        "block_state_plan": stage_outputs["06_script_outline_design"]["block_state_plan"],
        "qa_rules": stage_outputs["06_script_outline_design"]["qa_rules"],
        "conflict_engine": _compact_planning_value(
            stage_outputs["05_plot_character_adaptation"]["conflict_engine"]
        ),
        "expanded_character_network": compact_character_network_for_planning(
            stage_outputs["05_plot_character_adaptation"]["expanded_character_network"]
        ),
        "event_pool": compact_event_pool_for_planning(event_pool),
        "_full_event_pool_for_repair": event_pool,
        "transaction_schedule": schedule,
        "episode_event_options": event_transactions.episode_event_options(schedule),
        "foreshadowing_pool": compact_foreshadowing_pool_for_planning(
            stage_outputs["05_plot_character_adaptation"]["foreshadowing_pool"]
        ),
        "source_plot_points": compact_source_plot_points_for_planning(
            stage_outputs["03_plot_character_extract"]["source_plot_points"]
        ),
        "source_fact_ledger": _compact_planning_value(
            stage_outputs["03_plot_character_extract"].get("source_fact_ledger", [])
        ),
        "prop_registry": _compact_planning_value(
            schedule.get(
                "prop_activation_registry",
                stage_outputs["05_plot_character_adaptation"].get("prop_registry", []),
            )
        ),
        "adaptation_capacity": _compact_planning_value(
            stage_outputs.get("02_storyline_understanding", {}).get("adaptation_capacity", {})
        ),
        "canonical_story_lock": compact_canonical_story_lock_for_planning(canonical_story_lock),
    }


def _clip_text_head(text: Any, limit: int) -> str:
    """Handle clip text head."""
    value = str(text or "").strip()
    return value[:limit]


def _clip_text_tail(text: Any, limit: int) -> str:
    """Handle clip text tail."""
    value = str(text or "").strip()
    return value[-limit:] if len(value) > limit else value


def _completed_beats_from_episode(episode: dict[str, Any], output: dict[str, Any]) -> list[str]:
    """Handle completed beats from episode."""
    beats: list[str] = []
    for key in ("opening_beat", "closing_beat", "ending_hook", "counterattack", "information_gain"):
        value = str(episode.get(key, "")).strip()
        if value and value not in beats:
            beats.append(value)
    for item in episode.get("consumed_child_beats", []) or []:
        value = str(item).strip()
        if value and value not in beats:
            beats.append(value)
    update = output.get("continuity_update", {}) if isinstance(output, dict) else {}
    for item in update.get("completed_beats", []) or []:
        value = str(item).strip()
        if value and value not in beats:
            beats.append(value)
    for key in ("source_anchor_executed", "conflict_mode_used"):
        value = str(update.get(key, "")).strip()
        if value and value not in beats:
            beats.append(value)
    return beats


def build_previous_episode_context(
    *,
    episode: dict[str, Any],
    output: dict[str, Any],
    head_chars: int = PREVIOUS_CONTEXT_HEAD_CHARS,
    tail_chars: int = PREVIOUS_CONTEXT_TAIL_CHARS,
) -> dict[str, Any]:
    """Handle build previous episode context."""
    script = str(output.get("final_script", ""))
    continuity_update = (
        output.get("continuity_update", {}) if isinstance(output.get("continuity_update", {}), dict) else {}
    )
    return {
        "last_episode_num": episode.get("episode_num"),
        "last_episode_title": episode.get("title", ""),
        "previous_ending_hook": episode.get("ending_hook", ""),
        "last_script_head": _clip_text_head(script, head_chars),
        "last_script_tail": _clip_text_tail(script, tail_chars),
        "previous_next_bridge": continuity_update.get("next_episode_bridge", ""),
        "previous_source_anchor_executed": continuity_update.get("source_anchor_executed", ""),
        "last_scene_state": continuity_update.get("last_scene_state", {}),
        "already_completed_beats": _completed_beats_from_episode(episode, output),
        "opening_priority": "从 last_script_tail 和 previous_next_bridge 的后一拍继续，不重复 last_script_head 已完成动作。",
    }


def merge_continuity_ledger(
    ledger: dict[str, Any],
    *,
    episode: dict[str, Any],
    output: dict[str, Any],
) -> dict[str, Any]:
    """Handle merge continuity ledger."""
    update = output.get("continuity_update", {})
    next_ledger = json.loads(json.dumps(ledger, ensure_ascii=False))
    next_ledger.setdefault("generated_episode_summaries", []).append(
        {
            "episode_num": episode.get("episode_num"),
            "title": episode.get("title"),
            "ending_hook": episode.get("ending_hook"),
            "state_update": output.get("state_update", {}),
            "script_preview": _clip_text_head(output.get("final_script", ""), LEDGER_SCRIPT_EXCERPT_CHARS),
            "script_tail": _clip_text_tail(output.get("final_script", ""), LEDGER_SCRIPT_EXCERPT_CHARS),
            "next_episode_bridge": update.get("next_episode_bridge", ""),
            "last_scene_state": update.get("last_scene_state", {}),
            "completed_beats": _completed_beats_from_episode(episode, output),
        }
    )
    for key in ("audience_known", "writer_private"):
        values = next_ledger.setdefault(key, [])
        for item in update.get(key, []):
            if item not in values:
                values.append(item)
    character_known = next_ledger.setdefault("character_known", {})
    for name, items in update.get("character_known", {}).items():
        name_values = character_known.setdefault(name, [])
        if isinstance(items, list):
            for item in items:
                if item not in name_values:
                    name_values.append(item)
    foreshadowing_by_id: dict[str, Any] = {}
    for item in next_ledger.get("foreshadowing_status", []):
        if isinstance(item, dict) and "id" in item:
            foreshadowing_by_id[str(item["id"])] = item
    for item in update.get("foreshadowing_status", []):
        if isinstance(item, dict) and "id" in item:
            foreshadowing_by_id[str(item["id"])] = item
    next_ledger["foreshadowing_status"] = list(foreshadowing_by_id.values())
    prop_positions = next_ledger.setdefault("prop_positions", {})
    if not isinstance(prop_positions, dict):
        prop_positions = {}
    prop_identity_conflicts = next_ledger.setdefault("prop_identity_conflicts", [])
    if not isinstance(prop_identity_conflicts, list):
        prop_identity_conflicts = []
    for item in update.get("prop_state_updates", []) or []:
        if not isinstance(item, dict):
            continue
        prop_id = str(item.get("prop_id", "")).strip()
        if not prop_id:
            continue
        existing = prop_positions.get(prop_id)
        existing_name = str(existing.get("prop_name", "")).strip() if isinstance(existing, dict) else ""
        incoming_name = str(item.get("prop_name", "")).strip()
        if existing_name and incoming_name and existing_name != incoming_name:
            conflict = {
                "prop_id": prop_id,
                "existing_prop_name": existing_name,
                "incoming_prop_name": incoming_name,
                "conflict_episode_num": episode.get("episode_num"),
            }
            if conflict not in prop_identity_conflicts:
                prop_identity_conflicts.append(conflict)
            continue
        prop_positions[prop_id] = {
            "prop_name": item.get("prop_name", ""),
            "holder": item.get("holder", ""),
            "location": item.get("location", ""),
            "status": item.get("status", ""),
            "updated_episode": episode.get("episode_num"),
            "evidence": item.get("change_evidence", ""),
        }
    next_ledger["prop_positions"] = prop_positions
    next_ledger["prop_identity_conflicts"] = prop_identity_conflicts
    next_ledger["next_episode_bridge"] = update.get("next_episode_bridge", "")
    next_ledger["last_scene_state"] = update.get("last_scene_state", {})
    return next_ledger


def _compact_ledger_text(value: Any, *, limit: int = COMPACT_LEDGER_TEXT_CLIP_CHARS) -> Any:
    """Handle compact ledger text."""
    if isinstance(value, str):
        return _clip_text_head(value, limit)
    if isinstance(value, list):
        return [_compact_ledger_text(item, limit=limit) for item in value]
    if isinstance(value, dict):
        return {str(key): _compact_ledger_text(item, limit=limit) for key, item in value.items()}
    return value


def compact_continuity_context(
    ledger: dict[str, Any],
    *,
    recent_episode_count: int = COMPACT_LEDGER_RECENT_EPISODE_COUNT,
) -> dict[str, Any]:
    """Handle compact continuity context."""
    summaries = ledger.get("generated_episode_summaries", [])
    if not isinstance(summaries, list):
        summaries = []
    recent = summaries[-max(0, recent_episode_count):] if recent_episode_count else []
    older = summaries[: max(0, len(summaries) - len(recent))]
    completed_digest: list[dict[str, Any]] = []
    for item in older:
        if not isinstance(item, dict):
            continue
        beats = item.get("completed_beats", [])
        completed_digest.append(
            {
                "episode_num": item.get("episode_num"),
                "title": _compact_ledger_text(item.get("title", ""), limit=48),
                "completed_beats": _compact_ledger_text(beats[:3] if isinstance(beats, list) else beats, limit=72),
                "next_episode_bridge": _compact_ledger_text(item.get("next_episode_bridge", ""), limit=96),
            }
        )
    recent_summaries: list[dict[str, Any]] = []
    for item in recent:
        if not isinstance(item, dict):
            continue
        recent_summaries.append(
            {
                "episode_num": item.get("episode_num"),
                "title": _compact_ledger_text(item.get("title", ""), limit=60),
                "ending_hook": _compact_ledger_text(item.get("ending_hook", ""), limit=120),
                "state_update": _compact_ledger_text(item.get("state_update", {}), limit=120),
                "script_tail": _compact_ledger_text(item.get("script_tail", ""), limit=COMPACT_LEDGER_TEXT_CLIP_CHARS),
                "next_episode_bridge": _compact_ledger_text(item.get("next_episode_bridge", ""), limit=120),
                "completed_beats": _compact_ledger_text(item.get("completed_beats", []), limit=90),
            }
        )
    return {
        "audience_known": _compact_ledger_text(ledger.get("audience_known", []), limit=96),
        "character_known": _compact_ledger_text(ledger.get("character_known", {}), limit=96),
        "writer_private": _compact_ledger_text(ledger.get("writer_private", []), limit=96),
        "foreshadowing_status": _compact_ledger_text(ledger.get("foreshadowing_status", []), limit=120),
        "open_threads": _compact_ledger_text(ledger.get("open_threads", []), limit=120),
        "prop_positions": _compact_ledger_text(ledger.get("prop_positions", {}), limit=96),
        "prop_identity_conflicts": _compact_ledger_text(ledger.get("prop_identity_conflicts", []), limit=96),
        "next_episode_bridge": _compact_ledger_text(ledger.get("next_episode_bridge", ""), limit=160),
        "last_scene_state": _compact_ledger_text(ledger.get("last_scene_state", {}), limit=160),
        "recent_episode_summaries": recent_summaries,
        "completed_beats_digest": completed_digest[-20:],
        "compaction_policy": {
            "recent_episode_detail_count": recent_episode_count,
            "older_episode_detail": "只保留 completed_beats_digest，不传旧集 script_preview/script_tail 全量明细。",
        },
    }


def _find_block_state_plan(block_state_plan: list[dict[str, Any]], block_id: Any) -> dict[str, Any]:
    """Handle find block state plan."""
    for item in block_state_plan:
        if str(item.get("block_id")) == str(block_id):
            return item
    return {}


def create_run_paths(runs_dir: Path, run_id: str) -> RunPaths:
    """Handle create run paths."""
    root = runs_dir / run_id
    paths = RunPaths(
        root=root,
        prompts=root / "prompts",
        outputs=root / "outputs",
        parsed=root / "parsed",
        logs=root / "logs",
        manifests=root / "manifests",
        final=root / "final",
        attempts=root / "attempts",
    )
    for directory in (
        paths.prompts,
        paths.outputs,
        paths.parsed,
        paths.logs,
        paths.manifests,
        paths.final,
        paths.attempts,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return paths


def split_chapters(text: str) -> list[dict[str, Any]]:
    """Handle split chapters."""
    pattern = re.compile(r"(?m)^#{0,6}\s*第\s*([0-9一二三四五六七八九十百零〇]+)\s*章.*?#{0,6}\s*$")
    matches = list(pattern.finditer(text))
    if not matches:
        return [{"chapter_id": 1, "title": "全文", "content": text.strip()}]
    chapters: list[dict[str, Any]] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        chapters.append(
            {
                "chapter_id": idx + 1,
                "title": match.group(0).strip("# \t"),
                "content": text[start:end].strip(),
            }
        )
    return chapters


def build_source_anchors(text: str) -> list[dict[str, Any]]:
    """Handle build source anchors."""
    anchors: list[dict[str, Any]] = []
    paragraph_pattern = re.compile(r"\S(?:.*?\S)?(?=\n[ \t]*\n|\Z)", flags=re.S)
    for index, match in enumerate(paragraph_pattern.finditer(text), start=1):
        paragraph = match.group(0).strip()
        if not paragraph:
            continue
        anchors.append(
            {
                "source_anchor_id": f"SRC_P{index:04d}",
                "start_char": match.start(),
                "end_char": match.end(),
                "text": paragraph,
            }
        )
    return anchors


def render_anchored_source(anchors: list[dict[str, Any]]) -> str:
    """Handle render anchored source."""
    return "\n\n".join(f"[{item['source_anchor_id']}]\n{item['text']}" for item in anchors)


def compact_chapter_chunks(chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle compact chapter chunks."""
    chunks = []
    for chapter in chapters:
        content = str(chapter["content"])
        chunks.append(
            {
                "chapter_id": chapter["chapter_id"],
                "title": chapter["title"],
                "char_count": len(content),
                "preview": content[:220],
            }
        )
    return chunks


def localization_status_for_manifest(path: Path, artifact_id: str) -> str:
    """Handle localization status for manifest."""
    report_path = path.parent.parent / "parsed" / "localization_reports" / f"{artifact_id}.json"
    if not report_path.exists():
        return "NOT_APPLICABLE"
    try:
        report = json.loads(read_text(report_path))
    except (OSError, json.JSONDecodeError):
        return "FAIL"
    return str(report.get("status", "FAIL"))


def write_manifest(
    path: Path,
    *,
    stage: dict[str, Any],
    artifact_id: str,
    values: dict[str, Any],
    prompt: str,
    output_hash: str,
    dry_run: bool,
    llm_script: str,
    llm_runtime_options: dict[str, str] | None = None,
) -> None:
    """Handle write manifest."""
    manifest = {
        "stage_id": stage["stage_id"],
        "artifact_id": artifact_id,
        "stage_name": stage["stage_name"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "prompt_template": stage.get("prompt_file", ""),
        "prompt_sha256": sha256_text(prompt),
        "prompt_chars": len(prompt),
        "input_keys": sorted(values.keys()),
        "input_value_hashes": {key: sha256_text(prompt_renderer.stringify(value)) for key, value in values.items()},
        "stage_behavior_sha256": stage_behavior_sha256(stage),
        "prompt_schema_locale": "zh-CN",
        "localization_version": llm_schema_localization.LOCALIZATION_VERSION,
        "localization_status": localization_status_for_manifest(path, artifact_id),
        "llm_runtime_options": llm_runtime_options or {},
        "output_sha256": output_hash,
        "dry_run": dry_run,
        "llm_script": llm_script,
        "llm_script_sha256": file_sha256(Path(llm_script)) if llm_script else "",
    }
    write_json(path, manifest)


def _prompt_section_chars(prompt: str, heading: str) -> int:
    """Handle prompt section chars."""
    marker = f"## {heading}"
    start = prompt.find(marker)
    if start < 0:
        return 0
    next_match = re.search(r"\n## ", prompt[start + len(marker):])
    end = start + len(marker) + next_match.start() if next_match else len(prompt)
    return end - start


def measure_08_prompt_sections(prompt: str) -> dict[str, int]:
    """Handle measure 08 prompt sections."""
    return {
        "prompt_chars": len(prompt),
        "continuity_context_chars": max(
            _prompt_section_chars(prompt, "压缩连续性上下文"),
            _prompt_section_chars(prompt, "累积连续性账本"),
        ),
        "remaining_episode_plan_chars": _prompt_section_chars(prompt, "剩余分集计划摘要"),
    }


def update_manifest_for_deterministic_repair(
    path: Path,
    *,
    stage: dict[str, Any],
    output_hash: str,
    repair_info: dict[str, Any],
) -> None:
    """Handle update manifest for deterministic repair."""
    try:
        manifest = json.loads(read_text(path)) if path.exists() else {}
    except json.JSONDecodeError:
        manifest = {}
    repairs = list(manifest.get("deterministic_repairs", []))
    repairs.append(repair_info)
    manifest.update(
        {
            "stage_behavior_sha256": stage_behavior_sha256(stage),
            "output_sha256": output_hash,
            "deterministic_repairs": repairs,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    write_json(path, manifest)


def cached_artifact_matches(
    manifest: dict[str, Any],
    *,
    dry_run: bool,
    prompt: str,
    values: dict[str, Any],
    llm_script_path: Path | None,
    stage: dict[str, Any],
    output_path: Path | None = None,
) -> bool:
    """Handle cached artifact matches."""
    if bool(manifest.get("dry_run")) != bool(dry_run):
        return False
    if manifest.get("prompt_sha256") != sha256_text(prompt):
        return False
    expected_inputs = {key: sha256_text(prompt_renderer.stringify(value)) for key, value in values.items()}
    if manifest.get("input_value_hashes") != expected_inputs:
        return False
    if manifest.get("stage_behavior_sha256") != stage_behavior_sha256(stage):
        return False
    if manifest.get("llm_runtime_options") != llm_client.llm_runtime_options(
        llm_script_path, stage_id=stage["stage_id"]
    ):
        return False
    if not dry_run:
        if manifest.get("llm_script", "") != str(llm_script_path or ""):
            return False
        if manifest.get("llm_script_sha256", "") != file_sha256(llm_script_path):
            return False
    if output_path is not None and manifest.get("output_sha256") != clean_json_artifact_sha256(output_path):
        return False
    return True


def normalize_episode_scene_plan_times(data: dict[str, Any]) -> dict[str, Any]:
    """Handle normalize episode scene plan times."""
    episodes = data.get("episode_outlines")
    if not isinstance(episodes, list):
        return data
    changed = False
    normalized_episodes: list[Any] = []
    for episode in episodes:
        if not isinstance(episode, dict):
            normalized_episodes.append(episode)
            continue
        scene_plan = episode.get("scene_plan")
        if not isinstance(scene_plan, list):
            normalized_episodes.append(episode)
            continue
        normalized_plan: list[Any] = []
        episode_changed = False
        for item in scene_plan:
            if not isinstance(item, dict):
                normalized_plan.append(item)
                continue
            normalized_time = parsers.normalize_scene_time_token(item.get("time"))
            if normalized_time and normalized_time != item.get("time"):
                next_item = dict(item)
                next_item["time"] = normalized_time
                normalized_plan.append(next_item)
                episode_changed = True
            else:
                normalized_plan.append(item)
        if episode_changed:
            next_episode = dict(episode)
            next_episode["scene_plan"] = normalized_plan
            normalized_episodes.append(next_episode)
            changed = True
        else:
            normalized_episodes.append(episode)
    if not changed:
        return data
    normalized = dict(data)
    normalized["episode_outlines"] = normalized_episodes
    return normalized


def _scene_plan_cast_key(item: dict[str, Any]) -> tuple[str, ...]:
    """Handle scene plan cast key."""
    names = item.get("appearing_character_names")
    if not isinstance(names, list):
        return tuple()
    return tuple(sorted(str(name).strip() for name in names if str(name).strip()))


def _scene_plan_same_setting(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    """Handle scene plan same setting."""
    return (
        previous.get("location") == current.get("location")
        and previous.get("time") == current.get("time")
        and previous.get("space") == current.get("space")
    )


def _scene_plan_allows_split(item: dict[str, Any]) -> bool:
    """Handle scene plan allows split."""
    purpose = str(item.get("scene_purpose", "")).strip()
    reason = str(item.get("scene_boundary_reason", "")).strip()
    text = f"{purpose} {reason}"
    return purpose in validators.SCENE_BOUNDARY_PURPOSE_ALLOWLIST or any(
        marker in text for marker in validators.SCENE_BOUNDARY_REASON_MARKERS
    )


def _list_values(value: Any) -> list[str]:
    """Handle list values."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _unique_in_order(values: list[str]) -> list[str]:
    """Handle unique in order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _merge_scene_plan_items(previous: dict[str, Any], current: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """Handle merge scene plan items."""
    merged = dict(previous)
    merged["appearing_character_names"] = _unique_in_order(
        _list_values(previous.get("appearing_character_names")) + _list_values(current.get("appearing_character_names"))
    )
    merged["must_include_beats"] = _unique_in_order(
        _list_values(previous.get("must_include_beats")) + _list_values(current.get("must_include_beats"))
    )
    merged["scene_purpose"] = "；".join(
        _unique_in_order(
            [str(previous.get("scene_purpose", "")).strip(), str(current.get("scene_purpose", "")).strip()],
        )
    )
    merged["scene_boundary_reason"] = (
        f"自动合并相邻内部节奏段：{reason}；"
        + (
            f"{str(previous.get('scene_boundary_reason', '')).strip()}；"
            f"{str(current.get('scene_boundary_reason', '')).strip()}"
        )
    ).strip("；")
    return merged


def _should_merge_scene_plan_items(previous: dict[str, Any], current: dict[str, Any]) -> str:
    """Handle should merge scene plan items."""
    if not _scene_plan_same_setting(previous, current) or _scene_plan_allows_split(current):
        return ""
    if _scene_plan_cast_key(previous) == _scene_plan_cast_key(current):
        return "same_setting_same_cast_merge"
    previous_cast = set(_scene_plan_cast_key(previous))
    current_cast = set(_scene_plan_cast_key(current))
    removed_cast = previous_cast - current_cast
    reason_text = " ".join(
        [
            str(current.get("scene_purpose", "")),
            str(current.get("scene_boundary_reason", "")),
            " ".join(_list_values(current.get("must_include_beats"))),
        ]
    )
    if (
        removed_cast
        and any(marker in reason_text for marker in validators.VISIBLE_DOORWAY_EXIT_MARKERS)
        and not any(marker in reason_text for marker in validators.EXPLICIT_OFFSCREEN_EXIT_MARKERS)
    ):
        return "visible_doorway_cast_merge"
    return ""


def repair_episode_scene_plan_boundaries(data: dict[str, Any]) -> dict[str, Any]:
    """Handle repair episode scene plan boundaries."""
    episodes = data.get("episode_outlines")
    if not isinstance(episodes, list):
        return data
    changed = False
    repaired_episodes: list[Any] = []
    for episode in episodes:
        if not isinstance(episode, dict):
            repaired_episodes.append(episode)
            continue
        scene_plan = episode.get("scene_plan")
        if not isinstance(scene_plan, list) or len(scene_plan) < 2:
            repaired_episodes.append(episode)
            continue
        repaired_plan: list[dict[str, Any]] = []
        trace = list(episode.get("scene_plan_repair_trace", []))
        episode_changed = False
        for item in scene_plan:
            if not isinstance(item, dict):
                continue
            next_item = dict(item)
            if repaired_plan:
                merge_reason = _should_merge_scene_plan_items(repaired_plan[-1], next_item)
                if merge_reason:
                    previous_scene_no = repaired_plan[-1].get("scene_no")
                    current_scene_no = next_item.get("scene_no")
                    repaired_plan[-1] = _merge_scene_plan_items(repaired_plan[-1], next_item, reason=merge_reason)
                    trace.append(
                        {
                            "reason": merge_reason,
                            "merged_scene_no": current_scene_no,
                            "into_scene_no": previous_scene_no,
                        }
                    )
                    episode_changed = True
                    changed = True
                    continue
            repaired_plan.append(next_item)
        if episode_changed:
            reindexed_plan = []
            for index, item in enumerate(repaired_plan, start=1):
                reindexed = dict(item)
                reindexed["scene_no"] = index
                reindexed_plan.append(reindexed)
            next_episode = dict(episode)
            next_episode["scene_plan"] = reindexed_plan
            next_episode["scene_plan_repair_trace"] = trace
            repaired_episodes.append(next_episode)
        else:
            repaired_episodes.append(episode)
    if not changed:
        return data
    output = dict(data)
    output["episode_outlines"] = repaired_episodes
    return output


def _scene_plan_visible_generic_roles(scene: dict[str, Any]) -> list[str]:
    """Handle scene plan visible generic roles."""
    text = " ".join(
        [
            str(scene.get("scene_purpose", "")),
            str(scene.get("scene_boundary_reason", "")),
            " ".join(str(item) for item in scene.get("must_include_beats", []) or []),
        ]
    )
    roles: list[str] = []
    for role in validators.VISIBLE_GENERIC_ROLE_NAMES:
        if re.search(rf"{re.escape(role)}[^，。！？；：\n]{{0,14}}{validators.VISIBLE_ACTION_VERB_RE.pattern}", text):
            roles.append(role)
    return roles


def _text_supports_heading_location_expansion(text: str, token: str, *, require_action_marker: bool) -> bool:
    """Handle text supports heading location expansion."""
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if require_action_marker:
        if not stripped.startswith("△") or validators.SCREEN_TEXT_ACTION_RE.match(stripped):
            return False
    elif stripped.startswith("△") and validators.SCREEN_TEXT_ACTION_RE.match(stripped):
        return False
    if validators.DIALOGUE_SPEAKER_RE.match(stripped):
        return False
    if token not in stripped:
        return False
    patterns = (
        rf"(走向|走到|来到|进入|走进)[^，。！？；\n]{{0,12}}{re.escape(token)}",
        rf"(走过|经过|穿过|路过)[^，。！？；\n]{{0,12}}{re.escape(token)}",
        rf"(从|自)[^，。！？；\n]{{0,8}}{re.escape(token)}[^，。！？；\n]{{0,8}}(走出|出来|离开)",
        rf"(从|自)[^，。！？；\n]{{0,8}}{re.escape(token)}[^，。！？；\n]{{0,8}}(走过|经过|穿过|路过)",
        rf"(从|自)[^，。！？；\n]{{0,18}}(走出|出来|离开){re.escape(token)}",
        rf"推开[^，。！？；\n]{{0,12}}{re.escape(token)}",
        rf"(看向|望向|视线落在|目光落在)[^，。！？；\n]{{0,18}}{re.escape(token)}",
        rf"{re.escape(token)}(尽头|一端|另一端|拐角)",
        rf"{re.escape(token)}(门|口|玻璃门|门外|门口|区)",
    )
    return any(re.search(pattern, stripped) for pattern in patterns)


def expand_episode_scene_plan_locations_from_visible_space(data: dict[str, Any]) -> dict[str, Any]:
    """Handle expand episode scene plan locations from visible space."""
    episodes = data.get("episode_outlines")
    if not isinstance(episodes, list):
        return data
    changed = False
    repaired_episodes: list[Any] = []
    for episode in episodes:
        if not isinstance(episode, dict):
            repaired_episodes.append(episode)
            continue
        scene_plan = episode.get("scene_plan")
        if not isinstance(scene_plan, list):
            repaired_episodes.append(episode)
            continue
        next_episode = dict(episode)
        trace = list(next_episode.get("scene_plan_repair_trace", []))
        repaired_plan: list[Any] = []
        episode_changed = False
        for scene in scene_plan:
            if not isinstance(scene, dict):
                repaired_plan.append(scene)
                continue
            location = str(scene.get("location", "")).strip()
            additions: list[str] = []
            texts = [
                str(scene.get("scene_purpose", "")),
                str(scene.get("scene_boundary_reason", "")),
                *[str(item) for item in scene.get("must_include_beats", []) or []],
            ]
            for text in texts:
                for token in validators.CONCRETE_LOCATION_TOKENS:
                    if token in location or any(token in addition for addition in additions):
                        continue
                    if _text_supports_heading_location_expansion(text, token, require_action_marker=False):
                        additions.append(_location_expansion_label(token, text))
            if additions:
                next_scene = dict(scene)
                next_scene["location"] = f"{location}及{'及'.join(additions)}"
                repaired_plan.append(next_scene)
                trace.append(
                    {
                        "reason": "scene_location_expanded_from_visible_space",
                        "scene_no": next_scene.get("scene_no"),
                        "added_locations": additions,
                    }
                )
                episode_changed = True
                changed = True
            else:
                repaired_plan.append(scene)
        if episode_changed:
            next_episode["scene_plan"] = repaired_plan
            next_episode["scene_plan_repair_trace"] = trace
        repaired_episodes.append(next_episode if episode_changed else episode)
    if not changed:
        return data
    output = dict(data)
    output["episode_outlines"] = repaired_episodes
    return output


def repair_episode_scene_plan_generic_visible_roles(data: dict[str, Any]) -> dict[str, Any]:
    """Handle repair episode scene plan generic visible roles."""
    episodes = data.get("episode_outlines")
    if not isinstance(episodes, list):
        return data
    changed = False
    repaired_episodes: list[Any] = []
    for episode in episodes:
        if not isinstance(episode, dict):
            repaired_episodes.append(episode)
            continue
        next_episode = dict(episode)
        trace = list(next_episode.get("scene_plan_repair_trace", []))
        episode_cast = [
            str(item).strip()
            for item in next_episode.get("appearing_character_names", [])
            if str(item).strip()
        ]
        generic_episode_roles = [
            name for name in episode_cast
            if validators.normalize_character_name(name) in validators.VISIBLE_GENERIC_ROLE_NAMES
        ]
        if generic_episode_roles:
            next_episode["appearing_character_names"] = [
                name for name in episode_cast
                if validators.normalize_character_name(name) not in validators.VISIBLE_GENERIC_ROLE_NAMES
            ]
            trace.append(
                {
                    "reason": "generic_visible_role_removed_from_episode",
                    "removed_roles": generic_episode_roles,
                }
            )
            changed = True
            episode_changed = True
        else:
            episode_changed = False
        scene_plan = episode.get("scene_plan")
        if not isinstance(scene_plan, list):
            if trace:
                next_episode["scene_plan_repair_trace"] = trace
            repaired_episodes.append(next_episode if episode_changed else episode)
            continue
        repaired_plan: list[Any] = []
        for scene in scene_plan:
            if not isinstance(scene, dict):
                repaired_plan.append(scene)
                continue
            scene_cast = [str(item).strip() for item in scene.get("appearing_character_names", []) if str(item).strip()]
            scene_keys = {validators.normalize_character_name(name) for name in scene_cast}
            added_roles = [
                role for role in _scene_plan_visible_generic_roles(scene)
                if validators.normalize_character_name(role) not in scene_keys
            ]
            if added_roles:
                next_scene = dict(scene)
                next_scene["appearing_character_names"] = _ordered_unique(scene_cast + added_roles)
                repaired_plan.append(next_scene)
                trace.append(
                    {
                        "reason": "generic_visible_role_added",
                        "scene_no": next_scene.get("scene_no"),
                        "added_roles": added_roles,
                    }
                )
                episode_changed = True
                changed = True
            else:
                repaired_plan.append(scene)
        if episode_changed:
            next_episode["scene_plan"] = repaired_plan
            next_episode["scene_plan_repair_trace"] = trace
        repaired_episodes.append(next_episode)
    if not changed:
        return data
    output = dict(data)
    output["episode_outlines"] = repaired_episodes
    return output


def normalize_script_narration_device_usage(data: dict[str, Any]) -> dict[str, Any]:
    """Handle normalize script narration device usage."""
    continuity_update = data.get("continuity_update")
    if not isinstance(continuity_update, dict):
        return data
    usage = continuity_update.get("narration_device_usage")
    if not isinstance(usage, dict):
        return data
    actual_usage = validators.count_narration_devices(data.get("final_script", ""))
    next_usage = dict(usage)
    changed = False
    for key, value in actual_usage.items():
        if _safe_int_value(next_usage.get(key)) != value:
            next_usage[key] = value
            changed = True
    if not changed:
        return data
    next_update = dict(continuity_update)
    next_update["narration_device_usage"] = next_usage
    normalized = dict(data)
    normalized["continuity_update"] = next_update
    return normalized


def normalize_script_last_scene_state_list_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Handle normalize script last scene state list fields."""
    continuity_update = data.get("continuity_update")
    if not isinstance(continuity_update, dict):
        return data
    last_scene_state = continuity_update.get("last_scene_state")
    if not isinstance(last_scene_state, dict):
        return data
    names = last_scene_state.get("present_character_names")
    if names is None or isinstance(names, list):
        return data
    next_state = dict(last_scene_state)
    next_state["present_character_names"] = [names]
    next_update = dict(continuity_update)
    next_update["last_scene_state"] = next_state
    normalized = dict(data)
    normalized["continuity_update"] = next_update
    return normalized


def normalize_script_last_scene_state_from_script(data: dict[str, Any]) -> dict[str, Any]:
    """Handle normalize script last scene state from script."""
    continuity_update = data.get("continuity_update")
    if not isinstance(continuity_update, dict):
        return data
    try:
        actual = validators.extract_last_authored_scene_fact(data.get("final_script", ""))
    except ValueError:
        return data
    if not actual.get("location") or continuity_update.get("last_scene_state") == actual:
        return data
    next_update = dict(continuity_update)
    next_update["last_scene_state"] = actual
    normalized = dict(data)
    normalized["continuity_update"] = next_update
    return normalized


def normalize_script_completed_beat_ids_from_execution_sheet(
    data: dict[str, Any],
    *,
    normalization_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Handle normalize script completed beat ids from execution sheet."""
    continuity_update = data.get("continuity_update")
    if not isinstance(continuity_update, dict):
        return data
    context = normalization_context or {}
    execution_sheet = context.get("episode_execution_sheet") or context.get("episode_outline")
    if not isinstance(execution_sheet, dict):
        return data
    planned_ids = [
        str(item).strip()
        for item in execution_sheet.get("consumed_child_beat_ids", []) or []
        if str(item).strip()
    ]
    if continuity_update.get("completed_beat_ids") == planned_ids:
        return data
    next_update = dict(continuity_update)
    next_update["completed_beat_ids"] = planned_ids
    normalized = dict(data)
    normalized["continuity_update"] = next_update
    return normalized


FIELD_SUBTITLE_RE = re.compile(r"^\s*【字幕：(?P<text>[^】]*[:：][^】]*)】\s*$")
EMPTY_DIALOGUE_LINE_RE = re.compile(r"^\s*(?P<speaker>[^△【\s（：:]{1,12})（(?P<action>[^）]{1,80})）\s*[:：]\s*$")
ACTION_ONLY_DIALOGUE_LINE_RE = re.compile(
    r"^\s*(?P<speaker>[^△【\s（：:]{1,12})（(?P<action>[^）]{1,80})）\s*[:：]\s*（(?P<trailing>[^）]{1,80})）\s*[。！？…]*\s*$"
)
DIALOGUE_ACTION_LINE_RE = re.compile(
    r"^\s*(?P<speaker>[^△【\s（：:]{1,12})（(?P<action>[^）]*)）(?P<rest>\s*[:：].*)$"
)
EPISODE_TITLE_LINE_RE = re.compile(r"^\s*#?\s*第(?P<num>[0-9一二三四五六七八九十百]+)集\s*$")
VISIBLE_NAME_PREFIX_RE = re.compile(
    r"^△?\s*(?P<name>[\u4e00-\u9fff]{2,4}?)(?:已经|正在|已|正|仍|还|又)?"
    r"(?=(?:手机|手指|视线|目光|从|按|将|拿|放|看|低头|抬头|转身|站|坐|走|退|推|拉|点|滑|盯|停|提|拨|接|开|关|伸|抬|端|扫|跟随|起身))"
)
NON_NAME_PREFIXES = {
    "手机",
    "屏幕",
    "桌面",
    "抽屉",
    "截图",
    "便条",
    "收据",
    "窗外",
    "电梯",
    "公司",
    "咖啡",
    "合同",
    "支票",
}
NONVISUAL_DIALOGUE_ACTION_TOKENS = (
    "声音",
    "语气",
    "声调",
    "音量",
    "语速",
    "嗓音",
    "平声",
    "沉声",
    "冷声",
    "轻声",
    "低声",
    "淡淡",
    "漫不经心",
)
CN_NUMERAL_MAP = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _sentence_line(text: str) -> str:
    """Handle sentence line."""
    stripped = text.rstrip()
    if not stripped:
        return stripped
    if stripped.endswith(("。", "！", "？", "…")):
        return stripped
    return f"{stripped}。"


def _parse_episode_number_token(value: str) -> int | None:
    """Handle parse episode number token."""
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    if not text:
        return None
    if text == "十":
        return 10
    if "百" in text:
        left, _, right = text.partition("百")
        hundreds = CN_NUMERAL_MAP.get(left, 1 if not left else 0)
        if not hundreds:
            return None
        tail = _parse_episode_number_token(right) if right else 0
        return hundreds * 100 + (tail or 0)
    if "十" in text:
        left, _, right = text.partition("十")
        tens = CN_NUMERAL_MAP.get(left, 1 if not left else 0)
        if not tens:
            return None
        ones = CN_NUMERAL_MAP.get(right, 0) if right else 0
        return tens * 10 + ones
    return CN_NUMERAL_MAP.get(text)


def _find_script_title_episode(lines: list[str]) -> int | None:
    """Handle find script title episode."""
    for line in lines:
        if validators.SCRIPT_SCENE_HEADING_RE.match(line):
            return None
        match = EPISODE_TITLE_LINE_RE.match(line)
        if match:
            return _parse_episode_number_token(match.group("num"))
    return None


def normalize_script_heading_episode_from_title(script: str) -> str:
    """Handle normalize script heading episode from title."""
    lines = str(script or "").splitlines()
    title_episode = _find_script_title_episode(lines)
    if not title_episode:
        return str(script or "")
    changed = False
    normalized_lines: list[str] = []
    for line in lines:
        match = validators.SCRIPT_SCENE_HEADING_RE.match(line)
        if not match:
            normalized_lines.append(line)
            continue
        if int(match.group("episode")) == title_episode:
            normalized_lines.append(line)
            continue
        normalized_lines.append(
            f"{title_episode}-{int(match.group('scene'))}"
            f"    {match.group('location').strip()}    {match.group('time').strip()}    {match.group('space').strip()}"
        )
        changed = True
    return "\n".join(normalized_lines) if changed else str(script or "")


def _infer_cast_from_scene_lines(lines: list[str]) -> list[str]:
    """Handle infer cast from scene lines."""
    names: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        speaker_match = validators.DIALOGUE_SPEAKER_RE.match(line)
        if speaker_match:
            names.append(speaker_match.group("speaker").strip())
            continue
        visible_match = VISIBLE_NAME_PREFIX_RE.match(line)
        if visible_match:
            name = visible_match.group("name").strip()
            if name not in NON_NAME_PREFIXES:
                names.append(name)
    return _ordered_unique(names) or ["陈寻"]


def normalize_script_missing_first_scene_heading(script: str) -> str:
    """Handle normalize script missing first scene heading."""
    lines = str(script or "").splitlines()
    # A malformed scene-like line is still authored content. Do not invent a
    # replacement heading from a later scene; the validator reports it instead.
    if any(
        validators.SCRIPT_SCENE_HEADING_LIKE_RE.match(line)
        and not validators.SCRIPT_SCENE_HEADING_RE.match(line)
        for line in lines
    ):
        return str(script or "")
    first_heading_index = next(
        (index for index, line in enumerate(lines) if validators.SCRIPT_SCENE_HEADING_RE.match(line)),
        None,
    )
    if first_heading_index is None or first_heading_index <= 0:
        return str(script or "")
    first_match = validators.SCRIPT_SCENE_HEADING_RE.match(lines[first_heading_index])
    if first_match is None or int(first_match.group("scene")) <= 1:
        return str(script or "")
    leading_lines = lines[:first_heading_index]
    title_lines: list[str] = []
    content_lines: list[str] = []
    found_content = False
    for line in leading_lines:
        stripped = line.strip()
        if not found_content and (not stripped or EPISODE_TITLE_LINE_RE.match(stripped)):
            title_lines.append(line)
            continue
        found_content = True
        content_lines.append(line)
    if not any(line.strip() for line in content_lines):
        return str(script or "")
    episode_num = int(first_match.group("episode"))
    inferred_cast = _infer_cast_from_scene_lines(content_lines)
    inserted_heading = (
        f"{episode_num}-1"
        + (
            f"    {first_match.group('location').strip()}    {first_match.group('time').strip()}    "
            f"{first_match.group('space').strip()}"
        )
    )
    normalized_lines=(
        title_lines
        + [inserted_heading, f"出场人物：{'、'.join(inferred_cast)}"]
        + content_lines
        + lines[first_heading_index:]
    )
    return "\n".join(normalized_lines)


def normalize_script_empty_dialogue_lines(script: str) -> str:
    """Handle normalize script empty dialogue lines."""
    lines: list[str] = []
    for raw_line in str(script or "").splitlines():
        line = raw_line
        empty_match = EMPTY_DIALOGUE_LINE_RE.match(line)
        action_only_match = ACTION_ONLY_DIALOGUE_LINE_RE.match(line)
        if empty_match:
            speaker = empty_match.group("speaker").strip()
            action = empty_match.group("action").strip("，,。 ")
            line = _sentence_line(f"△{speaker}{action}")
        elif action_only_match:
            speaker = action_only_match.group("speaker").strip()
            action_parts = [
                action_only_match.group("action").strip("，,。 "),
                action_only_match.group("trailing").strip("，,。 "),
            ]
            action_text = "，".join(part for part in action_parts if part)
            line = _sentence_line(f"△{speaker}{action_text}")
        lines.append(line)
    return "\n".join(lines)


def _normalize_dialogue_action_text(action: str) -> str:
    """Handle normalize dialogue action text."""
    parts = [part.strip() for part in re.split(r"[，、,]+", str(action or "")) if part.strip()]
    normalized_parts: list[str] = []
    for part in parts:
        if any(token in part for token in NONVISUAL_DIALOGUE_ACTION_TOKENS):
            continue
        normalized_parts.append(part)
    if not normalized_parts:
        if any(part.upper() == "VO" for part in parts):
            return "VO"
        if any(part.upper() == "OS" for part in parts):
            return "OS"
        return "看向对方"
    return "，".join(normalized_parts)


def normalize_script_nonvisual_dialogue_action_tags(script: str) -> str:
    """Handle normalize script nonvisual dialogue action tags."""
    lines: list[str] = []
    changed = False
    for raw_line in str(script or "").splitlines():
        match = DIALOGUE_ACTION_LINE_RE.match(raw_line)
        if not match:
            lines.append(raw_line)
            continue
        normalized_action = _normalize_dialogue_action_text(match.group("action"))
        line = f"{match.group('speaker')}（{normalized_action}）{match.group('rest')}"
        if line != raw_line:
            changed = True
        lines.append(line)
    return "\n".join(lines) if changed else str(script or "")


def normalize_script_dialogue_triangle_prefix(script: str) -> str:
    """Handle normalize script dialogue triangle prefix."""
    lines: list[str] = []
    changed = False
    for raw_line in str(script or "").splitlines():
        match = validators.DIALOGUE_WITH_TRIANGLE_RE.match(raw_line)
        if not match:
            lines.append(raw_line)
            continue
        lines.append(match.group("dialogue").strip())
        changed = True
    return "\n".join(lines) if changed else str(script or "")


def normalize_script_subtitle_text_misuse(script: str) -> str:
    """Handle normalize script subtitle text misuse."""
    lines: list[str] = []
    for raw_line in str(script or "").splitlines():
        match = FIELD_SUBTITLE_RE.match(raw_line)
        if match:
            text = match.group("text").strip()
            lines.append(_sentence_line(f"△屏幕显示：{text}"))
        else:
            lines.append(raw_line)
    return "\n".join(lines)


def _split_cast_line_preserving_order(cast_text: Any) -> list[str]:
    """Handle split cast line preserving order."""
    names: list[str] = []
    for part in re.split(r"[、,，/]+|和|及|与", str(cast_text or "")):
        name = str(part or "").strip()
        if name:
            names.append(name)
    return _ordered_unique(names)


def normalize_script_scene_cast_from_dialogue_speakers(script: str) -> str:
    """Handle normalize script scene cast from dialogue speakers."""
    lines = str(script or "").splitlines()
    heading_indices = [
        index for index, line in enumerate(lines)
        if validators.SCRIPT_SCENE_HEADING_RE.match(line)
    ]
    if not heading_indices:
        return str(script or "")
    changed = False
    for heading_position, heading_index in enumerate(heading_indices):
        next_heading_index = (
            heading_indices[heading_position + 1]
            if heading_position + 1 < len(heading_indices)
            else len(lines)
        )
        cast_line_index: int | None = None
        cast_match: re.Match[str] | None = None
        for index in range(heading_index + 1, next_heading_index):
            if not lines[index].strip():
                continue
            cast_match = validators.SCRIPT_SCENE_CAST_RE.match(lines[index])
            if cast_match:
                cast_line_index = index
            break
        if cast_line_index is None or cast_match is None:
            continue
        cast_names = _split_cast_line_preserving_order(cast_match.group("cast"))
        cast_keys = {validators.normalize_character_name(name) for name in cast_names}
        added: list[str] = []
        for index in range(cast_line_index + 1, next_heading_index):
            line = lines[index].strip()
            if not line or line.startswith(("△", "【")) or validators.SCRIPT_SCENE_CAST_RE.match(line):
                continue
            speaker_match = validators.DIALOGUE_SPEAKER_RE.match(line)
            if not speaker_match:
                continue
            speaker = speaker_match.group("speaker").strip()
            normalized = validators.normalize_character_name(speaker)
            if normalized and normalized not in cast_keys:
                cast_keys.add(normalized)
                added.append(speaker)
        if added:
            lines[cast_line_index] = f"出场人物：{'、'.join(_ordered_unique(cast_names + added))}"
            changed = True
    return "\n".join(lines) if changed else str(script or "")


def _collect_script_cast_and_speaker_names(script: str) -> set[str]:
    """Handle collect script cast and speaker names."""
    names: set[str] = set()
    for raw_line in str(script or "").splitlines():
        cast_match = validators.SCRIPT_SCENE_CAST_RE.match(raw_line)
        if cast_match:
            names.update(
                validators.normalize_character_name(name)
                for name in _split_cast_line_preserving_order(cast_match.group("cast"))
            )
        speaker_match = validators.DIALOGUE_SPEAKER_RE.match(raw_line.strip())
        if speaker_match:
            names.add(validators.normalize_character_name(speaker_match.group("speaker")))
    return {name for name in names if name}


def normalize_script_scene_cast_from_visible_actions(
    script: str,
    *,
    allowed_character_names: set[str] | None = None,
) -> str:
    """Handle normalize script scene cast from visible actions."""
    lines = str(script or "").splitlines()
    heading_indices = [
        index for index, line in enumerate(lines)
        if validators.SCRIPT_SCENE_HEADING_RE.match(line)
    ]
    if not heading_indices:
        return str(script or "")
    known_names = _collect_script_cast_and_speaker_names(script)
    known_names.update(
        validators.normalize_character_name(name)
        for name in (allowed_character_names or set())
    )
    known_names.discard("")
    changed = False
    for heading_position, heading_index in enumerate(heading_indices):
        next_heading_index = (
            heading_indices[heading_position + 1]
            if heading_position + 1 < len(heading_indices)
            else len(lines)
        )
        cast_line_index: int | None = None
        cast_match: re.Match[str] | None = None
        for index in range(heading_index + 1, next_heading_index):
            if not lines[index].strip():
                continue
            cast_match = validators.SCRIPT_SCENE_CAST_RE.match(lines[index])
            if cast_match:
                cast_line_index = index
            break
        if cast_line_index is None or cast_match is None:
            continue
        cast_names = _split_cast_line_preserving_order(cast_match.group("cast"))
        cast_keys = {validators.normalize_character_name(name) for name in cast_names}
        added: list[str] = []
        for index in range(cast_line_index + 1, next_heading_index):
            line = lines[index].strip()
            if not line.startswith("△") or validators.SCREEN_TEXT_ACTION_RE.match(line):
                continue
            visible_match = VISIBLE_NAME_PREFIX_RE.match(line)
            candidate_names: list[str] = []
            if visible_match:
                candidate_names.append(visible_match.group("name").strip())
            for role in validators.VISIBLE_GENERIC_ROLE_NAMES:
                if role not in candidate_names and validators._line_mentions_visible_action_role(line, role):
                    candidate_names.append(role)
            for name in candidate_names:
                normalized = validators.normalize_character_name(name)
                if not normalized or normalized in cast_keys or normalized in NON_NAME_PREFIXES:
                    continue
                if normalized not in known_names and normalized not in validators.VISIBLE_GENERIC_ROLE_NAMES:
                    continue
                if not validators._line_mentions_visible_action_role(line, normalized):
                    continue
                cast_keys.add(normalized)
                added.append(name)
        if added:
            lines[cast_line_index] = f"出场人物：{'、'.join(_ordered_unique(cast_names + added))}"
            changed = True
    return "\n".join(lines) if changed else str(script or "")


def _scene_cast_name_is_active(name: str, scene_lines: list[str]) -> bool:
    """Handle scene cast name is active."""
    normalized = validators.normalize_character_name(name)
    if not normalized:
        return False
    for raw_line in scene_lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("【字幕：") and normalized in line:
            return True
        speaker_match = validators.DIALOGUE_SPEAKER_RE.match(line)
        if speaker_match and validators.normalize_character_name(speaker_match.group("speaker")) == normalized:
            return True
        if re.search(rf"(看向|望向|盯着|指向|推向|递给|面对|直视){re.escape(normalized)}", line):
            return True
        if line.startswith("△") and validators._line_mentions_visible_action_role(line, normalized):
            return True
        if line.startswith("△") and re.search(
            rf"{re.escape(normalized)}[^，。！？；\n]{{0,16}}(接听|接起|拨出|拨号|挂断|翻扣|拿起|放下|收起|按掉)",
            line,
        ):
            return True
    return False


def _scene_cast_name_is_referenced(name: str, scene_lines: list[str]) -> bool:
    """Handle scene cast name is referenced."""
    normalized = validators.normalize_character_name(name)
    if not normalized:
        return False
    return any(normalized in raw_line for raw_line in scene_lines)


def normalize_script_scene_cast_screen_only_mentions(script: str) -> str:
    # 人物表是生产拆解依据。规则可以确定地补人，但不能仅因动作词表未命中就删除模型已列人物。
    """Handle normalize script scene cast screen only mentions."""
    return str(script or "")


def normalize_script_extra_os_markers(script: str, *, max_os: int = 1) -> str:
    """Handle normalize script extra os markers."""
    lines: list[str] = []
    changed = False
    seen_os = 0
    for raw_line in str(script or "").splitlines():
        match = DIALOGUE_ACTION_LINE_RE.match(raw_line)
        if not match or "OS" not in match.group("action").upper():
            lines.append(raw_line)
            continue
        seen_os += 1
        if seen_os <= max_os:
            lines.append(raw_line)
            continue
        line = f"{match.group('speaker')}（看着眼前物件）{match.group('rest')}"
        lines.append(line)
        changed = True
    return "\n".join(lines) if changed else str(script or "")


def _line_supports_heading_location_expansion(line: str, token: str) -> bool:
    """Handle line supports heading location expansion."""
    return _text_supports_heading_location_expansion(line, token, require_action_marker=True)


def _location_expansion_label(token: str, line: str) -> str:
    """Handle location expansion label."""
    if token == "电梯":
        return "电梯口"
    if token == "工位" and "工位区" in line:
        return "工位区"
    if re.search(rf"(从|自)[^，。！？；\n]{{0,8}}{re.escape(token)}[^，。！？；\n]{{0,8}}(走出|出来|离开)", line):
        return f"{token}外"
    if re.search(rf"(从|自)[^，。！？；\n]{{0,18}}(走出|出来|离开){re.escape(token)}", line):
        return f"{token}外"
    if re.search(rf"(从|自)[^，。！？；\n]{{0,8}}{re.escape(token)}[^，。！？；\n]{{0,8}}(走过|经过|穿过|路过)", line):
        return f"{token}外"
    if any(marker in line for marker in ("门", "玻璃门", "门外", "门口")) and token not in {"门口", "走廊"}:
        return f"{token}外"
    return token


def normalize_script_scene_heading_visible_space(script: str) -> str:
    """Handle normalize script scene heading visible space."""
    lines = str(script or "").splitlines()
    heading_indices = [
        index for index, line in enumerate(lines)
        if validators.SCRIPT_SCENE_HEADING_RE.match(line)
    ]
    if not heading_indices:
        return str(script or "")
    changed = False
    for heading_position, heading_index in enumerate(heading_indices):
        match = validators.SCRIPT_SCENE_HEADING_RE.match(lines[heading_index])
        if not match:
            continue
        next_heading_index = (
            heading_indices[heading_position + 1]
            if heading_position + 1 < len(heading_indices)
            else len(lines)
        )
        location = match.group("location").strip()
        additions: list[str] = []
        for body_line in lines[heading_index + 1 : next_heading_index]:
            for token in validators.CONCRETE_LOCATION_TOKENS:
                if token in location or any(token in addition for addition in additions):
                    continue
                if _line_supports_heading_location_expansion(body_line, token):
                    additions.append(_location_expansion_label(token, body_line))
        if additions:
            next_location = f"{location}及{'及'.join(additions)}"
            lines[heading_index] = (
                f"{int(match.group('episode'))}-{int(match.group('scene'))}"
                f"    {next_location}    {match.group('time').strip()}    {match.group('space').strip()}"
            )
            changed = True
    return "\n".join(lines) if changed else str(script or "")


def normalize_script_camera_markers(script: str) -> str:
    """Handle normalize script camera markers."""
    lines: list[str] = []
    for raw_line in str(script or "").splitlines():
        line = raw_line
        if line.strip().startswith("△"):
            line = SCRIPT_CAMERA_MARKER_RE.sub("", line)
            line = re.sub(r"[，,]\s*([。！？])", r"\1", line)
            if (
                line.strip().startswith("△")
                and line.strip() != "△"
                and not line.rstrip().endswith(("。", "！", "？", "…"))
            ):
                line = f"{line.rstrip()}。"
        lines.append(line)
    return "\n".join(lines)


def normalize_script_outline_episode_budget(data: dict[str, Any]) -> dict[str, Any]:
    """Handle normalize script outline episode budget."""
    budget = data.get("episode_budget")
    if not isinstance(budget, list):
        return data
    normalized_budget: list[Any] = []
    changed = False
    for item in budget:
        if isinstance(item, dict) and str(item.get("phase", "")).strip().lower() in {"合计", "总计", "total", "sum"}:
            changed = True
            continue
        normalized_budget.append(item)
    if not changed:
        return data
    normalized = dict(data)
    normalized["episode_budget"] = normalized_budget
    return normalized


def normalize_script_outline_terminal_block_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Handle normalize script outline terminal block fields."""
    blocks = data.get("longform_blocks")
    state_plans = data.get("block_state_plan")
    if not isinstance(blocks, list) or not blocks:
        return data

    terminal_index = max(
        range(len(blocks)),
        key=lambda index: int(blocks[index].get("end_episode", 0)) if isinstance(blocks[index], dict) else 0,
    )
    terminal_block = blocks[terminal_index]
    if not isinstance(terminal_block, dict):
        return data
    terminal_block_id = terminal_block.get("block_id")
    terminal_text = "终局收束，无下一block"
    changed = False
    next_blocks = list(blocks)
    if terminal_block.get("hook") in (None, ""):
        next_block = dict(terminal_block)
        next_block["hook"] = terminal_text
        next_blocks[terminal_index] = next_block
        changed = True

    next_state_plans = state_plans
    if isinstance(state_plans, list):
        repaired_plans: list[Any] = []
        for index, item in enumerate(state_plans):
            if not isinstance(item, dict):
                repaired_plans.append(item)
                continue
            is_terminal = item.get("block_id") == terminal_block_id
            if terminal_block_id is None:
                is_terminal = index == len(state_plans) - 1
            if is_terminal and item.get("handoff_to_next_block") in (None, ""):
                next_item = dict(item)
                next_item["handoff_to_next_block"] = terminal_text
                repaired_plans.append(next_item)
                changed = True
            else:
                repaired_plans.append(item)
        next_state_plans = repaired_plans

    if not changed:
        return data
    normalized = dict(data)
    normalized["longform_blocks"] = next_blocks
    if isinstance(next_state_plans, list):
        normalized["block_state_plan"] = next_state_plans
    return normalized


def _macro_arc_boundary_specs(macro_arcs: Any) -> list[dict[str, Any]]:
    """Handle macro arc boundary specs."""
    specs: list[dict[str, Any]] = []
    for index, arc in enumerate(macro_arcs or []):
        if not isinstance(arc, dict):
            continue
        raw_range = arc.get("episode_range")
        try:
            if isinstance(raw_range, dict):
                start = int(raw_range.get("start", 0))
                end = int(raw_range.get("end", 0))
            else:
                start, end = validators.parse_numeric_range(str(raw_range or ""))
        except (TypeError, ValueError):
            continue
        if start <= 0 or end < start:
            continue
        specs.append(
            {
                "block_id": int(arc.get("arc_id", index + 1)),
                "start_episode": start,
                "end_episode": end,
                "episode_count": end - start + 1,
            }
        )
    return specs


def _episode_range_like(value: Any, *, start: int, end: int) -> Any:
    """Handle episode range like."""
    if isinstance(value, dict):
        return {"start": start, "end": end}
    return f"{start}-{end}"


def normalize_script_outline_macro_arc_boundaries(
    data: dict[str, Any],
    *,
    macro_arcs: Any,
) -> dict[str, Any]:
    """Keep 05 event ownership as the single source of truth for 06 boundaries."""

    specs = _macro_arc_boundary_specs(macro_arcs)
    blocks = data.get("longform_blocks")
    if not specs or not isinstance(blocks, list) or len(blocks) != len(specs):
        return data
    spec_by_id = {item["block_id"]: item for item in specs}

    def spec_for(item: Any, index: int) -> dict[str, Any]:
        """Handle spec for."""
        if isinstance(item, dict):
            try:
                block_id = int(item.get("block_id", 0))
            except (TypeError, ValueError):
                block_id = 0
            if block_id in spec_by_id:
                return spec_by_id[block_id]
        return specs[index]

    normalized = dict(data)
    normalized_blocks: list[Any] = []
    for index, raw_item in enumerate(blocks):
        if not isinstance(raw_item, dict):
            normalized_blocks.append(raw_item)
            continue
        spec = spec_for(raw_item, index)
        normalized_blocks.append(
            {
                **raw_item,
                "block_id": spec["block_id"],
                "start_episode": spec["start_episode"],
                "end_episode": spec["end_episode"],
                "episode_count": spec["episode_count"],
            }
        )
    normalized["longform_blocks"] = normalized_blocks

    budget = data.get("episode_budget")
    if isinstance(budget, list) and len(budget) == len(specs):
        normalized["episode_budget"] = [
            {
                **raw_item,
                "start_episode": specs[index]["start_episode"],
                "end_episode": specs[index]["end_episode"],
                "episode_count": specs[index]["episode_count"],
            }
            if isinstance(raw_item, dict)
            else raw_item
            for index, raw_item in enumerate(budget)
        ]

    release_schedule = data.get("event_release_schedule")
    if isinstance(release_schedule, list) and len(release_schedule) == len(specs):
        next_schedule: list[Any] = []
        for index, raw_item in enumerate(release_schedule):
            if not isinstance(raw_item, dict):
                next_schedule.append(raw_item)
                continue
            spec = spec_for(raw_item, index)
            next_schedule.append(
                {
                    **raw_item,
                    "block_id": spec["block_id"],
                    "episode_range": _episode_range_like(
                        raw_item.get("episode_range"),
                        start=spec["start_episode"],
                        end=spec["end_episode"],
                    ),
                }
            )
        normalized["event_release_schedule"] = next_schedule

    for key in ("block_event_plan", "block_state_plan"):
        items = data.get(key)
        if isinstance(items, list) and len(items) == len(specs):
            normalized[key] = [
                {**raw_item, "block_id": spec_for(raw_item, index)["block_id"]}
                if isinstance(raw_item, dict)
                else raw_item
                for index, raw_item in enumerate(items)
            ]

    phase_breakdown = data.get("phase_breakdown")
    if isinstance(phase_breakdown, dict) and len(phase_breakdown) == len(specs):
        normalized["phase_breakdown"] = {
            phase_name: {
                **raw_item,
                "episode_range": _episode_range_like(
                    raw_item.get("episode_range"),
                    start=specs[index]["start_episode"],
                    end=specs[index]["end_episode"],
                ),
            }
            if isinstance(raw_item, dict)
            else raw_item
            for index, (phase_name, raw_item) in enumerate(phase_breakdown.items())
        }
    return normalized


def normalize_flashback_screening_derived_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Handle normalize flashback screening derived fields."""
    changed = False
    normalized = dict(data)
    for list_key in ("retained_time_deviations", "rewrite_time_deviations", "deleted_time_deviations"):
        items = normalized.get(list_key)
        if not isinstance(items, list):
            continue
        next_items: list[Any] = []
        for item in items:
            if not isinstance(item, dict):
                next_items.append(item)
                continue
            next_item = dict(item)
            item_changed = False
            if "quota_count" not in next_item:
                grade = str(next_item.get("grade", "")).strip().upper()
                if grade in {"S", "A", "B", "C"}:
                    next_item["quota_count"] = 1 if grade == "A" else 0
                    item_changed = True
            if not str(next_item.get("reason", "")).strip():
                reason_parts = [
                    ("Q1", next_item.get("q1_structure_necessity")),
                    ("Q2", next_item.get("q2_information_necessity")),
                    ("decision", next_item.get("decision")),
                ]
                reason = "；".join(
                    f"{label}: {str(value).strip()}"
                    for label, value in reason_parts
                    if str(value or "").strip()
                )
                if reason:
                    next_item["reason"] = reason
                    item_changed = True
            next_items.append(next_item)
            changed = changed or item_changed
        if next_items != items:
            normalized[list_key] = next_items
    return normalized if changed else data


def _visible_space_tokens_from_location(location: Any) -> list[str]:
    """Handle visible space tokens from location."""
    text = str(location or "").strip()
    if not text:
        return []
    tokens: list[str] = []
    for part in re.split(r"[及/、,，\s]+", text):
        value = part.strip()
        if value and value not in tokens:
            tokens.append(value)
    return tokens or [text]


def repair_episode_scene_plan_visible_space_tokens(data: dict[str, Any]) -> dict[str, Any]:
    """Handle repair episode scene plan visible space tokens."""
    episodes = data.get("episode_outlines")
    if not isinstance(episodes, list):
        return data
    changed = False
    repaired_episodes: list[Any] = []
    for episode in episodes:
        if not isinstance(episode, dict):
            repaired_episodes.append(episode)
            continue
        scene_plan = episode.get("scene_plan")
        if not isinstance(scene_plan, list):
            repaired_episodes.append(episode)
            continue
        trace = list(episode.get("scene_plan_repair_trace", []))
        repaired_plan: list[Any] = []
        episode_changed = False
        for scene in scene_plan:
            if not isinstance(scene, dict):
                repaired_plan.append(scene)
                continue
            if isinstance(scene.get("visible_space_tokens"), list) and scene.get("visible_space_tokens"):
                repaired_plan.append(scene)
                continue
            next_scene = dict(scene)
            next_scene["visible_space_tokens"] = _visible_space_tokens_from_location(scene.get("location"))
            repaired_plan.append(next_scene)
            trace.append(
                {
                    "reason": "missing_visible_space_tokens_inferred_from_location",
                    "scene_no": scene.get("scene_no"),
                    "visible_space_tokens": next_scene["visible_space_tokens"],
                }
            )
            episode_changed = True
            changed = True
        if episode_changed:
            next_episode = dict(episode)
            next_episode["scene_plan"] = repaired_plan
            next_episode["scene_plan_repair_trace"] = trace
            repaired_episodes.append(next_episode)
        else:
            repaired_episodes.append(episode)
    if not changed:
        return data
    normalized = dict(data)
    normalized["episode_outlines"] = repaired_episodes
    return normalized


def repair_episode_target_script_density(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle repair episode target script density."""
    changed = False
    repaired: list[dict[str, Any]] = []
    for episode in episodes:
        if not isinstance(episode, dict):
            repaired.append(episode)
            continue
        if isinstance(episode.get("target_script_density"), dict):
            repaired.append(episode)
            continue
        ep_num = int(episode.get("episode_num", len(repaired) + 1))
        next_episode = dict(episode)
        next_episode["target_script_density"] = build_default_target_script_density(
            ep_num=ep_num,
            scene_plan=episode.get("scene_plan") if isinstance(episode.get("scene_plan"), list) else None,
        )
        trace = list(next_episode.get("target_script_density_repair_trace", []))
        trace.append({"reason": "missing_target_script_density_default_by_episode_cap"})
        next_episode["target_script_density_repair_trace"] = trace
        repaired.append(next_episode)
        changed = True
    return repaired if changed else episodes


def _changed_json_paths(before: Any, after: Any, *, path: str = "") -> list[str]:
    """Handle changed json paths."""
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        paths: list[str] = []
        for key in sorted(set(before) | set(after), key=str):
            child_path = f"{path}.{key}" if path else str(key)
            if key not in before or key not in after:
                paths.append(child_path)
                continue
            paths.extend(_changed_json_paths(before[key], after[key], path=child_path))
        return paths
    if isinstance(before, list) and isinstance(after, list):
        paths = []
        for index in range(max(len(before), len(after))):
            child_path = f"{path}[{index}]"
            if index >= len(before) or index >= len(after):
                paths.append(child_path)
                continue
            paths.extend(_changed_json_paths(before[index], after[index], path=child_path))
        return paths
    return [path or "$"]


def _normalization_allowed_character_names(context: dict[str, Any] | None) -> set[str]:
    """Handle normalization allowed character names."""
    context = context or {}
    names: set[str] = set()
    canonical_lock = context.get("canonical_story_lock")
    if isinstance(canonical_lock, dict):
        names.update(str(name) for name in canonical_lock.get("character_names", []) if str(name).strip())
        protagonist = str(canonical_lock.get("protagonist", "")).strip()
        if protagonist:
            names.add(protagonist)
    episode = context.get("episode_execution_sheet") or context.get("episode_outline")
    if isinstance(episode, dict):
        for key in ("required_character_names", "appearing_character_names"):
            names.update(str(name) for name in episode.get(key, []) if str(name).strip())
        for scene in episode.get("scene_plan", []):
            if isinstance(scene, dict):
                names.update(
                    str(name)
                    for name in scene.get("appearing_character_names", [])
                    if str(name).strip()
                )
    return names


def normalize_episode_contract_list_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Handle normalize episode contract list fields."""
    episode_list_fields = (
        "consumed_child_beats",
        "consumed_child_beat_ids",
        "event_ids",
        "foreshadowing_ids",
        "required_character_names",
        "appearing_character_names",
        "adapted_plot_point_ids",
        "source_fact_ids",
        "unresolved_threads_after_episode",
        "scene_plan",
        "prop_continuity_plan",
        "fact_transitions",
    )
    scene_list_fields = (
        "appearing_character_names",
        "must_include_beats",
        "visible_space_tokens",
    )
    narration_list_fields = (
        "approved_flashback_time_deviation_ids",
        "approved_os_time_deviation_ids",
        "visualized_time_deviation_ids",
        "deleted_or_rewritten_time_deviation_ids",
    )
    density_list_fields = (
        "must_cover_beats",
        "optional_compression_beats",
        "scene_char_budgets",
    )

    def normalize_present_list_fields(container: dict[str, Any], fields: tuple[str, ...]) -> None:
        """Handle normalize present list fields."""
        for key in fields:
            if key not in container or isinstance(container[key], list):
                continue
            container[key] = [] if container[key] is None else [container[key]]

    episodes = data.get("episode_outlines")
    if episodes is None or isinstance(episodes, list):
        normalized_episodes = episodes
    else:
        normalized_episodes = [episodes]
    if not isinstance(normalized_episodes, list):
        return data

    output = dict(data)
    output["episode_outlines"] = normalized_episodes
    repaired_episodes: list[Any] = []
    for item in normalized_episodes:
        if not isinstance(item, dict):
            repaired_episodes.append(item)
            continue
        episode = dict(item)
        episode.setdefault("prop_continuity_plan", [])
        normalize_present_list_fields(episode, episode_list_fields)

        scenes: list[Any] = []
        for raw_scene in episode.get("scene_plan", []):
            if not isinstance(raw_scene, dict):
                scenes.append(raw_scene)
                continue
            scene = dict(raw_scene)
            normalize_present_list_fields(scene, scene_list_fields)
            scenes.append(scene)
        if "scene_plan" in episode:
            episode["scene_plan"] = scenes

        narration_plan = episode.get("narration_device_plan")
        if isinstance(narration_plan, dict):
            narration_plan = dict(narration_plan)
            normalize_present_list_fields(narration_plan, narration_list_fields)
            episode["narration_device_plan"] = narration_plan

        density_plan = episode.get("target_script_density")
        if isinstance(density_plan, dict):
            density_plan = dict(density_plan)
            normalize_present_list_fields(density_plan, density_list_fields)
            scene_budgets: list[Any] = []
            for raw_budget in density_plan.get("scene_char_budgets", []):
                if not isinstance(raw_budget, dict):
                    scene_budgets.append(raw_budget)
                    continue
                budget = dict(raw_budget)
                normalize_present_list_fields(budget, ("must_cover_beat_ids",))
                scene_budgets.append(budget)
            if "scene_char_budgets" in density_plan:
                density_plan["scene_char_budgets"] = scene_budgets
            episode["target_script_density"] = density_plan
        repaired_episodes.append(episode)
    output["episode_outlines"] = repaired_episodes
    return output


def _normalized_evidence_match_text(value: Any) -> str:
    """Handle normalized evidence match text."""
    return re.sub(r"[\s△▲▽▼，。！？：；、,.:;!?\-—“”「」『』'\"]+", "", str(value or ""))


def _script_evidence_candidates(script: str) -> list[str]:
    """Handle script evidence candidates."""
    candidates: list[str] = []
    for raw_line in script.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        candidates.append(line)
        for match in re.finditer(r"[^。！？\n]+[。！？]?", line):
            clause = match.group(0).strip()
            if clause and clause != line:
                candidates.append(clause)
    return list(dict.fromkeys(candidates))


def reanchor_completed_effect_evidence(value: dict[str, Any]) -> dict[str, Any]:
    """Handle reanchor completed effect evidence."""
    script = str(value.get("final_script", ""))
    continuity = value.get("continuity_update")
    if not script or not isinstance(continuity, dict):
        return value
    evidence_items = continuity.get("completed_effect_evidence")
    if not isinstance(evidence_items, list):
        return value
    candidates = _script_evidence_candidates(script)
    repaired_items: list[Any] = []
    changed = False
    for raw_item in evidence_items:
        if not isinstance(raw_item, dict):
            repaired_items.append(raw_item)
            continue
        item = dict(raw_item)
        evidence = str(item.get("evidence_span", "")).strip()
        if len(evidence) >= 4 and evidence in script:
            repaired_items.append(item)
            continue
        stripped = evidence.lstrip("△▲▽▼ ")
        if len(stripped) >= 4 and stripped in script:
            item["evidence_span"] = stripped
            repaired_items.append(item)
            changed = True
            continue
        normalized_evidence = _normalized_evidence_match_text(evidence)
        if len(normalized_evidence) < 10:
            repaired_items.append(item)
            continue
        scored: list[tuple[float, str]] = []
        for candidate in candidates:
            normalized_candidate = _normalized_evidence_match_text(candidate)
            if len(normalized_candidate) < 8:
                continue
            length_ratio = len(normalized_candidate) / max(1, len(normalized_evidence))
            if not 0.55 <= length_ratio <= 1.8:
                continue
            score = difflib.SequenceMatcher(
                None,
                normalized_evidence,
                normalized_candidate,
                autojunk=False,
            ).ratio()
            scored.append((score, candidate))
        scored.sort(key=lambda item: (item[0], -len(item[1])), reverse=True)
        best_score = scored[0][0] if scored else 0.0
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        if scored and best_score >= 0.86 and (best_score - second_score >= 0.05 or best_score >= 0.94):
            item["evidence_span"] = scored[0][1]
            changed = True
        repaired_items.append(item)
    if not changed:
        return value
    output = dict(value)
    next_continuity = dict(continuity)
    next_continuity["completed_effect_evidence"] = repaired_items
    output["continuity_update"] = next_continuity
    return output


def normalize_stage_output_with_report(
    stage_id: str,
    data: dict[str, Any],
    *,
    normalization_context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Handle normalize stage output with report."""
    initial = json.loads(json.dumps(data, ensure_ascii=False))
    current = data
    operations: list[dict[str, Any]] = []

    def apply(operation: str, function: Any) -> None:
        """Handle apply."""
        nonlocal current
        before = json.loads(json.dumps(current, ensure_ascii=False))
        after = function(current)
        if after != before:
            operations.append(
                {
                    "operation": operation,
                    "changed_paths": sorted(set(_changed_json_paths(before, after))),
                }
            )
        current = after

    if stage_id == "01_novel_summary" and "key_events" not in current:
        def fill_key_events(value: dict[str, Any]) -> dict[str, Any]:
            """Handle fill key events."""
            key_events: list[Any] = []
            for chapter in value.get("chapter_summaries", []):
                if isinstance(chapter, dict):
                    key_events.extend(chapter.get("key_events", []))
            if not key_events:
                return value
            output = dict(value)
            output["key_events"] = key_events
            return output

        apply("normalize_novel_summary_key_events", fill_key_events)
    if stage_id == "04a_flashback_screening" and isinstance(current, dict):
        apply("normalize_flashback_screening_derived_fields", normalize_flashback_screening_derived_fields)
    if stage_id == "05_plot_character_adaptation" and isinstance(current, dict):
        apply("normalize_event_child_beats", normalize_event_child_beats)

        def normalize_prop_registry_optional_fields(value: dict[str, Any]) -> dict[str, Any]:
            """Handle normalize prop registry optional fields."""
            registry = value.get("prop_registry")
            if not isinstance(registry, list):
                return value
            repaired: list[Any] = []
            for raw_item in registry:
                if not isinstance(raw_item, dict):
                    repaired.append(raw_item)
                    continue
                item = dict(raw_item)
                for key in ("created_from_event_id", "replaces_prop_id", "parent_container_id"):
                    if item.get(key) is None:
                        item[key] = ""
                terminal_states = item.get("terminal_states")
                if terminal_states is None:
                    item["terminal_states"] = []
                elif not isinstance(terminal_states, list):
                    item["terminal_states"] = [terminal_states]
                repaired.append(item)
            if repaired == registry:
                return value
            output = dict(value)
            output["prop_registry"] = repaired
            return output

        apply("normalize_prop_registry_optional_fields", normalize_prop_registry_optional_fields)

        def normalize_prop_replacement_dag(value: dict[str, Any]) -> dict[str, Any]:
            """Handle normalize prop replacement dag."""
            registry = value.get("prop_registry")
            if not isinstance(registry, list):
                return value
            by_id = {
                str(item.get("prop_id", "")).strip(): item
                for item in registry
                if isinstance(item, dict) and str(item.get("prop_id", "")).strip()
            }
            repaired: list[Any] = []
            changed = False
            for raw_item in registry:
                if not isinstance(raw_item, dict):
                    repaired.append(raw_item)
                    continue
                item = dict(raw_item)
                prop_id = str(item.get("prop_id", "")).strip()
                replaced_id = str(item.get("replaces_prop_id", "")).strip()
                if replaced_id:
                    target = by_id.get(replaced_id)
                    try:
                        created_episode = int(item.get("created_episode", 0) or 0)
                        target_episode = int((target or {}).get("created_episode", 0) or 0)
                    except (TypeError, ValueError):
                        created_episode = 0
                        target_episode = 0
                    if (
                        replaced_id == prop_id
                        or target is None
                        or created_episode <= 0
                        or target_episode <= 0
                        or target_episode >= created_episode
                    ):
                        item["replaces_prop_id"] = ""
                        changed = True
                repaired.append(item)
            if not changed:
                return value
            output = dict(value)
            output["prop_registry"] = repaired
            return output

        apply("normalize_prop_replacement_dag", normalize_prop_replacement_dag)
    if stage_id == "06_script_outline_design" and isinstance(current, dict):
        apply("normalize_script_outline_episode_budget", normalize_script_outline_episode_budget)
        apply(
            "normalize_script_outline_macro_arc_boundaries",
            lambda value: normalize_script_outline_macro_arc_boundaries(
                value,
                macro_arcs=(normalization_context or {}).get("macro_arcs", []),
            ),
        )
        apply("normalize_script_outline_terminal_block_fields", normalize_script_outline_terminal_block_fields)
    if stage_id == "07_episode_planning" and isinstance(current, dict):
        apply("normalize_episode_contract_list_fields", normalize_episode_contract_list_fields)

        def join_canonical_transaction_actions(value: dict[str, Any]) -> dict[str, Any]:
            """Handle join canonical transaction actions."""
            context = normalization_context or {}
            options = context.get("episode_event_options")
            if not isinstance(options, list):
                return value
            action_by_id = {
                str(transaction.get("transaction_id") or transaction.get("child_beat_id", "")).strip(): str(
                    transaction.get("action", "")
                ).strip()
                for option in options
                if isinstance(option, dict)
                for transaction in option.get("authorized_transactions", []) or []
                if isinstance(transaction, dict)
                and str(transaction.get("transaction_id") or transaction.get("child_beat_id", "")).strip()
            }
            episodes = value.get("episode_outlines")
            if not isinstance(episodes, list):
                return value
            next_episodes: list[Any] = []
            changed = False
            for raw_episode in episodes:
                if not isinstance(raw_episode, dict):
                    next_episodes.append(raw_episode)
                    continue
                episode = dict(raw_episode)
                transaction_ids = [
                    str(item).strip()
                    for item in episode.get("consumed_child_beat_ids", []) or []
                    if str(item).strip()
                ]
                canonical_actions = [
                    action_by_id[transaction_id]
                    for transaction_id in transaction_ids
                    if transaction_id in action_by_id and action_by_id[transaction_id]
                ]
                if episode.get("consumed_child_beats") != canonical_actions:
                    episode["consumed_child_beats"] = canonical_actions
                    changed = True
                next_episodes.append(episode)
            if not changed:
                return value
            output = dict(value)
            output["episode_outlines"] = next_episodes
            return output

        apply("join_canonical_transaction_actions", join_canonical_transaction_actions)
    if stage_id == "08_script_body_generation" and isinstance(current, dict):
        def normalize_delta_change_lists(value: dict[str, Any]) -> dict[str, Any]:
            """Handle normalize delta change lists."""
            output = dict(value)
            state = dict(output.get("state_update", {}) or {})

            def normalize_changes(items: Any) -> list[Any]:
                """Handle normalize changes."""
                return items if isinstance(items, list) else ([] if items is None else [items])

            for key in ("audience_fact_changes", "character_knowledge_changes", "private_fact_changes"):
                state[key] = normalize_changes(state.get(key))
            if state.get("next_episode_bridge") is None:
                state["next_episode_bridge"] = ""
            output["state_update"] = state
            continuity = dict(output.get("continuity_update", {}) or {})
            completed_beats = continuity.get("completed_beat_ids")
            continuity["completed_beat_ids"] = (
                completed_beats
                if isinstance(completed_beats, list)
                else ([] if completed_beats is None else [completed_beats])
            )
            if "completed_effect_evidence" in continuity:
                continuity["completed_effect_evidence"] = normalize_changes(
                    continuity.get("completed_effect_evidence")
                )
            for key in ("foreshadowing_changes", "open_thread_changes", "prop_state_changes"):
                continuity[key] = normalize_changes(continuity.get(key))
            scene_boundary_check = dict(continuity.get("scene_boundary_check", {}) or {})
            if scene_boundary_check.get("merge_note") is None:
                scene_boundary_check["merge_note"] = ""
            continuity["scene_boundary_check"] = scene_boundary_check
            output["continuity_update"] = continuity
            return output

        apply("normalize_delta_change_lists", normalize_delta_change_lists)
        script_operations = (("clean_final_script", parsers.clean_final_script),)
        for operation, function in script_operations:
            def normalize_script_field(value: dict[str, Any], fn: Any = function) -> dict[str, Any]:
                """Handle normalize script field."""
                output = dict(value)
                output["final_script"] = fn(str(value.get("final_script", "")))
                return output

            apply(operation, normalize_script_field)
        apply("reanchor_completed_effect_evidence", reanchor_completed_effect_evidence)
        apply("normalize_script_last_scene_state_list_fields", normalize_script_last_scene_state_list_fields)

    before_hash = sha256_text(json.dumps(initial, ensure_ascii=False, sort_keys=True))
    after_hash = sha256_text(json.dumps(current, ensure_ascii=False, sort_keys=True))
    changed_paths = sorted({path for item in operations for path in item["changed_paths"]})
    report = {
        "status": "CHANGED" if operations else "UNCHANGED",
        "before_sha256": before_hash,
        "after_sha256": after_hash,
        "operation_count": len(operations),
        "changed_paths": changed_paths,
        "operations": operations,
    }
    return current, report


def normalize_stage_output(
    stage_id: str,
    data: dict[str, Any],
    *,
    normalization_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Handle normalize stage output."""
    normalized, _report = normalize_stage_output_with_report(
        stage_id,
        data,
        normalization_context=normalization_context,
    )
    return normalized


def migrate_stage_output_before_projection(stage_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Handle migrate stage output before projection."""
    if stage_id == "08_script_body_generation":
        return continuity_ledger_v2.normalize_episode_delta(data)
    return data


def normalize_and_project_stage_output(
    stage_id: str,
    data: dict[str, Any],
    *,
    projection_profile: str | None,
    normalization_context: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Handle normalize and project stage output."""
    normalized, report = normalize_stage_output_with_report(
        stage_id,
        data,
        normalization_context=normalization_context,
    )
    projected, discarded = stage_contracts.project_contract_data(
        stage_id,
        normalized,
        profile=projection_profile,
    )
    prefix = f"{stage_id}."
    discarded_paths = [
        item["path"][len(prefix):] if item["path"].startswith(prefix) else item["path"]
        for item in discarded
    ]
    report = {
        **report,
        "after_projection_sha256": sha256_text(json.dumps(projected, ensure_ascii=False, sort_keys=True)),
        "discarded_trace_paths": discarded_paths,
        "discarded_trace_fields": discarded,
    }
    return projected, report


def call_stage(
    paths: RunPaths,
    stage: dict[str, Any],
    values: dict[str, Any],
    *,
    dry_run: bool,
    llm_script_path: Path | None,
    timeout: int,
    artifact_id: str | None = None,
    force_reuse: bool = False,
    prompt_override: str | None = None,
    contract_projection_profile: str | None = None,
) -> dict[str, Any]:
    """Handle call stage."""
    stage_id = stage["stage_id"]
    artifact_id = artifact_id or stage_id
    update_run_state(paths, status="running", current_artifact=artifact_id)
    clean_path = paths.outputs / f"{artifact_id}.clean.json"
    manifest_path = paths.manifests / f"{artifact_id}.manifest.json"
    if "target_episodes" not in values and isinstance(values.get("run_config"), dict):
        values = {
            **values,
            "target_episodes": int(values["run_config"].get("target_episodes", DEFAULT_TARGET_EPISODES)),
        }
    if stage_id == "08_script_body_generation" and "episode_execution_sheet" not in values:
        legacy_continuity = values.get("compact_continuity_context") or values.get("continuity_ledger") or {}
        values = {
            "episode_execution_sheet": values.get("episode_outline", {}),
            "recent_episode_scripts": [],
            "active_continuity_view": legacy_continuity if isinstance(legacy_continuity, dict) else {},
            "future_event_reservations": values.get("remaining_episode_plan", []),
            "relevant_source_context": {
                "source_facts": values.get("source_fact_ledger", []),
                "approved_time_deviations": (
                    (values.get("flashback_screening") or {}).get("retained_time_deviations", [])
                ),
                "protagonist_action_boundary": values.get("protagonist_action_boundary", {}),
            },
        }
    if prompt_override is None:
        prompt_template = read_text(PROJECT_ROOT / stage["prompt_file"])
        prompt = prompt_renderer.render_template(prompt_template, values)
    else:
        prompt = prompt_override
    if force_reuse:
        if not clean_path.exists():
            raise FileNotFoundError(f"Cannot reuse missing artifact: {clean_path}")
        reused_clean = json.loads(read_text(clean_path))
        projected, unmapped = stage_contracts.project_contract_data(
            stage_id,
            migrate_stage_output_before_projection(stage_id, reused_clean),
            profile=contract_projection_profile,
        )
        write_unmapped_fields_report(
            paths,
            artifact_id=artifact_id,
            stage_id=stage_id,
            fields=unmapped,
        )
        data, normalization_report = normalize_and_project_stage_output(
            stage_id,
            projected,
            projection_profile=contract_projection_profile,
            normalization_context=values,
        )
        write_normalization_report(
            paths,
            artifact_id=artifact_id,
            stage_id=stage_id,
            report=normalization_report,
        )
        validate_projection_contract(
            paths,
            artifact_id=artifact_id,
            stage_id=stage_id,
            data=data,
            contract_profile=contract_projection_profile,
        )
        parser_report_path = paths.parsed / "parser_reports" / f"{artifact_id}.json"
        if not parser_report_path.exists():
            write_parser_report(
                paths,
                artifact_id=artifact_id,
                stage_id=stage_id,
                report=unchanged_parser_report(source="canonical_clean_reuse"),
            )
        if data != reused_clean:
            write_json(clean_path, data)
            update_manifest_for_deterministic_repair(
                manifest_path,
                stage=stage,
                output_hash=sha256_text(json.dumps(data, ensure_ascii=False, sort_keys=True)),
                repair_info={
                    "repair": "normalize_forced_reuse_clean",
                    "reason": "persist current canonical normalization while preserving original LLM provenance",
                },
            )
        return data
    if clean_path.exists() and manifest_path.exists():
        try:
            manifest = json.loads(read_text(manifest_path))
        except json.JSONDecodeError:
            manifest = {}
        if cached_artifact_matches(
            manifest,
            dry_run=dry_run,
            prompt=prompt,
            values=values,
            llm_script_path=llm_script_path,
            stage=stage,
            output_path=clean_path,
        ):
            projected, unmapped = stage_contracts.project_contract_data(
                stage_id,
                migrate_stage_output_before_projection(stage_id, json.loads(read_text(clean_path))),
                profile=contract_projection_profile,
            )
            write_unmapped_fields_report(
                paths,
                artifact_id=artifact_id,
                stage_id=stage_id,
                fields=unmapped,
            )
            data, normalization_report = normalize_and_project_stage_output(
                stage_id,
                projected,
                projection_profile=contract_projection_profile,
                normalization_context=values,
            )
            write_normalization_report(
                paths,
                artifact_id=artifact_id,
                stage_id=stage_id,
                report=normalization_report,
            )
            validate_projection_contract(
                paths,
                artifact_id=artifact_id,
                stage_id=stage_id,
                data=data,
                contract_profile=contract_projection_profile,
            )
            parser_report_path = paths.parsed / "parser_reports" / f"{artifact_id}.json"
            if not parser_report_path.exists():
                write_parser_report(
                    paths,
                    artifact_id=artifact_id,
                    stage_id=stage_id,
                    report=unchanged_parser_report(source="canonical_clean_cache"),
                )
            write_json(clean_path, data)
            output_hash = sha256_text(json.dumps(data, ensure_ascii=False, sort_keys=True))
            if manifest.get("output_sha256") != output_hash:
                write_manifest(
                    manifest_path,
                    stage=stage,
                    artifact_id=artifact_id,
                    values=values,
                    prompt=prompt,
                    output_hash=output_hash,
                    dry_run=dry_run,
                    llm_script=str(llm_script_path or ""),
                    llm_runtime_options=llm_client.llm_runtime_options(llm_script_path, stage_id=stage_id),
                )
            return data
        invalidate_artifact_cache(paths, artifact_id)
    elif clean_path.exists() or manifest_path.exists():
        invalidate_artifact_cache(paths, artifact_id)
    write_text(paths.prompts / f"{artifact_id}.prompt.md", prompt)

    if dry_run:
        dry_payload = dry_run_payload(stage_id, values)
        localized_payload = llm_schema_localization.localize_prompt_value("", dry_payload)
        canonical_payload, localization_report = llm_schema_localization.canonicalize_stage_output(
            stage_id,
            localized_payload,
        )
        write_localization_report(paths, artifact_id, localization_report)
        canonical_payload, unmapped = stage_contracts.project_contract_data(
            stage_id,
            migrate_stage_output_before_projection(stage_id, canonical_payload),
            profile=contract_projection_profile,
        )
        write_unmapped_fields_report(
            paths,
            artifact_id=artifact_id,
            stage_id=stage_id,
            fields=unmapped,
        )
        data, normalization_report = normalize_and_project_stage_output(
            stage_id,
            canonical_payload,
            projection_profile=contract_projection_profile,
            normalization_context=values,
        )
        write_normalization_report(
            paths,
            artifact_id=artifact_id,
            stage_id=stage_id,
            report=normalization_report,
        )
        validate_projection_contract(
            paths,
            artifact_id=artifact_id,
            stage_id=stage_id,
            data=data,
            contract_profile=contract_projection_profile,
        )
        write_parser_report(
            paths,
            artifact_id=artifact_id,
            stage_id=stage_id,
            report=unchanged_parser_report(source="dry_run_fixture"),
        )
        raw = json.dumps(
            {"dry_run": True, "stage_id": stage_id, "artifact_id": artifact_id, "payload": data},
            ensure_ascii=False,
            indent=2,
        )
        write_text(paths.outputs / f"{artifact_id}.raw.md", raw)
        write_json(clean_path, data)
        write_json(paths.logs / f"{artifact_id}.log.json", {"dry_run": True, "prompt_chars": len(prompt)})
        output_hash = sha256_text(json.dumps(data, ensure_ascii=False, sort_keys=True))
        write_manifest(
            manifest_path,
            stage=stage,
            artifact_id=artifact_id,
            values=values,
            prompt=prompt,
            output_hash=output_hash,
            dry_run=True,
            llm_script=str(llm_script_path or ""),
            llm_runtime_options=llm_client.llm_runtime_options(llm_script_path, stage_id=stage_id),
        )
        return data

    if llm_script_path is None:
        raise ValueError("llm_script_path is required for non-dry-run stage calls")
    attempt_session_dir = None
    if paths.attempts is not None:
        attempt_session_dir = paths.attempts / artifact_id / f"call_{time.time_ns()}"
    result = llm_client.call_llm(
        prompt,
        llm_script=llm_script_path,
        cwd=PROJECT_ROOT,
        timeout=timeout,
        stage_id=stage_id,
        attempts_dir=attempt_session_dir,
    )
    write_text(paths.outputs / f"{artifact_id}.raw.md", result.raw)
    write_json(
        paths.logs / f"{artifact_id}.log.json",
        {
            "dry_run": False,
            "returncode": result.returncode,
            "elapsed_seconds": result.elapsed_seconds,
            "prompt_chars": len(prompt),
            "stderr": result.stderr,
            "attempt_dirs": list(result.attempt_dirs),
        },
    )
    try:
        parsed_data, parser_report = parsers.parse_json_payload_with_report(result.clean)
    except Exception as exc:
        if result.attempt_dirs:
            write_json(
                Path(result.attempt_dirs[-1]) / "pipeline_parser_result.json",
                {"status": "FAIL", "stage_id": stage_id, "artifact_id": artifact_id, "error": str(exc)},
            )
        write_parser_report(
            paths,
            artifact_id=artifact_id,
            stage_id=stage_id,
            report={
                **unchanged_parser_report(source="llm_response"),
                "status": "FAIL",
                "before_sha256": sha256_text(result.clean),
                "parse_error": str(exc),
            },
        )
        write_localization_report(paths, artifact_id, failed_localization_report(stage_id, exc))
        raise
    write_parser_report(
        paths,
        artifact_id=artifact_id,
        stage_id=stage_id,
        report={"source": "llm_response", **parser_report},
    )
    try:
        canonical_data, localization_report = llm_schema_localization.canonicalize_stage_output(stage_id, parsed_data)
    except llm_schema_localization.LocalizationConflictError as exc:
        write_localization_report(paths, artifact_id, exc.report)
        raise
    write_localization_report(paths, artifact_id, localization_report)
    canonical_data, unmapped = stage_contracts.project_contract_data(
        stage_id,
        migrate_stage_output_before_projection(stage_id, canonical_data),
        profile=contract_projection_profile,
    )
    write_unmapped_fields_report(
        paths,
        artifact_id=artifact_id,
        stage_id=stage_id,
        fields=unmapped,
    )
    data, normalization_report = normalize_and_project_stage_output(
        stage_id,
        canonical_data,
        projection_profile=contract_projection_profile,
        normalization_context=values,
    )
    write_normalization_report(
        paths,
        artifact_id=artifact_id,
        stage_id=stage_id,
        report=normalization_report,
    )
    validate_projection_contract(
        paths,
        artifact_id=artifact_id,
        stage_id=stage_id,
        data=data,
        contract_profile=contract_projection_profile,
    )
    write_json(clean_path, data)
    output_hash = sha256_text(json.dumps(data, ensure_ascii=False, sort_keys=True))
    write_manifest(
        manifest_path,
        stage=stage,
        artifact_id=artifact_id,
        values=values,
        prompt=prompt,
        output_hash=output_hash,
        dry_run=False,
        llm_script=str(llm_script_path),
        llm_runtime_options=llm_client.llm_runtime_options(llm_script_path, stage_id=stage_id),
    )
    if result.attempt_dirs:
        write_json(
            Path(result.attempt_dirs[-1]) / "pipeline_parser_result.json",
            {
                "status": "PASS",
                "stage_id": stage_id,
                "artifact_id": artifact_id,
                "clean_output_sha256": output_hash,
            },
        )
    return data


def invalidate_artifact_cache(paths: RunPaths, artifact_id: str) -> None:
    """Handle invalidate artifact cache."""
    targets = [
        paths.prompts / f"{artifact_id}.prompt.md",
        paths.outputs / f"{artifact_id}.raw.md",
        paths.outputs / f"{artifact_id}.clean.json",
        paths.logs / f"{artifact_id}.log.json",
        paths.manifests / f"{artifact_id}.manifest.json",
        paths.parsed / "localization_reports" / f"{artifact_id}.json",
        paths.parsed / "parser_reports" / f"{artifact_id}.json",
        paths.parsed / "unmapped_fields" / f"{artifact_id}.json",
        paths.parsed / "normalization_reports" / f"{artifact_id}.json",
        paths.parsed / "contract_reports" / f"{artifact_id}.contract_report.json",
    ]
    localization_report_removed = False
    parser_report_removed = False
    unmapped_report_removed = False
    normalization_report_removed = False
    for path in targets:
        if path.exists():
            path.unlink()
            if path.parent.name == "localization_reports":
                localization_report_removed = True
            elif path.parent.name == "parser_reports":
                parser_report_removed = True
            elif path.parent.name == "unmapped_fields":
                unmapped_report_removed = True
            elif path.parent.name == "normalization_reports":
                normalization_report_removed = True
    if localization_report_removed:
        refresh_localization_summary(paths)
    if parser_report_removed:
        refresh_parser_summary(paths)
    if unmapped_report_removed:
        refresh_unmapped_fields_summary(paths)
    if normalization_report_removed:
        refresh_normalization_summary(paths)


def normalize_stage_boundary(stage_ref: str | None) -> str | None:
    """Handle normalize stage boundary."""
    if not stage_ref:
        return None
    value = str(stage_ref).strip()
    if value in STAGE_EXECUTION_ORDER:
        return value
    if re.fullmatch(r"\d{2}", value):
        matches = [stage_id for stage_id in STAGE_EXECUTION_ORDER if stage_id.startswith(f"{value}_")]
        if matches:
            return matches[0]
    matches = [stage_id for stage_id in STAGE_EXECUTION_ORDER if stage_id.startswith(value)]
    if len(matches) == 1:
        return matches[0]
    raise ValueError(f"Unknown stage boundary: {stage_ref}")


def stage_index(stage_id: str) -> int:
    """Handle stage index."""
    normalized = normalize_stage_boundary(stage_id)
    if normalized is None:
        raise ValueError("stage_id is required")
    return STAGE_EXECUTION_ORDER.index(normalized)


def stage_after(stage_id: str) -> str | None:
    """Handle stage after."""
    index = stage_index(stage_id)
    if index + 1 >= len(STAGE_EXECUTION_ORDER):
        return None
    return STAGE_EXECUTION_ORDER[index + 1]


def artifact_ids_for_stage(stage_id: str, *, generate_episodes: int) -> list[str]:
    """Handle artifact ids for stage."""
    normalized = normalize_stage_boundary(stage_id)
    if normalized == "08_script_body_generation":
        return [f"08_script_body_generation_ep{episode_num:03d}" for episode_num in range(1, generate_episodes + 1)]
    return [normalized] if normalized else []


def artifact_ids_from_stage(stage_id: str, *, generate_episodes: int) -> list[str]:
    """Handle artifact ids from stage."""
    start = stage_index(stage_id)
    artifact_ids: list[str] = []
    for current in STAGE_EXECUTION_ORDER[start:]:
        artifact_ids.extend(artifact_ids_for_stage(current, generate_episodes=generate_episodes))
    return artifact_ids


def invalidate_from_stage(paths: RunPaths, stage_id: str, *, generate_episodes: int) -> None:
    """Handle invalidate from stage."""
    for artifact_id in artifact_ids_from_stage(stage_id, generate_episodes=generate_episodes):
        invalidate_artifact_cache(paths, artifact_id)


def should_force_reuse(stage_id: str, reuse_through: str | None) -> bool:
    """Handle should force reuse."""
    if not reuse_through:
        return False
    return stage_index(stage_id) <= stage_index(reuse_through)


def completed_stages_through(stage_id: str) -> list[str]:
    """Handle completed stages through."""
    return STAGE_EXECUTION_ORDER[: stage_index(stage_id) + 1]


def write_stage_stop_summary(
    paths: RunPaths,
    *,
    run_id: str,
    stop_after: str,
    run_config: dict[str, Any],
    derived_config: dict[str, Any],
    validation_mode: str,
    metadata: dict[str, Any],
    dry_run: bool,
) -> Path:
    """Handle write stage stop summary."""
    completed_stages = completed_stages_through(stop_after)
    summary = {
        "run_id": run_id,
        "dry_run": bool(dry_run),
        "partial_run": True,
        "stop_after": stop_after,
        "completed_stages": completed_stages,
        "target_episodes": int(run_config["target_episodes"]),
        "generated_episodes": [],
        "run_config": run_config,
        "derived_config": derived_config,
        "validation_mode": validation_mode,
        "source_metadata": metadata,
        "stage_outputs": {
            stage_id: f"outputs/{stage_id}.clean.json"
            for stage_id in completed_stages
            if (paths.outputs / f"{stage_id}.clean.json").exists()
        },
        "config_resolution": "parsed/00a_global_config_resolution.json",
        "run_root": str(paths.root),
    }
    write_json(paths.final / "run_summary.json", summary)
    write_json(paths.final / "manifest_index.json", build_manifest_index(paths, generated_episodes=[]))
    update_run_state(
        paths,
        status="complete",
        current_artifact="",
        stopped_after=stop_after,
        completed_at=datetime.now().isoformat(timespec="seconds"),
    )
    return paths.root


def build_dry_run_dramatic_release_map(target: int) -> dict[str, Any]:
    """Handle build dry run dramatic release map."""
    targets: list[dict[str, Any]] = []
    modes = ["live_character", "live_character", "environment", "live_character", "process"]
    for episode_num in range(1, target + 1):
        mode = modes[(episode_num - 1) % len(modes)]
        targets.append(
            {
                "release_id": dramatic_release.release_id_for_episode(episode_num),
                "episode_num": episode_num,
                "desire": f"主角必须在第{episode_num}集取得一个可核验的新选择空间",
                "obstacle": f"对手或规则当场阻止第{episode_num}次推进",
                "choice": f"主角主动执行第{episode_num}次留证、拒绝或公开反击",
                "immediate_cost": f"主角立即失去第{episode_num}项旧关系便利或安全余地",
                "visible_result": f"第{episode_num}项人物、资源、权力、秘密或关系状态在镜头中改变",
                "hook": f"第{episode_num}项结果引出下一项更具体的新阻力",
                "confrontation_mode": mode,
                "process_only": mode == "process",
                "source_fact_ids": [],
                "required_event_function": "制造独立选择、代价和可见结果",
                "expansion_engine_id": "" if episode_num <= 5 else f"ENGINE_{(episode_num - 1) // 5:02d}",
            }
        )
    return {
        "release_overview": {
            "target_episodes": target,
            "natural_capacity_max": min(target, 30),
            "capacity_gap": max(0, target - 30),
            "opening_strategy": "前三集用现场人物阻力建立主角欲望、选择和可见代价。",
            "process_compression_strategy": "没有人物选择和即时代价的流程节点并入相邻戏剧集。",
            "expansion_strategy": "用新的目标、阻力、选择、代价和结果补足容量，不拆细同一流程。",
        },
        "episode_dramatic_targets": targets,
        "capacity_bridge_units": (
            [
                {
                    "bridge_id": "BRIDGE_01",
                    "episode_range": {"start": 31, "end": target},
                    "new_goal": "主角把个人脱身升级为阻止旧控制关系伤害他人",
                    "new_obstacle": "旧利益关系联合外部规则制造新的现实阻力",
                    "new_choice": "主角公开证据并承担关系彻底破裂的代价",
                    "new_cost": "失去与原家庭和解的最后余地",
                    "new_result": "旧控制结构失去资源或公信力",
                    "source_boundary": "不改变原著行动者、核心伤害和终局因果",
                }
            ]
            if target > 30
            else []
        ),
        "opening_gate": {
            "first_three_live_obstacle_count": 2,
            "first_five_process_only_count": 1,
            "required_early_source_fact_ids": [],
            "gate_reason": "开篇先建立现场人物冲突，再压缩必要流程。",
        },
    }


def dry_run_payload(stage_id: str, values: dict[str, Any]) -> dict[str, Any]:
    """Handle dry run payload."""
    if stage_id == "00a_global_config":
        recommended = merge_run_config(
            values.get("default_run_config") or DEFAULT_RUN_CONFIG,
            values.get("user_overrides") or {},
        )
        return {
            "novel_profile": {
                "genre": "现实情感复仇短剧",
                "core_conflict_type": "亲密关系或熟人社会中的利益压迫与规则反击",
                "target_audience": "偏好强冲突、主动反击和因果回收的短剧受众",
                "adaptation_risks": ["短篇容量不足时容易重复施压", "需保持原著人物行动者和因果关系"],
            },
            "recommended_run_config": recommended,
            "recommendation_reasons": [
                {"field": "target_episodes", "reason": "无用户覆盖时按系统默认40集执行"},
                {"field": "market_tags", "reason": "根据源故事的关系压迫、证据反击和情绪回收提炼"},
            ],
        }
    if stage_id == "01_novel_summary":
        chunks = values.get("chapter_chunks", [])
        return {
            "novel_summary": "主角在源故事核心伤害发生前后获得重新选择的机会，围绕熟人社会压力、利益侵占和公开误解完成反击，并守住自身人生边界。",
            "core_hook": "主角拒绝继续承担污名或代价，让压迫者的规则反噬到压迫者自己身上。",
            "emotional_debts": ["被亲近者背叛", "被公共舆论误解", "个人选择被剥夺", "真相长期被遮蔽"],
            "expansion_assets": ["核心误解机制", "熟人舆论场", "利益链", "见证者网络", "规则反击线", "关系切割线"],
            "immutable_elements": ["核心伤害", "主角主动选择", "压迫者反噬", "真相回收"],
            "potential_subplots": ["证据线", "邻里舆论线", "亲属利益线", "外部规则介入", "见证者转向"],
            "undeveloped_characters": ["关键见证者", "利益相关方", "基层调解者", "外部规则执行者"],
            "open_foreshadowing": ["旧证据", "误传源头", "关键录音", "隐瞒关系"],
            "chapter_summaries": [
                {
                    "chapter_id": item.get("chapter_id"),
                    "title": item.get("title"),
                    "summary": "围绕源故事的核心伤害、舆论压迫和主角反击展开。",
                    "key_events": ["核心伤害出现", "主角拒绝自证", "压迫者开始反噬"],
                }
                for item in chunks[:12]
            ],
            "key_events": [
                {
                    "id": 1,
                    "event": "主角遭遇核心污名或伤害",
                    "characters": ["主角", "核心反派"],
                    "conflict": "名誉与生存空间",
                    "source_hint": "开篇",
                },
                {"id": 2, "event": "主角拒绝按压迫者规则自证", "characters": ["主角"], "conflict": "自证陷阱与主动反击", "source_hint": "开篇"},
                {
                    "id": 3,
                    "event": "围观者和利益相关方扩散压力",
                    "characters": ["主角", "围观者", "利益相关方"],
                    "conflict": "公共误解",
                    "source_hint": "前段",
                },
            ],
        }
    if stage_id == "02_storyline_understanding":
        return {
            "storyline_candidates": [
                {"id": 1, "storyline": "主角从被动承受污名升级为主动拆解压迫系统", "strength": "冲突可循环", "risk": "需要控制重复争吵"},
                {"id": 2, "storyline": "主角切断旧关系并让利益链自曝", "strength": "情绪释放强", "risk": "需保留源故事核心"},
            ],
            "selected_storyline": "主角围绕源故事核心伤害，从拒绝自证开始，逐步让造谣者、既得利益者和旁观者承担各自后果。",
            "core_conflict": "主角的自我边界与熟人社会压迫、利益侵占之间的冲突。",
            "core_hook_structure": ["核心伤害", "拒绝自证", "证据反击", "关系切割", "公开回收"],
            "story_engine": {
                "main_line": "主角拆解源故事压迫机制并守住人生选择。",
                "subplot_lines": ["舆论扩散", "亲属利益", "证据回收", "规则介入"],
                "antagonist_line": "核心反派从私下压迫升级为公开围堵并逐渐露出利益动机。",
                "emotion_line": "主角从不再自证到建立新边界。",
                "growth_line": "主角从被迫反击到主动设定规则。",
                "recurring_hook_mechanism": "每个block都设置压力升级、主角留证、公开反转和新未解问题。",
            },
            "adaptation_capacity": {
                "independent_conflict_unit_count": 12,
                "natural_episode_range": {"min": 24, "max": 40},
                "target_episode_gap": max(0, int(values.get("target_episodes", 40)) - 40),
                "expansion_pressure": "high" if int(values.get("target_episodes", 40)) > 40 else "medium",
                "required_new_engines": ["外部利益链", "见证者转向", "规则反击"],
            },
        }
    if stage_id == "03_plot_character_extract":
        return {
            "source_plot_points": [
                {
                    "id": 1,
                    "title": "核心伤害",
                    "event": "主角被污名或代价压住",
                    "function": "情绪债",
                    "characters": ["主角", "核心反派"],
                    "source_evidence": "开篇",
                    "source_fact_ids": ["SF001"],
                },
                {
                    "id": 2,
                    "title": "拒绝自证",
                    "event": "主角不再按他人规则解释",
                    "function": "反击启动",
                    "characters": ["主角"],
                    "source_evidence": "开篇",
                    "source_fact_ids": ["SF002"],
                },
                {
                    "id": 3,
                    "title": "舆论扩散",
                    "event": "围观者将误解扩大",
                    "function": "外部压力",
                    "characters": ["主角", "围观者"],
                    "source_evidence": "前段",
                    "source_fact_ids": ["SF001"],
                },
                {
                    "id": 4,
                    "title": "证据反转",
                    "event": "旧证据让压迫者露出破绽",
                    "function": "爽点回收",
                    "characters": ["主角", "见证者"],
                    "source_evidence": "中段",
                    "source_fact_ids": ["SF003"],
                },
                {
                    "id": 5,
                    "title": "关系切割",
                    "event": "主角完成边界确认",
                    "function": "结局释放",
                    "characters": ["主角", "关键同盟"],
                    "source_evidence": "后段",
                    "source_fact_ids": ["SF004"],
                },
            ],
            "character_bible": [
                {
                    "name": "主角",
                    "role": "主角",
                    "relationship": "核心受压者",
                    "source_traits": ["冷静", "拒绝自证"],
                    "dramatic_function": "主动反击者",
                },
                {
                    "name": "核心反派",
                    "role": "反派",
                    "relationship": "压迫源",
                    "source_traits": ["操控舆论", "转嫁代价"],
                    "dramatic_function": "压力发动机",
                },
                {
                    "name": "关键同盟",
                    "role": "同盟",
                    "relationship": "被主角争取的人",
                    "source_traits": ["犹豫", "掌握局部事实"],
                    "dramatic_function": "见证与转向",
                },
                {
                    "name": "围观者",
                    "role": "群像",
                    "relationship": "熟人社会压力",
                    "source_traits": ["跟风", "怕担责"],
                    "dramatic_function": "舆论放大器",
                },
            ],
            "character_expandability": [
                {
                    "name": "主角",
                    "desire": "守住人生边界",
                    "fear": "再次被污名吞没",
                    "weakness": "容易被旧关系牵制",
                    "secret": "掌握关键事实",
                    "expand_space": "留证与规则反击升级",
                },
                {
                    "name": "核心反派",
                    "desire": "维持旧秩序和利益",
                    "fear": "谎言被公开",
                    "weakness": "过度依赖熟人舆论",
                    "secret": "隐藏动机",
                    "expand_space": "从私下施压升级为公开围堵",
                },
            ],
            "emotional_debt_chain": [
                {"step": 1, "source_fact": "源故事中的前世伤害", "emotion": "被亲近者背叛", "downstream_lock": "不得改成无关事故"},
                {"step": 2, "source_fact": "主角回到冲突起点", "emotion": "复仇启动", "downstream_lock": "保留核心动机"},
            ],
            "character_action_boundaries": [
                {
                    "name": "主角",
                    "can_change": ["更会留证", "更主动切割"],
                    "cannot_change": ["亲自动手违法伤害他人"],
                    "risk_note": "保持反噬而非加害",
                },
                {"name": "核心反派", "can_change": ["压迫方式升级"], "cannot_change": ["替代源核心伤害功能"], "risk_note": "不能抢走源事件功能"},
            ],
            "source_evidence": [{"id": 1, "quote_or_summary": "源故事开篇核心伤害导致主角行动受限", "supports": [1]}],
            "source_fact_ledger": [
                {
                    "fact_id": "SF001",
                    "actor": "核心反派",
                    "action": "施压",
                    "object": "主角",
                    "result": "主角承受污名",
                    "source_anchor_ids": ["SRC_P0001"],
                    "certainty": "explicit",
                    "interpretation_note": "原著明示，不做额外意图推断",
                },
                {
                    "fact_id": "SF002",
                    "actor": "主角",
                    "action": "拒绝自证",
                    "object": "压迫规则",
                    "result": "反击启动",
                    "source_anchor_ids": ["SRC_P0002"],
                    "certainty": "explicit",
                    "interpretation_note": "原著明示，不做额外意图推断",
                },
                {
                    "fact_id": "SF003",
                    "actor": "关键见证者",
                    "action": "提供证据",
                    "object": "旧事实",
                    "result": "压迫者露出破绽",
                    "source_anchor_ids": ["SRC_P0003"],
                    "certainty": "inferred",
                    "interpretation_note": "模拟数据只用于 dry-run",
                },
                {
                    "fact_id": "SF004",
                    "actor": "主角",
                    "action": "切割关系",
                    "object": "旧利益绑定",
                    "result": "边界确认",
                    "source_anchor_ids": ["SRC_P0004"],
                    "certainty": "explicit",
                    "interpretation_note": "原著明示，不做额外意图推断",
                },
            ],
        }
    if stage_id == "04_adaptation_direction":
        return {
            "adaptation_direction": "保留源故事核心伤害和主角边界，把被动承受改成主动留证、借规则反击和关系切割。",
            "target_tone": "强冲突、快反转、现实压迫、规则反击。",
            "change_principles": [
                {"principle": "主角主动留证", "why": "短漫剧需要即时行动", "impact_on_story": "每集有判断、试探或反击"},
                {"principle": "反派动机前置", "why": "观众需快速站队", "impact_on_story": "压迫升级但保留源人物功能"},
                {"principle": "关键关系转向", "why": "增强情感支撑", "impact_on_story": "同盟和见证者逐步变化"},
            ],
            "must_keep": ["核心伤害", "主角拒绝自证", "压迫者反噬", "真相回收"],
            "can_expand": ["公开误解", "见证者转向", "利益链暴露", "规则介入"],
            "longform_strategy": "按动态block扩写，每个block建立新压力源并回收一个源锚。",
            "market_tag_priority": [
                {"tag": "强冲突", "dramatic_action": "每集压力升级"},
                {"tag": "反转爽点", "dramatic_action": "用证据完成回收"},
                {"tag": "现实压迫", "dramatic_action": "用熟人社会施压"},
                {"tag": "规则反击", "dramatic_action": "主角依法留证"},
            ],
            "originality_boundary": {
                "source_retention_ratio": "核心梗和人物关系保留",
                "original_expansion_ratio": "外部危机和支线半原创",
                "risk_note": "原创扩写不得稀释核心梗和人物功能",
            },
            "source_preservation_contract": {
                "must_preserve": ["核心梗", "情绪债", "主要人物功能"],
                "must_preserve_fact_ids": ["SF001", "SF002", "SF004"],
                "can_expand": ["外部压力", "支线见证者"],
                "per_episode_check": "每集声明源锚和扩写差异",
            },
            "protagonist_action_boundary": {
                "allowed": ["提前避险", "留证", "借规则反击", "撤掉保护"],
                "allowed_active_strategies": ["取证", "公开事实", "拒绝兜底", "资源撤回", "依法处理"],
                "risk_examples": ["违法争议", "隐私争议", "主动反击争议", "公开反噬争议"],
                "risk_response": "按实际动作记录风险，不自动删除或改写事件",
            },
            "event_release_principles": ["终局事件不得早于高潮窗口", "每个block保留至少一个未解决张力", "尾声只做收束不新增主线"],
            "epilogue_budget": {"max_episodes": 2, "allowed_functions": ["情绪回收", "关系切割", "新生活确认"]},
            "retention_rules": ["前10集密集爽点", "每10集一次大反击", "每个篇章结尾强钩子"],
            "forbidden_changes": ["不能改掉核心伤害", "不能替换源人物功能", "不能让主角长期被动挨打"],
        }
    if stage_id == "04a_flashback_screening":
        return {
            "flashback_overview": {
                "source_type": "短篇小说",
                "genre_tags": values.get("market_tags") or ["强冲突", "现实复仇"],
                "total_time_deviation_count": 1,
                "s_count": 0,
                "a_count": 1,
                "b_count": 0,
                "c_count": 0,
            },
            "retained_time_deviations": [
                {
                    "id": "td_a_001",
                    "grade": "A",
                    "position": "源故事关键转折处",
                    "characters": ["主角", "核心反派"],
                    "content_summary": "旧事实真相必须在反转前短暂揭示",
                    "q1_structure_necessity": "否，拿掉不影响整体顺叙框架",
                    "q2_information_necessity": "是，观众此刻必须知道旧事实来源",
                    "decision": "有条件保留",
                    "reason": "作为关键反转的信息回收，优先压短成一段连续闪回",
                    "quota_count": 1,
                }
            ],
            "rewrite_time_deviations": [],
            "deleted_time_deviations": [],
            "quota_policy": {
                "used_quota": 0,
                "new_a_quota_count": 1,
                "cumulative_a_quota_count": 1,
                "quota_limit": validators.NARRATION_DEVICE_BUDGET_OS_FLASHBACK,
                "remaining_quota": validators.NARRATION_DEVICE_BUDGET_OS_FLASHBACK - 1,
            },
        }
    if stage_id == "04b_dramatic_release_map":
        payload = build_dry_run_dramatic_release_map(
            int(values.get("target_episodes", DEFAULT_TARGET_EPISODES))
        )
        if values.get("_stage04b_foundation"):
            return {
                "release_overview": payload["release_overview"],
                "capacity_bridge_units": payload["capacity_bridge_units"],
                "opening_gate": payload["opening_gate"],
            }
        target_spec = values.get("_stage04b_target_spec")
        if isinstance(target_spec, dict):
            start_episode = int(target_spec["start_episode"])
            end_episode = int(target_spec["end_episode"])
            return {
                "episode_dramatic_targets": payload["episode_dramatic_targets"][
                    start_episode - 1 : end_episode
                ]
            }
        return payload
    if stage_id == "05_plot_character_adaptation":
        event_spec = values.get("_stage05_event_spec")
        if isinstance(event_spec, dict):
            return {
                "event_pool": _build_dry_run_event_chunk(event_spec),
            }
        target = int(values.get("target_episodes", DEFAULT_TARGET_EPISODES))
        derived = values.get("derived_config") or derive_run_config(DEFAULT_RUN_CONFIG)
        blocks = build_longform_blocks(target)
        low, _high = validators.parse_numeric_range(str(derived.get("event_pool_size", "24-32")))
        return {
            "macro_arcs": build_macro_arcs(target),
            "event_pool": _build_dry_run_event_pool(low, blocks),
            "conflict_engine": {
                "pressure_templates": [
                    {
                        "template_id": "P1",
                        "template_name": "熟人道德绑架",
                        "mode": "以关系施压",
                        "applicable_arc_ids": [1],
                        "variant_examples": ["公开要求主角服从"],
                    }
                ],
                "counterattack_templates": [
                    {
                        "template_id": "C1",
                        "template_name": "证据反击",
                        "mode": "用可核验证据止损",
                        "applicable_arc_ids": [1],
                        "variant_examples": ["当场展示原始记录"],
                    }
                ],
                "reversal_templates": [
                    {
                        "template_id": "R1",
                        "template_name": "后果反噬",
                        "mode": "压迫者承担自身行为后果",
                        "applicable_arc_ids": [1],
                        "variant_examples": ["旧规则维护者失去既得利益"],
                    }
                ],
                "anti_monotony_rules": ["同一冲突模式不得连续超过配置上限", "每个block至少切换一次胜负结构", "终局资产保留到高潮窗口"],
            },
            "expanded_character_network": [
                {
                    "name": "围观者联盟",
                    "camp": "外部压迫",
                    "function": "把私人矛盾社会化",
                    "relationship_pressure": "用熟人舆论逼主角自证",
                    "secret_chain": "跟风传播的利益动机",
                },
                {
                    "name": "关键见证者",
                    "camp": "见证者",
                    "function": "提供真相支点",
                    "relationship_pressure": "在公开站队和自保之间摇摆",
                    "secret_chain": "掌握旧证据",
                },
                {
                    "name": "规则执行者",
                    "camp": "外部规则",
                    "function": "让证据产生后果",
                    "relationship_pressure": "要求双方给出可核验材料",
                    "secret_chain": "可触发公开处理",
                },
            ],
            "foreshadowing_pool": [
                {
                    "id": idx,
                    "setup": f"伏笔{idx}投放",
                    "mislead": "观众以为是小事",
                    "payoff": f"第{idx * 8}集回收",
                    "related_arc": (idx - 1) % 8 + 1,
                }
                for idx in range(1, 9)
            ],
            "prop_registry": [
                {
                    "prop_id": "PROP_EVIDENCE_PHONE",
                    "prop_name": "留证手机",
                    "entity_kind": "item",
                    "created_episode": 1,
                    "activation_episode": 1,
                    "initial_state": {"holder": "主角", "location": "主角手中", "status": "可用"},
                    "created_from_event_id": 1,
                    "replaces_prop_id": "",
                    "parent_container_id": "",
                    "terminal_states": ["销毁", "作废"],
                }
            ],
            "mapping_trace": [
                {
                    "asset_id": "macro_arcs",
                    "source_plot_point_ids": [1, 2, 3],
                    "change_type": "长篇扩容",
                    "reason": "把源故事机制拆成8个篇章",
                },
                {
                    "asset_id": "event_pool",
                    "source_plot_point_ids": [1, 2, 3, 4, 5],
                    "change_type": "事件池扩写",
                    "reason": "支撑目标集数连续冲突",
                },
            ],
        }
    if stage_id == "06_script_outline_design":
        target = int(values.get("target_episodes", DEFAULT_TARGET_EPISODES))
        blocks = build_longform_blocks(target)
        return {
            "global_outline": "主角从核心伤害现场拒绝自证开始，沿熟人舆论、利益链、证据回收和规则介入逐步推进，让压迫者承担后果并完成关系切割。",
            "longform_blocks": blocks,
            "phase_breakdown": {
                item["phase"]: {
                    "episode_range": {"start": item["start_episode"], "end": item["end_episode"]},
                    "dramatic_goal": item["goal"],
                    "stage_antagonist": item["antagonist"],
                    "foreshadowing_plan": item["foreshadowing_plan"],
                    "hook_strategy": item["hook"],
                }
                for item in blocks
            },
            "episode_budget": [
                {
                    "phase": item["phase"],
                    "start_episode": item["start_episode"],
                    "end_episode": item["end_episode"],
                    "episode_count": item["episode_count"],
                }
                for item in blocks
            ],
            "event_release_schedule": [
                {
                    "block_id": item["block_id"],
                    "episode_range": {"start": item["start_episode"], "end": item["end_episode"]},
                    "available_event_ids": [
                            event.get("id")
                            for event in values.get("event_pool", [])
                            if int(event.get("target_block", 0)) == item["block_id"]
                        ],
                    "reserved_payoff": item["hook"],
                    "forbidden_early_events": "不得使用后续block的A/S级事件",
                }
                for item in blocks
            ],
            "block_event_plan": [
                {
                    "block_id": item["block_id"],
                    "must_use_event_ids": [
                            event.get("id")
                            for event in values.get("event_pool", [])
                            if int(event.get("target_block", 0)) == item["block_id"]][:3
                        ],
                    "conflict_modes": ["rumor", "relationship_pressure", "rule_counterattack"],
                    "source_anchor_goal": "每集保留源情绪债或核心机制",
                }
                for item in blocks
            ],
            "climax_guardrails": {
                "major_climax_window": (values.get("derived_config") or {}).get("major_climax_window", "终局前段"),
                "final_climax_not_before_episode": (
                    validators.parse_numeric_range(
                        str((values.get("derived_config") or {}).get("major_climax_window", "1-1"))
                    )[0]
                ),
                "epilogue_max_episodes": (values.get("derived_config") or {}).get("epilogue_max_episodes", 2),
            },
            "block_state_plan": [
                {
                    "block_id": item["block_id"],
                    "entry_state": "上一block钩子未解决",
                    "exit_state": "本block核心压力被反噬并留下新问题",
                    "character_state_curve": "主角更清醒，反派付出代价但继续升级",
                    "handoff_to_next_block": item["hook"],
                }
                for item in blocks
            ],
            "qa_rules": ["每10集至少一次大爽点", "每个block必须有投放和回收", "不得连续3集无状态变化"],
            "adaptation_capacity_warning": {
                "status": "WARN" if target > 40 else "PASS",
                "target_episodes": target,
                "natural_max_episodes": 40,
                "gap": max(0, target - 40),
                "strategy": "保留目标集数，用外部利益链和见证者转向扩容。",
            },
        }
    if stage_id == "07_episode_planning":
        scope = values.get("episode_planning_scope") if isinstance(values.get("episode_planning_scope"), dict) else {}
        if scope.get("mode") == "internal_block":
            current_block = scope.get("current_block") or {}
            start = int(current_block.get("start_episode", scope.get("start_episode", 1)))
            end = int(current_block.get("end_episode", scope.get("end_episode", start)))
            global_target = int(
                scope.get("global_target_episodes", values.get("target_episodes", DEFAULT_TARGET_EPISODES)),
            )
            episodes = [
                item
                for item in build_episode_outlines(
                    global_target,
                    event_pool=values.get("event_pool"),
                    foreshadowing_pool=values.get("foreshadowing_pool"),
                    canonical_story_lock=values.get("canonical_story_lock"),
                )
                if start <= int(item.get("episode_num", 0)) <= end
            ]
            episodes = _apply_dry_run_transaction_contracts(
                episodes,
                values.get("episode_event_options", []),
            )
            return {
                "block_plan": current_block,
                "episode_outlines": episodes,
                "state_delta": {
                    "block_id": current_block.get("block_id"),
                    "completed_episode_range": {"start": start, "end": end},
                    "running_character_state": episodes[-1].get("state_change", {}) if episodes else {},
                    "unresolved_threads": episodes[-1].get("unresolved_threads_after_episode", []) if episodes else [],
                    "next_block_handoff": episodes[-1].get("next_episode_start_state", "") if episodes else "",
                },
            }
        target = int(values.get("target_episodes", DEFAULT_TARGET_EPISODES))
        blocks = values.get("longform_blocks") or build_longform_blocks(target)
        return {
            "episode_allocation": [
                    {
                        "block_id": item["block_id"],
                        "start_episode": item["start_episode"],
                        "end_episode": item["end_episode"],
                        "episode_count": item["episode_count"],
                    }
                    for item in blocks
                ],
            "block_plans": blocks,
            "episode_outlines": build_episode_outlines(
                target,
                event_pool=values.get("event_pool"),
                foreshadowing_pool=values.get("foreshadowing_pool"),
                canonical_story_lock=values.get("canonical_story_lock"),
            ),
        }
    if stage_id == "08_script_body_generation":
        episode=(
            values.get("episode_execution_sheet")
            or values.get("episode_outline")
            or {"episode_num": 1, "title": "首战破局", "required_character_names": ["主角"]}
        )
        ep_num = int(episode.get("episode_num", 1))
        derived = values.get("derived_config", {})
        length_hint = derived.get("script_length_chars", "1200-1800")
        relevant_context = (
            values.get("relevant_source_context") if isinstance(values.get("relevant_source_context"), dict) else {}
        )
        canonical_lock = {"protagonist_action_boundary": relevant_context.get("protagonist_action_boundary", {})}
        names = episode.get("required_character_names") or canonical_lock.get("character_names") or ["主角", "核心反派"]
        protagonist = canonical_lock.get("protagonist") or names[0]
        opponent = next((name for name in names if name != protagonist), "核心反派")
        source_anchor = episode.get("source_anchor", "源故事核心伤害")
        conflict_mode = episode.get("conflict_mode", "relationship_pressure")
        transaction_contract = episode.get("transaction_contract", {})
        authorized_transactions = (
            transaction_contract.get("authorized_transactions", [])
            if isinstance(transaction_contract, dict)
            else []
        )
        transaction_evidence = "；".join(
            str(term)
            for transaction in authorized_transactions
            if isinstance(transaction, dict)
            for term in transaction.get("completion_evidence_terms", []) or []
            if str(term).strip()
        )
        transaction_action = "；".join(
            str(transaction.get("action", ""))
            for transaction in authorized_transactions
            if isinstance(transaction, dict) and str(transaction.get("action", "")).strip()
        )
        completed_effect_evidence = [
            {
                "effect_id": str(effect.get("effect_id", "")),
                "evidence_span": str((effect.get("evidence_terms") or [transaction_evidence or "本集事务完成"])[0]),
            }
            for transaction in authorized_transactions
            if isinstance(transaction, dict)
            for effect in transaction.get("effects", []) or []
            if isinstance(effect, dict) and str(effect.get("effect_id", "")).strip()
        ]
        active_continuity = values.get("active_continuity_view")
        if isinstance(active_continuity, dict) and active_continuity.get("next_episode_bridge"):
            bridge = active_continuity.get("next_episode_bridge")
            opening_action = f"承接上一集结尾，{protagonist}没有回到旧争执，而是顺着“{bridge}”继续推进第{ep_num}次核验。"
        else:
            opening_action = f"{protagonist}第一次站到公共空间里，面对{opponent}抛出的源故事压力点。"
        return {
            "schema_version": continuity_ledger_v2.EPISODE_DELTA_SCHEMA_VERSION,
            "final_script": (
                (
                    f"第{ep_num}集\n\n{ep_num}-1    公共空间    日    内\n出场人物：{protagonist}、{opponent}\n△"
                    f"{opening_action}{opponent}伸手去挡桌上的手机，{protagonist}把手机往旁边挪开，屏幕仍朝向对方。\n{protagonist}（抬手打断）："
                    f"上一件事已经说完了，现在说第{ep_num}个能核验的问题。\n{opponent}（避开屏幕）：你别在这里装无辜。\n{protagonist}（把手机放回桌面）：我只问一遍"
                    f"，这段话是谁传出去的？\n△{transaction_action or '主角执行本集事务'}。屏幕显示：{transaction_evidence or '本集事务完成'}"
                    f"。\n\n{ep_num}-2    门口    日    外\n出场人物：{protagonist}、{opponent}、围观者\n△围观者堵在门口追问第{ep_num}条"
                    f"线索，{opponent}侧身挡住出口，把责任往{protagonist}身上推。\n围观者（举着手机）：你现在给大家一个说法。\n{opponent}（指向"
                    f"{protagonist}）：该解释的是她。\n{protagonist}（后退一步）：我不替任何人承担没有证据的罪名。\n△{protagonist}把录音文件名拍给围观者看"
                    f"，屏幕上出现保存时间。\n\n{ep_num}-3    公共空间    傍晚    内\n出场人物：{protagonist}、关键见证者、{opponent}\n△关键见证"
                    f"者站在门边，手指捏着一张旧单据。{opponent}盯着单据，脸色变了。\n关键见证者（低头）：这东西不是今天才有的。\n{protagonist}（看向单据）：下一集之前，我"
                    f"要看到真正的解释（特写）。\n△屏幕显示证据保存时间：第{ep_num}集当日傍晚。\n"
                )
            ),
            "state_update": {
                "audience_fact_changes": [
                    {
                        "fact_id": f"EP{ep_num:03d}_AUD_01",
                        "operation": "add",
                        "detail": f"{protagonist}拒绝自证",
                        "evidence": "主角台词",
                    }
                ],
                "character_knowledge_changes": [
                    {
                        "character_name": opponent,
                        "fact_id": f"EP{ep_num:03d}_CHAR_01",
                        "operation": "add",
                        "detail": "主角不再按旧规则自证",
                        "evidence": "主角公开追问",
                    }
                ],
                "private_fact_changes": [],
                "next_episode_bridge": f"下一集继续核验关键证据。真实模型应按run_config生成约{length_hint}字正文。",
            },
            "continuity_update": {
                "completed_beat_ids": list(episode.get("consumed_child_beat_ids", [])),
                "completed_effect_evidence": completed_effect_evidence,
                "foreshadowing_changes": [],
                "open_thread_changes": [],
                "prop_state_changes": [],
                "scene_boundary_check": {
                    "scene_count": 3,
                    "same_setting_split_count": 0,
                    "allowed_same_setting_splits": [],
                    "merge_note": "相同人物连续对话保留在同一自然场内。",
                },
                "narration_device_usage": {
                    "os_count": 0,
                    "flashback_count": 0,
                    "vo_count": 0,
                    "replacement_strategy_used": "用手机屏幕、录音文件名和见证者动作替代OS/闪回/VO。",
                },
                "last_scene_state": {
                    "location": "公共空间",
                    "present_character_names": [protagonist, "关键见证者", opponent],
                    "visible_result": f"屏幕显示证据保存时间：第{ep_num}集当日傍晚。",
                },
            },
        }
    raise KeyError(f"No dry-run payload for {stage_id}")


def _build_dry_run_event(idx: int, block: dict[str, Any]) -> dict[str, Any]:
    """Handle build dry run event."""
    start = int(block["start_episode"])
    end = int(block["end_episode"])
    span = min(3, max(1, end - start + 1))
    local_start = start + ((idx - 1) % max(1, end - start + 1))
    local_end = min(end, local_start + span - 1)
    return {
        "id": idx,
        "title": f"中型事件{idx}",
        "function": ["压迫", "反击", "反转", "揭露", "回收"][idx % 5],
        "source_plot_point_ids": [max(1, idx % 5)],
        "source_fact_ids": [f"SF{max(1, idx % 4 + 1):03d}"],
        "dramatic_delta": {
            "dimension": ["goal", "resource", "power", "secret", "relationship"][idx % 5],
            "before": "事件前主角受压",
            "after": "事件后主角获得新线索或资源",
            "why_not_repetition": "本事件引入新信息并改变可核验状态",
        },
        "expansion_type": "new_expansion" if idx % 3 == 0 else "strengthen",
        "target_block": block["block_id"],
        "episode_window": {"start": local_start, "end": local_end},
        "not_before_episode": local_start,
        "not_after_episode": local_end,
        "expected_episode_span": span,
        "importance_level": ["B", "A", "S"][idx % 3],
        "conflict_mode": ["rumor", "relationship_pressure", "rule_counterattack", "public_reversal"][idx % 4],
        "pattern_family": ["rumor_counterattack", "resource_fight", "relationship_break", "legal_proof"][idx % 4],
        "source_anchor": "源故事中的核心压迫或反噬机制",
        "delta_from_source": "只放大压力场，不改人物功能",
        "legal_moral_risk": "low",
        "content_sensitivity_risk": "low",
        "dramatic_target_ids": [
            dramatic_release.release_id_for_episode(episode_num)
            for episode_num in range(local_start, local_end + 1)
        ],
        "child_beats": [],
    }


def _build_dry_run_transaction(event_id: int, beat_index: int) -> dict[str, Any]:
    """Handle build dry run transaction."""
    transaction_id = f"E{event_id}-B{beat_index}"
    effect_id = f"{transaction_id}-F1"
    evidence_terms = [f"事件{event_id}证据{beat_index}", f"状态{beat_index}已改变"]
    return {
        "child_beat_id": transaction_id,
        "preconditions": [
            {
                "state_ref": f"EVENT_{event_id}.step_{beat_index}",
                "expected_state": "尚未执行",
            }
        ],
        "action": f"主角展示事件{event_id}证据{beat_index}",
        "effects": [
            {
                "effect_id": effect_id,
                "effect_type": "证据状态",
                "subject": "主角",
                "object": f"事件{event_id}证据{beat_index}",
                "before": "尚未公开",
                "after": "当场公开",
                "evidence_terms": evidence_terms,
            }
        ],
        "forbidden_early_effects": [
            {
                "effect_id": effect_id,
                "reason": f"所属集数前不得公开事件{event_id}证据{beat_index}",
            }
        ],
        "completion_evidence": (
            f"画面同时出现“事件{event_id}证据{beat_index}”与“状态{beat_index}已改变”"
        ),
        "completion_evidence_terms": evidence_terms,
        "process_transition": {
            "process_id": "",
            "from_stage": "",
            "to_stage": "",
        },
        "can_share_episode_with_next": False,
    }


def _build_dry_run_event_pool(count: int, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle build dry run event pool."""
    event_pool = []
    event_id = 1
    base = count // len(blocks)
    remainder = count % len(blocks)
    for block_index, block in enumerate(blocks):
        per_block = base + (1 if block_index < remainder else 0)
        block_start = int(block["start_episode"])
        block_end = int(block["end_episode"])
        block_len = block_end - block_start + 1
        span_base = block_len // per_block
        span_remainder = block_len % per_block
        local_start = block_start
        for local_idx in range(per_block):
            span = span_base + (1 if local_idx < span_remainder else 0)
            local_end = local_start + span - 1
            event = _build_dry_run_event(event_id, block)
            event["episode_window"] = {"start": local_start, "end": local_end}
            event["not_before_episode"] = local_start
            event["not_after_episode"] = local_end
            event["expected_episode_span"] = span
            event["dramatic_target_ids"] = [
                dramatic_release.release_id_for_episode(episode_num)
                for episode_num in range(local_start, local_end + 1)
            ]
            event["child_beats"] = [
                _build_dry_run_transaction(event_id, beat_index)
                for beat_index in range(1, span + 1)
            ]
            event_pool.append(event)
            event_id += 1
            local_start = local_end + 1
    return event_pool


def _build_dry_run_event_chunk(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Handle build dry run event chunk."""
    raw_range = spec.get("episode_range", {})
    if isinstance(raw_range, dict):
        start = int(raw_range.get("start", 1))
        end = int(raw_range.get("end", start))
    else:
        start, end = validators.parse_numeric_range(str(raw_range))
    event_count = int(spec.get("event_count", 0))
    if event_count <= 0:
        return []
    block = {
        "block_id": int(spec.get("arc_id", 1)),
        "start_episode": start,
        "end_episode": end,
    }
    episode_count = end - start + 1
    span_base = episode_count // event_count
    span_remainder = episode_count % event_count
    local_start = start
    events: list[dict[str, Any]] = []
    for offset in range(event_count):
        event_id = int(spec["start_event_id"]) + offset
        span = span_base + (1 if offset < span_remainder else 0)
        local_end = local_start + span - 1
        event = _build_dry_run_event(event_id, block)
        event["target_block"] = int(spec.get("arc_id", 1))
        event["episode_window"] = {"start": local_start, "end": local_end}
        event["not_before_episode"] = local_start
        event["not_after_episode"] = local_end
        event["expected_episode_span"] = span
        event["dramatic_target_ids"] = [
            dramatic_release.release_id_for_episode(episode_num)
            for episode_num in range(local_start, local_end + 1)
        ]
        event["child_beats"] = [
            _build_dry_run_transaction(event_id, beat_index)
            for beat_index in range(1, span + 1)
        ]
        events.append(event)
        local_start = local_end + 1
    return events


def _apply_dry_run_transaction_contracts(
    episodes: list[dict[str, Any]],
    episode_event_options: Any,
) -> list[dict[str, Any]]:
    """Handle apply dry run transaction contracts."""
    option_by_episode = {
        int(item.get("episode_num", 0)): item
        for item in (episode_event_options or [])
        if isinstance(item, dict) and str(item.get("episode_num", "")).isdigit()
    }
    output: list[dict[str, Any]] = []
    for raw_episode in episodes:
        episode = dict(raw_episode)
        option = option_by_episode.get(int(episode.get("episode_num", 0)), {})
        assigned_event = option.get("assigned_event_id")
        transaction_ids = list(option.get("assigned_child_beat_ids", []) or [])
        transactions = [
            item
            for item in option.get("authorized_transactions", []) or []
            if isinstance(item, dict)
        ]
        if assigned_event not in (None, ""):
            episode["event_ids"] = [assigned_event]
        episode["consumed_child_beat_ids"] = transaction_ids
        episode["consumed_child_beats"] = [
            str(item.get("action", ""))
            for item in transactions
        ]
        density = dict(episode.get("target_script_density", {}) or {})
        density["must_cover_beats"] = [
            {
                "beat_id": str(item.get("transaction_id") or item.get("child_beat_id", "")),
            }
            for item in transactions
        ]
        scene_budgets = list(density.get("scene_char_budgets", []) or [])
        if scene_budgets:
            scene_budgets[0] = {
                **scene_budgets[0],
                "must_cover_beat_ids": transaction_ids,
            }
            for index in range(1, len(scene_budgets)):
                scene_budgets[index] = {
                    **scene_budgets[index],
                    "must_cover_beat_ids": [],
                }
        density["scene_char_budgets"] = scene_budgets
        episode["target_script_density"] = density
        output.append(episode)
    return output


def build_longform_blocks(target: int) -> list[dict[str, Any]]:
    """Handle build longform blocks."""
    validators.validate_target_episodes_range(target)
    block_count = validators.expected_block_count_for_target(target)
    base_count = target // block_count
    remainder = target % block_count
    counts = [base_count + (1 if idx < remainder else 0) for idx in range(block_count)]
    titles = [
        "首战破局",
        "舆论扩散",
        "关系反转",
        "证据成网",
        "利益链暴露",
        "外部规则介入",
        "核心真相逼近",
        "终局清算准备",
        "最后反扑",
        "终局清算",
    ]
    goals = [
        "让观众确认核心伤害并建立第一次主动反击",
        "把私人压迫转入公开舆论场",
        "让关键关系从围攻转向裂变",
        "把零散证据组织成可验证链条",
        "揭开压迫背后的利益动机",
        "让外部规则开始产生后果",
        "把核心真相推到不可回避的位置",
        "为终局公开清算保留关键资产",
        "处理反派最后反扑和社会化围堵",
        "完成真相回收、关系切割和终局释放",
    ]
    antagonists = [
        "核心反派与第一批围观者",
        "传播者和利益相关方",
        "动摇同盟与旧关系压力",
        "证据阻断者",
        "利益链中层角色",
        "调解者与规则执行者",
        "核心反派同盟",
        "终局前置阻力",
        "外部反扑角色",
        "核心压迫者",
    ]
    output = []
    start = 1
    for idx, count in enumerate(counts):
        end = start + count - 1
        output.append(
            {
                "block_id": idx + 1,
                "phase": f"篇章{idx + 1}",
                "title": titles[idx],
                "start_episode": start,
                "end_episode": end,
                "episode_count": count,
                "goal": goals[idx],
                "antagonist": antagonists[idx],
                "hook": f"{titles[idx]}结束时抛出下一层压迫源",
                "foreshadowing_plan": {
                    "setup": f"投放{titles[idx]}的关键证据或秘密",
                    "payoff": f"在篇章{idx + 2 if idx + 1 < block_count else idx + 1}回收或反转",
                },
                "source_asset_ids": [max(1, (idx % 5) + 1)],
            }
        )
        start = end + 1
    return output


def build_macro_arcs(target: int) -> list[dict[str, Any]]:
    """Handle build macro arcs."""
    arcs = []
    for block in build_longform_blocks(target):
        arcs.append(
            {
                "arc_id": block["block_id"],
                "title": block["title"],
                "episode_range": {"start": block["start_episode"], "end": block["end_episode"]},
                "dramatic_goal": block["goal"],
                "pressure_source": block["antagonist"],
                "payoff": block["hook"],
                "source_plot_point_ids": block["source_asset_ids"],
            }
        )
    return arcs


def _event_child_beat_items(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Handle event child beat items."""
    return [
        item
        for item in event.get("child_beats", []) or []
        if isinstance(item, dict) and str(item.get("child_beat_id", "")).strip()
    ]


def _distribute_child_beats_to_episode_slots(
    child_beats: list[dict[str, Any]],
    slot_count: int,
) -> list[list[str]]:
    """Handle distribute child beats to episode slots."""
    if slot_count <= 0:
        return []
    bundles: list[list[str]] = [[] for _ in range(slot_count)]
    if not child_beats:
        return bundles
    base, remainder = divmod(len(child_beats), slot_count)
    cursor = 0
    for index in range(slot_count):
        bundle_size = base + (1 if index < remainder else 0)
        bundles[index] = [
            str(item.get("child_beat_id", "")).strip()
            for item in child_beats[cursor : cursor + bundle_size]
            if str(item.get("child_beat_id", "")).strip()
        ]
        cursor += bundle_size
    return bundles


def build_episode_event_options(event_pool: list[dict[str, Any]], *, target_episodes: int) -> list[dict[str, Any]]:
    """Handle build episode event options."""
    event_assignments: dict[int, list[dict[str, Any]]] = {}
    for event in event_pool:
        if not isinstance(event, dict) or not str(event.get("id", "")).isdigit():
            continue
        start, end = validators._event_window(event)
        episode_nums = list(range(max(1, start), min(target_episodes, end) + 1))
        bundles = _distribute_child_beats_to_episode_slots(
            _event_child_beat_items(event),
            len(episode_nums),
        )
        for episode_num, beat_ids in zip(episode_nums, bundles):
            event_assignments.setdefault(episode_num, []).append(
                {
                    "event_id": int(event["id"]),
                    "child_beat_ids": beat_ids,
                }
            )

    options: list[dict[str, Any]] = []
    for episode_num in range(1, target_episodes + 1):
        assignments = sorted(
            event_assignments.get(episode_num, []),
            key=lambda item: item["event_id"],
        )
        option: dict[str, Any] = {
            "episode_num": episode_num,
            "valid_event_ids": [item["event_id"] for item in assignments],
        }
        if assignments:
            option["assigned_event_id"] = assignments[0]["event_id"]
            option["assigned_child_beat_ids"] = assignments[0]["child_beat_ids"]
        options.append(option)
    return options


def event_repair_blocks_from_stage05(stage05_output: dict[str, Any], *, target_episodes: int) -> list[dict[str, Any]]:
    """Handle event repair blocks from stage05."""
    blocks: list[dict[str, Any]] = []
    macro_arcs = stage05_output.get("macro_arcs")
    if isinstance(macro_arcs, list):
        for idx, arc in enumerate(macro_arcs):
            if not isinstance(arc, dict):
                continue
            episode_range = arc.get("episode_range")
            try:
                if isinstance(episode_range, dict):
                    start = int(episode_range.get("start", 0))
                    end = int(episode_range.get("end", 0))
                elif episode_range:
                    start, end = validators.parse_numeric_range(str(episode_range))
                else:
                    continue
            except Exception:
                continue
            if start <= 0 or end <= 0 or start > end:
                continue
            blocks.append(
                {
                    "block_id": arc.get("arc_id") or arc.get("block_id") or idx + 1,
                    "start_episode": start,
                    "end_episode": end,
                    "episode_count": end - start + 1,
                }
            )
    return blocks or build_longform_blocks(target_episodes)


def _repair_legacy_event_windows(
    block_events: list[dict[str, Any]],
    *,
    block_id: Any,
    block_start: int,
    block_end: int,
) -> None:
    """Handle repair legacy event windows."""
    for idx, event in enumerate(block_events):
        window = event["episode_window"]
        raw_start = int(window.get("start", block_start))
        raw_end = int(window.get("end", raw_start))
        if raw_start > block_end or raw_end < block_start:
            continue
        start = max(block_start, raw_start)
        end = min(block_end, raw_end)
        if start > end:
            continue
        leading_gap = start - block_start
        if idx == 0 and 0 < leading_gap <= 2:
            start = block_start
        if idx + 1 < len(block_events):
            next_start = int(block_events[idx + 1]["episode_window"].get("start", end + 1))
            if end + 1 < next_start:
                end = min(block_end, next_start - 1)
        else:
            end = max(end, block_end)
        child_beat_count = len(_event_child_beat_items(event))
        if child_beat_count:
            end = min(end, start + child_beat_count - 1)
        if start != int(window.get("start", start)) or end != int(window.get("end", end)):
            event["episode_window"] = {"start": start, "end": end}
            event["not_before_episode"] = min(int(event.get("not_before_episode", start)), start)
            event["not_after_episode"] = end
            event["expected_episode_span"] = end - start + 1
            trace = list(event.get("event_window_repair_trace", []))
            trace.append(
                {
                    "reason": (
                        "cap_window_to_child_beat_capacity"
                        if child_beat_count and end == start + child_beat_count - 1
                        else "cover_block_episode_gap"
                    ),
                    "block_id": block_id,
                    "repaired_window": event["episode_window"],
                }
            )
            event["event_window_repair_trace"] = trace
        window_span = max(1, end - start + 1)
        if int(event.get("expected_episode_span", 1)) != window_span:
            event["expected_episode_span"] = window_span
            trace = list(event.get("event_window_repair_trace", []))
            trace.append(
                {
                    "reason": "align_expected_episode_span_with_window",
                    "block_id": block_id,
                    "episode_window": {"start": start, "end": end},
                }
            )
            event["event_window_repair_trace"] = trace


def repair_event_pool_window_gaps(
    event_pool: list[dict[str, Any]],
    longform_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Handle repair event pool window gaps."""
    repaired_pool = json.loads(json.dumps(event_pool, ensure_ascii=False))
    for block in longform_blocks:
        block_id = block.get("block_id")
        block_start = int(block.get("start_episode", 0))
        block_end = int(block.get("end_episode", 0))
        block_events = [
            item
            for item in repaired_pool
            if (
                isinstance(item, dict)
                and str(item.get("target_block")) == str(block_id)
                and isinstance(item.get("episode_window"), dict)
            )
        ]
        block_events.sort(key=lambda item: (int(item["episode_window"].get("start", 0)), int(item.get("id", 0))))
        if not block_events:
            continue
        if not all(_event_child_beat_items(event) for event in block_events):
            _repair_legacy_event_windows(
                block_events,
                block_id=block_id,
                block_start=block_start,
                block_end=block_end,
            )
            continue

        block_length = block_end - block_start + 1
        profiles: list[dict[str, Any]] = []
        for event in block_events:
            raw_start, raw_end = validators._event_window(event)
            child_beat_count = len(_event_child_beat_items(event))
            minimum_slots = max(1, (child_beat_count + 1) // 2)
            maximum_slots = max(1, child_beat_count)
            desired_slots = min(
                maximum_slots,
                max(minimum_slots, min(block_end, raw_end) - max(block_start, raw_start) + 1),
            )
            profiles.append(
                {
                    "event": event,
                    "slots": desired_slots,
                    "minimum_slots": minimum_slots,
                    "maximum_slots": maximum_slots,
                }
            )

        while sum(item["slots"] for item in profiles) > block_length:
            candidates = [item for item in profiles if item["slots"] > item["minimum_slots"]]
            if not candidates:
                candidates = [item for item in profiles if item["slots"] > 1]
            if not candidates:
                break
            candidates.sort(
                key=lambda item: (
                    item["slots"] - item["minimum_slots"],
                    item["slots"],
                    int(item["event"].get("id", 0)),
                ),
                reverse=True,
            )
            candidates[0]["slots"] -= 1

        while sum(item["slots"] for item in profiles) < block_length:
            candidates = [item for item in profiles if item["slots"] < item["maximum_slots"]]
            if not candidates:
                break
            candidates.sort(
                key=lambda item: (
                    item["maximum_slots"] - item["slots"],
                    -int(item["event"].get("id", 0)),
                ),
                reverse=True,
            )
            candidates[0]["slots"] += 1

        cursor = block_start
        for profile in profiles:
            event = profile["event"]
            slots = int(profile["slots"])
            original_window = dict(event.get("episode_window", {}))
            next_window = {"start": cursor, "end": cursor + slots - 1}
            event["episode_window"] = next_window
            event["not_before_episode"] = cursor
            event["not_after_episode"] = next_window["end"]
            event["expected_episode_span"] = slots
            if original_window != next_window:
                trace = list(event.get("event_window_repair_trace", []))
                trace.append(
                    {
                        "reason": "partition_block_for_deterministic_child_beat_schedule",
                        "block_id": block_id,
                        "original_window": original_window,
                        "repaired_window": next_window,
                        "child_beat_count": len(_event_child_beat_items(event)),
                    }
                )
                event["event_window_repair_trace"] = trace
            cursor = next_window["end"] + 1
    return repaired_pool


def repair_episode_event_ids(
    episodes: list[dict[str, Any]],
    *,
    event_pool: list[dict[str, Any]],
    target_episodes: int,
) -> list[dict[str, Any]]:
    """Handle repair episode event ids."""
    del event_pool, target_episodes
    # Event IDs carry story semantics. Preserve model output and let validators
    # report window/alignment violations instead of replacing only the metadata.
    return [dict(episode) for episode in episodes]


def _episode_nums_from_child_beat(child_beat: Any) -> list[int]:
    """Handle episode nums from child beat."""
    text = str(child_beat.get("action", "")) if isinstance(child_beat, dict) else str(child_beat or "")
    output: list[int] = []
    for match in re.finditer(r"第(\d+)(?:[-~—至到](\d+))?集", text):
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start <= end:
            output.extend(range(start, end + 1))
    return sorted(set(output))


def repair_episode_child_beat_accounting(data: dict[str, Any], *, event_pool: list[dict[str, Any]]) -> dict[str, Any]:
    """Handle repair episode child beat accounting."""
    episodes = data.get("episode_outlines")
    if not isinstance(episodes, list):
        return data
    event_by_id = {int(item["id"]): item for item in event_pool if str(item.get("id", "")).isdigit()}
    episodes_by_num = {
        int(item.get("episode_num")): dict(item)
        for item in episodes
        if str(item.get("episode_num", "")).isdigit()
    }
    required_episodes_by_event: dict[int, set[int]] = {}
    changed = False
    for event_id, event in event_by_id.items():
        try:
            window_start, window_end = validators._event_window(event)
        except ValueError:
            continue
        event_block = int(event.get("target_block", -1))
        for child_beat in event.get("child_beats", []) or []:
            child_beat_action = str(child_beat.get("action", "")) if isinstance(child_beat, dict) else str(child_beat)
            child_beat_id = str(child_beat.get("child_beat_id", "")) if isinstance(child_beat, dict) else ""
            for episode_num in _episode_nums_from_child_beat(child_beat):
                if episode_num < window_start or episode_num > window_end:
                    continue
                episode = episodes_by_num.get(episode_num)
                if not episode or int(episode.get("block_id", event_block)) != event_block:
                    continue
                required_episodes_by_event.setdefault(event_id, set()).add(episode_num)
                event_ids = [int(raw_id) for raw_id in episode.get("event_ids", []) if str(raw_id).isdigit()]
                trace = list(episode.get("child_beat_accounting_repair_trace", []))
                if event_id not in event_ids:
                    event_ids.append(event_id)
                    episode["event_ids"] = event_ids
                    trace.append(
                        {
                            "reason": "add_event_id_for_explicit_child_beat",
                            "event_id": event_id,
                            "child_beat": child_beat,
                        },
                    )
                    changed = True
                consumed = list(episode.get("consumed_child_beats", []) or [])
                if not _child_beat_is_covered(child_beat_action, consumed):
                    consumed.append(child_beat_action)
                    episode["consumed_child_beats"] = consumed
                    trace.append(
                        {
                            "reason": "add_missing_source_child_beat",
                            "event_id": event_id,
                            "child_beat": child_beat_action,
                        },
                    )
                    changed = True
                if child_beat_id:
                    consumed_ids = list(episode.get("consumed_child_beat_ids", []) or [])
                    if child_beat_id not in consumed_ids:
                        consumed_ids.append(child_beat_id)
                        episode["consumed_child_beat_ids"] = consumed_ids
                        trace.append(
                            {
                                "reason": "add_missing_source_child_beat_id",
                                "event_id": event_id,
                                "child_beat_id": child_beat_id,
                            },
                        )
                        changed = True
                if trace:
                    episode["child_beat_accounting_repair_trace"] = trace
                episodes_by_num[episode_num] = episode
    if required_episodes_by_event:
        last_required_by_event = {
            event_id: max(episode_nums)
            for event_id, episode_nums in required_episodes_by_event.items()
        }
        for episode_num, episode in episodes_by_num.items():
            event_ids = [int(raw_id) for raw_id in episode.get("event_ids", []) if str(raw_id).isdigit()]
            required_last_values = [
                last_required_by_event[event_id]
                for event_id in event_ids
                if event_id in last_required_by_event
            ]
            if not required_last_values:
                continue
            original_status = str(episode.get("event_consumption_status", "")).strip()
            next_status = original_status
            if any(last_episode > episode_num for last_episode in required_last_values):
                if _event_status_is_completed(original_status):
                    next_status = "partial"
            elif any(last_episode == episode_num for last_episode in required_last_values):
                next_status = "completed"
            if next_status != original_status:
                trace = list(episode.get("child_beat_accounting_repair_trace", []))
                trace.append(
                    {
                        "reason": "align_completed_status_with_last_explicit_child_beat",
                        "original_status": original_status,
                        "repaired_status": next_status,
                    },
                )
                episode["event_consumption_status"] = next_status
                episode["child_beat_accounting_repair_trace"] = trace
                episodes_by_num[episode_num] = episode
                changed = True
    if not changed:
        return data
    output = dict(data)
    output["episode_outlines"] = [episodes_by_num.get(int(item.get("episode_num", -1)), item) for item in episodes]
    return output


def repair_episode_planning_output(
    data: dict[str, Any],
    *,
    event_pool: list[dict[str, Any]],
    target_episodes: int,
) -> dict[str, Any]:
    """Handle repair episode planning output."""
    episodes = data.get("episode_outlines")
    if not isinstance(episodes, list):
        return data
    repaired = repair_episode_event_ids(episodes, event_pool=event_pool, target_episodes=target_episodes)
    repaired_data = repair_episode_child_beat_accounting({"episode_outlines": repaired}, event_pool=event_pool)
    repaired = repaired_data.get("episode_outlines", repaired)
    repaired = repair_episode_narration_device_plans(repaired)
    if repaired == episodes:
        return data
    output = dict(data)
    output["episode_outlines"] = repaired
    return output


def repair_episode_narration_device_plans(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle repair episode narration device plans."""
    changed = False
    repaired: list[dict[str, Any]] = []
    for episode in episodes:
        if not isinstance(episode, dict):
            repaired.append(episode)
            continue
        next_episode = dict(episode)
        trace = list(next_episode.get("narration_device_plan_repair_trace", []))
        plan = episode.get("narration_device_plan")
        if not isinstance(plan, dict):
            plan = build_default_narration_device_plan()
            next_episode["narration_device_plan"] = plan
            trace.append({"reason": "missing_narration_device_plan_default_zero"})
            changed = True
        else:
            plan = dict(plan)
        if "planned_flashback_quota_count" not in plan:
            plan["planned_flashback_quota_count"] = _safe_int_value(plan.get("planned_flashback_count"))
            next_episode["narration_device_plan"] = plan
            trace.append(
                {
                    "reason": "missing_planned_flashback_quota_count_default_to_flashback_count",
                    "planned_flashback_quota_count": plan["planned_flashback_quota_count"],
                }
            )
            changed = True
        if "approved_time_deviation_ids" not in plan:
            plan["approved_time_deviation_ids"] = []
            next_episode["narration_device_plan"] = plan
            trace.append({"reason": "missing_approved_time_deviation_ids_default_empty"})
            changed = True
        split_defaults = {
            "approved_flashback_time_deviation_ids": list(plan.get("approved_time_deviation_ids") or []),
            "approved_os_time_deviation_ids": [],
            "visualized_time_deviation_ids": [],
            "deleted_or_rewritten_time_deviation_ids": [],
        }
        for field, default_value in split_defaults.items():
            if field in plan:
                continue
            plan[field] = default_value
            next_episode["narration_device_plan"] = plan
            trace.append({"reason": f"missing_{field}_default_empty"})
            changed = True
        minimum_vo_count = infer_minimum_vo_count_from_scene_plan(next_episode)
        if minimum_vo_count > _safe_int_value(plan.get("planned_vo_count")):
            plan["planned_vo_count"] = minimum_vo_count
            next_episode["narration_device_plan"] = plan
            trace.append({"reason": "scene_plan_requires_vo_budget", "planned_vo_count": minimum_vo_count})
            changed = True
        if trace:
            next_episode["narration_device_plan_repair_trace"] = trace
        repaired.append(next_episode)
    return repaired if changed else episodes


PATTERN_FAMILY_BY_CONFLICT_MODE = {
    "emotional_anchor": "emotional_baseline",
    "moral_blackmail": "moral_pressure",
    "information_warfare": "information_reveal",
    "conspiracy_execution": "hidden_conspiracy",
    "sudden_crisis": "crisis_turn",
    "physical_confrontation": "physical_coercion",
    "physical_confrontation+emotional_warfare": "physical_emotional_break",
    "trauma_detonation": "trauma_turning_point",
    "legal_preparation": "legal_countermove",
    "family_encirclement": "family_pressure",
    "psychological_torture": "captivity_pressure",
    "survival_planning": "survival_countermove",
    "escape_execution": "escape_turn",
    "chase_pursuit": "pursuit_escalation",
    "legal_resolution": "legal_resolution",
}


def _episode_text_for_label_repair(episode: dict[str, Any]) -> str:
    """Handle episode text for label repair."""
    return " ".join(
        str(episode.get(key, ""))
        for key in ("title", "main_conflict", "counterattack", "information_gain", "source_anchor", "expansion_delta")
    )


def _conflict_mode_candidate(episode: dict[str, Any]) -> str:
    """Handle conflict mode candidate."""
    text = _episode_text_for_label_repair(episode)
    rules = [
        ("奶茶|车窗|逼停|偷运|拦截", "vehicle_blocking_counterattack"),
        ("掐|淤青|手机|玻璃|家暴", "domestic_violence_exposure"),
        ("侄子|耳光|摔狗|摔瘸", "pet_abuse_public_retaliation"),
        ("菜刀|残杀|踢中|裆部|绝命", "lethal_pet_violence_self_defense"),
        ("绑架|囚禁|灌食|木柱", "captivity_survival_pressure"),
        ("磨柱|脱困|逃", "escape_execution"),
        ("大灯|山道|翻滚|撞死", "vehicle_chase_evasion"),
        ("老人|座机|村名|110|报警定位", "help_request_under_pursuit"),
        ("撞破|院门|土屋|钻出车厢|不育绝后", "vehicle_crash_assault"),
        ("追杀|越野车|山林", "chase_pursuit"),
        ("报警|律师|法律|正当防卫|判决", "legal_resolution"),
    ]
    for pattern, label in rules:
        if re.search(pattern, text):
            return label
    pattern_family = str(episode.get("pattern_family", "")).strip()
    if pattern_family:
        return pattern_family
    return str(episode.get("conflict_mode", "")).strip()


def repair_episode_conflict_mode_streaks(
    data: dict[str, Any],
    *,
    max_streak: int,
) -> dict[str, Any]:
    """Handle repair episode conflict mode streaks."""
    episodes = data.get("episode_outlines")
    if not isinstance(episodes, list) or max_streak < 1:
        return data
    repaired: list[dict[str, Any]] = []
    current_mode = None
    current_streak = 0
    changed = False
    for episode in episodes:
        next_episode = dict(episode)
        mode = str(next_episode.get("conflict_mode", "")).strip()
        if mode == current_mode:
            current_streak += 1
        else:
            current_mode = mode
            current_streak = 1
        if current_streak > max_streak:
            candidate = _conflict_mode_candidate(next_episode)
            if candidate and candidate != mode:
                trace = list(next_episode.get("conflict_mode_repair_trace", []))
                trace.append(
                    {
                        "reason": "conflict_mode_streak_normalization",
                        "original_conflict_mode": mode,
                        "repaired_conflict_mode": candidate,
                        "pattern_family": next_episode.get("pattern_family", ""),
                    }
                )
                next_episode["conflict_mode"] = candidate
                next_episode["conflict_mode_repair_trace"] = trace
                current_mode = candidate
                current_streak = 1
                changed = True
        repaired.append(next_episode)
    if not changed:
        return data
    output = dict(data)
    output["episode_outlines"] = repaired
    return output


def repair_episode_active_motion_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Handle repair episode active motion fields."""
    episodes = data.get("episode_outlines")
    if not isinstance(episodes, list):
        return data
    repaired: list[dict[str, Any]] = []
    changed = False
    for episode in episodes:
        next_episode = dict(episode)
        if not next_episode.get("is_epilogue"):
            protagonist = next(
                (str(name).strip() for name in next_episode.get("required_character_names", []) if str(name).strip()),
                "主角",
            )
            source_anchor = str(next_episode.get("source_anchor") or next_episode.get("title") or "本集核心压力").strip()
            trace = list(next_episode.get("active_motion_repair_trace", []))
            if _episode_motion_field_is_empty(next_episode.get("main_conflict")):
                original = next_episode.get("main_conflict", "")
                next_episode["main_conflict"] = f"{source_anchor}带来的压力浮出水面，{protagonist}必须守住当前关系边界。"
                trace.append(
                    {"field": "main_conflict", "original": original, "reason": "non_epilogue_requires_active_motion"},
                )
                changed = True
            if _episode_motion_field_is_empty(next_episode.get("counterattack")):
                original = next_episode.get("counterattack", "")
                next_episode["counterattack"] = f"{protagonist}用明确照料、拒绝退让或当场回问完成本集最小反击。"
                trace.append(
                    {"field": "counterattack", "original": original, "reason": "non_epilogue_requires_active_motion"},
                )
                changed = True
            if trace:
                next_episode["active_motion_repair_trace"] = trace
        repaired.append(next_episode)
    if not changed:
        return data
    output = dict(data)
    output["episode_outlines"] = repaired
    return output


def repair_episode_epilogue_budget(data: dict[str, Any], *, max_epilogue: int) -> dict[str, Any]:
    """Handle repair episode epilogue budget."""
    episodes = data.get("episode_outlines")
    if not isinstance(episodes, list):
        return data
    epilogue_indexes = [index for index, episode in enumerate(episodes) if episode.get("is_epilogue")]
    if len(epilogue_indexes) <= max_epilogue:
        return data
    keep_indexes = set(epilogue_indexes[-max(0, max_epilogue) :]) if max_epilogue > 0 else set()
    keep_episode_nums = [episodes[index].get("episode_num") for index in sorted(keep_indexes)]
    repaired: list[dict[str, Any]] = []
    changed = False
    for index, episode in enumerate(episodes):
        next_episode = dict(episode)
        if index in epilogue_indexes and index not in keep_indexes:
            trace = list(next_episode.get("epilogue_budget_repair_trace", []))
            trace.append(
                {
                    "reason": "epilogue_budget_overrun_demote_earliest_tail_episode",
                    "max_epilogue": max_epilogue,
                    "kept_epilogue_episode_nums": keep_episode_nums,
                    "original_is_epilogue": True,
                }
            )
            next_episode["is_epilogue"] = False
            next_episode["epilogue_budget_repair_trace"] = trace
            changed = True
        repaired.append(next_episode)
    if not changed:
        return data
    output = dict(data)
    output["episode_outlines"] = repaired
    return output


def _episode_motion_field_is_empty(value: Any) -> bool:
    """Handle episode motion field is empty."""
    text = str(value or "").strip()
    return validators._contains_empty_motion(text) or any(
        marker in text
        for marker in ("无外部直接冲突", "没有外部直接冲突", "无直接冲突", "没有直接反击")
    )


def _ordered_unique(items: list[str]) -> list[str]:
    """Handle ordered unique."""
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if not value:
            continue
        key = validators.normalize_character_name(value)
        if key and key not in seen:
            seen.add(key)
            output.append(value)
    return output


def _preferred_character_name_map(allowed_names: list[str]) -> dict[str, str]:
    """Handle preferred character name map."""
    mapping: dict[str, str] = {}
    for raw_name in allowed_names:
        value = str(raw_name or "").strip()
        normalized = validators.normalize_character_name(value)
        if not normalized:
            continue
        current = mapping.get(normalized)
        if current is None or ("（" in current or "(" in current) or len(value) < len(current):
            mapping[normalized] = value
    if "女主" in mapping:
        mapping["女主"] = "女主"
    return mapping


def repair_episode_character_name_fields(
    data: dict[str, Any],
    *,
    allowed_character_names: list[str],
) -> dict[str, Any]:
    """Handle repair episode character name fields."""
    episodes = data.get("episode_outlines")
    if not isinstance(episodes, list):
        return data
    preferred = _preferred_character_name_map(allowed_character_names)
    repaired: list[dict[str, Any]] = []
    changed = False
    for episode in episodes:
        next_episode = dict(episode)
        trace = list(next_episode.get("character_name_repair_trace", []))
        for field in ("required_character_names", "appearing_character_names"):
            original = [str(item).strip() for item in next_episode.get(field, []) if str(item).strip()]
            normalized = [
                preferred.get(validators.normalize_character_name(name), name)
                for name in original
            ]
            normalized = _ordered_unique(normalized)
            if normalized != original:
                next_episode[field] = normalized
                trace.append({"field": field, "original": original, "repaired": normalized})
                changed = True
        required = [str(item).strip() for item in next_episode.get("required_character_names", []) if str(item).strip()]
        appearing = [
            str(item).strip()
            for item in next_episode.get("appearing_character_names", [])
            if str(item).strip()
        ]
        appearing_keys = {validators.normalize_character_name(name) for name in appearing}
        missing_required = [
            name
            for name in required
            if validators.normalize_character_name(name) not in appearing_keys
        ]
        if missing_required:
            next_episode["appearing_character_names"] = _ordered_unique(appearing + missing_required)
            trace.append({"field": "appearing_character_names", "added_required_names": missing_required})
            changed = True
            appearing = [
                str(item).strip()
                for item in next_episode.get("appearing_character_names", [])
                if str(item).strip()
            ]
            appearing_keys = {validators.normalize_character_name(name) for name in appearing}
        outline_text = " ".join(
            json.dumps(next_episode.get(key, ""), ensure_ascii=False)
            for key in (
                "opening_beat",
                "closing_beat",
                "next_episode_start_state",
                "main_conflict",
                "counterattack",
                "information_gain",
                "state_change",
                "ending_hook",
                "source_anchor",
                "expansion_delta",
                "consumed_child_beats",
                "unresolved_threads_after_episode",
            )
        )
        mentioned_names = [
            preferred_name
            for normalized_name, preferred_name in preferred.items()
            if normalized_name not in appearing_keys and validators.required_character_name_present(
                normalized_name,
                outline_text,
            )
        ]
        if mentioned_names:
            added_names = _ordered_unique(mentioned_names)
            next_episode["appearing_character_names"] = _ordered_unique(appearing + added_names)
            trace.append({"field": "appearing_character_names", "added_mentioned_names": added_names})
            changed = True
        scene_plan = next_episode.get("scene_plan")
        if isinstance(scene_plan, list):
            repaired_scene_plan: list[Any] = []
            scene_changed = False
            for scene in scene_plan:
                if not isinstance(scene, dict):
                    repaired_scene_plan.append(scene)
                    continue
                next_scene = dict(scene)
                scene_cast = [
                    preferred.get(validators.normalize_character_name(str(item).strip()), str(item).strip())
                    for item in next_scene.get("appearing_character_names", [])
                    if str(item).strip()
                ]
                scene_keys = {validators.normalize_character_name(name) for name in scene_cast}
                scene_text = json.dumps(next_scene, ensure_ascii=False)
                scene_mentions = [
                    preferred_name
                    for normalized_name, preferred_name in preferred.items()
                    if normalized_name not in scene_keys and validators.required_character_name_present(
                        normalized_name,
                        scene_text,
                    )
                ]
                if scene_mentions:
                    added_scene_names = _ordered_unique(scene_mentions)
                    next_scene["appearing_character_names"] = _ordered_unique(scene_cast + added_scene_names)
                    trace.append(
                        {
                            "field": "scene_plan.appearing_character_names",
                            "scene_no": next_scene.get("scene_no"),
                            "added_mentioned_names": added_scene_names,
                        }
                    )
                    scene_changed = True
                    changed = True
                repaired_scene_plan.append(next_scene)
            if scene_changed:
                next_episode["scene_plan"] = repaired_scene_plan
        if trace:
            next_episode["character_name_repair_trace"] = trace
        repaired.append(next_episode)
    if not changed:
        return data
    output = dict(data)
    output["episode_outlines"] = repaired
    return output


def _shared_boundary_recap_terms(previous: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Handle shared boundary recap terms."""
    previous_text = " ".join(
        str(previous.get(key, ""))
        for key in ("closing_beat", "ending_hook", "consumed_child_beats")
    )
    current_text = str(current.get("opening_beat", ""))
    terms = [
        "漏斗",
        "灌下",
        "咳嗽",
        "满嘴是血",
        "塞入",
        "强行",
        "电话接通",
        "远光灯",
        "残躯",
        "狗尸",
    ]
    return [term for term in terms if term in previous_text and term in current_text]


def repair_cross_block_opening_recap(data: dict[str, Any]) -> dict[str, Any]:
    """Handle repair cross block opening recap."""
    episodes = data.get("episode_outlines")
    if not isinstance(episodes, list):
        return data
    repaired: list[dict[str, Any]] = []
    changed = False
    previous: dict[str, Any] | None = None
    for episode in episodes:
        next_episode = dict(episode)
        if previous and str(previous.get("block_id")) != str(next_episode.get("block_id")):
            shared_terms = _shared_boundary_recap_terms(previous, next_episode)
            bridge = str(previous.get("next_episode_start_state", "")).strip()
            if len(shared_terms) >= 3 and bridge:
                original = str(next_episode.get("opening_beat", ""))
                next_episode["opening_beat"] = f"承接上一集结果，{bridge}"
                trace = list(next_episode.get("opening_beat_repair_trace", []))
                trace.append(
                    {
                        "reason": "cross_block_completed_action_recap",
                        "previous_episode_num": previous.get("episode_num"),
                        "shared_terms": shared_terms,
                        "original_opening_beat": original,
                    }
                )
                next_episode["opening_beat_repair_trace"] = trace
                changed = True
        repaired.append(next_episode)
        previous = next_episode
    if not changed:
        return data
    output = dict(data)
    output["episode_outlines"] = repaired
    return output


def _pattern_family_candidate(episode: dict[str, Any]) -> str:
    """Handle pattern family candidate."""
    conflict_mode = str(episode.get("conflict_mode", "")).strip()
    if conflict_mode in PATTERN_FAMILY_BY_CONFLICT_MODE:
        return PATTERN_FAMILY_BY_CONFLICT_MODE[conflict_mode]
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", conflict_mode.lower()).strip("_")
    if normalized:
        return normalized
    pattern_family = str(episode.get("pattern_family", "")).strip()
    if conflict_mode and conflict_mode != pattern_family:
        return conflict_mode
    return str(episode.get("pattern_family", "")).strip()


def repair_episode_pattern_family_streaks(
    data: dict[str, Any],
    *,
    max_streak: int,
) -> dict[str, Any]:
    """Handle repair episode pattern family streaks."""
    episodes = data.get("episode_outlines")
    if not isinstance(episodes, list) or max_streak < 1:
        return data
    repaired: list[dict[str, Any]] = []
    current_pattern = None
    current_streak = 0
    changed = False
    for episode in episodes:
        next_episode = dict(episode)
        pattern = str(next_episode.get("pattern_family", "")).strip()
        if pattern == current_pattern:
            current_streak += 1
        else:
            current_pattern = pattern
            current_streak = 1
        if current_streak > max_streak:
            candidate = _pattern_family_candidate(next_episode)
            if candidate and candidate != pattern:
                trace = list(next_episode.get("pattern_family_repair_trace", []))
                trace.append(
                    {
                        "reason": "pattern_family_streak_normalization",
                        "original_pattern_family": pattern,
                        "repaired_pattern_family": candidate,
                        "conflict_mode": next_episode.get("conflict_mode", ""),
                    }
                )
                next_episode["pattern_family"] = candidate
                next_episode["pattern_family_repair_trace"] = trace
                current_pattern = candidate
                current_streak = 1
                changed = True
        repaired.append(next_episode)
    if not changed:
        return data
    output = dict(data)
    output["episode_outlines"] = repaired
    return output


def episode_planning_block_artifact_id(block: dict[str, Any]) -> str:
    """Handle episode planning block artifact id."""
    base = f"07_episode_planning.block_{int(block.get('block_id', 0)):02d}"
    if "_chunk_index" not in block:
        return base
    start = int(block.get("start_episode", 0))
    end = int(block.get("end_episode", 0))
    return f"{base}_ep{start:03d}_{end:03d}"


def public_episode_planning_block(block: dict[str, Any]) -> dict[str, Any]:
    """Handle public episode planning block."""
    return {key: value for key, value in block.items() if not str(key).startswith("_")}


def _episode_range_overlaps_block(start: int, end: int, block: dict[str, Any]) -> bool:
    """Handle episode range overlaps block."""
    block_start = int(block.get("start_episode", 0))
    block_end = int(block.get("end_episode", 0))
    return start <= block_end and end >= block_start


def _item_matches_episode_block(item: dict[str, Any], block: dict[str, Any]) -> bool:
    """Handle item matches episode block."""
    block_id = str(block.get("block_id"))
    for key in ("block_id", "target_block"):
        if key in item and str(item.get(key)) == block_id:
            return True
    if "episode_num" in item and str(item.get("episode_num", "")).isdigit():
        episode_num = int(item["episode_num"])
        return _episode_range_overlaps_block(episode_num, episode_num, block)
    if "episode_range" in item and isinstance(item["episode_range"], dict):
        start = int(item["episode_range"].get("start", 0))
        end = int(item["episode_range"].get("end", start))
        return _episode_range_overlaps_block(start, end, block)
    if "start_episode" in item and "end_episode" in item:
        start = int(item.get("start_episode", 0))
        end = int(item.get("end_episode", start))
        return _episode_range_overlaps_block(start, end, block)
    return False


def filter_items_for_episode_block(items: Any, block: dict[str, Any]) -> list[dict[str, Any]]:
    """Handle filter items for episode block."""
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and _item_matches_episode_block(item, block)]


def _compact_block_prompt_value(value: Any, *, text_limit: int = 36, list_limit: int | None = 6) -> Any:
    """Handle compact block prompt value."""
    if isinstance(value, str):
        return _clip_planning_text(value, text_limit)
    if isinstance(value, list):
        items = value if list_limit is None else value[:list_limit]
        return [_compact_block_prompt_value(item, text_limit=text_limit, list_limit=list_limit) for item in items]
    if isinstance(value, dict):
        return {
            key: _compact_block_prompt_value(item, text_limit=text_limit, list_limit=list_limit)
            for key, item in value.items()
        }
    return value


def compact_canonical_story_lock_for_block_prompt(canonical_story_lock: dict[str, Any]) -> dict[str, Any]:
    """Handle compact canonical story lock for block prompt."""
    emotional_debts = []
    for item in canonical_story_lock.get("emotional_debt_chain", [])[:4]:
        if isinstance(item, dict):
            emotional_debts.append(
                {
                    "source_fact": _clip_planning_text(item.get("source_fact", ""), 42),
                    "emotion": _clip_planning_text(item.get("emotion", ""), 30),
                }
            )
        else:
            emotional_debts.append(_clip_planning_text(item, 42))
    source_contract = canonical_story_lock.get("source_preservation_contract", {})
    if isinstance(source_contract, dict):
        source_contract = {
            "must_preserve": _compact_block_prompt_value(
                    source_contract.get("must_preserve", []),
                    text_limit=42,
                    list_limit=5,
                ),
            "must_preserve_fact_ids": source_contract.get("must_preserve_fact_ids", []),
            "can_expand": _compact_block_prompt_value(
                    source_contract.get("can_expand", []),
                    text_limit=36,
                    list_limit=3,
                ),
        }
    action_boundary = canonical_story_lock.get("protagonist_action_boundary", {})
    if isinstance(action_boundary, dict):
        action_boundary = {
            "allowed": _compact_block_prompt_value(action_boundary.get("allowed", []), text_limit=42, list_limit=4),
            "allowed_active_strategies": _compact_block_prompt_value(
                    action_boundary.get("allowed_active_strategies", []),
                    text_limit=24,
                    list_limit=6,
                ),
            "risk_examples": _compact_block_prompt_value(
                    action_boundary.get("risk_examples", []),
                    text_limit=42,
                    list_limit=3,
                ),
            "risk_response": _clip_planning_text(action_boundary.get("risk_response", ""), 54),
        }
    compact = {
        "protagonist": canonical_story_lock.get("protagonist"),
        "character_names": canonical_story_lock.get("character_names", []),
        "must_keep": _compact_block_prompt_value(
                canonical_story_lock.get("must_keep", []),
                text_limit=42,
                list_limit=5,
            ),
        "emotional_debt_chain": emotional_debts,
        "source_preservation_contract": source_contract,
        "protagonist_action_boundary": action_boundary,
        "forbidden_changes": _compact_block_prompt_value(
                canonical_story_lock.get("forbidden_changes", []),
                text_limit=42,
                list_limit=5,
            ),
        "naming_rule": canonical_story_lock.get("naming_rule", ""),
    }
    source_plot_points = []
    for point in canonical_story_lock.get("source_plot_points", [])[:6]:
        if not isinstance(point, dict):
            continue
        source_plot_points.append(
            _compact_dict_keys(
                point,
                ["id", "title", "function", "characters"],
                text_limit=36,
            )
        )
    compact["source_plot_points"] = source_plot_points
    return compact


def compact_event_pool_for_block_prompt(event_pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle compact event pool for block prompt."""
    keys = [
        "id",
        "title",
        "function",
        "source_plot_point_ids",
        "source_fact_ids",
        "dramatic_delta",
        "target_block",
        "episode_window",
        "expected_episode_span",
        "importance_level",
        "conflict_mode",
        "pattern_family",
        "source_anchor",
        "legal_moral_risk",
        "content_sensitivity_risk",
        "child_beats",
    ]
    compact_events: list[dict[str, Any]] = []
    for event in event_pool:
        if not isinstance(event, dict):
            continue
        compact = _compact_dict_keys(event, keys, text_limit=42)
        compact_events.append(compact)
    return compact_events


def compact_character_network_for_block_prompt(network: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle compact character network for block prompt."""
    return [
        _compact_dict_keys(item, ["name", "camp", "function"], text_limit=32)
        for item in network[:10]
        if isinstance(item, dict)
    ]


def compact_conflict_engine_for_block_prompt(engine: dict[str, Any]) -> dict[str, Any]:
    """Handle compact conflict engine for block prompt."""
    if not isinstance(engine, dict):
        return {}
    return {
        "pressure_templates": [
            _compact_dict_keys(
                item,
                ["template_id", "template_name", "mode", "applicable_arc_ids", "variant_examples"],
                text_limit=28,
            )
            for item in engine.get("pressure_templates", [])[:5]
            if isinstance(item, dict)
        ],
        "counterattack_templates": [
            _compact_dict_keys(
                item,
                ["template_id", "template_name", "mode", "applicable_arc_ids", "variant_examples"],
                text_limit=28,
            )
            for item in engine.get("counterattack_templates", [])[:5]
            if isinstance(item, dict)
        ],
        "reversal_templates": [
            _compact_dict_keys(
                item,
                ["template_id", "template_name", "mode", "applicable_arc_ids", "variant_examples"],
                text_limit=28,
            )
            for item in engine.get("reversal_templates", [])[:4]
            if isinstance(item, dict)
        ],
        "anti_monotony_rules": _compact_block_prompt_value(
                engine.get("anti_monotony_rules", []),
                text_limit=34,
                list_limit=5,
            ),
    }


def compact_running_character_state_for_handoff(state: Any) -> dict[str, str]:
    """Handle compact running character state for handoff."""
    if not isinstance(state, dict):
        return {}
    compact: dict[str, str] = {}
    for name, value in list(state.items())[:6]:
        if isinstance(value, dict):
            bits = []
            for key in ("goal", "relationship", "arc_position", "emotional", "physical"):
                text = str(value.get(key, "")).strip()
                if text:
                    bits.append(_clip_planning_text(text, 32))
            compact[str(name)] = "；".join(bits[:2]) if bits else _clip_planning_text(value, 54)
        else:
            compact[str(name)] = _clip_planning_text(value, 54)
    return compact


def compact_unresolved_threads_for_handoff(threads: Any) -> list[Any]:
    """Handle compact unresolved threads for handoff."""
    if not isinstance(threads, list):
        return []
    compact = []
    for item in threads[:4]:
        if isinstance(item, dict):
            compact.append(
                {
                    "description": _clip_planning_text(item.get("description", ""), 42),
                    "expected_payoff_episode": item.get("expected_payoff_episode", ""),
                }
            )
        else:
            compact.append(_clip_planning_text(item, 36))
    return compact


def infer_prop_lifecycle_status(holder: Any, location: Any) -> str:
    """Handle infer prop lifecycle status."""
    holder_text = str(holder or "").strip()
    state_text = f"{holder_text} {str(location or '').strip()}"
    retired_terms = ("已丢弃", "垃圾桶", "马桶", "已销毁", "销毁", "焚烧", "冲走", "作废")
    if holder_text in {"", "无", "无人", "无持有人"} and any(term in state_text for term in retired_terms):
        return "已退出"
    return "有效"


def compact_handoff_for_block_prompt(handoff: dict[str, Any] | None) -> dict[str, Any]:
    """Handle compact handoff for block prompt."""
    if not isinstance(handoff, dict) or not handoff:
        return {}
    last_two = []
    for item in handoff.get("last_two_episode_summaries", [])[-2:]:
        if not isinstance(item, dict):
            continue
        last_two.append(
            {
                "episode_num": item.get("episode_num"),
                "title": _clip_planning_text(item.get("title", ""), 24),
                "closing_beat": _clip_planning_text(item.get("closing_beat", ""), 36),
                "next_episode_start_state": _clip_planning_text(item.get("next_episode_start_state", ""), 42),
                "ending_hook": _clip_planning_text(item.get("ending_hook", ""), 36),
                "unresolved_threads_after_episode": _compact_block_prompt_value(
                    item.get("unresolved_threads_after_episode", []),
                    text_limit=30,
                    list_limit=2,
                ),
                "event_ids": item.get("event_ids", []),
                "conflict_mode": item.get("conflict_mode", ""),
            }
        )
    return {
        "previous_block_id": handoff.get("previous_block_id"),
        "last_two_episode_summaries": last_two,
        "unresolved_threads": compact_unresolved_threads_for_handoff(handoff.get("unresolved_threads", [])),
        "running_character_state": compact_running_character_state_for_handoff(
                handoff.get("running_character_state", {}),
            ),
        "next_block_handoff": _clip_planning_text(handoff.get("next_block_handoff", ""), 60),
        "last_story_time": _compact_block_prompt_value(
            handoff.get("last_story_time", {}),
            text_limit=48,
        ),
        "current_fact_status": _compact_block_prompt_value(
            handoff.get("current_fact_status", {}),
            text_limit=24,
        ),
        "cumulative_consumed_child_beat_ids": [
            str(item).strip()
            for item in handoff.get("cumulative_consumed_child_beat_ids", []) or []
            if str(item).strip()
        ],
        "active_prop_registry": [
            {
                "prop_id": item.get("prop_id", ""),
                "prop_name": item.get("prop_name", ""),
                "holder": item.get("holder", ""),
                "location": item.get("location", ""),
                "lifecycle_status": item.get("lifecycle_status", "有效"),
                "last_updated_episode_num": item.get("last_updated_episode_num"),
            }
            for item in handoff.get("active_prop_registry", []) or []
            if isinstance(item, dict) and str(item.get("prop_id", "")).strip()
        ],
    }


def build_episode_planning_block_values(
    episode_planning_values: dict[str, Any],
    *,
    block: dict[str, Any],
    previous_handoff: dict[str, Any] | None = None,
    next_block: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Handle build episode planning block values."""
    start = int(block["start_episode"])
    end = int(block["end_episode"])
    block_id = int(block["block_id"])
    source_block = block.get("_source_block") if isinstance(block.get("_source_block"), dict) else block
    source_start = int(source_block.get("start_episode", start))
    source_end = int(source_block.get("end_episode", end))
    source_block_id = int(block.get("_source_block_id", source_block.get("block_id", block_id)))
    next_source_block_id = (
        int(next_block.get("_source_block_id", next_block.get("block_id", -1)))
        if isinstance(next_block, dict)
        else None
    )
    raw_block_event_pool = filter_items_for_episode_block(episode_planning_values.get("event_pool", []), block)
    raw_block_options = [
        dict(item)
        for item in episode_planning_values.get("episode_event_options", [])
        if isinstance(item, dict) and start <= int(item.get("episode_num", 0)) <= end
    ]
    uses_local_schedule = any("assigned_event_id" in item for item in raw_block_options)
    if uses_local_schedule:
        assigned_beat_ids_by_event: dict[int, set[str]] = {}
        legal_event_ids_for_chunk: set[int] = set()
        for item in raw_block_options:
            event_id = item.get("assigned_event_id")
            if not str(event_id).isdigit():
                continue
            numeric_event_id = int(event_id)
            legal_event_ids_for_chunk.add(numeric_event_id)
            assigned_beat_ids_by_event.setdefault(numeric_event_id, set()).update(
                str(beat_id).strip()
                for beat_id in item.get("assigned_child_beat_ids", []) or []
                if str(beat_id).strip()
            )
        block_event_pool: list[dict[str, Any]] = []
        for raw_event in raw_block_event_pool:
            if not isinstance(raw_event, dict) or not str(raw_event.get("id", "")).isdigit():
                continue
            event_id = int(raw_event["id"])
            if event_id not in legal_event_ids_for_chunk:
                continue
            event = dict(raw_event)
            assigned_ids = assigned_beat_ids_by_event.get(event_id, set())
            event["child_beats"] = [
                beat
                for beat in event.get("child_beats", []) or []
                if not isinstance(beat, dict)
                or str(beat.get("child_beat_id", "")).strip() in assigned_ids
            ]
            block_event_pool.append(event)
        block_episode_options = raw_block_options
    else:
        block_event_pool = []
        block_episode_options = []

    authorized_transactions = [
        transaction
        for option in block_episode_options
        if isinstance(option, dict)
        for transaction in option.get("authorized_transactions", []) or []
        if isinstance(transaction, dict)
    ]
    effective_prop_registry = [
        item
        for item in episode_planning_values.get("prop_registry", []) or []
        if isinstance(item, dict)
        and (
            _safe_int_value(item.get("created_episode")) <= 0
            or _safe_int_value(item.get("created_episode")) <= end
        )
    ]
    authorized_foreshadowing_pool = [
        item
        for item in episode_planning_values.get("foreshadowing_pool", []) or []
        if isinstance(item, dict)
        and any(
            event_transactions.text_matches_transaction(
                f"{item.get('setup', '')} {item.get('payoff', '')}",
                transaction,
            )
            for transaction in authorized_transactions
        )
    ]

    consumed_child_beat_ids = {
        str(item).strip()
        for item in (previous_handoff or {}).get("cumulative_consumed_child_beat_ids", []) or []
        if str(item).strip()
    }
    available_event_pool: list[dict[str, Any]] = []
    available_event_ids: set[int] = set()
    for raw_event in raw_block_event_pool:
        if not isinstance(raw_event, dict) or not str(raw_event.get("id", "")).isdigit():
            continue
        event = dict(raw_event)
        child_beats = event.get("child_beats")
        if isinstance(child_beats, list) and child_beats:
            available_beats = [
                beat
                for beat in child_beats
                if not isinstance(beat, dict)
                or str(beat.get("child_beat_id", "")).strip() not in consumed_child_beat_ids
            ]
            if not available_beats:
                continue
            event["child_beats"] = available_beats
        available_event_pool.append(event)
        available_event_ids.add(int(event["id"]))

    if not uses_local_schedule:
        legal_event_ids_for_chunk = set()
        for item in raw_block_options:
            valid_event_ids = [
                int(event_id)
                for event_id in item.get("valid_event_ids", [])
                if str(event_id).isdigit() and int(event_id) in available_event_ids
            ]
            legal_event_ids_for_chunk.update(valid_event_ids)
            block_episode_options.append({**item, "valid_event_ids": valid_event_ids})
        block_event_pool = [
            item
            for item in available_event_pool
            if int(item.get("id", -1)) in legal_event_ids_for_chunk
        ]
    scope = {
        "mode": "internal_block",
        "global_target_episodes": int(episode_planning_values.get("target_episodes", DEFAULT_TARGET_EPISODES)),
        "block_id": block_id,
        "start_episode": start,
        "end_episode": end,
        "episode_count": int(block.get("episode_count", end - start + 1)),
        "current_block": block,
        "parent_block_episode_range": {"start": source_start, "end": source_end},
        "parent_block_goal": source_block.get("goal", ""),
        "parent_block_hook": source_block.get("hook", ""),
        "chunk_is_parent_block_end": end == source_end,
        "next_chunk_episode_range": {
            "start": next_block.get("start_episode"),
            "end": next_block.get("end_episode"),
        }
        if isinstance(next_block, dict) and next_source_block_id == source_block_id
        else {},
        "previous_handoff": compact_handoff_for_block_prompt(previous_handoff),
        "next_block_target": {
            key: next_block.get(key)
            for key in ("block_id", "title", "start_episode", "end_episode", "goal", "hook")
        }
        if isinstance(next_block, dict) and next_source_block_id != source_block_id
        else {},
        "output_contract": {
            "top_level_keys": ["episode_outlines"],
            "episode_num_rule": f"episode_num 必须使用全局编号 {start}-{end}",
            "merge_rule": "runner 在本地生成篇章计划和状态交接，再合并成旧版 07_episode_planning shape。",
        },
    }
    return {
        **episode_planning_values,
        "episode_planning_scope": scope,
        "longform_blocks": [block],
        "phase_breakdown": filter_items_for_episode_block(episode_planning_values.get("phase_breakdown", []), block),
        "episode_budget": filter_items_for_episode_block(episode_planning_values.get("episode_budget", []), block),
        "event_release_schedule": filter_items_for_episode_block(
                episode_planning_values.get("event_release_schedule", []),
                block,
            ),
        "block_event_plan": filter_items_for_episode_block(episode_planning_values.get("block_event_plan", []), block),
        "block_state_plan": filter_items_for_episode_block(episode_planning_values.get("block_state_plan", []), block),
        "event_pool": block_event_pool,
        "episode_event_options": block_episode_options,
        "foreshadowing_pool": authorized_foreshadowing_pool,
        "prop_registry": effective_prop_registry,
        "dramatic_release_map": dramatic_release.slice_release_map(
            episode_planning_values.get("dramatic_release_map", {}),
            start_episode=start,
            end_episode=end,
        ),
    }


def clip_blocks_for_episode_limit(blocks: list[dict[str, Any]], episode_limit: int) -> list[dict[str, Any]]:
    """Handle clip blocks for episode limit."""
    if episode_limit <= 0:
        return []
    clipped: list[dict[str, Any]] = []
    for block in blocks:
        start = int(block.get("start_episode", 0))
        end = int(block.get("end_episode", 0))
        if start <= 0 or end < start:
            continue
        if start > episode_limit:
            break
        clipped_end = min(end, episode_limit)
        if clipped_end < start:
            continue
        next_block = dict(block)
        next_block["end_episode"] = clipped_end
        next_block["episode_count"] = clipped_end - start + 1
        clipped.append(next_block)
    return clipped


def split_blocks_for_episode_chunks(
    blocks: list[dict[str, Any]],
    *,
    max_episodes_per_chunk: int,
) -> list[dict[str, Any]]:
    """Handle split blocks for episode chunks."""
    if max_episodes_per_chunk <= 0:
        raise ValueError("max_episodes_per_chunk must be positive")
    chunks: list[dict[str, Any]] = []
    for block in blocks:
        start = int(block.get("start_episode", 0))
        end = int(block.get("end_episode", 0))
        if start <= 0 or end < start:
            continue
        public_block = public_episode_planning_block(block)
        total_chunks = (end - start + max_episodes_per_chunk) // max_episodes_per_chunk
        chunk_index = 1
        cursor = start
        while cursor <= end:
            chunk_end = min(end, cursor + max_episodes_per_chunk - 1)
            chunk = dict(public_block)
            chunk["start_episode"] = cursor
            chunk["end_episode"] = chunk_end
            chunk["episode_count"] = chunk_end - cursor + 1
            chunk["_source_block"] = public_block
            chunk["_source_block_id"] = int(public_block.get("block_id", 0))
            chunk["_chunk_index"] = chunk_index
            chunk["_chunk_count"] = total_chunks
            chunks.append(chunk)
            cursor = chunk_end + 1
            chunk_index += 1
    return chunks


def render_episode_planning_block_prompt(values: dict[str, Any]) -> str:
    """Handle render episode planning block prompt."""
    scope = values["episode_planning_scope"]
    current_block = scope["current_block"]
    prompt_current_block = public_episode_planning_block(current_block)
    if not scope.get("chunk_is_parent_block_end"):
        prompt_current_block["goal"] = "本批只推进逐集合法事件，不要求提前完成父篇章总目标。"
        prompt_current_block["hook"] = "只写本集可见结果后的下一拍，父篇章总钩子留到父篇章末批。"
    allowed_character_names = collect_allowed_character_names(
        values.get("canonical_story_lock", {}),
        values.get("expanded_character_network", []),
    )
    scope_summary = {
        "mode": scope.get("mode"),
        "global_target_episodes": scope.get("global_target_episodes"),
        "block_id": scope.get("block_id"),
        "episode_range": {"start": scope.get("start_episode"), "end": scope.get("end_episode")},
        "episode_count": scope.get("episode_count"),
        "parent_block_episode_range": scope.get("parent_block_episode_range", {}),
        "parent_block_goal": scope.get("parent_block_goal", ""),
        "parent_block_hook": scope.get("parent_block_hook", ""),
        "chunk_is_parent_block_end": scope.get("chunk_is_parent_block_end", False),
        "next_chunk_episode_range": scope.get("next_chunk_episode_range", {}),
    }
    field_labels = llm_schema_localization.FIELD_LABELS

    def field(key: str) -> str:
        """Handle field."""
        return f"`{field_labels[key]}`"

    def fields(*keys: str) -> str:
        """Handle fields."""
        return "、".join(f"`{field_labels[key]}`" for key in keys)

    episode_start = int(current_block.get("start_episode", 0))
    opening_payoff_rule = "- 前3集至少有1次主角可见胜利或反派可见受挫；第4-5集必须再完成1次新的微型兑现。"
    if episode_start == 3:
        opening_payoff_rule = "- 本集是前3集兑现截止集：必须完成一个主角可见胜利或反派可见受挫，不能只铺垫、逃离或延续施压。"
    elif episode_start == 5:
        opening_payoff_rule = "- 本集是前5集第二个兑现截止集：必须在前3集兑现之后，再产生一个新的主角胜利、反派损失或权力转折。"

    episode_fields = fields(
        "episode_num",
        "title",
        "block_id",
        "phase",
        "episode_reason",
        "main_conflict",
        "counterattack",
        "information_gain",
        "state_change",
        "opening_beat",
        "closing_beat",
        "next_episode_start_state",
        "consumed_child_beat_ids",
        "event_ids",
        "foreshadowing_ids",
        "required_character_names",
        "appearing_character_names",
        "ending_hook",
        "adapted_plot_point_ids",
        "conflict_mode",
        "pattern_family",
        "payoff_level",
        "event_role",
        "event_consumption_status",
        "source_anchor",
        "expansion_delta",
        "boundary_check",
        "content_sensitivity_check",
        "unresolved_threads_after_episode",
        "is_epilogue",
        "scene_plan",
        "narration_device_plan",
        "target_script_density",
        "prop_continuity_plan",
        "source_fact_ids",
        "story_time",
        "fact_transitions",
        "dramatic_target_id",
    )
    return "\n\n".join(
        [
            "# 任务目标",
            "完成 07 剧集规划的当前篇章分批，输出可供本地程序合并的分集大纲。",
            "## 本环节边界",
            "这是 07 剧集规划的内部分批调用，不是新环节。只规划指定集数，不写剧本正文。绝对不输出思考过程、分析过程、Markdown 说明或代码块；第一字符必须是 `{`，最后一字符必须是 `}`。",
            "## 输入材料",
            "### 本次范围",
            prompt_renderer.stringify_for_prompt("episode_planning_scope", scope_summary),
            "### 全局运行配置",
            prompt_renderer.stringify_for_prompt("run_config", values.get("run_config")),
            "### 系统派生规则",
            prompt_renderer.stringify_for_prompt("derived_config", values.get("derived_config")),
            "### 源故事锁",
            prompt_renderer.stringify_for_prompt(
                "canonical_story_lock",
                compact_canonical_story_lock_for_block_prompt(values.get("canonical_story_lock", {})),
            ),
            "### 允许出现人物名",
            prompt_renderer.stringify_for_prompt("appearing_character_names", allowed_character_names),
            "### 当前篇章",
            prompt_renderer.stringify_for_prompt("current_block", prompt_current_block),
            "### 上一批交接",
            prompt_renderer.stringify_for_prompt("previous_handoff", scope.get("previous_handoff", {})),
            "### 下一篇章目标",
            prompt_renderer.stringify_for_prompt("next_block_target", scope.get("next_block_target", {})),
            "### 逐集合法事件选项",
            prompt_renderer.stringify_for_prompt("episode_event_options", values.get("episode_event_options", [])),
            "### 当前篇章事件池",
            prompt_renderer.stringify_for_prompt(
                "event_pool",
                compact_event_pool_for_block_prompt(values.get("event_pool", [])),
            ),
            "### 伏笔池",
            prompt_renderer.stringify_for_prompt(
                "foreshadowing_pool",
                _compact_block_prompt_value(values.get("foreshadowing_pool", []), text_limit=32, list_limit=5),
            ),
            "### 原著事实账本",
            prompt_renderer.stringify_for_prompt(
                "source_fact_ledger",
                _compact_block_prompt_value(values.get("source_fact_ledger", []), text_limit=42, list_limit=16),
            ),
            "### 关键道具实体表",
            prompt_renderer.stringify_for_prompt(
                "prop_registry",
                _compact_block_prompt_value(values.get("prop_registry", []), text_limit=42, list_limit=None),
            ),
            "### 改编容量评估",
            prompt_renderer.stringify_for_prompt("adaptation_capacity", values.get("adaptation_capacity", {})),
            "### 本批不可变戏剧释放目标",
            prompt_renderer.stringify_for_prompt("dramatic_release_map", values.get("dramatic_release_map", {})),
            "### 闪回筛选结果",
            prompt_renderer.stringify_for_prompt(
                "flashback_screening",
                _compact_block_prompt_value(values.get("flashback_screening", {}), text_limit=42, list_limit=12),
            ),
            "### 人物网络",
            prompt_renderer.stringify_for_prompt(
                "expanded_character_network",
                compact_character_network_for_block_prompt(values.get("expanded_character_network", [])),
            ),
            "### 冲突发动机",
            prompt_renderer.stringify_for_prompt(
                "conflict_engine",
                compact_conflict_engine_for_block_prompt(values.get("conflict_engine", {})),
            ),
            "### 篇章状态计划",
            prompt_renderer.stringify_for_prompt(
                "block_state_plan",
                _compact_block_prompt_value(values.get("block_state_plan", []), text_limit=42, list_limit=3),
            ),
            "### 质量规则",
            prompt_renderer.stringify_for_prompt(
                "qa_rules",
                _compact_block_prompt_value(values.get("qa_rules", []), text_limit=42, list_limit=8),
            ),
            "## 输出 JSON 示例",
            """{
  "分集大纲": []
}""",
            "顶层必须只有 `分集大纲`。篇章计划和状态交接由本地程序从上游和本批最后一集确定性生成，模型不要输出。每个分集大纲必须包含：\n" + episode_fields,
            f"`边界检查` 必须包含 {fields('risk_level', 'protagonist_action', 'why_allowed', 'mitigation')}。",
            f"`内容敏感检查` 必须包含 {fields('risk_level', 'risk_reason', 'mitigation')}。",
            f"{field('scene_plan')} 每项必须包含 {fields(
                'scene_no',
                'location',
                'time',
                'space',
                'appearing_character_names',
                'scene_purpose',
                'must_include_beats',
                'scene_boundary_reason',
                'visible_space_tokens',
            )}。",
            f"`叙事手法计划` 必须包含 {fields(
                'planned_os_count',
                'planned_flashback_count',
                'planned_flashback_quota_count',
                'planned_vo_count',
                'reason',
                'visual_replacement_strategy',
                'approved_flashback_time_deviation_ids',
                'approved_os_time_deviation_ids',
                'visualized_time_deviation_ids',
                'deleted_or_rewritten_time_deviation_ids',
            )}。",
            f"`目标剧本密度` 必须包含 {fields(
                'target_range_chars',
                'minimum_effective_chars',
                'maximum_chars',
                'must_cover_beats',
                'optional_compression_beats',
                'expansion_strategy',
                'scene_char_budgets',
            )}。",
            f"{field('must_cover_beats')} 每项只包含 {field('beat_id')}；canonical 动作和完成证据由本地事务注册表关联，模型不要复写。",
            f"{field('scene_char_budgets')} 每项必须包含 {fields('scene_no', 'target_chars', 'must_cover_beat_ids')}。",
            (
                f"每集的 {field('dramatic_target_id')} 必须原样引用本批不可变戏剧释放目标中同集号的 {field('release_id')}；主要冲突、反击点、"
                f"状态变化、收尾情节和结尾钩子必须执行该目标的欲望、阻力、选择、即时代价、末场可见结果和钩子，不得自行换成纯流程。"
            ),
            f"{field('prop_continuity_plan')} 每项必须包含 {fields(
                'prop_id',
                'prop_name',
                'start_holder',
                'start_location',
                'end_holder',
                'end_location',
                'transfer_action',
                'completion_evidence',
            )}。",
            f"{field('story_time')} 必须包含 {fields('day_index', 'time_label', 'elapsed_from_previous')}。",
            f"{field('fact_transitions')} 每项必须包含 {fields('fact_id', 'from_status', 'to_status', 'evidence')}。",
            "## 执行规则",
            "\n".join(
                [
                    f"- 只生成第 {current_block['start_episode']}-{current_block['end_episode']} 集。",
                    "- `父篇章总目标` 和 `父篇章总钩子` 是整个父篇章的累计目标，不是当前单集 KPI；只有“本批是否父篇章末批”为 true 时才允许在本批完成总目标或兑现总钩子。",
                    "- 当前单集只推进 `逐集合法事件选项` 中本地预分配的事件和 child beat；不得为了提前完成父篇章总目标借用未来事件或下一批 child beat。",
                    "- 每集只声明 `逐集合法事件选项` 中的已分配事件ID，并执行其中已分配的1-3个 canonical 子情节点ID；这是本地全季调度结果，模型不得另选、增删或调换。",
                    "- `分集大纲` 数量必须等于当前篇章的 `集数`，`集号` 使用全剧编号。",
                    f"- 不得用简化情节字段替代 {fields('main_conflict', 'counterattack', 'information_gain', 'state_change')}。",
                    f"- 非尾声集的 {field('main_conflict')} 和 {field('counterattack')} 不能写“无”；第1集也必须有压力源和主角最小回应。",
                    "- `必需人物姓名` 和 `出场人物姓名` 只能使用“允许出现人物名”；不得新增神婆、邻居、医生、警察等未列名人物。",
                    "- `必需人物姓名` 必须同时出现在 `出场人物姓名`；主角显示名必须始终一致。",
                    "- `已消耗子情节点ID` 只能引用本集授权事务ID，不允许借用未声明事件的事务；模型不要输出 `已消耗子情节点` 文本，本地会按事务注册表确定性关联 canonical 动作。",
                    "- 本集事件必须完整消费本地分配的1-3个新子情节点；不得把一个子情节点拆成 -a/-b/-ext 后缀，不得写裸 B1/B2，也不得自行追加未分配子情节点。",
                    "- 先读取上一批交接中的 `已累计消耗子情节点ID`；其中任何ID都不得再次写入本集，除非本集只承接其结果且不再声明为已消耗。",
                    "- 同一事件拆到多集时，每集继续挂同一个事件ID，直到关键子情节点累计消耗完；真正执行动作不能漂移到别的事件ID下。",
                    "- 模型只执行本集已分配事务；`事件消耗状态` 只作阅读说明，真正完成状态由本地事务排期和完成证据审计，不会回写模型字段。",
                    f"- {field('source_fact_ids')} 只能引用原著事实账本已有ID，表示本集真正执行或推进的事实。",
                    f"- {field('story_time')} 用全剧单调不减的故事日序号和可读时间标记；非闪回不得把日序号写回过去。",
                    f"- {field('story_time')} 的故事日序号一律取本集最后一场所在的日历日；一集跨日时在时间标记里写清起止，不得用第一场日期造成下集回退。",
                    "- 故事时间与‘今天、明天、考前一天、考试当天’等台词必须一致；若故事时间已是考试当天，正文计划不得再说‘明天考试’。",
                    "- 前世事实只是观众与主角的过往信息，不是当前时间线已发生事件。未在当世正文重新发生的伤害，对白不得用‘上次、之前、又、差点死了’写成本世共同经历。",
                    f"- {field('fact_transitions')} 只记录本集中被证据改变的事实状态；状态只能使用未知、怀疑、已知、已确认、已解决，变更必须有正文可见证据。",
                    opening_payoff_rule,
                    (
                        "- 微型兑现不等于主角暂时没受害；必须让主角完成明确目标，或让反派丢失控制、资源、脸面、证据优势中的一项，并写进事件作用、回收级别和状态变化。兑现只能来自本集合法事件的未消费子"
                        "情节点；没有大结果时写更小的当场胜利，禁止借用未来事件、录取结果、判决结果或后续篇章资产。"
                    ),
                    "- 回收级别只能写铺垫、推进、兑现、高潮兑现、终局兑现之一；只要本集完成明确目标或让反派遭受可见损失，就必须写兑现或更高等级，不能把已经发生的可见结果标成铺垫级。",
                    "- 本集作用和主要冲突必须写清主角当前欲望与具体阻力；反击点写清主角选择及即时代价；状态变化写可见结果。不能只复述流程。",
                    "- 前5集不得连续两集重复“来电、拒接、关机、继续考试”。原著前段已有现场泄密、质问、暴力代价或关系决裂时，第3-5集至少安排一次现场对抗，不能推迟到正式结果之后。",
                    (
                        "- 外部流程必须区分行动完成、结果发布、申请、正式结果、通知和执行。查分只得到分数、位次和批次线；达到往年院校线只能写可尝试填报，不得写录取资格。新生群、报到须知、宿舍安排和赴"
                        "校报到必须晚于正式录取。"
                    ),
                    "- 主角“不拦不帮”只能撤回保护、拒绝兜底或不再阻止既有因果，不能规划故意混放、栽赃、替换材料或主动制造违规结果。",
                    "- 同一伏笔ID第一次引用视为投放；后续再引用时，事件作用或回收级别必须明写升级/递进/回收/兑现，信息增量必须提供新证据或新结果，不得重演同一噩梦、动作、台词或反应。",
                    f"- {field('scene_plan')} 是给 08 正文执行的时空单元，不是剧情节拍列表；同一地点、同一时间、同一内外、同一批人物的连续对话必须合在同一场。",
                    "- `时间` 只能使用“日”、“夜”、“傍晚”；清晨/早上/上午/中午/下午/白/白天统一写“日”，晚上/夜晚/深夜/凌晨统一写“夜”，黄昏写“傍晚”。",
                    "- 单个场头只能对应一个连续的内或外空间。教室内与教学楼外、客厅与阳台等跨越内外边界时必须拆成自然场，不得输出“内外”或“外转内”。",
                    "- `出场人物姓名` 必须列全本场出镜、开口、电话/VO出声或背景执行动作的人；前台、秘书、助理、保安、司机、接线员等泛角色只要有可见动作也必须列入。",
                    "- 场头地点必须覆盖本场所有可见空间；隔门、隔窗、玻璃门外看到另一空间时，地点必须写成“走廊及会议室外/会议室门口”这类覆盖范围，或另开自然场，不得在“走廊及工位区”里写会议室内可见动作。",
                    "- 每个自然场必须写 `可见空间词`，列出所有可见空间；08 场头地点必须覆盖这些词。",
                    (
                        f"- {fields(
                'scene_plan',
                'must_include_beats',
                'opening_beat',
                'closing_beat',
                'next_episode_start_state',
            )} "
                        f"禁止写语气、声调、音量、语速、沉声、低声、平声、冷声、轻声、淡淡、漫不经心；改用可见动作。"
                    ),
                    "- 自然分场和开收尾节拍禁止写镜头推近、镜头停在、镜头切到、定格；只写画面中真实出现的人、物、动作和屏幕内容。",
                    "- 同一时空里角色只是退到门口、门边、门外、靠墙或背对，仍然算出镜人物，必须继续列入出场人物；这不能作为切场理由。",
                    "- 看截图、催签、签字、收手机或拿行李这类连续动作应合并为同一自然场，不要为了程序收尾感硬拆。",
                    f"- 不要把施压段、反制段、情绪节拍变化作为独立自然场；它们只能写进同一场的 {field('must_include_beats')}。一集只有一个连续时空单元时可以只写1场。",
                    (
                        f"- 关键道具、文件、手机、支票、合同的状态不能在相邻集回卷；如果上一集写明道具已留下、被拿走或已交付，本集 {field('opening_beat')} 和 "
                        f"{field('must_include_beats')} 必须先交代谁把道具递回、推回或拿起。"
                    ),
                    (
                        f"- 每集必须写 {field('prop_continuity_plan')}；无关键道具写空数组。同一实物跨集复用同一 {field('prop_id')}。持有人或位置变化"
                        f"时必须写可拍摄的 {field('transfer_action')} 和 {field('completion_evidence')}，不允许无动作跳变。"
                    ),
                    (
                        "- 先读取上一批交接中的 `当前关键道具注册表`：同一道具必须沿用原ID和名称，本集开始持有人/开始位置必须承接注册表。05关键道具实体表中的全部 PROP 数字ID均已预留，"
                        "07临时新增道具必须使用 PROP_EP集号_序号（如 PROP_EP003_01），不得占用预留ID或按单集重置为 D1/D2。"
                    ),
                    "- `当前关键道具注册表` 中生命周期状态为“已退出”的实物不得再次出现；若剧情确实新增同类物品，必须写可见来源并使用新的全剧唯一道具ID。",
                    (
                        f"- 相邻自然场不得完全重复 {fields('location', 'time', 'space', 'appearing_character_names')}；除非是闪回、交"
                        f"叉剪辑或并行动作，并在 {field('scene_boundary_reason')} 写清真实剪辑理由。"
                    ),
                    "- 每集必须写 `叙事手法计划`；默认 OS/闪回/闪回配额/VO 计数都写0，四个时间线偏离ID数组都写空数组，优先用可见道具、屏幕、合同和对话替代 OS 与闪回。",
                    (
                        f"- 若计划闪回、插叙、倒叙、平行剪辑、闪前、梦境或幻觉式回溯，{field('approved_flashback_time_deviation_ids')} 只能引用 04a"
                        f" {field('retained_time_deviations')} 中的 S/A 项；B/C 项禁止引用。"
                    ),
                    (
                        f"- 执行闪回的 {field('scene_plan')} 必须在 {field('scene_purpose')} 或 "
                        f"{field('scene_boundary_reason')} 明写‘flashback/闪回/前世’，便于本地程序将历史画面与当前流程时序分开审计。"
                    ),
                    (
                        f"- A 级时间偏离如改成 OS 或当下可视化，只能写入 {field('approved_os_time_deviation_ids')} 或 "
                        f"{field('visualized_time_deviation_ids')}，不计入闪回配额。"
                    ),
                    (
                        f"- 引用 S 项作为闪回时只增加 {field('planned_flashback_count')}；引用 A 项时同时增加 "
                        f"{field('planned_flashback_count')} 和 {field('planned_flashback_quota_count')}。全剧 "
                        f"{field('planned_os_count')} + {field('planned_flashback_quota_count')} 不得超过5。"
                    ),
                    "- 04a 中 B 级项必须转成当下动作、道具、屏幕、台词追问或人物反应；C 级项不得进入分集大纲。",
                    "- 每集必须写 `目标剧本密度`；90秒每集的唯一创作目标是650-780字，`最低有效字数`=650，`最大字数`=780。本地 validator 的更宽容忍范围不是创作目标。",
                    f"- {field('must_cover_beats')} 只能有1-3个；每项只输出 {field('beat_id')}，不得重复填写或改写 canonical 动作和完成证据。",
                    f"- {field('must_cover_beats')} 的 {field('beat_id')} 必须与本集已消耗子情节点ID完全一致，不得另造局部编号或拆分后缀。",
                    (
                        "- 逐集合法事件选项中的 `本集授权事务` 是不可变执行契约。07 只选择并编排授权事务ID，canonical 动作、状态效果和完成证据由本地 registry join 注"
                        "入 08，不要求模型逐字复写。"
                    ),
                    "- 所属集数晚于本集的事务及其状态效果均禁止提前执行。任何规划字段都不得同时命中后续事务的完成证据词或状态效果证据词组合。",
                    (
                        f"- {field('scene_char_budgets')} 必须与 {field('scene_plan')} 一一对应，{field('target_chars')} 合"
                        f"计在650-780之间，每个 {field('beat_id')} 只分配一次。只有1场时该场承担整集预算，不得为分摊字数硬拆场。"
                    ),
                    (
                        f"- {field('scene_plan')} 中的必须包含情节、开场情节和收尾情节只是同一批 {field('must_cover_beats')} 的空间安排与起止位置，不"
                        f"是额外剧情任务；不得把它们分别展开一遍。"
                    ),
                    "- 前5集单集只覆盖一个连续行动段；跨数日等待后的新结果必须留到后续集。不得在同一集同时写考试开始、考试完成和数十天后的录取结果。",
                    "- 通话、录音、截图和系统记录必须写清设备或记录归属：某人的呼出记录只能出现在该人的设备或运营记录中，接收方只能看到来电记录；未建立录音来源时不得直接用VO复现过去通话内容。",
                    "- 如果本集有 VO、电话、来电、接通、听筒传来或画外声音场，`计划VO次数` 按实际场景数计数。",
                    "- 电话/画外声只在规划层写“某人通过电话说出某信息”或“听筒传来某人声音”，不要写 `某人（VO，语气...）`；08 正文只能用 `人物（VO）：台词`。",
                    f"- 相邻集承接以前一集 {field('next_episode_start_state')} 为准；如果上一集结尾是拨出电话、正在通话或等待接听，下一集第一场必须先承接电话动作。",
                    "- `冲突模式` 和 `模式家族` 都不能连续超过配置上限；同一合同/商业单连续推进时，也要按本集动作拆成追薪压价、证据存档、情报施压、资源拉拢、合同签署等更细中文短标签。",
                    "- 跨篇章的第一集开场节拍只能承接上一集结果后的下一拍，不能重演上一集收尾节拍已完成动作。",
                    "- 如果需要迷信施压、围观压力或规则介入，必须由已有角色或已列出的扩展人物承担功能。",
                    f"- 第一个 {field('opening_beat')} 必须承接 {field('previous_handoff')}；第一个篇章承接源故事第一压力点。",
                    f"- 最后一集必须写清 {field('closing_beat')} 和 {field('next_episode_start_state')}，供下一篇章继续。",
                    "- `事件ID` 只能从本篇章逐集合法事件选项中的 `合法事件ID` 选择。",
                    "- 不得重复上一批交接中最近两集已完成的动作。",
                    "- 如果需要铺垫下一篇章，只能写入 `信息增量`、`伏笔ID` 或 `本集后未解决线索`。",
                    "- 保留原著激烈冲突时只做风险记录，不因内容敏感风险为“高”就删除事件。",
                    "- 字段短句化，普通说明不超过24字，风险检查子字段不超过18字。",
                    "- JSON 字符串中不要出现英文双引号；如需表达台词或截图文字，改用中文引号或直接转述。",
                    "- 不要生成正文，只返回合法 JSON。",
                ]
            ),
            "## 输出前自检",
            (
                "1. 顶层只有分集大纲；分集数和全剧集号正确。\n"
                "2. 每集的嵌套对象和自然分场字段齐全，事件ID可对账。\n"
                "3. 分场依据真实时空变化，人物、地点、道具和相邻集状态连续。\n"
                "4. 闪回/OS/VO 与 04a 和全剧配额一致。\n"
                "5. 输出是单个合法 JSON 对象，没有额外说明。"
            ),
        ]
    )


def _block_plan_from_output(data: dict[str, Any], block: dict[str, Any]) -> dict[str, Any]:
    """Handle block plan from output."""
    del data
    plan = public_episode_planning_block(block)
    plan["block_id"] = int(block["block_id"])
    plan["start_episode"] = int(block["start_episode"])
    plan["end_episode"] = int(block["end_episode"])
    plan["episode_count"] = int(block.get("episode_count", plan["end_episode"] - plan["start_episode"] + 1))
    return plan


def _normalized_prop_name(value: Any) -> str:
    """Handle normalized prop name."""
    return re.sub(r"[\s·、，,。()（）《》“”\"'：:]+", "", str(value or "")).lower()


def normalize_episode_prop_plan_ids(
    episodes: list[dict[str, Any]],
    *,
    prop_registry: list[dict[str, Any]],
    previous_handoff: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Handle normalize episode prop plan ids."""
    reserved_by_id = {
        str(item.get("prop_id", "")).strip(): item
        for item in prop_registry
        if isinstance(item, dict) and str(item.get("prop_id", "")).strip()
    }
    reserved_id_by_name = {
        _normalized_prop_name(item.get("prop_name", "")): prop_id
        for prop_id, item in reserved_by_id.items()
        if _normalized_prop_name(item.get("prop_name", ""))
    }
    known_id_by_name: dict[str, str] = {}
    used_ids = set(reserved_by_id)
    for item in (previous_handoff or {}).get("active_prop_registry", []) or []:
        if not isinstance(item, dict):
            continue
        prop_id = str(item.get("prop_id", "")).strip()
        prop_name = _normalized_prop_name(item.get("prop_name", ""))
        if prop_id:
            used_ids.add(prop_id)
        if prop_id and prop_name:
            known_id_by_name[prop_name] = prop_id

    normalized_episodes: list[dict[str, Any]] = []
    for raw_episode in episodes:
        episode = dict(raw_episode)
        episode_num = _safe_int_value(episode.get("episode_num"))
        plans: list[Any] = []
        local_counter = 0
        for raw_plan in episode.get("prop_continuity_plan", []) or []:
            if not isinstance(raw_plan, dict):
                plans.append(raw_plan)
                continue
            plan = dict(raw_plan)
            original_id = str(plan.get("prop_id", "")).strip()
            prop_name = str(plan.get("prop_name", "")).strip()
            normalized_name = _normalized_prop_name(prop_name)
            assigned_id = known_id_by_name.get(normalized_name, "")
            if not assigned_id and normalized_name in reserved_id_by_name:
                candidate_id = reserved_id_by_name[normalized_name]
                candidate = reserved_by_id[candidate_id]
                created_episode = _safe_int_value(
                    candidate.get("activation_episode", candidate.get("created_episode"))
                )
                if created_episode <= 0 or episode_num >= created_episode:
                    assigned_id = candidate_id
            reserved = reserved_by_id.get(original_id)
            if not assigned_id and reserved is not None:
                reserved_name = _normalized_prop_name(reserved.get("prop_name", ""))
                created_episode = _safe_int_value(reserved.get("created_episode"))
                if normalized_name == reserved_name and (created_episode <= 0 or episode_num >= created_episode):
                    assigned_id = original_id
            if not assigned_id and original_id and original_id not in used_ids:
                assigned_id = original_id
            if not assigned_id:
                local_counter += 1
                assigned_id = f"PROP_EP{episode_num:03d}_{local_counter:02d}"
                while assigned_id in used_ids:
                    local_counter += 1
                    assigned_id = f"PROP_EP{episode_num:03d}_{local_counter:02d}"
            if assigned_id != original_id:
                plan.pop("prop_id_repair_trace", None)
            plan["prop_id"] = assigned_id
            used_ids.add(assigned_id)
            if normalized_name:
                known_id_by_name[normalized_name] = assigned_id
            plans.append(plan)
        episode["prop_continuity_plan"] = plans
        normalized_episodes.append(episode)
    return normalized_episodes


def align_episode_prop_plan_start_states(
    episodes: list[dict[str, Any]],
    *,
    prop_registry: list[dict[str, Any]],
    previous_handoff: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Handle align episode prop plan start states."""
    current_state: dict[str, dict[str, Any]] = {}
    activation_episode: dict[str, int] = {}
    for item in prop_registry:
        if not isinstance(item, dict):
            continue
        prop_id = str(item.get("prop_id", "")).strip()
        if not prop_id:
            continue
        initial = item.get("initial_state") if isinstance(item.get("initial_state"), dict) else {}
        current_state[prop_id] = {
            "holder": initial.get("holder", item.get("holder", "")),
            "location": initial.get("location", item.get("location", "")),
        }
        activation_episode[prop_id] = _safe_int_value(
            item.get("activation_episode", item.get("created_episode"))
        )
    for item in (previous_handoff or {}).get("active_prop_registry", []) or []:
        if not isinstance(item, dict):
            continue
        prop_id = str(item.get("prop_id", "")).strip()
        if prop_id:
            current_state[prop_id] = {
                "holder": item.get("holder", ""),
                "location": item.get("location", ""),
            }

    normalized: list[dict[str, Any]] = []
    for raw_episode in episodes:
        episode = dict(raw_episode)
        episode_num = _safe_int_value(episode.get("episode_num"))
        next_plans: list[Any] = []
        for raw_plan in episode.get("prop_continuity_plan", []) or []:
            if not isinstance(raw_plan, dict):
                next_plans.append(raw_plan)
                continue
            plan = dict(raw_plan)
            prop_id = str(plan.get("prop_id", "")).strip()
            known = current_state.get(prop_id)
            if known is not None and episode_num >= activation_episode.get(prop_id, 0):
                plan["start_holder"] = known.get("holder", "")
                plan["start_location"] = known.get("location", "")
            current_state[prop_id] = {
                "holder": plan.get("end_holder", plan.get("start_holder", "")),
                "location": plan.get("end_location", plan.get("start_location", "")),
            }
            next_plans.append(plan)
        episode["prop_continuity_plan"] = next_plans
        normalized.append(episode)
    return normalized


def align_episode_fact_transition_starts(
    episodes: list[dict[str, Any]],
    *,
    previous_handoff: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Handle align episode fact transition starts."""
    current_status = {
        str(key): value
        for key, value in ((previous_handoff or {}).get("current_fact_status", {}) or {}).items()
    }
    normalized: list[dict[str, Any]] = []
    for raw_episode in episodes:
        episode = dict(raw_episode)
        next_transitions: list[Any] = []
        for raw_transition in episode.get("fact_transitions", []) or []:
            if not isinstance(raw_transition, dict):
                next_transitions.append(raw_transition)
                continue
            transition = dict(raw_transition)
            fact_id = str(transition.get("fact_id", "")).strip()
            if fact_id:
                transition["from_status"] = current_status.get(fact_id, "unknown")
                current_status[fact_id] = transition.get("to_status", "")
            next_transitions.append(transition)
        episode["fact_transitions"] = next_transitions
        normalized.append(episode)
    return normalized


def apply_local_episode_event_schedule(
    episodes: list[dict[str, Any]],
    *,
    episode_event_options: list[dict[str, Any]],
    event_pool: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Handle apply local episode event schedule."""
    option_by_episode = {
        int(item.get("episode_num")): item
        for item in episode_event_options
        if isinstance(item, dict)
        and str(item.get("episode_num", "")).isdigit()
        and str(item.get("assigned_event_id", "")).isdigit()
    }
    beat_by_id, _ids_by_action = _event_child_beat_lookup(event_pool)
    normalized: list[dict[str, Any]] = []
    for raw_episode in episodes:
        episode = dict(raw_episode)
        episode_num = _safe_int_value(episode.get("episode_num"))
        option = option_by_episode.get(episode_num)
        if option is None:
            normalized.append(episode)
            continue
        event_id = int(option["assigned_event_id"])
        beat_ids = [
            str(item).strip()
            for item in option.get("assigned_child_beat_ids", []) or []
            if str(item).strip()
        ]
        episode["event_ids"] = [event_id]
        episode["consumed_child_beat_ids"] = beat_ids
        episode["consumed_child_beats"] = [
            str(beat_by_id[item].get("action", "")).strip()
            for item in beat_ids
            if item in beat_by_id and str(beat_by_id[item].get("action", "")).strip()
        ]
        episode.pop("event_schedule_repair_trace", None)
        normalized.append(episode)
    return normalized


def normalize_episode_planning_block_output(data: dict[str, Any], block_values: dict[str, Any]) -> dict[str, Any]:
    """Handle normalize episode planning block output."""
    scope = block_values["episode_planning_scope"]
    block = scope["current_block"]
    start = int(block["start_episode"])
    end = int(block["end_episode"])
    episodes = data.get("episode_outlines")
    if not isinstance(episodes, list):
        raise ValueError(f"07 block {block.get('block_id')} missing episode_outlines")
    normalized_episodes: list[dict[str, Any]] = []
    for item in episodes:
        if not isinstance(item, dict):
            continue
        episode = dict(item)
        episode["block_id"] = int(block["block_id"])
        normalized_episodes.append(episode)
    scheduled = apply_local_episode_event_schedule(
        normalized_episodes,
        episode_event_options=block_values.get("episode_event_options", []),
        event_pool=block_values.get("_full_event_pool_for_repair", block_values.get("event_pool", [])),
    )
    aligned_density = align_episode_target_script_density_ids(
        {"episode_outlines": scheduled},
    ).get("episode_outlines", scheduled)
    normalized_episodes = normalize_episode_prop_plan_ids(
        aligned_density,
        prop_registry=block_values.get("prop_registry", []),
        previous_handoff=scope.get("previous_handoff", {}),
    )
    normalized_episodes = align_episode_prop_plan_start_states(
        normalized_episodes,
        prop_registry=block_values.get("prop_registry", []),
        previous_handoff=scope.get("previous_handoff", {}),
    )
    normalized_episodes = align_episode_fact_transition_starts(
        normalized_episodes,
        previous_handoff=scope.get("previous_handoff", {}),
    )
    completed_event_ids: list[Any] = []
    active_event_ids: list[Any] = []
    foreshadowing_ids: list[Any] = []
    for episode in normalized_episodes:
        event_target = (
            completed_event_ids
            if str(episode.get("event_consumption_status", "")).lower() in {"completed", "block_payoff", "已完成", "篇章回收"}
            else active_event_ids
        )
        for event_id in episode.get("event_ids", []) or []:
            if event_id not in event_target:
                event_target.append(event_id)
        for foreshadowing_id in episode.get("foreshadowing_ids", []) or []:
            if foreshadowing_id not in foreshadowing_ids:
                foreshadowing_ids.append(foreshadowing_id)
    last_episode = normalized_episodes[-1] if normalized_episodes else {}
    state_delta = {
        "block_id": int(block["block_id"]),
        "completed_episode_range": {"start": start, "end": end},
        "running_character_state": last_episode.get("state_change", {}),
        "unresolved_threads": last_episode.get("unresolved_threads_after_episode", []),
        "next_block_handoff": last_episode.get("next_episode_start_state", ""),
        "completed_event_ids": completed_event_ids,
        "active_event_ids": active_event_ids,
        "foreshadowing_ids": foreshadowing_ids,
    }
    return {
        "block_plan": _block_plan_from_output(data, block),
        "episode_outlines": normalized_episodes,
        "state_delta": state_delta,
    }


def build_episode_planning_handoff(
    block_output: dict[str, Any],
    *,
    previous_handoff: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Handle build episode planning handoff."""
    previous_handoff = previous_handoff if isinstance(previous_handoff, dict) else {}
    episodes = [
        item
        for item in block_output.get("episode_outlines", [])
        if isinstance(item, dict) and str(item.get("episode_num", "")).isdigit()
    ]
    last_two = episodes[-2:]
    last_two_summaries = [
        {
            "episode_num": item.get("episode_num"),
            "title": item.get("title", ""),
            "closing_beat": item.get("closing_beat", ""),
            "next_episode_start_state": item.get("next_episode_start_state", ""),
            "ending_hook": item.get("ending_hook", ""),
            "unresolved_threads_after_episode": item.get("unresolved_threads_after_episode", []),
            "state_change": item.get("state_change", {}),
            "event_ids": item.get("event_ids", []),
            "consumed_child_beat_ids": item.get("consumed_child_beat_ids", []),
            "conflict_mode": item.get("conflict_mode", ""),
            "source_anchor": item.get("source_anchor", ""),
            "source_fact_ids": item.get("source_fact_ids", []),
            "story_time": item.get("story_time", {}),
            "fact_transitions": item.get("fact_transitions", []),
        }
        for item in last_two
    ]
    cumulative_consumed_ids = [
        str(item).strip()
        for item in previous_handoff.get("cumulative_consumed_child_beat_ids", []) or []
        if str(item).strip()
    ]
    for episode in episodes:
        for item in episode.get("consumed_child_beat_ids", []) or []:
            beat_id = str(item).strip()
            if beat_id and beat_id not in cumulative_consumed_ids:
                cumulative_consumed_ids.append(beat_id)

    prop_registry_by_id = {
        str(item.get("prop_id", "")).strip(): dict(item)
        for item in previous_handoff.get("active_prop_registry", []) or []
        if isinstance(item, dict) and str(item.get("prop_id", "")).strip()
    }
    for episode in episodes:
        episode_num = episode.get("episode_num")
        for plan in episode.get("prop_continuity_plan", []) or []:
            if not isinstance(plan, dict):
                continue
            prop_id = str(plan.get("prop_id", "")).strip()
            if not prop_id:
                continue
            prop_registry_by_id[prop_id] = {
                "prop_id": prop_id,
                "prop_name": plan.get("prop_name", ""),
                "holder": plan.get("end_holder", ""),
                "location": plan.get("end_location", ""),
                "lifecycle_status": infer_prop_lifecycle_status(
                    plan.get("end_holder", ""),
                    plan.get("end_location", ""),
                ),
                "last_updated_episode_num": episode_num,
            }
    state_delta = block_output.get("state_delta", {}) if isinstance(block_output.get("state_delta"), dict) else {}
    current_fact_status = dict(previous_handoff.get("current_fact_status", {}))
    for episode in episodes:
        for transition in episode.get("fact_transitions", []) or []:
            if isinstance(transition, dict) and str(transition.get("fact_id", "")).strip():
                current_fact_status[str(transition["fact_id"])] = transition.get("to_status", "")
    return {
        "previous_block_id": state_delta.get("block_id") or block_output.get("block_plan", {}).get("block_id"),
        "last_two_episode_summaries": last_two_summaries,
        "unresolved_threads": state_delta.get("unresolved_threads", []),
        "running_character_state": state_delta.get("running_character_state", {}),
        "next_block_handoff": state_delta.get("next_block_handoff", ""),
        "cumulative_consumed_child_beat_ids": cumulative_consumed_ids,
        "active_prop_registry": list(prop_registry_by_id.values()),
        "last_story_time": episodes[-1].get("story_time", {}) if episodes else {},
        "current_fact_status": current_fact_status,
    }


def _allocation_plan_from_block(block: dict[str, Any]) -> dict[str, Any]:
    """Handle allocation plan from block."""
    plan = public_episode_planning_block(block)
    plan["block_id"] = int(plan["block_id"])
    plan["start_episode"] = int(plan["start_episode"])
    plan["end_episode"] = int(plan["end_episode"])
    plan["episode_count"] = int(plan.get("episode_count", plan["end_episode"] - plan["start_episode"] + 1))
    return plan


def merge_episode_planning_blocks(
    block_outputs: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    *,
    allocation_blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Handle merge episode planning blocks."""
    block_plans: list[dict[str, Any]] = []
    episode_outlines: list[dict[str, Any]] = []
    if allocation_blocks is None:
        for block_output, block in zip(block_outputs, blocks):
            block_plan = _block_plan_from_output(block_output, block)
            block_plans.append(block_plan)
            episode_outlines.extend(block_output.get("episode_outlines", []))
    else:
        block_plans = [_allocation_plan_from_block(block) for block in allocation_blocks]
        for block_output in block_outputs:
            episode_outlines.extend(block_output.get("episode_outlines", []))
    episode_outlines.sort(key=lambda item: int(item.get("episode_num", 0)))
    return {
        "episode_allocation": [
            {
                "block_id": int(item["block_id"]),
                "start_episode": int(item["start_episode"]),
                "end_episode": int(item["end_episode"]),
                "episode_count": int(item["episode_count"]),
            }
            for item in block_plans
        ],
        "block_plans": block_plans,
        "episode_outlines": episode_outlines,
    }


def collect_artifact_output_hashes(paths: RunPaths, artifact_ids: list[str]) -> dict[str, str]:
    """Handle collect artifact output hashes."""
    return {
        artifact_id: clean_json_artifact_sha256(paths.outputs / f"{artifact_id}.clean.json")
        for artifact_id in artifact_ids
    }


def episode_planning_merge_values(
    episode_planning_values: dict[str, Any],
    block_output_hashes: dict[str, str],
) -> dict[str, Any]:
    """Handle episode planning merge values."""
    return {
        **episode_planning_values,
        "episode_planning_fanout": {
            "mode": "internal_fanout_merge",
            "block_output_hashes": block_output_hashes,
        },
    }


def render_episode_planning_merge_prompt(values: dict[str, Any]) -> str:
    """Handle render episode planning merge prompt."""
    fanout = values.get("episode_planning_fanout", {})
    return (
        "07 剧集规划本地分批合并索引（不调用模型）\n"
        + prompt_renderer.stringify_for_prompt("episode_planning_fanout", fanout)
    )


def call_episode_planning_block(
    paths: RunPaths,
    stage: dict[str, Any],
    block_values: dict[str, Any],
    *,
    dry_run: bool,
    llm_script_path: Path | None,
    timeout: int,
) -> dict[str, Any]:
    """Handle call episode planning block."""
    block = block_values["episode_planning_scope"]["current_block"]
    artifact_id = episode_planning_block_artifact_id(block)
    prompt = render_episode_planning_block_prompt(block_values)
    data = call_stage_with_structural_retries(
        paths,
        stage,
        block_values,
        dry_run=dry_run,
        llm_script_path=llm_script_path,
        timeout=timeout,
        artifact_id=artifact_id,
        prompt=prompt,
        contract_projection_profile="07_episode_chunk",
        retry_directory="07_retry_failures",
        max_retries=2,
    )
    normalized = normalize_episode_planning_block_output(data, block_values)
    if normalized != data:
        append_normalization_operation(
            paths,
            artifact_id=artifact_id,
            stage_id=stage["stage_id"],
            operation="derive_local_block_plan_and_state_delta",
            before=data,
            after=normalized,
        )
        write_json(paths.outputs / f"{artifact_id}.clean.json", normalized)
        write_manifest(
            paths.manifests / f"{artifact_id}.manifest.json",
            stage=stage,
            artifact_id=artifact_id,
            values=block_values,
            prompt=prompt,
            output_hash=sha256_text(json.dumps(normalized, ensure_ascii=False, sort_keys=True)),
            dry_run=dry_run,
            llm_script=str(llm_script_path or ""),
            llm_runtime_options=llm_client.llm_runtime_options(llm_script_path, stage_id=stage["stage_id"]),
        )
    return normalized


def run_episode_planning_stage(
    paths: RunPaths,
    stage: dict[str, Any],
    episode_planning_values: dict[str, Any],
    *,
    dry_run: bool,
    llm_script_path: Path | None,
    timeout: int,
    force_reuse: bool = False,
) -> dict[str, Any]:
    """Handle run episode planning stage."""
    global_target_episodes = int(episode_planning_values.get("target_episodes", DEFAULT_TARGET_EPISODES))
    planning_target_episodes = int(episode_planning_values.get("planning_target_episodes") or global_target_episodes)
    allocation_blocks = episode_planning_values.get("longform_blocks") or build_longform_blocks(global_target_episodes)
    if planning_target_episodes < global_target_episodes:
        allocation_blocks = clip_blocks_for_episode_limit(allocation_blocks, planning_target_episodes)
    call_blocks = split_blocks_for_episode_chunks(
        allocation_blocks,
        max_episodes_per_chunk=EPISODE_PLANNING_MAX_EPISODES_PER_CALL,
    )
    block_artifact_ids = [episode_planning_block_artifact_id(block) for block in call_blocks]
    final_clean_path = paths.outputs / "07_episode_planning.clean.json"
    final_manifest_path = paths.manifests / "07_episode_planning.manifest.json"
    block_hashes = collect_artifact_output_hashes(paths, block_artifact_ids)
    merge_values = episode_planning_merge_values(episode_planning_values, block_hashes)
    merge_prompt = render_episode_planning_merge_prompt(merge_values)
    write_text(paths.prompts / "07_episode_planning.prompt.md", merge_prompt)

    if force_reuse:
        if not final_clean_path.exists():
            raise FileNotFoundError(f"Cannot reuse missing artifact: {final_clean_path}")
        return normalize_stage_output(stage["stage_id"], json.loads(read_text(final_clean_path)))

    if final_clean_path.exists() and final_manifest_path.exists():
        try:
            manifest = json.loads(read_text(final_manifest_path))
        except json.JSONDecodeError:
            manifest = {}
        if cached_artifact_matches(
            manifest,
            dry_run=dry_run,
            prompt=merge_prompt,
            values=merge_values,
            llm_script_path=llm_script_path,
            stage=stage,
            output_path=final_clean_path,
        ):
            return normalize_stage_output(stage["stage_id"], json.loads(read_text(final_clean_path)))
        invalidate_artifact_cache(paths, "07_episode_planning")
    elif final_clean_path.exists() or final_manifest_path.exists():
        invalidate_artifact_cache(paths, "07_episode_planning")

    block_outputs: list[dict[str, Any]] = []
    fanout_trace: list[dict[str, Any]] = []
    previous_handoff: dict[str, Any] = {}
    for index, block in enumerate(call_blocks):
        next_block = call_blocks[index + 1] if index + 1 < len(call_blocks) else None
        block_values = build_episode_planning_block_values(
            episode_planning_values,
            block=block,
            previous_handoff=previous_handoff,
            next_block=next_block,
        )
        block_output = call_episode_planning_block(
            paths,
            stage,
            block_values,
            dry_run=dry_run,
            llm_script_path=llm_script_path,
            timeout=timeout,
        )
        block_outputs.append(block_output)
        previous_handoff = build_episode_planning_handoff(
            block_output,
            previous_handoff=previous_handoff,
        )
        block_output_sha256 = sha256_text(
            json.dumps(block_output, ensure_ascii=False, sort_keys=True)
        )
        fanout_trace.append(
            {
                "artifact_id": episode_planning_block_artifact_id(block),
                "output_sha256": block_output_sha256,
                "block_id": block.get("block_id"),
                "source_block_id": block.get("_source_block_id", block.get("block_id")),
                "chunk_index": block.get("_chunk_index"),
                "chunk_count": block.get("_chunk_count"),
                "episode_range": {"start": block.get("start_episode"), "end": block.get("end_episode")},
                "episode_count": len(block_output.get("episode_outlines", [])),
                "state_delta": block_output.get("state_delta", {}),
            }
        )

    merged = merge_episode_planning_blocks(block_outputs, call_blocks, allocation_blocks=allocation_blocks)
    merged_with_traces = merged
    merged, discarded_traces = stage_contracts.project_contract_data(stage["stage_id"], merged_with_traces)
    discarded_trace_paths = [
        item["path"].removeprefix(f"{stage['stage_id']}.")
        for item in discarded_traces
    ]
    write_normalization_report(
        paths,
        artifact_id="07_episode_planning",
        stage_id=stage["stage_id"],
        report={
            "status": "CHANGED" if discarded_traces else "UNCHANGED",
            "before_sha256": sha256_text(json.dumps(merged_with_traces, ensure_ascii=False, sort_keys=True)),
            "after_sha256": sha256_text(json.dumps(merged, ensure_ascii=False, sort_keys=True)),
            "after_projection_sha256": sha256_text(json.dumps(merged, ensure_ascii=False, sort_keys=True)),
            "operation_count": 1 if discarded_traces else 0,
            "changed_paths": discarded_trace_paths,
            "operations": [
                {
                    "operation": "project_local_episode_planning_repairs",
                    "changed_paths": discarded_trace_paths,
                }
            ]
            if discarded_traces
            else [],
            "discarded_trace_paths": discarded_trace_paths,
            "discarded_trace_fields": discarded_traces,
        },
    )
    write_json(paths.outputs / "07_episode_planning.merge.json", merged)
    write_json(paths.parsed / "07_episode_planning_fanout_trace.json", fanout_trace)
    write_json(final_clean_path, merged)
    block_hashes = collect_artifact_output_hashes(paths, block_artifact_ids)
    merge_values = episode_planning_merge_values(episode_planning_values, block_hashes)
    merge_prompt = render_episode_planning_merge_prompt(merge_values)
    write_text(paths.prompts / "07_episode_planning.prompt.md", merge_prompt)
    write_manifest(
        final_manifest_path,
        stage=stage,
        artifact_id="07_episode_planning",
        values=merge_values,
        prompt=merge_prompt,
        output_hash=sha256_text(json.dumps(merged, ensure_ascii=False, sort_keys=True)),
        dry_run=dry_run,
        llm_script=str(llm_script_path or ""),
        llm_runtime_options=llm_client.llm_runtime_options(llm_script_path, stage_id=stage["stage_id"]),
    )
    return merged


def build_episode_outlines(
    target: int,
    *,
    event_pool: list[dict[str, Any]] | None = None,
    foreshadowing_pool: list[dict[str, Any]] | None = None,
    canonical_story_lock: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Handle build episode outlines."""
    blocks = build_longform_blocks(target)
    event_items = event_pool or [_build_dry_run_event(idx, blocks[(idx - 1) % len(blocks)]) for idx in range(1, 25)]
    event_ids = [int(item["id"]) for item in event_items if str(item.get("id", "")).isdigit()]
    foreshadowing_ids = [
        int(item["id"])
        for item in (foreshadowing_pool or [{"id": idx} for idx in range(1, 9)])
        if str(item.get("id", "")).isdigit()
    ]
    character_names = (canonical_story_lock or {}).get("character_names") or ["主角", "核心反派", "关键同盟"]
    protagonist = (canonical_story_lock or {}).get("protagonist") or character_names[0]
    episodes = []
    for idx in range(1, target + 1):
        block = next(item for item in blocks if item["start_episode"] <= idx <= item["end_episode"])
        local_index = idx - block["start_episode"] + 1
        matching_events = []
        for event in event_items:
            if not str(event.get("id", "")).isdigit():
                continue
            if int(event.get("target_block", block["block_id"])) != int(block["block_id"]):
                continue
            try:
                window_start, window_end = validators._event_window(event)
            except ValueError:
                window_start, window_end = block["start_episode"], block["end_episode"]
            if window_start <= idx <= window_end:
                matching_events.append(event)
        selected_event = matching_events[0] if matching_events else next(
            (
                event
                for event in event_items
                if int(event.get("target_block", block["block_id"])) == int(block["block_id"])
            ),
            {
                "id": event_ids[(idx - 1) % len(event_ids)],
                "conflict_mode": "relationship_pressure",
                "pattern_family": "relationship_pressure",
                "source_anchor": "源故事核心机制",
            },
        )
        selected_event_id = int(selected_event.get("id", event_ids[(idx - 1) % len(event_ids)]))
        selected_child_beats = [item for item in selected_event.get("child_beats", []) or [] if isinstance(item, dict)]
        selected_child_beat_ids = [
            str(item.get("child_beat_id"))
            for item in selected_child_beats[:1]
            if item.get("child_beat_id")
        ]
        selected_child_beat_actions = [
            str(item.get("action"))
            for item in selected_child_beats[:1]
            if item.get("action")
        ]
        conflict_modes = ["rumor", "relationship_pressure", "rule_counterattack", "public_reversal"]
        pattern_families = ["rumor_counterattack", "relationship_pressure", "evidence_turn", "rule_intervention"]
        conflict_mode = conflict_modes[(idx - 1) % len(conflict_modes)]
        pattern_family = pattern_families[(idx - 1) % len(pattern_families)]
        required_names = [protagonist]
        if len(character_names) > 1:
            required_names.append(character_names[idx % len(character_names)])
        required_names = sorted(set(required_names))
        scene_plan = build_default_scene_plan(ep_num=idx, cast_names=required_names)
        episodes.append(
            {
                "episode_num": idx,
                "title": f"第{idx}集：第{idx}次破局",
                "block_id": block["block_id"],
                "phase": block["phase"],
                "episode_reason": f"推进{block['title']}中的第{local_index}个压力/反击节拍",
                "main_conflict": "主角面对舆论或关系压力，拒绝按压迫者规则自证。",
                "counterattack": "主角借证据、公开场合或规则程序完成一次小反击。",
                "information_gain": "观众获得一个关于利益链、人物秘密或伏笔状态的新信息。",
                "state_change": {
                    "protagonist": "更主动，掌握更多证据",
                    "key_relation": "从犹豫向转向推进",
                    "antagonists": "压迫升级但付出代价",
                },
                "opening_beat": "从上一集结尾或本集第一压力点后一拍进入，不重复已完成铺垫。",
                "closing_beat": "本集反击完成后留下下一集必须承接的动作或问题。",
                "next_episode_start_state": "下一集从本集结尾动作之后继续。",
                "consumed_child_beats": selected_child_beat_actions,
                "consumed_child_beat_ids": selected_child_beat_ids,
                "event_ids": [selected_event_id],
                "foreshadowing_ids": [foreshadowing_ids[(idx - 1) % len(foreshadowing_ids)]],
                "required_character_names": required_names,
                "ending_hook": "下一轮更强压迫逼近。",
                "adapted_plot_point_ids": [min(5, max(1, idx % 5 + 1))],
                "source_fact_ids": list(selected_event.get("source_fact_ids", [])),
                "story_time": {
                    "day_index": max(1, (idx - 1) // 3 + 1),
                    "time_label": ["日", "傍晚", "夜"][(idx - 1) % 3],
                    "elapsed_from_previous": "紧接上集" if idx > 1 else "故事起点",
                },
                "fact_transitions": [],
                "dramatic_target_id": dramatic_release.release_id_for_episode(idx),
                "conflict_mode": conflict_mode,
                "pattern_family": pattern_family,
                "payoff_level": (
                    "final_climax" if idx >= target - 2 else (
                        "block_payoff" if idx == block["end_episode"] else "setup_or_turn"
                    )
                ),
                "event_role": (
                    "setup" if local_index == 1 else (
                        "payoff" if idx == block["end_episode"] else "escalation"
                    )
                ),
                "event_consumption_status": "ongoing" if idx < block["end_episode"] else "block_payoff",
                "source_anchor": selected_event.get("source_anchor", "源故事核心机制"),
                "expansion_delta": selected_event.get("delta_from_source", "放大压力不改人物功能"),
                "boundary_check": {
                    "risk_level": "low",
                    "protagonist_action": "留证或公开反问",
                    "why_allowed": "按分集卡执行并记录风险",
                    "mitigation": "风险记录，不自动改写",
                },
                "content_sensitivity_check": {
                    "risk_level": "low",
                    "risk_reason": "按剧情记录内容强度",
                    "mitigation": "进入warning统计",
                },
                "appearing_character_names": required_names,
                "unresolved_threads_after_episode": ["下一轮压力仍未解决"] if idx < target else [],
                "is_epilogue": idx > target - 2,
                "scene_plan": scene_plan,
                "narration_device_plan": build_default_narration_device_plan(),
                "target_script_density": build_default_target_script_density(
                    ep_num=idx,
                    scene_plan=scene_plan,
                ),
                "prop_continuity_plan": [],
            }
        )
    return episodes


def build_default_narration_device_plan() -> dict[str, Any]:
    """Handle build default narration device plan."""
    return {
        "planned_os_count": 0,
        "planned_flashback_count": 0,
        "planned_flashback_quota_count": 0,
        "planned_vo_count": 0,
        "reason": "优先用当场动作、道具和对话交代信息。",
        "visual_replacement_strategy": "用手机屏幕、合同文件、对手追问和人物反应替代OS/闪回。",
        "approved_flashback_time_deviation_ids": [],
        "approved_os_time_deviation_ids": [],
        "visualized_time_deviation_ids": [],
        "deleted_or_rewritten_time_deviation_ids": [],
        "approved_time_deviation_ids": [],
    }


def build_default_target_script_density(
    *,
    ep_num: int,
    scene_plan: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Handle build default target script density."""
    scene_numbers = [
        int(item.get("scene_no", index + 1))
        for index, item in enumerate(scene_plan or [])
        if isinstance(item, dict)
    ] or [1]
    atomic_beats = [
        {"beat_id": "B1"},
        {"beat_id": "B2"},
    ]
    total_target_chars = 700
    base_chars, remainder = divmod(total_target_chars, len(scene_numbers))
    scene_char_budgets = []
    for index, scene_no in enumerate(scene_numbers):
        scene_char_budgets.append(
            {
                "scene_no": scene_no,
                "target_chars": base_chars + (1 if index < remainder else 0),
                "must_cover_beat_ids": [
                    beat["beat_id"]
                    for beat_index, beat in enumerate(atomic_beats)
                    if beat_index % len(scene_numbers) == index
                ],
            }
        )
    return {
        "target_range_chars": "650-780",
        "minimum_effective_chars": 650,
        "maximum_chars": 780,
        "must_cover_beats": atomic_beats,
        "optional_compression_beats": ["重复争执", "可由屏幕信息替代的解释"],
        "expansion_strategy": "低于下限时补可拍动作、对手追问、道具证据和人物反应，不补文学描述。",
        "scene_char_budgets": scene_char_budgets,
    }


def build_stage04b_target_specs(
    target_episodes: int,
    *,
    chunk_size: int = DRAMATIC_RELEASE_MAX_EPISODES_PER_CALL,
) -> list[dict[str, int]]:
    """Handle build stage04b target specs."""
    if target_episodes < 1:
        raise ValueError("target_episodes must be positive")
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    specs: list[dict[str, int]] = []
    regular_end = target_episodes - 1 if target_episodes > 1 else 0
    for chunk_index, start_episode in enumerate(range(1, regular_end + 1, chunk_size), start=1):
        end_episode = min(regular_end, start_episode + chunk_size - 1)
        specs.append(
            {
                "chunk_index": chunk_index,
                "start_episode": start_episode,
                "end_episode": end_episode,
                "episode_count": end_episode - start_episode + 1,
            }
        )
    specs.append(
        {
            "chunk_index": len(specs) + 1,
            "start_episode": target_episodes,
            "end_episode": target_episodes,
            "episode_count": 1,
        }
    )
    return specs


def stage04b_target_artifact_id(spec: dict[str, Any]) -> str:
    """Handle stage04b target artifact id."""
    return (
        "04b_dramatic_release_map."
        f"ep{int(spec['start_episode']):03d}_{int(spec['end_episode']):03d}"
    )


def render_stage04b_foundation_prompt(values: dict[str, Any]) -> str:
    """Handle render stage04b foundation prompt."""
    target_episodes = int(values.get("target_episodes", DEFAULT_TARGET_EPISODES))
    capacity_start = min(target_episodes, 31)
    foundation_skeleton = llm_schema_localization.localize_prompt_value(
        "",
        {
        "release_overview": {
            "target_episodes": target_episodes,
            "natural_capacity_max": min(target_episodes, 30),
            "capacity_gap": max(0, target_episodes - 30),
            "opening_strategy": "",
            "process_compression_strategy": "",
            "expansion_strategy": "",
        },
        "capacity_bridge_units": (
            [
                {
                    "bridge_id": "BRIDGE_01",
                    "episode_range": {"start": capacity_start, "end": target_episodes},
                    "new_goal": "",
                    "new_obstacle": "",
                    "new_choice": "",
                    "new_cost": "",
                    "new_result": "",
                    "source_boundary": "",
                }
            ]
            if target_episodes > 30
            else []
        ),
        "opening_gate": {
            "first_three_live_obstacle_count": min(2, target_episodes),
            "first_five_process_only_count": 0,
            "required_early_source_fact_ids": [],
            "gate_reason": "",
        },
        },
    )
    return "\n\n".join(
        [
            "# 任务目标",
            "为全季逐集戏剧释放图建立一次性的容量和开篇策略。本次只输出全局基础信息，不输出逐集目标。",
            "## 本环节边界",
            "只判断源故事容量缺口、扩写桥接方式和开篇门禁。不得写分集大纲、事件池或剧本正文。",
            "## 输入材料",
            "### 全局运行配置\n" + prompt_renderer.stringify_for_prompt("run_config", values.get("run_config", {})),
            "### 系统派生规则\n" + prompt_renderer.stringify_for_prompt("derived_config", values.get("derived_config", {})),
            "### 改编容量评估\n" + prompt_renderer.stringify_for_prompt(
                "adaptation_capacity",
                values.get("adaptation_capacity", {}),
            ),
            "### 原著事实账本\n" + prompt_renderer.stringify_for_prompt(
                "source_fact_ledger",
                values.get("source_fact_ledger", []),
            ),
            "### 改编方向\n" + prompt_renderer.stringify_for_prompt(
                "adaptation_direction",
                values.get("adaptation_direction", {}),
            ),
            "### 源故事锁\n" + prompt_renderer.stringify_for_prompt(
                "canonical_story_lock",
                values.get("canonical_story_lock", {}),
            ),
            "### 闪回筛选结果\n" + prompt_renderer.stringify_for_prompt(
                "flashback_screening",
                values.get("flashback_screening", {}),
            ),
            "## 输出 JSON 骨架",
            json.dumps(foundation_skeleton, ensure_ascii=False, indent=2),
            "## 执行规则",
            "\n".join(
                [
                    f"- 目标集数必须原样输出 {target_episodes}。自然容量最大集数来自输入判断，容量缺口等于目标集数减去自然容量最大集数，最低为0。",
                    "- 容量没有缺口时，容量扩写桥接单元输出空数组；有缺口时，每个桥接单元必须引入新的目标、人物或制度阻力、主角选择、即时代价和可见结果，不能只拆细等待、申请、审批、路程等流程。",
                    "- 前三集至少2集有当场出镜人物形成的具体阻力；前五集不得出现纯流程集。",
                    "- 第1集若使用结构性闪回，必须同集落回当下，并完成一个当下可见微动作；不能只以口号、宣告或‘这一次我要’收尾。",
                    "- 开篇必需原著事实ID只能引用输入账本已有ID。",
                    "- 第一字符必须是 {，最后一字符必须是 }。不得输出 Markdown 代码块、解释或思考过程。",
                ]
            ),
        ]
    )


def render_stage04b_target_prompt(
    values: dict[str, Any],
    *,
    foundation: dict[str, Any],
    spec: dict[str, Any],
    previous_target: dict[str, Any] | None,
) -> str:
    """Handle render stage04b target prompt."""
    start_episode = int(spec["start_episode"])
    end_episode = int(spec["end_episode"])
    episode_count = int(spec["episode_count"])
    target_episodes = int(values.get("target_episodes", DEFAULT_TARGET_EPISODES))
    includes_finale = end_episode == target_episodes
    example_episode = start_episode
    output_skeleton = llm_schema_localization.localize_prompt_value(
        "",
        {
            "episode_dramatic_targets": [
                {
                    "release_id": dramatic_release.release_id_for_episode(example_episode),
                    "episode_num": example_episode,
                    "desire": "本集主角必须取得的具体目标",
                    "obstacle": "当场阻止目标的人物、制度或现实条件",
                    "choice": "主角主动做出的不可替代选择",
                    "immediate_cost": "选择在本集立刻造成的损失或风险",
                    "visible_result": "镜头中已经改变的人物、资源、权力、秘密或关系状态",
                    "hook": "由本集结果直接引出的新问题",
                    "confrontation_mode": "live_character",
                    "process_only": False,
                    "source_fact_ids": [],
                    "required_event_function": "05事件必须实现的独立状态变化",
                    "expansion_engine_id": "",
                }
            ]
        },
    )
    return "\n\n".join(
        [
            "# 任务目标",
            f"生成全季戏剧释放图的第 {start_episode}-{end_episode} 集目标。本次只输出这一段逐集目标。",
            "## 本环节边界",
            "每集只定义一个不可变的戏剧因果目标，不写场景细节、对白、事件事务或剧本正文。",
            "## 输入材料",
            "### 全季基础策略\n" + prompt_renderer.stringify_for_prompt("dramatic_release_map", foundation),
            "### 上一分片最后一集目标\n" + prompt_renderer.stringify_for_prompt(
                "episode_dramatic_targets",
                [previous_target] if previous_target else [],
            ),
            "### 原著事实账本\n" + prompt_renderer.stringify_for_prompt(
                "source_fact_ledger",
                values.get("source_fact_ledger", []),
            ),
            "### 改编方向\n" + prompt_renderer.stringify_for_prompt(
                "adaptation_direction",
                values.get("adaptation_direction", {}),
            ),
            "### 源故事锁\n" + prompt_renderer.stringify_for_prompt(
                "canonical_story_lock",
                values.get("canonical_story_lock", {}),
            ),
            "### 闪回筛选结果\n" + prompt_renderer.stringify_for_prompt(
                "flashback_screening",
                values.get("flashback_screening", {}),
            ),
            "## 输出 JSON 骨架",
            json.dumps(output_skeleton, ensure_ascii=False, indent=2),
            "## 执行规则",
            "\n".join(
                [
                    f"- 必须输出正好 {episode_count} 项，集号严格连续为 {start_episode}-{end_episode}，释放目标ID严格依次为 "
                    + "、".join(
                        dramatic_release.release_id_for_episode(episode_num)
                        for episode_num in range(start_episode, end_episode + 1)
                    )
                    + "。",
                    "- 每集必须完整写出欲望、阻力、选择、即时代价、可见结果和钩子。六项必须形成因果链：因为主角要什么、谁或什么当场阻止、主角因此做何选择、选择立刻付出什么、画面中改变什么、改变又引出什么新问题。",
                    (
                        "- 对抗模式只用 live_character、environment、institution 或 process；只有没有出镜人物对抗、没有主动选择且主要内容是等待外部流程时"
                        "，是否纯流程才写 true。"
                    ),
                    "- 同一流程的考试、出分、申请、审批、通知和执行不能为了凑集数拆成连续纯流程集；无新选择、代价和可见结果的节点并入相邻集。",
                    "- 相邻集的可见结果和钩子不得同义复写；本分片第一项还必须避开上一分片最后一项。",
                    (
                        (
                            f"- 第 {target_episodes} 集是终集，仍必须完整输出全部字段。终集钩子不是下一集悬念，必须写成已经可见的终局余韵、新生活确认或主题落点；不得省略钩子，也不得开启"
                            f"未解决的新主线。"
                        )
                        if includes_finale
                        else "- 非终集钩子必须由本集可见结果直接引出下一集的新阻力、选择或待解决问题。"
                    ),
                    "- 前三集至少2集的对抗模式是 live_character；前五集不得出现纯流程集。",
                    "- 第1集如执行前世或重生闪回，必须同集回到当下，且让主角完成一个可拍的当下行动和可见结果，不得只作重生宣告。",
                    "- 前5集不得让同一个源事件连续占满超过3集；到第3集必须完成首个逃离、止损或考前部署，第4-5集进入新后果、新对手行动或新权力变化，不得只等待、考试或拒接电话。",
                    "- ‘今天、明天、考试当天、考前一天’等相对时间必须在相邻集内自洽，不得同集互相矛盾。",
                    "- 原著事实ID只能引用输入账本已有ID；原创扩写可写空数组，但必须填写扩写发动机ID并受全季桥接单元约束。非扩写目标的扩写发动机ID写空字符串。",
                    (
                        "- 只要引用原著事实ID，必须保留该事实的行动者、动作对象和结果；不得把监狱会面、对特定人物的拒绝或终局事实替换成写信、打电话或对其他人表态。源故事锁中的终局事实和人物行动边界"
                        "必须在最后两集按原对象落地。"
                    ),
                    "- 所需事件功能必须说明下游05事件要改变的目标、资源、权力、秘密或关系状态，不能写‘承接上集’或‘推进剧情’。",
                    "- 第一字符必须是 {，最后一字符必须是 }。不得输出 Markdown 代码块、解释或思考过程。",
                ]
            ),
        ]
    )


def call_stage_with_structural_retries(
    paths: RunPaths,
    stage: dict[str, Any],
    values: dict[str, Any],
    *,
    dry_run: bool,
    llm_script_path: Path | None,
    timeout: int,
    artifact_id: str,
    prompt: str,
    contract_projection_profile: str,
    retry_directory: str,
    max_retries: int,
) -> dict[str, Any]:
    """Handle call stage with structural retries."""
    current_prompt = prompt
    for retry_index in range(max_retries + 1):
        try:
            return call_stage(
                paths,
                stage,
                values,
                dry_run=dry_run,
                llm_script_path=llm_script_path,
                timeout=timeout,
                artifact_id=artifact_id,
                prompt_override=current_prompt,
                contract_projection_profile=contract_projection_profile,
            )
        except ValueError as exc:
            contract_report_path = (
                paths.parsed
                / "contract_reports"
                / f"{artifact_id}.contract_report.json"
            )
            parser_report_path = (
                paths.parsed
                / "parser_reports"
                / f"{artifact_id}.json"
            )
            contract_report: dict[str, Any] = {}
            parser_report: dict[str, Any] = {}
            if contract_report_path.exists():
                try:
                    contract_report = json.loads(read_text(contract_report_path))
                except (OSError, json.JSONDecodeError):
                    contract_report = {}
            if parser_report_path.exists():
                try:
                    parser_report = json.loads(read_text(parser_report_path))
                except (OSError, json.JSONDecodeError):
                    parser_report = {}
            if contract_report.get("status") == "FAIL":
                failure_kind = "contract"
                failure_details = list(contract_report.get("errors", []))
            elif parser_report.get("status") == "FAIL":
                failure_kind = "parser"
                failure_details = [str(parser_report.get("parse_error", exc))]
            else:
                raise
            failure_record = {
                "artifact_id": artifact_id,
                "stage_id": stage["stage_id"],
                "retry_index": retry_index,
                "failure_kind": failure_kind,
                "contract_profile": contract_projection_profile,
                "error": str(exc),
                "failure_details": failure_details,
                "raw_output_path": f"outputs/{artifact_id}.raw.md",
                "attempt_log_path": f"logs/{artifact_id}.log.json",
            }
            write_json(
                paths.parsed
                / retry_directory
                / f"{artifact_id}.attempt_{retry_index + 1:02d}.json",
                failure_record,
            )
            if retry_index >= max_retries:
                raise
            invalidate_artifact_cache(paths, artifact_id)
            missing_fields = "\n".join(
                f"- {item}" for item in failure_details
            )
            current_prompt = "\n\n".join(
                [
                    prompt,
                    "## 上次响应结构修复",
                    (
                        "上次响应未形成可用的完整 JSON。本次必须重新输出完整 JSON，并逐项对照输出骨架；不适用的字符串字段也必须写空字符串，数组写空数组，不能省略键。字符串内部使用「」或『』，"
                        "不要使用未转义的英文双引号。输出前检查根对象以 { 开始并以 } 结束，数组与对象括号严格成对。"
                    ),
                    missing_fields,
                ]
            )
    raise AssertionError("unreachable")


def call_stage04b_with_contract_retries(
    paths: RunPaths,
    stage: dict[str, Any],
    values: dict[str, Any],
    *,
    dry_run: bool,
    llm_script_path: Path | None,
    timeout: int,
    artifact_id: str,
    prompt: str,
    contract_projection_profile: str,
) -> dict[str, Any]:
    """Handle call stage04b with contract retries."""
    return call_stage_with_structural_retries(
        paths,
        stage,
        values,
        dry_run=dry_run,
        llm_script_path=llm_script_path,
        timeout=timeout,
        artifact_id=artifact_id,
        prompt=prompt,
        contract_projection_profile=contract_projection_profile,
        retry_directory="04b_retry_failures",
        max_retries=DRAMATIC_RELEASE_CONTRACT_RETRIES,
    )


def run_dramatic_release_stage(
    paths: RunPaths,
    stage: dict[str, Any],
    values: dict[str, Any],
    *,
    dry_run: bool,
    llm_script_path: Path | None,
    timeout: int,
    force_reuse: bool = False,
) -> dict[str, Any]:
    """Handle run dramatic release stage."""
    final_clean_path = paths.outputs / "04b_dramatic_release_map.clean.json"
    final_manifest_path = paths.manifests / "04b_dramatic_release_map.manifest.json"
    if force_reuse:
        if not final_clean_path.exists():
            raise FileNotFoundError(f"Cannot reuse missing artifact: {final_clean_path}")
        projected, _unmapped = stage_contracts.project_contract_data(
            stage["stage_id"],
            json.loads(read_text(final_clean_path)),
        )
        return normalize_stage_output(stage["stage_id"], projected)

    foundation_artifact_id = "04b_dramatic_release_map.foundation"
    foundation = call_stage04b_with_contract_retries(
        paths,
        stage,
        {**values, "_stage04b_foundation": True},
        dry_run=dry_run,
        llm_script_path=llm_script_path,
        timeout=timeout,
        artifact_id=foundation_artifact_id,
        prompt=render_stage04b_foundation_prompt(values),
        contract_projection_profile="04b_foundation",
    )
    target_episodes = int(values.get("target_episodes", DEFAULT_TARGET_EPISODES))
    targets: list[dict[str, Any]] = []
    fanout_trace: list[dict[str, Any]] = []
    child_hashes: dict[str, str] = {
        foundation_artifact_id: sha256_text(json.dumps(foundation, ensure_ascii=False, sort_keys=True))
    }
    previous_target: dict[str, Any] | None = None
    for spec in build_stage04b_target_specs(target_episodes):
        artifact_id = stage04b_target_artifact_id(spec)
        chunk = call_stage04b_with_contract_retries(
            paths,
            stage,
            {**values, "_stage04b_target_spec": spec},
            dry_run=dry_run,
            llm_script_path=llm_script_path,
            timeout=timeout,
            artifact_id=artifact_id,
            prompt=render_stage04b_target_prompt(
                values,
                foundation=foundation,
                spec=spec,
                previous_target=previous_target,
            ),
            contract_projection_profile="04b_target_chunk",
        )
        dramatic_release.validate_release_slice(
            chunk,
            start_episode=int(spec["start_episode"]),
            end_episode=int(spec["end_episode"]),
        )
        chunk_targets = [dict(item) for item in chunk["episode_dramatic_targets"]]
        targets.extend(chunk_targets)
        previous_target = chunk_targets[-1]
        child_hashes[artifact_id] = sha256_text(
            json.dumps(chunk, ensure_ascii=False, sort_keys=True)
        )
        fanout_trace.append(
            {
                "artifact_id": artifact_id,
                **spec,
                "actual_episode_count": len(chunk_targets),
                "output_sha256": child_hashes[artifact_id],
            }
        )

    merged = {**foundation, "episode_dramatic_targets": targets}
    dramatic_release.validate_release_structure(merged, target_episodes=target_episodes)
    merged, _discarded = stage_contracts.project_contract_data(stage["stage_id"], merged)
    merge_values = {**values, "stage04b_fanout": {"child_output_hashes": child_hashes}}
    merge_prompt = "04b 全季戏剧释放图本地分批合并索引（不调用模型）\n" + "\n".join(
        f"- {artifact_id}: {output_hash}"
        for artifact_id, output_hash in sorted(child_hashes.items())
    )
    append_normalization_operation(
        paths,
        artifact_id="04b_dramatic_release_map",
        stage_id=stage["stage_id"],
        operation="merge_stage04b_foundation_and_target_chunks",
        before=foundation,
        after=merged,
    )
    write_text(paths.prompts / "04b_dramatic_release_map.prompt.md", merge_prompt)
    write_json(paths.parsed / "04b_dramatic_release_fanout_trace.json", fanout_trace)
    write_json(final_clean_path, merged)
    write_manifest(
        final_manifest_path,
        stage=stage,
        artifact_id="04b_dramatic_release_map",
        values=merge_values,
        prompt=merge_prompt,
        output_hash=sha256_text(json.dumps(merged, ensure_ascii=False, sort_keys=True)),
        dry_run=dry_run,
        llm_script=str(llm_script_path or ""),
        llm_runtime_options=llm_client.llm_runtime_options(
            llm_script_path,
            stage_id=stage["stage_id"],
        ),
    )
    return merged


def build_stage05_event_specs(
    macro_arcs: list[dict[str, Any]],
    *,
    event_pool_size: str,
    max_event_span: int = 3,
) -> list[dict[str, Any]]:
    """Handle build stage05 event specs."""
    if not macro_arcs:
        return []
    target_count, _maximum = validators.parse_numeric_range(str(event_pool_size))
    required_counts: list[int] = []
    for arc in macro_arcs:
        episode_range = arc.get("episode_range", "")
        if isinstance(episode_range, dict):
            start_episode = int(episode_range.get("start", 0) or 0)
            end_episode = int(episode_range.get("end", 0) or 0)
        else:
            start_episode, end_episode = validators.parse_numeric_range(str(episode_range))
        episode_count = max(1, end_episode - start_episode + 1)
        required_counts.append(max(1, (episode_count + max_event_span - 1) // max_event_span))
    desired_count = max(target_count, sum(required_counts))
    event_counts = list(required_counts)
    extra = desired_count - sum(event_counts)
    for index in range(extra):
        event_counts[index % len(event_counts)] += 1
    specs: list[dict[str, Any]] = []
    next_event_id = 1
    for index, (arc, event_count) in enumerate(zip(macro_arcs, event_counts)):
        specs.append(
            {
                "arc_index": index + 1,
                "arc_id": int(arc.get("arc_id", index + 1)),
                "episode_range": arc.get("episode_range", ""),
                "event_count": event_count,
                "start_event_id": next_event_id,
                "end_event_id": next_event_id + event_count - 1,
            }
        )
        next_event_id += event_count
    return specs


def stage05_event_artifact_id(spec: dict[str, Any]) -> str:
    """Handle stage05 event artifact id."""
    return f"05_plot_character_adaptation.arc_{int(spec['arc_id']):02d}.events"


def render_stage05_foundation_prompt(values: dict[str, Any]) -> str:
    """Handle render stage05 foundation prompt."""
    prop_registry_skeleton = llm_schema_localization.localize_prompt_value(
        "",
        {
            "prop_registry": [
                {
                    "prop_id": "PROP_001",
                    "prop_name": "",
                    "entity_kind": "item",
                    "created_episode": 1,
                    "activation_episode": 1,
                    "initial_state": {
                        "holder": "",
                        "location": "",
                        "status": "",
                    },
                    "created_from_event_id": "",
                    "replaces_prop_id": "",
                    "parent_container_id": "",
                    "terminal_states": [],
                }
            ]
        },
    )
    return "\n\n".join(
        [
            "# 任务目标",
            "完成 05 情节人物改编的基础资产。本次不生成事件池，只生成宏观弧线、冲突引擎、扩展人物网络、伏笔池和关键道具实体表。",
            "## 输入材料",
            "### 全局运行配置\n" + prompt_renderer.stringify_for_prompt("run_config", values.get("run_config", {})),
            "### 系统派生规则\n" + prompt_renderer.stringify_for_prompt("derived_config", values.get("derived_config", {})),
            "### 源故事锁\n" + prompt_renderer.stringify_for_prompt(
                "canonical_story_lock",
                values.get("canonical_story_lock", {}),
            ),
            "### 源情节点\n" + prompt_renderer.stringify_for_prompt(
                "source_plot_points",
                values.get("source_plot_points", []),
            ),
            "### 人物小传\n" + prompt_renderer.stringify_for_prompt("character_bible", values.get("character_bible", [])),
            "### 改编方向\n" + prompt_renderer.stringify_for_prompt(
                "adaptation_direction",
                values.get("adaptation_direction", {}),
            ),
            "### 原著事实账本\n" + prompt_renderer.stringify_for_prompt(
                "source_fact_ledger",
                values.get("source_fact_ledger", []),
            ),
            "### 改编容量评估\n" + prompt_renderer.stringify_for_prompt(
                "adaptation_capacity",
                values.get("adaptation_capacity", {}),
            ),
            "### 闪回筛选结果\n" + prompt_renderer.stringify_for_prompt(
                "flashback_screening",
                values.get("flashback_screening", {}),
            ),
            "### 全季戏剧释放图\n" + prompt_renderer.stringify_for_prompt(
                "dramatic_release_map",
                values.get("dramatic_release_map", {}),
            ),
            "## 输出 JSON 骨架",
            (
                "{\"宏观弧线\": [{\"弧线ID\": 1, \"标题\": \"\", \"集数范围\": \"1-5\", "
                "\"戏剧目标\": \"\", \"压力来源\": \"\", \"回收\": \"\", \"原著情节点ID\": []}], "
                "\"冲突引擎\": {\"施压模板\": [{\"模板ID\": \"P1\", \"模板名称\": \"\", "
                "\"模式\": \"\", \"适用弧线ID\": [1], \"变体示例\": [\"\"]}], "
                "\"反击模板\": [{\"模板ID\": \"C1\", \"模板名称\": \"\", \"模式\": \"\", "
                "\"适用弧线ID\": [1], \"变体示例\": [\"\"]}], "
                "\"反转模板\": [{\"模板ID\": \"R1\", \"模板名称\": \"\", \"模式\": \"\", "
                "\"适用弧线ID\": [1], \"变体示例\": [\"\"]}], \"反单调规则\": []}, "
                "\"扩展人物网络\": [{\"姓名\": \"\", \"阵营\": \"\", \"功能\": \"\", "
                "\"关系压力\": \"\", \"秘密链\": \"\"}], \"伏笔池\": [{\"ID\": 1, \"设置"
                "\": \"\", \"误导\": \"\", \"回收\": \"\", \"相关弧线\": 1}]}"
            ),
            "### 关键道具实体表字段骨架\n" + json.dumps(prop_registry_skeleton, ensure_ascii=False, indent=2),
            (
                "上方根对象还必须增加 `关键道具实体表`；每项必须包含道具ID、道具名称、实体类型、创建集数、激活集数、初始状态、来源事件ID、替代道具ID、父容器ID和终止状态。初始状态必须"
                "严格包含 `当前持有人`、`地点`、`状态` 三个键，表示道具在首次授权事务执行前的真实状态；地点键必须写 `地点`，不要写 `当前地点`。"
            ),
            "## 执行规则",
            (
                "宏观弧线数量等于系统派生规则中的篇章数量，并承接全季戏剧释放图，而不是重新设计逐集节奏。冲突引擎三类模板每项只允许模板ID、模板名称、模式、适用弧线ID、变体示例五个字段。扩展"
                "人物网络最多8人，伏笔池正好6项。关键道具实体表区分实物、容器和内容物；换新实物使用新ID并只能单向引用早于它创建的旧ID，旧道具不得反向引用未来新道具，不得互相替代、自替代或"
                "形成环；容器内容物引用父容器ID。原著事实和宏观弧线中会承担结果证明、身份变化或后续反制的证件、通知书、确认函、记录、合同和录音载体必须提前登记。创建集数和激活集数使用首次进入"
                "故事权威状态的集数；初始状态写该集事务执行前的持有人、地点和状态。来源事件ID、替代道具ID或父容器ID不适用时输出空字符串，不得省略字段或输出 null；终止状态始终输出字符"
                "串数组。不输出事件池、映射链路、分集卡或剧本正文。第一字符是 { ，最后一字符是 }。"
            ),
        ]
    )


def render_stage05_event_prompt(
    values: dict[str, Any],
    *,
    arc: dict[str, Any],
    spec: dict[str, Any],
    foundation: dict[str, Any],
) -> str:
    """Handle render stage05 event prompt."""
    episode_range = spec.get("episode_range", "")
    if isinstance(episode_range, dict):
        episode_range = f"{episode_range.get('start', '')}-{episode_range.get('end', '')}"
    range_start, range_end = validators.parse_numeric_range(str(episode_range))
    example_event_id = int(spec["start_event_id"])
    example_transaction_id = f"E{example_event_id}-B1"
    example_effect_id = f"{example_transaction_id}-F1"
    max_event_span = int(
        (values.get("derived_config") or {}).get("event_reuse_max_episodes", 3) or 3
    )
    output_skeleton = {
        "事件池": [
            {
                "ID": example_event_id,
                "标题": "",
                "功能": "",
                "原著情节点ID": [],
                "原著事实ID": [],
                "戏剧状态变化": {
                    "变化维度": "目标",
                    "变化前": "",
                    "变化后": "",
                    "非重复说明": "",
                },
                "扩写类型": "强化原情节",
                "目标篇章": int(spec["arc_id"]),
                "事件集数窗口": {"开始": range_start, "结束": range_end},
                "不得早于集数": range_start,
                "不得晚于集数": range_end,
                "预期覆盖集数": range_end - range_start + 1,
                "重要级别": "A",
                "冲突模式": "",
                "模式家族": "",
                "原著锚点": "",
                "相对原著变化": "",
                "法律道德风险": "低",
                "内容敏感风险": "低",
                "戏剧释放目标ID列表": [
                    dramatic_release.release_id_for_episode(episode_num)
                    for episode_num in range(range_start, range_end + 1)
                ],
                "子情节点": [
                    {
                        "子情节点ID": example_transaction_id,
                        "前置状态": [
                            {
                                "状态引用": "PROP_001.location",
                                "预期状态": "人物A手中",
                            }
                        ],
                        "动作": "人物A把文件放到桌上",
                        "状态效果": [
                            {
                                "效果ID": example_effect_id,
                                "效果类型": "道具位置",
                                "效果主体": "人物A",
                                "行动对象": "PROP_001",
                                "变化前": "人物A手中",
                                "变化后": "桌上",
                                "证据词": ["文件", "桌上"],
                            }
                        ],
                        "提前禁止效果": [
                            {
                                "效果ID": example_effect_id,
                                "原因": "所属集数前不得让文件出现在桌上",
                            }
                        ],
                        "完成证据": "画面明确出现文件被放到桌上",
                        "完成证据词": ["文件", "桌上"],
                        "流程状态迁移": {
                            "流程ID": "",
                            "流程开始阶段": "",
                            "流程结束阶段": ""
                        },
                        "可与下一事务同集": False,
                    }
                ],
            }
        ]
    }
    return "\n\n".join(
        [
            "# 任务目标",
            "完成 05 情节人物改编的当前弧线事件池。本次只输出事件池。",
            "## 当前弧线\n" + prompt_renderer.stringify_for_prompt("macro_arcs", arc),
            (
                "## 生成范围\n"
                f"- 弧线编号：{int(spec['arc_id'])}\n"
                f"- 集数范围：{episode_range}\n"
                f"- 事件数量：{int(spec['event_count'])}\n"
                f"- 事件ID范围：{int(spec['start_event_id'])}-{int(spec['end_event_id'])}"
            ),
            "## 源故事锁\n" + prompt_renderer.stringify_for_prompt(
                "canonical_story_lock",
                values.get("canonical_story_lock", {}),
            ),
            "## 源情节点\n" + prompt_renderer.stringify_for_prompt(
                "source_plot_points",
                values.get("source_plot_points", []),
            ),
            "## 原著事实账本\n" + prompt_renderer.stringify_for_prompt(
                "source_fact_ledger",
                values.get("source_fact_ledger", []),
            ),
            "## 闪回筛选结果\n" + prompt_renderer.stringify_for_prompt(
                "flashback_screening",
                values.get("flashback_screening", {}),
            ),
            "## 当前弧线戏剧释放目标\n" + prompt_renderer.stringify_for_prompt(
                "dramatic_release_map",
                dramatic_release.slice_release_map(
                    values.get("dramatic_release_map", {}),
                    start_episode=range_start,
                    end_episode=range_end,
                ),
            ),
            "## 冲突引擎\n" + prompt_renderer.stringify_for_prompt(
                "conflict_engine",
                foundation.get("conflict_engine", {}),
            ),
            "## 伏笔池\n" + prompt_renderer.stringify_for_prompt(
                "foreshadowing_pool",
                foundation.get("foreshadowing_pool", []),
            ),
            "## 输出 JSON 骨架",
            json.dumps(output_skeleton, ensure_ascii=False),
            "上方每个事件还必须增加 `原著事实ID` 和 `戏剧状态变化`；后者必须包含变化维度、变化前、变化后、非重复说明。",
            "## 执行规则",
            (
                f"必须输出正好 {int(spec['event_count'])} 个事件，ID 依次使用 {int(spec['start_event_id'])}-"
                f"{int(spec['end_event_id'])}，目标篇章固定为 {int(spec['arc_id'])}。事件窗口必须位于当前弧线集数范围内，按事件顺序无空集、无重叠"
                f"地连续覆盖该范围，单个事件窗口最多 {max_event_span} 集。每个事件的戏剧释放目标ID列表必须按集号完整等于其事件窗口内的 DR_EP 编号，不得漏项、越窗或重排"
                f"；事件事务必须实现这些目标的欲望、阻力、选择、即时代价和可见结果，不能把它们降级为流程说明。全部事件的子情节点总数不得少于当前弧线集数。每个事件必须引用已有原著事实ID，并严格"
                f"保留被引用事实的行动者、动作对象和结果，不得把对特定人物的会面、拒绝或惩罚改成对其他人写信、打电话或表态；同时明确改变目标、资源、权力、秘密或关系中的一项，变化前后状态不得相同"
                f"。子情节点数量不得少于事件窗口长度，且不超过窗口长度的3倍。每项是一个可核验状态事务，可包含同一连续场景中为完成该状态变化所需的动作链，但不得在事务内部等待数日后取得新结果；“"
                f"次日、第二天、数周后”可以放在新事务开头作为与上一事务的时间边界。完整包含前置状态、动作、状态效果、提前禁止效果、完成证据、2-4个具体完成证据词、流程状态迁移和布尔值可与下一"
                f"事务同集。每个状态效果使用 E事件ID-B序号-F序号，并提供2-4个具体证据词；全部状态效果都必须列入提前禁止效果。非流程事务的流程ID、流程开始阶段、流程结束阶段都写空字符"
                f"串；流程事务必须使用稳定流程ID，教育录取流程阶段依次为尚未开始、考试完成、分数位次公布、志愿申请提交、正式录取结果、通知书收到、报到注册完成，不得跳级或倒退。可与下一事务同集"
                f"只按真实时空边界判断：同一场景中的行动、反应、揭露和可见结果应写 true；下一事务开头出现新的日期或必须等待成绩、审批、判决、通知时才写 false。输出前按每集最多3个事务"
                f"验证本事件能在窗口内合法分组，放不下就合并同场动作链或调整窗口，不能把矛盾留给 runner。高考流程必须拆成考试完成、分数/位次、填报志愿、正式录取、通知书、报到住宿；查分页"
                f"面不得显示院校录取结果，达到往年线只表示可尝试填报，新生群和宿舍安排只能晚于正式录取。原著前段已有泄密、质问、暴力代价或关系决裂时，保留其相对顺序，不得把第3-5集连续写成来电"
                f"、拒接、关机和考试等待。主角“不拦不帮”只能撤回保护，不得改成故意混放、栽赃或制造违规结果。不输出其他顶层字段。第一字符是 {{ ，最后一字符是 }}。"
            ),
            (
                "事务时间与流程补充硬规则：时间锚点只能出现在动作第一句，动作中途出现次日、第二天或数周后必须拆成新事务。只有教育录取流程填写流程状态迁移；阶段依次为尚未开始、考试完成、分数位次"
                "公布、志愿申请提交、正式录取结果、通知书收到、报到注册完成，每次只能前进一步且前后不得相同。第一科或考试进行中不迁移，全部科目结束才进入考试完成。离婚、治疗、谈判等未登记流程以"
                "及普通事务的三个流程字段全部写空字符串。"
            ),
            (
                "事件独立性底线：如果所有子情节只是前一事件的直接余波，且没有新目标、新角色、新空间、新信息、新证据、新代价或权力/资源/秘密/关系变化，就不能作为独立事件，应把余波缩进前事件的"
                "子情节，并为当前事件设计真正的新变化。非重复说明必须明写上述至少一类独立证据，不能只写「进一步推进」。"
            ),
            (
                "开篇结构规则：若第一弧线包含重生、前世死亡回到过去、循环重启或其他 S 级结构性时间偏离，"
                "事件1的窗口必须是第1集，且只设置1个结构性子情节点；该子情节点可以用一段连续蒙太奇压缩必要前史，"
                "但必须在同一集落回当下，并以主角的第一个主动选择或行动结束。不得把创伤闪回拖成前2-3集的连续铺垫。"
            ),
        ]
    )


def _normalize_stage05_event_chunk(data: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Handle normalize stage05 event chunk."""
    events = [dict(item) for item in data.get("event_pool", []) if isinstance(item, dict)]
    event_count = int(spec["event_count"])
    return normalize_event_child_beats({"event_pool": events[:event_count]})


def _stage05_blocking_transaction_findings(
    data: dict[str, Any],
    *,
    max_event_span: int = 3,
) -> list[dict[str, Any]]:
    """Handle stage05 blocking transaction findings."""
    findings = [
        item
        for item in event_transactions.transaction_atomicity_findings(
            data.get("event_pool", [])
        )
        if item.get("severity") == "BLOCK"
    ]
    for index, event in enumerate(data.get("event_pool", []) or []):
        if not isinstance(event, dict):
            continue
        window = event.get("episode_window", {}) or {}
        try:
            start_episode = int(window.get("start", 0) or 0)
            end_episode = int(window.get("end", 0) or 0)
        except (TypeError, ValueError):
            continue
        span = end_episode - start_episode + 1
        if start_episode > 0 and span > max_event_span:
            findings.append(
                {
                    "severity": "BLOCK",
                    "check": "event_window_span",
                    "path": f"event_pool[{index}].episode_window",
                    "transaction_id": "",
                    "issue": "event_window_exceeds_reuse_limit",
                    "event_id": event.get("id"),
                    "actual_span": span,
                    "maximum_span": max_event_span,
                }
            )
    return findings


def render_stage05_semantic_repair_prompt(
    original_prompt: str,
    *,
    previous_output: dict[str, Any],
    findings: list[dict[str, Any]],
) -> str:
    """Handle render stage05 semantic repair prompt."""
    localized_output = llm_schema_localization.localize_prompt_value("", previous_output)
    finding_lines = [
        "- 路径：{path}；事务：{transaction_id}；问题：{issue}".format(
            path=item.get("path", ""),
            transaction_id=item.get("transaction_id", ""),
            issue=item.get("issue", item.get("check", "")),
        )
        for item in findings
    ]
    return "\n\n".join(
        [
            original_prompt,
            "## 上次事件池完整输出\n" + json.dumps(localized_output, ensure_ascii=False, indent=2),
            "## 本地事务审计必须修复的问题\n" + "\n".join(finding_lines),
            (
                "请完整重写当前弧线事件池，不要只返回补丁。事件ID、原著事实方向和核心因果不得改变；"
                "如果问题包含事件窗口过长，可在当前弧线内重新连续划分各事件窗口，"
                "并同步重分配对应的戏剧释放目标ID，但不得产生空集、重叠或改变事件数量；"
                "可以拆分、合并或改写子情节点，并按顺序重编号子情节点及效果ID。动作中途不得跨日；教育录取流程不得同阶段迁移、跳级或倒退；"
                "未登记的离婚、治疗、谈判流程用普通状态效果表达，流程三个字段写空字符串。修复后仍须满足原输出骨架和事件数量。"
            ),
        ]
    )


def repair_stage05_event_chunk_semantics(
    paths: RunPaths,
    stage: dict[str, Any],
    values: dict[str, Any],
    *,
    spec: dict[str, Any],
    artifact_id: str,
    original_prompt: str,
    chunk: dict[str, Any],
    dry_run: bool,
    llm_script_path: Path | None,
    timeout: int,
    max_retries: int = 2,
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    """Handle repair stage05 event chunk semantics."""
    current = _normalize_stage05_event_chunk(chunk, spec)
    max_event_span = int(
        (values.get("derived_config") or {}).get("event_reuse_max_episodes", 3) or 3
    )
    findings = _stage05_blocking_transaction_findings(
        current,
        max_event_span=max_event_span,
    )
    retry_count = 0
    while findings and retry_count < max_retries and not dry_run:
        retry_count += 1
        retry_root = paths.parsed / "05_semantic_retry_failures"
        write_json(
            retry_root / f"{artifact_id}.attempt_{retry_count:02d}.clean.json",
            current,
        )
        write_json(
            retry_root / f"{artifact_id}.attempt_{retry_count:02d}.findings.json",
            {
                "artifact_id": artifact_id,
                "retry_index": retry_count,
                "finding_count": len(findings),
                "findings": findings,
            },
        )
        repair_prompt = render_stage05_semantic_repair_prompt(
            original_prompt,
            previous_output=current,
            findings=findings,
        )
        invalidate_artifact_cache(paths, artifact_id)
        repaired = call_stage_with_structural_retries(
            paths,
            stage,
            {**values, "_stage05_semantic_retry_index": retry_count},
            dry_run=dry_run,
            llm_script_path=llm_script_path,
            timeout=timeout,
            artifact_id=artifact_id,
            prompt=repair_prompt,
            contract_projection_profile="05_event_chunk",
            retry_directory="05_structural_retry_failures",
            max_retries=2,
        )
        current = _normalize_stage05_event_chunk(repaired, spec)
        findings = _stage05_blocking_transaction_findings(
            current,
            max_event_span=max_event_span,
        )
    return current, findings, retry_count


def _stage05_mapping_trace(
    macro_arcs: list[dict[str, Any]],
    event_pool: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Handle stage05 mapping trace."""
    arc_source_ids = sorted(
        {item for arc in macro_arcs for item in arc.get("source_plot_point_ids", [])},
        key=str,
    )
    event_source_ids = sorted(
        {item for event in event_pool for item in event.get("source_plot_point_ids", [])},
        key=str,
    )
    return [
        {
            "asset_id": "macro_arcs",
            "source_plot_point_ids": arc_source_ids,
            "change_type": "长篇弧线拆分",
            "reason": "依据源情节点和目标集数本地汇总",
        },
        {
            "asset_id": "event_pool",
            "source_plot_point_ids": event_source_ids,
            "change_type": "事件池扩写",
            "reason": "依据各弧线分批事件本地汇总",
        },
    ]


def run_plot_character_adaptation_stage(
    paths: RunPaths,
    stage: dict[str, Any],
    values: dict[str, Any],
    *,
    dry_run: bool,
    llm_script_path: Path | None,
    timeout: int,
    force_reuse: bool = False,
) -> dict[str, Any]:
    """Handle run plot character adaptation stage."""
    final_clean_path = paths.outputs / "05_plot_character_adaptation.clean.json"
    final_manifest_path = paths.manifests / "05_plot_character_adaptation.manifest.json"
    if force_reuse:
        if not final_clean_path.exists():
            raise FileNotFoundError(f"Cannot reuse missing artifact: {final_clean_path}")
        projected, _unmapped = stage_contracts.project_contract_data(
            stage["stage_id"],
            json.loads(read_text(final_clean_path)),
        )
        return normalize_stage_output(stage["stage_id"], projected)

    foundation_artifact_id = "05_plot_character_adaptation.foundation"
    foundation_prompt = render_stage05_foundation_prompt(values)
    foundation = call_stage(
        paths,
        stage,
        values,
        dry_run=dry_run,
        llm_script_path=llm_script_path,
        timeout=timeout,
        artifact_id=foundation_artifact_id,
        prompt_override=foundation_prompt,
        contract_projection_profile="05_foundation",
    )
    macro_arcs = foundation.get("macro_arcs", [])
    specs = build_stage05_event_specs(
        macro_arcs,
        event_pool_size=str((values.get("derived_config") or {}).get("event_pool_size", "12-16")),
        max_event_span=int(
            (values.get("derived_config") or {}).get("event_reuse_max_episodes", 3) or 3
        ),
    )
    event_pool: list[dict[str, Any]] = []
    fanout_trace: list[dict[str, Any]] = []
    child_hashes: dict[str, str] = {
        foundation_artifact_id: sha256_text(json.dumps(foundation, ensure_ascii=False, sort_keys=True))
    }
    for arc, spec in zip(macro_arcs, specs):
        if int(spec["event_count"]) <= 0:
            continue
        artifact_id = stage05_event_artifact_id(spec)
        prompt = render_stage05_event_prompt(values, arc=arc, spec=spec, foundation=foundation)
        chunk = call_stage_with_structural_retries(
            paths,
            stage,
            {**values, "_stage05_event_spec": spec},
            dry_run=dry_run,
            llm_script_path=llm_script_path,
            timeout=timeout,
            artifact_id=artifact_id,
            prompt=prompt,
            contract_projection_profile="05_event_chunk",
            retry_directory="05_structural_retry_failures",
            max_retries=2,
        )
        normalized_chunk, remaining_block_findings, semantic_retry_count = repair_stage05_event_chunk_semantics(
            paths,
            stage,
            {**values, "_stage05_event_spec": spec},
            spec=spec,
            artifact_id=artifact_id,
            original_prompt=prompt,
            chunk=chunk,
            dry_run=dry_run,
            llm_script_path=llm_script_path,
            timeout=timeout,
        )
        if normalized_chunk != chunk:
            append_normalization_operation(
                paths,
                artifact_id=artifact_id,
                stage_id=stage["stage_id"],
                operation="normalize_local_event_ids_and_arc",
                before=chunk,
                after=normalized_chunk,
            )
            child_clean_path = paths.outputs / f"{artifact_id}.clean.json"
            if child_clean_path.exists():
                write_json(child_clean_path, normalized_chunk)
                update_manifest_for_deterministic_repair(
                    paths.manifests / f"{artifact_id}.manifest.json",
                    stage=stage,
                    output_hash=sha256_text(json.dumps(normalized_chunk, ensure_ascii=False, sort_keys=True)),
                    repair_info={"repair": "normalize_local_event_ids_and_arc"},
                )
        event_pool.extend(normalized_chunk["event_pool"])
        child_hashes[artifact_id] = sha256_text(json.dumps(normalized_chunk, ensure_ascii=False, sort_keys=True))
        fanout_trace.append(
            {
                "artifact_id": artifact_id,
                **spec,
                "actual_event_count": len(normalized_chunk["event_pool"]),
                "semantic_retry_count": semantic_retry_count,
                "remaining_block_findings": remaining_block_findings,
                "output_sha256": child_hashes[artifact_id],
            }
        )

    merged = {
        **foundation,
        "event_pool": event_pool,
        "mapping_trace": _stage05_mapping_trace(macro_arcs, event_pool),
    }
    merged, _discarded = stage_contracts.project_contract_data(stage["stage_id"], merged)
    merge_values = {**values, "stage05_fanout": {"child_output_hashes": child_hashes}}
    merge_prompt = "05 情节人物改编本地分批合并索引（不调用模型）\n" + "\n".join(
        f"- {artifact_id}: {output_hash}"
        for artifact_id, output_hash in sorted(child_hashes.items())
    )
    append_normalization_operation(
        paths,
        artifact_id="05_plot_character_adaptation",
        stage_id=stage["stage_id"],
        operation="merge_stage05_foundation_and_event_chunks",
        before=foundation,
        after=merged,
    )
    write_text(paths.prompts / "05_plot_character_adaptation.prompt.md", merge_prompt)
    write_json(paths.parsed / "05_plot_character_adaptation_fanout_trace.json", fanout_trace)
    write_json(final_clean_path, merged)
    write_manifest(
        final_manifest_path,
        stage=stage,
        artifact_id="05_plot_character_adaptation",
        values=merge_values,
        prompt=merge_prompt,
        output_hash=sha256_text(json.dumps(merged, ensure_ascii=False, sort_keys=True)),
        dry_run=dry_run,
        llm_script=str(llm_script_path or ""),
        llm_runtime_options=llm_client.llm_runtime_options(llm_script_path, stage_id=stage["stage_id"]),
    )
    return merged


PHONE_VO_MARKERS = (
    "VO",
    "电话",
    "来电",
    "通话",
    "接听",
    "接通",
    "拨通",
    "拨出",
    "打给",
    "打电话",
    "手机响",
    "画外音",
    "画外声",
    "听筒传来",
    "听筒里",
    "人未到声先到",
)


def _safe_int_value(value: Any, default: int = 0) -> int:
    """Handle safe int value."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def infer_minimum_vo_count_from_scene_plan(episode: dict[str, Any]) -> int:
    """Handle infer minimum vo count from scene plan."""
    scene_plan = episode.get("scene_plan")
    if not isinstance(scene_plan, list):
        return 0
    count = 0
    for item in scene_plan:
        if not isinstance(item, dict):
            continue
        text = json.dumps(item, ensure_ascii=False)
        if any(marker in text for marker in PHONE_VO_MARKERS):
            count += 1
    return count


def build_default_scene_plan(*, ep_num: int, cast_names: list[str]) -> list[dict[str, Any]]:
    """Handle build default scene plan."""
    cast = [name for name in cast_names if str(name).strip()] or ["主角"]
    return [
        {
            "scene_no": 1,
            "location": "公共空间",
            "time": "日",
            "space": "内",
            "appearing_character_names": cast,
            "scene_purpose": "pressure",
            "must_include_beats": ["开场压力", "主角最小回应"],
            "scene_boundary_reason": "本集开场自然场。",
            "visible_space_tokens": ["公共空间"],
        },
        {
            "scene_no": 2,
            "location": "门口",
            "time": "日",
            "space": "外",
            "appearing_character_names": cast,
            "scene_purpose": "counterattack",
            "must_include_beats": [f"第{ep_num}个证据点被提出", "围观压力变化"],
            "scene_boundary_reason": "人物行动从室内压力推进到门口公开对峙。",
            "visible_space_tokens": ["门口"],
        },
        {
            "scene_no": 3,
            "location": "公共空间",
            "time": "傍晚",
            "space": "内",
            "appearing_character_names": cast,
            "scene_purpose": "hook",
            "must_include_beats": ["关键见证者动摇", "下一集承接钩子"],
            "scene_boundary_reason": "时间从日切到傍晚，形成新的承接状态。",
            "visible_space_tokens": ["公共空间"],
        },
    ]


def _strip_script_structure(text: Any) -> str:
    """Handle strip script structure."""
    lines = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^#?\s*第?[0-9一二三四五六七八九十百]+集$", line):
            continue
        if re.match(r"^(第[0-9一二三四五六七八九十百]+场|[0-9一二三四五六七八九十百]+[.、]|\d+\s*-\s*\d+\s+)", line):
            continue
        if re.match(r"^出场人物\s*[:：]", line):
            continue
        lines.append(line)
    return "\n".join(lines)


def _normalize_overlap_text(text: Any) -> str:
    """Handle normalize overlap text."""
    value = _strip_script_structure(text)
    value = re.sub(r"[，。！？；：、“”‘’（）()\[\]【】《》#\s]+", "", value)
    return value


def _script_sentences(text: Any) -> list[str]:
    """Handle script sentences."""
    body = _strip_script_structure(text)
    sentences = []
    for item in re.split(r"[。！？!?；;\n]+", body):
        normalized = _normalize_overlap_text(item)
        if len(normalized) >= 8:
            sentences.append(normalized)
    return sentences


def _ngram_set(text: str, n: int = 5) -> set[str]:
    """Handle ngram set."""
    if len(text) < n:
        return {text} if text else set()
    return {text[idx : idx + n] for idx in range(0, len(text) - n + 1)}


def _ngram_coverage(source_text: str, reference_text: str) -> float:
    """Handle ngram coverage."""
    source = _ngram_set(source_text)
    if not source:
        return 0.0
    reference = _ngram_set(reference_text)
    return len(source & reference) / len(source)


def _child_beat_is_covered(source_beat: Any, consumed_beats: list[Any]) -> bool:
    """Handle child beat is covered."""
    source = _normalize_overlap_text(source_beat)
    if len(source) < 4:
        return True
    for consumed_beat in consumed_beats:
        consumed = _normalize_overlap_text(consumed_beat)
        if not consumed:
            continue
        if source in consumed or consumed in source:
            return True
        source_grams = _ngram_set(source, n=3)
        if source_grams and len(source_grams & _ngram_set(consumed, n=3)) / len(source_grams) >= 0.45:
            return True
    return False


def _event_status_is_completed(value: Any) -> bool:
    """Handle event status is completed."""
    status = str(value or "").strip().lower()
    return status in {"completed", "complete", "done", "finished", "已完成", "完成"}


def analyze_adjacent_script_continuity(final_scripts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle analyze adjacent script continuity."""
    findings: list[dict[str, Any]] = []
    ordered_scripts = sorted(
        [item for item in final_scripts if str(item.get("episode_num", "")).isdigit()],
        key=lambda item: int(item["episode_num"]),
    )
    for previous, current in zip(ordered_scripts, ordered_scripts[1:]):
        previous_text = str(previous.get("final_script", ""))
        current_text = str(current.get("final_script", ""))
        previous_sentences = _script_sentences(previous_text)
        current_opening_sentences = _script_sentences(_clip_text_head(current_text, 700))[:4]
        protected_tail_count = max(1, round(len(previous_sentences) * 0.30)) if previous_sentences else 0
        previous_completed_sentences = (
            previous_sentences[:-protected_tail_count] if protected_tail_count else previous_sentences
        )
        repeated_sentences = [
            sentence
            for sentence in current_opening_sentences
            if any(
                sentence == previous_sentence
                or sentence in previous_sentence
                or previous_sentence in sentence
                for previous_sentence in previous_completed_sentences
            )
        ]
        previous_body = "".join(previous_completed_sentences)
        previous_tail = "".join(previous_sentences[-protected_tail_count:]) if protected_tail_count else ""
        current_opening = "".join(current_opening_sentences) or _normalize_overlap_text(
            _clip_text_head(current_text, 700)
        )
        body_overlap = _ngram_coverage(current_opening, previous_body)
        tail_overlap = _ngram_coverage(current_opening, previous_tail)
        if repeated_sentences or (body_overlap >= 0.28 and body_overlap > tail_overlap + 0.08):
            findings.append(
                {
                    "from_episode": previous.get("episode_num"),
                    "to_episode": current.get("episode_num"),
                    "issue": "current_opening_repeats_previous_completed_beat",
                    "repeated_opening_sentences": repeated_sentences[:3],
                    "previous_body_overlap": round(body_overlap, 3),
                    "previous_tail_overlap": round(tail_overlap, 3),
                }
            )
    return findings


CHECK_PROP_RECEIVED_RE = re.compile(r"(五千元?|补偿)?支票.{0,24}(收入口袋|放进(?:外套)?口袋|折.{0,8}口袋|交付)")
CHECK_PROP_RESET_RE = re.compile(
    r"(离职协议.{0,30}(五千元?|补偿)?支票|"
    r"(五千元?|补偿)?支票.{0,24}(收入口袋|放进(?:外套)?口袋|折.{0,8}口袋))"
)
CHECK_PROP_CONTINUATION_RE = re.compile(r"(从.{0,12}(口袋|衣兜|外套).{0,12}(取出|拿出).{0,8}支票|那张五千元支票|已.{0,8}支票)")
CHECK_PROP_LEFT_ON_TABLE_RE = re.compile(r"(合同.{0,12})?(五千元?|补偿)?支票.{0,24}(摆在桌上|留在桌上|还在桌上|没有人动|无人去拿|原封不动)")


def _script_or_completed_text(item: dict[str, Any]) -> str:
    """Handle script or completed text."""
    update = item.get("continuity_update") or {}
    completed = update.get("completed_beat_ids", update.get("completed_beats", [])) or []
    if isinstance(completed, list):
        completed_text = "\n".join(str(value) for value in completed)
    else:
        completed_text = str(completed or "")
    return str(item.get("final_script", "")) + "\n" + completed_text


def analyze_completed_prop_continuity(final_scripts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle analyze completed prop continuity."""
    findings: list[dict[str, Any]] = []
    ordered_scripts = sorted(
        [item for item in final_scripts if str(item.get("episode_num", "")).isdigit()],
        key=lambda item: int(item["episode_num"]),
    )
    for previous, current in zip(ordered_scripts, ordered_scripts[1:]):
        previous_text = _script_or_completed_text(previous)
        current_head = _clip_text_head(current.get("final_script", ""), 900)
        if not CHECK_PROP_RECEIVED_RE.search(previous_text):
            continue
        if not CHECK_PROP_RESET_RE.search(current_head):
            continue
        if CHECK_PROP_CONTINUATION_RE.search(current_head):
            continue
        findings.append(
            {
                "from_episode": previous.get("episode_num"),
                "to_episode": current.get("episode_num"),
                "issue": "completed_check_prop_state_repeated",
                "detail": (
                        "previous episode already received or pocketed the compensation check, but current openin"
                        "g resets it as a fresh table prop or repeats pocketing"
                    ),
            }
        )
    for previous, current in zip(ordered_scripts, ordered_scripts[1:]):
        previous_text = _script_or_completed_text(previous)
        current_head = _clip_text_head(current.get("final_script", ""), 900)
        if not CHECK_PROP_LEFT_ON_TABLE_RE.search(previous_text):
            continue
        if not CHECK_PROP_CONTINUATION_RE.search(current_head):
            continue
        findings.append(
            {
                "from_episode": previous.get("episode_num"),
                "to_episode": current.get("episode_num"),
                "issue": "check_prop_teleports_from_table_to_pocket",
                "detail": (
                        "previous episode leaves the compensation check on the table, but current opening treats "
                        "it as already in the protagonist's pocket"
                    ),
            }
        )
    return findings


def _prop_name_tracking_token(value: Any) -> str:
    """Handle prop name tracking token."""
    text = re.sub(r"[（(][^）)]*[）)]", "", str(value or ""))
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"^[一二三四五六七八九十百\d]+(?:个|罐|瓶|袋|盒|碗|部|张|份)?", "", text)
    return text if len(text) >= 2 else ""


def analyze_prop_lifecycle_reappearance(final_scripts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle analyze prop lifecycle reappearance."""
    findings: list[dict[str, Any]] = []
    retired_by_token: dict[str, dict[str, Any]] = {}
    ordered_scripts = sorted(
        [item for item in final_scripts if str(item.get("episode_num", "")).isdigit()],
        key=lambda item: int(item["episode_num"]),
    )
    for item in ordered_scripts:
        episode_num = int(item["episode_num"])
        script = re.sub(r"【闪回】.*?(?:【闪出】|【闪回结束】)", "", str(item.get("final_script", "")), flags=re.S)
        continuity = item.get("continuity_update", {}) or {}
        updates = [
            update
            for update in continuity.get("prop_state_changes", continuity.get("prop_state_updates", [])) or []
            if isinstance(update, dict)
        ]
        current_tokens_by_id = {
            str(update.get("prop_id", "")).strip(): _prop_name_tracking_token(update.get("prop_name", ""))
            for update in updates
            if str(update.get("prop_id", "")).strip()
        }
        for token, retired in list(retired_by_token.items()):
            if token not in re.sub(r"\s+", "", script):
                continue
            has_new_lineage = any(
                prop_id != retired["prop_id"] and update_token == token
                for prop_id, update_token in current_tokens_by_id.items()
            )
            if not has_new_lineage:
                findings.append(
                    {
                        "from_episode": retired["retired_episode_num"],
                        "to_episode": episode_num,
                        "issue": "retired_prop_reappears_without_new_lineage",
                        "prop_id": retired["prop_id"],
                        "prop_name": retired["prop_name"],
                        "matched_token": token,
                    }
                )
        for update in updates:
            prop_id = str(update.get("prop_id", "")).strip()
            prop_name = str(update.get("prop_name", "")).strip()
            token = _prop_name_tracking_token(prop_name)
            if not prop_id or not token:
                continue
            lifecycle = infer_prop_lifecycle_status(
                update.get("holder", ""),
                f"{update.get('location', '')} {update.get('status', '')}",
            )
            if lifecycle == "已退出":
                retired_by_token[token] = {
                    "prop_id": prop_id,
                    "prop_name": prop_name,
                    "retired_episode_num": episode_num,
                }
            elif token in retired_by_token and retired_by_token[token]["prop_id"] != prop_id:
                retired_by_token.pop(token, None)
    return findings


def analyze_structured_prop_state_continuity(
    episode_outlines: list[dict[str, Any]],
    final_scripts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Handle analyze structured prop state continuity."""
    outputs_by_episode = {
        int(item["episode_num"]): item
        for item in final_scripts
        if str(item.get("episode_num", "")).isdigit()
    }
    prop_positions: dict[str, Any] = {}
    findings: list[dict[str, Any]] = []
    for episode in sorted(
        [item for item in episode_outlines if str(item.get("episode_num", "")).isdigit()],
        key=lambda item: int(item["episode_num"]),
    ):
        episode_num = int(episode["episode_num"])
        output = outputs_by_episode.get(episode_num)
        if output is None:
            continue
        for finding in validators.prop_state_continuity_findings(
            output,
            episode_outline=episode,
            previous_prop_positions=prop_positions,
        ):
            findings.append({"episode_num": episode_num, **finding})
        continuity = output.get("continuity_update", {}) or {}
        for update in continuity.get("prop_state_changes", continuity.get("prop_state_updates", [])) or []:
            if not isinstance(update, dict):
                continue
            prop_id = str(update.get("prop_id", "")).strip()
            if prop_id:
                prop_positions[prop_id] = dict(update)
    return findings


def collect_character_names_for_coverage(
    canonical_story_lock: dict[str, Any] | None,
    stage05: dict[str, Any],
) -> list[str]:
    """Handle collect character names for coverage."""
    names = collect_allowed_character_names(canonical_story_lock or {}, stage05.get("expanded_character_network", []))
    candidates: list[str] = []
    for raw_name in names:
        name = validators.normalize_character_name(raw_name)
        if not name:
            continue
        candidates.append(name)
        candidates.extend(validators.split_character_group_name(name))
        if "父母" in name or "爸妈" in name or "爹妈" in name:
            prefix = re.sub(r"(父母|爸妈|爹妈).*", "", name).strip()
            if prefix:
                candidates.extend([f"{prefix}父亲", f"{prefix}母亲"])
    return sorted((name for name in _ordered_unique(candidates) if len(name) >= 2), key=lambda item: (-len(item), item))


def analyze_appearing_character_coverage(
    episode_outlines: list[dict[str, Any]],
    final_scripts: list[dict[str, Any]] | None,
    *,
    known_character_names: list[str],
) -> list[dict[str, Any]]:
    """Handle analyze appearing character coverage."""
    if not final_scripts or not known_character_names:
        return []
    script_by_episode = {
        int(item["episode_num"]): str(item.get("final_script", ""))
        for item in final_scripts
        if str(item.get("episode_num", "")).isdigit()
    }
    findings: list[dict[str, Any]] = []
    for episode in episode_outlines:
        if not str(episode.get("episode_num", "")).isdigit():
            continue
        episode_num = int(episode["episode_num"])
        script = script_by_episode.get(episode_num, "")
        if not script:
            continue
        listed_names = validators.expand_allowed_character_names(
            [str(name) for name in episode.get("appearing_character_names", []) if str(name).strip()]
        )
        missing_names: list[str] = []
        for name in known_character_names:
            normalized = validators.normalize_character_name(name)
            if not normalized or normalized in listed_names or normalized in missing_names:
                continue
            if script_has_active_character_appearance(script, normalized, episode_num=episode_num):
                missing_names.append(normalized)
        if missing_names:
            findings.append(
                {
                    "episode_num": episode_num,
                    "missing_appearing_character_names": missing_names,
                    "listed_appearing_character_names": episode.get("appearing_character_names", []),
                }
            )
    return findings


def script_has_active_character_appearance(script: str, name: str, *, episode_num: Any = "<unknown>") -> bool:
    """Handle script has active character appearance."""
    normalized = validators.normalize_character_name(name)
    if not normalized:
        return False
    try:
        scenes = validators.parse_final_script_scenes(script, episode_num=episode_num)
    except ValueError:
        return validators.required_character_name_present(normalized, script)
    if not scenes:
        return validators.required_character_name_present(normalized, script)
    for scene in scenes:
        if normalized in {validators.normalize_character_name(item) for item in scene.get("cast", [])}:
            return True
        for raw_line in str(scene.get("body", "")).splitlines():
            line = raw_line.strip()
            speaker_match = validators.DIALOGUE_SPEAKER_RE.match(line)
            if speaker_match and validators.normalize_character_name(speaker_match.group("speaker")) == normalized:
                return True
            if validators._line_mentions_visible_action_role(line, normalized):
                return True
    return False


def script_length_pacing_findings(
    final_scripts: list[dict[str, Any]] | None,
    *,
    derived_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Handle script length pacing findings."""
    if not final_scripts:
        return []
    match = re.match(
        r"^\s*(?P<min>\d+)\s*[-~到至]\s*(?P<max>\d+)\s*$",
        str(derived_config.get("script_length_chars", "")),
    )
    if not match:
        return []
    min_chars = int(match.group("min"))
    max_chars = int(match.group("max"))
    if min_chars < 400:
        return []
    findings: list[dict[str, Any]] = []
    for item in final_scripts:
        script = str(item.get("final_script", ""))
        char_count = len(re.sub(r"\s+", "", script))
        if char_count < min_chars:
            findings.append(
                {
                    "episode_num": item.get("episode_num"),
                    "non_space_chars": char_count,
                    "target_min_chars": min_chars,
                    "target_max_chars": max_chars,
                    "detail": "script is below configured pacing target; collect/report only, not a hard block",
                }
            )
        elif char_count > max_chars:
            findings.append(
                {
                    "episode_num": item.get("episode_num"),
                    "non_space_chars": char_count,
                    "target_min_chars": min_chars,
                    "target_max_chars": max_chars,
                    "detail": "script is above configured pacing target; collect/report only, not a hard block",
                }
            )
    return findings


STRESS_REACTION_WORDS = ("颤抖", "发抖", "脸色发白", "指节发白", "僵住", "痉挛", "喘气", "冷汗", "猛缩")
CONTROL_RECOVERY_WORDS = ("稳住", "放平", "松开", "抬头", "直视", "落笔", "收好", "关掉", "转身", "推开", "离开", "拒绝", "按下")


def protagonist_tone_balance_findings(
    final_scripts: list[dict[str, Any]] | None,
    *,
    target_tone: Any,
) -> list[dict[str, Any]]:
    """Handle protagonist tone balance findings."""
    tone_text = json.dumps(target_tone, ensure_ascii=False) if not isinstance(target_tone, str) else target_tone
    if not any(marker in tone_text for marker in ("冷感", "冷静", "掌控", "克制")):
        return []
    findings: list[dict[str, Any]] = []
    for item in final_scripts or []:
        script = str(item.get("final_script", ""))
        stress_count = sum(script.count(word) for word in STRESS_REACTION_WORDS)
        recovery_count = sum(script.count(word) for word in CONTROL_RECOVERY_WORDS)
        if stress_count >= 4 and recovery_count < stress_count:
            findings.append(
                {
                    "episode_num": item.get("episode_num"),
                    "issue": "stress_reactions_overwhelm_control_recovery",
                    "stress_reaction_count": stress_count,
                    "control_recovery_count": recovery_count,
                    "target_tone": target_tone,
                }
            )
    return findings


def build_qa_summary(
    stage_outputs: dict[str, dict[str, Any]],
    episode_outlines: list[dict[str, Any]],
    *,
    target_episodes: int,
    derived_config: dict[str, Any] | None = None,
    final_scripts: list[dict[str, Any]] | None = None,
    canonical_story_lock: dict[str, Any] | None = None,
    validation_mode: str | None = None,
) -> dict[str, Any]:
    """Handle build qa summary."""
    derived_config = derived_config or {}
    validation_mode = normalize_validation_mode(validation_mode)
    episode_numbers = [int(item.get("episode_num", -1)) for item in episode_outlines]
    expected_numbers = list(range(1, target_episodes + 1))
    missing_conflict = [item.get("episode_num") for item in episode_outlines if not item.get("main_conflict")]
    missing_counterattack = [item.get("episode_num") for item in episode_outlines if not item.get("counterattack")]
    missing_hook = [item.get("episode_num") for item in episode_outlines if not item.get("ending_hook")]
    used_foreshadowing_ids = sorted(
        {
            int(foreshadowing_id)
            for item in episode_outlines
            for foreshadowing_id in item.get("foreshadowing_ids", [])
            if str(foreshadowing_id).isdigit()
        }
    )
    stage01 = stage_outputs.get("01_novel_summary", {})
    stage04 = stage_outputs.get("04_adaptation_direction", {})
    stage04a = stage_outputs.get("04a_flashback_screening", {})
    stage05 = stage_outputs.get("05_plot_character_adaptation", {})
    known_foreshadowing_ids = {
        int(item["id"]) for item in stage05.get("foreshadowing_pool", []) if str(item.get("id", "")).isdigit()
    }
    event_pool = stage05.get("event_pool", [])
    event_by_id = {int(item["id"]): item for item in event_pool if str(item.get("id", "")).isdigit()}
    event_use_counts: dict[int, int] = {}
    event_block_mismatches = []
    event_window_mismatches = []
    conflict_streaks = []
    pattern_streaks = []
    boundary_risks = []
    content_sensitivity_risks = []
    content_sensitivity_warnings = []
    child_beat_accounting_warnings = []
    child_beat_claims_by_event: dict[int, dict[str, Any]] = {}
    for event in event_pool:
        risk_text = " ".join(
            [
                str(event.get("title", "")),
                str(event.get("source_anchor", "")),
                str(event.get("delta_from_source", "")),
                str(event.get("content_sensitivity_risk", "")),
                " ".join(str(item) for item in event.get("child_beats", [])),
            ]
        )
        if (
            str(event.get("content_sensitivity_risk", "")).strip().lower() == "high"
            or validators.has_content_sensitivity_risk(risk_text)
        ):
            content_sensitivity_risks.append(
                {"scope": "event_pool", "event_id": event.get("id"), "title": event.get("title", "")},
            )
        elif str(event.get("content_sensitivity_risk", "")).strip().lower() == "medium":
            content_sensitivity_warnings.append(
                {"scope": "event_pool", "event_id": event.get("id"), "title": event.get("title", "")},
            )
    current_mode = None
    current_streak = 0
    current_pattern = None
    current_pattern_streak = 0
    epilogue_episode_nums = []
    for item in episode_outlines:
        episode_num = item.get("episode_num")
        if item.get("is_epilogue"):
            epilogue_episode_nums.append(episode_num)
        boundary_check = item.get("boundary_check", {})
        if isinstance(boundary_check, dict):
            risk_level = str(boundary_check.get("risk_level", "")).lower()
            if risk_level in {"medium", "high"}:
                boundary_risks.append(
                    {
                        "episode_num": episode_num,
                        "risk_level": risk_level,
                        "protagonist_action": boundary_check.get("protagonist_action", ""),
                    }
                )
        episode_text = " ".join(
            str(item.get(key, ""))
            for key in (
                "main_conflict", "counterattack", "information_gain", "ending_hook", "source_anchor", "expansion_delta"
            )
        )
        if isinstance(boundary_check, dict):
            episode_text += " " + " ".join(str(value) for value in boundary_check.values())
        content_check = item.get("content_sensitivity_check", {})
        if isinstance(content_check, dict):
            episode_text += " " + " ".join(str(value) for value in content_check.values())
        if (
            isinstance(content_check, dict)
            and str(content_check.get("risk_level", "")).strip().lower() == "high"
        ) or validators.has_content_sensitivity_risk(episode_text):
            content_sensitivity_risks.append({"scope": "episode_outline", "episode_num": episode_num})
        elif isinstance(content_check, dict) and str(content_check.get("risk_level", "")).strip().lower() == "medium":
            content_sensitivity_warnings.append({"scope": "episode_outline", "episode_num": episode_num})
        mode = item.get("conflict_mode")
        if mode == current_mode:
            current_streak += 1
        else:
            if current_mode is not None:
                conflict_streaks.append({"conflict_mode": current_mode, "length": current_streak})
            current_mode = mode
            current_streak = 1
        pattern = item.get("pattern_family")
        if pattern == current_pattern:
            current_pattern_streak += 1
        else:
            if current_pattern is not None:
                pattern_streaks.append({"pattern_family": current_pattern, "length": current_pattern_streak})
            current_pattern = pattern
            current_pattern_streak = 1
        for event_id_raw in item.get("event_ids", []):
            if not str(event_id_raw).isdigit():
                continue
            event_id = int(event_id_raw)
            event_use_counts[event_id] = event_use_counts.get(event_id, 0) + 1
            event = event_by_id.get(event_id)
            has_stable_child_beat_ids = isinstance(item.get("consumed_child_beat_ids"), list)
            consumed_child_beats = item.get("consumed_child_beats", [])
            if event:
                claims = child_beat_claims_by_event.setdefault(
                    event_id,
                    {"consumed_child_beats": [], "statuses": [], "episodes": [], "uses_stable_ids": False},
                )
                if isinstance(consumed_child_beats, list):
                    claims["consumed_child_beats"].extend(consumed_child_beats)
                claims["uses_stable_ids"] = claims["uses_stable_ids"] or has_stable_child_beat_ids
                claims["statuses"].append(item.get("event_consumption_status", ""))
                claims["episodes"].append(episode_num)
            if (
                event
                and not has_stable_child_beat_ids
                and (not isinstance(consumed_child_beats, list) or not consumed_child_beats)
            ):
                child_beat_accounting_warnings.append(
                    {
                        "episode_num": episode_num,
                        "event_id": event_id,
                        "event_title": event.get("title", ""),
                        "detail": "event_id is used but consumed_child_beats is empty or not a list",
                    }
                )
            if (
                event
                and int(event.get("target_block", -1)) != int(item.get("block_id", -2))
                and not item.get("allowed_cross_block_bridge")
            ):
                event_block_mismatches.append(
                    {
                        "episode_num": episode_num,
                        "event_id": event_id,
                        "target_block": event.get("target_block"),
                        "block_id": item.get("block_id"),
                    }
                )
            if event:
                try:
                    start, end = validators._event_window(event)
                except ValueError:
                    event_window_mismatches.append(
                        {"episode_num": episode_num, "event_id": event_id, "window": "invalid"},
                    )
                else:
                    if int(episode_num) < start or int(episode_num) > end:
                        event_window_mismatches.append(
                            {
                                "episode_num": episode_num,
                                "event_id": event_id,
                                "episode_window": {"start": start, "end": end},
                            }
                        )
    for event_id, claims in sorted(child_beat_claims_by_event.items()):
        event = event_by_id.get(event_id, {})
        if claims.get("uses_stable_ids"):
            continue
        source_child_beats = [
            str(beat.get("action", "")).strip() if isinstance(beat, dict) else str(beat or "").strip()
            for beat in event.get("child_beats", [])
            if (str(beat.get("action", "")).strip() if isinstance(beat, dict) else str(beat or "").strip())
        ]
        if (
            not source_child_beats
            or not any(_event_status_is_completed(status) for status in claims.get("statuses", []))
        ):
            continue
        consumed_beats = claims.get("consumed_child_beats", [])
        missing_source_beats = [beat for beat in source_child_beats if not _child_beat_is_covered(beat, consumed_beats)]
        if missing_source_beats:
            child_beat_accounting_warnings.append(
                {
                    "issue": "completed_event_child_beats_not_covered",
                    "event_id": event_id,
                    "event_title": event.get("title", ""),
                    "episodes": claims.get("episodes", []),
                    "missing_source_child_beats": missing_source_beats[:5],
                    "consumed_child_beats": consumed_beats[:8],
                    "detail": "event is marked completed but consumed_child_beats do not cover all source child_beats",
                }
            )
    if current_mode is not None:
        conflict_streaks.append({"conflict_mode": current_mode, "length": current_streak})
    if current_pattern is not None:
        pattern_streaks.append({"pattern_family": current_pattern, "length": current_pattern_streak})
    max_conflict_streak = max([item["length"] for item in conflict_streaks], default=0)
    max_pattern_streak = max([item["length"] for item in pattern_streaks], default=0)
    episodes_per_block: dict[str, list[dict[str, Any]]] = {}
    for item in episode_outlines:
        episodes_per_block.setdefault(str(item.get("block_id")), []).append(item)
    event_consumption_by_block = {
        block_id: sorted(
            {
                int(event_id)
                for episode in episodes
                for event_id in episode.get("event_ids", [])
                if str(event_id).isdigit()
            }
        )
        for block_id, episodes in episodes_per_block.items()
    }
    unknown_foreshadowing_ids = sorted(set(used_foreshadowing_ids) - known_foreshadowing_ids)
    epilogue_max = derived_config.get("epilogue_max_episodes")
    conflict_limit = derived_config.get("conflict_mode_streak_limit")
    narration_device_budget_findings = validators.narration_device_plan_findings(episode_outlines)
    event_child_beat_alignment_findings = validators.event_child_beat_alignment_findings(
        episode_outlines,
        event_pool=event_pool,
    )
    flashback_screening_alignment_findings = validators.flashback_screening_alignment_findings(
        episode_outlines,
        flashback_screening=stage04a if stage04a else None,
    )
    adjacent_continuity_findings = analyze_adjacent_script_continuity(final_scripts or []) if final_scripts else []
    completed_prop_continuity_findings = analyze_completed_prop_continuity(final_scripts or []) if final_scripts else []
    prop_lifecycle_reappearance_findings = (
        analyze_prop_lifecycle_reappearance(final_scripts or []) if final_scripts else []
    )
    prop_plan_continuity_findings = validators.prop_continuity_plan_findings(episode_outlines)
    combined_prop_state_findings = prop_plan_continuity_findings + (
        analyze_structured_prop_state_continuity(
            episode_outlines,
            final_scripts or [],
        )
        if final_scripts
        else []
    )
    prop_state_continuity_findings: list[dict[str, Any]] = []
    seen_prop_state_findings: set[str] = set()
    for finding in combined_prop_state_findings:
        finding_key = json.dumps(finding, ensure_ascii=False, sort_keys=True)
        if finding_key in seen_prop_state_findings:
            continue
        seen_prop_state_findings.add(finding_key)
        prop_state_continuity_findings.append(finding)
    continuity_fact_alignment_findings = [
        finding
        for item in (final_scripts or [])
        for finding in validators.continuity_fact_findings(
            {
                "final_script": item.get("final_script", ""),
                "continuity_update": item.get("continuity_update", {}),
            },
            episode_num=item.get("episode_num"),
        )
    ]
    forbidden_script_idiom_findings: list[dict[str, Any]] = []
    for item in final_scripts or []:
        episode_num = item.get("episode_num")
        for finding in validators.find_forbidden_script_idioms(item.get("final_script", "")):
            forbidden_script_idiom_findings.append({"episode_num": episode_num, **finding})
    known_character_names = collect_character_names_for_coverage(canonical_story_lock, stage05)
    appearing_character_coverage_findings = analyze_appearing_character_coverage(
        episode_outlines,
        final_scripts,
        known_character_names=known_character_names,
    )
    short_script_pacing_findings = script_length_pacing_findings(final_scripts, derived_config=derived_config)
    protagonist_tone_findings = protagonist_tone_balance_findings(
        final_scripts,
        target_tone=stage04.get("target_tone", ""),
    )
    child_beat_accounting_blockers = [
        item
        for item in child_beat_accounting_warnings
        if item.get("issue") == "completed_event_child_beats_not_covered"
    ]
    blocking_issues = []
    warnings = []
    def issue_status(check_name: str, has_issue: bool, *, skip: bool = False) -> str:
        """Handle issue status."""
        if skip:
            return "SKIP"
        if not has_issue:
            return "PASS"
        if check_name in HARD_QA_CHECKS or validation_mode == VALIDATION_MODE_STRICT:
            return "BLOCK"
        return "WARN"

    def add_issue(check_name: str, payload: dict[str, Any]) -> None:
        """Handle add issue."""
        issue = {"check": check_name, **payload}
        if check_name in HARD_QA_CHECKS or validation_mode == VALIDATION_MODE_STRICT:
            blocking_issues.append(issue)
        else:
            warnings.append(issue)

    check_results = {
        "episode_numbering": issue_status("episode_numbering", episode_numbers != expected_numbers),
        "episode_motion": issue_status(
                "episode_motion",
                bool(missing_conflict or missing_counterattack or missing_hook),
            ),
        "asset_references": issue_status("asset_references", bool(unknown_foreshadowing_ids)),
        "event_block_alignment": issue_status("event_block_alignment", bool(event_block_mismatches)),
        "event_window_alignment": issue_status("event_window_alignment", bool(event_window_mismatches)),
        "epilogue_budget": issue_status(
                "epilogue_budget",
                bool(epilogue_max and len(epilogue_episode_nums) > int(epilogue_max)),
            ),
        "conflict_mode_streak": issue_status(
                "conflict_mode_streak",
                bool(conflict_limit and max_conflict_streak > int(conflict_limit)),
            ),
        "pattern_family_streak": issue_status(
                "pattern_family_streak",
                bool(conflict_limit and max_pattern_streak > int(conflict_limit)),
            ),
        "boundary_risk": "WARN" if boundary_risks else "PASS",
        "content_sensitivity": "WARN" if (content_sensitivity_risks or content_sensitivity_warnings) else "PASS",
        "child_beat_accounting": issue_status("child_beat_accounting", bool(child_beat_accounting_blockers))
        if child_beat_accounting_blockers
        else ("WARN" if child_beat_accounting_warnings else "PASS"),
        "event_child_beat_alignment": issue_status(
            "event_child_beat_alignment",
            bool(event_child_beat_alignment_findings),
        ),
        "narration_device_budget": issue_status("narration_device_budget", bool(narration_device_budget_findings)),
        "flashback_screening_alignment": issue_status(
            "flashback_screening_alignment",
            bool(flashback_screening_alignment_findings),
            skip=not bool(stage04a),
        ),
        "forbidden_script_idioms": issue_status(
            "forbidden_script_idioms",
            bool(forbidden_script_idiom_findings),
            skip=not bool(final_scripts),
        ),
        "adjacent_opening_continuity": issue_status(
            "adjacent_opening_continuity",
            bool(adjacent_continuity_findings),
            skip=not bool(final_scripts),
        ),
        "completed_prop_continuity": issue_status(
            "completed_prop_continuity",
            bool(completed_prop_continuity_findings),
            skip=not bool(final_scripts),
        ),
        "prop_lifecycle_reappearance": issue_status(
            "prop_lifecycle_reappearance",
            bool(prop_lifecycle_reappearance_findings),
            skip=not bool(final_scripts),
        ),
        "prop_state_continuity": issue_status(
            "prop_state_continuity",
            bool(prop_state_continuity_findings),
        ),
        "continuity_fact_alignment": issue_status(
            "continuity_fact_alignment",
            bool(continuity_fact_alignment_findings),
            skip=not bool(final_scripts),
        ),
        "appearing_character_coverage": (
            "WARN" if appearing_character_coverage_findings else ("PASS" if final_scripts else "SKIP")
        ),
        "script_length_pacing": "WARN" if short_script_pacing_findings else ("PASS" if final_scripts else "SKIP"),
        "protagonist_tone_balance": issue_status(
            "protagonist_tone_balance",
            bool(protagonist_tone_findings),
            skip=not bool(final_scripts),
        ),
        "parallel_readiness": "PASS"
        if bool(stage_outputs.get("06_script_outline_design", {}).get("block_state_plan"))
        and bool(stage_outputs.get("06_script_outline_design", {}).get("event_release_schedule"))
        else "WARN",
    }
    if check_results["episode_numbering"] == "BLOCK":
        add_issue("episode_numbering", {"detail": "episode_num is not continuous or count mismatches target"})
    if check_results["episode_motion"] in {"BLOCK", "WARN"}:
        add_issue(
            "episode_motion",
            {
                "missing_conflict": missing_conflict,
                "missing_counterattack": missing_counterattack,
                "missing_hook": missing_hook,
            },
        )
    if unknown_foreshadowing_ids:
        add_issue("asset_references", {"unknown_foreshadowing_ids": unknown_foreshadowing_ids})
    if event_block_mismatches:
        add_issue("event_block_alignment", {"items": event_block_mismatches})
    if event_window_mismatches:
        add_issue("event_window_alignment", {"items": event_window_mismatches})
    if check_results["epilogue_budget"] in {"BLOCK", "WARN"}:
        add_issue("epilogue_budget", {"episodes": epilogue_episode_nums, "limit": epilogue_max})
    if check_results["conflict_mode_streak"] in {"BLOCK", "WARN"}:
        add_issue("conflict_mode_streak", {"max": max_conflict_streak, "limit": conflict_limit})
    if check_results["pattern_family_streak"] in {"BLOCK", "WARN"}:
        add_issue("pattern_family_streak", {"max": max_pattern_streak, "limit": conflict_limit})
    if adjacent_continuity_findings:
        add_issue("adjacent_opening_continuity", {"items": adjacent_continuity_findings})
    if completed_prop_continuity_findings:
        add_issue("completed_prop_continuity", {"items": completed_prop_continuity_findings})
    if prop_lifecycle_reappearance_findings:
        add_issue("prop_lifecycle_reappearance", {"items": prop_lifecycle_reappearance_findings})
    if prop_state_continuity_findings:
        add_issue("prop_state_continuity", {"items": prop_state_continuity_findings})
    if continuity_fact_alignment_findings:
        add_issue("continuity_fact_alignment", {"items": continuity_fact_alignment_findings})
    if child_beat_accounting_blockers and validation_mode == VALIDATION_MODE_STRICT:
        add_issue("child_beat_accounting", {"items": child_beat_accounting_blockers})
    if event_child_beat_alignment_findings:
        add_issue("event_child_beat_alignment", {"items": event_child_beat_alignment_findings})
    if narration_device_budget_findings:
        add_issue("narration_device_budget", {"items": narration_device_budget_findings})
    if flashback_screening_alignment_findings:
        add_issue("flashback_screening_alignment", {"items": flashback_screening_alignment_findings})
    if forbidden_script_idiom_findings:
        add_issue("forbidden_script_idioms", {"items": forbidden_script_idiom_findings})
    if content_sensitivity_risks or content_sensitivity_warnings:
        warnings.append(
            {
                "check": "content_sensitivity",
                "items": content_sensitivity_risks + content_sensitivity_warnings,
                "risk_items": content_sensitivity_risks,
                "warning_items": content_sensitivity_warnings,
            }
        )
    if boundary_risks:
        warnings.append({"check": "boundary_risk", "items": boundary_risks})
    if child_beat_accounting_warnings:
        warning_items = (
            [item for item in child_beat_accounting_warnings if item not in child_beat_accounting_blockers]
            if validation_mode == VALIDATION_MODE_STRICT
            else child_beat_accounting_warnings
        )
        if warning_items:
            warnings.append({"check": "child_beat_accounting", "items": warning_items})
    if appearing_character_coverage_findings:
        warnings.append({"check": "appearing_character_coverage", "items": appearing_character_coverage_findings})
    if short_script_pacing_findings:
        warnings.append({"check": "script_length_pacing", "items": short_script_pacing_findings})
    if protagonist_tone_findings:
        add_issue("protagonist_tone_balance", {"items": protagonist_tone_findings})
    if check_results["parallel_readiness"] == "WARN":
        warnings.append(
            {"check": "parallel_readiness", "detail": "block_state_plan or event_release_schedule is missing"},
        )

    hard_blocking_issues = [item for item in blocking_issues if item.get("check") in HARD_QA_CHECKS]
    quality_blocking_issues = [item for item in blocking_issues if item.get("check") not in HARD_QA_CHECKS]
    generation_status = "BLOCK" if hard_blocking_issues else "PASS"
    quality_status = "WARN" if (warnings or quality_blocking_issues) else "PASS"

    return {
        "overall_status": "BLOCK" if blocking_issues else "PASS",
        "generation_status": generation_status,
        "quality_status": quality_status,
        "validation_mode": validation_mode,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "check_results": check_results,
        "episode_continuity": {
            "expected_count": target_episodes,
            "actual_count": len(episode_outlines),
            "numbering_continuous": episode_numbers == expected_numbers,
            "adjacent_opening_findings": adjacent_continuity_findings,
            "completed_prop_continuity_findings": completed_prop_continuity_findings,
            "prop_lifecycle_reappearance_findings": prop_lifecycle_reappearance_findings,
            "prop_state_continuity_findings": prop_state_continuity_findings,
            "prop_plan_continuity_findings": prop_plan_continuity_findings,
            "continuity_fact_alignment_findings": continuity_fact_alignment_findings,
            "narration_device_budget_findings": narration_device_budget_findings,
            "flashback_screening_alignment_findings": flashback_screening_alignment_findings,
            "forbidden_script_idiom_findings": forbidden_script_idiom_findings,
            "protagonist_tone_balance_findings": protagonist_tone_findings,
        },
        "episode_card_checks": {
            "missing_conflict_episode_nums": missing_conflict,
            "missing_counterattack_episode_nums": missing_counterattack,
            "missing_ending_hook_episode_nums": missing_hook,
            "all_episode_cards_have_required_motion": not (missing_conflict or missing_counterattack or missing_hook),
        },
        "foreshadowing": {
            "pool_count": len(stage05.get("foreshadowing_pool", [])),
            "used_foreshadowing_ids": used_foreshadowing_ids,
            "unknown_foreshadowing_ids": sorted(set(used_foreshadowing_ids) - known_foreshadowing_ids),
            "note": "统计分集卡引用的伏笔ID；真实模型输出后仍需人工复核投放与回收质量。",
        },
        "longform_pacing": {
            "event_use_counts": {str(key): value for key, value in sorted(event_use_counts.items())},
            "event_consumption_by_block": event_consumption_by_block,
            "event_block_mismatches": event_block_mismatches,
            "event_window_mismatches": event_window_mismatches,
            "epilogue_episode_nums": epilogue_episode_nums,
            "epilogue_max_episodes": epilogue_max,
            "max_conflict_mode_streak": max_conflict_streak,
            "max_pattern_family_streak": max_pattern_streak,
            "conflict_mode_streak_limit": conflict_limit,
            "boundary_risks": boundary_risks,
            "content_sensitivity_risks": content_sensitivity_risks,
            "content_sensitivity_warnings": content_sensitivity_warnings,
            "child_beat_accounting_warnings": child_beat_accounting_warnings,
            "event_child_beat_alignment_findings": event_child_beat_alignment_findings,
            "script_length_pacing_warnings": short_script_pacing_findings,
            "parallel_readiness": {
                "has_block_state_plan": bool(stage_outputs.get("06_script_outline_design", {}).get("block_state_plan")),
                "has_event_release_schedule": bool(
                        stage_outputs.get("06_script_outline_design", {}).get("event_release_schedule"),
                    ),
                "note": "当前仍默认顺序生成；这些字段用于下一版block级并发。",
            },
        },
        "character_tracking": {
            "appearing_character_coverage_warnings": appearing_character_coverage_findings,
            "known_character_names_checked": known_character_names,
            "note": "比对08正文实际出现的已知人物与07 appearing_character_names；仅用于发现人物台账漏记，不作为内容安全阻断。",
        },
        "source_core_retention": {
            "immutable_elements": stage01.get("immutable_elements", []),
            "must_keep": stage04.get("must_keep", []),
            "coverage_note": "本项检查核心保留项是否进入规划资产，非最终剧情质量评分。",
        },
        "original_expansion_risk": {
            "originality_boundary": stage04.get("originality_boundary", {}),
            "risk_note": "长篇扩写允许新增外部压力，但不能稀释核心梗、情绪债和主角主动性。",
        },
    }


def apply_report_only_issues_to_qa_summary(
    qa_summary: dict[str, Any],
    report_only_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    """Handle apply report only issues to qa summary."""
    validation_mode = normalize_validation_mode(qa_summary.get("validation_mode"))
    items = [item for item in report_only_issues if item.get("stage") != "final_qa"]
    if not items:
        updated = dict(qa_summary)
        check_results = dict(updated.get("check_results", {}))
        check_results.setdefault("report_only_validation", "PASS")
        updated["check_results"] = check_results
        return updated
    updated = dict(qa_summary)
    check_results = dict(updated.get("check_results", {}))
    report_only_status = "BLOCK" if validation_mode == VALIDATION_MODE_STRICT else "WARN"
    check_results["report_only_validation"] = report_only_status
    updated["check_results"] = check_results
    updated["quality_status"] = "WARN"
    if validation_mode == VALIDATION_MODE_STRICT:
        blocking_issues = list(updated.get("blocking_issues", []))
        blocking_issues.append({"check": "report_only_validation", "items": items})
        updated["blocking_issues"] = blocking_issues
        updated["overall_status"] = "BLOCK"
    else:
        warnings = list(updated.get("warnings", []))
        warnings.append({"check": "report_only_validation", "items": items})
        updated["warnings"] = warnings
        updated["blocking_issues"] = list(updated.get("blocking_issues", []))
        updated["generation_status"] = updated.get("generation_status", "PASS")
        updated["overall_status"] = "BLOCK" if updated["blocking_issues"] else "PASS"
    return updated


def validation_check_is_report_only(
    check_name: str,
    *,
    report_only_validation: bool = False,
    validation_mode: str | None = None,
) -> bool:
    """Handle validation check is report only."""
    if check_name == "stage_output":
        return False
    if report_only_validation:
        return True
    if normalize_validation_mode(validation_mode) == VALIDATION_MODE_STRICT:
        return False
    return check_name in DEFAULT_REPORT_ONLY_VALIDATION_CHECKS


def qa_blockers_are_report_only_only(qa_summary: dict[str, Any]) -> bool:
    """Handle qa blockers are report only only."""
    blocking_issues = qa_summary.get("blocking_issues", [])
    return bool(blocking_issues) and all(item.get("check") == "report_only_validation" for item in blocking_issues)


def validate_stage_output(
    stage_id: str,
    data: dict[str, Any],
    *,
    target_episodes: int,
    stage_context: dict[str, Any] | None = None,
    paths: RunPaths | None = None,
    artifact_id: str | None = None,
) -> None:
    """Handle validate stage output."""
    stage_context = stage_context or {}
    data = normalize_stage_output(stage_id, data)
    contract_report = validators.stage_contract_report(stage_id, data)
    if paths is not None and artifact_id is not None:
        write_contract_report(
            paths,
            artifact_id=artifact_id,
            stage_id=stage_id,
            errors=contract_report["errors"],
            warnings=contract_report["warnings"],
            checked_paths=contract_report["checked_paths"],
        )
    if contract_report["errors"]:
        raise ValueError("; ".join(contract_report["errors"]))
    if stage_id == "00a_global_config":
        validators.validate_run_config(data["recommended_run_config"])
    elif stage_id == "01_novel_summary":
        validators.require_keys(
            data,
            ["novel_summary", "core_hook", "expansion_assets", "immutable_elements", "chapter_summaries", "key_events"],
            stage_id=stage_id,
        )
    elif stage_id == "02_storyline_understanding":
        validators.require_keys(
            data,
            [
                "storyline_candidates",
                "selected_storyline",
                "core_conflict",
                "core_hook_structure",
                "story_engine",
                "adaptation_capacity",
            ],
            stage_id=stage_id,
        )
        _run_stage_semantic_validation(
            stage_context=stage_context,
            paths=paths,
            stage_id=stage_id,
            artifact_id=artifact_id,
            check_name="adaptation_capacity",
            check_fn=lambda: validators.validate_adaptation_capacity(
                data.get("adaptation_capacity", {}), target_episodes=target_episodes
            ),
        )
    elif stage_id == "03_plot_character_extract":
        validators.require_keys(
            data,
            [
                "source_plot_points",
                "source_fact_ledger",
                "character_bible",
                "character_expandability",
                "emotional_debt_chain",
                "character_action_boundaries",
                "source_evidence",
            ],
            stage_id=stage_id,
        )
        if "source_anchors" in stage_context:
            _run_stage_semantic_validation(
                stage_context=stage_context,
                paths=paths,
                stage_id=stage_id,
                artifact_id=artifact_id,
                check_name="source_fact_ledger_alignment",
                check_fn=lambda: validators.validate_source_fact_ledger_alignment(
                    data.get("source_fact_ledger", []),
                    source_anchors=stage_context.get("source_anchors", []),
                    source_plot_points=data.get("source_plot_points", []),
                ),
            )
    elif stage_id == "04_adaptation_direction":
        validators.require_keys(
            data,
            [
                "adaptation_direction",
                "target_tone",
                "change_principles",
                "longform_strategy",
                "market_tag_priority",
                "originality_boundary",
                "source_preservation_contract",
                "protagonist_action_boundary",
                "event_release_principles",
                "epilogue_budget",
            ],
            stage_id=stage_id,
        )
        if "source_fact_ledger" in stage_context:
            _run_stage_semantic_validation(
                stage_context=stage_context,
                paths=paths,
                stage_id=stage_id,
                artifact_id=artifact_id,
                check_name="source_preservation_fact_references",
                check_fn=lambda: validators.validate_source_fact_references(
                    [
                        {
                            "source_fact_ids": data.get(
                                "source_preservation_contract", {}
                            ).get("must_preserve_fact_ids", []),
                        },
                    ],
                    source_fact_ledger=stage_context.get("source_fact_ledger", []),
                    path_prefix="source_preservation_contract",
                ),
            )
    elif stage_id == "04a_flashback_screening":
        missing = [
            key
            for key in [
                "flashback_overview",
                "retained_time_deviations",
                "rewrite_time_deviations",
                "deleted_time_deviations",
                "quota_policy",
            ]
            if key not in data or data[key] in (None, "")
        ]
        if missing:
            raise ValueError(f"{stage_id} missing required key(s): {', '.join(missing)}")
        _run_stage_semantic_validation(
            stage_context=stage_context,
            paths=paths,
            stage_id=stage_id,
            artifact_id=artifact_id,
            check_name="flashback_screening_contract",
            check_fn=lambda: validators.validate_flashback_screening_contract(data),
        )
    elif stage_id == "04b_dramatic_release_map":
        dramatic_release.validate_release_structure(
            data,
            target_episodes=target_episodes,
        )
        release_audit = dramatic_release.audit_release_map(
            data,
            target_episodes=target_episodes,
        )
        _run_stage_semantic_validation(
            stage_context=stage_context,
            paths=paths,
            stage_id=stage_id,
            artifact_id=artifact_id,
            check_name="dramatic_release_quality",
            check_fn=lambda: _require_validation_condition(
                release_audit.get("status") == "PASS",
                json.dumps(release_audit.get("findings", []), ensure_ascii=False),
            ),
        )
    elif stage_id == "05_plot_character_adaptation":
        validators.require_keys(
            data,
            [
                "macro_arcs",
                "event_pool",
                "conflict_engine",
                "expanded_character_network",
                "foreshadowing_pool",
                "prop_registry",
                "mapping_trace",
            ],
            stage_id=stage_id,
        )
        expected_block_count = validators.expected_block_count_for_target(target_episodes)
        _run_stage_semantic_validation(
            stage_context=stage_context,
            paths=paths,
            stage_id=stage_id,
            artifact_id=artifact_id,
            check_name="macro_arcs_count",
            check_fn=lambda: _require_validation_condition(
                len(data["macro_arcs"]) == expected_block_count,
                f"05_plot_character_adaptation macro_arcs must contain {expected_block_count} items",
            ),
        )
        if "dramatic_release_map" in stage_context:
            release_findings = dramatic_release.event_alignment_findings(
                data.get("event_pool", []),
                release_map=stage_context.get("dramatic_release_map"),
            )
            _run_stage_semantic_validation(
                stage_context=stage_context,
                paths=paths,
                stage_id=stage_id,
                artifact_id=artifact_id,
                check_name="event_dramatic_release_alignment",
                check_fn=lambda: _require_validation_condition(
                    not release_findings,
                    json.dumps(release_findings, ensure_ascii=False),
                ),
            )
        _run_stage_semantic_validation(
            stage_context=stage_context,
            paths=paths,
            stage_id=stage_id,
            artifact_id=artifact_id,
            check_name="event_pool_trace",
            check_fn=lambda: validators.validate_event_pool_trace(data["event_pool"]),
        )
        if "derived_config" in stage_context:
            _run_stage_semantic_validation(
                stage_context=stage_context,
                paths=paths,
                stage_id=stage_id,
                artifact_id=artifact_id,
                check_name="event_pool_contract",
                check_fn=lambda: validators.validate_event_pool_contract(
                    data["event_pool"],
                    derived_config=stage_context["derived_config"],
                ),
            )
        if "source_fact_ledger" in stage_context:
            _run_stage_semantic_validation(
                stage_context=stage_context,
                paths=paths,
                stage_id=stage_id,
                artifact_id=artifact_id,
                check_name="event_source_fact_references",
                check_fn=lambda: validators.validate_source_fact_references(
                    data.get("event_pool", []),
                    source_fact_ledger=stage_context.get("source_fact_ledger", []),
                    path_prefix="event_pool",
                ),
            )
        _run_stage_semantic_validation(
            stage_context=stage_context,
            paths=paths,
            stage_id=stage_id,
            artifact_id=artifact_id,
            check_name="event_dramatic_delta",
            check_fn=lambda: validators.validate_event_dramatic_deltas(data.get("event_pool", [])),
        )
        _run_stage_semantic_validation(
            stage_context=stage_context,
            paths=paths,
            stage_id=stage_id,
            artifact_id=artifact_id,
            check_name="event_independence",
            check_fn=lambda: validators.validate_event_independence(data.get("event_pool", [])),
        )
        _run_stage_semantic_validation(
            stage_context=stage_context,
            paths=paths,
            stage_id=stage_id,
            artifact_id=artifact_id,
            check_name="event_child_beat_capacity",
            check_fn=lambda: validators.validate_event_child_beat_capacity(data.get("event_pool", [])),
        )
        _run_stage_semantic_validation(
            stage_context=stage_context,
            paths=paths,
            stage_id=stage_id,
            artifact_id=artifact_id,
            check_name="event_transaction_atomicity",
            check_fn=lambda: _require_validation_condition(
                not event_transactions.transaction_atomicity_findings(
                    data.get("event_pool", [])
                ),
                json.dumps(
                    event_transactions.transaction_atomicity_findings(
                        data.get("event_pool", [])
                    ),
                    ensure_ascii=False,
                ),
            ),
        )
    elif stage_id == "06_script_outline_design":
        validators.require_keys(
            data,
            [
                "global_outline",
                "longform_blocks",
                "phase_breakdown",
                "episode_budget",
                "event_release_schedule",
                "block_event_plan",
                "climax_guardrails",
                "block_state_plan",
                "qa_rules",
                "adaptation_capacity_warning",
            ],
            stage_id=stage_id,
        )
        _run_stage_semantic_validation(
            stage_context=stage_context,
            paths=paths,
            stage_id=stage_id,
            artifact_id=artifact_id,
            check_name="longform_blocks",
            check_fn=lambda: validators.validate_longform_blocks(
                data["longform_blocks"],
                target_episodes=target_episodes,
                expected_block_count=stage_context.get("expected_block_count"),
            ),
        )
        _run_stage_semantic_validation(
            stage_context=stage_context,
            paths=paths,
            stage_id=stage_id,
            artifact_id=artifact_id,
            check_name="episode_budget",
            check_fn=lambda: validators.validate_episode_budget(
                data["episode_budget"],
                target_episodes=target_episodes,
            ),
        )
    elif stage_id == "07_episode_planning":
        validators.require_keys(data, ["episode_allocation", "block_plans", "episode_outlines"], stage_id=stage_id)
        _run_stage_semantic_validation(
            stage_context=stage_context,
            paths=paths,
            stage_id=stage_id,
            artifact_id=artifact_id,
            check_name="block_plans",
            check_fn=lambda: validators.validate_longform_blocks(
                data["block_plans"],
                target_episodes=target_episodes,
                expected_block_count=stage_context.get("expected_block_count"),
            ),
        )
        validators.validate_episode_sequence(data["episode_outlines"], target_episodes=target_episodes)
        if "source_fact_ledger" in stage_context:
            _run_stage_semantic_validation(
                stage_context=stage_context,
                paths=paths,
                stage_id=stage_id,
                artifact_id=artifact_id,
                check_name="episode_source_fact_references",
                check_fn=lambda: validators.validate_source_fact_references(
                    data.get("episode_outlines", []),
                    source_fact_ledger=stage_context.get("source_fact_ledger", []),
                    path_prefix="episode_outlines",
                ),
            )
            _run_stage_semantic_validation(
                stage_context=stage_context,
                paths=paths,
                stage_id=stage_id,
                artifact_id=artifact_id,
                check_name="episode_fact_transitions",
                check_fn=lambda: validators.validate_episode_fact_transitions(
                    data.get("episode_outlines", []),
                    source_fact_ledger=stage_context.get("source_fact_ledger", []),
                ),
            )
        _run_stage_semantic_validation(
            stage_context=stage_context,
            paths=paths,
            stage_id=stage_id,
            artifact_id=artifact_id,
            check_name="target_script_density",
            check_fn=lambda: validators.validate_episode_target_script_density_plans(
                data["episode_outlines"]
            ),
        )
        _run_stage_semantic_validation(
            stage_context=stage_context,
            paths=paths,
            stage_id=stage_id,
            artifact_id=artifact_id,
            check_name="prop_continuity_plan",
            check_fn=lambda: validators.validate_episode_prop_continuity_plans(
                data["episode_outlines"]
            ),
        )
        _run_stage_semantic_validation(
            stage_context=stage_context,
            paths=paths,
            stage_id=stage_id,
            artifact_id=artifact_id,
            check_name="scene_space_coherence",
            check_fn=lambda: validators.validate_episode_scene_space_coherence_plans(
                data["episode_outlines"]
            ),
        )
        if "event_pool" in stage_context and "foreshadowing_pool" in stage_context:
            _run_stage_semantic_validation(
                stage_context=stage_context,
                paths=paths,
                stage_id=stage_id,
                artifact_id=artifact_id,
                check_name="episode_event_fact_alignment",
                check_fn=lambda: validators.validate_episode_event_fact_alignment(
                    data["episode_outlines"],
                    event_pool=stage_context["event_pool"],
                ),
            )
            _run_stage_semantic_validation(
                stage_context=stage_context,
                paths=paths,
                stage_id=stage_id,
                artifact_id=artifact_id,
                check_name="event_child_beat_alignment",
                check_fn=lambda: validators.validate_episode_child_beat_references(
                    data["episode_outlines"],
                    event_pool=stage_context["event_pool"],
                ),
            )
            _run_stage_semantic_validation(
                stage_context=stage_context,
                paths=paths,
                stage_id=stage_id,
                artifact_id=artifact_id,
                check_name="episode_asset_references",
                check_fn=lambda: validators.validate_episode_asset_references(
                    data["episode_outlines"],
                    event_pool=stage_context["event_pool"],
                    foreshadowing_pool=stage_context["foreshadowing_pool"],
                ),
            )
            if "derived_config" in stage_context:
                _run_stage_semantic_validation(
                    stage_context=stage_context,
                    paths=paths,
                    stage_id=stage_id,
                    artifact_id=artifact_id,
                    check_name="episode_longform_contract",
                    check_fn=lambda: validators.validate_episode_longform_contract(
                        data["episode_outlines"],
                        event_pool=stage_context["event_pool"],
                        derived_config=stage_context["derived_config"],
                        allowed_character_names=stage_context.get("allowed_character_names"),
                    ),
                )
        if "canonical_story_lock" in stage_context:
            _run_stage_semantic_validation(
                stage_context=stage_context,
                paths=paths,
                stage_id=stage_id,
                artifact_id=artifact_id,
                check_name="episode_required_names",
                check_fn=lambda: validators.validate_episode_required_names(
                    data["episode_outlines"],
                    allowed_names=stage_context.get("allowed_character_names")
                    or stage_context["canonical_story_lock"].get("character_names", []),
                ),
            )
        if "flashback_screening" in stage_context:
            _run_stage_semantic_validation(
                stage_context=stage_context,
                paths=paths,
                stage_id=stage_id,
                artifact_id=artifact_id,
                check_name="flashback_screening_alignment",
                check_fn=lambda: validators.validate_episode_flashback_screening_alignment(
                    data["episode_outlines"],
                    flashback_screening=stage_context.get("flashback_screening"),
                ),
            )
        if "dramatic_release_map" in stage_context:
            release_findings = dramatic_release.episode_alignment_findings(
                data.get("episode_outlines", []),
                release_map=stage_context.get("dramatic_release_map"),
            )
            _run_stage_semantic_validation(
                stage_context=stage_context,
                paths=paths,
                stage_id=stage_id,
                artifact_id=artifact_id,
                check_name="episode_dramatic_release_alignment",
                check_fn=lambda: _require_validation_condition(
                    not release_findings,
                    json.dumps(release_findings, ensure_ascii=False),
                ),
            )
    elif stage_id == "08_script_body_generation":
        validators.require_keys(
            data,
            ["schema_version", "final_script", "state_update", "continuity_update"],
            stage_id=stage_id,
        )
        if data.get("schema_version") != continuity_ledger_v2.EPISODE_DELTA_SCHEMA_VERSION:
            raise ValueError(f"{stage_id}.schema_version must be {continuity_ledger_v2.EPISODE_DELTA_SCHEMA_VERSION}")
        _run_stage_semantic_validation(
            stage_context=stage_context,
            paths=paths,
            stage_id=stage_id,
            artifact_id=artifact_id,
            check_name="episode_delta_operations",
            check_fn=lambda: validators.validate_episode_delta_operations(data),
        )


def run_pipeline(args: argparse.Namespace) -> Path:
    """Handle run pipeline."""
    stages = stage_map()
    run_id = args.run_id or datetime.now().strftime("%y%m%d_%H%M%S")
    paths = create_run_paths(Path(args.runs_dir), run_id)
    validation_mode = resolve_validation_mode(args)
    stop_after = normalize_stage_boundary(getattr(args, "stop_after", None))
    generate_episodes = int(args.generate_episodes)
    resume_from = normalize_stage_boundary(getattr(args, "resume_from", None))
    reuse_through = normalize_stage_boundary(getattr(args, "reuse_through", None))
    if resume_from:
        invalidate_from_stage(paths, resume_from, generate_episodes=generate_episodes)
        previous_index = stage_index(resume_from) - 1
        if previous_index >= 0:
            implied_reuse = STAGE_EXECUTION_ORDER[previous_index]
            if reuse_through is None or stage_index(reuse_through) < stage_index(implied_reuse):
                reuse_through = implied_reuse
    if reuse_through and not getattr(args, "preserve_downstream", False):
        next_stage = stage_after(reuse_through)
        if next_stage:
            invalidate_from_stage(paths, next_stage, generate_episodes=generate_episodes)

    source = text_io.read_text_with_metadata(args.novel)
    metadata = source.metadata()
    validators.validate_source_metadata(metadata)
    chapters = split_chapters(source.text)
    chapter_chunks = compact_chapter_chunks(chapters)
    source_anchors = build_source_anchors(source.text)
    anchored_source_text = render_anchored_source(source_anchors)
    llm_script_path = None if args.dry_run else llm_client.resolve_llm_script(args.llm_script)
    run_config, _config_resolution = resolve_global_run_config(
        args=args,
        paths=paths,
        stage=stages["00a_global_config"],
        source_text=source.text,
        source_sha256=str(metadata["sha256"]),
        llm_script_path=llm_script_path,
        allow_history=resume_from != "00a_global_config",
    )
    derived_config = derive_run_config(run_config)
    prompt_context = base_prompt_values(run_config, derived_config)
    target_episodes = int(run_config["target_episodes"])
    if generate_episodes < 0 or generate_episodes > target_episodes:
        raise ValueError("generate_episodes must be between 0 and target_episodes")
    update_run_state(
        paths,
        status="planned",
        run_id=run_id,
        configured_target_episodes=target_episodes,
        target_episodes=generate_episodes,
        generated_episodes=[],
        generated_episode_count=0,
        continuous_completed_prefix=0,
        current_artifact="",
        failure=None,
    )
    write_json(paths.parsed / "00_run_config.json", run_config)
    write_json(paths.parsed / "00_derived_config.json", derived_config)
    write_text(paths.parsed / "00_source_text.normalized.txt", source.text)
    write_json(paths.parsed / "00_source_metadata.json", metadata)
    write_json(paths.parsed / "00_chapter_chunks.json", chapter_chunks)
    write_json(paths.parsed / "00_source_anchors.json", source_anchors)
    write_text(paths.parsed / "00_source_text.anchored.txt", anchored_source_text)

    if stop_after == "00a_global_config":
        return finish_run(args, write_stage_stop_summary(
            paths,
            run_id=run_id,
            stop_after=stop_after,
            run_config=run_config,
            derived_config=derived_config,
            validation_mode=validation_mode,
            metadata=metadata,
            dry_run=args.dry_run,
        ))

    report_only_issues: list[dict[str, Any]] = []
    initialize_report_only_issue_log(paths)
    if bool(getattr(args, "force_reuse_existing_episodes", False)):
        report_only_issues.append(
            {
                "stage": "08_script_body_generation",
                "artifact_id": "unsafe_reuse",
                "errors": [
                    {
                        "check": "unsafe_episode_reuse",
                        "error": "--force-reuse-existing-episodes bypasses prompt, behavior and ledger hash checks",
                    }
                ],
            }
        )
        write_report_only_issue_log(paths, report_only_issues)
    stage_outputs: dict[str, dict[str, Any]] = {}
    stage_outputs["01_novel_summary"] = call_stage(
        paths,
        stages["01_novel_summary"],
        {**prompt_context, "source_text": anchored_source_text, "chapter_chunks": chapter_chunks},
        dry_run=args.dry_run,
        llm_script_path=llm_script_path,
        timeout=args.timeout,
        force_reuse=should_force_reuse("01_novel_summary", reuse_through),
    )
    validate_stage_output(
        "01_novel_summary",
        stage_outputs["01_novel_summary"],
        target_episodes=target_episodes,
        paths=paths,
        artifact_id="01_novel_summary",
    )
    if stop_after == "01_novel_summary":
        return finish_run(args, write_stage_stop_summary(
            paths,
            run_id=run_id,
            stop_after=stop_after,
            run_config=run_config,
            derived_config=derived_config,
            validation_mode=validation_mode,
            metadata=metadata,
            dry_run=args.dry_run,
        ))

    stage_outputs["02_storyline_understanding"] = call_stage(
        paths,
        stages["02_storyline_understanding"],
        {
            **prompt_context,
            "novel_summary": stage_outputs["01_novel_summary"]["novel_summary"],
            "key_events": stage_outputs["01_novel_summary"]["key_events"],
        },
        dry_run=args.dry_run,
        llm_script_path=llm_script_path,
        timeout=args.timeout,
        force_reuse=should_force_reuse("02_storyline_understanding", reuse_through),
    )
    validate_stage_output(
        "02_storyline_understanding",
        stage_outputs["02_storyline_understanding"],
        target_episodes=target_episodes,
        paths=paths,
        artifact_id="02_storyline_understanding",
        stage_context={
            "validation_mode": validation_mode,
            "report_only_issues": report_only_issues,
        },
    )
    if stop_after == "02_storyline_understanding":
        return finish_run(args, write_stage_stop_summary(
            paths,
            run_id=run_id,
            stop_after=stop_after,
            run_config=run_config,
            derived_config=derived_config,
            validation_mode=validation_mode,
            metadata=metadata,
            dry_run=args.dry_run,
        ))

    stage_outputs["03_plot_character_extract"] = call_stage(
        paths,
        stages["03_plot_character_extract"],
        {
            **prompt_context,
            "source_text": anchored_source_text,
            "source_anchors": source_anchors,
            "selected_storyline": stage_outputs["02_storyline_understanding"]["selected_storyline"],
        },
        dry_run=args.dry_run,
        llm_script_path=llm_script_path,
        timeout=args.timeout,
        force_reuse=should_force_reuse("03_plot_character_extract", reuse_through),
    )
    validate_stage_output(
        "03_plot_character_extract",
        stage_outputs["03_plot_character_extract"],
        target_episodes=target_episodes,
        paths=paths,
        artifact_id="03_plot_character_extract",
        stage_context={
            "source_anchors": source_anchors,
            "validation_mode": validation_mode,
            "report_only_issues": report_only_issues,
        },
    )
    if stop_after == "03_plot_character_extract":
        return finish_run(args, write_stage_stop_summary(
            paths,
            run_id=run_id,
            stop_after=stop_after,
            run_config=run_config,
            derived_config=derived_config,
            validation_mode=validation_mode,
            metadata=metadata,
            dry_run=args.dry_run,
        ))

    stage_outputs["04_adaptation_direction"] = call_stage(
        paths,
        stages["04_adaptation_direction"],
        {
            **prompt_context,
            "source_plot_points": stage_outputs["03_plot_character_extract"]["source_plot_points"],
            "character_bible": stage_outputs["03_plot_character_extract"]["character_bible"],
            "source_fact_ledger": stage_outputs["03_plot_character_extract"]["source_fact_ledger"],
            "market_tags": run_config["market_tags"],
        },
        dry_run=args.dry_run,
        llm_script_path=llm_script_path,
        timeout=args.timeout,
        force_reuse=should_force_reuse("04_adaptation_direction", reuse_through),
    )
    validate_stage_output(
        "04_adaptation_direction",
        stage_outputs["04_adaptation_direction"],
        target_episodes=target_episodes,
        paths=paths,
        artifact_id="04_adaptation_direction",
        stage_context={
            "source_fact_ledger": stage_outputs["03_plot_character_extract"].get("source_fact_ledger", []),
            "validation_mode": validation_mode,
            "report_only_issues": report_only_issues,
        },
    )
    if stop_after == "04_adaptation_direction":
        return finish_run(args, write_stage_stop_summary(
            paths,
            run_id=run_id,
            stop_after=stop_after,
            run_config=run_config,
            derived_config=derived_config,
            validation_mode=validation_mode,
            metadata=metadata,
            dry_run=args.dry_run,
        ))
    stage_outputs["04a_flashback_screening"] = call_stage(
        paths,
        stages["04a_flashback_screening"],
        {
            **prompt_context,
            "source_text": source.text,
            "chapter_summaries": stage_outputs["01_novel_summary"].get("chapter_summaries", []),
            "source_plot_points": stage_outputs["03_plot_character_extract"]["source_plot_points"],
            "adaptation_direction": stage_outputs["04_adaptation_direction"],
            "market_tags": run_config["market_tags"],
            "source_type": "短篇小说",
            "used_quota": 0,
        },
        dry_run=args.dry_run,
        llm_script_path=llm_script_path,
        timeout=args.timeout,
        force_reuse=should_force_reuse("04a_flashback_screening", reuse_through),
    )
    validate_stage_output(
        "04a_flashback_screening",
        stage_outputs["04a_flashback_screening"],
        target_episodes=target_episodes,
        paths=paths,
        artifact_id="04a_flashback_screening",
        stage_context={"validation_mode": validation_mode, "report_only_issues": report_only_issues},
    )
    if stop_after == "04a_flashback_screening":
        return finish_run(args, write_stage_stop_summary(
            paths,
            run_id=run_id,
            stop_after=stop_after,
            run_config=run_config,
            derived_config=derived_config,
            validation_mode=validation_mode,
            metadata=metadata,
            dry_run=args.dry_run,
        ))
    canonical_story_lock = build_canonical_story_lock(
        source_plot_points=stage_outputs["03_plot_character_extract"]["source_plot_points"],
        character_bible=stage_outputs["03_plot_character_extract"]["character_bible"],
        novel_summary=stage_outputs["01_novel_summary"],
        adaptation_direction=stage_outputs["04_adaptation_direction"],
        plot_extract=stage_outputs["03_plot_character_extract"],
    )
    write_json(paths.parsed / "04_canonical_story_lock.json", canonical_story_lock)
    stage_outputs["04b_dramatic_release_map"] = run_dramatic_release_stage(
        paths,
        stages["04b_dramatic_release_map"],
        {
            **prompt_context,
            "adaptation_capacity": stage_outputs["02_storyline_understanding"]["adaptation_capacity"],
            "source_fact_ledger": stage_outputs["03_plot_character_extract"]["source_fact_ledger"],
            "adaptation_direction": stage_outputs["04_adaptation_direction"],
            "flashback_screening": stage_outputs["04a_flashback_screening"],
            "canonical_story_lock": canonical_story_lock,
        },
        dry_run=args.dry_run,
        llm_script_path=llm_script_path,
        timeout=args.timeout,
        force_reuse=should_force_reuse("04b_dramatic_release_map", reuse_through),
    )
    validate_stage_output(
        "04b_dramatic_release_map",
        stage_outputs["04b_dramatic_release_map"],
        target_episodes=target_episodes,
        paths=paths,
        artifact_id="04b_dramatic_release_map",
        stage_context={
            "validation_mode": validation_mode,
            "report_only_issues": report_only_issues,
        },
    )
    dramatic_release_audit = dramatic_release.audit_release_map(
        stage_outputs["04b_dramatic_release_map"],
        target_episodes=target_episodes,
        source_fact_ledger=stage_outputs["03_plot_character_extract"].get("source_fact_ledger", []),
        canonical_story_lock=canonical_story_lock,
    )
    write_json(paths.parsed / "04b_dramatic_release_audit.json", dramatic_release_audit)
    if stop_after == "04b_dramatic_release_map":
        return finish_run(args, write_stage_stop_summary(
            paths,
            run_id=run_id,
            stop_after=stop_after,
            run_config=run_config,
            derived_config=derived_config,
            validation_mode=validation_mode,
            metadata=metadata,
            dry_run=args.dry_run,
        ))
    prompt_context = {
        **prompt_context,
        "canonical_story_lock": canonical_story_lock,
        "flashback_screening": stage_outputs["04a_flashback_screening"],
        "dramatic_release_map": stage_outputs["04b_dramatic_release_map"],
    }

    stage05_values = {
        **prompt_context,
        "source_plot_points": stage_outputs["03_plot_character_extract"]["source_plot_points"],
        "character_bible": stage_outputs["03_plot_character_extract"]["character_bible"],
        "source_fact_ledger": stage_outputs["03_plot_character_extract"]["source_fact_ledger"],
        "adaptation_capacity": stage_outputs["02_storyline_understanding"]["adaptation_capacity"],
        "adaptation_direction": stage_outputs["04_adaptation_direction"],
        "canonical_story_lock": canonical_story_lock,
        "flashback_screening": stage_outputs["04a_flashback_screening"],
        "dramatic_release_map": stage_outputs["04b_dramatic_release_map"],
    }
    stage05_force_reuse = should_force_reuse("05_plot_character_adaptation", reuse_through)
    stage_outputs["05_plot_character_adaptation"] = run_plot_character_adaptation_stage(
        paths,
        stages["05_plot_character_adaptation"],
        stage05_values,
        dry_run=args.dry_run,
        llm_script_path=llm_script_path,
        timeout=args.stage_05_timeout,
        force_reuse=stage05_force_reuse,
    )
    validate_stage_output(
        "05_plot_character_adaptation",
        stage_outputs["05_plot_character_adaptation"],
        target_episodes=target_episodes,
        stage_context={
            "derived_config": derived_config,
            "source_fact_ledger": stage_outputs["03_plot_character_extract"].get("source_fact_ledger", []),
            "dramatic_release_map": stage_outputs["04b_dramatic_release_map"],
            "validation_mode": validation_mode,
            "report_only_issues": report_only_issues,
        },
        paths=paths,
        artifact_id="05_plot_character_adaptation",
    )
    event_registry = season_plan_audit.build_event_registry(
        stage_outputs["05_plot_character_adaptation"].get("event_pool", [])
    )
    transaction_schedule = event_transactions.build_transaction_schedule(
        stage_outputs["05_plot_character_adaptation"].get("event_pool", []),
        target_episodes=target_episodes,
        prop_registry=stage_outputs["05_plot_character_adaptation"].get("prop_registry", []),
    )
    if transaction_schedule.get("status") != "PASS":
        _run_stage_semantic_validation(
            stage_context={
                "validation_mode": validation_mode,
                "report_only_issues": report_only_issues,
            },
            paths=paths,
            stage_id="05_plot_character_adaptation",
            artifact_id="05_transaction_schedule",
            check_name="transaction_schedule",
            check_fn=lambda: _require_validation_condition(
                False,
                json.dumps(transaction_schedule.get("findings", []), ensure_ascii=False),
            ),
        )
    write_json(paths.parsed / "05_event_registry.json", event_registry)
    write_json(paths.parsed / "05_transaction_schedule.json", transaction_schedule)
    write_json(
        paths.parsed / "05_prop_registry.json",
        stage_outputs["05_plot_character_adaptation"].get("prop_registry", []),
    )
    write_json(
        paths.parsed / "05_prop_activation_registry.json",
        transaction_schedule.get("prop_activation_registry", []),
    )
    if stop_after == "05_plot_character_adaptation":
        return finish_run(args, write_stage_stop_summary(
            paths,
            run_id=run_id,
            stop_after=stop_after,
            run_config=run_config,
            derived_config=derived_config,
            validation_mode=validation_mode,
            metadata=metadata,
            dry_run=args.dry_run,
        ))

    stage_outputs["06_script_outline_design"] = call_stage(
        paths,
        stages["06_script_outline_design"],
        {
            **prompt_context,
            "macro_arcs": stage_outputs["05_plot_character_adaptation"]["macro_arcs"],
            "event_pool": stage_outputs["05_plot_character_adaptation"]["event_pool"],
            "conflict_engine": stage_outputs["05_plot_character_adaptation"]["conflict_engine"],
            "expanded_character_network": stage_outputs["05_plot_character_adaptation"]["expanded_character_network"],
            "foreshadowing_pool": stage_outputs["05_plot_character_adaptation"]["foreshadowing_pool"],
            "canonical_story_lock": canonical_story_lock,
            "flashback_screening": stage_outputs["04a_flashback_screening"],
            "dramatic_release_map": stage_outputs["04b_dramatic_release_map"],
            "source_fact_ledger": stage_outputs["03_plot_character_extract"].get("source_fact_ledger", []),
            "adaptation_capacity": stage_outputs["02_storyline_understanding"]["adaptation_capacity"],
        },
        dry_run=args.dry_run,
        llm_script_path=llm_script_path,
        timeout=args.timeout,
        force_reuse=should_force_reuse("06_script_outline_design", reuse_through),
    )
    validate_stage_output(
        "06_script_outline_design",
        stage_outputs["06_script_outline_design"],
        target_episodes=target_episodes,
        stage_context={
            "expected_block_count": derived_config["block_count"],
            "validation_mode": validation_mode,
            "report_only_issues": report_only_issues,
        },
        paths=paths,
        artifact_id="06_script_outline_design",
    )
    if stop_after == "06_script_outline_design":
        return finish_run(args, write_stage_stop_summary(
            paths,
            run_id=run_id,
            stop_after=stop_after,
            run_config=run_config,
            derived_config=derived_config,
            validation_mode=validation_mode,
            metadata=metadata,
            dry_run=args.dry_run,
        ))

    episode_planning_values = build_episode_planning_values(
        prompt_context=prompt_context,
        stage_outputs=stage_outputs,
        canonical_story_lock=canonical_story_lock,
        target_episodes=target_episodes,
        transaction_schedule=transaction_schedule,
    )
    planning_target_episodes = generate_episodes if generate_episodes > 0 else target_episodes
    episode_planning_values["planning_target_episodes"] = planning_target_episodes
    write_json(paths.parsed / "07_episode_planning_compact_inputs.json", episode_planning_values)
    write_json(
        paths.parsed / "07_episode_event_schedule.json",
        episode_planning_values.get("episode_event_options", []),
    )
    stage_outputs["07_episode_planning"] = run_episode_planning_stage(
        paths,
        stages["07_episode_planning"],
        episode_planning_values,
        dry_run=args.dry_run,
        llm_script_path=llm_script_path,
        timeout=args.timeout,
        force_reuse=should_force_reuse("07_episode_planning", reuse_through),
    )
    planning_transaction_report = event_transactions.validate_season_plans(
        stage_outputs["07_episode_planning"].get("episode_outlines", []),
        schedule=transaction_schedule,
    )
    write_json(paths.parsed / "07_transaction_ownership_report.json", planning_transaction_report)
    season_audit_report = season_plan_audit.audit_season_plan(
        episode_outlines=stage_outputs["07_episode_planning"].get("episode_outlines", []),
        event_registry=event_registry,
        prop_registry=transaction_schedule.get(
            "prop_activation_registry",
            stage_outputs["05_plot_character_adaptation"].get("prop_registry", []),
        ),
        adaptation_capacity=stage_outputs["02_storyline_understanding"].get("adaptation_capacity", {}),
        target_episodes=target_episodes,
    )
    write_json(paths.parsed / "season_plan_audit.json", season_audit_report)
    write_text(
        paths.parsed / "season_plan_audit.md",
        season_plan_audit.render_audit_markdown(season_audit_report),
    )
    release_preflight_07 = release_preflight.build_release_preflight(
        transaction_schedule=transaction_schedule,
        planning_report=planning_transaction_report,
        season_plan_report=season_audit_report,
    )
    write_json(paths.parsed / "07_release_preflight.json", release_preflight_07)
    write_text(
        paths.parsed / "07_release_preflight.md",
        release_preflight.render_markdown(release_preflight_07),
    )
    if season_audit_report.get("findings"):
        _run_stage_semantic_validation(
            stage_context={
                "validation_mode": validation_mode,
                "report_only_issues": report_only_issues,
            },
            paths=paths,
            stage_id="07_episode_planning",
            artifact_id="07_episode_planning",
            check_name="season_plan_audit",
            check_fn=lambda: _require_validation_condition(False, str(season_audit_report.get("findings", []))),
        )
    validate_stage_output(
        "07_episode_planning",
        stage_outputs["07_episode_planning"],
        target_episodes=planning_target_episodes,
        paths=paths,
        artifact_id="07_episode_planning",
        stage_context={
            "event_pool": stage_outputs["05_plot_character_adaptation"]["event_pool"],
            "foreshadowing_pool": stage_outputs["05_plot_character_adaptation"]["foreshadowing_pool"],
            "canonical_story_lock": canonical_story_lock,
            "allowed_character_names": collect_allowed_character_names(
                canonical_story_lock,
                stage_outputs["05_plot_character_adaptation"].get("expanded_character_network", []),
            ),
            "derived_config": derived_config,
            "flashback_screening": stage_outputs["04a_flashback_screening"],
            "dramatic_release_map": stage_outputs["04b_dramatic_release_map"],
            "source_fact_ledger": stage_outputs["03_plot_character_extract"].get("source_fact_ledger", []),
            "validation_mode": validation_mode,
            "report_only_validation": bool(getattr(args, "report_only_validation", False)),
            "report_only_issues": report_only_issues,
            "expected_block_count": len(
                clip_blocks_for_episode_limit(
                    stage_outputs["06_script_outline_design"].get("longform_blocks", []),
                    planning_target_episodes,
                )
            ),
        },
    )
    episode_outlines = stage_outputs["07_episode_planning"]["episode_outlines"]
    write_json(paths.parsed / "07_episode_outlines.json", episode_outlines)
    preflight_qa_summary = build_qa_summary(
        stage_outputs,
        episode_outlines,
        target_episodes=planning_target_episodes,
        derived_config=derived_config,
        canonical_story_lock=canonical_story_lock,
        validation_mode=validation_mode,
    )
    write_json(paths.parsed / "07_preflight_qa_summary.json", preflight_qa_summary)
    if preflight_qa_summary["overall_status"] != "PASS" and (
        validation_mode == VALIDATION_MODE_STRICT or preflight_qa_summary.get("generation_status") == "BLOCK"
    ):
        raise ValueError(f"07 preflight QA blocked run: {preflight_qa_summary['blocking_issues']}")
    if stop_after == "07_episode_planning":
        return finish_run(args, write_stage_stop_summary(
            paths,
            run_id=run_id,
            stop_after=stop_after,
            run_config=run_config,
            derived_config=derived_config,
            validation_mode=validation_mode,
            metadata=metadata,
            dry_run=args.dry_run,
        ))

    final_scripts: list[dict[str, Any]] = []
    continuity_ledger = continuity_ledger_v2.new_ledger(
        canonical_story_lock=canonical_story_lock,
        prop_registry=transaction_schedule.get("prop_activation_registry", []),
    )
    prompt_metrics: list[dict[str, Any]] = []
    episode_transaction_reports: list[dict[str, Any]] = []
    for episode_index, episode in enumerate(episode_outlines[:generate_episodes]):
        ep_num = int(episode["episode_num"])
        continuity_ledger = continuity_ledger_v2.materialize_prop_registry_for_episode(
            continuity_ledger,
            episode_num=ep_num,
            prop_registry=transaction_schedule.get("prop_activation_registry", []),
        )
        episode_transaction_contract = event_transactions.execution_contract_for_episode(
            transaction_schedule,
            ep_num,
        )
        artifact_id = f"08_script_body_generation_ep{ep_num:03d}"
        output = None
        prechecked_transaction_report: dict[str, Any] | None = None
        max_attempts = 1 if args.dry_run else max(1, args.episode_retries + 1)
        for attempt in range(1, max_attempts + 1):
            try:
                episode_views = episode_generation_context.build_episode_generation_views(
                    episode=episode,
                    episode_index=episode_index,
                    episode_outlines=episode_outlines,
                    ledger=continuity_ledger,
                    source_fact_ledger=stage_outputs["03_plot_character_extract"].get("source_fact_ledger", []),
                    flashback_screening=stage_outputs["04a_flashback_screening"],
                    protagonist_action_boundary=canonical_story_lock.get("protagonist_action_boundary", {}),
                    target_tone=stage_outputs["04_adaptation_direction"].get("target_tone", ""),
                    transaction_contract=episode_transaction_contract,
                    dramatic_release_map=stage_outputs["04b_dramatic_release_map"],
                    source_voice_anchors=canonical_story_lock.get("emotional_debt_chain", []),
                )
                episode_force_reuse = should_force_reuse("08_script_body_generation", reuse_through) or (
                    bool(getattr(args, "force_reuse_existing_episodes", False))
                    and (paths.outputs / f"{artifact_id}.clean.json").exists()
                )
                output = call_stage(
                    paths,
                    stages["08_script_body_generation"],
                    episode_views,
                        dry_run=args.dry_run,
                        llm_script_path=llm_script_path,
                        timeout=args.timeout,
                        artifact_id=artifact_id,
                        force_reuse=episode_force_reuse,
                    )
                prompt_path = paths.prompts / f"{artifact_id}.prompt.md"
                if prompt_path.exists():
                    context_metrics = episode_generation_context.prompt_metrics(episode_views)
                    prompt_metrics.append(
                        {
                            "episode_num": ep_num,
                            **measure_08_prompt_sections(read_text(prompt_path)),
                            **context_metrics,
                        }
                    )
                    write_json(paths.parsed / "08_prompt_metrics.json", prompt_metrics)
                episode_validation_errors: list[dict[str, str]] = []
                validation_steps = [
                    (
                        "stage_output",
                        lambda: validate_stage_output(
                            "08_script_body_generation",
                            output,
                            target_episodes=target_episodes,
                            paths=paths,
                            artifact_id=artifact_id,
                            stage_context={"validation_mode": validation_mode},
                        ),
                    ),
                    (
                        "continuity_update_references",
                        lambda: validators.validate_continuity_update_references(
                            output.get("continuity_update", {}),
                            foreshadowing_pool=stage_outputs["05_plot_character_adaptation"]["foreshadowing_pool"],
                        ),
                    ),
                    (
                        "continuity_fact_alignment",
                        lambda: validators.validate_continuity_facts(output, episode_num=ep_num),
                    ),
                    (
                        "prop_state_continuity",
                        lambda: validators.validate_prop_state_continuity(
                            output,
                            episode_outline=episode,
                            previous_prop_positions=continuity_ledger.get("props", {}),
                        ),
                    ),
                ]
                if not args.dry_run:
                    validation_steps.append(
                        (
                            "final_script_quality",
                            lambda: validators.validate_final_script_quality(
                                output.get("final_script", ""),
                                episode_outline=episode,
                                canonical_story_lock=canonical_story_lock,
                                derived_config=derived_config,
                                stage_output=output,
                            ),
                        )
                    )
                for check_name, check_fn in validation_steps:
                    try:
                        check_fn()
                    except Exception as validation_exc:
                        if not validation_check_is_report_only(
                            check_name,
                            report_only_validation=getattr(args, "report_only_validation", False),
                            validation_mode=validation_mode,
                        ):
                            raise
                        episode_validation_errors.append({"check": check_name, "error": str(validation_exc)})
                candidate_transaction_report = event_transactions.validate_episode_script(
                    output,
                    contract=episode_transaction_contract,
                )
                candidate_transaction_report["findings"].extend(
                    continuity_ledger_v2.delta_operation_findings(
                        continuity_ledger,
                        output=output,
                    )
                )
                candidate_transaction_report["status"] = (
                    "BLOCK"
                    if any(
                        item.get("severity") == "BLOCK"
                        for item in candidate_transaction_report["findings"]
                    )
                    else "PASS"
                )
                if candidate_transaction_report["status"] == "BLOCK" and attempt < max_attempts:
                    raise ValueError(
                        "08 episode transaction validation failed before ledger commit: "
                        + json.dumps(candidate_transaction_report["findings"], ensure_ascii=False)
                    )
                if episode_validation_errors:
                    report_only_issues.append(
                        {
                            "stage": "08_script_body_generation",
                            "artifact_id": artifact_id,
                            "episode_num": ep_num,
                            "attempt": attempt,
                            "errors": episode_validation_errors,
                        }
                    )
                    write_report_only_issue_log(paths, report_only_issues)
                prechecked_transaction_report = candidate_transaction_report
                break
            except Exception as exc:
                if args.dry_run or attempt >= max_attempts:
                    archive_artifact_pipeline_attempt(
                        paths,
                        artifact_id=artifact_id,
                        attempt=attempt,
                        error=str(exc),
                    )
                    write_partial_generation_summary(
                        paths,
                        run_id=run_id,
                        target_episodes=generate_episodes,
                        generated_episodes=[int(item["episode_num"]) for item in final_scripts],
                        current_artifact=artifact_id,
                        failure={"category": "episode_generation", "artifact_id": artifact_id, "error": str(exc)},
                    )
                    raise
                write_json(
                    paths.logs / f"{artifact_id}.retry{attempt}.json",
                    {"attempt": attempt, "max_attempts": max_attempts, "error": str(exc)},
                )
                archive_artifact_pipeline_attempt(
                    paths,
                    artifact_id=artifact_id,
                    attempt=attempt,
                    error=str(exc),
                )
                invalidate_artifact_cache(paths, artifact_id)
        if output is None:
            raise RuntimeError(f"{artifact_id} did not produce output")
        final_scripts.append(
            {
                "episode_num": ep_num,
                "title": episode.get("title"),
                "final_script": output.get("final_script", ""),
                "state_update": output.get("state_update", {}),
                "continuity_update": output.get("continuity_update", {}),
            }
        )
        write_json(
            paths.parsed / f"08_proposed_delta_ep{ep_num:03d}.json",
            continuity_ledger_v2.normalize_episode_delta(output),
        )
        transaction_report = prechecked_transaction_report or event_transactions.validate_episode_script(
            output,
            contract=episode_transaction_contract,
        )
        if prechecked_transaction_report is None:
            transaction_report["findings"].extend(
                continuity_ledger_v2.delta_operation_findings(
                    continuity_ledger,
                    output=output,
                )
            )
            transaction_report["status"] = (
                "BLOCK"
                if any(item.get("severity") == "BLOCK" for item in transaction_report["findings"])
                else "PASS"
            )
        if transaction_report["status"] == "PASS":
            continuity_ledger = continuity_ledger_v2.merge_episode_delta(
                continuity_ledger,
                episode=episode,
                output=output,
            )
            transaction_report["commit_status"] = "COMMITTED"
        elif validation_mode != VALIDATION_MODE_STRICT:
            continuity_ledger = continuity_ledger_v2.record_uncommitted_episode(
                continuity_ledger,
                episode=episode,
                output=output,
                findings=transaction_report["findings"],
                commit_status="STATE_UNCOMMITTED",
            )
            transaction_report["status"] = "STATE_BLOCK"
            transaction_report["commit_status"] = "STATE_UNCOMMITTED"
            report_only_issues.append(
                {
                    "stage": "08_script_body_generation",
                    "artifact_id": artifact_id,
                    "episode_num": ep_num,
                    "errors": [
                        {
                            "check": "episode_transaction_commit",
                            "error": json.dumps(
                                transaction_report["findings"],
                                ensure_ascii=False,
                            ),
                        }
                    ],
                }
            )
            write_report_only_issue_log(paths, report_only_issues)
        else:
            continuity_ledger = continuity_ledger_v2.record_rejected_episode(
                continuity_ledger,
                episode=episode,
                output=output,
                findings=transaction_report["findings"],
            )
            transaction_report["commit_status"] = "REJECTED"
            report_only_issues.append(
                {
                    "stage": "08_script_body_generation",
                    "artifact_id": artifact_id,
                    "episode_num": ep_num,
                    "errors": [
                        {
                            "check": "episode_transaction_commit",
                            "error": json.dumps(
                                transaction_report["findings"],
                                ensure_ascii=False,
                            ),
                        }
                    ],
                }
            )
            write_report_only_issue_log(paths, report_only_issues)
            raise ValueError(
                f"{artifact_id} transaction commit rejected: {transaction_report['findings']}"
            )
        episode_transaction_reports.append(transaction_report)
        write_json(
            paths.parsed / f"08_transaction_report_ep{ep_num:03d}.json",
            transaction_report,
        )
        write_json(paths.parsed / f"08_continuity_ledger_after_ep{ep_num:03d}.json", continuity_ledger)
        write_partial_generation_summary(
            paths,
            run_id=run_id,
            target_episodes=generate_episodes,
            generated_episodes=[int(item["episode_num"]) for item in final_scripts],
            current_artifact=artifact_id,
        )

    compiled = "\n\n".join(item["final_script"] for item in final_scripts).strip()
    if compiled:
        write_text(paths.final / "final_scripts_compiled.md", compiled + "\n")
    qa_summary = build_qa_summary(
        stage_outputs,
        episode_outlines,
        target_episodes=planning_target_episodes,
        derived_config=derived_config,
        final_scripts=None if args.dry_run else final_scripts,
        canonical_story_lock=canonical_story_lock,
        validation_mode=validation_mode,
    )
    if report_only_issues or getattr(args, "report_only_validation", False):
        qa_summary = apply_report_only_issues_to_qa_summary(qa_summary, report_only_issues)
    normalization_reports: list[dict[str, Any]] = []
    for report_path in sorted((paths.parsed / "normalization_reports").glob("*.json")):
        try:
            report = json.loads(read_text(report_path))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(report, dict):
            normalization_reports.append(report)
    final_release_preflight = release_preflight.build_release_preflight(
        transaction_schedule=transaction_schedule,
        planning_report=planning_transaction_report,
        episode_transaction_reports=episode_transaction_reports,
        season_plan_report=season_audit_report,
        normalization_reports=normalization_reports,
        qa_summary=qa_summary,
    )
    qa_summary["release_status"] = final_release_preflight["release_status"]
    qa_summary["release_preflight"] = "release_preflight.json"
    qa_summary["canonical_story_lock"] = {
        "protagonist": canonical_story_lock.get("protagonist"),
        "character_names": canonical_story_lock.get("character_names", []),
    }
    write_json(paths.final / "qa_summary.json", qa_summary)
    write_json(paths.final / "release_preflight.json", final_release_preflight)
    write_text(
        paths.final / "release_preflight.md",
        release_preflight.render_markdown(final_release_preflight),
    )
    if qa_summary["overall_status"] != "PASS" and getattr(args, "report_only_validation", False):
        report_only_issues.append(
            {
                "stage": "final_qa",
                "artifact_id": "qa_summary",
                "errors": [
                        {
                            "check": "final_qa",
                            "error": json.dumps(qa_summary.get("blocking_issues", []), ensure_ascii=False),
                        },
                    ],
            }
        )
        write_report_only_issue_log(paths, report_only_issues)
    elif qa_summary["overall_status"] != "PASS" and report_only_issues and qa_blockers_are_report_only_only(qa_summary):
        write_report_only_issue_log(paths, report_only_issues)
    elif qa_summary["overall_status"] != "PASS":
        raise ValueError(f"final QA blocked run: {qa_summary['blocking_issues']}")
    summary = {
        "run_id": run_id,
        "dry_run": bool(args.dry_run),
        "target_episodes": target_episodes,
        "generated_episodes": [item["episode_num"] for item in final_scripts],
        "run_config": run_config,
        "derived_config": derived_config,
        "validation_mode": validation_mode,
        "canonical_story_lock": "parsed/04_canonical_story_lock.json",
        "config_resolution": "parsed/00a_global_config_resolution.json",
        "source_anchors": "parsed/00_source_anchors.json",
        "event_registry": "parsed/05_event_registry.json",
        "transaction_schedule": "parsed/05_transaction_schedule.json",
        "transaction_ownership_report": "parsed/07_transaction_ownership_report.json",
        "season_plan_audit": "parsed/season_plan_audit.json",
        "continuity_ledger": (
                (
                    f"parsed/08_continuity_ledger_after_ep{final_scripts[-1]['episode_num']:03d}.json"
                    if final_scripts
                    else ""
                )
            ),
        "source_metadata": metadata,
        "qa_summary": "qa_summary.json",
        "release_preflight": "release_preflight.json",
        "release_status": final_release_preflight["release_status"],
        "run_root": str(paths.root),
    }
    write_json(paths.final / "run_summary.json", summary)
    write_json(
        paths.final / "manifest_index.json",
        build_manifest_index(paths, generated_episodes=summary["generated_episodes"]),
    )
    update_run_state(
        paths,
        status="complete",
        generated_episodes=summary["generated_episodes"],
        generated_episode_count=len(summary["generated_episodes"]),
        continuous_completed_prefix=max(summary["generated_episodes"], default=0),
        current_artifact="",
        failure=None,
        completed_at=datetime.now().isoformat(timespec="seconds"),
    )
    return finish_run(args, paths.root)


def build_parser() -> argparse.ArgumentParser:
    """Handle build parser."""
    parser = argparse.ArgumentParser(description="Run the short novel to configured-length short-manga-drama pipeline.")
    parser.add_argument("--novel", required=True, help="Path to source short novel txt/md file.")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    parser.add_argument(
        "--run-config",
        default=None,
        help=(
                "Optional authoritative JSON config. Without it or matching run history, stage 00a recomm"
                "ends config from the whole novel."
            ),
    )
    parser.add_argument("--target-episodes", type=int, default=None, help="Override run_config.target_episodes.")
    parser.add_argument(
        "--episode-duration-seconds",
        type=int,
        default=None,
        help="Override run_config.episode_duration_seconds.",
    )
    parser.add_argument("--rewrite-intensity", choices=sorted(validators.ALLOWED_REWRITE_INTENSITIES), default=None)
    parser.add_argument(
        "--character-background-policy",
        choices=sorted(validators.ALLOWED_CHARACTER_BACKGROUND_POLICIES),
        default=None,
    )
    parser.add_argument("--subplot-policy", choices=sorted(validators.ALLOWED_SUBPLOT_POLICIES), default=None)
    parser.add_argument(
        "--new-character-policy",
        choices=sorted(validators.ALLOWED_NEW_CHARACTER_POLICIES),
        default=None,
    )
    parser.add_argument(
        "--source-preservation-level",
        choices=sorted(validators.ALLOWED_SOURCE_PRESERVATION_LEVELS),
        default=None,
    )
    parser.add_argument(
        "--market-tags",
        default=None,
        help="Comma-separated market tags overriding run_config.market_tags.",
    )
    parser.add_argument("--generate-episodes", type=int, default=1)
    parser.add_argument(
        "--stop-after",
        default=None,
        help="Stop after this stage has produced and validated its artifact.",
    )
    parser.add_argument(
        "--resume-from",
        default=None,
        help="Clear this stage and downstream, then reuse completed upstream artifacts.",
    )
    parser.add_argument(
        "--reuse-through",
        default=None,
        help="Force reuse completed artifacts through this stage and clear downstream artifacts.",
    )
    parser.add_argument(
        "--preserve-downstream",
        action="store_true",
        help="Do not clear downstream artifacts when --reuse-through is used.",
    )
    parser.add_argument(
        "--reuse-existing-episodes",
        action="store_true",
        help="Reuse existing 08 artifacts only when prompt, behavior, runtime and ledger input hashes match.",
    )
    parser.add_argument(
        "--force-reuse-existing-episodes",
        action="store_true",
        help="Unsafely reuse existing 08 clean artifacts without hash validation; a warning is recorded.",
    )
    parser.add_argument(
        "--validation-mode",
        choices=sorted(VALIDATION_MODES),
        default=None,
        help="collect records quality/business issues as warnings; strict restores blocking quality gates.",
    )
    parser.add_argument(
        "--strict-validation",
        action="store_true",
        help="Restore strict quality/business validation gates for release checks.",
    )
    parser.add_argument(
        "--report-only-validation",
        action="store_true",
        help="Compatibility flag; collect mode is now the default.",
    )
    parser.set_defaults(render_clean_md=True)
    parser.add_argument(
        "--render-clean-md",
        dest="render_clean_md",
        action="store_true",
        help="Render outputs/*.clean.json into readable Markdown under readable_outputs/. This is the default.",
    )
    parser.add_argument(
        "--no-render-clean-md",
        dest="render_clean_md",
        action="store_false",
        help="Skip readable Markdown rendering for outputs/*.clean.json.",
    )
    parser.add_argument(
        "--episode-retries",
        type=int,
        default=2,
        help="Retry each real script episode when parsing or quality gates fail.",
    )
    parser.add_argument("--llm-script", default=None)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument(
        "--stage-05-timeout",
        type=int,
        default=900,
        help="Timeout in seconds for each split 05 LLM call.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    """Handle main."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        run_root = run_pipeline(args)
    except Exception as exc:
        if getattr(args, "run_id", None):
            run_root = Path(args.runs_dir) / args.run_id
            if run_root.exists():
                paths = create_run_paths(Path(args.runs_dir), args.run_id)
                state_path = run_root / "run_state.json"
                try:
                    state = json.loads(read_text(state_path)) if state_path.exists() else {}
                except (OSError, json.JSONDecodeError):
                    state = {}
                generated = [int(item) for item in state.get("generated_episodes", []) if str(item).isdigit()]
                write_partial_generation_summary(
                    paths,
                    run_id=args.run_id,
                    target_episodes=int(state.get("target_episodes", getattr(args, "generate_episodes", 0))),
                    generated_episodes=generated,
                    current_artifact=str(state.get("current_artifact", "")),
                    failure={"category": "pipeline", "error": str(exc)},
                )
        if bool(getattr(args, "render_clean_md", False)) and getattr(args, "run_id", None):
            run_root = Path(args.runs_dir) / args.run_id
            if (run_root / "outputs").exists():
                render_clean_md_if_requested(args, run_root)
        raise
    print(f"OK: run artifacts written to {run_root}")


if __name__ == "__main__":
    main()
