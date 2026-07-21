"""Utilities for the short novel script pipeline."""
from __future__ import annotations

import re
from typing import Any

import stage_contracts


MIN_NOVEL_CHARS = 7000
MAX_NOVEL_CHARS = 50000
MIN_TARGET_EPISODES = 40
MAX_TARGET_EPISODES = 100
ALLOWED_EPISODE_DURATIONS = {60, 90, 120}
ALLOWED_REWRITE_INTENSITIES = {"light", "balanced", "heavy"}
ALLOWED_CHARACTER_BACKGROUND_POLICIES = {"keep", "minor_adjust", "allow_rewrite"}
ALLOWED_SUBPLOT_POLICIES = {"none", "moderate", "aggressive"}
ALLOWED_NEW_CHARACTER_POLICIES = {"limited", "controlled", "open"}
ALLOWED_SOURCE_PRESERVATION_LEVELS = {"core_hook", "core_plot", "character_strict"}
ALLOWED_SOURCE_BOUNDARY_MODES = {"strict_source_anchor", "balanced_spark", "heavy_rewrite"}
FORBIDDEN_SCRIPT_MARKERS = (
    "[音效]",
    "[镜头]",
    "画面：",
    "镜头拉远",
    "画外音",
    "眼神如刀",
    "如同被雷劈",
    "像被雷劈",
    "气场压住",
    "瞳孔地震",
)
FORBIDDEN_SCRIPT_IDIOM_PATTERNS = (
    (r"闪过一丝[\u4e00-\u9fffA-Za-z0-9]*", "闪过一丝XX"),
    (r"一抹[\u4e00-\u9fffA-Za-z0-9]*", "一抹XX"),
    (r"一股[\u4e00-\u9fffA-Za-z0-9]*", "一股XX"),
    (r"如同.{1,16}一般", "如同XX一般"),
    (r"仿佛.{1,16}一样", "仿佛XX一样"),
    (r"(淡淡|冷声|轻声|漫不经心[地的]?|沉声|低声)道", "冗余对话标签"),
    (
        r"（(?:[^）]*[，、,\s])?(平声|沉声|冷声|轻声|低声|淡淡|漫不经心[地的]?|语气[^）]*|声调[^）]*|音量[^）]*|语速[^）]*|嗓音[^）]*|声音[^）]*)[^）]*）",
        "非可视化声线标签",
    ),
    (r"（\s*VO\s*[，、,][^）]+）", "VO括号只能写VO"),
    (r"话卡在(嗓子|喉咙)里?", "话卡在嗓子里"),
    (r"【字幕：[^】]*[:：][^】]*】", "短信内容误用字幕"),
)
NARRATION_DEVICE_BUDGET_OS_FLASHBACK = 5
ALLOWED_TIME_DEVIATION_GRADES = {"S", "A", "B", "C"}
FRONT_EPISODE_WORD_CAP = 1000
DEFAULT_EPISODE_WORD_CAP = 800
DEFAULT_PACING_CONTROLS = {
    "epilogue_max_episodes": 2,
    "event_reuse_max_episodes": 3,
    "conflict_mode_streak_limit": 2,
    "major_climax_window": "auto",
    "cross_block_bridge_max_episodes": 1,
}
CONTENT_SENSITIVITY_PATTERNS = (
    r"(施暴全过程|侵犯过程|性侵过程|强暴过程|强奸过程)",
    r"(摄像头|监控|录屏|拍下|记录|直播).{0,30}(施暴|侵犯|性侵|强暴|强奸|裸照)",
    r"(施暴|侵犯|性侵|强暴|强奸|裸照).{0,30}(摄像头|监控|录屏|拍下|记录|直播)",
    r"(全村|众人|村民|围观|目睹|踹门).{0,30}(不堪入目|性侵|强暴|强奸|侵犯|施暴|裸照|乱伦)",
    r"(不堪入目|性侵|强暴|强奸|侵犯|施暴|裸照|乱伦).{0,30}(现场|社死|围观|目睹|公开|全村|众人|村民)",
    r"(全网|全村|当众|公开).{0,20}(播放|连播|展示|曝光).{0,30}(监控|视频|录音|聊天记录|病历|医疗记录|隐私|性污名|性侵|强奸|侵犯|裸照)",
    r"(公开处刑|社死围观|全网公开|全村公开).{0,30}(监控|视频|录音|聊天记录|病历|医疗记录|隐私|性污名|性侵|强奸|侵犯|裸照|不堪入目)",
    r"(监控|视频|录音|聊天记录|病历|医疗记录|隐私|性污名|性侵|强奸|侵犯|裸照).{0,30}(公开处刑|社死围观|全网公开|全村公开|当众播放|连播)",
    r"(暴力捂嘴|捂嘴).{0,20}(侵犯|施暴|强暴|强奸|性侵)",
    r"(强暴|强奸|性侵|衣衫不整|扑向床|不堪入目|姑侄相残)",
    r"姑侄乱伦",
)
SCRIPT_SCENE_HEADING_RE = re.compile(
    r"^\s*(?P<episode>\d+)\s*-\s*(?P<scene>\d+)\s+(?P<location>.+?)\s+(?P<time>日|夜|傍晚)\s+(?P<space>内|外)\s*$"
)
SCRIPT_SCENE_HEADING_AUTHORED_RE = re.compile(
    r"^\s*(?P<episode>\d+)\s*-\s*(?P<scene>\d+)\s+(?P<location>.+?)\s+"
    r"(?P<time>日|夜|傍晚)\s+(?P<space>内|外|内外|内转外|外转内)\s*$"
)
SCRIPT_SCENE_HEADING_LIKE_RE = re.compile(r"^\s*\d+\s*-\s*\d+(?:\s|$)")
SCRIPT_SCENE_CAST_RE = re.compile(r"^\s*出场人物\s*[:：]\s*(?P<cast>.+?)\s*$")
DIALOGUE_SPEAKER_RE = re.compile(r"^\s*(?P<speaker>[^△【\s（：:]{1,12})(?:（[^）]*）)?\s*[:：]")
DIALOGUE_WITH_TRIANGLE_RE = re.compile(
    r"^\s*△\s*"
    r"(?!(?:VO同时与画面进行|手机屏幕|屏幕|电脑屏幕|投影屏幕|截图|邮件|通知页面|群聊页面|头像列表))"
    r"(?P<dialogue>[^△【\s（：:]{1,12}（[^）]*）\s*[:：].*)$"
)
BARE_DIALOGUE_RE = re.compile(r"^\s*(?P<speaker>[^△【\s（：:]{1,12})\s*[:：]")
EMPTY_DIALOGUE_RE = re.compile(r"^\s*[^△【\s（：:]{1,12}(?:（[^）]*）)?\s*[:：]\s*$")
ACTION_ONLY_DIALOGUE_RE = re.compile(r"^\s*[^△【\s（：:]{1,12}(?:（[^）]*）)?\s*[:：]\s*（[^）]{1,80}）\s*[。！？…]*\s*$")
FILING_DONE_RE = re.compile(r"((已经|已).{0,8}(交律师备案|完成备案|备案成功|生成备案号)|备案.{0,8}(完成|成功|生成)|备案号.{0,12}(生成|出来|有了))")
FILING_UPLOAD_RE = re.compile(r"(点击上传|文件上传成功|上传成功|上传材料)")
INCOMING_CALL_RE = re.compile(
    r"(?:「(?P<quoted_caller>[^」]{1,30})」\s*来电|(?<!未接)来电(?:显示)?\s*[:：—-]+\s*(?P<dash_caller>[^」\n。；，]+))",
)
MISSED_INCOMING_RE = re.compile(r"未接来电\s*[:：—-]+\s*(?P<caller>[^」\n。；，]+)")
CALL_REJECTED_RE = re.compile(r"(翻扣|不接|未接|未接听|拒接|挂断|按掉|息屏|没有接|无人接听)")
VISIBLE_GENERIC_ROLE_NAMES = ("接线员", "司机", "前台", "秘书", "助理", "保安")
GENERIC_ROLE_LOCATION_SUFFIXES = ("区", "区域", "桌面", "柜台", "台面", "大厅", "门口", "门边", "旁", "处")
SCREEN_TEXT_ACTION_RE = re.compile(r"^△\s*(?:手机屏幕|屏幕|电脑屏幕|投影屏幕|截图|邮件|通知页面|群聊页面|头像列表)")
VISIBLE_ACTION_VERB_RE = re.compile(
    r"(走|站|坐|躺|卧|趴|蹲|倚|靠|睁|闭眼|拿|推|看|拨|拦|进|出|离开|转身|开门|关门|抬|点头|摇头|笑|皱|停|侧身|招手|拉开|接过|递|放|低头|盯|退|后退|端|扫|移动|起身|跟随)"
)
CONCRETE_LOCATION_TOKENS = (
    "办公室",
    "会议室",
    "出租屋",
    "住处",
    "前台",
    "走廊",
    "楼道",
    "工位",
    "街边",
    "咖啡厅",
    "大楼",
    "厂房",
    "仓库",
    "车内",
    "电梯",
    "厨房",
    "卧室",
    "客厅",
)
SCREEN_OR_TEXT_MARKERS = ("屏幕", "截图", "短信", "聊天", "来电", "定位", "导航", "备忘录", "邮件", "显示")
LOCATION_DOCUMENT_OBJECT_SUFFIXES = (
    "合同",
    "平面图",
    "合作协议",
    "协议",
    "文件",
    "资料",
    "图纸",
    "报告",
    "评估书",
    "估值表",
    "门牌",
    "地址",
    "页面",
    "截图",
    "记录",
)
LOCATION_DIRECTION_SUFFIXES = ("方向", "那边", "那头", "那端", "一侧")
SCENE_BOUNDARY_PURPOSE_ALLOWLIST = {"flashback", "intercut", "parallel_action"}
SCENE_BOUNDARY_REASON_MARKERS = (
    "【闪回】",
    "【闪出】",
    "闪回",
    "插叙",
    "并行",
    "另一边",
    "与此同时",
    "同一时间",
    "几分钟后",
    "半小时后",
    "一小时后",
    "当天傍晚",
    "第二天",
    "时间跳",
)
VISIBLE_DOORWAY_EXIT_MARKERS = ("退至门口", "退到门口", "退至门外", "退到门外", "门边", "背对", "靠墙")
EXPLICIT_OFFSCREEN_EXIT_MARKERS = ("离开画面", "走出画面", "离开现场", "不再出镜", "已离开镜头")


def validate_source_metadata(metadata: dict[str, Any]) -> None:
    """Handle validate source metadata."""
    count = int(metadata.get("non_space_chars", 0))
    if count < MIN_NOVEL_CHARS or count > MAX_NOVEL_CHARS:
        path = metadata.get("path", "<unknown>")
        raise ValueError(f"{path} non-space character count must be within 7000-50000, got {count}")


def validate_target_episodes_range(target_episodes: int) -> None:
    """Handle validate target episodes range."""
    if target_episodes < MIN_TARGET_EPISODES or target_episodes > MAX_TARGET_EPISODES:
        raise ValueError(f"target_episodes must be within 40-100, got {target_episodes}")


def expected_block_count_for_target(target_episodes: int) -> int:
    """Handle expected block count for target."""
    validate_target_episodes_range(target_episodes)
    return max(4, min(10, round(target_episodes / 10)))


def validate_run_config(config: dict[str, Any]) -> None:
    """Handle validate run config."""
    validate_target_episodes_range(int(config.get("target_episodes", 0)))
    duration = int(config.get("episode_duration_seconds", 0))
    if duration not in ALLOWED_EPISODE_DURATIONS:
        raise ValueError(f"episode_duration_seconds must be one of {sorted(ALLOWED_EPISODE_DURATIONS)}, got {duration}")
    enum_checks = [
        ("rewrite_intensity", ALLOWED_REWRITE_INTENSITIES),
        ("character_background_policy", ALLOWED_CHARACTER_BACKGROUND_POLICIES),
        ("subplot_policy", ALLOWED_SUBPLOT_POLICIES),
        ("new_character_policy", ALLOWED_NEW_CHARACTER_POLICIES),
        ("source_preservation_level", ALLOWED_SOURCE_PRESERVATION_LEVELS),
        ("source_boundary_mode", ALLOWED_SOURCE_BOUNDARY_MODES),
    ]
    for key, allowed in enum_checks:
        value = config.get(key)
        if value not in allowed:
            raise ValueError(f"{key} must be one of {sorted(allowed)}, got {value}")
    pacing_controls = {**DEFAULT_PACING_CONTROLS, **dict(config.get("pacing_controls") or {})}
    for key in (
        "epilogue_max_episodes",
        "event_reuse_max_episodes",
        "conflict_mode_streak_limit",
        "cross_block_bridge_max_episodes",
    ):
        value = pacing_controls.get(key)
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"pacing_controls.{key} must be a non-negative integer, got {value}")
    if pacing_controls["event_reuse_max_episodes"] < 1:
        raise ValueError("pacing_controls.event_reuse_max_episodes must be at least 1")
    if pacing_controls["conflict_mode_streak_limit"] < 1:
        raise ValueError("pacing_controls.conflict_mode_streak_limit must be at least 1")
    climax_window = pacing_controls.get("major_climax_window")
    if climax_window != "auto":
        low, high = parse_numeric_range(str(climax_window))
        target = int(config["target_episodes"])
        if low < 1 or high > target:
            raise ValueError(
                f"pacing_controls.major_climax_window must fit target_episodes 1-{target}, got {climax_window}",
            )
    market_tags = config.get("market_tags", [])
    if (
        not isinstance(market_tags, list)
        or not market_tags
        or not all(isinstance(item, str)
        and item.strip() for item in market_tags)
    ):
        raise ValueError("market_tags must be a non-empty list of strings")


