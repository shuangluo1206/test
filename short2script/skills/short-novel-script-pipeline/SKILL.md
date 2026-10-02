---
name: short-novel-script-pipeline
description: "Run and maintain the project-local Chinese short-novel-to-40-100-episode-short-manga-drama expansion pipeline. Use when Codex needs to turn a 7k-50k Chinese short novel into traceable longform adaptation assets, stage prompts, episode plans, generated scripts, CSV stage documentation, dry-run manifests, or debug the short-novel-script-pipeline skill."
---

# Short Novel Script Pipeline

## Overview

Use this skill for the project-local pipeline that expands a Chinese short novel into a traceable configured-length short-manga-drama adaptation plan and generated scripts. The pipeline resolves a global `run_config` first, then uses pacing controls and a `canonical_story_lock` to keep source character names, emotional debt, protagonist action boundaries, core events, forbidden changes, episode asset IDs, and script continuity stable across stages.

## Before Running

Read `references/pipeline-contract.md` before changing stage order, prompt inputs, output schemas, validators, or delivery paths.

Keep these source files read-only:
- `业务方需求文档 260622-【短篇小说扩写剧本】剧本需求.md（本地保留）`
- `docs/固执爷爷听不懂人话.txt`
- `docs/清明回村，村口情报组织造谣我在城里做皮肉生意-96858.txt`

## Run Workflow

Run a dry-run first. It renders every prompt, creates deterministic dry-run payloads, and writes manifests without calling a model:

```bash
python3 skills/short-novel-script-pipeline/scripts/pipeline_runner.py \
  --novel docs/固执爷爷听不懂人话.txt \
  --run-config configs/minimal_real_5ep.json \
  --run-id dryrun_config_5ep \
  --generate-episodes 5 \
  --dry-run
```

Run a real minimal five-episode pass after dry-run succeeds:

```bash
python3 skills/short-novel-script-pipeline/scripts/pipeline_runner.py \
  --novel docs/固执爷爷听不懂人话.txt \
  --run-config configs/minimal_real_5ep.json \
  --run-id run_opus46_minimal_5ep \
  --generate-episodes 5
```

If no config file or config CLI override is provided and the same run has no historical config for the same novel SHA, conditional model stage `00a_global_config` reads the complete short novel and recommends global creative settings and 3-6 market tags. The default target is 40 episodes. Resolution precedence is: any explicit user config, then matching run history, then LLM recommendation. Any explicit config skips the 00a model call and unspecified fields use local defaults. The source and resolved config are audited in `parsed/00a_global_config_resolution.json`.

If `--llm-script` is omitted, the runner checks `$LLM_SCRIPT`, then the packaged `skills/short-novel-script-pipeline/scripts/run_oneapi_claude_opus_4_6.sh`. The packaged default script reads `~/.short2script/.env-oneapi`, uses only that `base_url` / `ONEAPI_API_KEY`, and defaults to `Claude Opus 4.6`, `max_tokens=128000`, `output_config.effort=high`, with streaming enabled to keep long requests active through the zero-trust gateway. LLM, Gemini, or any other channel must be selected explicitly with `--llm-script`.

For failed long runs, resume from the failed stage instead of rerunning upstream stages:

```bash
python3 skills/short-novel-script-pipeline/scripts/pipeline_runner.py \
  --novel docs/清明回村，村口情报组织造谣我在城里做皮肉生意-96858.txt \
  --run-config configs/qingming_40ep.json \
  --run-id run_raw_intense_qingming_40ep_continuity_260626 \
  --generate-episodes 10 \
  --reuse-through 06
```

`--resume-from <stage>` clears that stage and downstream artifacts, then reuses completed upstream clean JSON. `--reuse-through <stage>` forces reuse through that stage and clears downstream artifacts. Stage references may be full IDs such as `07_episode_planning` or numeric prefixes such as `06`.

The cache key is stage-scoped: prompt hash, input hashes, parser/validator/prompt-renderer behavior hash, stage-specific LLM runtime options, LLM script hash, and output hash. `runner_sha256` is not a global hard invalidation key.

