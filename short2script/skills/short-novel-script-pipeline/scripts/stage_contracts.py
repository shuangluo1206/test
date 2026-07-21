"""Utilities for the short novel script pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContractRule:
    """Group contract rule behavior."""
    path: str
    keys: tuple[str, ...]
    allow_empty: tuple[str, ...] = ()


ROOT = ""


STAGE_CONTRACTS: dict[str, tuple[ContractRule, ...]] = {
    "00a_global_config": (
        ContractRule(ROOT, ("novel_profile", "recommended_run_config", "recommendation_reasons")),
        ContractRule(
            "novel_profile",
            ("genre", "core_conflict_type", "target_audience", "adaptation_risks"),
        ),
        ContractRule(
            "recommended_run_config",
            (
                "target_episodes",
                "episode_duration_seconds",
                "rewrite_intensity",
                "character_background_policy",
                "subplot_policy",
                "new_character_policy",
                "source_preservation_level",
                "source_boundary_mode",
                "pacing_controls",
                "market_tags",
            ),
        ),
        ContractRule(
            "recommended_run_config.pacing_controls",
            (
                "epilogue_max_episodes",
                "event_reuse_max_episodes",
                "conflict_mode_streak_limit",
                "major_climax_window",
                "cross_block_bridge_max_episodes",
            ),
        ),
        ContractRule("recommendation_reasons[]", ("field", "reason")),
    ),
    "01_novel_summary": (
        ContractRule(
            ROOT,
            (
                "novel_summary",
                "core_hook",
                "emotional_debts",
                "expansion_assets",
                "immutable_elements",
                "potential_subplots",
                "undeveloped_characters",
                "open_foreshadowing",
                "chapter_summaries",
                "key_events",
            ),
        ),
        ContractRule("chapter_summaries[]", ("chapter_id", "title", "summary", "key_events")),
        ContractRule("key_events[]", ("id", "event", "characters", "conflict", "source_hint")),
    ),
    "02_storyline_understanding": (
        ContractRule(
            ROOT,
            (
                "storyline_candidates",
                "selected_storyline",
                "core_conflict",
                "core_hook_structure",
                "story_engine",
                "adaptation_capacity",
            ),
        ),
        ContractRule("storyline_candidates[]", ("id", "storyline", "strength", "risk")),
        ContractRule(
            "story_engine",
            (
                "main_line",
                "subplot_lines",
                "antagonist_line",
                "emotion_line",
                "growth_line",
                "recurring_hook_mechanism",
            ),
        ),
        ContractRule(
            "adaptation_capacity",
            (
                "independent_conflict_unit_count",
                "natural_episode_range",
                "target_episode_gap",
                "expansion_pressure",
                "required_new_engines",
            ),
        ),
        ContractRule("adaptation_capacity.natural_episode_range", ("min", "max")),
    ),
    "03_plot_character_extract": (
        ContractRule(
            ROOT,
            (
                "source_plot_points",
                "character_bible",
                "character_expandability",
                "emotional_debt_chain",
                "character_action_boundaries",
                "source_evidence",
                "source_fact_ledger",
            ),
        ),
        ContractRule(
            "source_plot_points[]",
            ("id", "title", "event", "function", "characters", "source_evidence", "source_fact_ids"),
        ),
        ContractRule(
            "source_fact_ledger[]",
            ("fact_id", "actor", "action", "object", "result", "source_anchor_ids", "certainty", "interpretation_note"),
            allow_empty=("interpretation_note",),
        ),
        ContractRule("character_bible[]", ("name", "role", "relationship", "source_traits", "dramatic_function")),
        ContractRule("character_expandability[]", ("name", "desire", "fear", "weakness", "secret", "expand_space")),
        ContractRule("emotional_debt_chain[]", ("step", "source_fact", "emotion", "downstream_lock")),
        ContractRule("character_action_boundaries[]", ("name", "can_change", "cannot_change", "risk_note")),
        ContractRule("source_evidence[]", ("id", "quote_or_summary", "supports")),
    ),
    "04_adaptation_direction": (
        ContractRule(
            ROOT,
            (
                "adaptation_direction",
                "target_tone",
                "change_principles",
                "must_keep",
                "can_expand",
                "longform_strategy",
                "market_tag_priority",
                "originality_boundary",
                "source_preservation_contract",
                "protagonist_action_boundary",
                "event_release_principles",
                "epilogue_budget",
                "retention_rules",
                "forbidden_changes",
            ),
        ),
        ContractRule("change_principles[]", ("principle", "why", "impact_on_story")),
        ContractRule("market_tag_priority[]", ("tag", "dramatic_action")),
        ContractRule("originality_boundary", ("source_retention_ratio", "original_expansion_ratio", "risk_note")),
        ContractRule(
            "source_preservation_contract",
            ("must_preserve", "must_preserve_fact_ids", "can_expand", "per_episode_check"),
        ),
        ContractRule(
            "protagonist_action_boundary",
            ("allowed", "allowed_active_strategies", "risk_examples", "risk_response"),
        ),
        ContractRule("epilogue_budget", ("max_episodes", "allowed_functions")),
    ),
    "04a_flashback_screening": (
        ContractRule(
            ROOT,
            (
                "flashback_overview",
                "retained_time_deviations",
                "rewrite_time_deviations",
                "deleted_time_deviations",
                "quota_policy",
            ),
        ),
        ContractRule(
            "flashback_overview",
            ("source_type", "genre_tags", "total_time_deviation_count", "s_count", "a_count", "b_count", "c_count"),
        ),
        ContractRule(
            "retained_time_deviations[]",
            (
                "id",
                "grade",
                "position",
                "characters",
                "content_summary",
                "q1_structure_necessity",
                "q2_information_necessity",
                "decision",
                "reason",
                "quota_count",
            ),
        ),
        ContractRule(
            "rewrite_time_deviations[]",
            (
                "id",
                "grade",
                "position",
                "characters",
                "content_summary",
                "q1_structure_necessity",
                "q2_information_necessity",
                "decision",
                "reason",
                "quota_count",
            ),
        ),
        ContractRule(
            "deleted_time_deviations[]",
            (
                "id",
                "grade",
                "position",
                "characters",
                "content_summary",
                "q1_structure_necessity",
                "q2_information_necessity",
                "decision",
                "reason",
                "quota_count",
            ),
        ),
        ContractRule(
            "quota_policy",
            ("used_quota", "new_a_quota_count", "cumulative_a_quota_count", "quota_limit", "remaining_quota"),
        ),
    ),
    "04b_dramatic_release_map": (
        ContractRule(
            ROOT,
            (
                "release_overview",
                "episode_dramatic_targets",
                "capacity_bridge_units",
                "opening_gate",
            ),
        ),
        ContractRule(
            "release_overview",
            (
                "target_episodes",
                "natural_capacity_max",
                "capacity_gap",
                "opening_strategy",
                "process_compression_strategy",
                "expansion_strategy",
            ),
        ),
        ContractRule(
            "episode_dramatic_targets[]",
            (
                "release_id",
                "episode_num",
                "desire",
                "obstacle",
                "choice",
                "immediate_cost",
                "visible_result",
                "hook",
                "confrontation_mode",
                "process_only",
                "source_fact_ids",
                "required_event_function",
                "expansion_engine_id",
            ),
            allow_empty=("expansion_engine_id",),
        ),
        ContractRule(
            "capacity_bridge_units[]",
            (
                "bridge_id",
                "episode_range",
                "new_goal",
                "new_obstacle",
                "new_choice",
                "new_cost",
                "new_result",
                "source_boundary",
            ),
        ),
        ContractRule("capacity_bridge_units[].episode_range", ("start", "end")),
        ContractRule(
            "opening_gate",
            (
                "first_three_live_obstacle_count",
                "first_five_process_only_count",
                "required_early_source_fact_ids",
                "gate_reason",
            ),
        ),
    ),
    "05_plot_character_adaptation": (
        ContractRule(
            ROOT,
            (
                "macro_arcs",
                "event_pool",
                "conflict_engine",
                "expanded_character_network",
                "foreshadowing_pool",
                "prop_registry",
                "mapping_trace",
            ),
        ),
        ContractRule(
            "macro_arcs[]",
            ("arc_id", "title", "episode_range", "dramatic_goal", "pressure_source", "payoff", "source_plot_point_ids"),
        ),
        ContractRule(
            "event_pool[]",
            (
                "id",
                "title",
                "function",
                "source_plot_point_ids",
                "source_fact_ids",
                "dramatic_delta",
                "expansion_type",
                "target_block",
                "episode_window",
                "not_before_episode",
                "not_after_episode",
                "expected_episode_span",
                "importance_level",
                "conflict_mode",
                "pattern_family",
                "source_anchor",
                "delta_from_source",
                "legal_moral_risk",
                "content_sensitivity_risk",
                "dramatic_target_ids",
                "child_beats",
            ),
        ),
        ContractRule(
            "event_pool[].child_beats[]",
            (
                "child_beat_id",
                "preconditions",
                "action",
                "effects",
                "forbidden_early_effects",
                "completion_evidence",
                "completion_evidence_terms",
                "process_transition",
                "can_share_episode_with_next",
            ),
        ),
        ContractRule(
            "event_pool[].child_beats[].process_transition",
            ("process_id", "from_stage", "to_stage"),
            allow_empty=("process_id", "from_stage", "to_stage"),
        ),
        ContractRule(
            "event_pool[].child_beats[].preconditions[]",
            ("state_ref", "expected_state"),
        ),
        ContractRule(
            "event_pool[].child_beats[].effects[]",
            (
                "effect_id",
                "effect_type",
                "subject",
                "object",
                "before",
                "after",
                "evidence_terms",
            ),
        ),
        ContractRule(
            "event_pool[].child_beats[].forbidden_early_effects[]",
            ("effect_id", "reason"),
        ),
        ContractRule("event_pool[].dramatic_delta", ("dimension", "before", "after", "why_not_repetition")),
        ContractRule(
            "conflict_engine",
            ("pressure_templates", "counterattack_templates", "reversal_templates", "anti_monotony_rules"),
        ),
        ContractRule(
            "conflict_engine.pressure_templates[]",
            ("template_id", "template_name", "mode", "applicable_arc_ids", "variant_examples"),
        ),
        ContractRule(
            "conflict_engine.counterattack_templates[]",
            ("template_id", "template_name", "mode", "applicable_arc_ids", "variant_examples"),
        ),
        ContractRule(
            "conflict_engine.reversal_templates[]",
            ("template_id", "template_name", "mode", "applicable_arc_ids", "variant_examples"),
        ),
        ContractRule(
            "expanded_character_network[]",
            ("name", "camp", "function", "relationship_pressure", "secret_chain"),
        ),
        ContractRule("foreshadowing_pool[]", ("id", "setup", "mislead", "payoff", "related_arc")),
        ContractRule(
            "prop_registry[]",
            (
                "prop_id",
                "prop_name",
                "entity_kind",
                "created_episode",
                "activation_episode",
                "initial_state",
                "created_from_event_id",
                "replaces_prop_id",
                "parent_container_id",
                "terminal_states",
            ),
            allow_empty=("created_from_event_id", "replaces_prop_id", "parent_container_id"),
        ),
        ContractRule("prop_registry[].initial_state", ("holder", "location", "status")),
        ContractRule("mapping_trace[]", ("asset_id", "source_plot_point_ids", "change_type", "reason")),
    ),
    "06_script_outline_design": (
        ContractRule(
            ROOT,
            (
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
            ),
        ),
        ContractRule(
            "longform_blocks[]",
            (
                "block_id",
                "phase",
                "title",
                "start_episode",
                "end_episode",
                "episode_count",
                "goal",
                "antagonist",
                "hook",
                "foreshadowing_plan",
                "source_asset_ids",
            ),
        ),
        ContractRule(
            "phase_breakdown.*",
            ("episode_range", "dramatic_goal", "stage_antagonist", "foreshadowing_plan", "hook_strategy"),
        ),
        ContractRule("episode_budget[]", ("phase", "start_episode", "end_episode", "episode_count")),
        ContractRule(
            "event_release_schedule[]",
            ("block_id", "episode_range", "available_event_ids", "reserved_payoff", "forbidden_early_events"),
        ),
        ContractRule("block_event_plan[]", ("block_id", "must_use_event_ids", "conflict_modes", "source_anchor_goal")),
        ContractRule(
            "climax_guardrails",
            ("major_climax_window", "final_climax_not_before_episode", "epilogue_max_episodes"),
        ),
        ContractRule(
            "block_state_plan[]",
            ("block_id", "entry_state", "exit_state", "character_state_curve", "handoff_to_next_block"),
        ),
        ContractRule(
            "adaptation_capacity_warning",
            ("status", "target_episodes", "natural_max_episodes", "gap", "strategy"),
        ),
    ),
    "07_episode_planning": (
        ContractRule(ROOT, ("episode_allocation", "block_plans", "episode_outlines")),
        ContractRule("episode_allocation[]", ("block_id", "start_episode", "end_episode", "episode_count")),
        ContractRule(
            "block_plans[]",
            (
                "block_id",
                "phase",
                "title",
                "start_episode",
                "end_episode",
                "episode_count",
                "goal",
                "antagonist",
                "hook",
                "foreshadowing_plan",
            ),
        ),
        ContractRule(
            "episode_outlines[]",
            (
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
                "consumed_child_beats",
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
            ),
        ),
        ContractRule(
            "episode_outlines[].prop_continuity_plan[]",
            (
                "prop_id",
                "prop_name",
                "start_holder",
                "start_location",
                "end_holder",
                "end_location",
                "transfer_action",
                "completion_evidence",
            ),
        ),
        ContractRule("episode_outlines[].story_time", ("day_index", "time_label", "elapsed_from_previous")),
        ContractRule("episode_outlines[].fact_transitions[]", ("fact_id", "from_status", "to_status", "evidence")),
        ContractRule(
            "episode_outlines[].boundary_check",
            ("risk_level", "protagonist_action", "why_allowed", "mitigation"),
        ),
        ContractRule("episode_outlines[].content_sensitivity_check", ("risk_level", "risk_reason", "mitigation")),
        ContractRule(
            "episode_outlines[].scene_plan[]",
            (
                "scene_no",
                "location",
                "time",
                "space",
                "appearing_character_names",
                "scene_purpose",
                "must_include_beats",
                "scene_boundary_reason",
                "visible_space_tokens",
            ),
        ),
        ContractRule(
            "episode_outlines[].narration_device_plan",
            (
                "planned_os_count",
                "planned_flashback_count",
                "planned_flashback_quota_count",
                "planned_vo_count",
                "reason",
                "visual_replacement_strategy",
                "approved_flashback_time_deviation_ids",
                "approved_os_time_deviation_ids",
                "visualized_time_deviation_ids",
                "deleted_or_rewritten_time_deviation_ids",
            ),
        ),
        ContractRule(
            "episode_outlines[].target_script_density",
            (
                "target_range_chars",
                "minimum_effective_chars",
                "maximum_chars",
                "must_cover_beats",
                "optional_compression_beats",
                "expansion_strategy",
                "scene_char_budgets",
            ),
        ),
        ContractRule(
            "episode_outlines[].target_script_density.must_cover_beats[]",
            ("beat_id",),
        ),
        ContractRule(
            "episode_outlines[].target_script_density.scene_char_budgets[]",
            ("scene_no", "target_chars", "must_cover_beat_ids"),
        ),
    ),
    "08_script_body_generation": (
        ContractRule(ROOT, ("schema_version", "final_script", "state_update", "continuity_update")),
        ContractRule(
            "state_update",
            ("audience_fact_changes", "character_knowledge_changes", "private_fact_changes", "next_episode_bridge"),
            allow_empty=("next_episode_bridge",),
        ),
        ContractRule("state_update.audience_fact_changes[]", ("fact_id", "operation", "detail", "evidence")),
        ContractRule(
            "state_update.character_knowledge_changes[]",
            ("character_name", "fact_id", "operation", "detail", "evidence"),
        ),
        ContractRule("state_update.private_fact_changes[]", ("fact_id", "operation", "detail", "evidence")),
        ContractRule(
            "continuity_update",
            (
                "completed_beat_ids",
                "completed_effect_evidence",
                "foreshadowing_changes",
                "open_thread_changes",
                "prop_state_changes",
                "last_scene_state",
                "scene_boundary_check",
                "narration_device_usage",
            ),
        ),
        ContractRule(
            "continuity_update.completed_effect_evidence[]",
            ("effect_id", "evidence_span"),
        ),
        ContractRule("continuity_update.foreshadowing_changes[]", ("id", "operation", "detail")),
        ContractRule("continuity_update.open_thread_changes[]", ("thread_id", "operation", "detail")),
        ContractRule(
            "continuity_update.prop_state_changes[]",
            ("prop_id", "operation", "holder", "location", "status", "evidence"),
        ),
        ContractRule(
            "continuity_update.last_scene_state",
            ("location", "present_character_names", "visible_result"),
        ),
        ContractRule(
            "continuity_update.scene_boundary_check",
            ("scene_count", "same_setting_split_count", "allowed_same_setting_splits", "merge_note"),
            allow_empty=("merge_note",),
        ),
        ContractRule(
            "continuity_update.narration_device_usage",
            ("os_count", "flashback_count", "vo_count", "replacement_strategy_used"),
        ),
    ),
}


PROJECTION_ROOT_KEYS_BY_PROFILE: dict[str, tuple[str, ...]] = {
    "04b_foundation": ("release_overview", "capacity_bridge_units", "opening_gate"),
    "04b_target_chunk": ("episode_dramatic_targets",),
    "05_foundation": (
        "macro_arcs",
        "conflict_engine",
        "expanded_character_network",
        "foreshadowing_pool",
        "prop_registry",
    ),
    "05_event_chunk": ("event_pool",),
    "07_episode_chunk": ("episode_outlines",),
}


def _projection_rule_map(stage_id: str, profile: str | None) -> dict[str, tuple[str, ...]]:
    """Handle projection rule map."""
    rules = {rule.path: rule.keys for rule in STAGE_CONTRACTS.get(stage_id, ())}
    if profile:
        if profile not in PROJECTION_ROOT_KEYS_BY_PROFILE:
            raise ValueError(f"unknown contract projection profile: {profile}")
        rules[ROOT] = PROJECTION_ROOT_KEYS_BY_PROFILE[profile]
    return rules


def project_contract_data(
    stage_id: str,
    data: dict[str, Any],
    *,
    profile: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Keep declared contract fields and return discarded extras with exact paths."""

    rules = _projection_rule_map(stage_id, profile)
    unmapped: list[dict[str, Any]] = []

    def project(value: Any, *, contract_path: str, display_path: str) -> Any:
        """Handle project."""
        if isinstance(value, dict):
            allowed = set(rules[contract_path]) if contract_path in rules else None
            wildcard_path = f"{contract_path}.*" if contract_path else "*"
            use_wildcard_children = allowed is None and wildcard_path in rules
            projected: dict[Any, Any] = {}
            for raw_key, child in value.items():
                key = str(raw_key)
                child_display_path = f"{display_path}.{key}" if display_path else key
                if allowed is not None and key not in allowed:
                    unmapped.append({"path": child_display_path, "key": key, "value": child})
                    continue
                child_contract_path = (
                    wildcard_path
                    if use_wildcard_children
                    else (f"{contract_path}.{key}" if contract_path else key)
                )
                projected[raw_key] = project(
                    child,
                    contract_path=child_contract_path,
                    display_path=child_display_path,
                )
            return projected
        if isinstance(value, list):
            item_contract_path = f"{contract_path}[]"
            return [
                project(
                    item,
                    contract_path=item_contract_path,
                    display_path=f"{display_path}[{index}]",
                )
                for index, item in enumerate(value)
            ]
        return value

    projected = project(data, contract_path=ROOT, display_path=stage_id)
    return projected, sorted(unmapped, key=lambda item: item["path"])