def parse_numeric_range(value: str) -> tuple[int, int]:
    """Handle parse numeric range."""
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(value))
    if not match:
        raise ValueError(f"range must use MIN-MAX format, got {value}")
    low, high = int(match.group(1)), int(match.group(2))
    if low > high:
        raise ValueError(f"range minimum must be <= maximum, got {value}")
    return low, high


def validate_episode_sequence(episodes: list[dict[str, Any]], *, target_episodes: int) -> None:
    """Handle validate episode sequence."""
    if len(episodes) != target_episodes:
        raise ValueError(f"episode_outlines count must equal target_episodes={target_episodes}, got {len(episodes)}")
    expected = list(range(1, target_episodes + 1))
    actual = [int(item.get("episode_num", -1)) for item in episodes]
    if actual != expected:
        raise ValueError(f"episode_outlines episode_num must be continuous 1..{target_episodes}, got {actual}")


def validate_adapted_plot_points(points: list[dict[str, Any]]) -> None:
    """Handle validate adapted plot points."""
    allowed_new_types = {"new_bridge", "new_expansion"}
    for point in points:
        source_ids = point.get("source_plot_point_ids")
        adaptation_type = point.get("adaptation_type")
        if source_ids:
            continue
        if adaptation_type in allowed_new_types:
            continue
        point_id = point.get("id", "<unknown>")
        raise ValueError(
            (
                f"adapted_plot_point {point_id} must include source_plot_point_ids or adaptation_type new_"
                f"bridge/new_expansion"
            )
        )


def validate_event_pool_trace(events: list[dict[str, Any]]) -> None:
    """Handle validate event pool trace."""
    allowed_new_types = {"new_bridge", "new_expansion"}
    for event in events:
        source_ids = event.get("source_plot_point_ids")
        expansion_type = event.get("expansion_type")
        if source_ids:
            continue
        if expansion_type in allowed_new_types:
            continue
        event_id = event.get("id", "<unknown>")
        raise ValueError(
            f"event_pool item {event_id} must include source_plot_point_ids or expansion_type new_bridge/new_expansion",
        )


def validate_episode_asset_references(
    episodes: list[dict[str, Any]],
    *,
    event_pool: list[dict[str, Any]],
    foreshadowing_pool: list[dict[str, Any]],
) -> None:
    """Handle validate episode asset references."""
    event_ids = {int(item["id"]) for item in event_pool if str(item.get("id", "")).isdigit()}
    foreshadowing_ids = {int(item["id"]) for item in foreshadowing_pool if str(item.get("id", "")).isdigit()}
    for episode in episodes:
        episode_num = episode.get("episode_num", "<unknown>")
        used_events = {int(item) for item in episode.get("event_ids", []) if str(item).isdigit()}
        used_foreshadowing = {int(item) for item in episode.get("foreshadowing_ids", []) if str(item).isdigit()}
        if not used_events:
            raise ValueError(f"episode {episode_num} must include at least one event_id")
        extra_events = sorted(used_events - event_ids)
        if extra_events:
            raise ValueError(f"episode {episode_num} references unknown event_ids: {extra_events}")
        extra_foreshadowing = sorted(used_foreshadowing - foreshadowing_ids)
        if extra_foreshadowing:
            raise ValueError(f"episode {episode_num} references unknown foreshadowing_ids: {extra_foreshadowing}")


def normalize_character_name(name: str) -> str:
    """Handle normalize character name."""
    text = str(name or "").strip()
    return re.sub(r"\s*[\(（\[].*?[\)）\]]\s*$", "", text).strip()


def expand_allowed_character_names(names: list[str]) -> set[str]:
    """Handle expand allowed character names."""
    expanded: set[str] = set()
    for raw_name in names:
        name = normalize_character_name(raw_name)
        if not name:
            continue
        expanded.add(name)
        expanded.update(split_character_group_name(name))
        expanded.update(expand_family_group_aliases(name))
    return expanded


def expand_family_group_aliases(name: str) -> set[str]:
    """Handle expand family group aliases."""
    aliases: set[str] = set()
    if "父母" in name or "爸妈" in name or "爹妈" in name:
        aliases.update({"父亲", "母亲", "爸爸", "妈妈"})
        prefix = re.sub(r"(父母|爸妈|爹妈).*", "", name).strip()
        if prefix:
            aliases.update({f"{prefix}父亲", f"{prefix}母亲", f"{prefix}爸爸", f"{prefix}妈妈"})
    return aliases


def split_character_group_name(name: str) -> list[str]:
    """Handle split character group name."""
    parts = []
    for part in re.split(r"[、,/，和及与&+]+", normalize_character_name(name)):
        alias = part.strip()
        if len(alias) >= 2:
            parts.append(alias)
    return parts


def required_character_name_present(name: str, text: str) -> bool:
    """Handle required character name present."""
    normalized = normalize_character_name(name)
    if not normalized:
        return True
    if normalized in text:
        return True
    aliases = split_character_group_name(normalized)
    return len(aliases) > 1 and all(alias in text for alias in aliases)


def validate_episode_required_names(episodes: list[dict[str, Any]], *, allowed_names: list[str]) -> None:
    """Handle validate episode required names."""
    allowed = expand_allowed_character_names(allowed_names)
    for episode in episodes:
        episode_num = episode.get("episode_num", "<unknown>")
        required_names = episode.get("required_character_names", [])
        if not isinstance(required_names, list) or not required_names:
            raise ValueError(f"episode {episode_num} must include required_character_names")
        unknown = sorted({name for name in required_names if normalize_character_name(name) not in allowed})
        if unknown:
            raise ValueError(f"episode {episode_num} required_character_names not in canonical lock: {unknown}")


def validate_continuity_update_references(update: dict[str, Any], *, foreshadowing_pool: list[dict[str, Any]]) -> None:
    """Handle validate continuity update references."""
    foreshadowing_ids = {int(item["id"]) for item in foreshadowing_pool if str(item.get("id", "")).isdigit()}
    used_ids = {
        int(item["id"])
        for item in update.get("foreshadowing_changes", update.get("foreshadowing_status", []))
        if isinstance(item, dict) and str(item.get("id", "")).isdigit()
    }
    unknown = sorted(used_ids - foreshadowing_ids)
    if unknown:
        raise ValueError(f"continuity_update references unknown foreshadowing id(s): {unknown}")


def validate_episode_delta_operations(stage_output: dict[str, Any]) -> None:
    """Handle validate episode delta operations."""
    allowed = {"add", "update", "resolve", "retire"}
    state = stage_output.get("state_update") or {}
    continuity = stage_output.get("continuity_update") or {}
    collections = (
        ("state_update.audience_fact_changes", state.get("audience_fact_changes", [])),
        ("state_update.character_knowledge_changes", state.get("character_knowledge_changes", [])),
        ("state_update.private_fact_changes", state.get("private_fact_changes", [])),
        ("continuity_update.foreshadowing_changes", continuity.get("foreshadowing_changes", [])),
        ("continuity_update.open_thread_changes", continuity.get("open_thread_changes", [])),
        ("continuity_update.prop_state_changes", continuity.get("prop_state_changes", [])),
    )
    for path, items in collections:
        for index, item in enumerate(items or []):
            if not isinstance(item, dict):
                continue
            operation = str(item.get("operation", ""))
            if operation not in allowed:
                raise ValueError(f"08_script_body_generation.{path}[{index}].operation invalid: {operation}")


def validate_episode_budget(budget: list[dict[str, Any]], *, target_episodes: int) -> None:
    """Handle validate episode budget."""
    total = sum(int(item.get("episode_count", 0)) for item in budget)
    if total != target_episodes:
        raise ValueError(f"episode_budget total must equal target_episodes={target_episodes}, got {total}")


def require_keys(data: dict[str, Any], keys: list[str], *, stage_id: str) -> None:
    """Handle require keys."""
    missing = [key for key in keys if key not in data or data[key] in (None, "", [])]
    if missing:
        raise ValueError(f"{stage_id} missing required key(s): {', '.join(missing)}")


