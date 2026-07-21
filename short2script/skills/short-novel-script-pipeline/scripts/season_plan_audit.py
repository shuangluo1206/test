"""Utilities for the short novel script pipeline."""
from __future__ import annotations

import copy
import json
import re
from typing import Any


COMPLETED_STATUSES = {"completed", "block_payoff", "已完成", "篇章回收"}
TERMINAL_PROP_WORDS = ("销毁", "丢弃", "作废", "退出", "丢失", "冲走")
PAYOFF_MARKERS = (
    "完成目标",
    "完成全部",
    "获得",
    "保住",
    "化解",
    "击退",
    "锁定",
    "通过",
    "到手",
    "脱离",
    "失去",
    "丧失",
    "撤退",
    "败退",
    "公开认错",
    "反击成功",
    "可见胜利",
    "可见受挫",
    "损失",
)
PAYOFF_LEVEL_MARKERS = ("兑现", "回收", "高潮", "胜利", "受挫", "payoff", "climax")
PAYOFF_LEVEL_EXCLUSIONS = ("无兑现", "未兑现", "无回收", "未回收")
FINAL_CLIMAX_MARKERS = ("终局", "最终高潮", "终极高潮", "final_climax")
LOCAL_PROP_ID_RE = re.compile(r"^PROP_EP(?P<episode>\d{1,3})_(?P<index>\d{2})$")
FORESHADOWING_PROGRESS_MARKERS = ("升级", "递进", "回收", "兑现", "揭示", "暴露", "escalation", "payoff")


def build_event_registry(event_pool: list[dict[str, Any]]) -> dict[str, Any]:
    """Handle build event registry."""
    events: dict[str, Any] = {}
    child_beats: dict[str, Any] = {}
    for event in event_pool:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id", "")).strip()
        if not event_id:
            continue
        events[event_id] = {
            "event_id": event_id,
            "owner_block_id": event.get("target_block"),
            "episode_window": copy.deepcopy(event.get("episode_window", {})),
            "source_fact_ids": copy.deepcopy(event.get("source_fact_ids", [])),
            "child_beat_ids": [],
        }
        for beat in event.get("child_beats", []) or []:
            if not isinstance(beat, dict):
                continue
            beat_id = str(beat.get("child_beat_id", "")).strip()
            if not beat_id:
                continue
            events[event_id]["child_beat_ids"].append(beat_id)
            child_beats[beat_id] = {
                "child_beat_id": beat_id,
                "owner_event_id": event_id,
                "completion_evidence": beat.get("completion_evidence", ""),
            }
    return {"events": events, "child_beats": child_beats}


def apply_local_consumption_status(
    episode_outlines: list[dict[str, Any]],
    *,
    event_registry: dict[str, Any],
) -> list[dict[str, Any]]:
    """Handle apply local consumption status."""
    episodes = copy.deepcopy(episode_outlines)
    consumed: set[str] = set()
    events = event_registry.get("events", {})
    for episode in sorted(episodes, key=lambda item: int(item.get("episode_num", 0))):
        new_ids = [str(item) for item in episode.get("consumed_child_beat_ids", []) or [] if str(item) not in consumed]
        consumed.update(new_ids)
        event_ids = [str(item) for item in episode.get("event_ids", []) or []]
        required = {
            beat_id
            for event_id in event_ids
            for beat_id in (events.get(event_id, {}) or {}).get("child_beat_ids", [])
        }
        if required:
            episode["event_consumption_status"] = "completed" if required.issubset(consumed) else "ongoing"
    return episodes


def _normalized_text(value: Any) -> str:
    """Handle normalized text."""
    return re.sub(r"[\s\W_]+", "", str(value or "")).lower()


def _is_visible_payoff(episode: dict[str, Any]) -> bool:
    """Handle is visible payoff."""
    payoff_level = str(episode.get("payoff_level", "")).strip().lower()
    if not any(marker in payoff_level for marker in PAYOFF_LEVEL_EXCLUSIONS) and any(
        marker in payoff_level for marker in PAYOFF_LEVEL_MARKERS
    ):
        return True
    text = " ".join(
        str(episode.get(key, ""))
        for key in ("state_change", "counterattack", "closing_beat", "information_gain")
    )
    return any(marker in text for marker in PAYOFF_MARKERS)


def _is_final_climax(episode: dict[str, Any]) -> bool:
    """Handle is final climax."""
    text = " ".join(
        str(episode.get(key, ""))
        for key in ("payoff_level", "event_role", "state_change", "closing_beat")
    ).lower()
    return any(marker in text for marker in FINAL_CLIMAX_MARKERS)


