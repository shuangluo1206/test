"""Utilities for the short novel script pipeline."""
from __future__ import annotations

from typing import Any


LOCALIZATION_VERSION = "zh_contract_v7"

FIELD_LABELS: dict[str, str] = {
 'novel_profile': '小说画像',
 'genre': '故事类型',
 'core_conflict_type': '核心冲突类型',
 'target_audience': '目标受众',
 'adaptation_risks': '改编风险',
 'recommended_run_config': '推荐全局配置',
 'recommendation_reasons': '推荐理由',
 'default_run_config': '默认全局配置',
 'user_overrides': '用户指定参数',
 'source_anchor_id': '原文锚点ID',
 'start_char': '原文起始字符位置',
 'end_char': '原文结束字符位置',
 'text': '原文内容',
 'source_anchors': '原文锚点表',
 'adaptation_capacity': '改编容量评估',
 'dramatic_release_map': '全季戏剧释放图',
 'release_overview': '全季释放概览',
 'episode_dramatic_targets': '逐集戏剧释放目标',
 'capacity_bridge_units': '容量扩写桥接单元',
 'opening_gate': '开篇戏剧门禁',
 'natural_capacity_max': '自然容量最大集数',
 'capacity_gap': '容量扩写缺口',
 'opening_strategy': '开篇释放策略',
 'process_compression_strategy': '流程节点压缩策略',
 'release_id': '释放目标ID',
 'obstacle': '戏剧阻力',
 'choice': '戏剧选择',
 'immediate_cost': '即时代价',
 'confrontation_mode': '对抗方式',
 'process_only': '是否纯流程',
 'required_event_function': '所需事件功能',
 'expansion_engine_id': '扩写发动机ID',
 'bridge_id': '桥接单元ID',
 'new_goal': '新增目标',
 'new_obstacle': '新增阻力',
 'new_choice': '新增选择',
 'new_cost': '新增代价',
 'new_result': '新增结果',
 'source_boundary': '原著扩写边界',
 'first_three_live_obstacle_count': '前三集现场人物阻力数',
 'first_five_process_only_count': '前五集纯流程数',
 'required_early_source_fact_ids': '前段必用原著事实ID',
 'gate_reason': '门禁原因',
 'dramatic_target_ids': '戏剧释放目标ID列表',
 'dramatic_target_id': '戏剧释放目标ID',
 'dramatic_target': '本集不可变戏剧目标',
 'independent_conflict_unit_count': '独立冲突单元数',
 'natural_episode_range': '自然集数区间',
 'min': '最小值',
 'max': '最大值',
 'target_episode_gap': '目标集数缺口',
 'expansion_pressure': '扩写压力',
 'required_new_engines': '需补充剧情发动机',
 'source_fact_ledger': '原著事实账本',
 'source_fact_ids': '原著事实ID',
 'reserved_fact_ids': '保留事实ID',
 'actor': '行动主体',
 'object': '行动对象',
 'result': '可核验结果',
 'source_anchor_ids': '原文锚点ID列表',
 'certainty': '事实确定性',
 'interpretation_note': '改编解释备注',
 'dramatic_delta': '戏剧状态变化',
 'dimension': '变化维度',
 'before': '变化前',
 'after': '变化后',
 'why_not_repetition': '非重复说明',
 'prop_registry': '关键道具实体表',
 'entity_kind': '实体类型',
 'created_episode': '创建集数',
 'activation_episode': '激活集数',
 'initial_state': '初始状态',
 'declared_created_episode': '声明创建集数',
 'activation_transaction_ids': '激活事务ID',
 'activated_episode': '实际激活集数',
 'created_from_event_id': '来源事件ID',
 'replaces_prop_id': '替代道具ID',
 'parent_container_id': '父容器ID',
 'terminal_states': '终止状态',
 'adaptation_capacity_warning': '改编容量预警',
 'natural_max_episodes': '自然最大集数',
 'gap': '容量缺口',
 'strategy': '扩容策略',
 'allowed_active_strategies': '主角允许主动策略',
 'must_preserve_fact_ids': '必须保留事实ID',
 'story_time': '故事时间',
 'day_index': '故事日序号',
 'time_label': '时间标记',
 'elapsed_from_previous': '距上集时间',
 'fact_transitions': '事实状态变更',
 'last_story_time': '上批最后故事时间',
 'current_fact_status': '当前事实状态表',
 'from_status': '变更前状态',
 'to_status': '变更后状态',
 'schema_version': '契约版本',
 'audience_fact_changes': '观众事实变更',
 'character_knowledge_changes': '角色认知变更',
 'character_name': '变更角色姓名',
 'private_fact_changes': '作者私有事实变更',
 'completed_beat_ids': '已完成节拍ID',
 'completed_effect_evidence': '已完成效果正文证据',
 'evidence_span': '正文证据片段',
 'completed_transaction_digest': '已完成事务摘要',
 'completed_effect_digest': '已完成效果摘要',
 'state_block_count': '状态阻断次数',
 'foreshadowing_changes': '伏笔变更',
 'open_thread_changes': '未解决线索变更',
 'prop_state_changes': '关键道具状态变更',
 'operation': '变更操作',
 'evidence': '正文证据',
 'fact_id': '事实ID',
 'thread_id': '线索ID',
 'episode_execution_sheet': '本集去重执行单',
 'recent_episode_scripts': '最近三集完整剧本',
 'active_continuity_view': '当前有效连续性状态',
 'future_event_reservations': '后续事件保留表',
 'relevant_source_context': '本集相关原著与边界',
 'source_voice_anchors': '源文语气锚点',
 'audience_facts': '当前观众已知事实',
 'character_knowledge': '当前角色认知',
 'private_facts': '当前作者私有事实',
 'foreshadowing': '当前伏笔',
 'props': '当前道具',
 'source_facts': '本集原著事实',
 'approved_time_deviations': '本集获批时间线手法',
 'adaptation_direction': '改编方向',
 'adapted_plot_point_ids': '改编情节点ID',
 'allowed': '允许范围',
 'allowed_functions': '允许功能',
 'allowed_same_setting_splits': '允许同场景拆分',
 'appearing_character_names': '出场人物姓名',
 'applicable_arc_ids': '适用弧线ID',
 'asset_id': '资产ID',
 'audience_known': '观众已知信息',
 'audience_known_after_episode': '本集后观众已知信息',
 'available_event_ids': '可用事件ID',
 'block_event_plan': '篇章事件计划',
 'block_id': '篇章ID',
 'block_plans': '篇章计划',
 'block_state_plan': '篇章状态交接计划',
 'boundary_check': '边界检查',
 'boundary_risk': '边界风险',
 'can_expand': '可扩展内容',
 'canonical_story_lock': '故事锁定信息',
 'chapter_id': '章节ID',
 'chapter_summaries': '章节梗概',
 'char_count': '字符数',
 'change_principles': '改编原则',
 'change_type': '变化类型',
 'character_action_boundaries': '人物行动边界',
 'character_bible': '人物小传',
 'character_expandability': '人物扩写空间',
 'character_known': '角色已知信息',
 'character_known_after_episode': '本集后角色已知信息',
 'character_names': '角色姓名',
 'character_state_curve': '人物状态曲线',
 'characters': '相关人物',
 'climax_guardrails': '高潮护栏',
 'closing_beat': '收尾情节',
 'completed_beats': '已完成情节',
 'completed_beats_digest': '已完成情节摘要',
 'compaction_policy': '压缩策略',
 'conflict_engine': '冲突引擎',
 'conflict_mode': '冲突模式',
 'conflict_mode_used': '已使用冲突模式',
 'content_sensitivity_check': '内容敏感检查',
 'content_sensitivity_risk': '内容敏感风险',
 'content_summary': '内容摘要',
 'counterattack': '反击点',
 'cumulative_a_quota_count': '累计A级配额数',
 'cumulative_consumed_child_beat_ids': '已累计消耗子情节点ID',
 'decision': '处理决策',
 'deleted_time_deviations': '删除的时间线偏离',
 'deleted_or_rewritten_time_deviation_ids': '删除或顺叙改写的时间线偏离ID',
 'delta_from_source': '相对原著变化',
 'dramatic_goal': '戏剧目标',
 'dramatic_action': '剧情动作',
 'empty_list': '空数组',
 'empty_object': '空对象',
 'end': '结束',
 'end_episode': '结束集数',
 'ending_hook': '结尾钩子',
 'episode_allocation': '集数分配',
 'episode_budget': '集数预算',
 'episode_count': '集数',
 'episode_num': '集号',
 'episode_outlines': '分集大纲',
 'episode_range': '集数范围',
 'episode_reason': '本集作用',
 'event_consumption_status': '事件消耗状态',
 'event_ids': '事件ID',
 'valid_event_ids': '合法事件ID',
 'assigned_event_id': '已分配事件ID',
 'assigned_child_beat_ids': '已分配子情节点ID',
 'event_pool': '事件池',
 'event_release_principles': '事件释放原则',
 'event_release_schedule': '事件释放计划',
 'event_role': '事件作用',
 'expanded_character_network': '扩展人物网络',
 'expansion_assets': '扩写资产',
 'expansion_delta': '扩写增量',
 'expansion_type': '扩写类型',
 'expected_episode_span': '预期覆盖集数',
 'final_script': '最终剧本正文',
 'flashback_count': '闪回次数',
 'flashback_overview': '闪回筛选概览',
 'flashback_screening': '闪回筛选',
 'foreshadowing_ids': '伏笔ID',
 'foreshadowing_plan': '伏笔计划',
 'foreshadowing_pool': '伏笔池',
 'foreshadowing_status': '伏笔状态',
 'forbidden_changes': '禁止改动',
 'forbidden_early_events': '禁止提前释放事件',
 'function': '功能',
 'genre_tags': '类型标签',
 'global_outline': '全季大纲',
 'goal': '目标',
 'grade': '等级',
 'handoff_to_next_block': '交接到下一篇章',
 'hook': '钩子',
 'hook_strategy': '钩子策略',
 'id': 'ID',
 'impact_on_story': '对故事影响',
 'importance_level': '重要级别',
 'information_gain': '信息增量',
 'is_epilogue': '是否尾声',
 'key_events': '关键事件',
 'legal_moral_risk': '法律道德风险',
 'location': '地点',
 'longform_blocks': '长篇篇章',
 'longform_strategy': '长篇扩写策略',
 'main_confrontation': '主要对抗',
 'macro_arcs': '宏观弧线',
 'major_climax_window': '大高潮窗口',
 'main_conflict': '主要冲突',
 'mapping_trace': '映射链路',
 'market_tag_priority': '市场标签优先级',
 'max_episodes': '最大集数',
 'merge_note': '合并说明',
 'mitigation': '缓解措施',
 'must_include_beats': '必须包含情节',
 'must_keep': '必须保留要素',
 'must_preserve': '必须保留内容',
 'name': '姓名',
 'narration_device_plan': '叙事手法计划',
 'narration_device_usage': '叙事手法实际使用',
 'new_a_quota_count': '新增A级配额数',
 'next_episode_bridge': '下一集桥接',
 'next_episode_start_state': '下一集开场状态',
 'not_after_episode': '不得晚于集数',
 'not_before_episode': '不得早于集数',
 'novel_summary': '原著摘要',
 'open_foreshadowing': '开放伏笔',
 'open_threads': '全局未解决线索',
 'opening_beat': '开场情节',
 'opening_continuity_check': '开场连续性检查',
 'original_expansion_ratio': '原创扩写比例',
 'originality_boundary': '原创边界',
 'os_count': 'OS次数',
 'overall_status': '整体状态',
 'pattern_family': '模式家族',
 'payoff_level': '回收级别',
 'per_episode_check': '单集检查方式',
 'phase': '阶段',
 'phase_breakdown': '阶段拆解',
 'planned_flashback_count': '计划闪回次数',
 'planned_flashback_quota_count': '计划闪回配额数',
 'planned_os_count': '计划OS次数',
 'planned_vo_count': '计划VO次数',
 'position': '位置',
 'pressure_templates': '施压模板',
 'principle': '原则',
 'protagonist': '主角',
 'protagonist_action': '主角行动',
 'protagonist_action_boundary': '主角行动边界',
 'prop_positions': '道具位置',
 'prop_identity_conflicts': '道具身份冲突',
 'lifecycle_status': '生命周期状态',
 'existing_prop_name': '原道具名称',
 'incoming_prop_name': '冲突道具名称',
 'conflict_episode_num': '冲突集号',
 'prop_continuity_plan': '关键道具连续性计划',
 'prop_state_updates': '关键道具状态更新',
 'prop_id': '道具ID',
 'prop_name': '道具名称',
 'start_holder': '开始持有人',
 'start_location': '开始位置',
 'end_holder': '结束持有人',
 'end_location': '结束位置',
 'transfer_action': '转移动作',
 'holder': '当前持有人',
 'change_evidence': '变化证据',
 'q1_structure_necessity': 'Q1结构必要性',
 'q2_information_necessity': 'Q2信息必要性',
 'qa_rules': 'QA规则',
 'quota_count': '配额计数',
 'quota_limit': '配额上限',
 'quota_policy': '配额策略',
 'reason': '原因',
 'remaining_quota': '剩余配额',
 'required_character_names': '必需人物姓名',
 'reserved_payoff': '保留回收',
 'retained_time_deviations': '保留的时间线偏离',
 'retention_rules': '保留规则',
 'rewrite_time_deviations': '改写的时间线偏离',
 'risk_examples': '风险示例',
 'risk_level': '风险级别',
 'risk_note': '风险说明',
 'risk_reason': '风险原因',
 'risk_response': '风险应对',
 'same_setting_split_count': '同场景拆分次数',
 'scene_boundary_check': '分场边界检查',
 'scene_boundary_reason': '分场理由',
 'scene_count': '场次数',
 'scene_no': '场次编号',
 'scene_plan': '分场计划',
 'scene_purpose': '场次目的',
 'script_tail': '剧本结尾片段',
 'selected_storyline': '选定故事线',
 'source_anchor': '原著锚点',
 'source_anchor_executed': '已执行原著锚点',
 'source_anchor_goal': '原著锚点目标',
 'source_asset_ids': '原著资产ID',
 'source_evidence': '原著证据',
 'source_plot_point_ids': '原著情节点ID',
 'source_plot_points': '原著情节点',
 'source_preservation_contract': '原著保留契约',
 'source_retention_ratio': '原著保留比例',
 'source_type': '来源类型',
 'space': '内外空间',
 'stage_antagonist': '阶段反派',
 'start': '开始',
 'start_episode': '开始集数',
 'state_change': '状态变化',
 'state_delta': '状态增量',
 'state_update': '状态更新',
 'story_engine': '故事发动机',
 'storyline_candidates': '故事线候选',
 'summary': '摘要',
 'tag': '标签',
 'target_block': '目标篇章',
 'target_script_density': '目标剧本密度',
 'target_tone': '目标基调',
 'template_id': '模板ID',
 'template_name': '模板名称',
 'time': '时间',
 'title': '标题',
 'total_time_deviation_count': '时间线偏离总数',
 'unresolved_threads_after_episode': '本集后未解决线索',
 'used_quota': '已用配额',
 'visible_space_tokens': '可见空间词',
 'variant_examples': '变体示例',
 'visible_result': '末场可见结果',
 'visual_replacement_strategy': '视觉化替代策略',
 'visualized_time_deviation_ids': '视觉化处理的时间线偏离ID',
 'vo_count': 'VO次数',
 'why': '判断原因',
 'why_allowed': '允许原因',
 'writer_private': '作者私有信息',
 '_chunk_count': '分批总数',
 '_chunk_index': '分批序号',
 '_source_block': '来源篇章',
 '_source_block_id': '来源篇章ID',
 'a_count': 'A级数量',
 'action': '动作',
 'added_mentioned_names': '补充提及人物',
 'antagonist': '反派',
 'antagonist_line': '反派线',
 'antagonists': '反派状态',
 'anti_monotony_rules': '反单调规则',
 'approved_flashback_time_deviation_ids': '获批闪回时间线偏离ID',
 'approved_os_time_deviation_ids': '获批OS时间线偏离ID',
 'approved_time_deviation_ids': '获批时间线偏离ID',
 'active_prop_registry': '当前关键道具注册表',
 'arc_id': '弧线ID',
 'b_count': 'B级数量',
 'block_plan': '篇章分批计划',
 'c_count': 'C级数量',
 'camp': '阵营',
 'can_change': '可改变项',
 'cannot_change': '不可改变项',
 'character_name_repair_trace': '人物名修复记录',
 'child_beats': '子情节点',
 'child_beat_id': '子情节点ID',
 'preconditions': '前置状态',
 'effects': '状态效果',
 'forbidden_early_effects': '提前禁止效果',
 'completion_evidence_terms': '完成证据词',
 'can_share_episode_with_next': '可与下一事务同集',
 'state_ref': '状态引用',
 'expected_state': '预期状态',
 'effect_id': '效果ID',
 'effect_ids': '效果ID列表',
 'process_transition': '流程状态迁移',
 'process_id': '流程ID',
 'from_stage': '流程开始阶段',
 'to_stage': '流程结束阶段',
 'effect_type': '效果类型',
 'subject': '效果主体',
 'evidence_terms': '证据词',
 'transaction_contract': '本集事务执行契约',
 'transaction_schedule': '事件事务排期',
 'transaction_id': '事务ID',
 'owner_event_id': '所属事件ID',
 'owner_block_id': '所属篇章ID',
 'owner_episode': '所属集数',
 'authorized_transaction_ids': '本集授权事务ID',
 'authorized_transactions': '本集授权事务',
 'forbidden_future_transactions': '禁止提前执行的后续事务',
 'completed_episode_range': '已完成集数范围',
 'conflict': '冲突',
 'conflict_modes': '冲突模式列表',
 'consumed_child_beats': '已消耗子情节点',
 'consumed_child_beat_ids': '已消耗子情节点ID',
 'continuity_update': '连续性更新',
 'core_conflict': '核心冲突',
 'core_hook': '核心钩子',
 'core_hook_structure': '核心钩子结构',
 'counterattack_templates': '反击模板',
 'desire': '欲望',
 'detail': '说明',
 'direction': '方向',
 'downstream_lock': '下游锁定',
 'dramatic_function': '戏剧功能',
 'emotion': '情绪',
 'emotion_line': '情绪线',
 'emotional_debt_chain': '情绪债链',
 'emotional_debts': '情绪债',
 'entry_state': '进入状态',
 'epilogue_budget': '尾声预算',
 'epilogue_max_episodes': '尾声最大集数',
 'episode_window': '事件集数窗口',
 'event': '事件',
 'event_window_repair_trace': '事件窗口修复记录',
 'exit_state': '退出状态',
 'expand_space': '扩写空间',
 'expansion_strategy': '扩写策略',
 'expansion_value': '扩写价值',
 'fear': '恐惧',
 'field': '字段',
 'final_climax_not_before_episode': '最终高潮不得早于集数',
 'growth_line': '成长线',
 'immutable_elements': '不可改元素',
 'key_relation': '关键关系',
 'main_line': '主线',
 'maximum_chars': '最大字数',
 'minimum_effective_chars': '最低有效字数',
 'mislead': '误导',
 'must_cover_beats': '必覆盖情节',
 'must_cover_beat_ids': '必覆盖节拍ID',
 'must_use_event_ids': '必须使用事件ID',
 'next_block_handoff': '下一篇章交接',
 'last_closing_state': '上一集收尾状态',
 'last_episode_title': '上一集标题',
 'last_two_episode_summaries': '最近两集摘要',
 'last_episode_num': '上一集集号',
 'last_updated_episode_num': '最近更新集号',
 'updated_episode': '更新来源集数',
 'last_scene_state': '末场事实',
 'carries_forward_event_ids': '承接事件ID',
 'carries_forward_foreshadowing_ids': '承接伏笔ID',
 'next_hook': '下一钩子',
 'older_episode_detail': '更早分集处理',
 'opening_priority': '开场优先规则',
 'optional_compression_beats': '可压缩情节',
 'beat_id': '节拍ID',
 'completion_evidence': '完成证据',
 'scene_char_budgets': '分场字数预算',
 'target_chars': '目标字数',
 'payoff': '回收',
 'payoff_target': '回收目标',
 'payoff_after_episode': '回收所在集后',
 'potential_subplots': '潜在支线',
 'present_character_names': '末场在场人物姓名',
 'pressure_source': '压力来源',
 'primary_conflict': '首要冲突',
 'quote_or_summary': '引用或摘要',
 'recurring_hook_mechanism': '循环钩子机制',
 'related_arc': '相关弧线',
 'relationship': '关系',
 'relationship_changes': '关系变化',
 'relationship_pressure': '关系压力',
 'resolution': '收束阶段',
 'repaired_window': '修复后窗口',
 'replacement_strategy_used': '已使用替代策略',
 'reversal_templates': '反转模板',
 'risk': '风险',
 'role': '角色功能',
 'running_character_state': '运行中人物状态',
 's_count': 'S级数量',
 'secret': '秘密',
 'secret_chain': '秘密链',
 'setup': '设置',
 'source_fact': '原著事实',
 'source_hint': '原著提示',
 'source_role': '原著角色功能',
 'source_traits': '原著特征',
 'status': '状态',
 'step': '步骤',
 'storyline': '故事线',
 'strength': '优势',
 'subplot_lines': '支线列表',
 'supports': '支持内容',
 'target_range_chars': '目标字数区间',
 'undeveloped_characters': '未展开人物',
 'unresolved_threads': '当前未解决线索',
 'weakness': '弱点',
 'asset': '资产',
 'act1': '第一幕',
 'act2a': '第二幕前半',
 'act2b': '第二幕后半',
 'act3': '第三幕',
 'beginning': '起始阶段',
 'climax': '高潮',
 'cycle_span': '循环跨度',
 'ending': '结局',
 'emotional_spine': '情绪主轴',
 'entry_point': '切入点',
 'escalation_logic': '升级逻辑',
 'escalation_path': '升级路径',
 'escalation': '升级阶段',
 'expansion_potential': '扩写潜力',
 'item': '事项',
 'opening': '开局',
 'phase_1_oppression': '第一段压迫',
 'phase_2_counterattack': '第二段反击',
 'phase_3_reversal': '第三段反转',
 'phase_4_reward_and_new_hook': '第四段奖励与新钩子',
 'potential': '潜力',
 'premise': '故事前提',
 'preview': '内容预览',
 'previous_block_id': '上一篇章ID',
 'previous_ending_hook': '上一集结尾钩子',
 'previous_source_anchor_executed': '上一集已执行原著锚点',
 'type': '类型',
 'victory_condition': '胜利条件',
 'run_config': '全局运行配置',
 'derived_config': '系统派生规则',
 'target_episodes': '目标集数',
 'episode_duration_seconds': '单集时长秒数',
 'rewrite_intensity': '改写强度',
 'character_background_policy': '人物背景策略',
 'subplot_policy': '支线策略',
 'new_character_policy': '新增人物策略',
 'source_preservation_level': '原著保留级别',
 'source_boundary_mode': '原著边界模式',
 'pacing_controls': '节奏控制',
 'market_tags': '市场标签',
 'mode': '模式',
 'block_count': '篇章数量',
 'episodes_per_block': '每篇章集数',
 'subplot_budget': '支线预算',
 'new_character_budget': '新增人物预算',
 'event_reuse_max_episodes': '事件最多复用集数',
 'conflict_mode_streak_limit': '冲突模式连续上限',
 'cross_block_bridge_max_episodes': '跨篇章桥接集数上限',
 'scenes_per_episode': '单集自然场数',
 'script_length_chars': '剧本目标字数',
 'event_pool_size': '事件池规模',
 'foreshadowing_density': '伏笔密度',
 'source_text': '小说全文',
 'chapter_chunks': '章节切分',
 'naming_rule': '人物命名规则',
 'previous_context': '前情上下文',
 'character_state': '人物状态',
 'compact_continuity_context': '压缩连续性上下文',
 'remaining_episode_plan': '剩余分集计划摘要',
 'recent_conflict_modes': '最近冲突模式',
 'recent_episode_detail_count': '最近明细集数',
 'recent_episode_summaries': '最近分集摘要',
 'previous_next_bridge': '上一集桥接点',
 'last_script_tail': '上一集剧本结尾',
 'last_script_head': '上一集剧本开头',
 'already_completed_beats': '已完成情节清单',
 'generated_episode_summaries': '已生成分集摘要',
 'recent_episode_details': '最近分集明细',
 'completed_beat_digest': '已完成情节简表',
 'episode_outline': '本集分集大纲',
 'episode_event_options': '逐集合法事件选项',
 'episode_planning_scope': '本次分集规划范围',
 'global_target_episodes': '全剧目标集数',
 'current_block': '当前篇章',
 'previous_handoff': '上一批交接',
 'next_block_target': '下一篇章目标',
 'parent_block_episode_range': '父篇章集数范围',
 'parent_block_goal': '父篇章总目标',
 'parent_block_hook': '父篇章总钩子',
 'chunk_is_parent_block_end': '本批是否父篇章末批',
 'next_chunk_episode_range': '下一批集数范围',
 'output_contract': '输出契约',
 'top_level_keys': '顶层字段',
 'episode_num_rule': '集号规则',
 'merge_rule': '合并规则',
 'episode_planning_fanout': '分集规划分批信息',
 'block_output_hashes': '分批输出哈希',
 'input_keys': '输入字段',
 'input_value_hashes': '输入值哈希',
 'prompt_schema_locale': '提示词字段语言',
 'localization_version': '本地化版本'}

