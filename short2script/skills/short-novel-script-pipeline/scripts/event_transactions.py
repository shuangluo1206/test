"""Utilities for the short novel script pipeline."""
from __future__ import annotations

import copy
import json
import re
from typing import Any


TRANSACTION_SCHEDULE_SCHEMA_VERSION = "event_transaction_schedule_v2"
MAX_TRANSACTIONS_PER_EPISODE = 3
FUTURE_SEMANTIC_GUARD_HORIZON = 5
HARD_TIME_JUMP_RE = re.compile(
    r"(?:次日|第二天|第三天|数日后|几天后|数周后|几周后|一个月后|多年后|"
    r"连续[一二三四五六七八九十\d]+天)"
)
LEADING_TIME_ANCHOR_RE = re.compile(
    r"^\s*(?:(?:高考|考试|开庭|手术|住院)(?:次日|第[一二三四五六七八九十\d]+天)|"
    r"次日|第二天|第三天|数日后|几天后|数周后|几周后|一个月后|多年后|"
    r"连续[一二三四五六七八九十\d]+天)"
    r"(?:清晨|早上|上午|中午|下午|傍晚|夜里|晚上|深夜)?[\s，,：:、-]*"
)
SOFT_MULTI_STEP_RE = re.compile(
    r"(?:然后|随后|接着|与此同时|并且|继而|之后又)"
)
RESULT_STAGE_CONFLICT_RE = re.compile(
    r"(?:查分|成绩页面|高考成绩).{0,40}"
    r"(?:(?:显示|表明|已|正式|确认|获得).{0,8}(?:被)?(?:北大|大学)?.{0,8}(?:录取|录取资格)"
    r"|(?:北大|大学).{0,8}(?:新生群|报到须知|宿舍安排))"
)
SYNONYM_REPLACEMENTS = (
    ("高考前一天", "高考前夕"),
    ("考试现在开始", "开考"),
    ("开始考试", "开考"),
    ("放进", "放入"),
    ("放到", "放入"),
    ("塞进", "放入"),
    ("摆进", "放入"),
    ("拧紧袋口", "封口"),
    ("打死结", "封口"),
    ("封死", "封口"),
    ("抱在一起", "拥抱"),
    ("没有说话", "沉默"),
    ("不说话", "沉默"),
    ("谁让你往外说", "未经允许泄露"),
    ("谁允许你往外说", "未经允许泄露"),
    ("谁允许你把我的事往外说", "未经允许泄露"),
    ("北京大学", "北大"),
    ("总成绩", "分数"),
    ("总分", "分数"),
    ("最后一科", "全部科目"),
    ("考试结束", "全部科目结束"),
    ("走下台阶", "走出考场"),
    ("推开教学楼玻璃门", "走出考场"),
)
GENERIC_EVIDENCE_TERMS = {
    "人物",
    "主角",
    "反派",
    "动作",
    "结果",
    "画面",
    "出现",
    "完成",
    "看到",
    "显示",
}
EXECUTION_EPISODE_FIELDS = (
    "main_conflict",
    "counterattack",
    "information_gain",
    "state_change",
    "opening_beat",
    "closing_beat",
    "scene_plan",
    "prop_continuity_plan",
    "fact_transitions",
)
CURRENT_TIMELINE_PROCESS_FIELDS = (
    "counterattack",
    "state_change",
    "opening_beat",
    "closing_beat",
)
PAST_TIMELINE_MARKER_RE = re.compile(r"(?:前世|上一世|重生前|闪回|回忆|梦境|倒叙|插叙)")
FLASHBACK_BLOCK_RE = re.compile(
    r"【闪回】.*?(?:【闪出】|【闪回结束】)",
    re.DOTALL,
)
SCENE_HEADING_RE = re.compile(
    r"^\s*\d+\s*-\s*\d+\s+.+?\s+(?:日|夜|傍晚)\s+(?:内|外)\s*$"
)
EDUCATION_STAGE_EVIDENCE_PATTERNS: tuple[tuple[str, int, tuple[tuple[str, str], ...]], ...] = (
    (
        "exam",
        1,
        (
            (r"(?:高考|考试|全部科目|最后一科).{0,16}(?:完成|结束|考完|交卷)", "考试完成"),
            (r"(?:完成|结束|考完|交卷).{0,12}(?:高考|考试|全部科目|最后一科)", "考试完成"),
        ),
    ),
    (
        "score",
        2,
        (
            (r"(?:查分|成绩|分数|位次).{0,16}(?:公布|发布|显示|查到|确认)", "分数位次发布"),
            (r"(?:公布|发布|显示|查到|确认).{0,12}(?:成绩|分数|位次)", "分数位次发布"),
        ),
    ),
    (
        "application",
        3,
        (
            (r"(?:志愿|申请).{0,16}(?:提交成功|已提交|确认提交|锁定)", "志愿申请提交"),
            (r"(?:提交成功|已提交|确认提交).{0,12}(?:志愿|申请)", "志愿申请提交"),
        ),
    ),
    (
        "admission",
        4,
        (
            (r"(?:正式录取|录取结果).{0,12}(?:公布|发布|显示|确认|生效)", "正式录取结果"),
            (r"(?:已被|确认被).{0,16}(?:大学|学院|北大|清华).{0,4}录取", "正式录取结果"),
        ),
    ),
    (
        "notice",
        5,
        (
            (r"(?:收到|拿到|取回|签收|送达|寄到).{0,12}录取通知书", "通知书收到"),
            (r"录取通知书.{0,12}(?:收到|拿到|到手|签收|送达)", "通知书收到"),
        ),
    ),
    (
        "registration",
        6,
        (
            (r"(?:完成|办完|办理).{0,12}(?:报到|注册)", "报到注册完成"),
            (r"(?:加入|进入|收到).{0,8}(?:新生群|报到须知)", "报到材料可用"),
            (r"(?:新生群|报到须知).{0,12}(?:发来|收到|通知)", "报到材料可用"),
            (r"(?:宿舍安排|定宿舍|分配宿舍)", "宿舍安排生效"),
        ),
    ),
)
PROCESS_STAGE_RANKS: dict[str, int] = {
    "not_started": 0,
    "exam_completed": 1,
    "score_rank_published": 2,
    "application_submitted": 3,
    "admission_decision": 4,
    "notice_received": 5,
    "registered": 6,
}
DETECTED_STAGE_TO_PROCESS_STAGE = {
    "exam": "exam_completed",
    "score": "score_rank_published",
    "application": "application_submitted",
    "admission": "admission_decision",
    "notice": "notice_received",
    "registration": "registered",
}


