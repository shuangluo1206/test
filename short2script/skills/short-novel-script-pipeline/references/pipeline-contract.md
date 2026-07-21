# Short Novel Script Pipeline Contract

## Purpose

Turn a 7k-50k Chinese short novel into traceable 40-100 episode short-manga-drama adaptation artifacts and generated scripts. The pipeline follows the business workflow in the 260622 requirement document and keeps traceability from source plot assets to longform episode plans.

## Stage Order

```text
00_source_ingest
01_novel_summary
02_storyline_understanding
03_plot_character_extract
04_adaptation_direction
04a_flashback_screening
04b_dramatic_release_map
05_plot_character_adaptation
06_script_outline_design
07_episode_planning
08_script_body_generation
09_compile_run
```

`00_source_ingest` and `09_compile_run` are deterministic local stages. Stages `01` through `08`, including inserted stages `04a` and `04b`, are model stages and must save rendered prompts, raw outputs, clean outputs, logs, and manifests.

## Runtime Defaults

- `run_config.target_episodes`: 40
- `run_config.episode_duration_seconds`: 90
- `run_config.rewrite_intensity`: `balanced`
- `run_config.character_background_policy`: `minor_adjust`
- `run_config.subplot_policy`: `moderate`
- `run_config.new_character_policy`: `controlled`
- `run_config.source_preservation_level`: `core_plot`
- `run_config.source_boundary_mode`: `balanced_spark`
- `run_config.pacing_controls`: epilogue max 2, event reuse max 3, conflict-mode streak max 2, major climax window auto, cross-block bridge max 1
- `generate_episodes`: 1 by default; project validation often uses 5
- `runs_dir`: `runs`
- LLM script priority: `--llm-script`, `$LLM_SCRIPT`, packaged `skills/short-novel-script-pipeline/scripts/run_baidu_oneapi_claude_opus_4_6.sh`
- Default real-run model channel: Baidu OneAPI Anthropic-compatible `Claude Opus 4.6`, reading URL/key only from `/Users/cjlbd/Desktop/Code/.env-baidu-oneapi-data-0708`, with `max_tokens=128000`, `output_config.effort=high`, and streaming enabled. Bounded structured-output stages `02`, `04`, `04a`, `04b`, `05`, `06`, `07`, and `08` default to `thinking.type=disabled`; `01` and `03` use `adaptive`. An explicit `BAIDU_ONEAPI_THINKING_TYPE` overrides this.
- Each stage `05` split call uses a dedicated 900-second timeout by default (`--stage-05-timeout`); other stages use `--timeout`.

`--run-config` may point to a JSON file. CLI flags such as `--target-episodes`, `--episode-duration-seconds`, `--rewrite-intensity`, `--subplot-policy`, and `--market-tags` override the file values.

## Input Rules

- Read source text with encoding fallback: `utf-8-sig`, `utf-8`, `gb18030`, `gbk`.
- Reject empty source text.
- Reject novels outside 7000-50000 non-space characters.
- Reject `target_episodes` outside 40-100.
- Reject invalid `run_config` enum values.
- Split chapters when headings like `##第一章##` or `第001章` are present; otherwise treat full text as one chunk.

## Run Config Contract

Required user-facing fields:

- `target_episodes`: 40-100.
- `episode_duration_seconds`: 60, 90, or 120.
- `rewrite_intensity`: `light`, `balanced`, or `heavy`.
- `character_background_policy`: `keep`, `minor_adjust`, or `allow_rewrite`.
- `subplot_policy`: `none`, `moderate`, or `aggressive`.
- `new_character_policy`: `limited`, `controlled`, or `open`.
- `source_preservation_level`: `core_hook`, `core_plot`, or `character_strict`.
- `source_boundary_mode`: `strict_source_anchor`, `balanced_spark`, or `heavy_rewrite`.
- `pacing_controls`: object with `epilogue_max_episodes`, `event_reuse_max_episodes`, `conflict_mode_streak_limit`, `major_climax_window`, `cross_block_bridge_max_episodes`.
- `market_tags`: non-empty string array.