All model-facing structured keys and fixed enum values are localized to Chinese before prompt rendering. Model responses are parsed first, then immediately canonicalized back to the existing English schema before normalization, contract validation, clean output, or downstream use. English legacy responses and non-conflicting mixed responses remain readable; conflicting bilingual aliases are hard failures. Clean output is a strict contract projection: model extras go to `parsed/unmapped_fields/`, and deterministic normalizer changes go to `parsed/normalization_reports/` instead of entering clean JSON. Inspect those directories plus `parsed/localization_reports/` for the complete boundary audit. `scripts/llm_schema_localization.py` is the single source for prompt and readable-output field labels.

Readable clean JSON artifacts are rendered by default. The runner writes `runs/<run_id>/readable_outputs/index.md`, one Markdown file per `outputs/*.clean.json`, and `parse_report.json` / `parse_report.md`. The renderer is `scripts/clean_json_to_md.py`; it expands clean JSON in original field order with Chinese reading labels, starts each file body directly from the first JSON field without a file title or generated time, omits any separate summary/full-info duplicate layer, and removes legacy `*.readable.json` and `index.json` artifacts before writing Markdown. Add `--no-render-clean-md` only when a run should skip this reading layer. Existing runs can be rendered later without rerunning the pipeline:

```bash
python3 skills/short-novel-script-pipeline/scripts/clean_json_to_md.py --run-dir runs/<run_id>
```

For the 40-episode generalization sample:

```bash
python3 skills/short-novel-script-pipeline/scripts/pipeline_runner.py \
  --novel docs/清明回村，村口情报组织造谣我在城里做皮肉生意-96858.txt \
  --run-config configs/qingming_40ep.json \
  --run-id dryrun_qingming_40ep \
  --generate-episodes 5 \
  --dry-run
```

## Delivery Outputs

Generate the stage CSV from the stage config:

```bash
python3 skills/short-novel-script-pipeline/scripts/export_stage_table.py --check
```

Standard outputs:
- `outputs/260622-短篇小说扩写剧本管线环节表.csv`
- `configs/minimal_real_5ep.json`
- `configs/qingming_40ep.json`
- `prompts/clean/*.md`
- `runs/<run_id>/prompts/`
- `runs/<run_id>/outputs/`
- `runs/<run_id>/parsed/`
- `runs/<run_id>/logs/`
- `runs/<run_id>/manifests/`
- `runs/<run_id>/readable_outputs/` by default; use `--no-render-clean-md` to skip it
- `runs/<run_id>/final/`
- `runs/<run_id>/editorial_review/` only when the independent read-only reviewer is called

## Hard Rules

