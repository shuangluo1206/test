"""Utilities for the short novel script pipeline."""
from __future__ import annotations

import json
from typing import Any


RELEASE_PREFLIGHT_SCHEMA_VERSION = "release_preflight_v1"
SEMANTIC_NORMALIZER_OPERATIONS = {
    "align_episode_target_script_density_ids",
    "expand_episode_scene_plan_locations_from_visible_space",
    "normalize_event_child_beats",
    "normalize_episode_child_beat_references",
    "normalize_script_scene_cast_from_dialogue_speakers",
    "normalize_script_scene_cast_from_visible_actions",
    "normalize_script_scene_cast_screen_only_mentions",
    "normalize_script_completed_beat_ids_from_execution_sheet",
    "normalize_script_scene_heading_visible_space",
    "repair_event_pool_window_gaps",
    "repair_episode_scene_plan_boundaries",
    "repair_episode_scene_plan_generic_visible_roles",
    "repair_episode_scene_plan_visible_space_tokens",
    "apply_local_event_consumption_status",
}


def build_release_preflight(
    *,
    transaction_schedule: dict[str, Any],
    planning_report: dict[str, Any] | None = None,
    episode_transaction_reports: list[dict[str, Any]] | None = None,
    season_plan_report: dict[str, Any] | None = None,
    normalization_reports: list[dict[str, Any]] | None = None,
    qa_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Handle build release preflight."""
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if transaction_schedule.get("status") != "PASS":
        blockers.append(
            {
                "check": "transaction_schedule",
                "items": transaction_schedule.get("findings", []),
            }
        )
    if planning_report and planning_report.get("status") != "PASS":
        blockers.append(
            {
                "check": "planning_transaction_ownership",
                "items": planning_report.get("findings", []),
            }
        )
    rejected_episode_reports = [
        item
        for item in episode_transaction_reports or []
        if item.get("commit_status") != "COMMITTED"
    ]
    if rejected_episode_reports:
        blockers.append(
            {
                "check": "episode_transaction_commit",
                "items": rejected_episode_reports,
            }
        )
    semantic_normalizations: list[dict[str, Any]] = []
    for report in normalization_reports or []:
        for operation in report.get("operations", []) or []:
            if operation.get("operation") in SEMANTIC_NORMALIZER_OPERATIONS:
                semantic_normalizations.append(
                    {
                        "artifact_id": report.get("artifact_id"),
                        "operation": operation.get("operation"),
                        "changed_paths": operation.get("changed_paths", []),
                    }
                )
    if semantic_normalizations:
        blockers.append(
            {
                "check": "semantic_normalizer_mutation",
                "items": semantic_normalizations,
            }
        )
    if season_plan_report and season_plan_report.get("findings"):
        warnings.append(
            {
                "check": "season_plan_audit",
                "items": season_plan_report.get("findings", []),
            }
        )
    if qa_summary and qa_summary.get("quality_status") == "WARN":
        warnings.append(
            {
                "check": "quality_warnings",
                "items": qa_summary.get("warnings", []),
            }
        )
    return {
        "schema_version": RELEASE_PREFLIGHT_SCHEMA_VERSION,
        "release_status": "BLOCK" if blockers else "PASS",
        "generation_status": (qa_summary or {}).get("generation_status", "NOT_FINAL"),
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "blockers": blockers,
        "warnings": warnings,
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Handle render markdown."""
    lines = [
        "# Full Run 发布前检查",
        "",
        f"- 发布状态：{report.get('release_status')}",
        f"- 结构生成状态：{report.get('generation_status')}",
        f"- 阻断项：{report.get('blocker_count', 0)}",
        f"- 警告项：{report.get('warning_count', 0)}",
        "",
    ]
    for title, items in (
        ("阻断项", report.get("blockers", [])),
        ("警告项", report.get("warnings", [])),
    ):
        lines.append(f"## {title}")
        lines.append("")
        if not items:
            lines.append("- 无")
            lines.append("")
            continue
        for index, item in enumerate(items, start=1):
            lines.append(f"### {index}. {item.get('check', '未分类')}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(item, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