PROMPT_PLACEHOLDER_ALIASES: dict[str, str] = {'全局运行配置': 'run_config',
 '全季戏剧释放图': 'dramatic_release_map',
 '系统派生规则': 'derived_config',
 '目标集数': 'target_episodes',
 '默认全局配置': 'default_run_config',
 '用户指定参数': 'user_overrides',
 '小说全文': 'source_text',
 '章节切分': 'chapter_chunks',
 '小说摘要结果': 'novel_summary',
 '关键事件': 'key_events',
 '所选主线': 'selected_storyline',
 '源情节点': 'source_plot_points',
 '人物小传': 'character_bible',
 '市场标签': 'market_tags',
 '输入类型': 'source_type',
 '已用A级配额': 'used_quota',
 '章节梗概': 'chapter_summaries',
 '改编方向': 'adaptation_direction',
 '源故事锁': 'canonical_story_lock',
 '闪回筛选结果': 'flashback_screening',
 '篇章级剧情弧': 'macro_arcs',
 '中型事件池': 'event_pool',
 '冲突发动机': 'conflict_engine',
 '扩展人物网络': 'expanded_character_network',
 '伏笔池': 'foreshadowing_pool',
 '全剧大纲': 'global_outline',
 '长篇篇章卡段': 'longform_blocks',
 '篇章拆解': 'phase_breakdown',
 '集数预算': 'episode_budget',
 '事件释放表': 'event_release_schedule',
 '篇章事件计划': 'block_event_plan',
 '高潮与尾声护栏': 'climax_guardrails',
 '篇章状态计划': 'block_state_plan',
 '质量规则': 'qa_rules',
 '逐集合法事件选项': 'episode_event_options',
 '单集大纲': 'episode_outline',
 '剩余分集计划摘要': 'remaining_episode_plan',
 '最近冲突模式': 'recent_conflict_modes',
 '主角行为边界': 'protagonist_action_boundary',
 '前情上下文': 'previous_context',
 '人物状态': 'character_state',
 '压缩连续性上下文': 'compact_continuity_context',
 '原文锚点表': 'source_anchors',
 '原著事实账本': 'source_fact_ledger',
 '改编容量评估': 'adaptation_capacity',
 '关键道具实体表': 'prop_registry',
 '本集去重执行单': 'episode_execution_sheet',
 '最近三集完整剧本': 'recent_episode_scripts',
 '当前有效连续性状态': 'active_continuity_view',
 '后续事件保留表': 'future_event_reservations',
 '本集相关原著与边界': 'relevant_source_context',
 '源文语气锚点': 'source_voice_anchors'}