def stage_contract_report(stage_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Handle stage contract report."""
    return stage_contracts.validate(stage_id, data)


def validate_stage_contract(stage_id: str, data: dict[str, Any]) -> None:
    """Handle validate stage contract."""
    report = stage_contract_report(stage_id, data)
    if report["errors"]:
        raise ValueError("; ".join(report["errors"]))


def _raise_semantic_findings(check_name: str, findings: list[dict[str, Any]]) -> None:
    """Handle raise semantic findings."""
    if findings:
        raise ValueError(f"{check_name}: {findings}")


def source_fact_ledger_findings(
    source_fact_ledger: list[dict[str, Any]],
    *,
    source_anchors: list[dict[str, Any]],
    source_plot_points: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Handle source fact ledger findings."""
    findings: list[dict[str, Any]] = []
    anchor_text_by_id = {
        str(item.get("source_anchor_id", "")): str(item.get("text", ""))
        for item in source_anchors
        if isinstance(item, dict) and str(item.get("source_anchor_id", "")).strip()
    }
    fact_ids: set[str] = set()
    for index, fact in enumerate(source_fact_ledger):
        if not isinstance(fact, dict):
            continue
        fact_id = str(fact.get("fact_id", "")).strip()
        if fact_id in fact_ids:
            findings.append(
                {
                    "check": "source_fact_id",
                    "path": f"source_fact_ledger[{index}].fact_id",
                    "issue": "duplicate_fact_id",
                    "fact_id": fact_id,
                },
            )
        fact_ids.add(fact_id)
        certainty = str(fact.get("certainty", "")).strip()
        if certainty not in {"explicit", "inferred", "ambiguous"}:
            findings.append(
                {
                    "check": "source_fact_certainty",
                    "path": f"source_fact_ledger[{index}].certainty",
                    "issue": "invalid_certainty",
                    "value": certainty,
                },
            )
        anchor_ids = [str(item) for item in fact.get("source_anchor_ids", []) or []]
        unknown_anchor_ids = [item for item in anchor_ids if item not in anchor_text_by_id]
        if unknown_anchor_ids:
            findings.append(
                {
                    "check": "source_fact_anchor",
                    "path": f"source_fact_ledger[{index}].source_anchor_ids",
                    "issue": "unknown_source_anchor_ids",
                    "ids": unknown_anchor_ids,
                },
            )
        if certainty == "explicit":
            evidence_text = "".join(anchor_text_by_id.get(item, "") for item in anchor_ids)
            actor = str(fact.get("actor", "")).strip()
            if actor and evidence_text and actor not in evidence_text:
                findings.append(
                    {
                        "check": "source_fact_actor",
                        "path": f"source_fact_ledger[{index}].actor",
                        "issue": "explicit_actor_not_found_in_anchor",
                        "actor": actor,
                        "source_anchor_ids": anchor_ids,
                    },
                )
        elif not str(fact.get("interpretation_note", "")).strip():
            findings.append(
                {
                    "check": "source_fact_interpretation",
                    "path": f"source_fact_ledger[{index}].interpretation_note",
                    "issue": "non_explicit_fact_requires_interpretation_note",
                    "fact_id": fact_id,
                },
            )
        interpretation_note = str(fact.get("interpretation_note", "")).strip()
        corrected_match = re.search(r"(?:实为|实际为|应为|正确(?:理解|地点|动作)?为)([^，。；]{1,24})", interpretation_note)
        if corrected_match:
            corrected_fact = corrected_match.group(1).strip()
            canonical_fact = " ".join(
                str(fact.get(key, "")).strip()
                for key in ("actor", "action", "object", "result")
            )
            if corrected_fact and corrected_fact not in canonical_fact:
                findings.append(
                    {
                        "check": "source_fact_interpretation",
                        "path": f"source_fact_ledger[{index}].interpretation_note",
                        "issue": "interpretation_note_corrects_canonical_fact",
                        "fact_id": fact_id,
                        "corrected_fact": corrected_fact,
                    }
                )

    for index, plot_point in enumerate(source_plot_points or []):
        if not isinstance(plot_point, dict):
            continue
        unknown_fact_ids = [
            str(item)
            for item in plot_point.get("source_fact_ids", []) or []
            if str(item) not in fact_ids
        ]
        if unknown_fact_ids:
            findings.append(
                {
                    "check": "source_plot_point_fact_reference",
                    "path": f"source_plot_points[{index}].source_fact_ids",
                    "issue": "unknown_source_fact_ids",
                    "ids": unknown_fact_ids,
                },
            )
    return findings


def validate_source_fact_ledger_alignment(
    source_fact_ledger: list[dict[str, Any]],
    *,
    source_anchors: list[dict[str, Any]],
    source_plot_points: list[dict[str, Any]] | None = None,
) -> None:
    """Handle validate source fact ledger alignment."""
    _raise_semantic_findings(
        "source_fact_ledger_alignment",
        source_fact_ledger_findings(
            source_fact_ledger,
            source_anchors=source_anchors,
            source_plot_points=source_plot_points,
        ),
    )


def validate_adaptation_capacity(capacity: dict[str, Any], *, target_episodes: int) -> None:
    """Handle validate adaptation capacity."""
    natural = capacity.get("natural_episode_range", {}) if isinstance(capacity, dict) else {}
    try:
        natural_min = int(natural.get("min"))
        natural_max = int(natural.get("max"))
        reported_gap = int(capacity.get("target_episode_gap"))
    except (TypeError, ValueError):
        raise ValueError("adaptation_capacity numeric fields must be integers")
    findings: list[dict[str, Any]] = []
    if natural_min <= 0 or natural_max < natural_min:
        findings.append({"check": "adaptation_capacity", "issue": "invalid_natural_episode_range", "range": natural})
    expected_gap = max(0, target_episodes - natural_max)
    if reported_gap != expected_gap:
        findings.append(
            {
                "check": "adaptation_capacity",
                "issue": "target_episode_gap_mismatch",
                "expected": expected_gap,
                "reported": reported_gap,
            },
        )
    _raise_semantic_findings("adaptation_capacity", findings)


def source_fact_reference_findings(
    items: list[dict[str, Any]],
    *,
    source_fact_ledger: list[dict[str, Any]],
    path_prefix: str,
) -> list[dict[str, Any]]:
    """Handle source fact reference findings."""
    known_fact_ids = {
        str(item.get("fact_id"))
        for item in source_fact_ledger
        if isinstance(item, dict) and str(item.get("fact_id", "")).strip()
    }
    findings: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        unknown = [str(value) for value in item.get("source_fact_ids", []) or [] if str(value) not in known_fact_ids]
        if unknown:
            findings.append(
                {
                    "check": "source_fact_reference",
                    "path": f"{path_prefix}[{index}].source_fact_ids",
                    "issue": "unknown_source_fact_ids",
                    "ids": unknown,
                },
            )
    return findings


def validate_source_fact_references(
    items: list[dict[str, Any]],
    *,
    source_fact_ledger: list[dict[str, Any]],
    path_prefix: str,
) -> None:
    """Handle validate source fact references."""
    _raise_semantic_findings(
        "source_fact_references",
        source_fact_reference_findings(items, source_fact_ledger=source_fact_ledger, path_prefix=path_prefix),
    )


def event_dramatic_delta_findings(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle event dramatic delta findings."""
    findings: list[dict[str, Any]] = []
    allowed_dimensions = {"goal", "resource", "power", "secret", "relationship"}
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        delta = event.get("dramatic_delta", {})
        if not isinstance(delta, dict):
            continue
        dimension = str(delta.get("dimension", "")).strip()
        before = re.sub(r"\s+", "", str(delta.get("before", "")))
        after = re.sub(r"\s+", "", str(delta.get("after", "")))
        if dimension not in allowed_dimensions:
            findings.append(
                {
                    "check": "dramatic_delta",
                    "path": f"event_pool[{index}].dramatic_delta.dimension",
                    "issue": "invalid_dimension",
                    "value": dimension,
                },
            )
        if before and after and before == after:
            findings.append(
                {
                    "check": "dramatic_delta",
                    "path": f"event_pool[{index}].dramatic_delta",
                    "issue": "before_after_unchanged",
                    "event_id": event.get("id"),
                },
            )
    return findings


def validate_event_dramatic_deltas(events: list[dict[str, Any]]) -> None:
    """Handle validate event dramatic deltas."""
    _raise_semantic_findings("event_dramatic_delta", event_dramatic_delta_findings(events))


EVENT_INDEPENDENCE_EVIDENCE_WORDS = (
    "新目标",
    "新角色",
    "新空间",
    "新信息",
    "新证据",
    "新代价",
    "资源变化",
    "权力变化",
    "秘密暴露",
    "关系变化",
    "目标改变",
    "可见结果",
    "独立选择",
    "法律关系",
    "物理空间",
    "角色功能",
    "不可逆",
)


def event_independence_findings(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle event independence findings."""
    findings: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        delta = event.get("dramatic_delta", {})
        reason = str(delta.get("why_not_repetition", "")) if isinstance(delta, dict) else ""
        if not reason.strip():
            findings.append(
                {
                    "check": "event_independence",
                    "path": f"event_pool[{index}].dramatic_delta.why_not_repetition",
                    "issue": "missing_event_independence_reason",
                    "event_id": event.get("id"),
                }
            )
            continue
        if not any(word in reason for word in EVENT_INDEPENDENCE_EVIDENCE_WORDS):
            findings.append(
                {
                    "check": "event_independence",
                    "path": f"event_pool[{index}].dramatic_delta.why_not_repetition",
                    "issue": "event_independence_reason_lacks_concrete_evidence",
                    "event_id": event.get("id"),
                    "reason": reason,
                }
            )
    return findings


def validate_event_independence(events: list[dict[str, Any]]) -> None:
    """Handle validate event independence."""
    _raise_semantic_findings("event_independence", event_independence_findings(events))


def event_child_beat_capacity_findings(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle event child beat capacity findings."""
    findings: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        try:
            start, end = _event_window(event)
        except (TypeError, ValueError):
            continue
        expected_span = max(end - start + 1, int(event.get("expected_episode_span", 0) or 0))
        beats = [item for item in event.get("child_beats", []) or [] if isinstance(item, dict)]
        if len(beats) < expected_span:
            findings.append(
                {
                    "check": "event_child_beat_capacity",
                    "path": f"event_pool[{index}].child_beats",
                    "issue": "child_beat_count_below_event_span",
                    "event_id": event.get("id"),
                    "event_window": {"start": start, "end": end},
                    "expected_minimum": expected_span,
                    "actual": len(beats),
                }
            )
        if len(beats) > expected_span * 2:
            findings.append(
                {
                    "check": "event_child_beat_capacity",
                    "path": f"event_pool[{index}].child_beats",
                    "issue": "child_beat_count_above_two_per_episode_capacity",
                    "event_id": event.get("id"),
                    "event_window": {"start": start, "end": end},
                    "expected_maximum": expected_span * 2,
                    "actual": len(beats),
                }
            )
    return findings


def validate_event_child_beat_capacity(events: list[dict[str, Any]]) -> None:
    """Handle validate event child beat capacity."""
    _raise_semantic_findings(
        "event_child_beat_capacity",
        event_child_beat_capacity_findings(events),
    )


def validate_episode_fact_transitions(
    episodes: list[dict[str, Any]],
    *,
    source_fact_ledger: list[dict[str, Any]],
) -> None:
    """Handle validate episode fact transitions."""
    allowed_statuses = {"unknown", "suspected", "known", "confirmed", "resolved"}
    known_fact_ids = {
        str(item.get("fact_id"))
        for item in source_fact_ledger
        if isinstance(item, dict) and str(item.get("fact_id", "")).strip()
    }
    findings: list[dict[str, Any]] = []
    for episode_index, episode in enumerate(episodes):
        if not isinstance(episode, dict):
            continue
        for transition_index, transition in enumerate(episode.get("fact_transitions", []) or []):
            if not isinstance(transition, dict):
                continue
            fact_id = str(transition.get("fact_id", ""))
            path = f"episode_outlines[{episode_index}].fact_transitions[{transition_index}]"
            if fact_id not in known_fact_ids:
                findings.append(
                    {
                        "check": "fact_transition",
                        "path": f"{path}.fact_id",
                        "issue": "unknown_source_fact_id",
                        "fact_id": fact_id,
                    },
                )
            if str(transition.get("from_status", "")).strip() == str(transition.get("to_status", "")).strip():
                findings.append(
                    {"check": "fact_transition", "path": path, "issue": "fact_status_unchanged", "fact_id": fact_id},
                )
            for field in ("from_status", "to_status"):
                value = str(transition.get(field, "")).strip()
                if value not in allowed_statuses:
                    findings.append(
                        {
                            "check": "fact_transition",
                            "path": f"{path}.{field}",
                            "issue": "invalid_fact_status",
                            "value": value,
                        },
                    )
    _raise_semantic_findings("episode_fact_transitions", findings)


def validate_episode_event_fact_alignment(
    episodes: list[dict[str, Any]],
    *,
    event_pool: list[dict[str, Any]],
) -> None:
    """Handle validate episode event fact alignment."""
    event_facts = {
        str(event.get("id")): {str(item) for item in event.get("source_fact_ids", []) or []}
        for event in event_pool
        if isinstance(event, dict) and str(event.get("id", "")).strip()
    }
    findings: list[dict[str, Any]] = []
    for index, episode in enumerate(episodes):
        if not isinstance(episode, dict):
            continue
        expected = {
            fact_id
            for event_id in episode.get("event_ids", []) or []
            for fact_id in event_facts.get(str(event_id), set())
        }
        actual = {str(item) for item in episode.get("source_fact_ids", []) or []}
        if expected and not (actual & expected):
            findings.append(
                {
                    "check": "event_fact_alignment",
                    "path": f"episode_outlines[{index}].source_fact_ids",
                    "issue": "no_fact_shared_with_selected_events",
                    "expected_any": sorted(expected),
                    "actual": sorted(actual),
                },
            )
        extra = sorted(actual - expected) if expected else []
        if extra:
            findings.append(
                {
                    "check": "event_fact_alignment",
                    "path": f"episode_outlines[{index}].source_fact_ids",
                    "issue": "fact_not_supported_by_selected_events",
                    "ids": extra,
                },
            )
    _raise_semantic_findings("episode_event_fact_alignment", findings)


def validate_longform_blocks(
    blocks: list[dict[str, Any]],
    *,
    target_episodes: int,
    expected_block_count: int | None = None,
) -> None:
    """Handle validate longform blocks."""
    expected = expected_block_count or expected_block_count_for_target(target_episodes)
    if len(blocks) != expected:
        raise ValueError(
            f"longform_blocks expected {expected} blocks for target_episodes={target_episodes}, got {len(blocks)}",
        )
    total = sum(int(item.get("episode_count", 0)) for item in blocks)
    if total != target_episodes:
        raise ValueError(f"longform_blocks total must equal target_episodes={target_episodes}, got {total}")


def _event_window(event: dict[str, Any]) -> tuple[int, int]:
    """Handle event window."""
    window = event.get("episode_window")
    if isinstance(window, dict):
        start = int(window.get("start", 0))
        end = int(window.get("end", 0))
        if start <= 0 or end <= 0 or start > end:
            raise ValueError(f"event_pool item {event.get('id', '<unknown>')} has invalid episode_window")
        return start, end
    if window:
        return parse_numeric_range(str(window))
    start = int(event.get("not_before_episode", 0))
    end = int(event.get("not_after_episode", 0))
    if start <= 0 or end <= 0 or start > end:
        raise ValueError(f"event_pool item {event.get('id', '<unknown>')} has invalid episode_window")
    return start, end


def validate_event_pool_contract(events: list[dict[str, Any]], *, derived_config: dict[str, Any]) -> None:
    """Handle validate event pool contract."""
    low, high = parse_numeric_range(str(derived_config.get("event_pool_size", f"{len(events)}-{len(events)}")))
    if len(events) < low or len(events) > high:
        raise ValueError(f"event_pool count must be within {low}-{high}, got {len(events)}")
    required_keys = [
        "id",
        "title",
        "function",
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
        "child_beats",
    ]
    for event in events:
        event_id = event.get("id", "<unknown>")
        missing = [key for key in required_keys if key not in event or event[key] in (None, "", [])]
        if missing:
            raise ValueError(f"event_pool item {event_id} missing required key(s): {', '.join(missing)}")
        if str(event.get("source_anchor", "")).strip().lower() in {"无", "none", "n/a", "na", "null"}:
            raise ValueError(
                (
                    f"event_pool item {event_id} source_anchor must name a source fact, source mechanism, or e"
                    f"motional debt"
                ),
            )
        _event_window(event)
        if int(event.get("not_before_episode", 0)) > int(event.get("not_after_episode", 0)):
            raise ValueError(f"event_pool item {event_id} has not_before_episode after not_after_episode")
        if int(event.get("expected_episode_span", 0)) < 1:
            raise ValueError(f"event_pool item {event_id} expected_episode_span must be at least 1")


def event_child_beat_alignment_findings(
    episodes: list[dict[str, Any]],
    *,
    event_pool: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Handle event child beat alignment findings."""
    beat_by_id: dict[str, dict[str, Any]] = {}
    beats_by_event: dict[str, set[str]] = {}
    event_windows: dict[str, tuple[int, int]] = {}
    for event in event_pool:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id", "")).strip()
        try:
            event_windows[event_id] = _event_window(event)
        except (TypeError, ValueError):
            pass
        for beat in event.get("child_beats", []) or []:
            if not isinstance(beat, dict):
                continue
            beat_id = str(beat.get("child_beat_id", "")).strip()
            if not beat_id:
                continue
            beat_by_id[beat_id] = {**beat, "event_id": event_id}
            beats_by_event.setdefault(event_id, set()).add(beat_id)

    findings: list[dict[str, Any]] = []
    consumed_by_event: dict[str, set[str]] = {}
    completed_events: dict[str, list[Any]] = {}
    first_consumed_episode: dict[str, Any] = {}
    for episode in episodes:
        episode_num = episode.get("episode_num")
        event_ids = {str(item).strip() for item in episode.get("event_ids", []) or [] if str(item).strip()}
        consumed_ids = [
            str(item).strip()
            for item in episode.get("consumed_child_beat_ids", []) or []
            if str(item).strip()
        ]
        if event_ids and not consumed_ids:
            findings.append(
                {
                    "episode_num": episode_num,
                    "issue": "event_ids_without_consumed_child_beat_ids",
                    "event_ids": sorted(event_ids),
                }
            )
        consumed_owner_event_ids: set[str] = set()
        for beat_id in consumed_ids:
            beat = beat_by_id.get(beat_id)
            if beat is None:
                findings.append(
                    {"episode_num": episode_num, "issue": "unknown_child_beat_id", "child_beat_id": beat_id}
                )
                continue
            owner_event_id = str(beat.get("event_id", ""))
            consumed_owner_event_ids.add(owner_event_id)
            window = event_windows.get(owner_event_id)
            if window and str(episode_num).isdigit() and not window[0] <= int(episode_num) <= window[1]:
                findings.append(
                    {
                        "episode_num": episode_num,
                        "issue": "child_beat_consumed_outside_owner_event_window",
                        "child_beat_id": beat_id,
                        "owner_event_id": owner_event_id,
                        "window": {"start": window[0], "end": window[1]},
                    }
                )
            if owner_event_id not in event_ids:
                findings.append(
                    {
                        "episode_num": episode_num,
                        "issue": "child_beat_belongs_to_undeclared_event",
                        "child_beat_id": beat_id,
                        "owner_event_id": owner_event_id,
                        "declared_event_ids": sorted(event_ids),
                    }
                )
            if beat_id in first_consumed_episode:
                findings.append(
                    {
                        "episode_num": episode_num,
                        "issue": "child_beat_consumed_more_than_once",
                        "child_beat_id": beat_id,
                        "first_episode_num": first_consumed_episode[beat_id],
                    }
                )
            else:
                first_consumed_episode[beat_id] = episode_num
            consumed_by_event.setdefault(owner_event_id, set()).add(beat_id)
        for event_id in sorted(event_ids - consumed_owner_event_ids):
            findings.append(
                {
                    "episode_num": episode_num,
                    "issue": "declared_event_without_own_child_beat_id",
                    "event_id": event_id,
                    "consumed_child_beat_ids": consumed_ids,
                }
            )
        if str(episode.get("event_consumption_status", "")).strip().lower() in {
            "completed",
            "block_payoff",
            "已完成",
            "篇章回收",
        }:
            for event_id in event_ids:
                completed_events.setdefault(event_id, []).append(episode_num)

    for event_id, episode_nums in completed_events.items():
        expected = beats_by_event.get(event_id, set())
        missing = sorted(expected - consumed_by_event.get(event_id, set()))
        if missing:
            findings.append(
                {
                    "issue": "completed_event_child_beat_ids_not_covered",
                    "event_id": event_id,
                    "episodes": episode_nums,
                    "missing_child_beat_ids": missing,
                }
            )
    return findings


def validate_episode_child_beat_references(
    episodes: list[dict[str, Any]],
    *,
    event_pool: list[dict[str, Any]],
) -> None:
    """Handle validate episode child beat references."""
    findings = event_child_beat_alignment_findings(episodes, event_pool=event_pool)
    if findings:
        first = findings[0]
        raise ValueError(f"event child beat alignment failed: {first}")


PROP_LOCATION_TERMS = (
    "书包侧袋",
    "书包",
    "枕头下",
    "书桌上",
    "手中",
    "口袋",
    "冰箱",
    "垃圾桶",
    "马桶",
    "床底",
    "抽屉",
    "客房",
    "卧室",
    "房间",
    "车内",
    "考场",
)

PROP_CONTAINER_TERMS = {
    "书包侧袋",
    "书包",
    "枕头下",
    "书桌上",
    "手中",
    "口袋",
    "冰箱",
    "垃圾桶",
    "马桶",
    "床底",
    "抽屉",
}


def prop_location_states_compatible(left: Any, right: Any) -> bool:
    """Handle prop location states compatible."""
    left_text = re.sub(r"[\s·，,。；;：:]", "", str(left or ""))
    right_text = re.sub(r"[\s·，,。；;：:]", "", str(right or ""))
    if not left_text or not right_text:
        return left_text == right_text
    if left_text in right_text or right_text in left_text:
        return True
    left_terms = {term for term in PROP_LOCATION_TERMS if term in left_text}
    right_terms = {term for term in PROP_LOCATION_TERMS if term in right_text}
    if not left_terms or not right_terms:
        return False
    return bool((left_terms & right_terms) & PROP_CONTAINER_TERMS)


def prop_evidence_matches_script(evidence: Any, script: Any) -> bool:
    """Handle prop evidence matches script."""
    evidence_text = str(evidence or "").strip()
    script_text = str(script or "")
    if not evidence_text or not script_text:
        return False

    def compact(value: str) -> str:
        """Handle compact."""
        return re.sub(r"[\s△，,。；;：:！!？?—…·\-]", "", value)

    compact_evidence = compact(evidence_text)
    compact_script = compact(script_text)
    if compact_evidence and compact_evidence in compact_script:
        return True
    clauses = [
        compact(item)
        for item in re.split(r"[，,。；;！!？?\n]+", evidence_text)
        if len(compact(item)) >= 8
    ]
    if not clauses:
        return False
    matched = sum(1 for clause in clauses if clause in compact_script)
    return matched > 0 and matched * 2 >= len(clauses)


def prop_continuity_plan_findings(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle prop continuity plan findings."""
    findings: list[dict[str, Any]] = []
    state_by_id: dict[str, dict[str, Any]] = {}
    name_by_id: dict[str, str] = {}
    id_by_name: dict[str, str] = {}
    for episode in sorted(
        [item for item in episodes if str(item.get("episode_num", "")).isdigit()],
        key=lambda item: int(item["episode_num"]),
    ):
        episode_num = int(episode["episode_num"])
        for plan in episode.get("prop_continuity_plan", []) or []:
            if not isinstance(plan, dict):
                continue
            prop_id = str(plan.get("prop_id", "")).strip()
            prop_name = str(plan.get("prop_name", "")).strip()
            if not prop_id:
                continue
            prior_name = name_by_id.get(prop_id)
            if prior_name and prop_name and prior_name != prop_name:
                findings.append(
                    {
                        "episode_num": episode_num,
                        "issue": "prop_id_reused_for_different_name",
                        "prop_id": prop_id,
                        "previous_prop_name": prior_name,
                        "current_prop_name": prop_name,
                    }
                )
            prior_id = id_by_name.get(prop_name)
            if prop_name and prior_id and prior_id != prop_id:
                findings.append(
                    {
                        "episode_num": episode_num,
                        "issue": "prop_name_changed_id",
                        "prop_name": prop_name,
                        "previous_prop_id": prior_id,
                        "current_prop_id": prop_id,
                    }
                )
            prior = state_by_id.get(prop_id)
            if prior:
                if str(prior.get("holder", "")).strip() != str(plan.get("start_holder", "")).strip():
                    findings.append(
                        {
                            "episode_num": episode_num,
                            "issue": "prop_plan_start_state_mismatch",
                            "prop_id": prop_id,
                            "field": "start_holder",
                            "previous_value": prior.get("holder", ""),
                            "planned_value": plan.get("start_holder", ""),
                        }
                    )
                if not prop_location_states_compatible(prior.get("location"), plan.get("start_location")):
                    findings.append(
                        {
                            "episode_num": episode_num,
                            "issue": "prop_plan_start_state_mismatch",
                            "prop_id": prop_id,
                            "field": "start_location",
                            "previous_value": prior.get("location", ""),
                            "planned_value": plan.get("start_location", ""),
                        }
                    )
            name_by_id[prop_id] = prop_name or prior_name or ""
            if prop_name:
                id_by_name[prop_name] = prop_id
            state_by_id[prop_id] = {
                "holder": plan.get("end_holder", ""),
                "location": plan.get("end_location", ""),
            }
    return findings


def validate_episode_prop_continuity_plans(episodes: list[dict[str, Any]]) -> None:
    """Handle validate episode prop continuity plans."""
    findings = prop_continuity_plan_findings(episodes)
    if findings:
        raise ValueError(f"prop continuity plan failed: {findings[0]}")


def prop_state_continuity_findings(
    stage_output: dict[str, Any],
    *,
    episode_outline: dict[str, Any],
    previous_prop_positions: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Handle prop state continuity findings."""
    script = re.sub(r"\s+", "", str(stage_output.get("final_script", "")))
    plans = [item for item in episode_outline.get("prop_continuity_plan", []) or [] if isinstance(item, dict)]
    continuity = stage_output.get("continuity_update", {}) or {}
    updates = [
        item
        for item in continuity.get("prop_state_changes", continuity.get("prop_state_updates", [])) or []
        if isinstance(item, dict)
    ]
    previous = previous_prop_positions if isinstance(previous_prop_positions, dict) else {}
    plan_by_id = {str(item.get("prop_id", "")).strip(): item for item in plans if str(item.get("prop_id", "")).strip()}
    update_by_id = {
        str(item.get("prop_id", "")).strip(): item
        for item in updates
        if str(item.get("prop_id", "")).strip()
    }
    findings: list[dict[str, Any]] = []

    for prop_id, plan in plan_by_id.items():
        prior = previous.get(prop_id)
        if isinstance(prior, dict):
            prior_name = str(prior.get("prop_name", "")).strip()
            planned_name = str(plan.get("prop_name", "")).strip()
            if prior_name and planned_name and prior_name != planned_name:
                findings.append(
                    {
                        "issue": "prop_id_reused_for_different_name",
                        "prop_id": prop_id,
                        "previous_prop_name": prior_name,
                        "current_prop_name": planned_name,
                    }
                )
            for plan_key, prior_key in (("start_holder", "holder"), ("start_location", "location")):
                planned = str(plan.get(plan_key, "")).strip()
                actual_prior = str(prior.get(prior_key, "")).strip()
                compatible = planned == actual_prior if plan_key == "start_holder" else prop_location_states_compatible(
                    planned,
                    actual_prior,
                )
                if planned and actual_prior and not compatible:
                    findings.append(
                        {
                            "issue": "prop_plan_start_state_mismatch",
                            "prop_id": prop_id,
                            "field": plan_key,
                            "previous_value": actual_prior,
                            "planned_value": planned,
                        }
                    )
        state_changes = any(
            str(plan.get(start_key, "")).strip() != str(plan.get(end_key, "")).strip()
            for start_key, end_key in (("start_holder", "end_holder"), ("start_location", "end_location"))
        )
        if state_changes and (
            not str(plan.get("transfer_action", "")).strip()
            or not str(plan.get("completion_evidence", "")).strip()
        ):
            findings.append({"issue": "prop_state_change_without_planned_evidence", "prop_id": prop_id})
        update = update_by_id.get(prop_id)
        if update is None:
            findings.append({"issue": "planned_prop_missing_state_update", "prop_id": prop_id})
            continue
        for update_key, plan_key in (("holder", "end_holder"), ("location", "end_location")):
            actual = str(update.get(update_key, "")).strip()
            planned = str(plan.get(plan_key, "")).strip()
            compatible = actual == planned if update_key == "holder" else prop_location_states_compatible(
                actual,
                planned,
            )
            if not compatible:
                findings.append(
                    {
                        "issue": "prop_actual_end_state_mismatch",
                        "prop_id": prop_id,
                        "field": update_key,
                        "planned_value": planned,
                        "actual_value": actual,
                    }
                )
        evidence = str(update.get("evidence", update.get("change_evidence", ""))).strip()
        if not prop_evidence_matches_script(evidence, script):
            findings.append(
                {
                    "issue": "prop_change_evidence_not_found_in_script",
                    "prop_id": prop_id,
                    "change_evidence": update.get("evidence", update.get("change_evidence", "")),
                }
            )

    for prop_id, update in update_by_id.items():
        if prop_id not in plan_by_id and prop_id not in previous:
            findings.append({"issue": "unplanned_new_prop_state_update", "prop_id": prop_id})
    return findings


def validate_prop_state_continuity(
    stage_output: dict[str, Any],
    *,
    episode_outline: dict[str, Any],
    previous_prop_positions: dict[str, Any] | None = None,
) -> None:
    """Handle validate prop state continuity."""
    findings = prop_state_continuity_findings(
        stage_output,
        episode_outline=episode_outline,
        previous_prop_positions=previous_prop_positions,
    )
    if findings:
        raise ValueError(f"prop state continuity failed: {findings[0]}")


def _contains_empty_motion(value: Any) -> bool:
    """Handle contains empty motion."""
    text = str(value or "").strip()
    if not text:
        return True
    return text in {"无", "无冲突", "无反击"} or "无冲突" in text or "纯粹展示" in text


def has_content_sensitivity_risk(text: Any) -> bool:
    """Handle has content sensitivity risk."""
    value = str(text or "")
    return any(re.search(pattern, value) for pattern in CONTENT_SENSITIVITY_PATTERNS)


def find_forbidden_script_idioms(script: Any) -> list[dict[str, str]]:
    """Handle find forbidden script idioms."""
    text = str(script or "")
    findings: list[dict[str, str]] = []
    for pattern, label in FORBIDDEN_SCRIPT_IDIOM_PATTERNS:
        for match in re.finditer(pattern, text):
            findings.append({"pattern": label, "match": match.group(0)})
    return findings


def count_narration_devices(script: Any) -> dict[str, int]:
    """Handle count narration devices."""
    text = str(script or "")
    vo_pattern = re.compile(r"（[^）]*\bVO\b[^）]*）")
    vo_occurrences = vo_pattern.findall(text)
    return {
        "os_count": len(re.findall(r"（[^）]*\bOS\b[^）]*）", text)),
        "flashback_count": len(re.findall(r"【闪回】", text)),
        "vo_count": len(vo_occurrences),
    }


def _safe_int(value: Any, default: int = 0) -> int:
    """Handle safe int."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _time_deviation_items(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Handle time deviation items."""
    items: list[tuple[str, dict[str, Any]]] = []
    for list_key in ("retained_time_deviations", "rewrite_time_deviations", "deleted_time_deviations"):
        for item in data.get(list_key, []) or []:
            if isinstance(item, dict):
                items.append((list_key, item))
    return items


def _flashback_screening_id_maps(data: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Handle flashback screening id maps."""
    by_id: dict[str, dict[str, Any]] = {}
    source_by_id: dict[str, str] = {}
    for list_key, item in _time_deviation_items(data):
        item_id = str(item.get("id", "")).strip()
        if item_id:
            by_id[item_id] = item
            source_by_id[item_id] = list_key
    return by_id, source_by_id


def validate_flashback_screening_contract(data: dict[str, Any]) -> None:
    """Handle validate flashback screening contract."""
    validate_stage_contract("04a_flashback_screening", data)
    quota_policy = data.get("quota_policy", {})
    overview = data.get("flashback_overview", {})
    used_quota = _safe_int(quota_policy.get("used_quota"))
    quota_limit = _safe_int(quota_policy.get("quota_limit"), NARRATION_DEVICE_BUDGET_OS_FLASHBACK)
    actual_a_quota = 0
    grade_counts = {"S": 0, "A": 0, "B": 0, "C": 0}
    seen_ids: set[str] = set()
    expected_grade_by_list = {
        "retained_time_deviations": {"S", "A"},
        "rewrite_time_deviations": {"B"},
        "deleted_time_deviations": {"C"},
    }
    for list_key, item in _time_deviation_items(data):
        item_id = str(item.get("id", "")).strip()
        if item_id in seen_ids:
            raise ValueError(f"04a_flashback_screening duplicate time deviation id: {item_id}")
        if item_id:
            seen_ids.add(item_id)
        grade = str(item.get("grade", "")).strip().upper()
        if grade not in ALLOWED_TIME_DEVIATION_GRADES:
            raise ValueError(f"04a_flashback_screening {item_id or '<missing id>'} grade must be one of S/A/B/C")
        if grade not in expected_grade_by_list[list_key]:
            raise ValueError(
                f"04a_flashback_screening {item_id or '<missing id>'} grade {grade} cannot appear in {list_key}",
            )
        grade_counts[grade] += 1
        quota_count = _safe_int(item.get("quota_count"))
        expected_quota = 1 if grade == "A" else 0
        if quota_count != expected_quota:
            raise ValueError(
                (
                    f"04a_flashback_screening {item_id or '<missing id>'} quota_count must be {expected_quota}"
                    f" for grade {grade}"
                )
            )
        actual_a_quota += quota_count
    cumulative = used_quota + actual_a_quota
    if cumulative > quota_limit:
        raise ValueError(f"04a_flashback_screening A flashback quota must be <= {quota_limit}, got {cumulative}")
    actual_total = sum(grade_counts.values())
    overview_checks = (
        ("total_time_deviation_count", actual_total),
        ("s_count", grade_counts["S"]),
        ("a_count", grade_counts["A"]),
        ("b_count", grade_counts["B"]),
        ("c_count", grade_counts["C"]),
    )
    for key, expected in overview_checks:
        if _safe_int(overview.get(key)) != expected:
            raise ValueError(f"04a_flashback_screening flashback_overview.{key} must be {expected}")
    declared_new = _safe_int(quota_policy.get("new_a_quota_count"))
    declared_cumulative = _safe_int(quota_policy.get("cumulative_a_quota_count"))
    declared_remaining = _safe_int(quota_policy.get("remaining_quota"))
    if declared_new != actual_a_quota:
        raise ValueError(f"04a_flashback_screening quota_policy.new_a_quota_count must be {actual_a_quota}")
    if declared_cumulative != cumulative:
        raise ValueError(f"04a_flashback_screening quota_policy.cumulative_a_quota_count must be {cumulative}")
    if declared_remaining != quota_limit - cumulative:
        raise ValueError(f"04a_flashback_screening quota_policy.remaining_quota must be {quota_limit - cumulative}")


def flashback_screening_alignment_findings(
    episodes: list[dict[str, Any]],
    *,
    flashback_screening: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Handle flashback screening alignment findings."""
    if not flashback_screening:
        return []
    by_id, source_by_id = _flashback_screening_id_maps(flashback_screening)
    findings: list[dict[str, Any]] = []
    total_planned_os = 0
    total_planned_flashback_quota = 0
    for episode in episodes:
        plan = episode.get("narration_device_plan", {})
        if not isinstance(plan, dict):
            continue
        episode_num = episode.get("episode_num")
        planned_flashback_count = _safe_int(plan.get("planned_flashback_count"))
        planned_os_count = _safe_int(plan.get("planned_os_count"))
        planned_quota = _safe_int(plan.get("planned_flashback_quota_count", plan.get("planned_flashback_count")))
        total_planned_os += planned_os_count
        total_planned_flashback_quota += planned_quota
        legacy_approved_ids = [
            str(item).strip()
            for item in (plan.get("approved_time_deviation_ids") or [])
            if str(item).strip()
        ]
        flashback_ids = [
            str(item).strip()
            for item in (
                plan.get("approved_flashback_time_deviation_ids")
                if "approved_flashback_time_deviation_ids" in plan
                else legacy_approved_ids
            )
            if str(item).strip()
        ]
        os_ids = [
            str(item).strip()
            for item in (plan.get("approved_os_time_deviation_ids") or [])
            if str(item).strip()
        ]
        visualized_ids = [
            str(item).strip()
            for item in (plan.get("visualized_time_deviation_ids") or [])
            if str(item).strip()
        ]
        rewritten_ids = [
            str(item).strip()
            for item in (plan.get("deleted_or_rewritten_time_deviation_ids") or [])
            if str(item).strip()
        ]
        if planned_flashback_count > 0 and not flashback_ids:
            findings.append(
                {
                    "episode_num": episode_num,
                    "issue": "planned flashback requires approved_time_deviation_ids",
                    "planned_flashback_count": planned_flashback_count,
                }
            )
            continue
        if flashback_ids and planned_flashback_count <= 0:
            flashback_field = (
                "approved_time_deviation_ids"
                if legacy_approved_ids and legacy_approved_ids == flashback_ids
                else "approved_flashback_time_deviation_ids"
            )
            findings.append(
                {
                    "episode_num": episode_num,
                    "issue": f"{flashback_field} require planned_flashback_count",
                    flashback_field: flashback_ids,
                }
            )
        actual_a_refs = 0
        for item_id in flashback_ids:
            item = by_id.get(item_id)
            if not item:
                findings.append(
                    {
                        "episode_num": episode_num,
                        "issue": "unknown approved_time_deviation_ids",
                        "id": item_id,
                    }
                )
                continue
            grade = str(item.get("grade", "")).strip().upper()
            list_key = source_by_id.get(item_id, "")
            if grade in {"B", "C"} or list_key in {"rewrite_time_deviations", "deleted_time_deviations"}:
                findings.append(
                    {
                        "episode_num": episode_num,
                        "issue": "cannot reference B/C time deviation",
                        "id": item_id,
                        "grade": grade,
                    }
                )
            elif grade == "A":
                actual_a_refs += 1
        for field_name, ids in (
            ("approved_os_time_deviation_ids", os_ids),
            ("visualized_time_deviation_ids", visualized_ids),
            ("deleted_or_rewritten_time_deviation_ids", rewritten_ids),
        ):
            for item_id in ids:
                item = by_id.get(item_id)
                if not item:
                    findings.append(
                        {
                            "episode_num": episode_num,
                            "issue": f"unknown {field_name}",
                            "id": item_id,
                        }
                    )
                    continue
                grade = str(item.get("grade", "")).strip().upper()
                list_key = source_by_id.get(item_id, "")
                if (
                    field_name == "approved_os_time_deviation_ids"
                    and (grade in {"B", "C"}
                    or list_key in {"rewrite_time_deviations", "deleted_time_deviations"})
                ):
                    findings.append(
                        {
                            "episode_num": episode_num,
                            "issue": "OS time deviation ids must reference retained S/A items",
                            "id": item_id,
                            "grade": grade,
                        }
                    )
        if planned_quota != actual_a_refs:
            findings.append(
                {
                    "episode_num": episode_num,
                    "issue": "planned_flashback_quota_count must equal referenced A-grade time deviations",
                    "planned_flashback_quota_count": planned_quota,
                    "referenced_a_count": actual_a_refs,
                }
            )
        if planned_quota > planned_flashback_count:
            findings.append(
                {
                    "episode_num": episode_num,
                    "issue": "planned_flashback_quota_count cannot exceed planned_flashback_count",
                    "planned_flashback_count": planned_flashback_count,
                    "planned_flashback_quota_count": planned_quota,
                }
            )
    total = total_planned_os + total_planned_flashback_quota
    if total > NARRATION_DEVICE_BUDGET_OS_FLASHBACK:
        findings.append(
            {
                "issue": "narration device budget OS+flashback quota must be <= 5",
                "planned_os_count": total_planned_os,
                "planned_flashback_quota_count": total_planned_flashback_quota,
                "planned_total": total,
                "limit": NARRATION_DEVICE_BUDGET_OS_FLASHBACK,
            }
        )
    return findings


def validate_episode_flashback_screening_alignment(
    episodes: list[dict[str, Any]],
    *,
    flashback_screening: dict[str, Any] | None,
) -> None:
    """Handle validate episode flashback screening alignment."""
    findings = flashback_screening_alignment_findings(episodes, flashback_screening=flashback_screening)
    if findings:
        first = findings[0]
        raise ValueError(str(first.get("issue", "flashback screening alignment failed")))


def narration_device_plan_findings(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle narration device plan findings."""
    os_total = 0
    flashback_quota_total = 0
    items: list[dict[str, Any]] = []
    for episode in episodes:
        plan = episode.get("narration_device_plan", {})
        if not isinstance(plan, dict):
            continue
        os_count = _safe_int(plan.get("planned_os_count"))
        flashback_count = _safe_int(plan.get("planned_flashback_count"))
        flashback_quota_count = _safe_int(plan.get("planned_flashback_quota_count", flashback_count))
        os_total += os_count
        flashback_quota_total += flashback_quota_count
        if os_count or flashback_count or flashback_quota_count:
            items.append(
                {
                    "episode_num": episode.get("episode_num"),
                    "planned_os_count": os_count,
                    "planned_flashback_count": flashback_count,
                    "planned_flashback_quota_count": flashback_quota_count,
                    "reason": plan.get("reason", ""),
                }
            )
    total = os_total + flashback_quota_total
    if total <= NARRATION_DEVICE_BUDGET_OS_FLASHBACK:
        return []
    return [
        {
            "issue": "narration device budget OS+flashback quota must be <= 5",
            "planned_os_count": os_total,
            "planned_flashback_quota_count": flashback_quota_total,
            "planned_total": total,
            "limit": NARRATION_DEVICE_BUDGET_OS_FLASHBACK,
            "episodes": items,
        }
    ]


def validate_narration_device_plan_budget(episodes: list[dict[str, Any]]) -> None:
    """Handle validate narration device plan budget."""
    findings = narration_device_plan_findings(episodes)
    if findings:
        item = findings[0]
        raise ValueError(
            "narration device budget OS+flashback quota must be <= 5, "
            + (
                f"got {item['planned_total']} (OS={item['planned_os_count']}, flashback_quota="
                f"{item['planned_flashback_quota_count']})"
            )
        )


def validate_episode_longform_contract(
    episodes: list[dict[str, Any]],
    *,
    event_pool: list[dict[str, Any]],
    derived_config: dict[str, Any],
    allowed_character_names: list[str] | None = None,
) -> None:
    """Handle validate episode longform contract."""
    validate_narration_device_plan_budget(episodes)
    event_by_id = {int(item["id"]): item for item in event_pool if str(item.get("id", "")).isdigit()}
    max_epilogue = int(derived_config.get("epilogue_max_episodes", DEFAULT_PACING_CONTROLS["epilogue_max_episodes"]))
    max_reuse = int(derived_config.get("event_reuse_max_episodes", DEFAULT_PACING_CONTROLS["event_reuse_max_episodes"]))
    max_conflict_streak = int(
        derived_config.get("conflict_mode_streak_limit", DEFAULT_PACING_CONTROLS["conflict_mode_streak_limit"]),
    )
    required_keys = [
        "conflict_mode",
        "pattern_family",
        "source_anchor",
        "boundary_check",
        "appearing_character_names",
        "is_epilogue",
    ]
    epilogue_count = 0
    event_use_counts: dict[int, int] = {}
    last_conflict_mode = None
    conflict_streak = 0
    last_pattern_family = None
    pattern_streak = 0
    allowed_names = expand_allowed_character_names(allowed_character_names or [])
    for episode in episodes:
        episode_num = int(episode.get("episode_num", 0))
        episode_id = episode.get("episode_num", "<unknown>")
        missing = [key for key in required_keys if key not in episode or episode[key] in (None, "")]
        if missing:
            raise ValueError(f"episode {episode_id} missing required key(s): {', '.join(missing)}")
        is_epilogue = bool(episode.get("is_epilogue"))
        if is_epilogue:
            epilogue_count += 1
            if len(episode.get("event_ids", [])) > 2:
                raise ValueError(f"episode {episode_id} epilogue event count must be <= 2")
        if (
            not is_epilogue
            and (_contains_empty_motion(episode.get("main_conflict"))
            or _contains_empty_motion(episode.get("counterattack")))
        ):
            raise ValueError(f"episode {episode_id} non-epilogue cards must include active conflict and counterattack")
        boundary_check = episode.get("boundary_check")
        if not isinstance(boundary_check, dict):
            raise ValueError(f"episode {episode_id} boundary_check must be an object")
        boundary_missing = [
            key
            for key in ("risk_level", "protagonist_action", "why_allowed", "mitigation")
            if key not in boundary_check or boundary_check[key] in (None, "")
        ]
        if boundary_missing:
            raise ValueError(
                f"episode {episode_id} boundary_check missing required key(s): {', '.join(boundary_missing)}",
            )
        content_text = " ".join(
            str(episode.get(key, ""))
            for key in (
                "main_conflict", "counterattack", "information_gain", "ending_hook", "source_anchor", "expansion_delta"
            )
        )
        appearing_names = episode.get("appearing_character_names", [])
        if not isinstance(appearing_names, list) or not appearing_names:
            raise ValueError(f"episode {episode_id} appearing_character_names must be a non-empty list")
        if allowed_names:
            unknown_names = sorted(
                {name for name in appearing_names if name and normalize_character_name(name) not in allowed_names},
            )
            if unknown_names:
                raise ValueError(
                    f"episode {episode_id} appearing_character_names not in allowed names: {unknown_names}",
                )
        validate_episode_scene_plan_boundaries(episode)
        conflict_mode = str(episode.get("conflict_mode"))
        if conflict_mode == last_conflict_mode:
            conflict_streak += 1
        else:
            last_conflict_mode = conflict_mode
            conflict_streak = 1
        if conflict_streak > max_conflict_streak:
            raise ValueError(
                f"episode {episode_id} conflict_mode streak exceeds {max_conflict_streak}: {conflict_mode}",
            )
        pattern_family = str(episode.get("pattern_family"))
        if pattern_family == last_pattern_family:
            pattern_streak += 1
        else:
            last_pattern_family = pattern_family
            pattern_streak = 1
        if pattern_streak > max_conflict_streak:
            raise ValueError(
                f"episode {episode_id} pattern_family streak exceeds {max_conflict_streak}: {pattern_family}",
            )
        for event_id_raw in episode.get("event_ids", []):
            if not str(event_id_raw).isdigit():
                continue
            event_id = int(event_id_raw)
            event = event_by_id.get(event_id)
            if not event:
                continue
            event_use_counts[event_id] = event_use_counts.get(event_id, 0) + 1
            if (
                not episode.get("allowed_cross_block_bridge")
                and int(event.get("target_block", -1)) != int(episode.get("block_id", -2))
            ):
                raise ValueError(
                    (
                        f"episode {episode_id} event {event_id} target_block={event.get('target_block')} does not "
                        f"match block_id={episode.get('block_id')}"
                    )
                )
            start, end = _event_window(event)
            if episode_num < start or episode_num > end:
                raise ValueError(f"episode {episode_id} consumes event {event_id} outside episode_window {start}-{end}")
    if epilogue_count > max_epilogue:
        raise ValueError(f"epilogue episode count must be <= {max_epilogue}, got {epilogue_count}")
    for event_id, count in event_use_counts.items():
        expected_span = int(event_by_id[event_id].get("expected_episode_span", max_reuse))
        allowed = max(max_reuse, expected_span)
        if count > allowed:
            raise ValueError(f"event {event_id} reused in {count} episodes, allowed {allowed}")


def parse_final_script_scenes(script: str, *, episode_num: Any = "<unknown>") -> list[dict[str, Any]]:
    """Handle parse final script scenes."""
    lines = str(script or "").splitlines()
    headings: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = SCRIPT_SCENE_HEADING_RE.match(line)
        if match:
            headings.append((index, match))
    scenes: list[dict[str, Any]] = []
    for index, (line_index, match) in enumerate(headings):
        next_line_index = headings[index + 1][0] if index + 1 < len(headings) else len(lines)
        body_lines = lines[line_index + 1 : next_line_index]
        first_content = next((line.strip() for line in body_lines if line.strip()), "")
        cast_match = SCRIPT_SCENE_CAST_RE.match(first_content)
        scene_id = f"{int(match.group('episode'))}-{int(match.group('scene'))}"
        if not cast_match:
            raise ValueError(f"episode {episode_num} final_script scene {scene_id} missing 出场人物")
        scenes.append(
            {
                "scene_id": scene_id,
                "scene_no": int(match.group("scene")),
                "location": match.group("location").strip(),
                "time": match.group("time").strip(),
                "space": match.group("space").strip(),
                "cast": _split_scene_cast(cast_match.group("cast")),
                "body": "\n".join(body_lines).strip(),
            }
        )
    return scenes


PREMATURE_BRIDGE_COMPLETION_RE = re.compile(
    r"(?:已|已经|成功|正式|完成)(?:[^，。！？；\n]{0,10})"
    r"(?:抵达|到达|进入|签约|签署|备案|上传|交付|拿下|获胜|离开)"
)


def _normalize_continuity_fact_text(value: Any) -> str:
    """Handle normalize continuity fact text."""
    return re.sub(r"[\s△。！？；，,]", "", str(value or ""))


def extract_last_scene_fact(script: str, *, episode_num: Any = "<unknown>") -> dict[str, Any]:
    """Handle extract last scene fact."""
    scenes = parse_final_script_scenes(script, episode_num=episode_num)
    if not scenes:
        return {"location": "", "present_character_names": [], "visible_result": ""}
    last_scene = scenes[-1]
    visible_lines = [
        line.strip()
        for line in str(last_scene.get("body", "")).splitlines()
        if line.strip()
        and not SCRIPT_SCENE_CAST_RE.match(line.strip())
        and line.strip() not in {"【闪回】", "【闪出】", "【闪回结束】"}
    ]
    return {
        "location": str(last_scene.get("location", "")).strip(),
        "present_character_names": list(last_scene.get("cast", [])),
        "visible_result": visible_lines[-1].lstrip("△").strip() if visible_lines else "",
    }


def extract_last_authored_scene_fact(script: str, *, episode_num: Any = "<unknown>") -> dict[str, Any]:
    """Extract the authored last scene even when its space token is malformed.

    This is only for continuity bookkeeping. The strict script validator still
    reports headings such as `内外` or `内转外`.
    """

    lines = str(script or "").splitlines()
    headings: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = SCRIPT_SCENE_HEADING_AUTHORED_RE.match(line)
        if match:
            headings.append((index, match))
    if not headings:
        return extract_last_scene_fact(script, episode_num=episode_num)
    line_index, match = headings[-1]
    body_lines = lines[line_index + 1 :]
    first_content = next((line.strip() for line in body_lines if line.strip()), "")
    cast_match = SCRIPT_SCENE_CAST_RE.match(first_content)
    cast = _split_scene_cast(cast_match.group("cast")) if cast_match else []
    visible_lines = [
        line.strip()
        for line in body_lines
        if line.strip()
        and not SCRIPT_SCENE_CAST_RE.match(line.strip())
        and line.strip() not in {"【闪回】", "【闪出】", "【闪回结束】"}
    ]
    return {
        "location": match.group("location").strip(),
        "present_character_names": cast,
        "visible_result": visible_lines[-1].lstrip("△").strip() if visible_lines else "",
    }


def continuity_fact_findings(
    stage_output: dict[str, Any],
    *,
    episode_num: Any = "<unknown>",
) -> list[dict[str, Any]]:
    """Handle continuity fact findings."""
    findings: list[dict[str, Any]] = []
    script = str(stage_output.get("final_script", ""))
    update = stage_output.get("continuity_update")
    if not isinstance(update, dict):
        return findings
    reported = update.get("last_scene_state")
    if not isinstance(reported, dict):
        return findings
    try:
        actual = extract_last_scene_fact(script, episode_num=episode_num)
        scenes = parse_final_script_scenes(script, episode_num=episode_num)
    except ValueError as exc:
        return [{"episode_num": episode_num, "issue": "last_scene_unparseable", "detail": str(exc)}]

    if str(reported.get("location", "")).strip() != actual["location"]:
        findings.append(
            {
                "episode_num": episode_num,
                "issue": "last_scene_location_mismatch",
                "reported": reported.get("location", ""),
                "actual": actual["location"],
            }
        )
    reported_cast = sorted(
        {
            normalize_character_name(str(item))
            for item in reported.get("present_character_names", [])
            if normalize_character_name(str(item))
        }
    ) if isinstance(reported.get("present_character_names"), list) else []
    if reported_cast != sorted(actual["present_character_names"]):
        findings.append(
            {
                "episode_num": episode_num,
                "issue": "last_scene_cast_mismatch",
                "reported": reported_cast,
                "actual": sorted(actual["present_character_names"]),
            }
        )
    reported_result = _normalize_continuity_fact_text(reported.get("visible_result", ""))
    actual_body = _normalize_continuity_fact_text(scenes[-1].get("body", "")) if scenes else ""
    if not reported_result or reported_result not in actual_body:
        findings.append(
            {
                "episode_num": episode_num,
                "issue": "last_scene_visible_result_unverifiable",
                "reported": reported.get("visible_result", ""),
                "actual_last_line": actual["visible_result"],
            }
        )

    bridge = str(
        (stage_output.get("state_update") or {}).get("next_episode_bridge", update.get("next_episode_bridge", "")),
    )
    completion_match = PREMATURE_BRIDGE_COMPLETION_RE.search(bridge)
    if (
        completion_match
        and _normalize_continuity_fact_text(completion_match.group(0)) not in _normalize_continuity_fact_text(script)
    ):
        findings.append(
            {
                "episode_num": episode_num,
                "issue": "next_episode_bridge_claims_unseen_completion",
                "claim": completion_match.group(0),
                "bridge": bridge,
            }
        )

    for scene in scenes:
        lines = [line.strip() for line in str(scene.get("body", "")).splitlines() if line.strip()]
        vo_speakers = {
            normalize_character_name(match.group("speaker"))
            for line in lines
            for match in [DIALOGUE_SPEAKER_RE.match(line)]
            if match and "VO" in line.upper()
        }
        for speaker in sorted(name for name in vo_speakers if name):
            visibly_present = any(
                _line_mentions_visible_action_role(line, speaker)
                or (
                    (dialogue_match := DIALOGUE_SPEAKER_RE.match(line)) is not None
                    and normalize_character_name(dialogue_match.group("speaker")) == speaker
                    and "VO" not in line.upper()
                )
                for line in lines
            )
            if visibly_present:
                findings.append(
                    {
                        "episode_num": episode_num,
                        "scene_id": scene.get("scene_id"),
                        "issue": "visible_character_uses_vo",
                        "speaker": speaker,
                    }
                )
    return findings


def validate_continuity_facts(stage_output: dict[str, Any], *, episode_num: Any = "<unknown>") -> None:
    """Handle validate continuity facts."""
    findings = continuity_fact_findings(stage_output, episode_num=episode_num)
    if findings:
        raise ValueError(f"episode {episode_num} continuity fact mismatch: {findings}")


def _split_scene_cast(cast_text: Any) -> list[str]:
    """Handle split scene cast."""
    names = []
    for part in re.split(r"[、,，/]+|和|及|与", str(cast_text or "")):
        name = normalize_character_name(part)
        if name:
            names.append(name)
    return sorted(set(names))


def _scene_plan_item_for_scene(episode_outline: dict[str, Any], scene_no: int) -> dict[str, Any]:
    """Handle scene plan item for scene."""
    scene_plan = episode_outline.get("scene_plan", [])
    if not isinstance(scene_plan, list):
        return {}
    for item in scene_plan:
        if not isinstance(item, dict):
            continue
        raw_no = item.get("scene_no")
        if str(raw_no).isdigit() and int(raw_no) == scene_no:
            return item
        if str(raw_no).strip().endswith(f"-{scene_no}"):
            return item
    return {}


def _scene_allows_same_setting_split(scene: dict[str, Any], episode_outline: dict[str, Any]) -> bool:
    """Handle scene allows same setting split."""
    plan_item = _scene_plan_item_for_scene(episode_outline, int(scene.get("scene_no", 0)))
    purpose = str(plan_item.get("scene_purpose", "")).strip()
    reason_text = str(plan_item.get("scene_boundary_reason", ""))
    body_text = str(scene.get("body", ""))
    if purpose in SCENE_BOUNDARY_PURPOSE_ALLOWLIST:
        return True
    return any(marker in body_text or marker in reason_text for marker in SCENE_BOUNDARY_REASON_MARKERS)


def _known_scene_cast_candidates(episode_outline: dict[str, Any], canonical_story_lock: dict[str, Any]) -> set[str]:
    """Handle known scene cast candidates."""
    candidates: set[str] = set()
    for value in canonical_story_lock.get("character_names", []) or []:
        name = normalize_character_name(value)
        if name:
            candidates.add(name)
    for key in ("required_character_names", "appearing_character_names"):
        for value in episode_outline.get(key, []) or []:
            name = normalize_character_name(value)
            if name:
                candidates.add(name)
    scene_plan = episode_outline.get("scene_plan", [])
    if isinstance(scene_plan, list):
        for item in scene_plan:
            if not isinstance(item, dict):
                continue
            for value in item.get("appearing_character_names", []) or []:
                name = normalize_character_name(value)
                if name:
                    candidates.add(name)
    candidates.update(VISIBLE_GENERIC_ROLE_NAMES)
    return candidates


def _line_mentions_visible_action_role(line: str, name: str) -> bool:
    """Handle line mentions visible action role."""
    if not line.strip().startswith("△"):
        return False
    if SCREEN_TEXT_ACTION_RE.match(line.strip()):
        return False
    if re.search(rf"{re.escape(name)}(?:的)?(名字|签名|名单|截图|消息|电话|来电|对话框)", line):
        return False
    if re.search(rf"(屏幕|截图|页面|字段|头像|姓名|发起人).{{0,24}}{re.escape(name)}", line):
        return False
    if re.search(rf"{re.escape(name)}.{{0,16}}(头像|姓名|截图|字段|发起人|发起投票|投票截图)", line):
        return False
    role_text = line
    if name in VISIBLE_GENERIC_ROLE_NAMES:
        suffix_pattern = "|".join(re.escape(suffix) for suffix in GENERIC_ROLE_LOCATION_SUFFIXES)
        role_text = re.sub(rf"{re.escape(name)}(?:{suffix_pattern})", "", role_text)
    return bool(re.search(rf"{re.escape(name)}[^，。！？；：\n]{{0,14}}{VISIBLE_ACTION_VERB_RE.pattern}", role_text))


def validate_scene_cast_members(
    scenes: list[dict[str, Any]],
    *,
    episode_outline: dict[str, Any],
    canonical_story_lock: dict[str, Any],
    episode_num: Any,
) -> None:
    """Handle validate scene cast members."""
    candidates = _known_scene_cast_candidates(episode_outline, canonical_story_lock)
    for scene in scenes:
        cast = set(scene.get("cast", []))
        missing: set[str] = set()
        for raw_line in str(scene.get("body", "")).splitlines():
            line = raw_line.strip()
            if not line or SCRIPT_SCENE_CAST_RE.match(line):
                continue
            speaker_match = DIALOGUE_SPEAKER_RE.match(line)
            if speaker_match:
                speaker = normalize_character_name(speaker_match.group("speaker"))
                if speaker and speaker not in cast:
                    missing.add(speaker)
            for candidate in candidates:
                if candidate not in cast and _line_mentions_visible_action_role(line, candidate):
                    missing.add(candidate)
        if missing:
            raise ValueError(
                (
                    f"episode {episode_num} final_script scene {scene['scene_id']} missing cast member(s): "
                    f"{sorted(missing)}"
                )
            )


def validate_dialogue_action_format(scenes: list[dict[str, Any]], *, episode_num: Any) -> None:
    """Handle validate dialogue action format."""
    for scene in scenes:
        for raw_line in str(scene.get("body", "")).splitlines():
            line = raw_line.strip()
            if DIALOGUE_WITH_TRIANGLE_RE.match(line):
                raise ValueError(
                    (
                        f"episode {episode_num} final_script scene {scene['scene_id']} dialogue line must not star"
                        f"t with △: {line}"
                    )
                )
            if not line or line.startswith(("△", "【")) or SCRIPT_SCENE_CAST_RE.match(line):
                continue
            if EMPTY_DIALOGUE_RE.match(line):
                raise ValueError(
                    f"episode {episode_num} final_script scene {scene['scene_id']} dialogue text is empty: {line}"
                )
            if ACTION_ONLY_DIALOGUE_RE.match(line):
                raise ValueError(
                    f"episode {episode_num} final_script scene {scene['scene_id']} dialogue text is action-only: {line}"
                )
            if BARE_DIALOGUE_RE.match(line):
                raise ValueError(
                    (
                        f"episode {episode_num} final_script scene {scene['scene_id']} dialogue missing action par"
                        f"entheses: {line}"
                    )
                )


def _phone_display_to_character(raw: Any) -> str:
    """Handle phone display to character."""
    text = str(raw or "").strip().strip("「」『』【】[]:：，。；;、 ")
    if not text:
        return ""
    parts = [part for part in re.split(r"[·・.．\-—_/\s]+", text) if part]
    return normalize_character_name(parts[-1] if parts else text)


def validate_internal_script_continuity(
    script: str,
    scenes: list[dict[str, Any]],
    *,
    canonical_story_lock: dict[str, Any],
    episode_num: Any,
) -> None:
    """Handle validate internal script continuity."""
    filing_done = list(FILING_DONE_RE.finditer(script))
    filing_upload = list(FILING_UPLOAD_RE.finditer(script))
    if (
        filing_done
        and filing_upload
        and min(match.start() for match in filing_upload) > min(match.start() for match in filing_done)
    ):
        raise ValueError(
            f"episode {episode_num} final_script filing timeline contradiction: already filed/备案 before later upload"
        )

    protagonist = normalize_character_name(canonical_story_lock.get("protagonist"))
    unanswered_calls: list[dict[str, str]] = []
    for scene in scenes:
        cast = set(scene.get("cast", []))
        recipient = protagonist if protagonist and protagonist in cast else ""
        lines = str(scene.get("body", "")).splitlines()
        for line_index, raw_line in enumerate(lines):
            line = raw_line.strip()
            for match in INCOMING_CALL_RE.finditer(line):
                caller = _phone_display_to_character(match.group("quoted_caller") or match.group("dash_caller"))
                if not caller or caller == recipient:
                    continue
                window = "\n".join(lines[line_index : line_index + 4])
                if recipient and CALL_REJECTED_RE.search(window):
                    unanswered_calls.append(
                        {"caller": caller, "recipient": recipient, "scene_id": str(scene["scene_id"])},
                    )
            for match in MISSED_INCOMING_RE.finditer(line):
                missed_from = _phone_display_to_character(match.group("caller"))
                if not missed_from:
                    continue
                for call in unanswered_calls:
                    if call["caller"] in cast and missed_from == call["recipient"]:
                        raise ValueError(
                            f"episode {episode_num} final_script phone direction contradiction: "
                            + (
                                f"{call['caller']} called {call['recipient']} without answer, but scene "
                                f"{scene['scene_id']} shows missed call from {missed_from}"
                            )
                        )


def validate_scene_location_coherence(scenes: list[dict[str, Any]], *, episode_num: Any) -> None:
    """Handle validate scene location coherence."""
    for scene in scenes:
        scene_location = str(scene.get("location", ""))
        interior_tokens = [
            token
            for token in DISJOINT_INTERIOR_SPACE_TOKENS
            if re.search(rf"{re.escape(token)}(?!外|门口|门边|方向)", scene_location)
        ]
        if len(interior_tokens) > 1 and not any(
            marker in scene_location for marker in CONNECTED_SPACE_EXEMPTIONS
        ):
            raise ValueError(
                (
                    f"episode {episode_num} final_script scene {scene['scene_id']} contains disjoint visible s"
                    f"paces: {interior_tokens}"
                )
            )
        for raw_line in str(scene.get("body", "")).splitlines():
            line = raw_line.strip()
            if not line.startswith("△"):
                continue
            if SCREEN_TEXT_ACTION_RE.match(line) or any(marker in line for marker in SCREEN_OR_TEXT_MARKERS):
                continue
            if not VISIBLE_ACTION_VERB_RE.search(line):
                continue
            for token in CONCRETE_LOCATION_TOKENS:
                if token in scene_location or token not in line:
                    continue
                if _line_mentions_location_as_document_object(line, token):
                    continue
                without_directional_reference = re.sub(
                    rf"{re.escape(token)}(?:{'|'.join(re.escape(suffix) for suffix in LOCATION_DIRECTION_SUFFIXES)})",
                    "",
                    line,
                )
                if token not in without_directional_reference:
                    continue
                raise ValueError(
                    f"episode {episode_num} final_script scene {scene['scene_id']} location break: "
                    f"scene location is {scene_location}, but line mentions visible action at {token}: {line}"
                )


def validate_scene_char_budget_execution(
    scenes: list[dict[str, Any]],
    *,
    episode_outline: dict[str, Any],
    episode_num: Any,
) -> None:
    """Handle validate scene char budget execution."""
    density = episode_outline.get("target_script_density")
    if not isinstance(density, dict):
        return
    raw_budgets = density.get("scene_char_budgets")
    if not isinstance(raw_budgets, list):
        return
    budgets = {
        int(item["scene_no"]): int(item["target_chars"])
        for item in raw_budgets
        if isinstance(item, dict)
        and str(item.get("scene_no", "")).isdigit()
        and isinstance(item.get("target_chars"), int)
    }
    overages: list[str] = []
    for scene in scenes:
        target = budgets.get(int(scene.get("scene_no", 0)))
        if not target:
            continue
        actual = len(re.sub(r"\s+", "", str(scene.get("body", ""))))
        allowed = max(target + 40, int(target * 1.2))
        if actual > allowed:
            overages.append(
                f"scene {scene['scene_id']} actual={actual}, target={target}, warning_limit={allowed}"
            )
    if overages:
        raise ValueError(
            f"episode {episode_num} final_script scene char budget exceeded: {'; '.join(overages)}"
        )


def _line_mentions_location_as_document_object(line: str, token: str) -> bool:
    """Handle line mentions location as document object."""
    suffix_pattern = "|".join(re.escape(suffix) for suffix in LOCATION_DOCUMENT_OBJECT_SUFFIXES)
    return bool(re.search(rf"{re.escape(token)}(?:{suffix_pattern})", line))


def _validate_adjacent_scene_boundaries(
    scenes: list[dict[str, Any]],
    *,
    episode_outline: dict[str, Any],
    episode_num: Any,
) -> None:
    """Handle validate adjacent scene boundaries."""
    for previous, current in zip(scenes, scenes[1:]):
        same_setting = (
            previous.get("location") == current.get("location")
            and previous.get("time") == current.get("time")
            and previous.get("space") == current.get("space")
        )
        same_cast = previous.get("cast") == current.get("cast")
        if same_setting and same_cast and not _scene_allows_same_setting_split(current, episode_outline):
            raise ValueError(
                f"episode {episode_num} final_script adjacent scenes {previous['scene_id']} and {current['scene_id']} "
                "repeat same setting and cast without flashback/intercut/time-jump reason"
            )


def validate_episode_scene_plan_boundaries(episode: dict[str, Any]) -> None:
    """Handle validate episode scene plan boundaries."""
    scene_plan = episode.get("scene_plan")
    if not isinstance(scene_plan, list) or len(scene_plan) < 2:
        return
    episode_id = episode.get("episode_num", "<unknown>")
    for previous, current in zip(scene_plan, scene_plan[1:]):
        if not isinstance(previous, dict) or not isinstance(current, dict):
            continue
        same_setting = (
            previous.get("location") == current.get("location")
            and previous.get("time") == current.get("time")
            and previous.get("space") == current.get("space")
        )
        same_cast = _scene_plan_cast(previous) == _scene_plan_cast(current)
        previous_cast = set(_scene_plan_cast(previous))
        current_cast = set(_scene_plan_cast(current))
        removed_cast = previous_cast - current_cast
        reason_text = " ".join(
            [
                str(current.get("scene_purpose", "")),
                str(current.get("scene_boundary_reason", "")),
                " ".join(str(beat) for beat in current.get("must_include_beats", []) or []),
            ]
        )
        if (
            same_setting
            and removed_cast
            and any(marker in reason_text for marker in VISIBLE_DOORWAY_EXIT_MARKERS)
            and not any(marker in reason_text for marker in EXPLICIT_OFFSCREEN_EXIT_MARKERS)
        ):
            raise ValueError(
                f"episode {episode_id} scene_plan adjacent scenes "
                f"{previous.get('scene_no')} and {current.get('scene_no')} "
                f"removes visible doorway cast member(s): {sorted(removed_cast)}"
            )
        if same_setting and same_cast and not _scene_plan_item_allows_split(current):
            raise ValueError(
                f"episode {episode_id} scene_plan adjacent scenes "
                f"{previous.get('scene_no')} and {current.get('scene_no')} "
                "repeat same setting and cast without flashback/intercut/time-jump reason"
            )


DISJOINT_INTERIOR_SPACE_TOKENS = (
    "卧室",
    "厨房",
    "卫生间",
    "客厅",
    "办公室",
    "会议室",
    "教室",
    "病房",
)
CONNECTED_SPACE_EXEMPTIONS = ("开放式", "连通", "隔门可见", "隔窗可见", "玻璃门可见")


def validate_episode_target_script_density(episode: dict[str, Any]) -> None:
    """Handle validate episode target script density."""
    episode_id = episode.get("episode_num", "<unknown>")
    density = episode.get("target_script_density")
    if not isinstance(density, dict):
        raise ValueError(f"episode {episode_id} target_script_density must be an object")
    beats = density.get("must_cover_beats")
    if not isinstance(beats, list) or not 1 <= len(beats) <= 3:
        raise ValueError(f"episode {episode_id} target_script_density must_cover_beats count must be 1-3")
    beat_ids: list[str] = []
    for index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            raise ValueError(
                f"episode {episode_id} target_script_density must_cover_beats[{index}] must be an object"
            )
        beat_id = str(beat.get("beat_id", "")).strip()
        if not beat_id:
            raise ValueError(
                f"episode {episode_id} target_script_density must_cover_beats[{index}] missing beat_id"
            )
        beat_ids.append(beat_id)
    if len(beat_ids) != len(set(beat_ids)):
        raise ValueError(f"episode {episode_id} target_script_density beat_id values must be unique")

    budgets = density.get("scene_char_budgets")
    if not isinstance(budgets, list) or not budgets:
        raise ValueError(f"episode {episode_id} target_script_density scene_char_budgets must be non-empty")
    scene_plan = episode.get("scene_plan") if isinstance(episode.get("scene_plan"), list) else []
    planned_scene_numbers = {
        int(item.get("scene_no"))
        for item in scene_plan
        if isinstance(item, dict) and str(item.get("scene_no", "")).isdigit()
    }
    budget_scene_numbers: list[int] = []
    assigned_beat_ids: list[str] = []
    total_chars = 0
    for index, budget in enumerate(budgets):
        if not isinstance(budget, dict):
            raise ValueError(
                f"episode {episode_id} target_script_density scene_char_budgets[{index}] must be an object"
            )
        scene_no = budget.get("scene_no")
        target_chars = budget.get("target_chars")
        if not str(scene_no).isdigit() or not isinstance(target_chars, int) or target_chars <= 0:
            raise ValueError(
                (
                    f"episode {episode_id} target_script_density scene_char_budgets[{index}] has invalid scene"
                    f"_no/target_chars"
                )
            )
        raw_ids = budget.get("must_cover_beat_ids")
        if not isinstance(raw_ids, list):
            raise ValueError(
                (
                    f"episode {episode_id} target_script_density scene_char_budgets[{index}].must_cover_beat_i"
                    f"ds must be a list"
                )
            )
        budget_scene_numbers.append(int(scene_no))
        total_chars += target_chars
        assigned_beat_ids.extend(str(item).strip() for item in raw_ids if str(item).strip())
    if planned_scene_numbers and set(budget_scene_numbers) != planned_scene_numbers:
        raise ValueError(
            f"episode {episode_id} target_script_density scene_char_budgets scene numbers "
            f"must match scene_plan: expected {sorted(planned_scene_numbers)}, got {sorted(set(budget_scene_numbers))}"
        )
    if len(budget_scene_numbers) != len(set(budget_scene_numbers)):
        raise ValueError(f"episode {episode_id} target_script_density scene_char_budgets scene_no must be unique")
    if sorted(assigned_beat_ids) != sorted(beat_ids):
        raise ValueError(
            f"episode {episode_id} target_script_density scene_char_budgets must assign each beat_id exactly once"
        )
    low, high = parse_numeric_range(str(density.get("target_range_chars", "")))
    if not low <= total_chars <= high:
        raise ValueError(
            (
                f"episode {episode_id} target_script_density scene_char_budgets total must be within {low}"
                f"-{high}, got {total_chars}"
            )
        )


def validate_episode_target_script_density_plans(episodes: list[dict[str, Any]]) -> None:
    """Handle validate episode target script density plans."""
    for episode in episodes:
        validate_episode_target_script_density(episode)


def validate_episode_scene_space_coherence(episode: dict[str, Any]) -> None:
    """Handle validate episode scene space coherence."""
    episode_id = episode.get("episode_num", "<unknown>")
    for scene in episode.get("scene_plan", []) or []:
        if not isinstance(scene, dict):
            continue
        if str(scene.get("time", "")).strip() not in {"日", "夜", "傍晚"}:
            raise ValueError(
                f"episode {episode_id} scene_plan scene {scene.get('scene_no')} time must be 日/夜/傍晚"
            )
        if str(scene.get("space", "")).strip() not in {"内", "外"}:
            raise ValueError(
                f"episode {episode_id} scene_plan scene {scene.get('scene_no')} space must be 内/外"
            )
        scene_beats = scene.get("must_include_beats")
        if not isinstance(scene_beats, list) or not 1 <= len(scene_beats) <= 2:
            raise ValueError(
                f"episode {episode_id} scene_plan scene {scene.get('scene_no')} must_include_beats count must be 1-2"
            )
        visible_tokens = [str(item).strip() for item in scene.get("visible_space_tokens", []) if str(item).strip()]
        interior_tokens = [
            token
            for token in DISJOINT_INTERIOR_SPACE_TOKENS
            if any(token in item for item in visible_tokens)
        ]
        reason_text = " ".join(
            [
                str(scene.get("location", "")),
                str(scene.get("scene_boundary_reason", "")),
                str(scene.get("scene_purpose", "")),
            ]
        )
        if len(interior_tokens) > 1 and not any(marker in reason_text for marker in CONNECTED_SPACE_EXEMPTIONS):
            raise ValueError(
                (
                    f"episode {episode_id} scene_plan scene {scene.get('scene_no')} contains disjoint visible "
                    f"spaces: {interior_tokens}"
                )
            )


def validate_episode_scene_space_coherence_plans(episodes: list[dict[str, Any]]) -> None:
    """Handle validate episode scene space coherence plans."""
    for episode in episodes:
        validate_episode_scene_space_coherence(episode)


def _scene_plan_cast(item: dict[str, Any]) -> list[str]:
    """Handle scene plan cast."""
    raw_names = item.get("appearing_character_names", [])
    if isinstance(raw_names, list):
        return sorted(
            {normalize_character_name(str(name)) for name in raw_names if normalize_character_name(str(name))},
        )
    return _split_scene_cast(raw_names)


def _scene_plan_item_allows_split(item: dict[str, Any]) -> bool:
    """Handle scene plan item allows split."""
    purpose = str(item.get("scene_purpose", "")).strip()
    reason_text = str(item.get("scene_boundary_reason", ""))
    if purpose in SCENE_BOUNDARY_PURPOSE_ALLOWLIST:
        return True
    return any(marker in reason_text for marker in SCENE_BOUNDARY_REASON_MARKERS)


def collect_final_script_quality_errors(
    script: str,
    *,
    episode_outline: dict[str, Any],
    canonical_story_lock: dict[str, Any],
    derived_config: dict[str, Any],
    stage_output: dict[str, Any] | None = None,
) -> list[str]:
    """Handle collect final script quality errors."""
    errors: list[str] = []
    required_names = episode_outline.get("required_character_names", [])
    missing_names = [name for name in required_names if name and not required_character_name_present(name, script)]
    episode_num = episode_outline.get("episode_num", "<unknown>")
    if missing_names:
        errors.append(f"episode {episode_num} final_script missing required character name(s): {missing_names}")

    malformed_scene_headings = [
        line.strip()
        for line in str(script or "").splitlines()
        if SCRIPT_SCENE_HEADING_LIKE_RE.match(line) and not SCRIPT_SCENE_HEADING_RE.match(line)
    ]
    for line in malformed_scene_headings:
        errors.append(f"episode {episode_num} final_script malformed scene heading: {line}")

    non_space_chars = len(re.sub(r"\s+", "", script))
    episode_int = _safe_int(episode_num, default=999999)
    word_cap = FRONT_EPISODE_WORD_CAP if 1 <= episode_int <= 3 else DEFAULT_EPISODE_WORD_CAP
    if non_space_chars > word_cap:
        errors.append(f"episode {episode_num} final_script word cap must be <= {word_cap}, got {non_space_chars}")
    idiom_findings = find_forbidden_script_idioms(script)
    for finding in idiom_findings:
        errors.append(
            (
                f"episode {episode_num} final_script contains forbidden script idiom {finding['pattern']}:"
                f" {finding['match']}"
            )
        )
    narration_usage = count_narration_devices(script)
    narration_plan = episode_outline.get("narration_device_plan", {})
    if isinstance(narration_plan, dict) and narration_plan:
        overages = []
        comparisons = (
            ("os_count", "planned_os_count"),
            ("flashback_count", "planned_flashback_count"),
            ("vo_count", "planned_vo_count"),
        )
        for actual_key, planned_key in comparisons:
            actual = narration_usage.get(actual_key, 0)
            planned = _safe_int(narration_plan.get(planned_key))
            if actual > planned:
                overages.append(f"{actual_key}={actual}>{planned_key}={planned}")
        if overages:
            errors.append(f"episode {episode_num} narration device usage exceeds episode plan: {', '.join(overages)}")
    reported_usage = (((stage_output or {}).get("continuity_update") or {}).get("narration_device_usage") or {})
    if isinstance(reported_usage, dict) and reported_usage:
        mismatches = []
        for key, actual in narration_usage.items():
            reported = _safe_int(reported_usage.get(key))
            if reported != actual:
                mismatches.append(f"{key}=reported {reported}, actual {actual}")
        if mismatches:
            errors.append(f"episode {episode_num} narration_device_usage mismatch: {', '.join(mismatches)}")

    scenes: list[dict[str, Any]] = []
    try:
        scenes = parse_final_script_scenes(script, episode_num=episode_num)
    except ValueError as exc:
        errors.append(str(exc))
    if scenes:
        scene_low, scene_high = parse_numeric_range(str(derived_config.get("scenes_per_episode", "1-99")))
        outline_scene_plan = episode_outline.get("scene_plan")
        if isinstance(outline_scene_plan, list) and outline_scene_plan:
            plan_count = len(outline_scene_plan)
            scene_low = min(scene_low, plan_count)
            scene_high = max(scene_high, plan_count)
        scene_count = len(scenes)
        if scene_count < scene_low or scene_count > scene_high:
            errors.append(
                (
                    f"episode {episode_num} final_script scene count must be within {scene_low}-{scene_high}, "
                    f"got {scene_count}"
                )
            )
        for check in (
            lambda: validate_dialogue_action_format(scenes, episode_num=episode_num),
            lambda: validate_scene_cast_members(
                scenes,
                episode_outline=episode_outline,
                canonical_story_lock=canonical_story_lock,
                episode_num=episode_num,
            ),
            lambda: validate_scene_location_coherence(scenes, episode_num=episode_num),
            lambda: validate_scene_char_budget_execution(
                scenes,
                episode_outline=episode_outline,
                episode_num=episode_num,
            ),
            lambda: _validate_adjacent_scene_boundaries(
                    scenes,
                    episode_outline=episode_outline,
                    episode_num=episode_num,
                ),
            lambda: validate_internal_script_continuity(
                script,
                scenes,
                canonical_story_lock=canonical_story_lock,
                episode_num=episode_num,
            ),
        ):
            try:
                check()
            except ValueError as exc:
                errors.append(str(exc))
    else:
        scene_low, scene_high = parse_numeric_range(str(derived_config.get("scenes_per_episode", "1-99")))
        if scene_low > 0:
            errors.append(
                f"episode {episode_num} final_script scene count must be within {scene_low}-{scene_high}, got 0",
            )

    canonical_names = set(canonical_story_lock.get("character_names", []))
    protagonist = canonical_story_lock.get("protagonist")
    if protagonist and not required_character_name_present(protagonist, script):
        errors.append(f"episode {episode_num} final_script must include protagonist name: {protagonist}")
    if canonical_names and not any(required_character_name_present(name, script) for name in canonical_names):
        errors.append(f"episode {episode_num} final_script must include at least one canonical character name")
    forbidden_markers = [marker for marker in FORBIDDEN_SCRIPT_MARKERS if marker in script]
    if forbidden_markers:
        errors.append(f"episode {episode_num} final_script contains forbidden cinematic marker(s): {forbidden_markers}")
    return errors


def validate_final_script_quality(
    script: str,
    *,
    episode_outline: dict[str, Any],
    canonical_story_lock: dict[str, Any],
    derived_config: dict[str, Any],
    stage_output: dict[str, Any] | None = None,
) -> None:
    """Handle validate final script quality."""
    errors = collect_final_script_quality_errors(
        script,
        episode_outline=episode_outline,
        canonical_story_lock=canonical_story_lock,
        derived_config=derived_config,
        stage_output=stage_output,
    )
    if errors:
        raise ValueError("; ".join(errors))