Derived system fields include `block_count`, `episodes_per_block`, `subplot_budget`, `new_character_budget`, `scenes_per_episode`, `script_length_chars`, `event_pool_size`, `foreshadowing_density`, `source_retention_ratio`, `major_climax_window`, `epilogue_max_episodes`, `event_reuse_max_episodes`, `conflict_mode_streak_limit`, and `cross_block_bridge_max_episodes`. `scenes_per_episode` means natural production scenes, not story beats.

## Canonical Story Lock

After stages `03` and `04`, the runner builds `parsed/04_canonical_story_lock.json`. It contains:

- `protagonist`
- `character_names`
- source plot point summaries
- immutable elements
- emotional debt chain
- character action boundaries
- must-keep items
- source preservation contract
- protagonist action boundary
- event release principles
- epilogue budget
- forbidden changes
- naming rules

Stages `05` through `08` must receive this lock. It prevents character-name drift, replacement of source character functions, and destructive changes to source core events.

## Output Ledger

Every model stage writes:

- Rendered prompt: `runs/<run_id>/prompts/<stage_id>.prompt.md`
- Raw output: `runs/<run_id>/outputs/<stage_id>.raw.md`
- Clean output: `runs/<run_id>/outputs/<stage_id>.clean.json`
- Log: `runs/<run_id>/logs/<stage_id>.log.json`
- Manifest: `runs/<run_id>/manifests/<stage_id>.manifest.json`

The LLM boundary is bilingual by design:

- Rendered prompts localize registered structured keys and fixed enum values to Chinese.
- Raw output preserves the model response exactly as received.
- The runner canonicalizes Chinese, English, or non-conflicting mixed response keys to the existing English schema before normalization and validation.
- Clean output always uses the English canonical schema consumed by contracts, validators, resume/reuse, and RD integrations.
- Equal Chinese/English aliases collapse with a warning; different values at the same canonical JSON path are a hard failure. Missing canonical required fields remain contract failures.
- `clean.json` is a strict contract projection. Unknown model fields are removed from clean and written with exact paths and values to `parsed/unmapped_fields/<artifact_id>.json`; summaries are in `parsed/unmapped_fields_summary.json`.
- Deterministic normalizer operations and discarded repair traces are written to `parsed/normalization_reports/<artifact_id>.json` and `parsed/normalization_summary.json`.

Global configuration is resolved before stage `01`:

- Priority is any user `--run-config` or config CLI override, then `parsed/00_run_config.json` from the same `run_id` only when the source novel SHA matches, then conditional LLM stage `00a_global_config`.
- With no user target, `target_episodes` is locked locally to 40 even if the 00a response drifts. The 00a model reads the complete short novel and recommends duration, rewrite intensity, character/subplot/new-character/source-preservation policies, source-boundary mode, pacing controls, and 3-6 market tags.
- Any explicit config skips the model call rather than generating a fake raw response; unspecified fields use local defaults. Matching history also skips the model call.
- `parsed/00a_global_config_resolution.json` records resolution source, whether a model was called, novel SHA, user overrides, system-locked values, any recommendation adjustment, final config, and recommendation artifact path.
- All longform model prompts receive the resolved `target_episodes` in their role statement; generic `40-100` wording is not used when an exact target exists.

Localization audits are written to `runs/<run_id>/parsed/localization_reports/<artifact_id>.json` and summarized in `runs/<run_id>/parsed/localization_summary.json`. Reports include `status`, `translated_key_paths`, `translated_enum_paths`, `english_fallback_paths`, `unknown_key_paths`, `duplicate_equal_paths`, and `conflicting_alias_paths`.

For repeated episode-body stages, use artifact ids such as `08_script_body_generation_ep001` so each episode has independent prompt, raw output, clean output, log, and manifest files.