ENUM_VALUE_ALIASES_BY_FIELD: dict[str, dict[str, str]] = {
 'operation': {'add': '新增', 'update': '更新', 'resolve': '解决', 'retire': '终止'},
 'from_status': {'unknown': '未知', 'suspected': '怀疑', 'known': '已知', 'confirmed': '已确认', 'resolved': '已解决'},
 'to_status': {'unknown': '未知', 'suspected': '怀疑', 'known': '已知', 'confirmed': '已确认', 'resolved': '已解决'},
 'certainty': {'explicit': '原著明示', 'inferred': '合理推断', 'ambiguous': '原著有歧义'},
 'expansion_pressure': {'low': '低', 'medium': '中', 'high': '高'},
 'dimension': {'goal': '目标', 'resource': '资源', 'power': '权力', 'secret': '秘密', 'relationship': '关系'},
 'rewrite_intensity': {'light': '轻度', 'balanced': '平衡', 'heavy': '重度'},
 'character_background_policy': {'keep': '保持原设', 'minor_adjust': '小幅调整', 'allow_rewrite': '允许重写'},
 'subplot_policy': {'none': '不新增支线', 'moderate': '适量支线', 'aggressive': '多支线'},
 'new_character_policy': {'limited': '少量新增', 'controlled': '控制新增', 'open': '开放新增'},
 'source_preservation_level': {'core_hook': '保留核心梗', 'core_plot': '保留核心情节', 'character_strict': '严格保留人物'},
 'source_boundary_mode': {'strict_source_anchor': '严格原著锚点', 'balanced_spark': '平衡强化', 'heavy_rewrite': '重度改写'},
 'foreshadowing_density': {'low': '低', 'medium': '中', 'high': '高'},
 'risk_level': {'low': '低', 'medium': '中', 'high': '高'},
 'legal_moral_risk': {'low': '低', 'medium': '中', 'high': '高'},
 'content_sensitivity_risk': {'low': '低', 'medium': '中', 'high': '高'},
 'boundary_risk': {'low': '低', 'medium': '中', 'high': '高'},
 'expansion_type': {'strengthen': '强化原情节', 'new_bridge': '新增桥段', 'new_expansion': '新增扩写'},
 'scene_purpose': {'pressure': '施压',
                   'counterattack': '反击',
                   'hook': '钩子',
                   'flashback': '闪回',
                   'intercut': '交叉剪辑',
                   'parallel_action': '并行动作'},
 'event_role': {'setup': '铺垫', 'escalation': '升级', 'payoff': '回收'},
 'event_consumption_status': {'setup': '铺垫',
                              'ongoing': '进行中',
                              'partial': '部分完成',
                              'completed': '已完成',
                              'block_payoff': '篇章回收'},
 'payoff_level': {'setup_or_turn': '铺垫或转折', 'block_payoff': '篇章回收', 'final_climax': '终局高潮'},
 'mode': {'internal_block': '内部分批', 'internal_fanout_merge': '本地分批合并'},
 'confrontation_mode': {'live_character': '现场人物对抗', 'environment': '环境阻力', 'process': '制度流程'},
 'from_stage': {
         'not_started': '尚未开始',
         'exam_completed': '考试完成',
         'score_rank_published': '分数位次公布',
         'application_submitted': '志愿申请提交',
         'admission_decision': '正式录取结果',
         'notice_received': '通知书收到',
         'registered': '报到注册完成',
     },
 'to_stage': {'not_started': '尚未开始',
 'exam_completed': '考试完成',
 'score_rank_published': '分数位次公布',
 'application_submitted': '志愿申请提交',
 'admission_decision': '正式录取结果',
 'notice_received': '通知书收到',
 'registered': '报到注册完成'}}