def _foreshadowing_progresses(episode: dict[str, Any]) -> bool:
    """Handle foreshadowing progresses."""
    text = " ".join(str(episode.get(key, "")) for key in ("event_role", "payoff_level", "information_gain"))
    text = text.replace("无回收", "").replace("未回收", "")
    return any(marker in text for marker in FORESHADOWING_PROGRESS_MARKERS)


def audit_season_plan(
    *,
    episode_outlines: list[dict[str, Any]],
    event_registry: dict[str, Any],
    prop_registry: list[dict[str, Any]] | None = None,
    adaptation_capacity: dict[str, Any] | None = None,
    target_episodes: int,
) -> dict[str, Any]:
    """Handle audit season plan."""
    findings: list[dict[str, Any]] = []
    events = event_registry.get("events", {})
    child_beats = event_registry.get("child_beats", {})
    consumed_beat_episode: dict[str, int] = {}
    completed_event_episode: dict[str, int] = {}
    cumulatively_consumed_beats: set[str] = set()
    fact_status: dict[str, str] = {}
    last_day_index: int | None = None
    prop_state: dict[str, dict[str, Any]] = {
        str(item.get("prop_id")): copy.deepcopy(item)
        for item in prop_registry or []
        if isinstance(item, dict) and str(item.get("prop_id", "")).strip()
    }
    prop_ids = set(prop_state)
    for index, prop in enumerate(prop_registry or []):
        if not isinstance(prop, dict):
            continue
        prop_id = str(prop.get("prop_id", ""))
        for field in ("replaces_prop_id", "parent_container_id"):
            reference = str(prop.get(field, "")).strip()
            if reference and reference not in prop_ids:
                findings.append(
                    {
                        "check": "prop_lineage",
                        "path": f"prop_registry[{index}].{field}",
                        "prop_id": prop_id,
                        "issue": "unknown_prop_reference",
                        "reference": reference,
                    },
                )

    payoff_episodes: list[int] = []
    epilogue_episodes: list[int] = []
    final_climax_episodes: list[int] = []
    setup_streak: list[int] = []
    foreshadowing_first_use: dict[str, int] = {}

    ordered = sorted(episode_outlines, key=lambda item: int(item.get("episode_num", 0)))
    for episode in ordered:
        episode_num = int(episode.get("episode_num", 0))
        block_id = str(episode.get("block_id", ""))
        event_role = str(episode.get("event_role", ""))
        payoff_level = str(episode.get("payoff_level", ""))
        if _is_visible_payoff(episode):
            payoff_episodes.append(episode_num)
            setup_streak = []
        else:
            setup_streak.append(episode_num)
            if len(setup_streak) == 6:
                findings.append(
                    {
                        "check": "payoff_interval",
                        "episode_range": [setup_streak[0], setup_streak[-1]],
                        "issue": "six_consecutive_episodes_without_visible_payoff",
                    },
                )
        if bool(episode.get("is_epilogue")):
            epilogue_episodes.append(episode_num)
        if _is_final_climax(episode):
            final_climax_episodes.append(episode_num)
        current_event_ids = [str(item) for item in episode.get("event_ids", []) or []]
        for event_id_raw in episode.get("event_ids", []) or []:
            event_id = str(event_id_raw)
            event = events.get(event_id)
            if not event:
                findings.append(
                    {
                        "check": "event_reference",
                        "episode_num": episode_num,
                        "event_id": event_id,
                        "issue": "unknown_event_id",
                    },
                )
                continue
            window = event.get("episode_window", {})
            start = int(window.get("start", episode_num)) if isinstance(window, dict) else episode_num
            end = int(window.get("end", episode_num)) if isinstance(window, dict) else episode_num
            if not start <= episode_num <= end:
                findings.append(
                    {
                        "check": "event_window",
                        "episode_num": episode_num,
                        "event_id": event_id,
                        "issue": "event_outside_window",
                        "window": {"start": start, "end": end},
                    },
                )
            if str(event.get("owner_block_id", "")) != block_id:
                findings.append(
                    {
                        "check": "event_owner",
                        "episode_num": episode_num,
                        "event_id": event_id,
                        "issue": "event_crosses_owner_block",
                    },
                )
            if event_id in completed_event_episode:
                findings.append(
                    {
                        "check": "event_completion",
                        "episode_num": episode_num,
                        "event_id": event_id,
                        "issue": "event_referenced_after_local_completion",
                        "first_episode": completed_event_episode[event_id],
                    },
                )

        for beat_id_raw in episode.get("consumed_child_beat_ids", []) or []:
            beat_id = str(beat_id_raw)
            if beat_id not in child_beats:
                findings.append(
                    {
                        "check": "child_beat_reference",
                        "episode_num": episode_num,
                        "child_beat_id": beat_id,
                        "issue": "unknown_child_beat_id",
                    },
                )
            elif beat_id in consumed_beat_episode:
                findings.append(
                    {
                        "check": "child_beat_repeat",
                        "episode_num": episode_num,
                        "child_beat_id": beat_id,
                        "issue": "child_beat_consumed_more_than_once",
                        "first_episode": consumed_beat_episode[beat_id],
                    },
                )
            else:
                consumed_beat_episode[beat_id] = episode_num
                cumulatively_consumed_beats.add(beat_id)

        for event_id in current_event_ids:
            required = set((events.get(event_id, {}) or {}).get("child_beat_ids", []))
            if required and required.issubset(cumulatively_consumed_beats) and event_id not in completed_event_episode:
                completed_event_episode[event_id] = episode_num

        story_time = episode.get("story_time", {})
        if isinstance(story_time, dict) and str(story_time.get("day_index", "")).isdigit():
            day_index = int(story_time["day_index"])
            if last_day_index is not None and day_index < last_day_index:
                findings.append(
                    {
                        "check": "story_time",
                        "episode_num": episode_num,
                        "issue": "story_time_moves_backward",
                        "previous_day_index": last_day_index,
                        "day_index": day_index,
                    },
                )
            last_day_index = day_index

        for foreshadowing_id_raw in episode.get("foreshadowing_ids", []) or []:
            foreshadowing_id = str(foreshadowing_id_raw)
            if foreshadowing_id in foreshadowing_first_use and not _foreshadowing_progresses(episode):
                findings.append(
                    {
                        "check": "foreshadowing_progression",
                        "episode_num": episode_num,
                        "foreshadowing_id": foreshadowing_id,
                        "issue": "foreshadowing_reused_without_escalation_or_payoff",
                        "first_episode": foreshadowing_first_use[foreshadowing_id],
                    }
                )
            foreshadowing_first_use.setdefault(foreshadowing_id, episode_num)

        for transition in episode.get("fact_transitions", []) or []:
            if not isinstance(transition, dict):
                continue
            fact_id = str(transition.get("fact_id", ""))
            reported_from = str(transition.get("from_status", ""))
            known = fact_status.get(fact_id, "unknown")
            if reported_from != known:
                findings.append(
                    {
                        "check": "fact_transition",
                        "episode_num": episode_num,
                        "fact_id": fact_id,
                        "issue": "fact_from_status_mismatch",
                        "expected": known,
                        "reported": reported_from,
                    },
                )
            fact_status[fact_id] = str(transition.get("to_status", ""))

        for plan in episode.get("prop_continuity_plan", []) or []:
            if not isinstance(plan, dict):
                continue
            prop_id = str(plan.get("prop_id", ""))
            previous = prop_state.get(prop_id)
            if not previous:
                local_match = LOCAL_PROP_ID_RE.match(prop_id)
                if local_match:
                    declared_episode = int(local_match.group("episode"))
                    if declared_episode > episode_num:
                        findings.append(
                            {
                                "check": "prop_registry",
                                "episode_num": episode_num,
                                "prop_id": prop_id,
                                "issue": "local_prop_used_before_declared_episode",
                                "declared_episode": declared_episode,
                            }
                        )
                    elif declared_episode < episode_num:
                        findings.append(
                            {
                                "check": "prop_registry",
                                "episode_num": episode_num,
                                "prop_id": prop_id,
                                "issue": "local_prop_missing_first_episode_registration",
                                "declared_episode": declared_episode,
                            }
                        )
                else:
                    findings.append(
                        {
                            "check": "prop_registry",
                            "episode_num": episode_num,
                            "prop_id": prop_id,
                            "issue": "prop_not_declared_in_stage05_registry",
                        },
                    )
            if previous and previous.get("terminal_episode"):
                findings.append(
                    {
                        "check": "prop_lifecycle",
                        "episode_num": episode_num,
                        "prop_id": prop_id,
                        "issue": "terminal_prop_reappears",
                        "terminal_episode": previous["terminal_episode"],
                    },
                )
            end_text = f"{plan.get('end_holder', '')} {plan.get('end_location', '')}"
            prop_state[prop_id] = {
                **(previous or {}),
                "holder": plan.get("end_holder", ""),
                "location": plan.get("end_location", ""),
                "terminal_episode": episode_num if any(word in end_text for word in TERMINAL_PROP_WORDS) else None,
            }

    for previous, current in zip(ordered, ordered[1:]):
        if (
            _normalized_text(previous.get("state_change"))
            and _normalized_text(previous.get("state_change")) == _normalized_text(current.get("state_change"))
        ):
            findings.append(
                {
                    "check": "adjacent_result",
                    "from_episode": previous.get("episode_num"),
                    "to_episode": current.get("episode_num"),
                    "issue": "adjacent_episodes_repeat_state_change",
                },
            )
        if (
            _normalized_text(previous.get("ending_hook"))
            and _normalized_text(previous.get("ending_hook")) == _normalized_text(current.get("ending_hook"))
        ):
            findings.append(
                {
                    "check": "adjacent_hook",
                    "from_episode": previous.get("episode_num"),
                    "to_episode": current.get("episode_num"),
                    "issue": "adjacent_episodes_repeat_hook",
                },
            )

    if len(epilogue_episodes) > 2 or any(item < max(1, target_episodes - 1) for item in epilogue_episodes):
        findings.append(
            {
                "check": "epilogue_budget",
                "issue": "epilogue_outside_last_two_or_over_budget",
                "episodes": epilogue_episodes,
            },
        )
    expected_climax_start = max(1, target_episodes - 2)
    outside_climax = [item for item in final_climax_episodes if item < expected_climax_start]
    if outside_climax:
        findings.append(
            {
                "check": "climax_window",
                "issue": "final_climax_outside_terminal_window",
                "episodes": outside_climax,
                "allowed_start": expected_climax_start,
            },
        )
    covered_through = max((int(item.get("episode_num", 0)) for item in ordered), default=0)
    terminal_window_reached = covered_through >= expected_climax_start
    if terminal_window_reached and not any(item >= expected_climax_start for item in final_climax_episodes):
        findings.append(
            {
                "check": "climax_window",
                "issue": "no_final_climax_in_terminal_window",
                "allowed_start": expected_climax_start,
            },
        )
    if covered_through >= 3 and not any(episode_num <= 3 for episode_num in payoff_episodes):
        findings.append(
            {
                "check": "opening_micro_payoff",
                "issue": "no_visible_payoff_in_first_three_episodes",
                "episode_range": [1, 3],
            }
        )
    if covered_through >= 5 and not any(4 <= episode_num <= 5 for episode_num in payoff_episodes):
        findings.append(
            {
                "check": "opening_micro_payoff",
                "issue": "no_additional_visible_payoff_in_episodes_four_to_five",
                "episode_range": [4, 5],
            }
        )

    capacity = adaptation_capacity or {}
    natural = capacity.get("natural_episode_range", {}) if isinstance(capacity, dict) else {}
    natural_max = (
        (
            (
                int(natural.get("max", target_episodes))
                if isinstance(natural, dict) and str(natural.get("max", "")).isdigit()
                else target_episodes
            )
        )
    )
    if target_episodes > natural_max:
        findings.append(
            {
                "check": "adaptation_capacity",
                "issue": "target_exceeds_natural_capacity",
                "target_episodes": target_episodes,
                "natural_max_episodes": natural_max,
                "gap": target_episodes - natural_max,
            },
        )

    return {
        "status": "WARN" if findings else "PASS",
        "target_episodes": target_episodes,
        "episode_count": len(ordered),
        "covered_through_episode": covered_through,
        "coverage_complete": covered_through >= target_episodes,
        "finding_count": len(findings),
        "findings": findings,
        "event_registry": event_registry,
        "final_fact_status": fact_status,
        "final_prop_state": prop_state,
        "local_event_completion_episode": completed_event_episode,
        "payoff_episodes": payoff_episodes,
        "epilogue_episodes": epilogue_episodes,
        "final_climax_episodes": final_climax_episodes,
    }


def render_audit_markdown(report: dict[str, Any]) -> str:
    """Handle render audit markdown."""
    lines = ["# 全季规划审计", "", f"- 状态：{report.get('status')}", f"- 问题数：{report.get('finding_count', 0)}", ""]
    for index, item in enumerate(report.get("findings", []), start=1):
        lines.append(f"## {index}. {item.get('check', '未分类')} / {item.get('issue', '')}")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(item, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