The runner also writes cumulative continuity ledgers:

- `runs/<run_id>/parsed/08_continuity_ledger_after_ep001.json`
- `runs/<run_id>/parsed/08_continuity_ledger_after_epNNN.json`
- `runs/<run_id>/parsed/08_prompt_metrics.json`

The full `continuity_ledger_v2` remains the audit source on disk. Stage `08` receives five bounded views instead of the cumulative ledger: current deduplicated execution sheet, latest 3 complete `final_script` values, active continuity state, up to 5 future event reservations capped at 1000 characters, and current-event source facts/flashback authorization/protagonist boundary. Resolved and retired history remains on disk but does not re-enter the prompt.

The runner also writes:

- `runs/<run_id>/run_state.json`: atomic `planned/running/partial/failed/complete` state, requested target, actual coverage, continuous completed prefix, current artifact, last success time, and failure category.
- `runs/<run_id>/parsed/00_source_anchors.json`: stable local paragraph anchors such as `SRC_P0001`; source files are never modified.
- `runs/<run_id>/parsed/05_event_registry.json` and the prop registry: immutable event/child-beat and prop identity sources used by local cumulative calculations.
- `runs/<run_id>/parsed/season_plan_audit.json` and `.md`: deterministic full-season audit generated after stage `07`.
- Per-artifact immutable attempt directories containing sanitized response headers, raw SSE, assembled text, HTTP status, content type, first-token and total latency, event count, stop reason, and parser result. A stream without the terminal event is a transport failure and cannot enter the normal parser.

By default, the runner also writes a reading layer under `runs/<run_id>/readable_outputs/`:

- `index.md`: entry point linking all rendered clean JSON files.
- `<artifact_id>.md`: one readable Markdown file per `outputs/<artifact_id>.clean.json`.
- `parse_report.json`: machine-readable coverage and error report.
- `parse_report.md`: human-readable parse report.

The reading layer must render every JSON path from each clean output or explicitly record the failed path in `parse_report.*`. Markdown body text should follow the original clean JSON field order directly, starting from the first JSON field without a file title or generated timestamp, and using Chinese reading labels instead of a separate summary/full-info duplicate layer; unknown English field labels are rendered as `未登记字段 <field_name>` and listed in `unknown_field_labels`. Before rendering, `clean_json_to_md.py` removes legacy `*.readable.json` and `index.json` artifacts so standalone rendering uses the current Markdown layer only. This layer must not modify clean JSON, manifests, QA summaries, or run validation semantics; per-file JSON parse failures should be recorded and should not stop parsing of other clean files. Use `--no-render-clean-md` to skip this layer for runs that need fewer artifacts.

Independent editorial review writes only to `runs/<run_id>/editorial_review/`. It reads existing stage artifacts, preserves its prompt/raw/structured/Markdown output and immutable attempts, and never changes generation state, QA gate, clean JSON, or prompts. `season` reviews the complete stage `07`; `episodes` reviews available EP1-3, EP1-5, and EP1-10 windows.

Every manifest includes:

- `stage_id`
- `artifact_id`
- `stage_name`
- `prompt_template`
- `prompt_sha256`
- `input_keys`
- `input_value_hashes`
- `prompt_schema_locale`
- `localization_version`
- `localization_status`
- `output_sha256`
- `dry_run`
- `llm_script`
- `llm_script_sha256`

## Quality Gates