DYNAMIC_OBJECT_FIELDS = {'character_known',
 'character_known_after_episode',
 'character_state_curve',
 'phase_breakdown',
 'prop_positions',
 'running_character_state',
 'state_update'}

CONTEXTUAL_FIELD_LABELS_BY_PARENT: dict[str, dict[str, str]] = {
    "running_character_state": {
        "protagonist": "主角总体状态",
        "key_relation": "关键关系总体状态",
        "antagonists": "反派总体状态",
    },
    "state_update": {
        "audience_known": "本集观众已知信息",
        "audience_known_after_episode": "本集后观众已知信息",
        "character_known_after_episode": "本集后角色已知信息",
        "relationship_changes": "本集关系变化",
        "next_hook": "本集下一钩子",
        "next_episode_bridge": "下一集桥接",
    },
}

STATIC_CHILD_FIELDS_BY_DYNAMIC_PARENT: dict[str, set[str]] = {
    "state_update": {
        "audience_fact_changes",
        "character_knowledge_changes",
        "private_fact_changes",
        "next_episode_bridge",
    },
}


def _invert_unique(mapping: dict[str, str], *, label: str) -> dict[str, str]:
    """Handle invert unique."""
    inverse: dict[str, str] = {}
    for canonical, localized in mapping.items():
        if localized in inverse:
            raise RuntimeError(
                f"{label} has duplicate localized label {localized!r} for {inverse[localized]!r} and {canonical!r}",
            )
        inverse[localized] = canonical
    return inverse