def validate(
    stage_id: str,
    data: dict[str, Any],
    *,
    profile: str | None = None,
) -> dict[str, Any]:
    """Handle validate."""
    checked_paths: list[str] = []
    errors: list[str] = []
    rules = list(STAGE_CONTRACTS.get(stage_id, ()))
    if profile:
        if profile not in PROJECTION_ROOT_KEYS_BY_PROFILE:
            raise ValueError(f"unknown contract projection profile: {profile}")
        root_keys = PROJECTION_ROOT_KEYS_BY_PROFILE[profile]
        allowed_roots = set(root_keys)
        rules = [ContractRule(ROOT, root_keys)] + [
            rule
            for rule in rules
            if rule.path
            and rule.path.split(".", 1)[0].removesuffix("[]") in allowed_roots
        ]
    for rule in rules:
        for value_path, value in _resolve_path(data, rule.path, stage_id):
            if isinstance(value, _MissingPath):
                errors.append(f"{value_path} missing")
                checked_paths.append(value_path)
                continue
            if not isinstance(value, dict):
                errors.append(f"{value_path} must be an object")
                checked_paths.append(value_path)
                continue
            for key in rule.keys:
                checked_path = f"{value_path}.{key}" if value_path else f"{stage_id}.{key}"
                checked_paths.append(checked_path)
                if _is_missing(value, key, allow_empty=key in rule.allow_empty):
                    errors.append(f"{checked_path} missing")
    return {
        "stage_id": stage_id,
        "contract_profile": profile,
        "status": "FAIL" if errors else "PASS",
        "errors": errors,
        "warnings": [],
        "checked_paths": sorted(set(checked_paths)),
    }