- Prompt rendering must fail on unresolved `{placeholder}` values.
- JSON model outputs must parse after removing code fences and trailing commas.
- Model-facing registered schema keys should be Chinese; old English keys and unknown extras are warning-compatible, while conflicting bilingual aliases are hard failures.
- Canonicalization must happen before stage normalization, contract validation, and clean output. `clean.json` remains English canonical regardless of model response language.
- `target_episodes` must be between 40 and 100.
- `run_config` and `derived_config` must be passed into every model stage.
- `00a_global_config.recommended_run_config` must contain every canonical run-config field and pass the same range/enum/pacing/tag validation as user config. Missing or illegal configuration fields are production blockers.
- Stage `00` must create stable paragraph-level `source_anchor_id` values locally. Stage `01` must distinguish explicit source fact, inference, and adaptation interpretation rather than upgrade unsupported intent into fact.
- Stage `02.adaptation_capacity` must include independent conflict-unit count, natural episode range, configured-target gap, expansion pressure, and required new engines. It is a hard field contract but never changes configured `target_episodes`; insufficient capacity is a warning.
- Stage `03.source_fact_ledger` is a hard contract. Each fact has `fact_id`, actor, action, object, result, source anchor IDs, certainty, and interpretation note; `source_plot_points.source_fact_ids` must reference it. Unknown anchors, actor mismatch, or unsupported certainty are warnings in collect mode and blockers only in strict mode.
- `macro_arcs` and `longform_blocks` must contain exactly `derived_config.block_count` items.
- `event_pool` count must fit `derived_config.event_pool_size`.
- Cached clean outputs must re-match `output_sha256`; non-dry-run cache hits must also re-match `llm_script` path and `llm_script_sha256`.
- Each event also declares `dramatic_target_ids` matching every episode in its window. Every child beat is a verifiable state transaction with stable effect IDs and `process_transition`. Non-process transactions leave its three fields empty; process transactions use a stable process ID and advance exactly one typed stage. A leading date marker starts a new transaction; a second time jump or independently awaited result inside the same action is invalid. If an event chunk has blocking transaction findings, the runner retries only that chunk with the complete failed output and exact findings, at most twice, and preserves every failed artifact under `parsed/05_semantic_retry_failures/`. If no semantic partition fits the event window after repair, fallback is diagnostic only and must not become the authoritative 07 schedule.
- `event_pool.legal_moral_risk`, `event_pool.content_sensitivity_risk`, and event text are warning/statistics surfaces, not hard blockers. Intense source conflict, public backlash, criminal consequences, protagonist controversy, and familiar-social-pressure scenes may remain in event assets.
- Stage `04a_flashback_screening` must classify every real time-line deviation into `S/A/B/C`: retained list may contain only S/A, rewrite list only B, deleted list only C. A items must have `quota_count=1`, S/B/C must have `quota_count=0`, and `used_quota + new_a_quota_count <= 5`.
- Stage `04b_dramatic_release_map` receives the canonical story lock and must contain exactly one deterministic `DR_EPxxx` target per configured episode. Runtime generation is split into one foundation artifact and target chunks of at most 5 episodes, with the configured finale isolated in a one-episode chunk; the runner validates every chunk's exact episode/ID range and deterministically merges them into the unchanged canonical stage artifact. A malformed-JSON or contract-missing chunk may be retried twice without rerunning successful chunks, and each failed attempt remains auditable. Every target has desire, obstacle, choice, immediate cost, visible result, hook, confrontation mode, process-only flag, source facts, and required event function. The first five targets allow no process-only episode; source fact actor, character object, and terminal outcome are audited. The finale hook is required but must be a visible coda, new-life confirmation, or thematic landing rather than a new unresolved main plot. These semantic checks warn in collect mode.
- Stages `05` through `08` must consume `flashback_screening`: S/A items are the only legal source for flashback/intercut/parallel-action time deviations; B items must become present-time action, props, screen text, dialogue, or reaction shots; C items must be removed.
- `episode_outlines` must contain exactly `target_episodes` items numbered from 1.
- `episode_outlines.event_ids` must reference existing `event_pool.id` values.
- `episode_outlines.event_ids` must be selected from the current episode's `episode_event_options.valid_event_ids`.
- `episode_outlines.event_ids` must fit `episode_window` and block assignment unless `allowed_cross_block_bridge` is explicit; `not_before_episode` and `not_after_episode` do not expand the official consumption window.
- `parsed/05_transaction_schedule.json` is the source of truth for episode ownership. Every episode has exactly one owner event and one to three explicitly authorized transactions. `episode_outlines.event_ids`, `consumed_child_beat_ids`, and `target_script_density.must_cover_beats[].beat_id` must exactly match that schedule. `parsed/05_prop_activation_registry.json` is the source of truth for when a prop can first appear; each prop carries an initial holder, location, and status that is materialized before its first authorized mutation.
- Every 07 fan-out handoff carries `cumulative_consumed_child_beat_ids` and `active_prop_registry`. These are prompt inputs, not new clean output fields: they prevent each episode-planning call from resetting event consumption and prop identity while preserving the existing canonical schema.
- A one-episode 07 fan-out chunk is not a new parent block. The prompt carries the parent block range, total goal and total hook, and only the parent block's final chunk may complete them; intermediate chunks must stay within their per-episode legal event options.
- Event-window and child-beat alignment are semantic checks. The normalizer preserves the model's original `event_ids` and reports violations; it must not replace an event id without synchronously rewriting its child beats and story content.
- `parsed/full_run_issue_log.json` is scoped to the current run attempt. Resume/reuse initializes a fresh issue snapshot so prior attempt findings cannot contaminate the current QA report.
- The continuity ledger must not overwrite an existing prop when the same `prop_id` arrives with a different `prop_name`. It keeps the original `prop_positions` entry and records the collision in `prop_identity_conflicts`; collect mode reports the semantic violation without stopping generation.
- Active prop handoff entries carry a derived lifecycle status. If a prop marked discarded, destroyed, flushed away or invalidated reappears in a later script without a visible new object and a new id, final QA emits `prop_lifecycle_reappearance` as a warning in collect mode.
- `episode_outlines.foreshadowing_ids` must reference existing `foreshadowing_pool.id` values.
- `episode_outlines.required_character_names` must come from `canonical_story_lock.character_names`.
- `episode_outlines.appearing_character_names` must come from `canonical_story_lock.character_names` or `expanded_character_network.name`.
- `episode_outlines` should provide `opening_beat`, `closing_beat`, `next_episode_start_state`, and `consumed_child_beats` so stage `08` can continue from the previous episode instead of replaying completed beats.
- `episode_outlines` must also provide `source_fact_ids`, `story_time`, and `fact_transitions`. Story time has a stable day index/label/elapsed description; a cross-day episode uses the calendar day of its final scene. Fact transitions record old state, new state, and evidence so unconfirmed claims cannot silently become confirmed facts.
- `episode_outlines.scene_plan` is a hard contract. Each item must include `scene_no`, `location`, `time`, `space`, `appearing_character_names`, `scene_purpose`, `must_include_beats`, `scene_boundary_reason`, and `visible_space_tokens`.
- Adjacent `scene_plan` items must not repeat the same `location`, `time`, `space`, and `appearing_character_names` unless the split is a flashback, intercut, parallel action, or explicit time jump with a clear boundary reason.
- `episode_outlines.target_script_density` is a hard contract. It must include `target_range_chars`, `minimum_effective_chars`, `maximum_chars`, `must_cover_beats`, `optional_compression_beats`, `expansion_strategy`, and `scene_char_budgets`. `must_cover_beats` contains 1-3 atomic objects with `beat_id`, one visible `action`, and `completion_evidence`; every budget item contains `scene_no`, `target_chars`, and `must_cover_beat_ids`. Scene numbers must match `scene_plan`, each beat id is assigned exactly once, and 90-second budget totals must fit 650-780.
- `episode_outlines.prop_continuity_plan` is a hard contract list. Each item contains `prop_id`, `prop_name`, start/end holder and location, `transfer_action`, and `completion_evidence`; an empty list means the episode has no continuity-critical prop. Holder/location changes without a visible transfer are quality warnings in collect mode.
- `episode_outlines.narration_device_plan` is a hard contract. It must include `planned_os_count`, `planned_flashback_count`, `planned_flashback_quota_count`, `planned_vo_count`, `reason`, `visual_replacement_strategy`, `approved_flashback_time_deviation_ids`, `approved_os_time_deviation_ids`, `visualized_time_deviation_ids`, and `deleted_or_rewritten_time_deviation_ids`.
- If `planned_flashback_count > 0`, `approved_flashback_time_deviation_ids` must reference S/A ids from `04a_flashback_screening.retained_time_deviations`. Referencing B/C ids as flashback is a warning in default collect mode and a hard failure only under `--strict-validation`. S references increase `planned_flashback_count` but not `planned_flashback_quota_count`; A references increase both only when used as flashback. A items converted to OS or present-time visual replacement do not count toward flashback quota. Planned OS + A-grade flashback quota across the full season must be <= 5.
- `episode_outlines.boundary_check` must be an object with `risk_level`, `protagonist_action`, `why_allowed`, and `mitigation`; high-risk protagonist actions become warnings and risk statistics, not hard failures.
- `episode_outlines.content_sensitivity_check` should separate story-content risk from protagonist-action risk; high content-risk cards become warnings and risk statistics, not hard failures.
- Non-epilogue episodes must not have empty conflict or counterattack.
- `is_epilogue=true` count must not exceed `derived_config.epilogue_max_episodes`.
- `conflict_mode` streaks must not exceed `derived_config.conflict_mode_streak_limit`.
- `pattern_family` streaks must not exceed `derived_config.conflict_mode_streak_limit`.
- Each event in the longform event pool should keep `source_plot_point_ids` or declare `expansion_type` as `new_bridge` or `new_expansion`.
- Final script cleaning must remove model explanation prelude and keep only script content.
- Real script outputs must use the `N-M    地点    日/夜/傍晚    内/外` scene heading format, include `出场人物：` immediately after every scene heading, include required character names, write every dialogue line as `人物（可见动作）：台词`, reject action-only pseudo-dialogue such as `人物（动作）：（转身走开）`, fit the expected natural scene count, avoid forbidden cinematic markers, forbidden idioms such as `闪过一丝XX` / `一抹XX` / `一股XX` / `淡淡道`, non-visual voice tags such as `平声` / `沉声` / `语气随意` in dialogue parentheses, non-visual phrasing such as `话卡在嗓子里`, SMS content as standalone subtitle, simple internal continuity contradictions around filing/upload status and missed-call direction, and stay under the script cap: episodes 1-3 <= 1000 non-space chars, later episodes <= 800 non-space chars. These content-quality violations are warnings in default `validation_mode=collect` and hard blockers only under `--strict-validation`. `derived_config.script_length_chars` is a pacing target, not a hard lower-bound contract.
- Real script outputs must not split adjacent scenes with the same location, time, interior/exterior, and appearing cast unless the second scene is a flashback, intercut, parallel action, or explicit time jump supported by `episode_outline.scene_plan`.
- In both `episode_outline.scene_plan` and `final_script`, a character who only moves to the doorway, door side, outside the door, against a wall, or turns away is still visible and must remain in the scene cast; only explicit leaving-frame language may remove the character from the next same-setting scene.
- Stage `05.macro_arcs` is the canonical season-boundary source. Stage `06` inherits every arc ID and episode range exactly; its deterministic normalizer reports whether any boundary drift was corrected.
- Stage `07` normalization must not merge scenes, alter character lists, expand locations, repair story time, or change conflict patterns. It deterministically assigns event IDs, transaction IDs, density beat IDs, prop start state, and fact-transition start state from the immutable local schedule and registries, then joins canonical `consumed_child_beats` display text. These machine-owned fields are not trusted to model repetition; all creative differences remain in clean output and are reported.
- Stage `08` must obey `episode_outline.target_script_density`, `episode_outline.narration_device_plan`, and `flashback_screening`, prefer visual replacement over OS/flashback/VO, and output `continuity_update.narration_device_usage`; validators independently parse usage and report mismatched counts or usage above the plan.
- Stage `08` must output one `08_episode_delta_v2` envelope per episode. `continuity_update` includes ordered `completed_effect_evidence`; every authorized effect ID appears exactly once and cites a verbatim span present in `final_script`. The normalizer may deterministically replace only high-confidence pronoun or camera-marker variants with an exact existing script span; ambiguous evidence is left unchanged. Remaining transaction failures are retried within the episode retry budget before collect mode records a final `STATE_UNCOMMITTED` delta.
- Every state change uses a stable ID and `add/update/resolve/retire`. `character_knowledge_changes` is an object array, never a dynamic person-name dictionary. The 08 response is a proposed delta. `update` requires an active existing record, `add` requires a new ID, and resolved/retired records cannot be reactivated. Invalid proposals are written to `rejected_deltas` and do not mutate active continuity state.
- `qa_summary.check_results.flashback_screening_alignment` must be `PASS` when stage `04a` exists; violations become warnings in default collect mode and blocking issues only under `--strict-validation`.
- Stage `08` uses the preceding three complete scripts plus active ledger state; the next episode must begin after completed beats and the previous visible result instead of replaying them. Prompt target is at most 25,000 characters; more than 35,000 characters is a warning, not a collect-mode blocker.
- Education and comparable external workflows keep distinct states for action completion, result publication, application, formal result, notification, and execution. A score/position page cannot establish university admission; registration groups, reporting instructions, or lodging arrangements require a formal admission state.
- New episode facts use episode-scoped IDs such as `EP005_AUD_01`, `EP005_CHAR_01`, and `EP005_PRIVATE_01`. State commit is atomic: transaction, effect-evidence, future-state, or ledger-operation failure records the script and proposed delta as `STATE_UNCOMMITTED`, but commits none of its facts, props, bridge, last-scene state, or completion digest. Collect mode continues; strict mode also stops.
- `continuity_update.last_scene_state` location/cast must equal the parsed final scene, and `visible_result` must be copied from a visible line. The normalizer does not overwrite this model-authored state from the script; drift remains auditable.
- Parser repairs are audited in `parsed/parser_reports/` with before/after hashes, named operations, and `content_discarded`. Stage 05 foundation/event chunks and stage 07 episode chunks receive profile-aware contract reports before merge; fan-out traces retain artifact id, output hash, range, and item count.
- Real-output final QA must check adjacent generated scripts for opening rewind: if episode N+1 opens by repeating episode N's already completed early beat, `adjacent_opening_continuity` is a warning in default collect mode and a hard failure only under `--strict-validation`. Dry-run skips this content-quality gate because dry-run scripts are deterministic fixtures.
- `qa_summary` must include `overall_status`, `generation_status`, `quality_status`, `validation_mode`, `blocking_issues`, `warnings`, and `check_results`. In default `validation_mode=collect`, `blocking_issues` only contains API/output/JSON/contract/required-field/episode-count/episode-numbering blockers;剧作、格式、节奏、闪回/OS/VO、不可拍描述、地点漂移、出场人物漏、business QA 问题进入 `warnings` and set `quality_status=WARN`.
- `07_preflight_qa_summary.overall_status` and final `qa_summary.overall_status` must be `PASS` for a structure-complete collect-mode run. `quality_status=WARN` means the run is ready for review and root-cause analysis, not necessarily content-deliverable. Use `--strict-validation` when quality/business findings should stop the runner.
- If requested script coverage is incomplete, `run_state`, final summary, and QA must all report `PARTIAL`; no stale prior `PASS` may survive. Episode reuse requires matching input, behavior, and ledger hashes unless the caller explicitly forces unsafe reuse, which must emit a prominent warning.
- `season_plan_audit` deterministically reports event/child-beat repeat, window and owner violations, adjacent repeated outcomes/hooks, missing opening micro-payoffs, repeated foreshadowing IDs without escalation/payoff, consecutive setup-only episodes, story-time rewinds, unsupported fact upgrades, prop lineage, climax/epilogue repetition, and configured target versus natural capacity. All findings warn in collect mode and may block only in strict mode.
- Clean JSON Markdown rendering is default-on. It renders existing `outputs/*.clean.json` to `readable_outputs/`; render failures are reported in `parse_report.*` and do not change `overall_status`, `generation_status`, or `quality_status`. Use `--no-render-clean-md` to skip it.
- Dry-run outputs must be deterministic and marked as dry-run; do not present them as model-generated content.