CHINESE_TO_FIELD = _invert_unique(FIELD_LABELS, label="FIELD_LABELS")
FIELD_INPUT_ALIASES: dict[str, str] = {
    "当前地点": "location",
}
for _alias, _canonical in FIELD_INPUT_ALIASES.items():
    if _canonical not in FIELD_LABELS:
        raise RuntimeError(f"FIELD_INPUT_ALIASES target {_canonical!r} is not registered")
    if _alias in CHINESE_TO_FIELD and CHINESE_TO_FIELD[_alias] != _canonical:
        raise RuntimeError(
            f"FIELD_INPUT_ALIASES label {_alias!r} conflicts with FIELD_LABELS"
        )
CONTEXTUAL_CHINESE_TO_FIELD_BY_PARENT = {
    parent: _invert_unique(value_map, label=f"CONTEXTUAL_FIELD_LABELS_BY_PARENT[{parent}]")
    for parent, value_map in CONTEXTUAL_FIELD_LABELS_BY_PARENT.items()
}
_contextual_label_list = [
    label
    for value_map in CONTEXTUAL_FIELD_LABELS_BY_PARENT.values()
    for label in value_map.values()
]
_contextual_labels = set(_contextual_label_list)
if len(_contextual_label_list) != len(_contextual_labels):
    raise RuntimeError("contextual field labels must be globally unique")