def _normalized_text(value: Any) -> str:
    """Handle normalized text."""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = str(value or "").lower()
    for source, target in SYNONYM_REPLACEMENTS:
        text = text.replace(source, target)
    return re.sub(r"[\s\W_]+", "", text)


def _as_string_list(value: Any) -> list[str]:
    """Handle as string list."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value in (None, ""):
        return []
    return [str(value).strip()]


def _safe_int(value: Any, default: int = 0) -> int:
    """Handle safe int."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _event_window(event: dict[str, Any]) -> tuple[int, int]:
    """Handle event window."""
    window = event.get("episode_window", {})
    if not isinstance(window, dict):
        raise ValueError(f"event {event.get('id')} episode_window must be an object")
    return int(window.get("start", 0)), int(window.get("end", 0))


def _transaction_id(beat: dict[str, Any]) -> str:
    """Handle transaction id."""
    return str(beat.get("child_beat_id", "")).strip()


def _specific_evidence_terms(value: Any) -> list[str]:
    """Handle specific evidence terms."""
    terms = []
    for raw in _as_string_list(value):
        term = _normalized_text(raw)
        if len(term) < 2 or term in GENERIC_EVIDENCE_TERMS:
            continue
        if term not in terms:
            terms.append(term)
    return terms


def _semantic_windows(value: Any, *, radius: int = 6) -> list[str]:
    """Handle semantic windows."""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    lines = [
        line.strip()
        for line in re.split(r"[\r\n]+", str(value or ""))
        if line.strip()
    ]
    if not lines:
        return [str(value or "")]
    windows: list[str] = []
    for index in range(len(lines)):
        windows.append("\n".join(lines[index : index + radius]))
    return windows


def _matched_signature_terms(
    text: Any,
    terms: Any,
    *,
    radius: int = 6,
) -> tuple[list[str], list[str]]:
    """Handle matched signature terms."""
    specific = _specific_evidence_terms(terms)
    if len(specific) < 2:
        return [], specific
    best: list[str] = []
    for window in _semantic_windows(text, radius=radius):
        normalized = _normalized_text(window)
        matched = [term for term in specific if term in normalized]
        if len(matched) > len(best):
            best = matched
    return best, specific