## Longform Stage Contract

- `00a_global_config`: conditionally reads the complete source novel and returns `novel_profile`, `recommended_run_config`, and field-level recommendation reasons. It is bypassed when authoritative user config or matching run history exists.
- `01_novel_summary`: uses anchored source paragraphs and `run_config` to decide asset density while separating explicit fact, inference, and adaptation interpretation.
- `02_storyline_understanding`: selects the storyline, builds the story engine, and reports `adaptation_capacity` without changing the configured target.
- `03_plot_character_extract`: extracts source plot points and character assets plus a stable source fact ledger; source plot points cite fact IDs and facts cite source anchor IDs.
- `04_adaptation_direction`: defines longform strategy and originality limits, references preserved fact IDs, and gives the protagonist explicit allowed active strategies such as evidence collection, fact publication, refusal to rescue, resource withdrawal, and lawful action.
- `04a_flashback_screening`: uses source text, chapter summaries, source plot points, adaptation direction, market tags, `source_type`, and `used_quota` to produce retained/rewrite/deleted time-line deviation lists and A-grade quota policy.
- `04b_dramatic_release_map`: turns configured season length into an immutable per-episode dramatic release map before event generation.
- `05_plot_character_adaptation`: first generates `macro_arcs`, `conflict_engine`, `expanded_character_network`, `foreshadowing_pool`, and prop identities; then generates `event_pool` once per macro arc. Every child beat is a state-transition transaction. The runner retries only semantically invalid event chunks, merges successful child artifacts, builds the immutable transaction schedule, and derives effective prop activation from the first owning transaction.
- `06_script_outline_design`: inherits stage-05 macro-arc IDs and ranges exactly, uses those variable-length blocks, keeps total configured episodes unchanged, and emits `adaptation_capacity_warning` when natural capacity is lower than the requested target.
- `07_episode_planning`: model fan-out calls output episode plans with source facts, story time, fact transitions, scenes, and dramatic execution. Canonical event/transaction ownership, density beat IDs, prop starts, and fact starts stay in local registries and are deterministically assigned after each response; future props and unrelated foreshadowing are removed from each block prompt. The runner then writes the transaction report and season-plan audit.
- `08_script_body_generation`: receives five bounded context views and generates one free-text script plus a proposed v2 delta. The local commit layer requires verbatim effect evidence, checks typed process/future leakage and ledger operations, then commits the whole delta or none of it.
- `09_compile_run`: compiles outputs and supports QA checks for continuity, hooks, foreshadowing, source retention, and expansion risk.

## Editorial Review Contract

- `scripts/editorial_review.py --mode season` reads complete stage `07`, the source fact ledger, adaptation direction, season audit, and QA warnings.
- `--mode episodes` reads the available EP1-3, EP1-5, and EP1-10 outlines/scripts; unavailable windows are skipped rather than fabricated.
- Every structured review scores exactly these twelve dimensions: 欲望、阻力、选择、代价、可见结果、尾钩、主角主动性、信息增量、爽点兑现、台词个性、可拍摄性、源故事情绪保留.
- The reviewer is advisory only: it cannot modify generation artifacts, automatically revise prompts, or change collect/strict validation status.