for _parent, _value_map in CONTEXTUAL_FIELD_LABELS_BY_PARENT.items():
    for _canonical, _localized in _value_map.items():
        _global_canonical = CHINESE_TO_FIELD.get(_localized)
        if _global_canonical is not None and _global_canonical != _canonical:
            raise RuntimeError(
                f"contextual field label {_localized!r} maps to {_canonical!r} under {_parent!r} "
                f"but globally maps to {_global_canonical!r}"
            )
ENUM_VALUE_CANONICAL_BY_FIELD = {
    field_name: _invert_unique(value_map, label=f"ENUM_VALUE_ALIASES_BY_FIELD[{field_name}]")
    for field_name, value_map in ENUM_VALUE_ALIASES_BY_FIELD.items()
}
ENUM_VALUE_SYNONYMS_BY_FIELD: dict[str, dict[str, str]] = {
    "operation": {
        "添加": "add",
        "建立": "add",
        "创建": "add",
        "开启": "add",
        "修改": "update",
        "变更": "update",
        "推进": "update",
        "完成": "resolve",
        "关闭": "resolve",
        "结案": "resolve",
        "废弃": "retire",
        "退役": "retire",
        "删除": "retire",
        "移除": "retire",
        "撤销": "retire",
    }
}


class LocalizationConflictError(ValueError):
    """Group localization conflict error behavior."""
    def __init__(self, message: str, report: dict[str, Any]):
        """Initialize the instance."""
        super().__init__(message)
        self.report = report