def _signature_matches(text: Any, terms: Any, *, radius: int = 6) -> bool:
    """Handle signature matches."""
    matched, specific = _matched_signature_terms(text, terms, radius=radius)
    required = max(2, (len(specific) * 3 + 4) // 5)
    return len(specific) >= 2 and len(matched) >= required


def _transaction_entities(transaction: dict[str, Any]) -> list[str]:
    """Handle transaction entities."""
    entities: list[str] = []
    for effect in transaction.get("effects", []) or []:
        if not isinstance(effect, dict):
            continue
        for key in ("subject", "object"):
            value = _normalized_text(effect.get(key))
            value = value.replace("自身", "")
            if len(value) >= 2 and value not in entities:
                entities.append(value)
    return entities


def _transaction_semantic_match(
    text: Any,
    transaction: dict[str, Any],
    *,
    radius: int = 4,
    strict_future: bool = False,
) -> list[str]:
    """Handle transaction semantic match."""
    signatures: list[tuple[str, list[str]]] = [
        (
            "completion",
            _specific_evidence_terms(transaction.get("completion_evidence_terms")),
        )
    ]
    for effect in transaction.get("effects", []) or []:
        if isinstance(effect, dict):
            signatures.append(
                (
                    str(effect.get("effect_id", "")),
                    _specific_evidence_terms(effect.get("evidence_terms")),
                )
            )
    entities = _transaction_entities(transaction)
    matched_signatures: list[str] = []
    for window in _semantic_windows(text, radius=radius):
        normalized = _normalized_text(window)
        entity_hits = [entity for entity in entities if entity in normalized]
        if entities and not entity_hits:
            continue
        for signature_id, terms in signatures:
            if signature_id in matched_signatures:
                continue
            matched, specific = _matched_signature_terms(window, terms, radius=radius)
            required = (
                len(specific)
                if strict_future and len(specific) <= 3
                else max(3, (len(specific) * 4 + 4) // 5)
                if strict_future
                else max(2, (len(specific) * 3 + 4) // 5)
            )
            if len(specific) >= 2 and len(matched) >= required:
                matched_signatures.append(signature_id)
    return matched_signatures


def text_matches_transaction(text: Any, transaction: dict[str, Any]) -> bool:
    """Handle text matches transaction."""
    if _transaction_semantic_match(text, transaction):
        return True
    return _signature_matches(text, transaction.get("completion_evidence_terms"))


def _contains_internal_time_jump(action: str) -> bool:
    """Handle contains internal time jump."""
    first_match = HARD_TIME_JUMP_RE.search(action)
    if first_match and first_match.group(0).startswith("连续"):
        return True
    without_leading_anchor = LEADING_TIME_ANCHOR_RE.sub("", action, count=1)
    if without_leading_anchor != action:
        return bool(HARD_TIME_JUMP_RE.search(without_leading_anchor))
    if not first_match:
        return False
    prefix = action[: first_match.start()]
    is_first_clause_anchor = (
        len(prefix) <= 18
        and not re.search(r"[，,。；;！？!?：:]", prefix)
    )
    if is_first_clause_anchor:
        return bool(HARD_TIME_JUMP_RE.search(action[first_match.end() :]))
    return True


def _semantic_units(value: Any) -> list[Any]:
    """Handle semantic units."""
    if isinstance(value, dict):
        return [item for item in value.values()]
    if isinstance(value, list):
        return [item for item in value]
    text = str(value or "")
    if not text:
        return []
    units: list[list[str]] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if SCENE_HEADING_RE.match(line) and current:
            units.append(current)
            current = []
        current.append(line)
    if current:
        units.append(current)
    return ["\n".join(lines) for lines in units] or [text]


def _episode_execution_units(episode: dict[str, Any]) -> list[Any]:
    """Handle episode execution units."""
    units: list[Any] = []
    for field in EXECUTION_EPISODE_FIELDS:
        value = episode.get(field)
        if isinstance(value, list):
            units.extend(item for item in value if item not in (None, "", [], {}))
        elif value not in (None, "", [], {}):
            units.append(value)
    return units


def _episode_current_timeline_process_units(episode: dict[str, Any]) -> list[Any]:
    """Handle episode current timeline process units."""
    units: list[Any] = []
    for field in CURRENT_TIMELINE_PROCESS_FIELDS:
        value = episode.get(field)
        if value not in (None, "", [], {}) and not PAST_TIMELINE_MARKER_RE.search(_normalized_text(value)):
            units.append(value)
    for scene in episode.get("scene_plan", []) or []:
        if not isinstance(scene, dict):
            continue
        scene_text = " ".join(
            [
                str(scene.get("scene_purpose", "")),
                str(scene.get("scene_boundary_reason", "")),
                json.dumps(scene.get("must_include_beats", []), ensure_ascii=False),
            ]
        )
        if PAST_TIMELINE_MARKER_RE.search(_normalized_text(scene_text)):
            continue
        units.append(scene)
    return units


def _strip_flashback_blocks(script: str) -> str:
    """Handle strip flashback blocks."""
    return FLASHBACK_BLOCK_RE.sub("", str(script or ""))


def _education_process_stage(value: Any) -> tuple[int, str, list[str]]:
    """Handle education process stage."""
    normalized = _normalized_text(value).replace("录取线", "分数线")
    highest = 0
    stage_name = ""
    matched_terms: list[str] = []
    for candidate_name, level, patterns in EDUCATION_STAGE_EVIDENCE_PATTERNS:
        candidate_hits = [label for pattern, label in patterns if re.search(pattern, normalized)]
        if candidate_hits and level >= highest:
            highest = level
            stage_name = candidate_name
            matched_terms = candidate_hits
    return highest, stage_name, matched_terms


def _is_education_process_transition(process_id: str, from_stage: str, to_stage: str) -> bool:
    """Handle is education process transition."""
    normalized_id = _normalized_text(process_id)
    return (
        any(marker in normalized_id for marker in ("education", "admission", "gaokao", "高考", "录取"))
        or from_stage in PROCESS_STAGE_RANKS
        or to_stage in PROCESS_STAGE_RANKS
    )


def transaction_atomicity_findings(event_pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle transaction atomicity findings."""
    findings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_effect_ids: set[str] = set()
    seen_signatures: dict[tuple[str, ...], str] = {}
    process_tracks: dict[str, list[dict[str, str]]] = {}

    def register_signature(
        terms: list[str],
        *,
        transaction_id: str,
        path: str,
    ) -> None:
        """Handle register signature."""
        if len(terms) < 2:
            return
        signature = tuple(sorted(terms))
        previous_transaction_id = seen_signatures.get(signature)
        if previous_transaction_id and previous_transaction_id != transaction_id:
            findings.append(
                {
                    "severity": "BLOCK",
                    "check": "transaction_signature_uniqueness",
                    "path": path,
                    "issue": "evidence_signature_reused_by_multiple_transactions",
                    "transaction_id": transaction_id,
                    "previous_transaction_id": previous_transaction_id,
                    "terms": terms,
                }
            )
            return
        seen_signatures[signature] = transaction_id

    for event_index, event in enumerate(event_pool):
        if not isinstance(event, dict):
            continue
        for beat_index, beat in enumerate(event.get("child_beats", []) or []):
            path = f"event_pool[{event_index}].child_beats[{beat_index}]"
            if not isinstance(beat, dict):
                findings.append(
                    {
                        "severity": "BLOCK",
                        "check": "transaction_shape",
                        "path": path,
                        "issue": "transaction_must_be_object",
                    }
                )
                continue
            transaction_id = _transaction_id(beat)
            if transaction_id in seen_ids:
                findings.append(
                    {
                        "severity": "BLOCK",
                        "check": "transaction_id",
                        "path": f"{path}.child_beat_id",
                        "issue": "duplicate_transaction_id",
                        "transaction_id": transaction_id,
                    }
                )
            seen_ids.add(transaction_id)
            action = str(beat.get("action", "")).strip()
            if _contains_internal_time_jump(action):
                findings.append(
                    {
                        "severity": "BLOCK",
                        "check": "transaction_atomicity",
                        "path": f"{path}.action",
                        "issue": "action_contains_explicit_time_jump",
                        "transaction_id": transaction_id,
                        "action": action,
                    }
                )
            elif len(action) > 120 or len(SOFT_MULTI_STEP_RE.findall(action)) >= 3:
                findings.append(
                    {
                        "severity": "WARN",
                        "check": "transaction_atomicity",
                        "path": f"{path}.action",
                        "issue": "action_may_contain_multiple_state_changes",
                        "transaction_id": transaction_id,
                        "action": action,
                    }
                )
            if RESULT_STAGE_CONFLICT_RE.search(action.replace("录取线", "分数线")):
                findings.append(
                    {
                        "severity": "BLOCK",
                        "check": "transaction_process_timeline",
                        "path": f"{path}.action",
                        "issue": "score_release_cannot_directly_equal_admission_result",
                        "transaction_id": transaction_id,
                        "action": action,
                    }
                )
            preconditions = beat.get("preconditions")
            if not isinstance(preconditions, list):
                findings.append(
                    {
                        "severity": "BLOCK",
                        "check": "transaction_preconditions",
                        "path": f"{path}.preconditions",
                        "issue": "preconditions_must_be_list",
                        "transaction_id": transaction_id,
                    }
                )
            effects = beat.get("effects")
            if not isinstance(effects, list) or not effects:
                findings.append(
                    {
                        "severity": "BLOCK",
                        "check": "transaction_effects",
                        "path": f"{path}.effects",
                        "issue": "effects_must_be_non_empty",
                        "transaction_id": transaction_id,
                    }
                )
                effects = []
            effect_ids: set[str] = set()
            for effect_index, effect in enumerate(effects):
                effect_path = f"{path}.effects[{effect_index}]"
                if not isinstance(effect, dict):
                    findings.append(
                        {
                            "severity": "BLOCK",
                            "check": "transaction_effects",
                            "path": effect_path,
                            "issue": "effect_must_be_object",
                            "transaction_id": transaction_id,
                        }
                    )
                    continue
                effect_id = str(effect.get("effect_id", "")).strip()
                if effect_id in seen_effect_ids:
                    findings.append(
                        {
                            "severity": "BLOCK",
                            "check": "transaction_effect_id",
                            "path": f"{effect_path}.effect_id",
                            "issue": "duplicate_effect_id",
                            "effect_id": effect_id,
                        }
                    )
                seen_effect_ids.add(effect_id)
                effect_ids.add(effect_id)
                terms = _specific_evidence_terms(effect.get("evidence_terms"))
                if len(terms) < 2:
                    findings.append(
                        {
                            "severity": "BLOCK",
                            "check": "transaction_effect_signature",
                            "path": f"{effect_path}.evidence_terms",
                            "issue": "effect_requires_at_least_two_specific_evidence_terms",
                            "effect_id": effect_id,
                            "terms": terms,
                        }
                    )
                register_signature(
                    terms,
                    transaction_id=transaction_id,
                    path=f"{effect_path}.evidence_terms",
                )
            forbidden = beat.get("forbidden_early_effects")
            if not isinstance(forbidden, list):
                findings.append(
                    {
                        "severity": "BLOCK",
                        "check": "transaction_forbidden_effects",
                        "path": f"{path}.forbidden_early_effects",
                        "issue": "forbidden_early_effects_must_be_list",
                        "transaction_id": transaction_id,
                    }
                )
                forbidden = []
            forbidden_ids = {
                str(item.get("effect_id", "")).strip()
                for item in forbidden
                if isinstance(item, dict)
            }
            missing_forbidden = sorted(effect_ids - forbidden_ids)
            if missing_forbidden:
                findings.append(
                    {
                        "severity": "BLOCK",
                        "check": "transaction_forbidden_effects",
                        "path": f"{path}.forbidden_early_effects",
                        "issue": "transaction_effects_not_marked_for_early_execution_guard",
                        "transaction_id": transaction_id,
                        "missing_effect_ids": missing_forbidden,
                    }
                )
            completion_terms = _specific_evidence_terms(beat.get("completion_evidence_terms"))
            if len(completion_terms) < 2:
                findings.append(
                    {
                        "severity": "BLOCK",
                        "check": "transaction_completion_signature",
                        "path": f"{path}.completion_evidence_terms",
                        "issue": "completion_requires_at_least_two_specific_evidence_terms",
                        "transaction_id": transaction_id,
                        "terms": completion_terms,
                    }
                )
            register_signature(
                completion_terms,
                transaction_id=transaction_id,
                path=f"{path}.completion_evidence_terms",
            )
            if not isinstance(beat.get("can_share_episode_with_next"), bool):
                findings.append(
                    {
                        "severity": "BLOCK",
                        "check": "transaction_episode_load",
                        "path": f"{path}.can_share_episode_with_next",
                        "issue": "can_share_episode_with_next_must_be_boolean",
                        "transaction_id": transaction_id,
                    }
                )
            transition = beat.get("process_transition")
            if not isinstance(transition, dict):
                findings.append(
                    {
                        "severity": "BLOCK",
                        "check": "transaction_process_transition",
                        "path": f"{path}.process_transition",
                        "issue": "process_transition_must_be_object",
                        "transaction_id": transaction_id,
                    }
                )
                continue
            process_id = str(transition.get("process_id", "")).strip()
            from_stage = str(transition.get("from_stage", "")).strip()
            to_stage = str(transition.get("to_stage", "")).strip()
            populated = [bool(process_id), bool(from_stage), bool(to_stage)]
            if any(populated) and not all(populated):
                findings.append(
                    {
                        "severity": "BLOCK",
                        "check": "transaction_process_transition",
                        "path": f"{path}.process_transition",
                        "issue": "process_transition_must_be_all_empty_or_complete",
                        "transaction_id": transaction_id,
                        "process_transition": transition,
                    }
                )
                continue
            if not all(populated):
                continue
            education_process = _is_education_process_transition(process_id, from_stage, to_stage)
            if education_process and (
                from_stage not in PROCESS_STAGE_RANKS or to_stage not in PROCESS_STAGE_RANKS
            ):
                findings.append(
                    {
                        "severity": "BLOCK",
                        "check": "transaction_process_transition",
                        "path": f"{path}.process_transition",
                        "issue": "unsupported_process_stage",
                        "transaction_id": transaction_id,
                        "process_transition": transition,
                    }
                )
                continue
            if education_process:
                advances_one_stage = (
                    PROCESS_STAGE_RANKS[to_stage] == PROCESS_STAGE_RANKS[from_stage] + 1
                )
            else:
                advances_one_stage = from_stage != to_stage
            if not advances_one_stage:
                findings.append(
                    {
                        "severity": "BLOCK",
                        "check": "transaction_process_transition",
                        "path": f"{path}.process_transition",
                        "issue": "process_transition_must_advance_exactly_one_stage",
                        "transaction_id": transaction_id,
                        "process_id": process_id,
                        "from_stage": from_stage,
                        "to_stage": to_stage,
                    }
                )
                continue
            process_tracks.setdefault(process_id, []).append(
                {
                    "path": f"{path}.process_transition",
                    "transaction_id": transaction_id,
                    "from_stage": from_stage,
                    "to_stage": to_stage,
                }
            )
    for process_id, transitions in process_tracks.items():
        previous_to = ""
        for index, transition in enumerate(transitions):
            if index and transition["from_stage"] != previous_to:
                findings.append(
                    {
                        "severity": "BLOCK",
                        "check": "transaction_process_transition",
                        "path": transition["path"],
                        "issue": "process_transition_chain_is_not_continuous",
                        "process_id": process_id,
                        "transaction_id": transition["transaction_id"],
                        "expected_from_stage": previous_to,
                        "actual_from_stage": transition["from_stage"],
                    }
                )
            previous_to = transition["to_stage"]
    return findings


def _has_forced_boundary_after(
    current: dict[str, Any],
    following: dict[str, Any],
) -> bool:
    """Handle has forced boundary after."""
    following_text = " ".join(
        [
            str(following.get("action", "")),
            json.dumps(following.get("preconditions", []), ensure_ascii=False),
        ]
    )
    return bool(
        LEADING_TIME_ANCHOR_RE.search(str(following.get("action", "")))
        or re.search(r"(?:等待.{0,8}(?:结果|公布|通知)|成绩公布|录取结果公布)", following_text)
    )


def _partition_transactions(
    transactions: list[dict[str, Any]],
    slot_count: int,
) -> list[list[dict[str, Any]]] | None:
    """Handle partition transactions."""
    if slot_count <= 0:
        return None

    def solve(index: int, slots_left: int) -> list[list[dict[str, Any]]] | None:
        """Handle solve."""
        remaining = len(transactions) - index
        if slots_left == 0:
            return [] if remaining == 0 else None
        if remaining < slots_left or remaining > slots_left * MAX_TRANSACTIONS_PER_EPISODE:
            return None
        maximum_size = min(MAX_TRANSACTIONS_PER_EPISODE, remaining)
        ideal_size = min(
            maximum_size,
            max(1, (remaining + slots_left - 1) // slots_left),
        )
        candidate_sizes = sorted(
            range(1, maximum_size + 1),
            key=lambda size: (abs(size - ideal_size), -size),
        )
        for size in candidate_sizes:
            if any(
                _has_forced_boundary_after(
                    transactions[position],
                    transactions[position + 1],
                )
                for position in range(index, index + size - 1)
            ):
                continue
            tail = solve(index + size, slots_left - 1)
            if tail is not None:
                return [[*transactions[index : index + size]], *tail]
        return None

    return solve(0, slot_count)


def _fallback_partition(
    transactions: list[dict[str, Any]],
    slot_count: int,
) -> list[list[dict[str, Any]]]:
    """Handle fallback partition."""
    bundles: list[list[dict[str, Any]]] = [[] for _ in range(max(0, slot_count))]
    if not bundles:
        return bundles
    for index, transaction in enumerate(transactions):
        bundle_index = min(len(bundles) - 1, index * len(bundles) // max(1, len(transactions)))
        bundles[bundle_index].append(transaction)
    return bundles


def effective_prop_registry(
    prop_registry: list[dict[str, Any]],
    *,
    transactions: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Handle effective prop registry."""
    output: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for raw_item in prop_registry or []:
        if not isinstance(raw_item, dict):
            continue
        item = copy.deepcopy(raw_item)
        prop_id = str(item.get("prop_id", "")).strip()
        prop_name = _normalized_text(item.get("prop_name"))
        declared_episode = _safe_int(item.get("created_episode"))
        transaction_episodes: list[int] = []
        transaction_ids: list[str] = []
        if prop_name:
            for transaction_id, transaction in transactions.items():
                searchable = " ".join(
                    [
                        str(transaction.get("action", "")),
                        json.dumps(transaction.get("effects", []), ensure_ascii=False),
                        str(transaction.get("completion_evidence", "")),
                    ]
                )
                if prop_name not in _normalized_text(searchable):
                    continue
                owner_episode = _safe_int(transaction.get("owner_episode"))
                if owner_episode > 0:
                    transaction_episodes.append(owner_episode)
                    transaction_ids.append(transaction_id)
        effective_episode = min(transaction_episodes) if transaction_episodes else declared_episode
        item["declared_created_episode"] = declared_episode
        item["created_episode"] = effective_episode
        item["activation_episode"] = effective_episode
        item["activation_transaction_ids"] = transaction_ids
        if (
            declared_episode > 0
            and effective_episode > 0
            and declared_episode != effective_episode
        ):
            findings.append(
                {
                    "severity": "WARN",
                    "check": "prop_activation_alignment",
                    "issue": "declared_created_episode_differs_from_first_transaction_owner",
                    "prop_id": prop_id,
                    "prop_name": item.get("prop_name", ""),
                    "declared_created_episode": declared_episode,
                    "effective_created_episode": effective_episode,
                    "transaction_ids": transaction_ids,
                }
            )
        output.append(item)
    return output, findings


def build_transaction_schedule(
    event_pool: list[dict[str, Any]],
    *,
    target_episodes: int,
    prop_registry: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Handle build transaction schedule."""
    findings = transaction_atomicity_findings(event_pool)
    transactions: dict[str, dict[str, Any]] = {}
    episode_assignments: dict[int, list[dict[str, Any]]] = {
        episode_num: [] for episode_num in range(1, target_episodes + 1)
    }
    event_records: dict[str, dict[str, Any]] = {}

    ordered_events = sorted(
        [event for event in event_pool if isinstance(event, dict)],
        key=lambda item: (
            _safe_int((item.get("episode_window") or {}).get("start"))
            if isinstance(item.get("episode_window"), dict)
            else 0,
            _safe_int(item.get("id")),
        ),
    )
    for event in ordered_events:
        event_id = str(event.get("id", "")).strip()
        try:
            start, end = _event_window(event)
        except (TypeError, ValueError) as exc:
            findings.append(
                {
                    "severity": "BLOCK",
                    "check": "transaction_schedule",
                    "issue": "invalid_event_window",
                    "event_id": event_id,
                    "error": str(exc),
                }
            )
            continue
        start = max(1, start)
        end = min(target_episodes, end)
        episode_nums = list(range(start, end + 1))
        beats = [
            copy.deepcopy(item)
            for item in event.get("child_beats", []) or []
            if isinstance(item, dict) and _transaction_id(item)
        ]
        bundles = _partition_transactions(beats, len(episode_nums))
        if bundles is None:
            findings.append(
                {
                    "severity": "BLOCK",
                    "check": "transaction_schedule",
                    "issue": "event_transactions_cannot_fit_window_with_semantic_boundaries",
                    "event_id": event_id,
                    "episode_window": {"start": start, "end": end},
                    "transaction_count": len(beats),
                    "slot_count": len(episode_nums),
                    "max_transactions_per_episode": MAX_TRANSACTIONS_PER_EPISODE,
                }
            )
            event_records[event_id] = {
                "event_id": event_id,
                "owner_block_id": event.get("target_block"),
                "episode_window": {"start": start, "end": end},
                "transaction_ids": [_transaction_id(item) for item in beats],
                "diagnostic_fallback": [
                    [_transaction_id(item) for item in bundle]
                    for bundle in _fallback_partition(beats, len(episode_nums))
                ],
            }
            continue
        event_records[event_id] = {
            "event_id": event_id,
            "owner_block_id": event.get("target_block"),
            "episode_window": {"start": start, "end": end},
            "transaction_ids": [_transaction_id(item) for item in beats],
        }
        for episode_num, bundle in zip(episode_nums, bundles):
            if not bundle:
                findings.append(
                    {
                        "severity": "BLOCK",
                        "check": "transaction_schedule",
                        "issue": "episode_has_no_authorized_transaction",
                        "event_id": event_id,
                        "episode_num": episode_num,
                    }
                )
                continue
            assignment = {
                "event_id": event_id,
                "transaction_ids": [_transaction_id(item) for item in bundle],
            }
            episode_assignments[episode_num].append(assignment)
            for beat in bundle:
                transaction_id = _transaction_id(beat)
                transactions[transaction_id] = {
                    **beat,
                    "transaction_id": transaction_id,
                    "owner_event_id": event_id,
                    "owner_block_id": event.get("target_block"),
                    "owner_episode": episode_num,
                }

    episodes: list[dict[str, Any]] = []
    for episode_num in range(1, target_episodes + 1):
        assignments = episode_assignments[episode_num]
        if len(assignments) != 1:
            findings.append(
                {
                    "severity": "BLOCK",
                    "check": "transaction_schedule",
                    "issue": (
                        "episode_has_multiple_owner_events"
                        if len(assignments) > 1
                        else "episode_has_no_owner_event"
                    ),
                    "episode_num": episode_num,
                    "event_ids": [item["event_id"] for item in assignments],
                }
            )
        selected = assignments[0] if assignments else {"event_id": "", "transaction_ids": []}
        episodes.append(
            {
                "episode_num": episode_num,
                "assigned_event_id": (
                        int(selected["event_id"]) if str(selected["event_id"]).isdigit() else selected["event_id"]
                    ),
                "authorized_transaction_ids": selected["transaction_ids"],
            }
        )

    effective_props, prop_findings = effective_prop_registry(
        prop_registry or [],
        transactions=transactions,
    )
    findings.extend(prop_findings)
    return {
        "schema_version": TRANSACTION_SCHEDULE_SCHEMA_VERSION,
        "status": "BLOCK" if any(item.get("severity") == "BLOCK" for item in findings) else "PASS",
        "target_episodes": target_episodes,
        "events": event_records,
        "transactions": transactions,
        "episodes": episodes,
        "prop_activation_registry": effective_props,
        "findings": findings,
    }


def episode_event_options(schedule: dict[str, Any]) -> list[dict[str, Any]]:
    """Handle episode event options."""
    transactions = schedule.get("transactions", {})
    output: list[dict[str, Any]] = []
    for item in schedule.get("episodes", []) or []:
        transaction_ids = list(item.get("authorized_transaction_ids", []) or [])
        output.append(
            {
                "episode_num": item.get("episode_num"),
                "valid_event_ids": (
                    [item.get("assigned_event_id")]
                    if item.get("assigned_event_id") not in (None, "")
                    else []
                ),
                "assigned_event_id": item.get("assigned_event_id"),
                "assigned_child_beat_ids": transaction_ids,
                "authorized_transactions": [
                    copy.deepcopy(transactions[transaction_id])
                    for transaction_id in transaction_ids
                    if transaction_id in transactions
                ],
            }
        )
    return output


def execution_contract_for_episode(
    schedule: dict[str, Any],
    episode_num: int,
) -> dict[str, Any]:
    """Handle execution contract for episode."""
    transactions = schedule.get("transactions", {})
    episode = next(
        (
            item
            for item in schedule.get("episodes", []) or []
            if int(item.get("episode_num", 0)) == int(episode_num)
        ),
        {},
    )
    authorized_ids = list(episode.get("authorized_transaction_ids", []) or [])
    education_stage_before_episode = max(
        (
            PROCESS_STAGE_RANKS.get(
                str((item.get("process_transition") or {}).get("to_stage", "")),
                0,
            )
            for item in transactions.values()
            if _safe_int(item.get("owner_episode")) < int(episode_num)
            and isinstance(item.get("process_transition"), dict)
            and _is_education_process_transition(
                str(item["process_transition"].get("process_id", "")),
                str(item["process_transition"].get("from_stage", "")),
                str(item["process_transition"].get("to_stage", "")),
            )
        ),
        default=0,
    )
    future = [
        copy.deepcopy(item)
        for item in transactions.values()
        if _safe_int(item.get("owner_episode")) > int(episode_num)
    ]
    return {
        "episode_num": episode_num,
        "assigned_event_id": episode.get("assigned_event_id"),
        "authorized_transaction_ids": authorized_ids,
        "authorized_transactions": [
            copy.deepcopy(transactions[transaction_id])
            for transaction_id in authorized_ids
            if transaction_id in transactions
        ],
        "education_stage_before_episode": education_stage_before_episode,
        "forbidden_future_transactions": future,
        "prop_activation_registry": copy.deepcopy(
            schedule.get("prop_activation_registry", [])
        ),
    }


def _future_transaction_leak_findings(
    text: Any,
    *,
    contract: dict[str, Any],
    scope: str,
) -> list[dict[str, Any]]:
    """Handle future transaction leak findings."""
    findings: list[dict[str, Any]] = []
    episode_num = _safe_int(contract.get("episode_num"))
    for transaction in contract.get("forbidden_future_transactions", []) or []:
        owner_episode = _safe_int(transaction.get("owner_episode"))
        if (
            owner_episode <= episode_num
            or owner_episode > episode_num + FUTURE_SEMANTIC_GUARD_HORIZON
        ):
            continue
        matched: list[str] = []
        for unit in _semantic_units(text):
            for signature_id in _transaction_semantic_match(
                unit,
                transaction,
                radius=4,
                strict_future=True,
            ):
                if signature_id not in matched:
                    matched.append(signature_id)
        if matched:
            findings.append(
                {
                    "severity": "BLOCK",
                    "check": "future_transaction_semantic_leak",
                    "scope": scope,
                    "episode_num": contract.get("episode_num"),
                    "transaction_id": transaction.get("transaction_id"),
                    "owner_episode": owner_episode,
                    "matched_signatures": matched,
                    "action": transaction.get("action", ""),
                }
            )
    return findings


def _future_process_stage_findings(
    value: Any,
    *,
    contract: dict[str, Any],
    scope: str,
) -> list[dict[str, Any]]:
    """Handle future process stage findings."""
    all_relevant_transactions = [
        item
        for item in (
            list(contract.get("authorized_transactions", []) or [])
            + list(contract.get("forbidden_future_transactions", []) or [])
        )
        if isinstance(item, dict)
    ]
    typed_transitions = [
        item.get("process_transition")
        for item in all_relevant_transactions
        if isinstance(item.get("process_transition"), dict)
        and str(item["process_transition"].get("process_id", "")).strip()
        and _is_education_process_transition(
            str(item["process_transition"].get("process_id", "")),
            str(item["process_transition"].get("from_stage", "")),
            str(item["process_transition"].get("to_stage", "")),
        )
    ]
    relevant_transactions = [
        item
        for item in all_relevant_transactions
        if (
            isinstance(item.get("process_transition"), dict)
            and str(item["process_transition"].get("process_id", "")).strip()
            and _is_education_process_transition(
                str(item["process_transition"].get("process_id", "")),
                str(item["process_transition"].get("from_stage", "")),
                str(item["process_transition"].get("to_stage", "")),
            )
        )
        or _education_process_stage(
            " ".join(
                [
                    str(item.get("action", "")),
                    json.dumps(item.get("effects", []), ensure_ascii=False),
                ]
            )
        )[0]
    ]
    if not relevant_transactions:
        return []
    if typed_transitions:
        authorized_stage = max(
            int(contract.get("education_stage_before_episode", 0) or 0),
            max(
                (
                    PROCESS_STAGE_RANKS.get(
                        str((item.get("process_transition") or {}).get("to_stage", "")),
                        0,
                    )
                    for item in contract.get("authorized_transactions", []) or []
                    if isinstance(item, dict)
                    and isinstance(item.get("process_transition"), dict)
                    and _is_education_process_transition(
                        str(item["process_transition"].get("process_id", "")),
                        str(item["process_transition"].get("from_stage", "")),
                        str(item["process_transition"].get("to_stage", "")),
                    )
                ),
                default=0,
            ),
        )
    else:
        authorized_stage = max(
            int(contract.get("education_stage_before_episode", 0) or 0),
            max(
                (
                    _education_process_stage(
                        " ".join(
                            [
                                str(item.get("action", "")),
                                json.dumps(item.get("effects", []), ensure_ascii=False),
                            ]
                        )
                    )[0]
                    for item in contract.get("authorized_transactions", []) or []
                    if isinstance(item, dict)
                ),
                default=0,
            ),
        )
    findings: list[dict[str, Any]] = []
    for unit in _semantic_units(value):
        detected_stage, stage_name, matched_terms = _education_process_stage(unit)
        if detected_stage <= authorized_stage:
            continue
        findings.append(
            {
                "severity": "BLOCK",
                "check": "future_process_stage_leak",
                "scope": scope,
                "episode_num": contract.get("episode_num"),
                "process": "education_admission",
                "authorized_stage": authorized_stage,
                "detected_stage": detected_stage,
                "detected_stage_name": stage_name,
                "detected_process_stage": DETECTED_STAGE_TO_PROCESS_STAGE.get(stage_name, ""),
                "matched_terms": matched_terms,
            }
        )
    return findings


def _future_prop_activation_findings(
    value: dict[str, Any],
    *,
    contract: dict[str, Any],
    scope: str,
) -> list[dict[str, Any]]:
    """Handle future prop activation findings."""
    episode_num = _safe_int(contract.get("episode_num"))
    activation_by_id = {
        str(item.get("prop_id", "")).strip(): _safe_int(
            item.get("activation_episode", item.get("created_episode"))
        )
        for item in contract.get("prop_activation_registry", []) or []
        if isinstance(item, dict) and str(item.get("prop_id", "")).strip()
    }
    if scope == "07_episode_plan":
        prop_changes = value.get("prop_continuity_plan", []) or []
        id_key = "prop_id"
    else:
        continuity = value.get("continuity_update", {}) or {}
        prop_changes = continuity.get("prop_state_changes", []) or []
        id_key = "prop_id"
    findings: list[dict[str, Any]] = []
    for item in prop_changes:
        if not isinstance(item, dict):
            continue
        prop_id = str(item.get(id_key, "")).strip()
        activation_episode = activation_by_id.get(prop_id, 0)
        if activation_episode > episode_num:
            findings.append(
                {
                    "severity": "BLOCK",
                    "check": "future_prop_activation",
                    "scope": scope,
                    "episode_num": episode_num,
                    "prop_id": prop_id,
                    "activation_episode": activation_episode,
                }
            )
    return findings


def validate_episode_plan(
    episode: dict[str, Any],
    *,
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Handle validate episode plan."""
    findings: list[dict[str, Any]] = []
    expected_event = contract.get("assigned_event_id")
    actual_events = [str(item).strip() for item in episode.get("event_ids", []) or []]
    expected_events = (
        [str(expected_event).strip()]
        if expected_event not in (None, "")
        else []
    )
    if actual_events != expected_events:
        findings.append(
            {
                "severity": "BLOCK",
                "check": "episode_transaction_owner",
                "episode_num": contract.get("episode_num"),
                "issue": "event_ids_do_not_match_transaction_schedule",
                "expected": expected_events,
                "actual": actual_events,
            }
        )
    expected_ids = list(contract.get("authorized_transaction_ids", []) or [])
    actual_ids = list(episode.get("consumed_child_beat_ids", []) or [])
    if actual_ids != expected_ids:
        findings.append(
            {
                "severity": "BLOCK",
                "check": "episode_transaction_owner",
                "episode_num": contract.get("episode_num"),
                "issue": "consumed_transaction_ids_do_not_match_schedule",
                "expected": expected_ids,
                "actual": actual_ids,
            }
        )
    density = episode.get("target_script_density", {})
    density_beats = density.get("must_cover_beats", []) if isinstance(density, dict) else []
    density_ids = [
        str(item.get("beat_id", "")).strip()
        for item in density_beats
        if isinstance(item, dict)
    ]
    if density_ids != expected_ids:
        findings.append(
            {
                "severity": "BLOCK",
                "check": "episode_transaction_density",
                "episode_num": contract.get("episode_num"),
                "issue": "density_transaction_ids_do_not_match_schedule",
                "expected": expected_ids,
                "actual": density_ids,
            }
        )
    execution_units = _episode_execution_units(episode)
    for unit in execution_units:
        findings.extend(
            _future_transaction_leak_findings(
                unit,
                contract=contract,
                scope="07_episode_plan",
            )
        )
    findings.extend(
        _future_process_stage_findings(
            _episode_current_timeline_process_units(episode),
            contract=contract,
            scope="07_episode_plan",
        )
    )
    findings.extend(
        _future_prop_activation_findings(
            episode,
            contract=contract,
            scope="07_episode_plan",
        )
    )
    return {
        "episode_num": contract.get("episode_num"),
        "status": "BLOCK" if any(item.get("severity") == "BLOCK" for item in findings) else "PASS",
        "authorized_transaction_ids": expected_ids,
        "findings": findings,
    }


def validate_episode_script(
    output: dict[str, Any],
    *,
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Handle validate episode script."""
    findings: list[dict[str, Any]] = []
    script = str(output.get("final_script", ""))
    completed_ids = list(
        ((output.get("continuity_update") or {}).get("completed_beat_ids", []))
    )
    expected_ids = list(contract.get("authorized_transaction_ids", []) or [])
    if completed_ids != expected_ids:
        findings.append(
            {
                "severity": "BLOCK",
                "check": "script_transaction_completion",
                "episode_num": contract.get("episode_num"),
                "issue": "completed_transaction_ids_do_not_match_authorized_transactions",
                "expected": expected_ids,
                "actual": completed_ids,
            }
        )
    expected_effect_ids = [
        str(effect.get("effect_id", "")).strip()
        for transaction in contract.get("authorized_transactions", []) or []
        if isinstance(transaction, dict)
        for effect in transaction.get("effects", []) or []
        if isinstance(effect, dict) and str(effect.get("effect_id", "")).strip()
    ]
    continuity_update = output.get("continuity_update") or {}
    has_explicit_effect_evidence = "completed_effect_evidence" in continuity_update
    evidence_items = list(continuity_update.get("completed_effect_evidence", []) or [])
    actual_effect_ids = [
        str(item.get("effect_id", "")).strip()
        for item in evidence_items
        if isinstance(item, dict)
    ]
    if has_explicit_effect_evidence and actual_effect_ids != expected_effect_ids:
        findings.append(
            {
                "severity": "BLOCK",
                "check": "script_effect_evidence",
                "episode_num": contract.get("episode_num"),
                "issue": "completed_effect_ids_do_not_match_authorized_effects",
                "expected": expected_effect_ids,
                "actual": actual_effect_ids,
            }
        )
    for item in evidence_items:
        if not isinstance(item, dict):
            findings.append(
                {
                    "severity": "BLOCK",
                    "check": "script_effect_evidence",
                    "episode_num": contract.get("episode_num"),
                    "issue": "effect_evidence_item_must_be_object",
                }
            )
            continue
        effect_id = str(item.get("effect_id", "")).strip()
        evidence_span = str(item.get("evidence_span", "")).strip()
        if len(evidence_span) < 4 or evidence_span not in script:
            findings.append(
                {
                    "severity": "BLOCK",
                    "check": "script_effect_evidence",
                    "episode_num": contract.get("episode_num"),
                    "issue": "effect_evidence_span_not_found_verbatim_in_script",
                    "effect_id": effect_id,
                    "evidence_span": evidence_span,
                }
            )
    if not has_explicit_effect_evidence:
        for transaction in contract.get("authorized_transactions", []) or []:
            if _signature_matches(
                script,
                transaction.get("completion_evidence_terms"),
                radius=12,
            ):
                continue
            matched_terms, required_terms = _matched_signature_terms(
                script,
                transaction.get("completion_evidence_terms"),
                radius=12,
            )
            findings.append(
                {
                    "severity": "BLOCK",
                    "check": "script_transaction_completion",
                    "episode_num": contract.get("episode_num"),
                    "issue": "legacy_output_lacks_completion_evidence",
                    "transaction_id": transaction.get("transaction_id"),
                    "matched_terms": matched_terms,
                    "required_terms": required_terms,
                }
            )
    findings.extend(
        _future_transaction_leak_findings(
            script,
            contract=contract,
            scope="08_final_script",
        )
    )
    findings.extend(
        _future_process_stage_findings(
            _strip_flashback_blocks(script),
            contract=contract,
            scope="08_final_script",
        )
    )
    findings.extend(
        _future_prop_activation_findings(
            output,
            contract=contract,
            scope="08_final_script",
        )
    )
    return {
        "episode_num": contract.get("episode_num"),
        "status": "BLOCK" if any(item.get("severity") == "BLOCK" for item in findings) else "PASS",
        "authorized_transaction_ids": expected_ids,
        "findings": findings,
    }


def validate_season_plans(
    episode_outlines: list[dict[str, Any]],
    *,
    schedule: dict[str, Any],
) -> dict[str, Any]:
    """Handle validate season plans."""
    reports = [
        validate_episode_plan(
            episode,
            contract=execution_contract_for_episode(
                schedule,
                int(episode.get("episode_num", 0)),
            ),
        )
        for episode in episode_outlines
        if isinstance(episode, dict)
    ]
    findings = [
        finding
        for report in reports
        for finding in report.get("findings", [])
    ]
    return {
        "status": "BLOCK" if any(item.get("severity") == "BLOCK" for item in findings) else "PASS",
        "episode_reports": reports,
        "finding_count": len(findings),
        "findings": findings,
    }