- Do not modify source business docs or source novels.
- Treat input text outside 7000-50000 non-space characters as a hard failure.
- Treat `target_episodes` outside 40-100 as a hard failure.
- Treat invalid `run_config` enum values as a hard failure.
- Treat unresolved prompt placeholders as a hard failure.
- When no explicit user config or matching same-novel run history exists, call `00a_global_config` with the whole short novel. Require its full recommended config to pass the existing enum/range validator; default `target_episodes` is 40. Any config file or config CLI override skips the model and uses local defaults for unspecified fields.
- Render the actual `target_episodes` parameter in every longform prompt role statement. Do not leave a generic `40-100` range in model queries when the configured target is already known.
- Keep model-facing prompt fields in Chinese while preserving English canonical keys in every `clean.json`; never change downstream contracts merely to localize the query.
- Treat conflicting Chinese/English aliases as a hard failure. English fallback fields remain canonical-compatible and are recorded in localization reports; unknown extra fields are removed from clean output and preserved in `parsed/unmapped_fields/`.
- Generate stable `source_anchor_id` values locally for source paragraphs. Stage `01` must separate explicit source facts, reasonable inference, and adaptation interpretation; stage `02.adaptation_capacity` reports natural story capacity without changing configured `target_episodes`.
- Require stage `03.source_fact_ledger` entries to identify actor, action, object, result, source anchors, certainty, and interpretation note. `source_plot_points` and downstream source-preservation references use stable fact IDs; weak evidence or actor mismatch is a collect-mode warning.
- Require `macro_arcs` and `longform_blocks` to match `derived_config.block_count`.
- Require `event_pool` to fit `derived_config.event_pool_size` and include event windows, source anchors, source fact IDs, a concrete dramatic delta, conflict modes, legal/moral risk, content sensitivity risk, and child beats.
- Treat `event_pool.legal_moral_risk`, `episode_outlines.boundary_check`, `continuity_update.boundary_risk`, and story-content sensitivity as warning/risk statistics, not hard blockers.
- Allow intense source conflict, public backlash, criminal consequences, protagonist controversy, and familiar-social-pressure scenes to remain in the event pool, episode cards, and script body.
- Require `episode_outlines.event_ids` and `episode_outlines.foreshadowing_ids` to reference existing upstream asset IDs.
- Require `episode_outlines.event_ids` to come from the current episode's `episode_event_options.valid_event_ids`.
- Require `episode_outlines.event_ids` to fit event block and `episode_window` constraints unless a cross-block bridge is explicit; `not_before_episode` and `not_after_episode` do not expand the official event consumption window.
- Require non-epilogue episodes to have active conflict and counterattack; epilogue count must stay within `derived_config.epilogue_max_episodes`.
- Require `conflict_mode` and `pattern_family` streaks to stay within `derived_config.conflict_mode_streak_limit`.
- Require `episode_outlines.required_character_names` to come from `canonical_story_lock.character_names`.
- Require `episode_outlines.appearing_character_names` to come from `canonical_story_lock.character_names` or `expanded_character_network.name`.
- Require every `event_pool.child_beats` item to be one verifiable state transition: stable `child_beat_id`, preconditions, one primary state change, explicit effects, forbidden-early effects, completion evidence terms, and an explicit same-episode sharing flag. A transaction may contain the visible action chain needed to complete that state change in one continuous scene, but it cannot cross a real time jump or collapse two independent external results.
- Build immutable event-transaction and prop entity registries after stage `05`, then generate `parsed/05_transaction_schedule.json` and `parsed/05_prop_activation_registry.json`. If a stage-05 event chunk has blocking transaction findings, retry only that chunk with its complete previous output and exact findings, at most twice; preserve failed artifacts under `parsed/05_semantic_retry_failures/`. The local scheduler assigns one to three authorized transactions per episode and derives each prop's effective activation episode from its first owning transaction.
- Treat stage-05 `macro_arcs` as the single source of truth for season boundaries. Stage `06` must inherit their IDs and episode ranges exactly. During stage `07`, locally assign each episode's authorized event/transaction IDs, density beat IDs, prop start state, and fact-transition start state from immutable registries; the model remains responsible for story content, scenes, characters, and visible execution.
- Write `parsed/season_plan_audit.json` and `.md` after stage `07`. The audit reports repeat/window/owner errors, adjacent repeated results and hooks, payoff gaps, story-time rewinds, fact-state upgrades, prop lineage, climax/epilogue repetition, and configured-target capacity gaps. Findings warn in collect mode and may block only in strict mode.
- Treat each one-episode 07 chunk as a slice of its parent block: expose the parent range/goal/hook, but allow the total goal and hook to complete only on the parent block's final chunk. Track prop lifecycle in the handoff; a retired prop that reappears without a visible new lineage is a collect-mode `prop_lifecycle_reappearance` warning.
- Require `episode_outlines.scene_plan` to describe natural production scenes with `scene_no`, location, time, interior/exterior, appearing characters, purpose, beats, boundary reason, and `visible_space_tokens`.
- Run `04a_flashback_screening` after adaptation direction and before longform event design. It classifies time-line deviations as S/A/B/C; only A counts toward the full-season quota of 5, S is retained without quota, B must become present-time visual replacement, and C must be removed.
- Build the canonical story lock before `04b_dramatic_release_map`, then run 04b after 04a and before event design. Runtime generation uses one foundation call plus target chunks of at most 5 episodes, with the finale isolated in its own call, then locally merges them into one canonical artifact. It fixes one `DR_EPxxx` target for every configured episode, each with desire, obstacle, choice, immediate cost, visible result, and hook. The first five episodes allow no process-only target, and cited source facts must retain their actor, object, and result. The finale hook is a visible coda or thematic landing, not a new unresolved storyline. Stages 05-08 must reference these IDs instead of freely redistributing dramatic value.
- Require `episode_outlines.target_script_density` with target range, effective minimum, hard maximum, 1-3 atomic must-cover beats (`beat_id` / one visible `action` / `completion_evidence`), optional compression beats, expansion strategy, and per-scene `scene_char_budgets`. Budget scene numbers must match `scene_plan`, every beat id is assigned exactly once, and target chars sum to 650-780 for the 90-second profile.
- Require `episode_outlines.narration_device_plan` with planned OS, flashback, A-grade flashback quota, VO counts, split approved flashback/OS/visualized/deleted 04a time-deviation ids, and a visual replacement strategy; planned OS + A-grade flashback quota across the full season should be <= 5, reported as warning in collect mode and hard-blocked only under `--strict-validation`.
- Require any planned flashback/intercut/parallel time deviation in stage `07` to cite S/A ids through `approved_flashback_time_deviation_ids` from `04a_flashback_screening.retained_time_deviations`; B/C flashback references are warning issues in default collect mode, and hard failures only under `--strict-validation`. A-grade items converted to OS or present-time visual replacement do not count as flashback quota.
- Report adjacent `scene_plan` items or final script scenes that repeat the same location, time, interior/exterior, and appearing cast unless the split is a flashback, intercut, parallel action, or explicit time jump; this is warning-only in collect mode and hard-blocked only under `--strict-validation`.
- Do not allow `scene_plan` to remove a cast member in the same setting merely because the character moved to the doorway, door side, outside the door, against a wall, or turned away; that character remains visible until explicitly leaving frame and must stay in the appearing cast.
- Do not use the normalizer to merge scenes, rewrite cast, expand locations, change event ownership, or repair story time. These remain visible model-output problems and are reported by validators and release preflight.
- Require `episode_outlines.boundary_check` to be a structured object with `risk_level`, `protagonist_action`, `why_allowed`, and `mitigation`; risk level is recorded in QA warnings/statistics.
- Keep `episode_outlines.content_sensitivity_check` separate from protagonist action boundary checks.
- Require `episode_outlines` count to match `target_episodes` and episode numbers to be continuous from 1.
- Require real `final_script` outputs to use the `N-M    地点    日/夜/傍晚    内/外` scene heading format, include `出场人物：` after every scene heading, include required character names, write every dialogue line as `人物（可见动作）：台词`, reject action-only pseudo-dialogue such as `人物（动作）：（转身走开）`, use the expected natural scene count, avoid forced same-setting/same-cast adjacent splits, stay under 1000 chars for episodes 1-3 and 800 chars afterwards, avoid forbidden idioms such as `闪过一丝XX` / `一抹XX` / `一股XX` / `淡淡道`, avoid non-visual voice tags such as `平声` / `沉声` / `语气随意` in dialogue parentheses, avoid non-visual phrasing such as `话卡在嗓子里`, avoid SMS content as standalone subtitle, avoid simple internal continuity contradictions around filing/upload status and missed-call direction, and avoid cinematic markers such as `[音效]` or `镜头`; these are warning-only in default collect mode and hard-block only under `--strict-validation`. `script_length_chars` is a pacing target, not a hard lower bound. Boundary and content sensitivity risks are recorded as warnings/statistics.
- Require `continuity_update.narration_device_usage` to report actual OS, flashback, and VO counts; validators independently parse the script and report count mismatches or usage above the episode plan. Flashback usage must align with `approved_flashback_time_deviation_ids` in the episode plan.
- Stage `08` makes one model call per episode and returns the `08_episode_delta_v2` envelope. Every authorized effect ID must cite a verbatim script span. Before validation, the normalizer may re-anchor only high-confidence pronoun or line-marker variants to an exact span already present in the script; it never invents an effect. A remaining transaction failure consumes the configured per-episode retry budget, while the final collect-mode failure still keeps the script and records `STATE_UNCOMMITTED`. External processes use typed one-step transitions, and explicit flashback blocks do not advance the current-timeline process guard. The local state commit remains all-or-none.
- Keep the complete v2 continuity ledger on disk, but pass exactly five bounded views into stage `08`: the current deduplicated execution sheet, the latest 3 complete scripts, active continuity state, up to 5 future event reservations capped at 1000 characters, and current-event source facts/flashback authorization/protagonist boundary. Prompt metrics are written to `parsed/08_prompt_metrics.json`; prompts above 35,000 characters warn without stopping collect runs.
- Require every stage-05 prop to carry activation episode and initial holder/location/status. Materialize that canonical state before its first authorized mutation, then apply `continuity_update.prop_state_changes` atomically. Persist full history; only active states enter the next prompt.
- Require `continuity_update.last_scene_state` with the exact last scene heading location, cast list, and final visible line copied from `final_script`. Location/cast drift, unverifiable results, premature completed-action bridges, and VO assigned to a visibly present speaker are quality warnings in collect mode.
- Write JSON parser repair audits to `parsed/parser_reports/`; any content-dropping repair is explicit. Validate 05 foundation/event chunks and 07 episode chunks immediately, and retain child output hashes/ranges/counts in fan-out traces. Every API attempt is immutable and must record transport metadata; a streamed response without its terminal event is an API failure and never enters the normal JSON parser.
- Maintain atomic `run_state.json` values `planned/running/partial/failed/complete`. A run that does not reach its requested episode coverage must end as `PARTIAL`, never retain a stale `PASS`. Safe episode reuse requires matching input, behavior, and ledger hashes; forced unsafe reuse must be explicit and warning-audited.
- Default validation mode is `collect`: `overall_status=PASS` means structure-complete artifacts were generated; `generation_status=PASS` means no hard production blocker; `quality_status=WARN` means quality/business warnings need review. Only API/output/JSON parse failures, hard contract field misses, missing `final_script` / `state_update` / `continuity_update`, and incomplete or discontinuous `episode_num` stop the run by default. Use `--strict-validation` to restore quality/business blockers as release gates.
- Treat `final/release_preflight.json` as the independent delivery decision. `release_status=PASS` requires a valid transaction schedule, exact 07 ownership, committed 08 deltas, and no semantic normalizer mutation. A collect run may finish with `overall_status=PASS` while `release_status=BLOCK`; this means generation completed but the result is not approved for full-run release.
- Clean JSON Markdown rendering is a default reading layer only. It must not modify clean JSON, manifests, QA, or run semantics; parse failures are written to `readable_outputs/parse_report.*` and must not change `overall_status`. Use `--no-render-clean-md` to skip this layer.
- Save prompt, raw output, clean output, log, and manifest for every model stage.
- Save a localization report for every model artifact; include the localization module hash in stage behavior so ordinary caches invalidate when mappings change.
- Do not fake real model outputs. Dry-run outputs must stay marked as dry-run.
- Full real 40-100 episode generation is not the minimal validation target; run real generation incrementally.