def canonical_placeholder_name(name: str) -> str:
    """Handle canonical placeholder name."""
    return PROMPT_PLACEHOLDER_ALIASES.get(name, name)


def localize_prompt_value(root_key: str, value: Any) -> Any:
    """Handle localize prompt value."""
    return _localize(value, field_name=root_key)


def _localize(value: Any, *, field_name: str | None) -> Any:
    """Handle localize."""
    if isinstance(value, dict):
        preserve_child_keys = field_name in DYNAMIC_OBJECT_FIELDS
        contextual_labels = CONTEXTUAL_FIELD_LABELS_BY_PARENT.get(field_name or "", {})
        static_child_fields = STATIC_CHILD_FIELDS_BY_DYNAMIC_PARENT.get(field_name or "", set())
        localized: dict[Any, Any] = {}
        for raw_key, child in value.items():
            canonical_key = str(raw_key)
            if preserve_child_keys:
                if canonical_key in contextual_labels:
                    localized_key = contextual_labels[canonical_key]
                    child_field_name = canonical_key
                elif canonical_key in static_child_fields:
                    localized_key = FIELD_LABELS.get(canonical_key, canonical_key)
                    child_field_name = canonical_key
                else:
                    localized_key = canonical_key
                    child_field_name = None
            else:
                localized_key = FIELD_LABELS.get(canonical_key, canonical_key)
                child_field_name = canonical_key
            localized[localized_key] = _localize(child, field_name=child_field_name)
        return localized
    if isinstance(value, list):
        return [_localize(item, field_name=field_name) for item in value]
    if isinstance(value, str) and field_name in ENUM_VALUE_ALIASES_BY_FIELD:
        return ENUM_VALUE_ALIASES_BY_FIELD[field_name].get(value, value)
    return value