class _MissingPath:
    """Group missing path behavior."""
    pass


def _resolve_path(data: Any, path: str, stage_id: str) -> list[tuple[str, Any]]:
    """Handle resolve path."""
    if not path:
        return [(stage_id, data)]
    current: list[tuple[str, Any]] = [(stage_id, data)]
    for token in path.split("."):
        next_values: list[tuple[str, Any]] = []
        if token == "*":
            for label, value in current:
                if not isinstance(value, dict):
                    next_values.append((f"{label}.*", _MissingPath()))
                    continue
                for key, item in value.items():
                    next_values.append((f"{label}.{key}", item))
            current = next_values
            continue
        if token.endswith("[]"):
            key = token[:-2]
            for label, value in current:
                item_label = f"{label}.{key}"
                if not isinstance(value, dict) or key not in value:
                    next_values.append((item_label, _MissingPath()))
                    continue
                items = value.get(key)
                if not isinstance(items, list):
                    next_values.append((item_label, _MissingPath()))
                    continue
                for index, item in enumerate(items):
                    next_values.append((f"{item_label}[{index}]", item))
            current = next_values
            continue
        for label, value in current:
            item_label = f"{label}.{token}"
            if not isinstance(value, dict) or token not in value:
                next_values.append((item_label, _MissingPath()))
            else:
                next_values.append((item_label, value[token]))
        current = next_values
    return current


def _is_missing(data: dict[str, Any], key: str, *, allow_empty: bool = False) -> bool:
    """Handle is missing."""
    if key not in data:
        return True
    value = data[key]
    return (value is None or value == "") and not allow_empty