## Independent Editorial Review

Run editorial review only after generation artifacts exist. It is read-only, is not part of the default generation gate, and must never rewrite scripts, clean JSON, or prompts:

```bash
python3 skills/short-novel-script-pipeline/scripts/editorial_review.py \
  --run-dir runs/<run_id> \
  --mode season

python3 skills/short-novel-script-pipeline/scripts/editorial_review.py \
  --run-dir runs/<run_id> \
  --mode episodes
```

`season` reviews the complete stage `07` plan. `episodes` reviews the available EP1-3, EP1-5, and EP1-10 windows and skips unavailable windows. Reports under `runs/<run_id>/editorial_review/` always score desire, resistance, choice, cost, visible result, ending hook, protagonist agency, information gain, payoff, dialogue voice, filmability, and source-emotion preservation. Use reports together with deterministic warnings to decide whether to progress from 5 to 10 to 30 to full generation; never auto-apply a reviewer recommendation.

## Validation

Run these commands after script, prompt, or Skill changes:

```bash
python3 -m unittest skills/short-novel-script-pipeline/scripts/test_pipeline_tools.py
python3 quick_validate.py skills/short-novel-script-pipeline
python3 skills/short-novel-script-pipeline/scripts/export_stage_table.py --check
python3 skills/short-novel-script-pipeline/scripts/pipeline_runner.py --novel docs/固执爷爷听不懂人话.txt --run-config configs/minimal_real_5ep.json --run-id dryrun_config_5ep --generate-episodes 5 --dry-run
python3 skills/short-novel-script-pipeline/scripts/pipeline_runner.py --novel docs/清明回村，村口情报组织造谣我在城里做皮肉生意-96858.txt --run-config configs/qingming_40ep.json --run-id dryrun_qingming_40ep --generate-episodes 5 --dry-run
```