def _new_report(stage_id: str) -> dict[str, Any]:
    """Handle new report."""
    return {
        "stage_id": stage_id,
        "status": "PASS",
        "translated_key_paths": [],
        "translated_enum_paths": [],
        "english_fallback_paths": [],
        "unknown_key_paths": [],
        "duplicate_equal_paths": [],
        "conflicting_alias_paths": [],
    }


def _record(report: dict[str, Any], field: str, path: str) -> None:
    """Handle record."""
    values = report[field]
    if path not in values:
        values.append(path)


def _finalize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Handle finalize report."""
    for key, value in report.items():
        if isinstance(value, list):
            value.sort()
    if report["conflicting_alias_paths"]:
        report["status"] = "FAIL"
    elif report["english_fallback_paths"] or report["unknown_key_paths"] or report["duplicate_equal_paths"]:
        report["status"] = "WARN"
    else:
        report["status"] = "PASS"
    return report


def canonicalize_stage_output(stage_id: str, data: Any) -> tuple[Any, dict[str, Any]]:
    """Handle canonicalize stage output."""
    report = _new_report(stage_id)
    canonical = _canonicalize(data, field_name=None, path=stage_id, report=report)
    return canonical, _finalize_report(report)


def _canonicalize(value: Any, *, field_name: str | None, path: str, report: dict[str, Any]) -> Any:
    """Handle canonicalize."""
    if isinstance(value, dict):
        preserve_child_keys = field_name in DYNAMIC_OBJECT_FIELDS
        contextual_labels = CONTEXTUAL_FIELD_LABELS_BY_PARENT.get(field_name or "", {})
        contextual_reverse = CONTEXTUAL_CHINESE_TO_FIELD_BY_PARENT.get(field_name or "", {})
        static_child_fields = STATIC_CHILD_FIELDS_BY_DYNAMIC_PARENT.get(field_name or "", set())
        canonicalized: dict[Any, Any] = {}
        source_keys: dict[Any, str] = {}
        for raw_key, child in value.items():
            raw_name = str(raw_key)
            if preserve_child_keys:
                if raw_name in contextual_reverse:
                    canonical_key = contextual_reverse[raw_name]
                elif raw_name in static_child_fields:
                    canonical_key = raw_name
                elif raw_name in CHINESE_TO_FIELD and CHINESE_TO_FIELD[raw_name] in static_child_fields:
                    canonical_key = CHINESE_TO_FIELD[raw_name]
                else:
                    canonical_key = raw_name
            elif raw_name in FIELD_LABELS:
                canonical_key = raw_name
            elif raw_name in CHINESE_TO_FIELD:
                canonical_key = CHINESE_TO_FIELD[raw_name]
            elif raw_name in FIELD_INPUT_ALIASES:
                canonical_key = FIELD_INPUT_ALIASES[raw_name]
            else:
                canonical_key = raw_name
            child_path = f"{path}.{canonical_key}" if path else canonical_key
            if preserve_child_keys:
                if raw_name in contextual_reverse:
                    _record(report, "translated_key_paths", child_path)
                elif raw_name in static_child_fields:
                    _record(report, "english_fallback_paths", child_path)
                elif raw_name in CHINESE_TO_FIELD and CHINESE_TO_FIELD[raw_name] in static_child_fields:
                    _record(report, "translated_key_paths", child_path)
            else:
                if raw_name in FIELD_LABELS:
                    _record(report, "english_fallback_paths", child_path)
                elif raw_name in CHINESE_TO_FIELD:
                    _record(report, "translated_key_paths", child_path)
                elif raw_name in FIELD_INPUT_ALIASES:
                    _record(report, "translated_key_paths", child_path)
                else:
                    _record(report, "unknown_key_paths", child_path)
            canonical_child = _canonicalize(
                child,
                field_name=(
                    canonical_key
                    if canonical_key in contextual_labels or canonical_key in static_child_fields
                    else None
                )
                if preserve_child_keys else canonical_key,
                path=child_path,
                report=report,
            )
            if canonical_key in canonicalized:
                if canonicalized[canonical_key] == canonical_child:
                    _record(report, "duplicate_equal_paths", child_path)
                    continue
                _record(report, "conflicting_alias_paths", child_path)
                _finalize_report(report)
                raise LocalizationConflictError(
                    f"{child_path} conflicting bilingual keys: {source_keys[canonical_key]} / {raw_name}",
                    report,
                )
            canonicalized[canonical_key] = canonical_child
            source_keys[canonical_key] = raw_name
        return canonicalized
    if isinstance(value, list):
        return [
            _canonicalize(item, field_name=field_name, path=f"{path}[{index}]", report=report)
            for index, item in enumerate(value)
        ]
    if isinstance(value, str) and field_name in ENUM_VALUE_CANONICAL_BY_FIELD:
        synonym_map = ENUM_VALUE_SYNONYMS_BY_FIELD.get(field_name, {})
        if value in synonym_map:
            _record(report, "translated_enum_paths", path)
            return synonym_map[value]
        reverse_map = ENUM_VALUE_CANONICAL_BY_FIELD[field_name]
        if value in reverse_map:
            _record(report, "translated_enum_paths", path)
            return reverse_map[value]
        if value in ENUM_VALUE_ALIASES_BY_FIELD[field_name]:
            _record(report, "english_fallback_paths", path)
    return value
