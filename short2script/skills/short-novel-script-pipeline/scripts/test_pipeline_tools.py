"""Tests for short novel script pipeline tools."""
import csv
import json
import re
import sys
import tempfile
import unittest
import urllib.request
from typing import Any
from unittest import mock
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import export_stage_table
import clean_json_to_md
import continuity_ledger
import dramatic_release
import episode_generation_context
import editorial_review
import event_transactions
import llm_client
import llm_schema_localization
import parsers
import pipeline_runner
import prompt_renderer
import release_preflight
import season_plan_audit
import stage_contracts
import text_io
import validators


PROJECT_ROOT = SCRIPT_DIR.parents[2]


class PipelineToolTests(unittest.TestCase):
    """Group pipeline tool tests behavior."""
    def test_global_config_contract_requires_complete_recommendation(self):
        """Verify global config contract requires complete recommendation."""
        payload = pipeline_runner.dry_run_payload(
            "00a_global_config",
            {
                "default_run_config": pipeline_runner.DEFAULT_RUN_CONFIG,
                "user_overrides": {},
            },
        )
        self.assertEqual(stage_contracts.validate("00a_global_config", payload)["status"], "PASS")

        payload["recommended_run_config"].pop("market_tags")
        report = stage_contracts.validate("00a_global_config", payload)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn(
            "00a_global_config.recommended_run_config.market_tags missing",
            report["errors"],
        )

    def test_global_config_chinese_response_round_trips_to_canonical_schema(self):
        """Verify global config chinese response round trips to canonical schema."""
        canonical = pipeline_runner.dry_run_payload(
            "00a_global_config",
            {
                "default_run_config": pipeline_runner.DEFAULT_RUN_CONFIG,
                "user_overrides": {},
            },
        )
        localized = llm_schema_localization.localize_prompt_value("00a_global_config", canonical)

        restored, report = llm_schema_localization.canonicalize_stage_output(
            "00a_global_config",
            localized,
        )

        self.assertEqual(restored, canonical)
        self.assertEqual(report["status"], "PASS")

    def test_global_config_resolution_user_overrides_skip_llm(self):
        """Verify global config resolution user overrides skip llm."""
        args = pipeline_runner.build_parser().parse_args(
            ["--novel", "novel.txt", "--target-episodes", "60", "--market-tags", "家庭反击,规则反击", "--dry-run"]
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "auto_config")
            with mock.patch.object(pipeline_runner, "call_stage", side_effect=AssertionError("LLM must not be called")):
                config, resolution = pipeline_runner.resolve_global_run_config(
                    args=args,
                    paths=paths,
                    stage=pipeline_runner.stage_map()["00a_global_config"],
                    source_text="完整短篇小说",
                    source_sha256="novel-sha",
                    llm_script_path=None,
                )

            self.assertEqual(config["target_episodes"], 60)
            self.assertEqual(config["market_tags"], ["家庭反击", "规则反击"])
            self.assertEqual(resolution["source"], "user_overrides")
            self.assertFalse(resolution["model_called"])
            self.assertFalse((paths.outputs / "00a_global_config.clean.json").exists())

    def test_global_config_resolution_no_input_uses_default_40_recommendation(self):
        """Verify global config resolution no input uses default 40 recommendation."""
        args = pipeline_runner.build_parser().parse_args(["--novel", "novel.txt", "--dry-run"])
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "auto_config")
            config, resolution = pipeline_runner.resolve_global_run_config(
                args=args,
                paths=paths,
                stage=pipeline_runner.stage_map()["00a_global_config"],
                source_text="完整短篇小说",
                source_sha256="novel-sha",
                llm_script_path=None,
            )

            self.assertEqual(config["target_episodes"], 40)
            self.assertEqual(resolution["source"], "dry_run_recommendation")
            self.assertFalse(resolution["model_called"])
            self.assertEqual(resolution["system_locked_values"], {"target_episodes": 40})
            self.assertTrue((paths.outputs / "00a_global_config.clean.json").exists())

    def test_global_config_resolution_locks_default_target_against_model_drift(self):
        """Verify global config resolution locks default target against model drift."""
        args = pipeline_runner.build_parser().parse_args(["--novel", "novel.txt"])
        recommendation = pipeline_runner.dry_run_payload(
            "00a_global_config",
            {
                "default_run_config": pipeline_runner.DEFAULT_RUN_CONFIG,
                "user_overrides": {},
            },
        )
        recommendation["recommended_run_config"]["target_episodes"] = 60
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "auto_config")
            with mock.patch.object(pipeline_runner, "call_stage", return_value=recommendation):
                config, resolution = pipeline_runner.resolve_global_run_config(
                    args=args,
                    paths=paths,
                    stage=pipeline_runner.stage_map()["00a_global_config"],
                    source_text="完整短篇小说",
                    source_sha256="novel-sha",
                    llm_script_path=Path("fake-llm.sh"),
                )

        self.assertEqual(config["target_episodes"], 40)
        self.assertEqual(resolution["source"], "llm_recommendation")
        self.assertTrue(resolution["model_called"])
        self.assertEqual(resolution["system_locked_values"], {"target_episodes": 40})
        self.assertEqual(
            resolution["recommendation_adjustments"],
            [
                {
                    "field": "target_episodes",
                    "recommended_value": 60,
                    "resolved_value": 40,
                    "reason": "system_default_locked_without_user_or_history_config",
                }
            ],
        )

    def test_global_config_resolution_reuses_same_novel_history_without_llm(self):
        """Verify global config resolution reuses same novel history without llm."""
        args = pipeline_runner.build_parser().parse_args(["--novel", "novel.txt", "--dry-run"])
        history = pipeline_runner.merge_run_config(
            pipeline_runner.DEFAULT_RUN_CONFIG,
            {"market_tags": ["历史标签"]},
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "history_config")
            pipeline_runner.write_json(paths.parsed / "00_source_metadata.json", {"sha256": "same-sha"})
            pipeline_runner.write_json(paths.parsed / "00_run_config.json", history)
            with mock.patch.object(pipeline_runner, "call_stage", side_effect=AssertionError("LLM must not be called")):
                config, resolution = pipeline_runner.resolve_global_run_config(
                    args=args,
                    paths=paths,
                    stage=pipeline_runner.stage_map()["00a_global_config"],
                    source_text="完整短篇小说",
                    source_sha256="same-sha",
                    llm_script_path=None,
                )

        self.assertEqual(config["market_tags"], ["历史标签"])
        self.assertEqual(resolution["source"], "history")

    def test_global_config_resolution_user_file_skips_llm_and_cli_wins(self):
        """Verify global config resolution user file skips llm and cli wins."""
        user_config = pipeline_runner.merge_run_config(
            pipeline_runner.DEFAULT_RUN_CONFIG,
            {"target_episodes": 50, "market_tags": ["用户文件标签"]},
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "run_config.json"
            config_path.write_text(json.dumps(user_config, ensure_ascii=False), encoding="utf-8")
            args = pipeline_runner.build_parser().parse_args(
                [
                    "--novel",
                    "novel.txt",
                    "--run-config",
                    str(config_path),
                    "--target-episodes",
                    "60",
                    "--dry-run",
                ]
            )
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "user_config")
            with mock.patch.object(pipeline_runner, "call_stage", side_effect=AssertionError("LLM must not be called")):
                config, resolution = pipeline_runner.resolve_global_run_config(
                    args=args,
                    paths=paths,
                    stage=pipeline_runner.stage_map()["00a_global_config"],
                    source_text="完整短篇小说",
                    source_sha256="user-sha",
                    llm_script_path=None,
                )

        self.assertEqual(config["target_episodes"], 60)
        self.assertEqual(config["market_tags"], ["用户文件标签"])
        self.assertEqual(resolution["source"], "user_config")

    def test_longform_prompt_roles_use_exact_target_episode_parameter(self):
        """Verify longform prompt roles use exact target episode parameter."""
        stage_ids = (
            "01_novel_summary",
            "02_storyline_understanding",
            "04_adaptation_direction",
            "05_plot_character_adaptation",
            "06_script_outline_design",
            "07_episode_planning",
        )
        stages = pipeline_runner.stage_map()
        for stage_id in stage_ids:
            template = (PROJECT_ROOT / stages[stage_id]["prompt_file"]).read_text(encoding="utf-8")
            with self.subTest(stage_id=stage_id):
                self.assertIn("{目标集数}", template)
                self.assertNotRegex(template, r"40\s*[-—–到至]\s*100")

    def test_editorial_review_prompt_and_report_cover_fixed_dimensions(self):
        """Verify editorial review prompt and report cover fixed dimensions."""
        context = {
            "run_id": "run_test",
            "episode_outlines": [{"episode_num": 1, "main_conflict": "被迫离家"}],
            "episode_outputs": [{"episode_num": 1, "final_script": "第1集"}],
        }
        prompt = editorial_review.build_review_prompt(
            context=context,
            mode="episodes",
            scope_label="EP1-3",
        )
        for dimension in editorial_review.EDITORIAL_DIMENSIONS:
            self.assertIn(dimension, prompt)

        report = {
            "审稿模式": "episodes",
            "审查范围": "EP1-3",
            "总体判断": "需要加强主角选择",
            "维度评分": [
                {"维度": dimension, "分数": 7, "证据": [], "问题": [], "改进建议": []}
                for dimension in editorial_review.EDITORIAL_DIMENSIONS
            ],
            "阻断性问题": [],
            "优势": [],
            "根因分析": [],
            "管线改进建议": [],
        }
        editorial_review.validate_review_report(report)
        rendered = editorial_review.render_review_markdown(report)
        self.assertIn("EP1-3", rendered)
        self.assertIn("主角主动性：7/10", rendered)

    def test_editorial_review_dry_run_uses_existing_artifacts_without_generation(self):
        """Verify editorial review dry run uses existing artifacts without generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "run_editorial"
            (run_dir / "outputs").mkdir(parents=True)
            (run_dir / "parsed").mkdir()
            (run_dir / "final").mkdir()
            (run_dir / "outputs" / "07_episode_planning.clean.json").write_text(
                json.dumps({"episode_outlines": [{"episode_num": item} for item in range(1, 6)]}, ensure_ascii=False),
                encoding="utf-8",
            )
            for episode_num in range(1, 6):
                (run_dir / "outputs" / f"08_script_body_generation_ep{episode_num:03d}.clean.json").write_text(
                    json.dumps(
                        {"final_script": f"第{episode_num}集", "state_update": {}, "continuity_update": {}},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

            summary = editorial_review.run_review(
                run_dir=run_dir,
                mode="episodes",
                episode_windows=(3, 5, 10),
                dry_run=True,
            )

            self.assertEqual([item["status"] for item in summary["results"]], ["DRY_RUN", "DRY_RUN", "SKIPPED"])
            self.assertTrue((run_dir / "editorial_review" / "episodes_ep001_003.prompt.md").exists())
            self.assertFalse((run_dir / "editorial_review" / "episodes_ep001_003.md").exists())

    def test_editorial_review_resolves_relative_llm_script_before_run_cwd_change(self):
        """Verify editorial review resolves relative llm script before run cwd change."""
        report = {
            "审稿模式": "episodes",
            "审查范围": "EP1-1",
            "总体判断": "可用",
            "维度评分": [
                {"维度": dimension, "分数": 7, "证据": [], "问题": [], "改进建议": []}
                for dimension in editorial_review.EDITORIAL_DIMENSIONS
            ],
            "阻断性问题": [],
            "优势": [],
            "根因分析": [],
            "管线改进建议": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run_dir = root / "run_editorial"
            (run_dir / "outputs").mkdir(parents=True)
            (run_dir / "parsed").mkdir()
            (run_dir / "final").mkdir()
            (run_dir / "outputs" / "07_episode_planning.clean.json").write_text(
                json.dumps({"episode_outlines": [{"episode_num": 1}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (run_dir / "outputs" / "08_script_body_generation_ep001.clean.json").write_text(
                json.dumps({"final_script": "第1集", "state_update": {}, "continuity_update": {}}, ensure_ascii=False),
                encoding="utf-8",
            )
            script = root / "fake-llm.sh"
            script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            relative_script = (
                script.relative_to(Path.cwd())
                if script.is_relative_to(Path.cwd())
                else Path("fake-llm.sh")
            )

            with mock.patch.object(
                editorial_review.llm_client,
                "call_llm",
                return_value=mock.Mock(
                    raw=json.dumps(report, ensure_ascii=False),
                    clean=json.dumps(report, ensure_ascii=False),
                ),
            ) as call_llm:
                editorial_review.run_review(
                    run_dir=run_dir,
                    mode="episodes",
                    episode_windows=(1,),
                    llm_script_path=relative_script,
                )

            self.assertTrue(call_llm.call_args.kwargs["llm_script"].is_absolute())

    def test_source_anchors_are_stable_and_cover_nonempty_paragraphs(self):
        """Verify source anchors are stable and cover nonempty paragraphs."""
        text = "第一段。\n\n第二段。\n续句。"

        first = pipeline_runner.build_source_anchors(text)
        second = pipeline_runner.build_source_anchors(text)

        self.assertEqual(first, second)
        self.assertEqual([item["source_anchor_id"] for item in first], ["SRC_P0001", "SRC_P0002"])
        self.assertEqual(first[1]["text"], "第二段。\n续句。")

    def test_season_plan_audit_reports_repeat_time_rewind_and_capacity_gap(self):
        """Verify season plan audit reports repeat time rewind and capacity gap."""
        registry = season_plan_audit.build_event_registry(
            [
                {
                    "id": "E1",
                    "target_block": 1,
                    "episode_window": {"start": 1, "end": 2},
                    "source_fact_ids": ["F1"],
                    "child_beats": [{"child_beat_id": "E1-B1", "completion_evidence": "签字"}],
                },
            ]
        )
        episodes = [
            {
                "episode_num": 1,
                "block_id": 1,
                "event_ids": ["E1"],
                "consumed_child_beat_ids": ["E1-B1"],
                "event_consumption_status": "completed",
                "state_change": "合同已签",
                "ending_hook": "电话响起",
                "story_time": {"day_index": 2},
                "fact_transitions": [],
                "prop_continuity_plan": [],
            },
            {
                "episode_num": 2,
                "block_id": 1,
                "event_ids": ["E1"],
                "consumed_child_beat_ids": ["E1-B1"],
                "event_consumption_status": "completed",
                "state_change": "合同已签",
                "ending_hook": "电话响起",
                "story_time": {"day_index": 1},
                "fact_transitions": [],
                "prop_continuity_plan": [],
            },
        ]

        report = season_plan_audit.audit_season_plan(
            episode_outlines=episodes,
            event_registry=registry,
            adaptation_capacity={"natural_episode_range": {"min": 1, "max": 1}},
            target_episodes=2,
        )

        issues = {item["issue"] for item in report["findings"]}
        self.assertIn("child_beat_consumed_more_than_once", issues)
        self.assertIn("story_time_moves_backward", issues)
        self.assertIn("adjacent_episodes_repeat_state_change", issues)
        self.assertIn("target_exceeds_natural_capacity", issues)

    def test_season_plan_audit_reports_opening_payoff_and_foreshadowing_progression_gaps(self):
        """Verify season plan audit reports opening payoff and foreshadowing progression gaps."""
        registry = season_plan_audit.build_event_registry([])
        episodes = [
            {
                "episode_num": episode_num,
                "block_id": 1,
                "event_ids": [],
                "consumed_child_beat_ids": [],
                "event_role": "铺垫",
                "payoff_level": "无回收",
                "information_gain": "重复展示同一噩梦" if episode_num in {1, 4} else "一般铺垫",
                "foreshadowing_ids": ["F1"] if episode_num in {1, 4} else [],
                "story_time": {"day_index": episode_num},
                "fact_transitions": [],
                "prop_continuity_plan": [],
            }
            for episode_num in range(1, 6)
        ]

        report = season_plan_audit.audit_season_plan(
            episode_outlines=episodes,
            event_registry=registry,
            target_episodes=5,
        )

        issues = {item["issue"] for item in report["findings"]}
        self.assertIn("no_visible_payoff_in_first_three_episodes", issues)
        self.assertIn("no_additional_visible_payoff_in_episodes_four_to_five", issues)
        self.assertIn("foreshadowing_reused_without_escalation_or_payoff", issues)

        episodes[2]["counterattack"] = "主角完成目标，迫使爷爷公开认错"
        episodes[4]["state_change"] = "主角获得录取证明，爷爷失去控制"
        episodes[3]["event_role"] = "伏笔递进"
        report = season_plan_audit.audit_season_plan(
            episode_outlines=episodes,
            event_registry=registry,
            target_episodes=5,
        )
        issues = {item["issue"] for item in report["findings"]}
        self.assertNotIn("no_visible_payoff_in_first_three_episodes", issues)
        self.assertNotIn("no_additional_visible_payoff_in_episodes_four_to_five", issues)
        self.assertNotIn("foreshadowing_reused_without_escalation_or_payoff", issues)

    def test_season_plan_audit_uses_explicit_payoff_levels_and_accepts_local_props(self):
        """Verify season plan audit uses explicit payoff levels and accepts local props."""
        episodes = [
            {
                "episode_num": 1,
                "block_id": 1,
                "event_ids": [],
                "consumed_child_beat_ids": [],
                "payoff_level": "兑现",
                "story_time": {"day_index": 1},
                "fact_transitions": [],
                "prop_continuity_plan": [
                    {
                        "prop_id": "PROP_EP001_01",
                        "prop_name": "临时车票",
                        "end_holder": "主角",
                        "end_location": "书包",
                    }
                ],
            },
            {
                "episode_num": 2,
                "block_id": 1,
                "event_ids": [],
                "consumed_child_beat_ids": [],
                "payoff_level": "铺垫",
                "story_time": {"day_index": 2},
                "fact_transitions": [],
                "prop_continuity_plan": [
                    {
                        "prop_id": "PROP_EP001_01",
                        "prop_name": "临时车票",
                        "end_holder": "主角",
                        "end_location": "口袋",
                    }
                ],
            },
            {
                "episode_num": 3,
                "block_id": 1,
                "event_ids": [],
                "consumed_child_beat_ids": [],
                "payoff_level": "终局兑现",
                "story_time": {"day_index": 3},
                "fact_transitions": [],
                "prop_continuity_plan": [],
            },
        ]

        report = season_plan_audit.audit_season_plan(
            episode_outlines=episodes,
            event_registry=season_plan_audit.build_event_registry([]),
            target_episodes=3,
        )

        issues = {item["issue"] for item in report["findings"]}
        self.assertNotIn("no_visible_payoff_in_first_three_episodes", issues)
        self.assertNotIn("no_final_climax_in_terminal_window", issues)
        self.assertNotIn("prop_not_declared_in_stage05_registry", issues)
        self.assertEqual(report["final_climax_episodes"], [3])

    def test_season_plan_audit_rejects_local_prop_first_seen_in_wrong_episode(self):
        """Verify season plan audit rejects local prop first seen in wrong episode."""
        report = season_plan_audit.audit_season_plan(
            episode_outlines=[
                {
                    "episode_num": 2,
                    "block_id": 1,
                    "event_ids": [],
                    "consumed_child_beat_ids": [],
                    "story_time": {"day_index": 1},
                    "fact_transitions": [],
                    "prop_continuity_plan": [
                        {
                            "prop_id": "PROP_EP003_01",
                            "prop_name": "未来道具",
                            "end_holder": "主角",
                            "end_location": "桌上",
                        }
                    ],
                }
            ],
            event_registry=season_plan_audit.build_event_registry([]),
            target_episodes=3,
        )

        self.assertTrue(
            any(item.get("issue") == "local_prop_used_before_declared_episode" for item in report["findings"])
        )

    def test_local_event_consumption_status_uses_cumulative_child_registry(self):
        """Verify local event consumption status uses cumulative child registry."""
        registry = season_plan_audit.build_event_registry(
            [
                {
                    "id": "E1",
                    "target_block": 1,
                    "episode_window": {"start": 1, "end": 2},
                    "child_beats": [{"child_beat_id": "E1-B1"}, {"child_beat_id": "E1-B2"}],
                },
            ]
        )
        episodes = [
            {
                "episode_num": 1,
                "event_ids": ["E1"],
                "consumed_child_beat_ids": ["E1-B1"],
                "event_consumption_status": "completed",
            },
            {
                "episode_num": 2,
                "event_ids": ["E1"],
                "consumed_child_beat_ids": ["E1-B2"],
                "event_consumption_status": "ongoing",
            },
        ]

        repaired = season_plan_audit.apply_local_consumption_status(episodes, event_registry=registry)

        self.assertEqual(repaired[0]["event_consumption_status"], "ongoing")
        self.assertEqual(repaired[1]["event_consumption_status"], "completed")

    def test_new_source_and_season_contract_fields_are_required(self):
        """Verify new source and season contract fields are required."""
        stage02 = pipeline_runner.dry_run_payload("02_storyline_understanding", {"target_episodes": 40})
        stage02.pop("adaptation_capacity")
        with self.assertRaisesRegex(ValueError, r"02_storyline_understanding\.adaptation_capacity missing"):
            validators.validate_stage_contract("02_storyline_understanding", stage02)

        stage03 = pipeline_runner.dry_run_payload("03_plot_character_extract", {})
        stage03["source_plot_points"][0].pop("source_fact_ids")
        with self.assertRaisesRegex(ValueError, r"source_plot_points\[0\]\.source_fact_ids missing"):
            validators.validate_stage_contract("03_plot_character_extract", stage03)

        stage05 = pipeline_runner.dry_run_payload("05_plot_character_adaptation", {"target_episodes": 40})
        stage05["event_pool"][0].pop("dramatic_delta")
        with self.assertRaisesRegex(ValueError, r"event_pool\[0\]\.dramatic_delta missing"):
            validators.validate_stage_contract("05_plot_character_adaptation", stage05)

        stage07 = pipeline_runner.dry_run_payload("07_episode_planning", {"target_episodes": 40})
        stage07["episode_outlines"][0].pop("story_time")
        with self.assertRaisesRegex(ValueError, r"episode_outlines\[0\]\.story_time missing"):
            validators.validate_stage_contract("07_episode_planning", stage07)

    def test_prop_registry_optional_lineage_ids_must_exist_but_may_be_empty(self):
        """Verify prop registry optional lineage ids must exist but may be empty."""
        stage05 = pipeline_runner.normalize_stage_output(
            "05_plot_character_adaptation",
            pipeline_runner.dry_run_payload("05_plot_character_adaptation", {"target_episodes": 40}),
        )
        stage05["prop_registry"][0]["replaces_prop_id"] = ""
        stage05["prop_registry"][0]["parent_container_id"] = ""
        validators.validate_stage_contract("05_plot_character_adaptation", stage05)

        stage05["prop_registry"][0]["created_from_event_id"] = None
        stage05["prop_registry"][0]["replaces_prop_id"] = None
        stage05["prop_registry"][0]["parent_container_id"] = None
        validators.validate_stage_contract("05_plot_character_adaptation", stage05)

        stage05["prop_registry"][0].pop("parent_container_id")
        with self.assertRaisesRegex(ValueError, r"prop_registry\[0\]\.parent_container_id missing"):
            validators.validate_stage_contract("05_plot_character_adaptation", stage05)

    def test_prop_registry_normalizer_fills_optional_ids_and_list_shape(self):
        """Verify prop registry normalizer fills optional ids and list shape."""
        stage05 = pipeline_runner.dry_run_payload(
            "05_plot_character_adaptation",
            {"target_episodes": 40},
        )
        item = stage05["prop_registry"][0]
        item.pop("created_from_event_id")
        item.pop("replaces_prop_id")
        item["parent_container_id"] = None
        item["terminal_states"] = "销毁"

        normalized, report = pipeline_runner.normalize_stage_output_with_report(
            "05_plot_character_adaptation",
            stage05,
        )

        normalized_item = normalized["prop_registry"][0]
        self.assertEqual(normalized_item["created_from_event_id"], "")
        self.assertEqual(normalized_item["replaces_prop_id"], "")
        self.assertEqual(normalized_item["parent_container_id"], "")
        self.assertEqual(normalized_item["terminal_states"], ["销毁"])
        self.assertEqual(report["status"], "CHANGED")
        validators.validate_stage_contract("05_plot_character_adaptation", normalized)

        prompt = pipeline_runner.render_stage05_foundation_prompt({})
        self.assertIn("不得省略字段或输出 null", prompt)
        self.assertIn("终止状态始终输出字符串数组", prompt)

    def test_prop_registry_normalizer_removes_future_and_reciprocal_replacement_edges(self):
        """Verify prop registry normalizer removes future and reciprocal replacement edges."""
        stage05 = pipeline_runner.dry_run_payload(
            "05_plot_character_adaptation",
            {"target_episodes": 40},
        )
        stage05["prop_registry"] = [
            {
                "prop_id": "PROP_OLD",
                "prop_name": "旧笔袋",
                "entity_kind": "item",
                "created_episode": 2,
                "activation_episode": 2,
                "initial_state": {"holder": "方华", "location": "家", "status": "使用中"},
                "created_from_event_id": "E1",
                "replaces_prop_id": "PROP_NEW",
                "parent_container_id": "",
                "terminal_states": [],
            },
            {
                "prop_id": "PROP_NEW",
                "prop_name": "新笔袋",
                "entity_kind": "item",
                "created_episode": 8,
                "activation_episode": 8,
                "initial_state": {"holder": "方华", "location": "学校", "status": "新建"},
                "created_from_event_id": "E3",
                "replaces_prop_id": "PROP_OLD",
                "parent_container_id": "",
                "terminal_states": [],
            },
        ]

        normalized, report = pipeline_runner.normalize_stage_output_with_report(
            "05_plot_character_adaptation",
            stage05,
        )

        by_id = {item["prop_id"]: item for item in normalized["prop_registry"]}
        self.assertEqual(by_id["PROP_OLD"]["replaces_prop_id"], "")
        self.assertEqual(by_id["PROP_NEW"]["replaces_prop_id"], "PROP_OLD")
        self.assertIn(
            "normalize_prop_replacement_dag",
            [item["operation"] for item in report["operations"]],
        )

    def test_episode_delta_normalizer_reanchors_high_confidence_effect_evidence(self):
        """Verify episode delta normalizer reanchors high confidence effect evidence."""
        delta = pipeline_runner.dry_run_payload("08_script_body_generation", {})
        delta["final_script"] = (
            "第一集\n1-1    卧室    夜    内\n出场人物：方华\n"
            "△她转头看向墙上日历——日期显示高考前一天。\n"
            "△林可卧室里，林可把花生酱扔进垃圾桶。"
        )
        delta["continuity_update"]["completed_effect_evidence"] = [
            {"effect_id": "F1", "evidence_span": "△方华转头看向墙上日历——日期显示高考前一天。"},
            {"effect_id": "F2", "evidence_span": "△林可把花生酱扔进垃圾桶。"},
        ]

        normalized, report = pipeline_runner.normalize_stage_output_with_report(
            "08_script_body_generation",
            delta,
        )

        evidence = normalized["continuity_update"]["completed_effect_evidence"]
        self.assertIn(evidence[0]["evidence_span"], normalized["final_script"])
        self.assertEqual(evidence[1]["evidence_span"], "林可把花生酱扔进垃圾桶。")
        self.assertIn(
            "reanchor_completed_effect_evidence",
            [item["operation"] for item in report["operations"]],
        )

    def test_episode_delta_normalizer_does_not_reanchor_ambiguous_or_unrelated_evidence(self):
        """Verify episode delta normalizer does not reanchor ambiguous or unrelated evidence."""
        delta = pipeline_runner.dry_run_payload("08_script_body_generation", {})
        delta["final_script"] = "第一集\n△方华收起手机。\n△林可收起手机。"
        delta["continuity_update"]["completed_effect_evidence"] = [
            {"effect_id": "F1", "evidence_span": "△爷爷已经在学校签完合同。"},
        ]

        normalized, _report = pipeline_runner.normalize_stage_output_with_report(
            "08_script_body_generation",
            delta,
        )

        self.assertEqual(
            normalized["continuity_update"]["completed_effect_evidence"][0]["evidence_span"],
            "△爷爷已经在学校签完合同。",
        )

    def test_reanchored_effect_evidence_allows_atomic_transaction_commit(self):
        """Verify reanchored effect evidence allows atomic transaction commit."""
        event = pipeline_runner._build_dry_run_event(
            1,
            {"block_id": 1, "start_episode": 1, "end_episode": 1},
        )
        event["episode_window"] = {"start": 1, "end": 1}
        transaction = pipeline_runner._build_dry_run_transaction(1, 1)
        event["child_beats"] = [transaction]
        schedule = event_transactions.build_transaction_schedule([event], target_episodes=1)
        effect_id = transaction["effects"][0]["effect_id"]
        output = pipeline_runner.dry_run_payload(
            "08_script_body_generation",
            {"episode_outline": {"episode_num": 1, "title": "重新锚定"}},
        )
        output["final_script"] = "第一集\n△她转头看向墙上日历——日期显示高考前一天。"
        output["continuity_update"]["completed_beat_ids"] = [transaction["child_beat_id"]]
        output["continuity_update"]["completed_effect_evidence"] = [
            {
                "effect_id": effect_id,
                "evidence_span": "△方华转头看向墙上日历——日期显示高考前一天。",
            }
        ]

        normalized = pipeline_runner.normalize_stage_output(
            "08_script_body_generation",
            output,
        )
        report = event_transactions.validate_episode_script(
            normalized,
            contract=event_transactions.execution_contract_for_episode(schedule, 1),
        )

        self.assertFalse(
            any(
                item.get("issue") == "effect_evidence_span_not_found_verbatim_in_script"
                for item in report["findings"]
            )
        )

    def test_episode_delta_normalizer_fills_optional_notes(self):
        """Verify episode delta normalizer fills optional notes."""
        delta = pipeline_runner.dry_run_payload("08_script_body_generation", {})
        delta["state_update"].pop("next_episode_bridge")
        delta["continuity_update"]["scene_boundary_check"].pop("merge_note")

        normalized, report = pipeline_runner.normalize_stage_output_with_report(
            "08_script_body_generation",
            delta,
        )

        self.assertEqual(normalized["state_update"]["next_episode_bridge"], "")
        self.assertEqual(normalized["continuity_update"]["scene_boundary_check"]["merge_note"], "")
        self.assertEqual(report["status"], "CHANGED")
        validators.validate_stage_contract("08_script_body_generation", normalized)

        normalized["state_update"]["next_episode_bridge"] = None
        normalized["continuity_update"]["scene_boundary_check"]["merge_note"] = None
        validators.validate_stage_contract("08_script_body_generation", normalized)

    def test_episode_delta_normalizer_preserves_no_change_operations_for_audit(self):
        """Verify episode delta normalizer preserves no change operations for audit."""
        delta = pipeline_runner.dry_run_payload("08_script_body_generation", {})
        delta["state_update"]["audience_fact_changes"] = [
            {"fact_id": "F1", "operation": "不变", "detail": "观众仍已知", "evidence": "画面"},
            {"fact_id": "F2", "operation": "add", "detail": "新信息", "evidence": "手机"},
        ]
        delta["continuity_update"]["prop_state_changes"] = [
            {"prop_id": "P1", "operation": "保持", "holder": "方华", "location": "家", "status": "完好", "evidence": "道具在桌上"},
            {
                "prop_id": "P2",
                "operation": "update",
                "holder": "方华",
                "location": "学校",
                "status": "携带",
                "evidence": "放入书包",
            },
        ]

        normalized, report = pipeline_runner.normalize_stage_output_with_report(
            "08_script_body_generation",
            delta,
        )

        self.assertEqual(
            [item["fact_id"] for item in normalized["state_update"]["audience_fact_changes"]],
            ["F1", "F2"],
        )
        self.assertEqual(
            [item["prop_id"] for item in normalized["continuity_update"]["prop_state_changes"]],
            ["P1", "P2"],
        )
        self.assertEqual(report["status"], "CHANGED")
        with self.assertRaisesRegex(ValueError, "operation invalid"):
            validators.validate_episode_delta_operations(normalized)

    def test_source_fact_alignment_reports_unknown_anchor_actor_and_fact_reference(self):
        """Verify source fact alignment reports unknown anchor actor and fact reference."""
        findings = validators.source_fact_ledger_findings(
            [
                {
                    "fact_id": "F1",
                    "actor": "人物甲",
                    "action": "签字",
                    "object": "合同",
                    "result": "合同生效",
                    "source_anchor_ids": ["SRC_P0001", "SRC_MISSING"],
                    "certainty": "explicit",
                    "interpretation_note": "",
                }
            ],
            source_anchors=[{"source_anchor_id": "SRC_P0001", "text": "人物乙拿走合同。"}],
            source_plot_points=[{"source_fact_ids": ["F2"]}],
        )

        issues = {item["issue"] for item in findings}
        self.assertIn("unknown_source_anchor_ids", issues)
        self.assertIn("explicit_actor_not_found_in_anchor", issues)
        self.assertIn("unknown_source_fact_ids", issues)

    def test_source_fact_alignment_reports_interpretation_note_that_corrects_canonical_action(self):
        """Verify source fact alignment reports interpretation note that corrects canonical action."""
        findings = validators.source_fact_ledger_findings(
            [
                {
                    "fact_id": "SF026",
                    "actor": "方建成",
                    "action": "从监狱打电话要求方华赡养",
                    "object": "方华",
                    "result": "方华去医院探望",
                    "source_anchor_ids": ["SRC_P0001"],
                    "certainty": "inferred",
                    "interpretation_note": "原著此处是笔误，实际为从医院打电话。",
                }
            ],
            source_anchors=[
                {
                    "source_anchor_id": "SRC_P0001",
                    "text": "方建成胃癌手术后住院，从病房打来电话要求方华赡养。",
                }
            ],
        )

        self.assertTrue(
            any(item["issue"] == "interpretation_note_corrects_canonical_fact" for item in findings)
        )

    def test_event_dramatic_delta_rejects_unchanged_state(self):
        """Verify event dramatic delta rejects unchanged state."""
        findings = validators.event_dramatic_delta_findings(
            [{"id": 1, "dramatic_delta": {"dimension": "power", "before": "对方掌控", "after": "对方掌控"}}]
        )

        self.assertEqual(findings[0]["issue"], "before_after_unchanged")

    def test_event_independence_requires_concrete_non_repetition_evidence(self):
        """Verify event independence requires concrete non repetition evidence."""
        vague = validators.event_independence_findings(
            [{"id": 1, "dramatic_delta": {"why_not_repetition": "进一步推进了剧情"}}]
        )
        concrete = validators.event_independence_findings(
            [{"id": 1, "dramatic_delta": {"why_not_repetition": "新证据暴露后导致权力变化"}}]
        )
        structural = validators.event_independence_findings(
            [
                {
                    "id": 2,
                    "dramatic_delta": {
                        "why_not_repetition": "法律关系发生不可逆断裂，人物转入新的物理空间，角色功能也随之改变"
                    },
                }
            ]
        )

        self.assertEqual(vague[0]["issue"], "event_independence_reason_lacks_concrete_evidence")
        self.assertEqual(concrete, [])
        self.assertEqual(structural, [])

    def test_event_child_beat_capacity_covers_event_window(self):
        """Verify event child beat capacity covers event window."""
        short = pipeline_runner.normalize_event_child_beats(
            {
                "event_pool": [
                    {
                        "id": 1,
                        "episode_window": {"start": 1, "end": 3},
                        "expected_episode_span": 3,
                        "child_beats": ["施压", "留证"],
                    }
                ]
            }
        )["event_pool"]
        enough = pipeline_runner.normalize_event_child_beats(
            {
                "event_pool": [
                    {
                        "id": 1,
                        "episode_window": {"start": 1, "end": 3},
                        "expected_episode_span": 3,
                        "child_beats": ["施压", "留证", "反噬"],
                    }
                ]
            }
        )["event_pool"]

        findings = validators.event_child_beat_capacity_findings(short)

        self.assertEqual(findings[0]["issue"], "child_beat_count_below_event_span")
        self.assertEqual(findings[0]["expected_minimum"], 3)
        self.assertEqual(validators.event_child_beat_capacity_findings(enough), [])

    def test_event_transaction_atomicity_allows_same_scene_chain_and_rejects_weak_evidence(self):
        """Verify event transaction atomicity allows same scene chain and rejects weak evidence."""
        transaction = pipeline_runner._build_dry_run_transaction(1, 1)
        transaction["action"] = "主角取出文件，然后交给证人"
        transaction["completion_evidence_terms"] = ["画面"]
        event = pipeline_runner._build_dry_run_event(1, {"block_id": 1, "start_episode": 1, "end_episode": 1})
        event["episode_window"] = {"start": 1, "end": 1}
        event["child_beats"] = [transaction]

        findings = event_transactions.transaction_atomicity_findings([event])
        issues = {item["issue"] for item in findings}

        self.assertNotIn("action_contains_explicit_time_jump", issues)
        self.assertNotIn("action_may_contain_multiple_state_changes", issues)
        self.assertIn("completion_requires_at_least_two_specific_evidence_terms", issues)

    def test_event_transaction_atomicity_rejects_explicit_time_jump_and_result_stage_conflict(self):
        """Verify event transaction atomicity rejects explicit time jump and result stage conflict."""
        time_jump = pipeline_runner._build_dry_run_transaction(1, 1)
        time_jump["action"] = "主角提交材料，数日后收到结果"
        result_conflict = pipeline_runner._build_dry_run_transaction(1, 2)
        result_conflict["action"] = "高考成绩页面直接显示北大录取"
        event = pipeline_runner._build_dry_run_event(
            1,
            {"block_id": 1, "start_episode": 1, "end_episode": 2},
        )
        event["episode_window"] = {"start": 1, "end": 2}
        event["child_beats"] = [time_jump, result_conflict]

        issues = {
            item["issue"]
            for item in event_transactions.transaction_atomicity_findings([event])
        }

        self.assertIn("action_contains_explicit_time_jump", issues)
        self.assertIn("score_release_cannot_directly_equal_admission_result", issues)

    def test_event_transaction_atomicity_allows_leading_time_anchor_and_score_line(self):
        """Verify event transaction atomicity allows leading time anchor and score line."""
        time_anchor = pipeline_runner._build_dry_run_transaction(1, 1)
        time_anchor["action"] = "数周后，方华打开查分页面确认总分和位次"
        score_line = pipeline_runner._build_dry_run_transaction(1, 2)
        score_line["action"] = "高考成绩达到往年北大录取线，方华决定准备填报志愿"
        event = pipeline_runner._build_dry_run_event(
            1,
            {"block_id": 1, "start_episode": 1, "end_episode": 2},
        )
        event["episode_window"] = {"start": 1, "end": 2}
        event["child_beats"] = [time_anchor, score_line]

        issues = {
            item["issue"]
            for item in event_transactions.transaction_atomicity_findings([event])
        }

        self.assertNotIn("action_contains_explicit_time_jump", issues)
        self.assertNotIn("score_release_cannot_directly_equal_admission_result", issues)

    def test_event_transaction_schedule_assigns_exact_owner_per_episode(self):
        """Verify event transaction schedule assigns exact owner per episode."""
        blocks = pipeline_runner.build_longform_blocks(40)
        events = pipeline_runner._build_dry_run_event_pool(12, blocks)

        schedule = event_transactions.build_transaction_schedule(
            events,
            target_episodes=40,
        )

        self.assertEqual(schedule["status"], "PASS")
        self.assertEqual(len(schedule["episodes"]), 40)
        self.assertTrue(
            all(
                item["assigned_event_id"] and item["authorized_transaction_ids"]
                for item in schedule["episodes"]
            )
        )
        self.assertEqual(
            schedule["episodes"][3]["authorized_transaction_ids"],
            ["E1-B4"],
        )
        self.assertEqual(
            schedule["episodes"][4]["authorized_transaction_ids"],
            ["E2-B1"],
        )

    def test_event_transaction_schedule_uses_semantic_boundaries_not_share_flag_alone(self):
        """Verify event transaction schedule uses semantic boundaries not share flag alone."""
        event = pipeline_runner._build_dry_run_event(
            1,
            {"block_id": 1, "start_episode": 1, "end_episode": 3},
        )
        event["episode_window"] = {"start": 1, "end": 3}
        transactions = [
            pipeline_runner._build_dry_run_transaction(1, index)
            for index in range(1, 7)
        ]
        for transaction in transactions:
            transaction["can_share_episode_with_next"] = False
        event["child_beats"] = transactions

        schedule = event_transactions.build_transaction_schedule(
            [event],
            target_episodes=3,
        )

        self.assertEqual(schedule["status"], "PASS")
        bundle_sizes = [
            len(item["authorized_transaction_ids"])
            for item in schedule["episodes"]
        ]
        self.assertEqual(sum(bundle_sizes), 6)
        self.assertTrue(all(1 <= size <= 3 for size in bundle_sizes))

    def test_event_transaction_schedule_does_not_publish_invalid_fallback(self):
        """Verify event transaction schedule does not publish invalid fallback."""
        event = pipeline_runner._build_dry_run_event(
            1,
            {"block_id": 1, "start_episode": 1, "end_episode": 1},
        )
        event["episode_window"] = {"start": 1, "end": 1}
        event["child_beats"] = [
            pipeline_runner._build_dry_run_transaction(1, index)
            for index in range(1, 5)
        ]

        schedule = event_transactions.build_transaction_schedule(
            [event],
            target_episodes=1,
        )

        self.assertEqual(schedule["status"], "BLOCK")
        self.assertEqual(schedule["episodes"][0]["authorized_transaction_ids"], [])
        self.assertIn("diagnostic_fallback", schedule["events"]["1"])

    def test_event_transaction_atomicity_rejects_reused_evidence_signature(self):
        """Verify event transaction atomicity rejects reused evidence signature."""
        first = pipeline_runner._build_dry_run_transaction(1, 1)
        second = pipeline_runner._build_dry_run_transaction(2, 1)
        second["effects"][0]["evidence_terms"] = list(first["effects"][0]["evidence_terms"])
        second["completion_evidence_terms"] = list(first["completion_evidence_terms"])
        events = []
        for event_id, transaction, episode_num in (
            (1, first, 1),
            (2, second, 2),
        ):
            event = pipeline_runner._build_dry_run_event(
                event_id,
                {
                    "block_id": 1,
                    "start_episode": episode_num,
                    "end_episode": episode_num,
                },
            )
            event["episode_window"] = {"start": episode_num, "end": episode_num}
            event["child_beats"] = [transaction]
            events.append(event)

        findings = event_transactions.transaction_atomicity_findings(events)

        self.assertTrue(
            any(
                item["issue"] == "evidence_signature_reused_by_multiple_transactions"
                for item in findings
            )
        )

    def test_event_transaction_plan_rejects_future_semantic_leak(self):
        """Verify event transaction plan rejects future semantic leak."""
        event = pipeline_runner._build_dry_run_event(
            1,
            {"block_id": 1, "start_episode": 1, "end_episode": 2},
        )
        event["episode_window"] = {"start": 1, "end": 2}
        event["not_before_episode"] = 1
        event["not_after_episode"] = 2
        event["expected_episode_span"] = 2
        event["child_beats"] = [
            pipeline_runner._build_dry_run_transaction(1, 1),
            pipeline_runner._build_dry_run_transaction(1, 2),
        ]
        schedule = event_transactions.build_transaction_schedule(
            [event],
            target_episodes=2,
        )
        episode = {
            "episode_num": 1,
            "event_ids": [1],
            "consumed_child_beat_ids": ["E1-B1"],
            "target_script_density": {
                "must_cover_beats": [
                    {
                        "beat_id": "E1-B1",
                        "action": event["child_beats"][0]["action"],
                        "completion_evidence": event["child_beats"][0]["completion_evidence"],
                    }
                ]
            },
            "closing_beat": "事件1证据2出现，状态2已改变",
        }

        report = event_transactions.validate_episode_plan(
            episode,
            contract=event_transactions.execution_contract_for_episode(schedule, 1),
        )

        self.assertEqual(report["status"], "BLOCK")
        self.assertTrue(
            any(
                item["check"] == "future_transaction_semantic_leak"
                for item in report["findings"]
            )
        )

    def test_event_transaction_semantic_guard_ignores_distant_lexical_collision(self):
        """Verify event transaction semantic guard ignores distant lexical collision."""
        events = []
        for event_id, episode_num in ((1, 1), (2, 8)):
            event = pipeline_runner._build_dry_run_event(
                event_id,
                {
                    "block_id": 1,
                    "start_episode": episode_num,
                    "end_episode": episode_num,
                },
            )
            event["episode_window"] = {"start": episode_num, "end": episode_num}
            event["child_beats"] = [
                pipeline_runner._build_dry_run_transaction(event_id, 1)
            ]
            events.append(event)
        schedule = event_transactions.build_transaction_schedule(
            events,
            target_episodes=8,
        )
        future = schedule["transactions"]["E2-B1"]
        episode = {
            "episode_num": 1,
            "event_ids": [1],
            "consumed_child_beat_ids": ["E1-B1"],
            "target_script_density": {"must_cover_beats": [{"beat_id": "E1-B1"}]},
            "closing_beat": future["completion_evidence"],
        }

        report = event_transactions.validate_episode_plan(
            episode,
            contract=event_transactions.execution_contract_for_episode(schedule, 1),
        )

        self.assertFalse(
            any(
                item["check"] == "future_transaction_semantic_leak"
                for item in report["findings"]
            )
        )

    def test_event_transaction_plan_accepts_numeric_equivalent_event_id_and_handoff_preview(self):
        """Verify event transaction plan accepts numeric equivalent event id and handoff preview."""
        event = pipeline_runner._build_dry_run_event(
            1,
            {"block_id": 1, "start_episode": 1, "end_episode": 2},
        )
        event["episode_window"] = {"start": 1, "end": 2}
        event["child_beats"] = [
            pipeline_runner._build_dry_run_transaction(1, 1),
            pipeline_runner._build_dry_run_transaction(1, 2),
        ]
        schedule = event_transactions.build_transaction_schedule(
            [event],
            target_episodes=2,
        )
        future = schedule["transactions"]["E1-B2"]
        episode = {
            "episode_num": 1,
            "event_ids": ["1"],
            "consumed_child_beat_ids": ["E1-B1"],
            "target_script_density": {"must_cover_beats": [{"beat_id": "E1-B1"}]},
            "main_conflict": "当前事务冲突",
            "counterattack": "当前事务反击",
            "next_episode_start_state": future["completion_evidence"],
            "ending_hook": future["completion_evidence"],
        }

        report = event_transactions.validate_episode_plan(
            episode,
            contract=event_transactions.execution_contract_for_episode(schedule, 1),
        )

        self.assertEqual(report["status"], "PASS")

    def test_event_transaction_completion_accepts_configured_synonyms(self):
        """Verify event transaction completion accepts configured synonyms."""
        transaction = pipeline_runner._build_dry_run_transaction(1, 1)
        transaction["completion_evidence_terms"] = ["考试现在开始", "放进", "打死结"]
        transaction["effects"][0]["evidence_terms"] = ["开始考试", "塞进", "拧紧袋口"]
        event = pipeline_runner._build_dry_run_event(
            1,
            {"block_id": 1, "start_episode": 1, "end_episode": 1},
        )
        event["episode_window"] = {"start": 1, "end": 1}
        event["child_beats"] = [transaction]
        schedule = event_transactions.build_transaction_schedule(
            [event],
            target_episodes=1,
        )
        output = pipeline_runner.dry_run_payload(
            "08_script_body_generation",
            {"episode_outline": {"episode_num": 1, "title": "同义表达"}},
        )
        output["continuity_update"]["completed_beat_ids"] = ["E1-B1"]
        output["continuity_update"].pop("completed_effect_evidence", None)
        output["final_script"] = "第1集\n1-1    教室    日    内\n出场人物：老师\n△老师宣布开考，把材料放入袋中并封口。"

        report = event_transactions.validate_episode_script(
            output,
            contract=event_transactions.execution_contract_for_episode(schedule, 1),
        )

        self.assertEqual(report["status"], "PASS")

    def test_event_transaction_completion_accepts_exam_and_score_paraphrases(self):
        """Verify event transaction completion accepts exam and score paraphrases."""
        event = pipeline_runner._build_dry_run_event(
            2,
            {"block_id": 1, "start_episode": 4, "end_episode": 5},
        )
        event["episode_window"] = {"start": 4, "end": 5}
        exam = pipeline_runner._build_dry_run_transaction(2, 1)
        exam["completion_evidence_terms"] = ["走出", "考场", "结束", "全部科目"]
        score = pipeline_runner._build_dry_run_transaction(2, 2)
        score["completion_evidence_terms"] = ["查分", "分数", "北大"]
        event["child_beats"] = [exam, score]
        schedule = event_transactions.build_transaction_schedule(
            [event],
            target_episodes=5,
        )

        ep4 = pipeline_runner.dry_run_payload(
            "08_script_body_generation",
            {"episode_outline": {"episode_num": 4, "title": "考完"}},
        )
        ep4["continuity_update"]["completed_beat_ids"] = ["E2-B1"]
        ep4["continuity_update"].pop("completed_effect_evidence", None)
        ep4["final_script"] = (
            "第四集\n4-1    教室    日    内\n出场人物：方华、监考老师\n"
            "△铃声响起。\n监考老师（收卷）：考试结束，停笔。\n"
            "△方华看一眼最后一科的答题卡，交卷后推开教学楼玻璃门，走下台阶。"
        )
        ep5 = pipeline_runner.dry_run_payload(
            "08_script_body_generation",
            {"episode_outline": {"episode_num": 5, "title": "查分"}},
        )
        ep5["continuity_update"]["completed_beat_ids"] = ["E2-B2"]
        ep5["continuity_update"].pop("completed_effect_evidence", None)
        ep5["final_script"] = (
            "第五集\n5-1    客厅    日    内\n出场人物：方华\n"
            "△方华打开成绩查询页面，刷新后屏幕显示总分694。\n"
            "△她另开网页查看往年北京大学投档位次，拿笔圈住自己的位次。"
        )

        self.assertEqual(
            event_transactions.validate_episode_script(
                ep4,
                contract=event_transactions.execution_contract_for_episode(schedule, 4),
            )["status"],
            "PASS",
        )
        self.assertEqual(
            event_transactions.validate_episode_script(
                ep5,
                contract=event_transactions.execution_contract_for_episode(schedule, 5),
            )["status"],
            "PASS",
        )

    def test_event_transaction_requires_verbatim_effect_evidence_when_v2_field_present(self):
        """Verify event transaction requires verbatim effect evidence when v2 field present."""
        event = pipeline_runner._build_dry_run_event(
            1,
            {"block_id": 1, "start_episode": 1, "end_episode": 1},
        )
        event["episode_window"] = {"start": 1, "end": 1}
        transaction = pipeline_runner._build_dry_run_transaction(1, 1)
        event["child_beats"] = [transaction]
        schedule = event_transactions.build_transaction_schedule([event], target_episodes=1)
        effect_id = transaction["effects"][0]["effect_id"]
        script = "第一集\n1-1    教室    日    内\n出场人物：主角\n△主角展示事件1证据1，状态1已改变。"
        output = {
            "final_script": script,
            "continuity_update": {
                "completed_beat_ids": ["E1-B1"],
                "completed_effect_evidence": [
                    {"effect_id": effect_id, "evidence_span": "△主角展示事件1证据1，状态1已改变。"}
                ],
            },
        }

        passed = event_transactions.validate_episode_script(
            output,
            contract=event_transactions.execution_contract_for_episode(schedule, 1),
        )
        self.assertEqual(passed["status"], "PASS")

        output["continuity_update"]["completed_effect_evidence"][0]["evidence_span"] = "正文里不存在的概括"
        blocked = event_transactions.validate_episode_script(
            output,
            contract=event_transactions.execution_contract_for_episode(schedule, 1),
        )
        self.assertTrue(
            any(
                item.get("issue") == "effect_evidence_span_not_found_verbatim_in_script"
                for item in blocked["findings"]
            )
        )

    def test_typed_application_transition_does_not_trigger_future_process_leak(self):
        """Verify typed application transition does not trigger future process leak."""
        event = pipeline_runner._build_dry_run_event(
            9,
            {"block_id": 1, "start_episode": 1, "end_episode": 4},
        )
        event["episode_window"] = {"start": 1, "end": 4}
        stages = (
            ("not_started", "exam_completed", "高考全部科目结束", ["高考", "全部科目"]),
            ("exam_completed", "score_rank_published", "成绩位次发布", ["成绩", "位次"]),
            ("score_rank_published", "application_submitted", "志愿提交成功", ["志愿", "提交"]),
            ("application_submitted", "admission_decision", "正式录取结果发布", ["正式录取", "结果"]),
        )
        transactions = []
        for index, (from_stage, to_stage, action, terms) in enumerate(stages, start=1):
            transaction = pipeline_runner._build_dry_run_transaction(9, index)
            transaction["action"] = action
            transaction["completion_evidence_terms"] = terms
            transaction["effects"][0]["evidence_terms"] = terms
            transaction["process_transition"] = {
                "process_id": "education_admission",
                "from_stage": from_stage,
                "to_stage": to_stage,
            }
            transactions.append(transaction)
        event["child_beats"] = transactions
        schedule = event_transactions.build_transaction_schedule([event], target_episodes=4)
        application = transactions[2]
        output = {
            "final_script": "第三集\n3-1    客厅    日    内\n出场人物：主角\n△屏幕显示志愿提交成功。",
            "continuity_update": {
                "completed_beat_ids": [application["child_beat_id"]],
                "completed_effect_evidence": [
                    {
                        "effect_id": application["effects"][0]["effect_id"],
                        "evidence_span": "△屏幕显示志愿提交成功。",
                    }
                ],
            },
        }

        report = event_transactions.validate_episode_script(
            output,
            contract=event_transactions.execution_contract_for_episode(schedule, 3),
        )

        self.assertFalse(
            any(item["check"] == "future_process_stage_leak" for item in report["findings"])
        )
        self.assertEqual(report["status"], "PASS")

    def test_event_transaction_process_guard_blocks_registration_before_admission(self):
        """Verify event transaction process guard blocks registration before admission."""
        event = pipeline_runner._build_dry_run_event(
            2,
            {"block_id": 1, "start_episode": 5, "end_episode": 6},
        )
        event["episode_window"] = {"start": 5, "end": 6}
        score = pipeline_runner._build_dry_run_transaction(2, 1)
        score["action"] = "方华查分确认总分和位次"
        score["completion_evidence_terms"] = ["查分", "分数", "位次"]
        notice = pipeline_runner._build_dry_run_transaction(2, 2)
        notice["action"] = "方华正式录取后签收北大录取通知书"
        notice["completion_evidence_terms"] = ["录取通知书", "北大", "签收"]
        event["child_beats"] = [score, notice]
        schedule = event_transactions.build_transaction_schedule(
            [event],
            target_episodes=6,
        )
        output = pipeline_runner.dry_run_payload(
            "08_script_body_generation",
            {"episode_outline": {"episode_num": 5, "title": "越权"}},
        )
        output["continuity_update"]["completed_beat_ids"] = ["E2-B1"]
        output["final_script"] = (
            "第五集\n5-1    客厅    日    内\n出场人物：方华\n"
            "△屏幕显示总分694。\n方华（拉开行李箱）：新生群发了报到须知，我先去定宿舍。"
        )

        report = event_transactions.validate_episode_script(
            output,
            contract=event_transactions.execution_contract_for_episode(schedule, 5),
        )

        self.assertTrue(
            any(
                item["check"] == "future_process_stage_leak"
                for item in report["findings"]
            )
        )

    def test_process_guard_ignores_entity_mentions_without_completion_evidence(self):
        """Verify process guard ignores entity mentions without completion evidence."""
        event = pipeline_runner._build_dry_run_event(
            3,
            {"block_id": 1, "start_episode": 1, "end_episode": 1},
        )
        event["episode_window"] = {"start": 1, "end": 1}
        transaction = pipeline_runner._build_dry_run_transaction(3, 1)
        transaction["action"] = "方华收好准考证，准备明天参加高考"
        transaction["process_transition"] = {
            "process_id": "FLOW_GAOKAO",
            "from_stage": "not_started",
            "to_stage": "exam_completed",
        }
        event["child_beats"] = [transaction]
        schedule = event_transactions.build_transaction_schedule([event], target_episodes=1)
        output = pipeline_runner.dry_run_payload(
            "08_script_body_generation",
            {"episode_outline": {"episode_num": 1, "title": "考前"}},
        )
        output["continuity_update"]["completed_beat_ids"] = [transaction["child_beat_id"]]
        output["final_script"] = (
            "第一集\n1-1    卧室    夜    内\n出场人物：方华\n"
            "△方华把准考证放进书包。桌上的清单写着高考、录取通知书、报到材料。"
        )

        report = event_transactions.validate_episode_script(
            output,
            contract=event_transactions.execution_contract_for_episode(schedule, 1),
        )

        self.assertFalse(
            any(item["check"] == "future_process_stage_leak" for item in report["findings"])
        )

    def test_process_guard_ignores_prior_life_flashback_but_keeps_current_timeline_guard(self):
        """Verify process guard ignores prior life flashback but keeps current timeline guard."""
        event = pipeline_runner._build_dry_run_event(
            4,
            {"block_id": 1, "start_episode": 1, "end_episode": 2},
        )
        event["episode_window"] = {"start": 1, "end": 2}
        prepare = pipeline_runner._build_dry_run_transaction(4, 1)
        prepare["action"] = "方华收好准考证等待高考"
        prepare["process_transition"] = {
            "process_id": "education_admission",
            "from_stage": "",
            "to_stage": "",
        }
        finish = pipeline_runner._build_dry_run_transaction(4, 2)
        finish["action"] = "高考全部科目结束"
        finish["completion_evidence_terms"] = ["高考", "全部科目", "结束"]
        finish["process_transition"] = {
            "process_id": "education_admission",
            "from_stage": "not_started",
            "to_stage": "exam_completed",
        }
        event["child_beats"] = [prepare, finish]
        schedule = event_transactions.build_transaction_schedule([event], target_episodes=2)
        contract = event_transactions.execution_contract_for_episode(schedule, 1)
        plan = {
            "episode_num": 1,
            "event_ids": [4],
            "consumed_child_beat_ids": [prepare["child_beat_id"]],
            "target_script_density": {
                "must_cover_beats": [{"beat_id": prepare["child_beat_id"]}],
            },
            "opening_beat": "方华在当下收好准考证",
            "closing_beat": "方华把准考证放进书包",
            "scene_plan": [
                {
                    "scene_purpose": "flashback 前世闪回",
                    "scene_boundary_reason": "前世记忆",
                    "must_include_beats": ["前世高考已经结束"],
                },
                {
                    "scene_purpose": "当下考前准备",
                    "scene_boundary_reason": "闪回结束回当下",
                    "must_include_beats": ["方华收好准考证"],
                },
            ],
        }

        report = event_transactions.validate_episode_plan(plan, contract=contract)
        self.assertFalse(
            any(item["check"] == "future_process_stage_leak" for item in report["findings"])
        )

        plan["closing_beat"] = "当下高考全部科目已经结束"
        blocked = event_transactions.validate_episode_plan(plan, contract=contract)
        self.assertTrue(
            any(item["check"] == "future_process_stage_leak" for item in blocked["findings"])
        )

    def test_script_process_guard_ignores_explicit_flashback_block(self):
        """Verify script process guard ignores explicit flashback block."""
        event = pipeline_runner._build_dry_run_event(
            5,
            {"block_id": 1, "start_episode": 1, "end_episode": 2},
        )
        event["episode_window"] = {"start": 1, "end": 2}
        prepare = pipeline_runner._build_dry_run_transaction(5, 1)
        finish = pipeline_runner._build_dry_run_transaction(5, 2)
        finish["action"] = "高考全部科目结束"
        finish["completion_evidence_terms"] = ["高考", "全部科目", "结束"]
        finish["process_transition"] = {
            "process_id": "education_admission",
            "from_stage": "not_started",
            "to_stage": "exam_completed",
        }
        event["child_beats"] = [prepare, finish]
        schedule = event_transactions.build_transaction_schedule([event], target_episodes=2)
        output = {
            "final_script": (
                "第一集\n【闪回】\n△前世高考全部科目结束。\n【闪出】\n"
                "△当下方华把准考证放进书包。"
            ),
            "continuity_update": {"completed_beat_ids": [prepare["child_beat_id"]]},
        }

        report = event_transactions.validate_episode_script(
            output,
            contract=event_transactions.execution_contract_for_episode(schedule, 1),
        )
        self.assertFalse(
            any(item["check"] == "future_process_stage_leak" for item in report["findings"])
        )

    def test_unknown_process_transition_accepts_continuous_custom_stages(self):
        """Verify unknown process transition accepts continuous custom stages."""
        event = pipeline_runner._build_dry_run_event(
            7,
            {"block_id": 1, "start_episode": 1, "end_episode": 2},
        )
        event["episode_window"] = {"start": 1, "end": 2}
        first = pipeline_runner._build_dry_run_transaction(7, 1)
        first["process_transition"] = {
            "process_id": "PROC_DIVORCE",
            "from_stage": "意向表达",
            "to_stage": "口头达成",
        }
        first["can_share_episode_with_next"] = False
        second = pipeline_runner._build_dry_run_transaction(7, 2)
        second["process_transition"] = {
            "process_id": "PROC_DIVORCE",
            "from_stage": "口头达成",
            "to_stage": "法律执行完成",
        }
        event["child_beats"] = [first, second]

        findings = event_transactions.transaction_atomicity_findings([event])

        self.assertFalse(
            any(
                item.get("issue")
                in {"unsupported_process_stage", "process_transition_chain_is_not_continuous"}
                for item in findings
            )
        )

    def test_transaction_time_guard_allows_leading_date_but_blocks_internal_jump(self):
        """Verify transaction time guard allows leading date but blocks internal jump."""
        event = pipeline_runner._build_dry_run_event(
            8,
            {"block_id": 1, "start_episode": 1, "end_episode": 3},
        )
        event["episode_window"] = {"start": 1, "end": 3}
        leading = pipeline_runner._build_dry_run_transaction(8, 1)
        leading["action"] = "方华报到第三天接到父亲电话，当场拒绝寄钱"
        leading["can_share_episode_with_next"] = False
        internal = pipeline_runner._build_dry_run_transaction(8, 2)
        internal["action"] = "方华先提交材料；次日收到审批结果"
        internal["can_share_episode_with_next"] = False
        duration = pipeline_runner._build_dry_run_transaction(8, 3)
        duration["action"] = "方旭连续三天打电话，最后逼方华回家"
        event["child_beats"] = [leading, internal, duration]

        findings = event_transactions.transaction_atomicity_findings([event])
        blocked_ids = {
            item.get("transaction_id")
            for item in findings
            if item.get("issue") == "action_contains_explicit_time_jump"
        }

        self.assertNotIn("E8-B1", blocked_ids)
        self.assertIn("E8-B2", blocked_ids)
        self.assertIn("E8-B3", blocked_ids)

    def test_stage05_semantic_repair_prompt_contains_previous_output_and_findings(self):
        """Verify stage05 semantic repair prompt contains previous output and findings."""
        prompt = pipeline_runner.render_stage05_semantic_repair_prompt(
            "原始规则",
            previous_output={"event_pool": [{"id": 1, "title": "事件"}]},
            findings=[
                {
                    "path": "event_pool[0].child_beats[0].process_transition",
                    "transaction_id": "E1-B1",
                    "issue": "process_transition_must_advance_exactly_one_stage",
                }
            ],
        )

        self.assertIn("上次事件池完整输出", prompt)
        self.assertIn("E1-B1", prompt)
        self.assertIn("完整重写当前弧线事件池", prompt)

    def test_prop_activation_uses_first_transaction_owner_and_blocks_early_use(self):
        """Verify prop activation uses first transaction owner and blocks early use."""
        event = pipeline_runner._build_dry_run_event(
            1,
            {"block_id": 1, "start_episode": 7, "end_episode": 7},
        )
        event["episode_window"] = {"start": 7, "end": 7}
        transaction = pipeline_runner._build_dry_run_transaction(1, 1)
        transaction["action"] = "方华把方旭考公书混放进书架"
        event["child_beats"] = [transaction]
        schedule = event_transactions.build_transaction_schedule(
            [event],
            target_episodes=7,
            prop_registry=[
                {
                    "prop_id": "PROP_004",
                    "prop_name": "方旭考公书",
                    "created_episode": 5,
                }
            ],
        )
        prop = schedule["prop_activation_registry"][0]
        self.assertEqual(prop["created_episode"], 7)
        self.assertEqual(prop["declared_created_episode"], 5)

        episode = {
            "episode_num": 5,
            "event_ids": [],
            "consumed_child_beat_ids": [],
            "target_script_density": {"must_cover_beats": []},
            "prop_continuity_plan": [{"prop_id": "PROP_004"}],
        }
        report = event_transactions.validate_episode_plan(
            episode,
            contract=event_transactions.execution_contract_for_episode(schedule, 5),
        )

        self.assertTrue(
            any(item["check"] == "future_prop_activation" for item in report["findings"])
        )

    def test_stage07_normalizer_joins_canonical_actions_from_authorized_ids(self):
        """Verify stage07 normalizer joins canonical actions from authorized ids."""
        transaction = pipeline_runner._build_dry_run_transaction(1, 1)
        value = {
            "episode_outlines": [
                {
                    "episode_num": 1,
                    "consumed_child_beat_ids": ["E1-B1"],
                }
            ]
        }
        normalized = pipeline_runner.normalize_stage_output(
            "07_episode_planning",
            value,
            normalization_context={
                "episode_event_options": [
                    {
                        "episode_num": 1,
                        "authorized_transactions": [transaction],
                    }
                ]
            },
        )

        self.assertEqual(
            normalized["episode_outlines"][0]["consumed_child_beats"],
            [transaction["action"]],
        )

    def test_rejected_episode_keeps_script_without_mutating_active_ledger(self):
        """Verify rejected episode keeps script without mutating active ledger."""
        ledger = continuity_ledger.new_ledger()
        output = pipeline_runner.dry_run_payload(
            "08_script_body_generation",
            {"episode_outline": {"episode_num": 1, "title": "拒绝提交"}},
        )
        output["state_update"]["audience_fact_changes"] = [
            {
                "fact_id": "F1",
                "operation": "update",
                "detail": "不应写入 active 状态",
                "evidence": "屏幕",
            }
        ]

        rejected = continuity_ledger.record_rejected_episode(
            ledger,
            episode={"episode_num": 1, "title": "拒绝提交"},
            output=output,
            findings=[{"issue": "update_missing_record"}],
        )

        self.assertEqual(rejected["audience_facts"], {})
        self.assertEqual(rejected["generated_episodes"][0]["delta_commit_status"], "REJECTED")
        self.assertEqual(rejected["rejected_deltas"][0]["episode_num"], 1)

    def test_prop_registry_materializes_before_first_episode_mutation(self):
        """Verify prop registry materializes before first episode mutation."""
        ledger = continuity_ledger.new_ledger(
            prop_registry=[
                {
                    "prop_id": "PROP_004",
                    "prop_name": "旧笔袋",
                    "entity_kind": "item",
                    "activation_episode": 1,
                    "initial_state": {
                        "holder": "方华",
                        "location": "方华手中",
                        "status": "可用",
                    },
                }
            ]
        )
        ledger = continuity_ledger.materialize_prop_registry_for_episode(
            ledger,
            episode_num=1,
        )
        output = pipeline_runner.dry_run_payload(
            "08_script_body_generation",
            {"episode_outline": {"episode_num": 1, "title": "丢弃旧笔袋"}},
        )
        output["continuity_update"]["prop_state_changes"] = [
            {
                "prop_id": "PROP_004",
                "operation": "retire",
                "holder": "方华",
                "location": "垃圾桶",
                "status": "已丢弃",
                "evidence": "△方华把旧笔袋扔进垃圾桶。",
            }
        ]

        self.assertEqual(continuity_ledger.delta_operation_findings(ledger, output=output), [])
        merged = continuity_ledger.merge_episode_delta(
            ledger,
            episode={"episode_num": 1, "title": "丢弃旧笔袋"},
            output=output,
        )
        self.assertEqual(merged["props"]["PROP_004"]["lifecycle_status"], "retired")

    def test_collect_merge_keeps_script_but_commits_no_state_when_delta_is_invalid(self):
        """Verify collect merge keeps script but commits no state when delta is invalid."""
        ledger = continuity_ledger.new_ledger()
        first = pipeline_runner.dry_run_payload(
            "08_script_body_generation",
            {"episode_outline": {"episode_num": 1, "title": "第一集"}},
        )
        first["state_update"]["audience_fact_changes"] = [
            {
                "fact_id": "EP001_AUD_01",
                "operation": "add",
                "detail": "第一事实",
                "evidence": "第一集正文",
            }
        ]
        ledger = continuity_ledger.merge_episode_delta(
            ledger,
            episode={"episode_num": 1, "title": "第一集"},
            output=first,
        )
        second = pipeline_runner.dry_run_payload(
            "08_script_body_generation",
            {"episode_outline": {"episode_num": 2, "title": "第二集"}},
        )
        second["state_update"]["audience_fact_changes"] = [
            {
                "fact_id": "EP001_AUD_01",
                "operation": "add",
                "detail": "错误复用",
                "evidence": "第二集正文",
            }
        ]
        second["state_update"]["next_episode_bridge"] = "错误桥接不得落账"

        merged = continuity_ledger.merge_episode_delta(
            ledger,
            episode={"episode_num": 2, "title": "第二集"},
            output=second,
            collect_invalid_operations=True,
            commit_status="COMMITTED_WITH_WARNINGS",
        )

        self.assertEqual(merged["audience_facts"]["EP001_AUD_01"]["detail"], "第一事实")
        self.assertEqual(
            merged["generated_episodes"][-1]["delta_commit_status"],
            "STATE_UNCOMMITTED",
        )
        self.assertNotEqual(merged["next_episode_bridge"], "错误桥接不得落账")
        self.assertEqual(merged["state_blocks"][-1]["episode_num"], 2)
        self.assertEqual(merged["completed_transaction_digest"], ledger["completed_transaction_digest"])

    def test_release_preflight_blocks_rejected_commit_and_semantic_normalizer(self):
        """Verify release preflight blocks rejected commit and semantic normalizer."""
        report = release_preflight.build_release_preflight(
            transaction_schedule={"status": "PASS", "findings": []},
            planning_report={"status": "PASS", "findings": []},
            episode_transaction_reports=[
                {"episode_num": 1, "commit_status": "REJECTED", "findings": []}
            ],
            normalization_reports=[
                {
                    "artifact_id": "08_script_body_generation_ep001",
                    "operations": [
                        {
                            "operation": "normalize_script_scene_cast_from_dialogue_speakers",
                            "changed_paths": ["final_script"],
                        }
                    ],
                }
            ],
        )

        self.assertEqual(report["release_status"], "BLOCK")
        self.assertEqual(
            {item["check"] for item in report["blockers"]},
            {"episode_transaction_commit", "semantic_normalizer_mutation"},
        )

    def test_release_preflight_blocks_legacy_partial_commit(self):
        """Verify release preflight blocks legacy partial commit."""
        report = release_preflight.build_release_preflight(
            transaction_schedule={"status": "PASS", "findings": []},
            planning_report={"status": "PASS", "findings": []},
            episode_transaction_reports=[
                {
                    "episode_num": 1,
                    "status": "WARN",
                    "commit_status": "COMMITTED_WITH_WARNINGS",
                    "findings": [{"check": "future_process_stage_leak"}],
                }
            ],
        )

        self.assertEqual(report["release_status"], "BLOCK")
        self.assertEqual(
            report["blockers"][0]["check"],
            "episode_transaction_commit",
        )

    def test_runtime_stage05_and_07_prompts_include_fact_time_and_prop_contracts(self):
        """Verify runtime stage05 and 07 prompts include fact time and prop contracts."""
        stage05_values = {
            "run_config": {},
            "derived_config": {},
            "canonical_story_lock": {},
            "source_plot_points": [],
            "character_bible": [],
            "adaptation_direction": {},
            "flashback_screening": {},
            "source_fact_ledger": [],
            "adaptation_capacity": {},
        }
        foundation_prompt = pipeline_runner.render_stage05_foundation_prompt(stage05_values)
        event_prompt = pipeline_runner.render_stage05_event_prompt(
            stage05_values,
            arc={"arc_id": 1, "episode_range": "1-5"},
            spec={"arc_id": 1, "episode_range": "1-5", "event_count": 1, "start_event_id": 1, "end_event_id": 1},
            foundation={"conflict_engine": {}, "foreshadowing_pool": []},
        )
        self.assertIn("关键道具实体表", foundation_prompt)
        self.assertIn("原著事实ID", event_prompt)
        self.assertIn("戏剧状态变化", event_prompt)
        self.assertIn("事件独立性底线", event_prompt)
        self.assertIn("子情节点数量不得少于事件窗口长度", event_prompt)
        self.assertIn("全部事件的子情节点总数不得少于当前弧线集数", event_prompt)
        self.assertIn("重生、前世死亡回到过去", event_prompt)
        self.assertIn("事件1的窗口必须是第1集", event_prompt)
        self.assertIn("E事件ID-B序号", event_prompt)
        offset_event_prompt = pipeline_runner.render_stage05_event_prompt(
            stage05_values,
            arc={"arc_id": 2, "episode_range": "6-10"},
            spec={
                "arc_id": 2,
                "episode_range": "6-10",
                "event_count": 2,
                "start_event_id": 4,
                "end_event_id": 5,
            },
            foundation={"conflict_engine": {}, "foreshadowing_pool": []},
        )
        self.assertIn('"ID": 4', offset_event_prompt)
        self.assertIn('"子情节点ID": "E4-B1"', offset_event_prompt)
        self.assertIn('"目标篇章": 2', offset_event_prompt)

        dry07 = pipeline_runner.dry_run_payload("07_episode_planning", {"target_episodes": 40})
        values = {
            "episode_planning_scope": {
                "mode": "internal_block",
                "global_target_episodes": 40,
                "block_id": 1,
                "start_episode": 1,
                "end_episode": 1,
                "episode_count": 1,
                "current_block": dry07["block_plans"][0] | {"end_episode": 1, "episode_count": 1},
                "previous_handoff": {},
            },
            "run_config": {},
            "derived_config": {},
            "canonical_story_lock": {},
            "expanded_character_network": [],
            "episode_event_options": [],
            "event_pool": [],
            "foreshadowing_pool": [],
            "source_fact_ledger": [],
            "prop_registry": [],
            "adaptation_capacity": {},
            "flashback_screening": {},
            "conflict_engine": {},
            "block_state_plan": [],
            "qa_rules": [],
        }
        prompt07 = pipeline_runner.render_episode_planning_block_prompt(values)
        self.assertIn("故事时间", prompt07)
        self.assertIn("事实状态变更", prompt07)
        self.assertIn("原著事实账本", prompt07)
        self.assertIn("本集最后一场所在的日历日", prompt07)
        self.assertIn("同一伏笔ID第一次引用视为投放", prompt07)
        self.assertIn("每集只声明 `逐集合法事件选项` 中的已分配事件ID", prompt07)
        self.assertIn("已分配的1-3个 canonical 子情节点ID", prompt07)
        self.assertIn("必须与本集已消耗子情节点ID完全一致", prompt07)
        self.assertIn("`必覆盖情节` 只能有1-3个", prompt07)

    def test_episode_delta_v2_preserves_character_knowledge_and_history(self):
        """Verify episode delta v2 preserves character knowledge and history."""
        ledger = continuity_ledger.new_ledger()
        output = {
            "schema_version": "08_episode_delta_v2",
            "final_script": "第1集",
            "state_update": {
                "audience_fact_changes": [
                    {"fact_id": "F1", "operation": "add", "detail": "观众知道真相", "evidence": "对白"}
                ],
                "character_knowledge_changes": [
                    {"character_name": "方华", "fact_id": "F1", "operation": "add", "detail": "知道真相", "evidence": "手机屏幕"}
                ],
                "private_fact_changes": [],
                "next_episode_bridge": "方华等对方回复",
            },
            "continuity_update": {
                "completed_beat_ids": ["E1-B1"],
                "foreshadowing_changes": [],
                "open_thread_changes": [],
                "prop_state_changes": [],
                "last_scene_state": {},
                "scene_boundary_check": {},
                "narration_device_usage": {},
            },
        }

        merged = continuity_ledger.merge_episode_delta(
            ledger,
            episode={"episode_num": 1, "title": "证据"},
            output=output,
        )

        self.assertEqual(merged["character_knowledge"]["方华"]["F1"]["detail"], "知道真相")
        self.assertEqual(merged["history"][1]["record_id"], "F1")
        self.assertEqual(merged["generated_episodes"][0]["final_script"], "第1集")

    def test_active_continuity_view_excludes_resolved_and_retired_records(self):
        """Verify active continuity view excludes resolved and retired records."""
        ledger = continuity_ledger.new_ledger()
        ledger["audience_facts"] = {
            "F1": {"id": "F1", "status": "active", "detail": "未解决"},
            "F2": {"id": "F2", "status": "resolved", "detail": "已解决"},
        }
        ledger["props"] = {
            "P1": {"id": "P1", "status": "retired", "location": "已销毁"},
        }

        view = continuity_ledger.active_view(ledger)

        self.assertEqual(list(view["audience_facts"]), ["F1"])
        self.assertEqual(view["props"], {})

    def test_active_continuity_view_bounds_completed_digests(self):
        """Verify active continuity view bounds completed digests."""
        ledger = continuity_ledger.new_ledger()
        ledger["completed_transaction_digest"] = [
            {"episode_num": index, "transaction_ids": [f"E{index}-B1"]}
            for index in range(1, 41)
        ]
        ledger["completed_effect_digest"] = [
            {"episode_num": index, "effect_ids": [f"E{index}-B1-F1"]}
            for index in range(1, 41)
        ]

        view = continuity_ledger.active_view(ledger)

        self.assertEqual(len(view["completed_transaction_digest"]), continuity_ledger.ACTIVE_DIGEST_WINDOW)
        self.assertEqual(view["completed_transaction_digest"][0]["episode_num"], 33)
        self.assertEqual(view["completed_effect_digest"][-1]["episode_num"], 40)

    def test_episode_delta_rejects_update_on_missing_record(self):
        """Verify episode delta rejects update on missing record."""
        ledger = continuity_ledger.new_ledger()
        output = {
            "schema_version": "08_episode_delta_v2",
            "final_script": "第1集",
            "state_update": {
                "audience_fact_changes": [],
                "character_knowledge_changes": [],
                "private_fact_changes": [],
                "next_episode_bridge": "",
            },
            "continuity_update": {
                "completed_beat_ids": ["E1-B1"],
                "foreshadowing_changes": [],
                "open_thread_changes": [],
                "prop_state_changes": [
                    {
                        "prop_id": "PROP_PHONE",
                        "operation": "update",
                        "holder": "方华",
                        "location": "方华手中",
                        "status": "屏幕已锁定",
                        "evidence": "方华按灭屏幕",
                    }
                ],
                "last_scene_state": {},
                "scene_boundary_check": {},
                "narration_device_usage": {},
            },
        }

        findings = continuity_ledger.delta_operation_findings(ledger, output=output)

        self.assertEqual(findings[0]["issue"], "update_missing_record")
        with self.assertRaisesRegex(ValueError, "update_missing_record"):
            continuity_ledger.merge_episode_delta(
                ledger,
                episode={"episode_num": 1, "title": "锁屏"},
                output=output,
            )

    def test_episode_delta_rejects_resolve_on_missing_record(self):
        """Verify episode delta rejects resolve on missing record."""
        ledger = continuity_ledger.new_ledger()
        output = pipeline_runner.dry_run_payload(
            "08_script_body_generation",
            {"episode_outline": {"episode_num": 1}},
        )
        output["continuity_update"]["open_thread_changes"] = [
            {
                "thread_id": "THREAD_MISSING",
                "operation": "resolve",
                "detail": "不存在的线索不能直接关闭",
            }
        ]

        findings = continuity_ledger.delta_operation_findings(ledger, output=output)

        self.assertTrue(
            any(item["issue"] == "resolve_missing_record" for item in findings)
        )

    def test_active_continuity_view_uses_lifecycle_status_without_hiding_prop_business_status(self):
        """Verify active continuity view uses lifecycle status without hiding prop business status."""
        ledger = continuity_ledger.new_ledger()
        ledger["props"] = {
            "P1": {
                "id": "P1",
                "status": "内容物已销毁但空瓶保留",
                "lifecycle_status": "active",
            },
            "P2": {
                "id": "P2",
                "status": "已销毁",
                "lifecycle_status": "retired",
            },
        }

        view = continuity_ledger.active_view(ledger)

        self.assertEqual(view["props"]["P1"]["status"], "内容物已销毁但空瓶保留")
        self.assertNotIn("P2", view["props"])

    def test_legacy_08_snapshot_migrates_string_character_knowledge(self):
        """Verify legacy 08 snapshot migrates string character knowledge."""
        migrated = continuity_ledger.normalize_episode_delta(
            {
                "final_script": "第1集",
                "state_update": {},
                "continuity_update": {
                    "audience_known": ["观众已知"],
                    "character_known": {"方华": "单个字符串也不应丢失"},
                    "writer_private": [],
                    "completed_beats": ["E1-B1"],
                },
            }
        )

        change = migrated["state_update"]["character_knowledge_changes"][0]
        self.assertEqual(change["character_name"], "方华")
        self.assertEqual(change["detail"], "单个字符串也不应丢失")
        self.assertEqual(migrated["continuity_update"]["completed_beat_ids"], ["E1-B1"])

    def test_episode_generation_context_keeps_only_three_full_scripts_and_active_state(self):
        """Verify episode generation context keeps only three full scripts and active state."""
        ledger = continuity_ledger.new_ledger()
        ledger["generated_episodes"] = [
            {"episode_num": idx, "title": f"第{idx}集", "final_script": f"SCRIPT-{idx}"}
            for idx in range(1, 8)
        ]
        ledger["audience_facts"] = {
            "ACTIVE": {"id": "ACTIVE", "status": "active", "detail": "有效"},
            "OLD": {"id": "OLD", "status": "resolved", "detail": "旧事"},
        }
        outlines = [
            {"episode_num": idx, "event_ids": [f"E{idx}"], "ending_hook": "钩子" * 100}
            for idx in range(1, 41)
        ]

        views = episode_generation_context.build_episode_generation_views(
            episode=outlines[7],
            episode_index=7,
            episode_outlines=outlines,
            ledger=ledger,
            target_tone="冷感克制、掌控反击",
            source_voice_anchors=[
                {"source_fact": "主角不再替家人兜底", "emotion": "冷静止损"},
            ],
        )

        self.assertEqual([item["episode_num"] for item in views["recent_episode_scripts"]], [5, 6, 7])
        self.assertNotIn("SCRIPT-4", json.dumps(views, ensure_ascii=False))
        self.assertNotIn("OLD", views["active_continuity_view"]["audience_facts"])
        self.assertLessEqual(len(json.dumps(views["future_event_reservations"], ensure_ascii=False)), 1000)
        self.assertEqual(views["relevant_source_context"]["target_tone"], "冷感克制、掌控反击")
        self.assertEqual(
            views["relevant_source_context"]["source_voice_anchors"][0]["emotion"],
            "冷静止损",
        )

    def test_episode_generation_context_uses_deduplicated_execution_sheet(self):
        """Verify episode generation context uses deduplicated execution sheet."""
        episode = {
            "episode_num": 4,
            "title": "拒绝退学",
            "main_conflict": "家人逼方华退学",
            "counterattack": "方华拒绝签字",
            "information_gain": "家人隐瞒录取短信",
            "opening_beat": "方华接过退学申请表",
            "closing_beat": "方华撕下家长签字页",
            "next_episode_start_state": "校方要求监护人到场",
            "event_ids": [2],
            "consumed_child_beat_ids": ["E2-B1"],
            "required_character_names": ["方华", "爷爷"],
            "scene_plan": [
                {
                    "scene_no": 1,
                    "location": "校办",
                    "time": "日",
                    "space": "内",
                    "appearing_character_names": ["方华", "爷爷"],
                    "scene_purpose": "反击",
                    "must_include_beats": ["方华接表", "方华拒签"],
                    "scene_boundary_reason": "同一场连续动作",
                    "visible_space_tokens": ["校办"],
                }
            ],
            "target_script_density": {
                "target_range_chars": "650-780",
                "minimum_effective_chars": 650,
                "maximum_chars": 780,
                "must_cover_beats": [
                    {"beat_id": "B1", "action": "方华拒绝签字", "completion_evidence": "签字栏保持空白"}
                ],
                "optional_compression_beats": [],
                "expansion_strategy": "补动作",
                "scene_char_budgets": [
                    {"scene_no": 1, "target_chars": 700, "must_cover_beat_ids": ["B1"]}
                ],
            },
        }

        views = episode_generation_context.build_episode_generation_views(
            episode=episode,
            episode_index=3,
            episode_outlines=[episode],
            ledger=continuity_ledger.new_ledger(),
        )
        sheet = views["episode_execution_sheet"]

        self.assertNotIn("main_conflict", sheet)
        self.assertNotIn("counterattack", sheet)
        self.assertNotIn("information_gain", sheet)
        self.assertNotIn("must_include_beats", sheet["scene_plan"][0])
        self.assertNotIn("expansion_strategy", sheet["target_script_density"])
        self.assertEqual(sheet["target_script_density"]["must_cover_beats"][0]["beat_id"], "B1")

    def test_protagonist_tone_balance_reports_stress_without_recovery(self):
        """Verify protagonist tone balance reports stress without recovery."""
        findings = pipeline_runner.protagonist_tone_balance_findings(
            [
                {
                    "episode_num": 1,
                    "final_script": "方华颤抖。方华僵住。方华喘气。方华脸色发白。方华指节发白。",
                }
            ],
            target_tone="冷感复仇、冷静掌控",
        )

        self.assertEqual(findings[0]["issue"], "stress_reactions_overwhelm_control_recovery")
        self.assertEqual(
            pipeline_runner.protagonist_tone_balance_findings(
                [{"episode_num": 1, "final_script": "方华颤抖后稳住手，抬头直视，按下拒接键。"}],
                target_tone="冷感复仇、冷静掌控",
            ),
            [],
        )

    def test_read_text_detects_gb18030_novel(self):
        """Verify read text detects gb18030 novel."""
        source = PROJECT_ROOT / "docs" / "固执爷爷听不懂人话.txt"

        result = text_io.read_text_with_metadata(source)

        self.assertIn(result.encoding, {"gb18030", "gbk"})
        self.assertIn("固执爷爷听不懂人话", result.text)
        self.assertGreater(result.non_space_chars, 7000)

    def test_validate_source_length_accepts_business_range(self):
        """Verify validate source length accepts business range."""
        metadata = {"non_space_chars": 10358, "path": "novel.txt"}

        validators.validate_source_metadata(metadata)

        with self.assertRaisesRegex(ValueError, "7000-50000"):
            validators.validate_source_metadata({"non_space_chars": 6999, "path": "short.txt"})

    def test_render_template_rejects_unresolved_placeholders(self):
        """Verify render template rejects unresolved placeholders."""
        rendered = prompt_renderer.render_template("标题：{title}", {"title": "测试"})
        self.assertEqual(rendered, "标题：测试")

        with self.assertRaisesRegex(ValueError, "missing"):
            prompt_renderer.render_template("标题：{missing}", {"title": "测试"})

    def test_script_body_prompt_requires_scene_cast_and_visual_action_language(self):
        """Verify script body prompt requires scene cast and visual action language."""
        prompt = (
            PROJECT_ROOT / "prompts" / "clean" / "08_剧本正文生成_script_body_generation.md"
        ).read_text(encoding="utf-8")

        self.assertIn("每场必须标识出场人物", prompt)
        self.assertIn("严禁文学化描述", prompt)
        self.assertIn("所有描述都必须能被视觉化呈现", prompt)
        self.assertIn("可拍摄", prompt)
        self.assertIn("1-1    地点    日/夜/傍晚    内/外", prompt)
        self.assertIn("△画面描述", prompt)
        self.assertIn("人物（表情动作）：台词", prompt)
        self.assertIn("人物（表情动作，OS）：台词", prompt)
        self.assertIn(
            "人物（表情动作1）：台词，（表情动作2或与台词有发生顺序的场景变化），台词（特写）",
            prompt,
        )
        self.assertIn("人物（表情动作）：台词，（VO）台词", prompt)
        self.assertIn("△VO同时与画面进行：画面描述", prompt)
        self.assertIn("【字幕：xxxx】", prompt)
        self.assertIn("不要使用旧场次格式", prompt)
        self.assertIn("闪回标记必须单独成行", prompt)
        self.assertIn("不要输出 `[音效]`、`[镜头]`、`画面：`、`镜头拉远`、`画外音`", prompt)
        self.assertIn("场头地点必须覆盖本场所有可见空间", prompt)
        self.assertIn("写了 `人物（VO）`，该人物必须列入同场 `出场人物`", prompt)
        self.assertIn("来电未接、拒接、扣屏或铃声停止", prompt)
        self.assertIn("不能原样重复“屏幕显示来电——某人”", prompt)
        self.assertIn("90秒配置的 `650-780` 是唯一创作目标区间", prompt)
        self.assertIn("每出现一段颤抖", prompt)
        self.assertIn("恢复掌控的可见动作", prompt)
        self.assertIn("超过最大字数时", prompt)
        self.assertNotIn("第1-3集不超过1000字", prompt)
        self.assertIn("不能因为只有 1 场就压成 200-400 字", prompt)
        self.assertIn('"作者私有事实变更": [', prompt)
        self.assertIn('"正文证据": "正文原句"', prompt)
        self.assertIn("正文证据不可省略", prompt)

    def test_episode_planning_prompt_requires_scene_location_to_cover_visible_space(self):
        """Verify episode planning prompt requires scene location to cover visible space."""
        prompt = (PROJECT_ROOT / "prompts" / "clean" / "07_剧集规划_episode_planning.md").read_text(encoding="utf-8")

        self.assertIn("场头地点必须覆盖本场所有可见空间", prompt)
        self.assertIn("隔门、隔窗、玻璃门外看到另一空间", prompt)

    def test_stage_contract_blocks_missing_nested_phase_field(self):
        """Verify stage contract blocks missing nested phase field."""
        self.assertTrue(hasattr(validators, "validate_stage_contract"), "validate_stage_contract missing")
        data = {
            "global_outline": "全剧大纲",
            "longform_blocks": [
                {
                    "block_id": 1,
                    "phase": "setup",
                    "title": "起",
                    "start_episode": 1,
                    "end_episode": 10,
                    "episode_count": 10,
                    "goal": "破局",
                    "antagonist": "反派",
                    "hook": "钩子",
                    "foreshadowing_plan": ["投放证据"],
                    "source_asset_ids": [1],
                }
            ],
            "phase_breakdown": {
                "setup": {
                    "episode_range": "1-10",
                    "dramatic_goal": "破局",
                    "stage_antagonist": "反派",
                    "foreshadowing_plan": ["投放证据"],
                }
            },
            "episode_budget": [{"phase": "setup", "start_episode": 1, "end_episode": 10, "episode_count": 10}],
            "event_release_schedule": [
                {
                    "block_id": 1,
                    "episode_range": "1-10",
                    "available_event_ids": [1],
                    "reserved_payoff": "保留反转",
                    "forbidden_early_events": [],
                }
            ],
            "block_event_plan": [
                {"block_id": 1, "must_use_event_ids": [1], "conflict_modes": ["压迫"], "source_anchor_goal": "源锚"}
            ],
            "climax_guardrails": {
                "major_climax_window": "8-10",
                "final_climax_not_before_episode": 8,
                "epilogue_max_episodes": 1,
            },
            "block_state_plan": [
                {
                    "block_id": 1,
                    "entry_state": "被压迫",
                    "exit_state": "开始反击",
                    "character_state_curve": "从忍耐到反击",
                    "handoff_to_next_block": "新证据出现",
                }
            ],
            "qa_rules": ["事件不得越窗"],
        }

        with self.assertRaisesRegex(
            ValueError,
            r"06_script_outline_design\.phase_breakdown\.setup\.hook_strategy missing",
        ):
            validators.validate_stage_contract("06_script_outline_design", data)

    def test_normalize_06_fills_terminal_block_hook_and_handoff(self):
        """Verify normalize 06 fills terminal block hook and handoff."""
        data = pipeline_runner.dry_run_payload("06_script_outline_design", {"target_episodes": 40})
        data["longform_blocks"][-1].pop("hook", None)
        data["block_state_plan"][-1]["handoff_to_next_block"] = None

        normalized = pipeline_runner.normalize_stage_output("06_script_outline_design", data)

        self.assertEqual(normalized["longform_blocks"][-1]["hook"], "终局收束，无下一block")
        self.assertEqual(normalized["block_state_plan"][-1]["handoff_to_next_block"], "终局收束，无下一block")
        validators.validate_stage_contract("06_script_outline_design", normalized)

    def test_stage_contract_blocks_missing_episode_outline_field(self):
        """Verify stage contract blocks missing episode outline field."""
        self.assertTrue(hasattr(validators, "validate_stage_contract"), "validate_stage_contract missing")
        def make_episode(episode_num: int) -> dict[str, Any]:
            """Handle make episode."""
            return {
                "episode_num": episode_num,
                "title": f"第{episode_num}集",
                "block_id": 2,
                "phase": "development",
                "episode_reason": "推进证据",
                "main_conflict": "反派施压",
                "counterattack": "主角留证",
                "information_gain": "新证据",
                "state_change": "主角更主动",
                "opening_beat": "承接上一集门口追问",
                "closing_beat": "证据被看见",
                "next_episode_start_state": "反派追问",
                "consumed_child_beats": ["证据被看见"],
                "event_ids": [4],
                "foreshadowing_ids": [],
                "required_character_names": ["沈念"],
                "appearing_character_names": ["沈念"],
                "ending_hook": "门外脚步声",
                "adapted_plot_point_ids": [2],
                "conflict_mode": "evidence_turn",
                "pattern_family": "evidence_turn",
                "payoff_level": "A",
                "event_role": "推进",
                "event_consumption_status": "ongoing",
                "source_anchor": "源锚",
                "expansion_delta": "扩写见证者",
                "boundary_check": {
                        "risk_level": "low",
                        "protagonist_action": "留证",
                        "why_allowed": "自保",
                        "mitigation": "无",
                    },
                "content_sensitivity_check": {"risk_level": "low", "risk_reason": "无", "mitigation": "无"},
                "unresolved_threads_after_episode": ["证据归属"],
                "is_epilogue": False,
                "scene_plan": [
                    {
                        "scene_no": 1,
                        "location": "村口",
                        "time": "日",
                        "space": "外",
                        "appearing_character_names": ["沈念"],
                        "scene_purpose": "counterattack",
                        "must_include_beats": ["沈念留证"],
                        "scene_boundary_reason": "本集自然开场",
                    }
                ],
            }

        episodes = [make_episode(index) for index in range(1, 13)]
        episodes[11].pop("opening_beat")

        with self.assertRaisesRegex(ValueError, r"07_episode_planning\.episode_outlines\[11\]\.opening_beat missing"):
            validators.validate_stage_contract(
                "07_episode_planning",
                {"episode_allocation": [], "block_plans": [], "episode_outlines": episodes},
            )

    def test_stage_contract_blocks_missing_07_scene_plan(self):
        """Verify stage contract blocks missing 07 scene plan."""
        episode = {
            "episode_num": 1,
            "title": "第1集",
            "block_id": 1,
            "phase": "setup",
            "episode_reason": "建立冲突",
            "main_conflict": "反派施压",
            "counterattack": "主角留证",
            "information_gain": "新证据",
            "state_change": "主角更主动",
            "opening_beat": "村口追问",
            "closing_beat": "证据被看见",
            "next_episode_start_state": "反派追问",
            "consumed_child_beats": ["证据被看见"],
            "event_ids": [1],
            "foreshadowing_ids": [],
            "required_character_names": ["沈念"],
            "appearing_character_names": ["沈念"],
            "ending_hook": "门外脚步声",
            "adapted_plot_point_ids": [1],
            "conflict_mode": "evidence_turn",
            "pattern_family": "evidence_turn",
            "payoff_level": "A",
            "event_role": "推进",
            "event_consumption_status": "ongoing",
            "source_anchor": "源锚",
            "expansion_delta": "扩写见证者",
            "boundary_check": {"risk_level": "low", "protagonist_action": "留证", "why_allowed": "自保", "mitigation": "无"},
            "content_sensitivity_check": {"risk_level": "low", "risk_reason": "无", "mitigation": "无"},
            "unresolved_threads_after_episode": ["证据归属"],
            "is_epilogue": False,
        }

        with self.assertRaisesRegex(ValueError, r"07_episode_planning\.episode_outlines\[0\]\.scene_plan missing"):
            validators.validate_stage_contract(
                "07_episode_planning",
                {"episode_allocation": [], "block_plans": [], "episode_outlines": [episode]},
            )

    def test_stage_contract_blocks_missing_07_scene_plan_item_field(self):
        """Verify stage contract blocks missing 07 scene plan item field."""
        episode = {
            "episode_num": 1,
            "title": "第1集",
            "block_id": 1,
            "phase": "setup",
            "episode_reason": "建立冲突",
            "main_conflict": "反派施压",
            "counterattack": "主角留证",
            "information_gain": "新证据",
            "state_change": "主角更主动",
            "opening_beat": "村口追问",
            "closing_beat": "证据被看见",
            "next_episode_start_state": "反派追问",
            "consumed_child_beats": ["证据被看见"],
            "event_ids": [1],
            "foreshadowing_ids": [],
            "required_character_names": ["沈念"],
            "appearing_character_names": ["沈念"],
            "ending_hook": "门外脚步声",
            "adapted_plot_point_ids": [1],
            "conflict_mode": "evidence_turn",
            "pattern_family": "evidence_turn",
            "payoff_level": "A",
            "event_role": "推进",
            "event_consumption_status": "ongoing",
            "source_anchor": "源锚",
            "expansion_delta": "扩写见证者",
            "boundary_check": {"risk_level": "low", "protagonist_action": "留证", "why_allowed": "自保", "mitigation": "无"},
            "content_sensitivity_check": {"risk_level": "low", "risk_reason": "无", "mitigation": "无"},
            "unresolved_threads_after_episode": ["证据归属"],
            "is_epilogue": False,
            "scene_plan": [
                {
                    "scene_no": 1,
                    "location": "村口",
                    "time": "日",
                    "space": "外",
                    "appearing_character_names": ["沈念"],
                    "scene_purpose": "counterattack",
                    "must_include_beats": ["沈念留证"],
                }
            ],
            "narration_device_plan": {
                "planned_os_count": 0,
                "planned_flashback_count": 0,
                "planned_vo_count": 0,
                "reason": "用当场动作交代",
                "visual_replacement_strategy": "用手机录音和围观反应替代内心解释",
            },
        }

        with self.assertRaisesRegex(
            ValueError,
            r"07_episode_planning\.episode_outlines\[0\]\.scene_plan\[0\]\.scene_boundary_reason missing",
        ):
            validators.validate_stage_contract(
                "07_episode_planning",
                {"episode_allocation": [], "block_plans": [], "episode_outlines": [episode]},
            )

    def test_stage_contract_blocks_missing_08_continuity_field(self):
        """Verify stage contract blocks missing 08 continuity field."""
        self.assertTrue(hasattr(validators, "validate_stage_contract"), "validate_stage_contract missing")
        data = pipeline_runner.dry_run_payload(
            "08_script_body_generation",
            {"episode_execution_sheet": {"episode_num": 1, "required_character_names": ["沈念"]}},
        )
        data["continuity_update"].pop("completed_beat_ids")

        with self.assertRaisesRegex(
            ValueError,
            r"08_script_body_generation\.continuity_update\.completed_beat_ids missing",
        ):
            validators.validate_stage_contract("08_script_body_generation", data)

    def test_stage_contract_blocks_missing_08_last_scene_state_fields(self):
        """Verify stage contract blocks missing 08 last scene state fields."""
        data = pipeline_runner.dry_run_payload(
            "08_script_body_generation",
            {"episode_outline": {"episode_num": 1, "required_character_names": ["方华", "爷爷"]}},
        )
        data["continuity_update"].pop("last_scene_state", None)
        with self.assertRaisesRegex(
            ValueError,
            r"08_script_body_generation\.continuity_update\.last_scene_state missing",
        ):
            validators.validate_stage_contract("08_script_body_generation", data)

        data["continuity_update"]["last_scene_state"] = {
            "location": "公共空间",
            "present_character_names": ["方华"],
        }
        with self.assertRaisesRegex(
            ValueError,
            r"last_scene_state\.visible_result missing",
        ):
            validators.validate_stage_contract("08_script_body_generation", data)

    def test_validate_continuity_facts_rejects_last_scene_mismatch_and_premature_bridge(self):
        """Verify validate continuity facts rejects last scene mismatch and premature bridge."""
        script = "\n".join(
            [
                "第一集",
                "1-1    方家卧室    日    内",
                "出场人物：方华、爷爷",
                "△方华把录取通知收进书包。",
                "方华（按住书包）：我现在去学校。",
            ]
        )
        output = {
            "final_script": script,
            "continuity_update": {
                "next_episode_bridge": "方华已抵达学校教室",
                "last_scene_state": {
                    "location": "学校教室",
                    "present_character_names": ["方华"],
                    "visible_result": "方华坐在课桌前",
                },
            },
        }

        findings = validators.continuity_fact_findings(output, episode_num=1)

        self.assertTrue(any(item["issue"] == "last_scene_location_mismatch" for item in findings))
        self.assertTrue(any(item["issue"] == "last_scene_cast_mismatch" for item in findings))
        self.assertTrue(any(item["issue"] == "last_scene_visible_result_unverifiable" for item in findings))
        self.assertTrue(any(item["issue"] == "next_episode_bridge_claims_unseen_completion" for item in findings))

    def test_validate_continuity_facts_rejects_vo_for_visible_speaker(self):
        """Verify validate continuity facts rejects vo for visible speaker."""
        script = "\n".join(
            [
                "第一集",
                "1-1    方家卧室    日    内",
                "出场人物：方华",
                "△方华把录取通知收进书包。",
                "方华（VO）：我今天必须离开。",
            ]
        )
        output = {
            "final_script": script,
            "continuity_update": {
                "next_episode_bridge": "方华准备出门",
                "last_scene_state": {
                    "location": "方家卧室",
                    "present_character_names": ["方华"],
                    "visible_result": "方华把录取通知收进书包。",
                },
            },
        }

        findings = validators.continuity_fact_findings(output, episode_num=1)

        self.assertTrue(any(item["issue"] == "visible_character_uses_vo" for item in findings))

    def test_normalize_stage_output_wraps_last_scene_present_character_scalar(self):
        """Verify normalize stage output wraps last scene present character scalar."""
        data = {
            "final_script": "第一集\n1-1    卧室    日    内\n出场人物：方华\n△方华收起通知。",
            "state_update": {},
            "continuity_update": {
                "last_scene_state": {
                    "location": "卧室",
                    "present_character_names": "方华",
                    "visible_result": "方华收起通知。",
                }
            },
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertEqual(
            normalized["continuity_update"]["last_scene_state"]["present_character_names"],
            ["方华"],
        )

    def test_normalize_stage_output_preserves_model_last_scene_state(self):
        """Verify normalize stage output preserves model last scene state."""
        data = {
            "final_script": "\n".join(
                [
                    "第二集",
                    "2-1    方家客厅    日    内",
                    "出场人物：方华、爷爷",
                    "△爷爷把手机塞进口袋。",
                    "",
                    "2-2    小区门口    傍晚    外",
                    "出场人物：方华、林月",
                    "△林月把准考证递给方华。",
                ]
            ),
            "state_update": {},
            "continuity_update": {
                "last_scene_state": {
                    "location": "方家客厅",
                    "present_character_names": ["方华", "爷爷"],
                    "visible_result": "爷爷拿走手机",
                }
            },
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertEqual(
            normalized["continuity_update"]["last_scene_state"],
            {
                "location": "方家客厅",
                "present_character_names": ["方华", "爷爷"],
                "visible_result": "爷爷拿走手机",
            },
        )

    def test_normalize_stage_output_preserves_last_scene_state_when_heading_is_malformed(self):
        """Verify normalize stage output preserves last scene state when heading is malformed."""
        data = {
            "final_script": "\n".join(
                [
                    "第五集",
                    "5-1    林可家客房    日    内",
                    "出场人物：方华、林可",
                    "△方华背起书包。",
                    "",
                    "5-2    考场学校侧门及校正门外    日    内外",
                    "出场人物：方华、林可、爷爷",
                    "△方华从侧门进入学校。",
                    "△考试结束后，方华站在校正门外锁上手机。",
                ]
            ),
            "state_update": {},
            "continuity_update": {
                "last_scene_state": {
                    "location": "林可家客房",
                    "present_character_names": ["方华", "林可"],
                    "visible_result": "方华背起书包。",
                }
            },
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertEqual(
            normalized["continuity_update"]["last_scene_state"],
            {
                "location": "林可家客房",
                "present_character_names": ["方华", "林可"],
                "visible_result": "方华背起书包。",
            },
        )
        errors = validators.collect_final_script_quality_errors(
            normalized["final_script"],
            episode_outline={"episode_num": 5, "required_character_names": ["方华"]},
            canonical_story_lock={"protagonist": "方华", "character_names": ["方华", "林可", "爷爷"]},
            derived_config={"script_length_chars": "20-800", "scenes_per_episode": "1-4"},
        )
        self.assertTrue(any("malformed scene heading" in error and "内外" in error for error in errors))

    def test_normalize_stage_output_preserves_08_completed_beat_ids(self):
        """Verify normalize stage output preserves 08 completed beat ids."""
        data = {
            "schema_version": "08_episode_delta_v2",
            "final_script": "第三集\n3-1    客厅    日    内\n出场人物：方华\n△方华关门。",
            "state_update": {
                "audience_fact_changes": [],
                "character_knowledge_changes": [],
                "private_fact_changes": [],
                "next_episode_bridge": "",
            },
            "continuity_update": {
                "completed_beat_ids": ["E2-B2-a", "E2-B2-b"],
                "foreshadowing_changes": [],
                "open_thread_changes": [],
                "prop_state_changes": [],
                "last_scene_state": {
                    "location": "客厅",
                    "present_character_names": ["方华"],
                    "visible_result": "方华关门。",
                },
                "scene_boundary_check": {
                    "scene_count": 1,
                    "same_setting_split_count": 0,
                    "allowed_same_setting_splits": [],
                    "merge_note": "",
                },
                "narration_device_usage": {
                    "os_count": 0,
                    "flashback_count": 0,
                    "vo_count": 0,
                    "replacement_strategy_used": "",
                },
            },
        }

        normalized = pipeline_runner.normalize_stage_output(
            "08_script_body_generation",
            data,
            normalization_context={
                "episode_execution_sheet": {
                    "episode_num": 3,
                    "consumed_child_beat_ids": ["E2-B2"],
                }
            },
        )

        self.assertEqual(
            normalized["continuity_update"]["completed_beat_ids"],
            ["E2-B2-a", "E2-B2-b"],
        )

    def test_normalize_stage_output_preserves_07_density_ids(self):
        """Verify normalize stage output preserves 07 density ids."""
        data = {
            "episode_outlines": [
                {
                    "episode_num": 3,
                    "consumed_child_beat_ids": ["E2-B2"],
                    "target_script_density": {
                        "must_cover_beats": [
                            {
                                "beat_id": "B1",
                                "action": "方华取得录取材料",
                                "completion_evidence": "材料出现在手中",
                            }
                        ],
                        "scene_char_budgets": [
                            {
                                "scene_no": 1,
                                "target_chars": 700,
                                "must_cover_beat_ids": ["B1"],
                            }
                        ],
                    },
                }
            ]
        }

        normalized = pipeline_runner.normalize_stage_output("07_episode_planning", data)
        density = normalized["episode_outlines"][0]["target_script_density"]

        self.assertEqual(density["must_cover_beats"][0]["beat_id"], "B1")
        self.assertEqual(density["scene_char_budgets"][0]["must_cover_beat_ids"], ["B1"])

    def test_stage_contract_blocks_missing_08_scene_boundary_check_field(self):
        """Verify stage contract blocks missing 08 scene boundary check field."""
        data = {
            "final_script": "第一集\n\n1-1    家中    夜    内\n出场人物：沈念\n△沈念关门。",
            "state_update": {"next": "门外有人"},
            "continuity_update": {
                "audience_known": ["沈念关门"],
                "character_known": {"沈念": ["有人追来"]},
                "writer_private": [],
                "foreshadowing_status": [],
                "next_episode_bridge": "门外有人",
                "conflict_mode_used": "home_pressure",
                "source_anchor_executed": "源锚",
                "boundary_risk": "low",
                "content_sensitivity_risk": "low",
                "opening_continuity_check": "承接上一集门口",
                "completed_beats": ["沈念关门"],
            },
        }

        with self.assertRaisesRegex(
            ValueError,
            r"08_script_body_generation\.continuity_update\.scene_boundary_check missing",
        ):
            validators.validate_stage_contract("08_script_body_generation", data)

    def test_stage_contract_blocks_missing_07_narration_device_plan(self):
        """Verify stage contract blocks missing 07 narration device plan."""
        episode = {
            "episode_num": 1,
            "title": "第1集",
            "block_id": 1,
            "phase": "setup",
            "episode_reason": "建立冲突",
            "main_conflict": "反派施压",
            "counterattack": "主角留证",
            "information_gain": "新证据",
            "state_change": "主角更主动",
            "opening_beat": "村口追问",
            "closing_beat": "证据被看见",
            "next_episode_start_state": "反派追问",
            "consumed_child_beats": ["证据被看见"],
            "event_ids": [1],
            "foreshadowing_ids": [],
            "required_character_names": ["沈念"],
            "appearing_character_names": ["沈念"],
            "ending_hook": "门外脚步声",
            "adapted_plot_point_ids": [1],
            "conflict_mode": "evidence_turn",
            "pattern_family": "evidence_turn",
            "payoff_level": "A",
            "event_role": "推进",
            "event_consumption_status": "ongoing",
            "source_anchor": "源锚",
            "expansion_delta": "扩写见证者",
            "boundary_check": {"risk_level": "low", "protagonist_action": "留证", "why_allowed": "自保", "mitigation": "无"},
            "content_sensitivity_check": {"risk_level": "low", "risk_reason": "无", "mitigation": "无"},
            "unresolved_threads_after_episode": ["证据归属"],
            "is_epilogue": False,
            "scene_plan": [
                {
                    "scene_no": 1,
                    "location": "村口",
                    "time": "日",
                    "space": "外",
                    "appearing_character_names": ["沈念"],
                    "scene_purpose": "counterattack",
                    "must_include_beats": ["沈念留证"],
                    "scene_boundary_reason": "本集自然开场",
                }
            ],
        }

        with self.assertRaisesRegex(
            ValueError,
            r"07_episode_planning\.episode_outlines\[0\]\.narration_device_plan missing",
        ):
            validators.validate_stage_contract(
                "07_episode_planning",
                {"episode_allocation": [], "block_plans": [], "episode_outlines": [episode]},
            )

    def test_stage_contract_blocks_missing_07_visible_space_tokens(self):
        """Verify stage contract blocks missing 07 visible space tokens."""
        data = pipeline_runner.dry_run_payload("07_episode_planning", {"target_episodes": 40})
        scene = data["episode_outlines"][0]["scene_plan"][0]
        scene.pop("visible_space_tokens", None)

        with self.assertRaisesRegex(
            ValueError,
            r"07_episode_planning\.episode_outlines\[0\]\.scene_plan\[0\]\.visible_space_tokens missing",
        ):
            validators.validate_stage_contract("07_episode_planning", data)

    def test_stage_contract_blocks_missing_07_target_script_density(self):
        """Verify stage contract blocks missing 07 target script density."""
        data = pipeline_runner.dry_run_payload("07_episode_planning", {"target_episodes": 40})
        data["episode_outlines"][0].pop("target_script_density", None)

        with self.assertRaisesRegex(
            ValueError,
            r"07_episode_planning\.episode_outlines\[0\]\.target_script_density missing",
        ):
            validators.validate_stage_contract("07_episode_planning", data)

    def test_stage_contract_blocks_missing_scene_char_budgets_and_item_fields(self):
        """Verify stage contract blocks missing scene char budgets and item fields."""
        data = pipeline_runner.dry_run_payload("07_episode_planning", {"target_episodes": 40})
        density = data["episode_outlines"][0]["target_script_density"]
        density.pop("scene_char_budgets", None)

        with self.assertRaisesRegex(
            ValueError,
            r"episode_outlines\[0\]\.target_script_density\.scene_char_budgets missing",
        ):
            validators.validate_stage_contract("07_episode_planning", data)

        density["scene_char_budgets"] = [
            {"scene_no": 1, "must_cover_beat_ids": ["B1"]}
        ]
        with self.assertRaisesRegex(
            ValueError,
            r"scene_char_budgets\[0\]\.target_chars missing",
        ):
            validators.validate_stage_contract("07_episode_planning", data)

    def test_stage_contract_requires_only_canonical_beat_id(self):
        """Verify stage contract requires only canonical beat id."""
        data = pipeline_runner.dry_run_payload("07_episode_planning", {"target_episodes": 40})
        beat = data["episode_outlines"][0]["target_script_density"]["must_cover_beats"][0]
        beat.pop("action", None)
        beat.pop("completion_evidence", None)
        validators.validate_stage_contract("07_episode_planning", data)

        beat.pop("beat_id", None)
        with self.assertRaisesRegex(
            ValueError,
            r"must_cover_beats\[0\]\.beat_id missing",
        ):
            validators.validate_stage_contract("07_episode_planning", data)

    def test_validate_episode_target_script_density_accepts_id_only_beats_and_rejects_bad_budget_sum(self):
        """Handle pipeline behavior."""
        episode = pipeline_runner.dry_run_payload(
            "07_episode_planning",
            {"target_episodes": 40},
        )["episode_outlines"][0]
        for beat in episode["target_script_density"]["must_cover_beats"]:
            beat.pop("action", None)
            beat.pop("completion_evidence", None)
        validators.validate_episode_target_script_density(episode)

        wrong_sum = json.loads(json.dumps(episode, ensure_ascii=False))
        wrong_sum["target_script_density"]["scene_char_budgets"][0]["target_chars"] = 500
        with self.assertRaisesRegex(ValueError, r"scene_char_budgets total.*650-780"):
            validators.validate_episode_target_script_density(wrong_sum)

        overloaded = json.loads(json.dumps(episode, ensure_ascii=False))
        overloaded["target_script_density"]["must_cover_beats"].append(
            {
                "beat_id": "B3",
            }
        )
        overloaded["target_script_density"]["must_cover_beats"].append(
            {
                "beat_id": "B4",
            }
        )
        overloaded["target_script_density"]["scene_char_budgets"][0]["must_cover_beat_ids"].append("B3")
        overloaded["target_script_density"]["scene_char_budgets"][0]["must_cover_beat_ids"].append("B4")
        with self.assertRaisesRegex(ValueError, r"must_cover_beats count must be 1-3"):
            validators.validate_episode_target_script_density(overloaded)

    def test_validate_episode_scene_space_coherence_rejects_disjoint_rooms(self):
        """Verify validate episode scene space coherence rejects disjoint rooms."""
        episode = pipeline_runner.dry_run_payload(
            "07_episode_planning",
            {"target_episodes": 40},
        )["episode_outlines"][0]
        episode["scene_plan"][0]["location"] = "方家卧室及厨房"
        episode["scene_plan"][0]["visible_space_tokens"] = ["卧室", "厨房"]

        with self.assertRaisesRegex(ValueError, r"disjoint visible spaces"):
            validators.validate_episode_scene_space_coherence(episode)

    def test_validate_episode_scene_space_coherence_rejects_transition_space(self):
        """Verify validate episode scene space coherence rejects transition space."""
        episode = pipeline_runner.dry_run_payload(
            "07_episode_planning",
            {"target_episodes": 40},
        )["episode_outlines"][0]
        episode["scene_plan"][0]["space"] = "内转外"

        with self.assertRaisesRegex(ValueError, r"space must be 内/外"):
            validators.validate_episode_scene_space_coherence(episode)

    def test_validate_episode_scene_space_coherence_limits_scene_beats(self):
        """Verify validate episode scene space coherence limits scene beats."""
        episode = pipeline_runner.dry_run_payload(
            "07_episode_planning",
            {"target_episodes": 40},
        )["episode_outlines"][0]
        episode["scene_plan"][0]["must_include_beats"] = ["动作一", "动作二", "动作三"]

        with self.assertRaisesRegex(ValueError, r"must_include_beats count must be 1-2"):
            validators.validate_episode_scene_space_coherence(episode)

    def test_collect_mode_records_density_failure_without_blocking(self):
        """Verify collect mode records density failure without blocking."""
        data = pipeline_runner.dry_run_payload("07_episode_planning", {"target_episodes": 40})
        data["episode_outlines"][0]["target_script_density"]["scene_char_budgets"][0]["target_chars"] = 500
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "density_collect_test")
            pipeline_runner.validate_stage_output(
                "07_episode_planning",
                data,
                target_episodes=40,
                stage_context={
                    "validation_mode": "collect",
                    "expected_block_count": validators.expected_block_count_for_target(40),
                },
                paths=paths,
                artifact_id="07_episode_planning",
            )
            issue_log = json.loads(
                (paths.parsed / "full_run_issue_log.json").read_text(encoding="utf-8")
            )

        self.assertTrue(
            any(
                error.get("check") == "target_script_density"
                for item in issue_log["issues"]
                for error in item.get("errors", [])
            )
        )

    def test_stage_contract_blocks_missing_split_narration_device_id_field(self):
        """Verify stage contract blocks missing split narration device id field."""
        data = pipeline_runner.dry_run_payload("07_episode_planning", {"target_episodes": 40})
        plan = data["episode_outlines"][0]["narration_device_plan"]
        plan.pop("approved_flashback_time_deviation_ids", None)

        with self.assertRaisesRegex(
            ValueError,
            (
                "07_episode_planning\\.episode_outlines\\[0\\]\\.narration_device_plan\\.approved_flashback_ti"
                "me_deviation_ids missing"
            ),
        ):
            validators.validate_stage_contract("07_episode_planning", data)

    def test_stage_contract_blocks_missing_04a_flashback_screening_root_field(self):
        """Verify stage contract blocks missing 04a flashback screening root field."""
        data = {
            "retained_time_deviations": [],
            "rewrite_time_deviations": [],
            "deleted_time_deviations": [],
            "quota_policy": {
                "used_quota": 0,
                "new_a_quota_count": 0,
                "cumulative_a_quota_count": 0,
                "quota_limit": 5,
                "remaining_quota": 5,
            },
        }

        with self.assertRaisesRegex(ValueError, r"04a_flashback_screening\.flashback_overview missing"):
            validators.validate_stage_contract("04a_flashback_screening", data)

    def test_stage_contract_blocks_missing_04a_time_deviation_item_field(self):
        """Verify stage contract blocks missing 04a time deviation item field."""
        data = {
            "flashback_overview": {
                "source_type": "短篇小说",
                "genre_tags": ["职场复仇"],
                "total_time_deviation_count": 1,
                "s_count": 0,
                "a_count": 1,
                "b_count": 0,
                "c_count": 0,
            },
            "retained_time_deviations": [
                {
                    "id": "td_001",
                    "grade": "A",
                    "position": "第1章",
                    "characters": ["陈寻"],
                    "content_summary": "旧合同真相",
                    "q1_structure_necessity": "否",
                    "q2_information_necessity": "是",
                    "decision": "有条件保留",
                    "quota_count": 1,
                }
            ],
            "rewrite_time_deviations": [],
            "deleted_time_deviations": [],
            "quota_policy": {
                "used_quota": 0,
                "new_a_quota_count": 1,
                "cumulative_a_quota_count": 1,
                "quota_limit": 5,
                "remaining_quota": 4,
            },
        }

        with self.assertRaisesRegex(
            ValueError,
            r"04a_flashback_screening\.retained_time_deviations\[0\]\.reason missing",
        ):
            validators.validate_stage_contract("04a_flashback_screening", data)

    def test_stage_contract_blocks_missing_04b_dramatic_target_field(self):
        """Verify stage contract blocks missing 04b dramatic target field."""
        data = pipeline_runner.build_dry_run_dramatic_release_map(5)
        data["episode_dramatic_targets"][2].pop("obstacle")

        with self.assertRaisesRegex(
            ValueError,
            r"04b_dramatic_release_map\.episode_dramatic_targets\[2\]\.obstacle missing",
        ):
            validators.validate_stage_contract("04b_dramatic_release_map", data)

    def test_dramatic_release_structure_requires_exact_target_coverage(self):
        """Verify dramatic release structure requires exact target coverage."""
        data = pipeline_runner.build_dry_run_dramatic_release_map(5)
        data["episode_dramatic_targets"].pop(3)

        with self.assertRaisesRegex(ValueError, r"episode numbers must be exactly 1-5"):
            dramatic_release.validate_release_structure(data, target_episodes=5)

    def test_stage04b_target_specs_split_40_episodes_into_five_episode_chunks(self):
        """Verify stage04b target specs split 40 episodes into five episode chunks."""
        specs = pipeline_runner.build_stage04b_target_specs(40)

        self.assertEqual(
            [(item["start_episode"], item["end_episode"]) for item in specs],
            [
                (1, 5),
                (6, 10),
                (11, 15),
                (16, 20),
                (21, 25),
                (26, 30),
                (31, 35),
                (36, 39),
                (40, 40),
            ],
        )
        self.assertEqual([item["episode_count"] for item in specs[-2:]], [4, 1])
        self.assertTrue(all(item["episode_count"] <= 5 for item in specs))

    def test_stage04b_runtime_prompts_use_registered_chinese_contract_labels(self):
        """Verify stage04b runtime prompts use registered chinese contract labels."""
        foundation_prompt = pipeline_runner.render_stage04b_foundation_prompt(
            {"target_episodes": 40}
        )
        target_prompt = pipeline_runner.render_stage04b_target_prompt(
            {"target_episodes": 40},
            foundation={},
            spec={"start_episode": 1, "end_episode": 10, "episode_count": 10},
            previous_target=None,
        )
        finale_prompt = pipeline_runner.render_stage04b_target_prompt(
            {"target_episodes": 40},
            foundation={},
            spec={"start_episode": 40, "end_episode": 40, "episode_count": 1},
            previous_target=None,
        )

        for label in (
            "容量扩写缺口",
            "开篇释放策略",
            "流程节点压缩策略",
            "桥接单元ID",
            "新增目标",
            "前五集纯流程数",
            "前段必用原著事实ID",
        ):
            self.assertIn(label, foundation_prompt)
        for label in ("释放目标ID", "戏剧阻力", "戏剧选择", "末场可见结果", "对抗方式"):
            self.assertIn(label, target_prompt)
        self.assertNotIn('"capacity_gap"', foundation_prompt)
        self.assertNotIn('"visible_result"', target_prompt)
        self.assertIn("终局余韵", finale_prompt)
        self.assertIn("不得省略钩子", finale_prompt)

    def test_stage04b_fanout_merges_foundation_and_target_chunks(self):
        """Verify stage04b fanout merges foundation and target chunks."""
        payload = pipeline_runner.build_dry_run_dramatic_release_map(40)
        foundation = {
            "release_overview": payload["release_overview"],
            "capacity_bridge_units": payload["capacity_bridge_units"],
            "opening_gate": payload["opening_gate"],
        }
        chunks = [
            {
                "episode_dramatic_targets": payload["episode_dramatic_targets"][
                    spec["start_episode"] - 1 : spec["end_episode"]
                ]
            }
            for spec in pipeline_runner.build_stage04b_target_specs(40)
        ]
        calls: list[dict[str, Any]] = []

        def fake_call_stage(*args, **kwargs):
            """Handle fake call stage."""
            calls.append(kwargs)
            if kwargs["contract_projection_profile"] == "04b_foundation":
                return foundation
            return chunks.pop(0)

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "stage04b_fanout_test")
            stage = pipeline_runner.stage_map()["04b_dramatic_release_map"]
            with mock.patch.object(pipeline_runner, "call_stage", side_effect=fake_call_stage):
                merged = pipeline_runner.run_dramatic_release_stage(
                    paths,
                    stage,
                    {"target_episodes": 40},
                    dry_run=False,
                    llm_script_path=Path("/tmp/fake-llm.sh"),
                    timeout=900,
                )
            trace = json.loads(
                (paths.parsed / "04b_dramatic_release_fanout_trace.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(
            [call["contract_projection_profile"] for call in calls],
            ["04b_foundation"] + ["04b_target_chunk"] * 9,
        )
        self.assertEqual(len(merged["episode_dramatic_targets"]), 40)
        self.assertEqual(merged["episode_dramatic_targets"][-1]["release_id"], "DR_EP040")
        self.assertEqual(len(trace), 9)
        self.assertEqual([item["actual_episode_count"] for item in trace[-2:]], [4, 1])
        self.assertTrue(all(item["actual_episode_count"] <= 5 for item in trace))

    def test_stage04b_contract_retry_only_retries_current_artifact_and_keeps_audit(self):
        """Verify stage04b contract retry only retries current artifact and keeps audit."""
        calls: list[str] = []
        payload = {
            "episode_dramatic_targets": pipeline_runner.build_dry_run_dramatic_release_map(1)[
                "episode_dramatic_targets"
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "stage04b_retry_test")
            stage = pipeline_runner.stage_map()["04b_dramatic_release_map"]

            def fake_call_stage(*args, **kwargs):
                """Handle fake call stage."""
                calls.append(kwargs["prompt_override"])
                if len(calls) == 1:
                    pipeline_runner.write_json(
                        paths.parsed
                        / "contract_reports"
                        / "04b_dramatic_release_map.ep001_001.contract_report.json",
                        {
                            "status": "FAIL",
                            "errors": [
                                "04b_dramatic_release_map.episode_dramatic_targets[0].expansion_engine_id missing"
                            ],
                        },
                    )
                    raise ValueError("expansion_engine_id missing")
                return payload

            with mock.patch.object(pipeline_runner, "call_stage", side_effect=fake_call_stage):
                actual = pipeline_runner.call_stage04b_with_contract_retries(
                    paths,
                    stage,
                    {"target_episodes": 1},
                    dry_run=False,
                    llm_script_path=Path("/tmp/fake-llm.sh"),
                    timeout=30,
                    artifact_id="04b_dramatic_release_map.ep001_001",
                    prompt="生成目标",
                    contract_projection_profile="04b_target_chunk",
                )
            retry_report = (
                paths.parsed
                / "04b_retry_failures"
                / "04b_dramatic_release_map.ep001_001.attempt_01.json"
            )
            retry_report_exists = retry_report.exists()

        self.assertEqual(actual, payload)
        self.assertEqual(len(calls), 2)
        self.assertIn("上次响应结构修复", calls[1])
        self.assertTrue(retry_report_exists)

    def test_stage04b_parser_failure_retries_current_artifact(self):
        """Verify stage04b parser failure retries current artifact."""
        calls: list[str] = []
        payload = {
            "episode_dramatic_targets": pipeline_runner.build_dry_run_dramatic_release_map(1)[
                "episode_dramatic_targets"
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "stage04b_parser_retry_test")
            stage = pipeline_runner.stage_map()["04b_dramatic_release_map"]

            def fake_call_stage(*args, **kwargs):
                """Handle fake call stage."""
                calls.append(kwargs["prompt_override"])
                if len(calls) == 1:
                    pipeline_runner.write_json(
                        paths.parsed
                        / "parser_reports"
                        / "04b_dramatic_release_map.ep001_001.json",
                        {"status": "FAIL", "parse_error": "mismatched closing brace"},
                    )
                    raise json.JSONDecodeError("mismatched closing brace", "{", 1)
                return payload

            with mock.patch.object(pipeline_runner, "call_stage", side_effect=fake_call_stage):
                actual = pipeline_runner.call_stage04b_with_contract_retries(
                    paths,
                    stage,
                    {"target_episodes": 1},
                    dry_run=False,
                    llm_script_path=Path("/tmp/fake-llm.sh"),
                    timeout=30,
                    artifact_id="04b_dramatic_release_map.ep001_001",
                    prompt="生成目标",
                    contract_projection_profile="04b_target_chunk",
                )
            retry_report = json.loads(
                (
                    paths.parsed
                    / "04b_retry_failures"
                    / "04b_dramatic_release_map.ep001_001.attempt_01.json"
                ).read_text(encoding="utf-8")
            )

        self.assertEqual(actual, payload)
        self.assertEqual(len(calls), 2)
        self.assertEqual(retry_report["failure_kind"], "parser")
        self.assertIn("根对象", calls[1])

    def test_stage07_structural_retry_preserves_completed_episode_checkpoint(self):
        """Verify stage07 structural retry preserves completed episode checkpoint."""
        calls: list[str] = []
        payload = {"episode_outlines": []}
        artifact_id = "07_episode_planning.block_04_ep031_031"

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "stage07_retry_test")
            stage = pipeline_runner.stage_map()["07_episode_planning"]

            def fake_call_stage(*args, **kwargs):
                """Handle fake call stage."""
                calls.append(kwargs["prompt_override"])
                if len(calls) == 1:
                    pipeline_runner.write_json(
                        paths.parsed / "parser_reports" / f"{artifact_id}.json",
                        {"status": "FAIL", "parse_error": "mismatched closing brace"},
                    )
                    raise json.JSONDecodeError("mismatched closing brace", "{", 1)
                return payload

            with mock.patch.object(pipeline_runner, "call_stage", side_effect=fake_call_stage):
                actual = pipeline_runner.call_stage_with_structural_retries(
                    paths,
                    stage,
                    {"target_episodes": 40},
                    dry_run=False,
                    llm_script_path=Path("/tmp/fake-llm.sh"),
                    timeout=30,
                    artifact_id=artifact_id,
                    prompt="生成第31集规划",
                    contract_projection_profile="07_episode_chunk",
                    retry_directory="07_retry_failures",
                    max_retries=2,
                )
            retry_report = json.loads(
                (
                    paths.parsed
                    / "07_retry_failures"
                    / f"{artifact_id}.attempt_01.json"
                ).read_text(encoding="utf-8")
            )

        self.assertEqual(actual, payload)
        self.assertEqual(len(calls), 2)
        self.assertEqual(retry_report["stage_id"], "07_episode_planning")
        self.assertEqual(retry_report["failure_kind"], "parser")

    def test_dramatic_release_audit_reports_weak_opening_distribution(self):
        """Verify dramatic release audit reports weak opening distribution."""
        data = pipeline_runner.build_dry_run_dramatic_release_map(5)
        for item in data["episode_dramatic_targets"][:3]:
            item["confrontation_mode"] = "process"
            item["process_only"] = True

        report = dramatic_release.audit_release_map(data, target_episodes=5)

        checks = {item["check"] for item in report["findings"]}
        self.assertIn("opening_live_obstacle_density", checks)
        self.assertIn("opening_process_density", checks)
        self.assertIn("opening_process_streak", checks)

    def test_dramatic_release_audit_requires_zero_opening_process_episodes_and_preserves_fact_object(self):
        """Handle pipeline behavior."""
        data = pipeline_runner.build_dry_run_dramatic_release_map(5)
        data["episode_dramatic_targets"][4]["process_only"] = True
        data["episode_dramatic_targets"][4]["confrontation_mode"] = "process"
        data["episode_dramatic_targets"][4]["source_fact_ids"] = ["SF032"]
        data["episode_dramatic_targets"][4]["desire"] = "方华给母亲写信"
        report = dramatic_release.audit_release_map(
            data,
            target_episodes=5,
            source_fact_ledger=[
                {
                    "fact_id": "SF032",
                    "actor": "方华",
                    "action": "在监狱会面中拒绝释放",
                    "object": "方旭",
                    "result": "方旭彻底绝望",
                }
            ],
            canonical_story_lock={
                "protagonist": "方华",
                "character_names": ["方华", "方旭", "母亲"],
            },
        )

        issues = {item["issue"] for item in report["findings"]}
        self.assertIn("first_five_require_zero_process_only_episodes", issues)
        self.assertIn("source_fact_character_object_not_preserved", issues)

    def test_validate_flashback_screening_blocks_invalid_grade_and_quota(self):
        """Verify validate flashback screening blocks invalid grade and quota."""
        invalid_grade = pipeline_runner.dry_run_payload("04a_flashback_screening", {})
        invalid_grade["retained_time_deviations"][0]["grade"] = "D"

        with self.assertRaisesRegex(ValueError, r"grade must be one of S/A/B/C"):
            validators.validate_flashback_screening_contract(invalid_grade)

        over_quota = pipeline_runner.dry_run_payload("04a_flashback_screening", {})
        over_quota["retained_time_deviations"] = [
            {
                "id": f"td_{index:03d}",
                "grade": "A",
                "position": f"第{index}章",
                "characters": ["陈寻"],
                "content_summary": "关键真相",
                "q1_structure_necessity": "否",
                "q2_information_necessity": "是",
                "decision": "有条件保留",
                "reason": "反转必需",
                "quota_count": 1,
            }
            for index in range(1, 7)
        ]
        over_quota["quota_policy"]["new_a_quota_count"] = 6
        over_quota["quota_policy"]["cumulative_a_quota_count"] = 6
        over_quota["quota_policy"]["remaining_quota"] = -1

        with self.assertRaisesRegex(ValueError, r"A flashback quota.*<= 5"):
            validators.validate_flashback_screening_contract(over_quota)

    def test_validate_flashback_screening_allows_s_grade_without_quota(self):
        """Verify validate flashback screening allows s grade without quota."""
        data = pipeline_runner.dry_run_payload("04a_flashback_screening", {})
        data["retained_time_deviations"] = [
            {
                "id": "td_s_001",
                "grade": "S",
                "position": "第1章",
                "characters": ["陈寻"],
                "content_summary": "多时空结构成立",
                "q1_structure_necessity": "是",
                "q2_information_necessity": "是",
                "decision": "保留",
                "reason": "结构装置本身",
                "quota_count": 0,
            }
        ]
        data["flashback_overview"]["total_time_deviation_count"] = 1
        data["flashback_overview"]["s_count"] = 1
        data["flashback_overview"]["a_count"] = 0
        data["flashback_overview"]["b_count"] = 0
        data["flashback_overview"]["c_count"] = 0
        data["quota_policy"]["new_a_quota_count"] = 0
        data["quota_policy"]["cumulative_a_quota_count"] = 0
        data["quota_policy"]["remaining_quota"] = 5

        validators.validate_flashback_screening_contract(data)

    def test_stage_contract_blocks_missing_08_narration_device_usage(self):
        """Verify stage contract blocks missing 08 narration device usage."""
        data = {
            "final_script": "第一集\n\n1-1    家中    夜    内\n出场人物：沈念\n△沈念关门。",
            "state_update": {"next": "门外有人"},
            "continuity_update": {
                "audience_known": ["沈念关门"],
                "character_known": {"沈念": ["有人追来"]},
                "writer_private": [],
                "foreshadowing_status": [],
                "next_episode_bridge": "门外有人",
                "conflict_mode_used": "home_pressure",
                "source_anchor_executed": "源锚",
                "boundary_risk": "low",
                "content_sensitivity_risk": "low",
                "opening_continuity_check": "承接上一集门口",
                "completed_beats": ["沈念关门"],
                "scene_boundary_check": {
                    "scene_count": 1,
                    "same_setting_split_count": 0,
                    "allowed_same_setting_splits": [],
                    "merge_note": "无硬拆",
                },
            },
        }

        with self.assertRaisesRegex(
            ValueError,
            r"08_script_body_generation\.continuity_update\.narration_device_usage missing",
        ):
            validators.validate_stage_contract("08_script_body_generation", data)

    def test_stage_contract_allows_non_kv_string_lists(self):
        """Verify stage contract allows non kv string lists."""
        self.assertTrue(hasattr(validators, "validate_stage_contract"), "validate_stage_contract missing")
        data = {
            "adaptation_direction": "强化主角反击",
            "target_tone": "强冲突",
            "change_principles": [{"principle": "保留核心梗", "why": "情绪债强", "impact_on_story": "支撑长线"}],
            "must_keep": ["源故事核心伤害"],
            "can_expand": ["外部见证者"],
            "longform_strategy": "分篇章递进",
            "market_tag_priority": [{"tag": "强冲突", "dramatic_action": "落到公开反击"}],
            "originality_boundary": {
                "source_retention_ratio": "60%",
                "original_expansion_ratio": "40%",
                "risk_note": "不改核心梗",
            },
            "source_preservation_contract": {
                "must_preserve": ["核心伤害"],
                "must_preserve_fact_ids": ["SF001"],
                "can_expand": ["证据线"],
                "per_episode_check": "每集检查源锚",
            },
            "protagonist_action_boundary": {
                "allowed": ["留证"],
                "allowed_active_strategies": ["留证", "公开事实"],
                "risk_examples": ["公开反击"],
                "risk_response": "记录风险",
            },
            "event_release_principles": ["终局事件后置"],
            "epilogue_budget": {"max_episodes": 1, "allowed_functions": ["收束"]},
            "retention_rules": ["每篇保留情绪债"],
            "forbidden_changes": ["不得改名"],
        }

        validators.validate_stage_contract("04_adaptation_direction", data)

    def test_contract_report_is_written_on_contract_failure(self):
        """Verify contract report is written on contract failure."""
        self.assertTrue(hasattr(pipeline_runner, "write_contract_report"), "write_contract_report missing")
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "contract_report_test")
            episode = {
                "episode_num": 1,
                "title": "第1集",
                "block_id": 1,
                "phase": "setup",
                "episode_reason": "建立冲突",
                "main_conflict": "反派施压",
                "counterattack": "主角留证",
                "information_gain": "新证据",
                "state_change": "主角更主动",
                "closing_beat": "证据被看见",
                "next_episode_start_state": "反派追问",
                "consumed_child_beats": ["证据被看见"],
                "event_ids": [1],
                "foreshadowing_ids": [],
                "required_character_names": ["沈念"],
                "appearing_character_names": ["沈念"],
                "ending_hook": "门外脚步声",
                "adapted_plot_point_ids": [1],
                "conflict_mode": "evidence_turn",
                "pattern_family": "evidence_turn",
                "payoff_level": "A",
                "event_role": "推进",
                "event_consumption_status": "ongoing",
                "source_anchor": "源锚",
                "expansion_delta": "扩写见证者",
                "boundary_check": {
                        "risk_level": "low",
                        "protagonist_action": "留证",
                        "why_allowed": "自保",
                        "mitigation": "无",
                    },
                "content_sensitivity_check": {"risk_level": "low", "risk_reason": "无", "mitigation": "无"},
                "unresolved_threads_after_episode": ["证据归属"],
                "is_epilogue": False,
                "scene_plan": [
                    {
                        "scene_no": 1,
                        "location": "村口",
                        "time": "日",
                        "space": "外",
                        "appearing_character_names": ["沈念"],
                        "scene_purpose": "counterattack",
                        "must_include_beats": ["沈念留证"],
                        "scene_boundary_reason": "本集自然开场",
                    }
                ],
            }

            with self.assertRaisesRegex(
                ValueError,
                r"07_episode_planning\.episode_outlines\[0\]\.opening_beat missing",
            ):
                pipeline_runner.validate_stage_output(
                    "07_episode_planning",
                    {"episode_allocation": [], "block_plans": [], "episode_outlines": [episode]},
                    target_episodes=1,
                    paths=paths,
                    artifact_id="07_episode_planning",
                )

            report_path = paths.parsed / "contract_reports" / "07_episode_planning.contract_report.json"
            self.assertTrue(report_path.exists())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["stage_id"], "07_episode_planning")
            self.assertIn(
                "07_episode_planning.episode_outlines[0].opening_beat missing",
                report["errors"],
            )
            stored = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["artifact_id"], "07_episode_planning")

    def test_parse_json_payload_accepts_fence_and_trailing_commas(self):
        """Verify parse json payload accepts fence and trailing commas."""
        text = """说明
```json
{"items": [1, 2,],}
```
尾注"""

        self.assertEqual(parsers.parse_json_payload(text), {"items": [1, 2]})

    def test_parse_json_payload_with_report_records_wrapper_and_trailing_comma_repairs(self):
        """Verify parse json payload with report records wrapper and trailing comma repairs."""
        text = """说明
```json
{"items": [1, 2,],}
```
尾注"""

        parsed, report = parsers.parse_json_payload_with_report(text)

        self.assertEqual(parsed, {"items": [1, 2]})
        self.assertEqual(report["status"], "WARN")
        self.assertEqual(
            [item["operation"] for item in report["operations"]],
            ["extract_json_fence_or_wrapper", "remove_trailing_commas"],
        )
        self.assertEqual(report["operation_count"], 2)
        self.assertFalse(report["content_discarded"])
        self.assertRegex(report["before_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(report["after_sha256"], r"^[0-9a-f]{64}$")

    def test_clean_json_to_md_renders_expert_readable_markdown_and_unknown_labels(self):
        """Verify clean json to md renders expert readable markdown and unknown labels."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "readable_test"
            outputs_dir = run_dir / "outputs"
            outputs_dir.mkdir(parents=True)
            long_script = "第一集\n\n1-1    办公室    日    内\n出场人物：陈寻\n△陈寻把合同摊开。" * 20
            payload = {
                "final_script": long_script,
                "known_bool": True,
                "unknown_field": {
                    "child": [1, False, None, {}, []],
                    "nested_text": "完整保留",
                },
                "empty_object": {},
                "empty_list": [],
            }
            (outputs_dir / "08_script_body_generation_ep001.clean.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            report = clean_json_to_md.render_run_clean_json_to_md(run_dir=run_dir)

            md_path = run_dir / "readable_outputs" / "08_script_body_generation_ep001.md"
            self.assertTrue(md_path.exists())
            content = md_path.read_text(encoding="utf-8")
            self.assertIn("最终剧本正文", content)
            self.assertIn(long_script, content)
            self.assertIn("未登记字段 unknown_field", content)
            self.assertIn("未登记字段 child", content)
            self.assertIn("空值", content)
            self.assertIn("空对象", content)
            self.assertIn("空列表", content)
            self.assertNotIn("JSON path", content)
            self.assertNotIn("coverage_status", content)
            coverage = report["field_coverage_by_file"]["08_script_body_generation_ep001.clean.json"]
            self.assertEqual(coverage["coverage_status"], "PASS")
            self.assertEqual(coverage["unrendered_json_paths"], [])
            unknown_fields = {item["field_name"] for item in report["unknown_field_labels"]}
            self.assertIn("unknown_field", unknown_fields)
            self.assertIn("child", unknown_fields)

    def test_clean_json_to_md_renders_07_fanout_as_expert_episode_plan(self):
        """Verify clean json to md renders 07 fanout as expert episode plan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "episode_plan_readable_test"
            outputs_dir = run_dir / "outputs"
            outputs_dir.mkdir(parents=True)
            payload = {
                "block_plan": {
                    "block_id": 1,
                    "phase": "背刺与觉醒",
                    "title": "背刺与觉醒",
                    "goal": "展现陈寻追单身体代价并推进沈星泄密暗线",
                    "key_events": ["陈寻吞胃药", "沈星翻拍客户联系簿"],
                },
                "episode_outlines": [
                    {
                        "episode_num": 2,
                        "title": "暗拍",
                        "episode_reason": "外化陈寻代价，推进沈星泄密暗线",
                        "main_conflict": "沈星趁陈寻离座翻拍客户联系簿",
                        "counterattack": "王辉主动发消息确认见面",
                        "ending_hook": "吴经理圈住王辉名字",
                        "scene_plan": [
                            {
                                "scene_no": 1,
                                "location": "办公室工位区",
                                "time": "日",
                                "space": "内",
                                "appearing_character_names": ["陈寻", "沈星"],
                                "scene_purpose": "制造沈星翻拍机会",
                                "must_include_beats": ["陈寻吞胃药", "沈星翻拍客户联系簿"],
                                "scene_boundary_reason": "地点转换至吴经理办公室",
                                "visible_space_tokens": ["办公室工位区"],
                            }
                        ],
                        "narration_device_plan": {
                            "planned_os_count": 0,
                            "planned_flashback_count": 0,
                            "planned_flashback_quota_count": 0,
                            "planned_vo_count": 0,
                            "reason": "全部用可见动作和道具传递信息",
                            "visual_replacement_strategy": "用胃药瓶、行程表和翻拍动作外化背景信息",
                        },
                    }
                ],
                "state_delta": {
                    "completed_episode_range": {"start": 2, "end": 2},
                    "unresolved_threads": ["吴经理如何截客"],
                },
            }
            (outputs_dir / "07_episode_planning.block_01_ep002_002.clean.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            report = clean_json_to_md.render_run_clean_json_to_md(run_dir=run_dir)

            md_path = run_dir / "readable_outputs" / "07_episode_planning.block_01_ep002_002.md"
            content = md_path.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("# 篇章分批计划"))
            self.assertNotIn("生成时间", content)
            self.assertIn("# 篇章分批计划", content)
            self.assertIn("# 分集大纲", content)
            self.assertIn("- 主要冲突：沈星趁陈寻离座翻拍客户联系簿", content)
            self.assertIn("### 分场计划", content)
            self.assertIn("- 地点：办公室工位区", content)
            self.assertIn("##### 出场人物姓名", content)
            self.assertIn("- 陈寻", content)
            self.assertIn("- 沈星", content)
            self.assertNotIn("## 完整信息", content)
            self.assertNotIn("JSON path", content)
            self.assertNotIn("coverage_status", content)
            self.assertNotIn("artifact_id", content)
            coverage = report["field_coverage_by_file"]["07_episode_planning.block_01_ep002_002.clean.json"]
            self.assertEqual(coverage["coverage_status"], "PASS")

    def test_clean_json_to_md_renders_direct_stage_json_fields(self):
        """Verify clean json to md renders direct stage json fields."""
        stage_samples = {
            "01_novel_summary": (
                {
                    "novel_summary": "公司靠陈寻养活却投票开除他。",
                    "core_hook": "功臣被逐后反杀。",
                    "emotional_debts": ["半年付出被背刺"],
                    "expansion_assets": [{"id": 1, "summary": "客户资源"}],
                    "chapter_summaries": [{"chapter_id": 1, "summary": "被开除"}],
                    "key_events": [{"id": 1, "summary": "投票"}],
                },
                ["- 原著摘要：公司靠陈寻养活却投票开除他。", "# 情绪债", "# 扩写资产", "# 章节梗概", "# 关键事件"],
            ),
            "02_storyline_understanding": (
                {
                    "storyline_candidates": [{"id": 1, "title": "职场反杀", "summary": "被开除后反击"}],
                    "selected_storyline": "职场反杀",
                    "core_conflict": "功臣和公司利益集团冲突",
                    "core_hook_structure": "背刺-证据-反杀",
                    "story_engine": {"hook": "开除", "conflict": "截客"},
                },
                ["# 故事线候选", "- 选定故事线：职场反杀", "- 核心冲突：功臣和公司利益集团冲突", "# 故事发动机"],
            ),
            "03_plot_character_extract": (
                {
                    "source_plot_points": [{"id": 1, "summary": "被投票开除"}],
                    "character_bible": [{"name": "陈寻", "summary": "销售骨干"}],
                    "character_expandability": [{"name": "沈星", "expand_space": "背刺暗线"}],
                    "emotional_debt_chain": ["付出被否定"],
                    "character_action_boundaries": [{"name": "陈寻", "cannot_change": "不能主动违法"}],
                    "source_evidence": [{"id": 1, "quote_or_summary": "公司投票"}],
                },
                ["# 原著情节点", "# 人物小传", "# 人物扩写空间", "# 原著证据"],
            ),
            "04_adaptation_direction": (
                {
                    "adaptation_direction": "职场复仇短剧",
                    "target_tone": "爽感强",
                    "change_principles": [{"principle": "保留背刺", "why": "核心情绪"}],
                    "must_keep": ["投票开除"],
                    "can_expand": ["客户截胡"],
                    "originality_boundary": {"allowed": "补商业线"},
                    "source_preservation_contract": {"must_preserve": "背刺事实"},
                    "protagonist_action_boundary": {"cannot_change": "不能犯罪"},
                    "forbidden_changes": ["不能改成误会"],
                },
                ["- 改编方向：职场复仇短剧", "# 改编原则", "# 原创边界", "# 禁止改动"],
            ),
            "04a_flashback_screening": (
                {
                    "flashback_overview": {"total_time_deviation_count": 1, "a_count": 1},
                    "retained_time_deviations": [{"id": "A1", "grade": "A", "decision": "保留", "reason": "必要"}],
                    "rewrite_time_deviations": [],
                    "deleted_time_deviations": [],
                    "quota_policy": {"quota_limit": 5, "used_quota": 0, "remaining_quota": 4},
                },
                ["# 闪回筛选概览", "# 保留的时间线偏离", "# 配额策略"],
            ),
            "05_plot_character_adaptation": (
                {
                    "macro_arcs": [{"arc_id": 1, "title": "背刺", "episode_range": "1-5", "goal": "建立创伤"}],
                    "event_pool": [{"id": 1, "title": "投票", "target_block": 1}],
                    "conflict_engine": {"core_conflict": "利益集团围剿陈寻"},
                    "expanded_character_network": [{"name": "吴经理", "role": "反派"}],
                    "foreshadowing_pool": [{"id": 1, "title": "考勤陷阱"}],
                    "mapping_trace": [{"source": 1, "event": 1}],
                },
                ["# 宏观弧线", "# 事件池", "# 冲突引擎", "# 伏笔池"],
            ),
            "06_script_outline_design": (
                {
                    "global_outline": "40集职场反杀。",
                    "longform_blocks": [{"block_id": 1, "title": "背刺", "start_episode": 1, "end_episode": 5}],
                    "phase_breakdown": {"phase_1": {"hook_strategy": "开除"}},
                    "episode_budget": [{"phase": "背刺", "episode_count": 5}],
                    "event_release_schedule": [{"block_id": 1, "episode_range": "1-5"}],
                    "block_state_plan": [{"block_id": 1, "entry_state": "在职", "exit_state": "被开除"}],
                    "qa_rules": {"rule": "不提前反杀"},
                },
                ["- 全季大纲：40集职场反杀。", "# 长篇篇章", "# 事件释放计划", "# QA规则"],
            ),
            "08_script_body_generation_ep001": (
                {
                    "final_script": "第1集\n1-1    办公室    日    内\n出场人物：陈寻\n△陈寻摊开合同。",
                    "state_update": {"completed_beats": ["陈寻摊开合同"]},
                    "continuity_update": {"next_episode_bridge": "吴经理进门"},
                },
                ["**最终剧本正文：**", "# 状态更新", "# 连续性更新"],
            ),
        }
        for artifact_id, (payload, expected_headings) in stage_samples.items():
            with self.subTest(artifact_id=artifact_id):
                markdown, coverage, _tracker = clean_json_to_md.render_markdown_for_data(artifact_id, payload)
                self.assertEqual(coverage["coverage_status"], "PASS")
                for expected in expected_headings:
                    self.assertIn(expected, markdown)
                self.assertNotIn("## 完整信息", markdown)
                self.assertNotIn("阅读摘要", markdown)
                self.assertNotIn("JSON path", markdown)
                self.assertNotIn("coverage_status", markdown)

    def test_clean_json_to_md_renders_direct_json_structure_without_summary_then_full_info(self):
        """Verify clean json to md renders direct json structure without summary then full info."""
        payload = {
            "macro_arcs": [{"arc_id": 1, "title": "背刺", "episode_range": "1-5", "goal": "建立创伤"}],
            "event_pool": [{"id": 1, "title": "投票", "target_block": 1}],
            "conflict_engine": {"core_conflict": "利益集团围剿陈寻"},
            "expanded_character_network": [{"name": "吴经理", "role": "反派"}],
            "foreshadowing_pool": [{"id": 1, "title": "考勤陷阱"}],
            "mapping_trace": [{"source": 1, "event": 1}],
        }

        markdown, coverage, _tracker = clean_json_to_md.render_markdown_for_data(
            "05_plot_character_adaptation",
            payload,
        )

        self.assertEqual(coverage["coverage_status"], "PASS")
        self.assertTrue(markdown.startswith("# 宏观弧线"))
        self.assertIn("# 宏观弧线", markdown)
        self.assertIn("# 事件池", markdown)
        self.assertNotIn("# 情节人物扩写", markdown)
        self.assertNotIn("生成时间", markdown)
        self.assertNotIn("## 完整信息", markdown)
        self.assertNotIn("阅读摘要", markdown)
        self.assertNotIn("见“完整信息”", markdown)
        self.assertLess(markdown.index("# 宏观弧线"), markdown.index("# 事件池"))

    def test_clean_json_to_md_reports_broken_clean_json_without_stopping(self):
        """Verify clean json to md reports broken clean json without stopping."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "broken_json_test"
            outputs_dir = run_dir / "outputs"
            outputs_dir.mkdir(parents=True)
            (outputs_dir / "01_novel_summary.clean.json").write_text(
                json.dumps({"novel_summary": "摘要"}, ensure_ascii=False),
                encoding="utf-8",
            )
            (outputs_dir / "02_storyline_understanding.clean.json").write_text("{bad json", encoding="utf-8")

            report = clean_json_to_md.render_run_clean_json_to_md(run_dir=run_dir)

            self.assertIn("01_novel_summary.clean.json", report["rendered_files"])
            self.assertIn("02_storyline_understanding.clean.json", report["failed_files"])
            self.assertTrue((run_dir / "readable_outputs" / "01_novel_summary.md").exists())
            self.assertTrue((run_dir / "readable_outputs" / "parse_report.json").exists())
            self.assertTrue((run_dir / "readable_outputs" / "parse_report.md").exists())

    def test_clean_json_to_md_removes_legacy_readable_json_outputs(self):
        """Verify clean json to md removes legacy readable json outputs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "runs" / "legacy_readable_test"
            outputs_dir = run_dir / "outputs"
            readable_dir = run_dir / "readable_outputs"
            outputs_dir.mkdir(parents=True)
            readable_dir.mkdir(parents=True)
            (outputs_dir / "01_novel_summary.clean.json").write_text(
                json.dumps({"novel_summary": "摘要"}, ensure_ascii=False),
                encoding="utf-8",
            )
            legacy_file = readable_dir / "01_novel_summary.readable.json"
            legacy_index = readable_dir / "index.json"
            legacy_file.write_text(json.dumps({"old": True}, ensure_ascii=False), encoding="utf-8")
            legacy_index.write_text(json.dumps({"parser_module": "parsers.py"}, ensure_ascii=False), encoding="utf-8")

            clean_json_to_md.render_run_clean_json_to_md(run_dir=run_dir)

            self.assertFalse(legacy_file.exists())
            self.assertFalse(legacy_index.exists())
            self.assertTrue((readable_dir / "01_novel_summary.md").exists())
            self.assertTrue((readable_dir / "index.md").exists())
            self.assertTrue((readable_dir / "parse_report.json").exists())

    def test_clean_json_to_md_coverage_fails_when_path_unrendered(self):
        """Verify clean json to md coverage fails when path unrendered."""
        coverage = clean_json_to_md.build_coverage_report(
            all_paths=["root.a", "root.b"],
            rendered_paths=["root.a"],
            failed_paths=[],
        )

        self.assertEqual(coverage["coverage_status"], "FAIL")
        self.assertEqual(coverage["unrendered_json_paths"], ["root.b"])

    def test_parse_json_payload_repairs_fullwidth_structural_punctuation(self):
        """Verify parse json payload repairs fullwidth structural punctuation."""
        text = '{"items":[{"name":"保留，字符串内中文逗号"}，{"name"："第二项"}]}'

        self.assertEqual(
            parsers.parse_json_payload(text),
            {"items": [{"name": "保留，字符串内中文逗号"}, {"name": "第二项"}]},
        )

    def test_parse_json_payload_repairs_unescaped_quotes_inside_string(self):
        """Verify parse json payload repairs unescaped quotes inside string."""
        text = '{"summary": "方华用"听不懂人话"这个武器反击", "items": ["爷爷的"服从性测试""]}'

        self.assertEqual(
            parsers.parse_json_payload(text),
            {"summary": '方华用"听不懂人话"这个武器反击', "items": ['爷爷的"服从性测试"']},
        )

    def test_parse_json_payload_with_report_records_unescaped_quote_repair(self):
        """Verify parse json payload with report records unescaped quote repair."""
        text = '{"summary": "方华用"听不懂人话"这个武器反击"}'

        parsed, report = parsers.parse_json_payload_with_report(text)

        self.assertEqual(parsed, {"summary": '方华用"听不懂人话"这个武器反击'})
        self.assertIn("escape_unescaped_string_quotes", [item["operation"] for item in report["operations"]])
        self.assertFalse(report["content_discarded"])

    def test_parse_json_payload_repairs_literal_newlines_inside_string(self):
        """Verify parse json payload repairs literal newlines inside string."""
        text = '{"final_script": "# 第1集\n\n第1场 家中 夜\n方华反击。", "state_update": {"next": "进考场"}}'

        self.assertEqual(
            parsers.parse_json_payload(text),
            {"final_script": "# 第1集\n\n第1场 家中 夜\n方华反击。", "state_update": {"next": "进考场"}},
        )

    def test_parse_json_payload_repairs_extra_object_close_before_next_field(self):
        """Verify parse json payload repairs extra object close before next field."""
        text = (
            "{\"final_script\": \"# 第1集\n"
            "正文\"\n"
            "  },\n"
            "  \"state_update\": {\"next\": \"进考场\"}, \"continuity_update\": {\"audience_known\": []}}"
        )

        self.assertEqual(
            parsers.parse_json_payload(text),
            {
                "final_script": "# 第1集\n正文",
                "state_update": {"next": "进考场"},
                "continuity_update": {"audience_known": []},
            },
        )

    def test_parse_json_payload_repairs_extra_object_close_before_next_chinese_field(self):
        """Verify parse json payload repairs extra object close before next chinese field."""
        text = '{"最终剧本正文": "第一集\n正文"\n  },\n  "状态更新": {"下一步": "进考场"}, "连续性更新": {"观众已知信息": []}}'

        self.assertEqual(
            parsers.parse_json_payload(text),
            {
                "最终剧本正文": "第一集\n正文",
                "状态更新": {"下一步": "进考场"},
                "连续性更新": {"观众已知信息": []},
            },
        )

    def test_parse_json_payload_repairs_extra_object_close_before_array_field(self):
        """Verify parse json payload repairs extra object close before array field."""
        text = (
            '{"episode_outlines":[{"episode_num":10,'
            '"narration_device_plan":{"approved_time_deviation_ids":[]}}}],'
            '"state_delta":{"next":"进入第二块"}}'
        )

        self.assertEqual(
            parsers.parse_json_payload(text),
            {
                "episode_outlines": [
                    {
                        "episode_num": 10,
                        "narration_device_plan": {"approved_time_deviation_ids": []},
                    }
                ],
                "state_delta": {"next": "进入第二块"},
            },
        )

    def test_parse_json_payload_repairs_extra_object_close_after_nested_field(self):
        """Verify parse json payload repairs extra object close after nested field."""
        text = (
            '{"事件列表":[{"事件ID":8,"戏剧状态变化":{"变化维度":"关系",'
            '"变化前":"被绑架","变化后":"主动拒绝"}}, "子情节点":'
            '[{"子情节点ID":"E8-B1","动作":"关门","完成证据":"门已关闭"}]},'
            '{"事件ID":9,"戏剧状态变化":{"变化维度":"权力",'
            '"变化前":"被控制","变化后":"取得证据"}}, "子情节点":'
            '[{"子情节点ID":"E9-B1","动作":"存证","完成证据":"文件已保存"}]}]}'
        )

        parsed, report = parsers.parse_json_payload_with_report(text)

        self.assertEqual(parsed["事件列表"][0]["事件ID"], 8)
        self.assertEqual(parsed["事件列表"][0]["子情节点"][0]["子情节点ID"], "E8-B1")
        self.assertEqual(parsed["事件列表"][1]["子情节点"][0]["子情节点ID"], "E9-B1")
        self.assertIn(
            "remove_extra_event_close_before_child_beats",
            [item["operation"] for item in report["operations"]],
        )

    def test_validate_stage_output_reports_07_flashback_alignment_in_report_only_mode(self):
        """Verify validate stage output reports 07 flashback alignment in report only mode."""
        episode = {
            "episode_num": 1,
            "dramatic_target_id": "DR_EP001",
            "title": "证据入场",
            "block_id": 1,
            "phase": "反击启动",
            "episode_reason": "用当下证据替代回忆",
            "main_conflict": "陈寻需要说明过往投入",
            "counterattack": "陈寻摆出收据",
            "information_gain": "收据总额被看见",
            "state_change": "陈寻掌握主动",
            "opening_beat": "陈寻打开抽屉",
            "closing_beat": "收据被拍照存档",
            "next_episode_start_state": "进入签约准备",
            "consumed_child_beats": ["陈寻摆收据"],
            "consumed_child_beat_ids": ["E1-B1"],
            "event_ids": [1],
            "foreshadowing_ids": [],
            "required_character_names": ["陈寻"],
            "appearing_character_names": ["陈寻"],
            "ending_hook": "手机亮起",
            "adapted_plot_point_ids": [1],
            "source_fact_ids": ["SF001"],
            "story_time": {"day_index": 1, "time_label": "第一天", "elapsed_from_previous": "故事起点"},
            "fact_transitions": [],
            "conflict_mode": "evidence_turn",
            "pattern_family": "evidence_turn",
            "payoff_level": "A",
            "event_role": "推进",
            "event_consumption_status": "completed",
            "source_anchor": "出差垫款",
            "expansion_delta": "用收据可视化",
            "boundary_check": {"risk_level": "low", "protagonist_action": "存档", "why_allowed": "自保", "mitigation": "无"},
            "content_sensitivity_check": {"risk_level": "low", "risk_reason": "无", "mitigation": "无"},
            "unresolved_threads_after_episode": [],
            "is_epilogue": False,
            "scene_plan": [
                {
                    "scene_no": 1,
                    "location": "出租屋",
                    "time": "日",
                    "space": "内",
                    "appearing_character_names": ["陈寻"],
                    "scene_purpose": "evidence_turn",
                    "must_include_beats": ["陈寻摆收据"],
                    "scene_boundary_reason": "本集唯一自然场",
                    "visible_space_tokens": ["出租屋"],
                }
            ],
            "narration_device_plan": {
                "planned_os_count": 1,
                "planned_flashback_count": 0,
                "planned_flashback_quota_count": 0,
                "planned_vo_count": 0,
                "reason": "A 级内容转为 OS，不使用闪回",
                "visual_replacement_strategy": "用收据当下可见动作替代回忆画面",
                "approved_flashback_time_deviation_ids": ["td_a_001"],
                "approved_os_time_deviation_ids": [],
                "visualized_time_deviation_ids": [],
                "deleted_or_rewritten_time_deviation_ids": [],
            },
            "target_script_density": {
                "target_range_chars": "650-780",
                "minimum_effective_chars": 650,
                "maximum_chars": 780,
                "must_cover_beats": [
                    {
                        "beat_id": "E1-B1",
                        "action": "陈寻摆收据",
                        "completion_evidence": "收据被拍照存档",
                    }
                ],
                "optional_compression_beats": [],
                "expansion_strategy": "补对手追问和可见证据",
                "scene_char_budgets": [
                    {
                        "scene_no": 1,
                        "target_chars": 700,
                        "must_cover_beat_ids": ["E1-B1"],
                    }
                ],
            },
        }
        data = {
            "episode_allocation": [{"block_id": 1, "start_episode": 1, "end_episode": 1, "episode_count": 1}],
            "block_plans": [
                {
                    "block_id": 1,
                    "phase": "反击启动",
                    "title": "证据入场",
                    "start_episode": 1,
                    "end_episode": 1,
                    "episode_count": 1,
                    "goal": "完成证据入场",
                    "antagonist": "刘波",
                    "hook": "收据亮出",
                    "foreshadowing_plan": [],
                }
            ],
            "episode_outlines": [episode],
        }
        flashback_screening = {
            "retained_time_deviations": [
                {
                    "id": "td_a_001",
                    "grade": "A",
                    "decision": "压缩为当下心理流",
                    "quota_count": 1,
                }
            ],
            "rewrite_time_deviations": [],
            "deleted_time_deviations": [],
        }

        with self.assertRaisesRegex(
            ValueError,
            r"approved_flashback_time_deviation_ids require planned_flashback_count",
        ):
            pipeline_runner.validate_stage_output(
                "07_episode_planning",
                data,
                target_episodes=1,
                stage_context={
                    "expected_block_count": 1,
                    "flashback_screening": flashback_screening,
                    "validation_mode": "strict",
                },
            )

        pipeline_runner.validate_stage_output(
            "07_episode_planning",
            data,
            target_episodes=1,
            stage_context={
                "expected_block_count": 1,
                "flashback_screening": flashback_screening,
                "validation_mode": "collect",
            },
        )

    def test_parse_json_payload_closes_chapter_summaries_before_key_events(self):
        """Verify parse json payload closes chapter summaries before key events."""
        text = """{
  "chapter_summaries": [
    {
      "chapter_id": 1,
      "summary": "开场"
    },
  "key_events": [
    {"id": "E01"}
  ]
  ]
}"""

        parsed = parsers.parse_json_payload(text)

        self.assertEqual(parsed["chapter_summaries"][0]["chapter_id"], 1)
        self.assertEqual(parsed["key_events"][0]["id"], "E01")

    def test_parse_json_payload_closes_chinese_chapter_summaries_before_key_events(self):
        """Verify parse json payload closes chinese chapter summaries before key events."""
        text = """{
  "章节梗概": [
    {
      "章节ID": 1,
      "摘要": "开场"
    },
  "关键事件": [
    {"ID": "E01"}
  ]
  ]
}"""

        parsed = parsers.parse_json_payload(text)

        self.assertEqual(parsed["章节梗概"][0]["章节ID"], 1)
        self.assertEqual(parsed["关键事件"][0]["ID"], "E01")

    def test_clean_final_script_removes_model_residue(self):
        """Verify clean final script removes model residue."""
        text = """模型理解：这里是分析
以下是剧本正文：
# 第1集

第1场 家中 夜
方华：我不会再忍。
"""

        cleaned = parsers.clean_final_script(text)

        self.assertTrue(cleaned.startswith("# 第1集"))
        self.assertNotIn("模型理解", cleaned)
        self.assertNotIn("以下是剧本正文", cleaned)

    def test_clean_final_script_normalizes_scene_heading_time_aliases(self):
        """Verify clean final script normalizes scene heading time aliases."""
        text = "\n".join(
            [
                "第四集",
                "",
                "4-1    陈寻出租屋门口    清晨    内",
                "出场人物：陈寻、沈星",
                "△门铃响。",
                "",
                "4 - 2  旧厂会议室  深夜  外",
                "出场人物：刘波",
                "△会议室灯亮着。",
            ]
        )

        cleaned = parsers.clean_final_script(text)

        self.assertIn("4-1    陈寻出租屋门口    日    内", cleaned)
        self.assertIn("4-2    旧厂会议室    夜    外", cleaned)
        self.assertNotIn("清晨", cleaned)
        self.assertNotIn("深夜", cleaned)

    def test_parse_json_payload_repairs_truncated_mapping_trace_tail(self):
        """Verify parse json payload repairs truncated mapping trace tail."""
        text = """{
  "macro_arcs": [{"arc_id": 1}],
  "event_pool": [{"id": 1}],
  "conflict_engine": {"pressure_templates": []},
  "expanded_character_network": [],
  "foreshadowing_pool": [],
  "mapping_trace": [
    {
      "asset_id": "macro_arc_1",
      "source_plot_point_ids": [1],
      "change_type": "expanded",
      "reason": "扩写"
    },
    {
      "asset_id": "event_1",
      "source_plot_point_ids": [1],
      "change

---
model: claude-sonnet-4-6 | stop: end_turn
"""

        parsed = parsers.parse_json_payload(text)

        self.assertEqual(parsed["macro_arcs"], [{"arc_id": 1}])
        self.assertEqual(parsed["event_pool"], [{"id": 1}])
        self.assertEqual(parsed["mapping_trace"], [])

    def test_parse_json_payload_with_report_marks_truncated_mapping_trace_as_discarded(self):
        """Verify parse json payload with report marks truncated mapping trace as discarded."""
        text = """{
  "macro_arcs": [{"arc_id": 1}],
  "mapping_trace": [
    {"asset_id": "macro_arc_1"},
    {"asset_id": "event_1", "change

---
model: claude | stop: max_tokens
"""

        parsed, report = parsers.parse_json_payload_with_report(text)

        self.assertEqual(parsed["mapping_trace"], [])
        self.assertTrue(report["content_discarded"])
        self.assertIn("drop_truncated_mapping_trace_tail", [item["operation"] for item in report["operations"]])

    def test_parse_json_payload_repairs_truncated_chinese_mapping_trace_tail(self):
        """Verify parse json payload repairs truncated chinese mapping trace tail."""
        text = """{
  "宏观弧线": [{"弧线ID": 1}],
  "事件池": [{"ID": 1}],
  "映射链路": [
    {
      "资产ID": "macro_arc_1",
      "原著情节点ID": [1],
      "改编类型": "新增扩写"
    },
    {
      "资产ID": "event_1",
      "原著情节点ID": [1],
      "改编

---
model: claude | stop: max_tokens
"""

        parsed = parsers.parse_json_payload(text)

        self.assertEqual(parsed["宏观弧线"], [{"弧线ID": 1}])
        self.assertEqual(parsed["事件池"], [{"ID": 1}])
        self.assertEqual(parsed["映射链路"], [])

    def test_parse_json_payload_keeps_valid_nested_object_when_later_chinese_tail_is_truncated(self):
        """Verify parse json payload keeps valid nested object when later chinese tail is truncated."""
        text = """{
  "状态更新": {
    "目标": "保全证据",
    "地点": "法务部"
  },
  "映射链路": [
    {
      "资产ID": "event_1",
      "改编类型": "新增扩写"
    },
    {
      "资产ID": "event_2",
      "改编

---
model: claude | stop: max_tokens
"""

        parsed = parsers.parse_json_payload(text)

        self.assertEqual(parsed["状态更新"], {"目标": "保全证据", "地点": "法务部"})
        self.assertEqual(parsed["映射链路"], [])

    def test_normalize_stage_output_cleans_cached_08_scene_heading_times(self):
        """Verify normalize stage output cleans cached 08 scene heading times."""
        data = {
            "final_script": "第四集\n\n4-1    陈寻出租屋门口    清晨    内\n出场人物：陈寻、沈星\n△门铃响。",
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("4-1    陈寻出租屋门口    日    内", normalized["final_script"])

    def test_normalize_stage_output_preserves_07_scene_plan_time_aliases_for_validation(self):
        """Verify normalize stage output preserves 07 scene plan time aliases for validation."""
        data = {
            "episode_allocation": [{"block_id": 1, "start_episode": 1, "end_episode": 1, "episode_count": 1}],
            "block_plans": [{"block_id": 1, "start_episode": 1, "end_episode": 1, "episode_count": 1}],
            "episode_outlines": [
                {
                    "episode_num": 1,
                    "scene_plan": [
                        {"scene_no": 1, "time": "清晨"},
                        {"scene_no": 2, "time": "深夜"},
                    ],
                }
            ],
        }

        normalized = pipeline_runner.normalize_stage_output("07_episode_planning", data)

        times = [item["time"] for item in normalized["episode_outlines"][0]["scene_plan"]]
        self.assertEqual(times, ["清晨", "深夜"])

    def test_normalize_stage_output_does_not_invent_07_scene_plan_roles(self):
        """Verify normalize stage output does not invent 07 scene plan roles."""
        data = {
            "episode_allocation": [{"block_id": 1, "start_episode": 1, "end_episode": 1, "episode_count": 1}],
            "block_plans": [{"block_id": 1, "start_episode": 1, "end_episode": 1, "episode_count": 1}],
            "episode_outlines": [
                {
                    "episode_num": 1,
                    "required_character_names": ["陈寻"],
                    "appearing_character_names": ["陈寻"],
                    "scene_plan": [
                        {
                            "scene_no": 1,
                            "location": "旧厂公司前台区",
                            "time": "日",
                            "space": "内",
                            "appearing_character_names": ["陈寻"],
                            "scene_purpose": "pressure",
                            "must_include_beats": ["陈寻进门，前台抬头看他，吴经理走近"],
                            "scene_boundary_reason": "首场压力",
                        }
                    ],
                }
            ],
        }

        normalized = pipeline_runner.normalize_stage_output("07_episode_planning", data)

        episode = normalized["episode_outlines"][0]
        scene = episode["scene_plan"][0]
        self.assertNotIn("前台", scene["appearing_character_names"])
        self.assertNotIn("前台", episode["appearing_character_names"])
        self.assertNotIn("scene_plan_repair_trace", episode)

    def test_normalize_stage_output_preserves_07_episode_level_roles(self):
        """Verify normalize stage output preserves 07 episode level roles."""
        data = {
            "episode_allocation": [{"block_id": 1, "start_episode": 1, "end_episode": 1, "episode_count": 1}],
            "block_plans": [{"block_id": 1, "start_episode": 1, "end_episode": 1, "episode_count": 1}],
            "episode_outlines": [
                {
                    "episode_num": 1,
                    "required_character_names": ["陈寻"],
                    "appearing_character_names": ["陈寻", "前台"],
                    "scene_plan": [
                        {
                            "scene_no": 1,
                            "location": "旧厂公司前台区",
                            "time": "日",
                            "space": "内",
                            "appearing_character_names": ["陈寻", "前台"],
                            "scene_purpose": "pressure",
                            "must_include_beats": ["陈寻进门，前台抬头看他"],
                            "scene_boundary_reason": "首场压力",
                        }
                    ],
                }
            ],
        }

        normalized = pipeline_runner.normalize_stage_output("07_episode_planning", data)

        episode = normalized["episode_outlines"][0]
        self.assertEqual(episode["appearing_character_names"], ["陈寻", "前台"])
        self.assertEqual(episode["scene_plan"][0]["appearing_character_names"], ["陈寻", "前台"])
        self.assertNotIn("scene_plan_repair_trace", episode)

    def test_normalize_stage_output_preserves_07_scene_plan_location_for_validation(self):
        """Verify normalize stage output preserves 07 scene plan location for validation."""
        data = {
            "episode_allocation": [{"block_id": 1, "start_episode": 1, "end_episode": 1, "episode_count": 1}],
            "block_plans": [{"block_id": 1, "start_episode": 1, "end_episode": 1, "episode_count": 1}],
            "episode_outlines": [
                {
                    "episode_num": 1,
                    "required_character_names": ["陈寻"],
                    "appearing_character_names": ["陈寻"],
                    "scene_plan": [
                        {
                            "scene_no": 3,
                            "location": "公司出口走廊",
                            "time": "日",
                            "space": "内",
                            "appearing_character_names": ["陈寻"],
                            "scene_purpose": "离场收束",
                            "must_include_beats": ["陈寻拖着行李箱走过工位区，四周无人抬头"],
                            "scene_boundary_reason": "陈寻独自离场",
                        }
                    ],
                }
            ],
        }

        normalized = pipeline_runner.normalize_stage_output("07_episode_planning", data)

        episode = normalized["episode_outlines"][0]
        self.assertEqual(episode["scene_plan"][0]["location"], "公司出口走廊")
        self.assertNotIn("scene_plan_repair_trace", episode)

    def test_normalize_stage_output_removes_06_episode_budget_summary_rows(self):
        """Verify normalize stage output removes 06 episode budget summary rows."""
        data = {
            "global_outline": "全剧40集",
            "longform_blocks": [],
            "phase_breakdown": {},
            "episode_budget": [
                {"phase": "第一篇章", "start_episode": 1, "end_episode": 10, "episode_count": 10},
                {"phase": "第二篇章", "start_episode": 11, "end_episode": 20, "episode_count": 10},
                {"phase": "第三篇章", "start_episode": 21, "end_episode": 30, "episode_count": 10},
                {"phase": "第四篇章", "start_episode": 31, "end_episode": 40, "episode_count": 10},
                {"phase": "合计", "start_episode": 1, "end_episode": 40, "episode_count": 40},
            ],
            "event_release_schedule": [],
            "block_event_plan": [],
            "climax_guardrails": {},
            "block_state_plan": [],
            "qa_rules": [],
        }

        normalized = pipeline_runner.normalize_stage_output("06_script_outline_design", data)

        self.assertEqual(len(normalized["episode_budget"]), 4)
        self.assertEqual(sum(item["episode_count"] for item in normalized["episode_budget"]), 40)

    def test_normalize_stage_output_fills_04a_missing_reason_from_decision_fields(self):
        """Verify normalize stage output fills 04a missing reason from decision fields."""
        data = pipeline_runner.dry_run_payload("04a_flashback_screening", {})
        del data["retained_time_deviations"][0]["reason"]

        normalized = pipeline_runner.normalize_stage_output("04a_flashback_screening", data)

        item = normalized["retained_time_deviations"][0]
        self.assertIn("Q1:", item["reason"])
        self.assertIn("Q2:", item["reason"])
        self.assertIn("decision:", item["reason"])
        validators.validate_stage_contract("04a_flashback_screening", normalized)

    def test_normalize_stage_output_fills_04a_deterministic_quota_count(self):
        """Verify normalize stage output fills 04a deterministic quota count."""
        data = pipeline_runner.dry_run_payload("04a_flashback_screening", {})
        data["deleted_time_deviations"] = [
            {
                "id": "td_c_001",
                "grade": "C",
                "position": "第三章",
                "characters": ["方华"],
                "content_summary": "零碎回忆",
                "q1_structure_necessity": "不成立",
                "q2_information_necessity": "不成立",
                "decision": "删除",
                "reason": "不影响当前时间线",
            }
        ]
        data["flashback_overview"]["total_time_deviation_count"] = 2
        data["flashback_overview"]["c_count"] = 1

        normalized = pipeline_runner.normalize_stage_output("04a_flashback_screening", data)

        self.assertEqual(normalized["deleted_time_deviations"][0]["quota_count"], 0)
        validators.validate_stage_contract("04a_flashback_screening", normalized)

    def test_normalize_stage_output_does_not_overwrite_wrong_04a_quota_count(self):
        """Verify normalize stage output does not overwrite wrong 04a quota count."""
        data = pipeline_runner.dry_run_payload("04a_flashback_screening", {})
        data["retained_time_deviations"][0]["quota_count"] = 7

        normalized = pipeline_runner.normalize_stage_output("04a_flashback_screening", data)

        self.assertEqual(normalized["retained_time_deviations"][0]["quota_count"], 7)
        with self.assertRaisesRegex(ValueError, r"quota_count must be 1"):
            validators.validate_flashback_screening_contract(normalized)

    def test_event_pool_gap_repair_uses_stage05_macro_arc_ranges(self):
        """Verify event pool gap repair uses stage05 macro arc ranges."""
        event_pool = [
            {
                "id": 10,
                "title": "外部阻击",
                "function": "压力升级",
                "source_plot_point_ids": [1],
                "expansion_type": "source_expansion",
                "target_block": 3,
                "episode_window": {"start": 27, "end": 30},
                "not_before_episode": 27,
                "not_after_episode": 32,
                "expected_episode_span": 4,
                "importance_level": "A",
                "conflict_mode": "合同争议",
                "pattern_family": "商业阻击",
                "source_anchor": "旧公司阻击新公司",
                "delta_from_source": "扩写为合同争议",
                "legal_moral_risk": "low",
                "content_sensitivity_risk": "low",
                "child_beats": ["对方施压", "主角留证"],
            },
            {
                "id": 11,
                "title": "规模跃升",
                "function": "成长节点",
                "source_plot_point_ids": [1],
                "expansion_type": "source_expansion",
                "target_block": 3,
                "episode_window": {"start": 32, "end": 35},
                "not_before_episode": 32,
                "not_after_episode": 35,
                "expected_episode_span": 4,
                "importance_level": "A",
                "conflict_mode": "成果展示",
                "pattern_family": "成长对比",
                "source_anchor": "公司扩至百人",
                "delta_from_source": "量化成长",
                "legal_moral_risk": "low",
                "content_sensitivity_risk": "low",
                "child_beats": ["百人大会", "自有厂签约"],
            },
        ]
        stage05 = {
            "macro_arcs": [
                {"arc_id": 1, "episode_range": {"start": 1, "end": 10}},
                {"arc_id": 2, "episode_range": {"start": 11, "end": 20}},
                {"arc_id": 3, "episode_range": {"start": 21, "end": 35}},
                {"arc_id": 4, "episode_range": {"start": 36, "end": 40}},
            ],
            "event_pool": event_pool,
        }

        blocks = pipeline_runner.event_repair_blocks_from_stage05(stage05, target_episodes=40)
        repaired = pipeline_runner.repair_event_pool_window_gaps(event_pool, blocks)

        event_11 = next(item for item in repaired if item["id"] == 11)
        self.assertEqual(event_11["episode_window"], {"start": 32, "end": 35})
        validators.validate_event_pool_contract(repaired, derived_config={"event_pool_size": "2-2"})

    def test_normalize_stage_output_preserves_cached_07_phone_vo_budget(self):
        """Verify normalize stage output preserves cached 07 phone vo budget."""
        data = {
            "episode_allocation": [{"block_id": 1, "start_episode": 3, "end_episode": 3, "episode_count": 1}],
            "block_plans": [{"block_id": 1, "start_episode": 3, "end_episode": 3, "episode_count": 1}],
            "episode_outlines": [
                {
                    "episode_num": 3,
                    "scene_plan": [{"scene_no": 3, "scene_purpose": "于涛主动来电"}],
                    "narration_device_plan": {
                        "planned_os_count": 0,
                        "planned_flashback_count": 0,
                        "planned_vo_count": 0,
                        "reason": "用电话推进",
                        "visual_replacement_strategy": "用手机屏幕和对话替代说明",
                    },
                }
            ],
        }

        normalized = pipeline_runner.normalize_stage_output("07_episode_planning", data)

        plan = normalized["episode_outlines"][0]["narration_device_plan"]
        self.assertEqual(plan["planned_vo_count"], 0)

    def test_normalize_stage_output_preserves_08_narration_device_usage_counts(self):
        """Verify normalize stage output preserves 08 narration device usage counts."""
        data = {
            "final_script": "第三集\n\n3-1    咖啡店    夜    内\n出场人物：陈寻\n△陈寻放下手机。",
            "state_update": {},
            "continuity_update": {
                "narration_device_usage": {
                    "os_count": 0,
                    "flashback_count": 0,
                    "vo_count": 1,
                    "replacement_strategy_used": "自报有VO",
                }
            },
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        usage = normalized["continuity_update"]["narration_device_usage"]
        self.assertEqual(usage["vo_count"], 1)

    def test_normalize_stage_output_preserves_08_empty_dialogue_for_validation(self):
        """Verify normalize stage output preserves 08 empty dialogue for validation."""
        data = {
            "final_script": "第二集\n\n2-1    办公室    日    内\n出场人物：陈寻\n陈寻（挂断电话，将手机屏幕扣在桌上）：",
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("陈寻（挂断电话，将手机屏幕扣在桌上）：", normalized["final_script"])

    def test_normalize_stage_output_preserves_08_field_subtitle_for_validation(self):
        """Verify normalize stage output preserves 08 field subtitle for validation."""
        data = {
            "final_script": "第一集\n\n1-1    公司前台区    日    内\n出场人物：陈寻\n【字幕：发起人：刘波】",
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("【字幕：发起人：刘波】", normalized["final_script"])

    def test_normalize_stage_output_does_not_backfill_08_scene_cast_from_vo_speaker(self):
        """Verify normalize stage output does not backfill 08 scene cast from vo speaker."""
        data = {
            "final_script": "\n".join(
                [
                    "第五集",
                    "",
                    "5-1    咖啡馆门口街道    日    外",
                    "出场人物：陈寻、刘波",
                    "△陈寻拿出手机，贴近耳朵。",
                    "王辉（VO）：喂？",
                    "陈寻（继续向前走）：王总，我是陈寻。",
                ]
            ),
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertNotIn("出场人物：陈寻、刘波、王辉", normalized["final_script"])
        with self.assertRaisesRegex(ValueError, "missing cast member"):
            validators.validate_final_script_quality(
                normalized["final_script"],
                episode_outline={"episode_num": 5, "required_character_names": ["陈寻", "王辉"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "刘波", "王辉"]},
                derived_config={"script_length_chars": "20-800", "scenes_per_episode": "1-3"},
            )

    def test_normalize_stage_output_does_not_backfill_08_scene_cast_from_visible_action_actor(self):
        """Verify normalize stage output does not backfill 08 scene cast from visible action actor."""
        data = {
            "final_script": "\n".join(
                [
                    "第五集",
                    "",
                    "5-1    咖啡馆内    日    内",
                    "出场人物：陈寻、刘波",
                    "△赵敏视线跟随陈寻背影到门口，将杯子放回桌面，没有起身。",
                    "陈寻（看向刘波）：你解释。",
                ]
            ),
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output(
            "08_script_body_generation",
            data,
            normalization_context={
                "episode_outline": {"appearing_character_names": ["陈寻", "刘波", "赵敏"]},
                "canonical_story_lock": {"character_names": ["陈寻", "刘波", "赵敏"]},
            },
        )

        self.assertNotIn("出场人物：陈寻、刘波、赵敏", normalized["final_script"])
        with self.assertRaisesRegex(ValueError, "missing cast member"):
            validators.validate_final_script_quality(
                normalized["final_script"],
                episode_outline=(
                    {
                        "episode_num": 5,
                        "required_character_names": ["陈寻"],
                        "appearing_character_names": ["陈寻", "刘波", "赵敏"],
                    }
                ),
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "刘波", "赵敏"]},
                derived_config={"script_length_chars": "20-1000", "scenes_per_episode": "1-3"},
            )

    def test_normalize_stage_output_preserves_scene_heading_episode_for_validation(self):
        """Verify normalize stage output preserves scene heading episode for validation."""
        data = {
            "final_script": "第二集\n\n1-1    出租屋    夜    内\n出场人物：陈寻\n△陈寻放下纸箱。",
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("1-1    出租屋    夜    内", normalized["final_script"])

    def test_normalize_stage_output_preserves_missing_first_scene_heading_for_validation(self):
        """Verify normalize stage output preserves missing first scene heading for validation."""
        data = {
            "final_script": "\n".join(
                [
                    "△陈寻手机屏幕显示：发起人：刘波。",
                    "△陈寻手指停在截图上。",
                    "",
                    "3-2    出租屋室内    日    内",
                    "出场人物：陈寻、王辉",
                    "△陈寻拨出电话。",
                    "王辉（VO）：陈哥，我正想联系你。",
                ]
            ),
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertNotIn("3-1", normalized["final_script"])
        with self.assertRaises(ValueError):
            validators.validate_final_script_quality(
                normalized["final_script"],
                episode_outline={"episode_num": 3, "required_character_names": ["陈寻", "王辉"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "刘波", "王辉"]},
                derived_config={"script_length_chars": "20-800", "scenes_per_episode": "2-4"},
            )

    def test_normalize_stage_output_does_not_invent_heading_for_malformed_scene_line(self):
        """Verify normalize stage output does not invent heading for malformed scene line."""
        data = {
            "final_script": "\n".join(
                [
                    "第五集",
                    "5-1    林月家玄关及街道    日    内转外",
                    "出场人物：方华、林月",
                    "△方华和林月走出单元门。",
                    "",
                    "5-2    考场门口    日    外",
                    "出场人物：方华、林月",
                    "△两人抵达考场。",
                ]
            ),
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertEqual(normalized["final_script"].count("5-1"), 1)
        self.assertNotIn("出场人物：出场人物", normalized["final_script"])
        errors = validators.collect_final_script_quality_errors(
            normalized["final_script"],
            episode_outline={"episode_num": 5, "required_character_names": ["方华"]},
            canonical_story_lock={"protagonist": "方华", "character_names": ["方华", "林月"]},
            derived_config={"script_length_chars": "20-800", "scenes_per_episode": "2-4"},
        )
        self.assertTrue(any("malformed scene heading" in error and "内转外" in error for error in errors))

    def test_normalize_stage_output_preserves_08_transition_location_for_validation(self):
        """Verify normalize stage output preserves 08 transition location for validation."""
        data = {
            "final_script": "\n".join(
                [
                    "第一集",
                    "",
                    "1-1    公司工位区    日    内",
                    "出场人物：陈寻、吴经理",
                    "△陈寻提起纸箱走向电梯，背对吴经理。吴经理站在原地未动。",
                ]
            ),
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("1-1    公司工位区    日    内", normalized["final_script"])

    def test_normalize_stage_output_preserves_08_passed_visible_space_for_validation(self):
        """Verify normalize stage output preserves 08 passed visible space for validation."""
        data = {
            "final_script": "\n".join(
                [
                    "第一集",
                    "",
                    "1-3    公司出口走廊    日    内",
                    "出场人物：陈寻",
                    "△陈寻拖着行李箱走过工位区，四周无人抬头。",
                    "△陈寻走到大门口，取出手机。",
                ]
            ),
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("1-3    公司出口走廊    日    内", normalized["final_script"])

    def test_normalize_stage_output_preserves_08_exited_source_space_for_validation(self):
        """Verify normalize stage output preserves 08 exited source space for validation."""
        data = {
            "final_script": "\n".join(
                [
                    "第一集",
                    "",
                    "1-3    公司出口走廊及工位区    日    内",
                    "出场人物：陈寻",
                    "△陈寻拖着行李箱从办公室走出，经过工位区，四周无人抬头。",
                ]
            ),
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("1-3    公司出口走廊及工位区    日    内", normalized["final_script"])

    def test_normalize_stage_output_preserves_08_passed_source_space_for_validation(self):
        """Verify normalize stage output preserves 08 passed source space for validation."""
        data = {
            "final_script": "\n".join(
                [
                    "第一集",
                    "",
                    "1-3    公司出口走廊及工位区    日    内",
                    "出场人物：陈寻",
                    "△陈寻拖着行李箱从办公室走过工位区，脚步匀速。",
                ]
            ),
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("1-3    公司出口走廊及工位区    日    内", normalized["final_script"])

    def test_normalize_stage_output_preserves_08_location_end_for_validation(self):
        """Verify normalize stage output preserves 08 location end for validation."""
        data = {
            "final_script": "\n".join(
                [
                    "第一集",
                    "",
                    "1-1    公司大厅及前台区    日    内",
                    "出场人物：陈寻、吴经理",
                    "△走廊尽头，吴经理推开办公室门，朝陈寻抬了抬下巴。",
                ]
            ),
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("1-1    公司大厅及前台区    日    内", normalized["final_script"])

    def test_normalize_stage_output_preserves_model_listed_screen_only_cast_member(self):
        """Verify normalize stage output preserves model listed screen only cast member."""
        data = {
            "final_script": "\n".join(
                [
                    "第二集",
                    "",
                    "2-1    出租屋房间    夜    内",
                    "出场人物：陈寻、吴经理",
                    "△手机屏幕亮起。",
                    "△屏幕显示：吴经理 来电。",
                    "△陈寻将手机翻扣在桌面。",
                ]
            ),
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("出场人物：陈寻、吴经理", normalized["final_script"])

    def test_normalize_stage_output_does_not_delete_visible_actor_who_opens_eyes(self):
        """Verify normalize stage output does not delete visible actor who opens eyes."""
        data = {
            "final_script": "\n".join(
                [
                    "第一集",
                    "1-2    医院ICU病房    日    内",
                    "出场人物：方华、爷爷",
                    "△方华睁开眼睛，手指动了一下。",
                    "△爷爷坐在门外剥橘子。",
                ]
            ),
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("出场人物：方华、爷爷", normalized["final_script"])

    def test_normalize_stage_output_does_not_delete_visible_actor_lying_on_sofa(self):
        """Verify normalize stage output does not delete visible actor lying on sofa."""
        data = {
            "final_script": "\n".join(
                [
                    "第五集",
                    "5-2    方家客厅    日    内",
                    "出场人物：方华、方旭、爷爷",
                    "△客厅沙发上方旭半躺着，手机横在胸前。",
                    "方华（放下书包）：我回来了。",
                ]
            ),
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("出场人物：方华、方旭、爷爷", normalized["final_script"])

    def test_normalize_stage_output_keeps_vo_cast_member(self):
        """Verify normalize stage output keeps vo cast member."""
        data = {
            "final_script": "\n".join(
                [
                    "第三集",
                    "",
                    "3-1    出租屋房间    日    内",
                    "出场人物：陈寻、吴经理",
                    "△陈寻接听电话。",
                    "吴经理（VO）：你得还钱。",
                ]
            ),
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("出场人物：陈寻、吴经理", normalized["final_script"])

    def test_normalize_stage_output_keeps_visible_background_cast_member(self):
        """Verify normalize stage output keeps visible background cast member."""
        data = {
            "final_script": "\n".join(
                [
                    "第四集",
                    "",
                    "4-1    咖啡馆内    日    内",
                    "出场人物：陈寻、刘波、赵敏",
                    "△赵敏端起咖啡杯，视线扫过这张桌子。",
                    "陈寻（看向刘波）：你解释。",
                ]
            ),
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("出场人物：陈寻、刘波、赵敏", normalized["final_script"])

    def test_normalize_stage_output_preserves_extra_os_markers_for_validation(self):
        """Verify normalize stage output preserves extra os markers for validation."""
        data = {
            "final_script": "\n".join(
                [
                    "第二集",
                    "",
                    "2-1    出租屋房间    夜    内",
                    "出场人物：陈寻",
                    "陈寻（OS）：第一句。",
                    "陈寻（OS）：第二句。",
                ]
            ),
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertEqual(normalized["final_script"].count("OS"), 2)

    def test_normalize_stage_output_preserves_nonvisual_dialogue_voice_tags_for_validation(self):
        """Verify normalize stage output preserves nonvisual dialogue voice tags for validation."""
        data = {
            "final_script": "第四集\n\n4-1    咖啡馆    日    内\n出场人物：陈寻、刘波\n刘波（抬手，声音拔高）：你给我个理由。",
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("刘波（抬手，声音拔高）：你给我个理由。", normalized["final_script"])

    def test_normalize_stage_output_preserves_dialogue_triangle_prefix_for_validation(self):
        """Verify normalize stage output preserves dialogue triangle prefix for validation."""
        data = {
            "final_script": "第三集\n\n3-2    出租屋室内    日    内\n出场人物：陈寻、王辉\n△陈寻（点头）：好，我准时到。",
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("△陈寻（点头）：好，我准时到。", normalized["final_script"])

    def test_normalize_stage_output_preserves_08_camera_markers_for_validation(self):
        """Verify normalize stage output preserves 08 camera markers for validation."""
        data = {
            "final_script": "第四集\n\n4-1    旧厂会议室    日    内\n出场人物：吴经理\n△吴经理伸手去拿，镜头拉远。",
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("镜头拉远", normalized["final_script"])

    def test_normalize_stage_output_preserves_08_camera_marker_variants_for_validation(self):
        """Verify normalize stage output preserves 08 camera marker variants for validation."""
        data = {
            "final_script": "第一集\n\n1-1    公司门口    日    外\n出场人物：陈寻\n△镜头推近公文包拉链处，定格。\n△镜头停在桌上扣着的手机，屏幕熄灭。",
            "state_update": {},
            "continuity_update": {},
        }

        normalized = pipeline_runner.normalize_stage_output("08_script_body_generation", data)

        self.assertIn("镜头推近", normalized["final_script"])
        self.assertIn("定格", normalized["final_script"])

    def test_llm_client_marks_gateway_errors_as_transient(self):
        """Verify llm client marks gateway errors as transient."""
        self.assertTrue(llm_client.is_transient_error("Poe API HTTP 502 Bad Gateway"))
        self.assertTrue(llm_client.is_transient_error("HTTP 503"))
        self.assertTrue(
            llm_client.is_transient_error(
                "curl: (18) transfer closed with outstanding read data remaining"
            )
        )
        self.assertFalse(llm_client.is_transient_error("missing prompt value"))

    def test_llm_client_retries_incomplete_curl_transfer(self):
        """Verify llm client retries incomplete curl transfer."""
        class FakeProcess:
            """Group fake process behavior."""
            def __init__(self, returncode, stdout=b"", stderr=b""):
                """Initialize the instance."""
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        responses = [
            FakeProcess(
                18,
                stderr=b"curl: (18) transfer closed with outstanding read data remaining",
            ),
            FakeProcess(0, stdout=b'{"ok": true}'),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            attempts_dir = Path(tmpdir) / "attempts"
            attempts_dir.mkdir()
            with mock.patch.object(llm_client.subprocess, "run", side_effect=responses) as mocked_run:
                with mock.patch.object(llm_client.time, "sleep"):
                    result = llm_client.call_llm(
                        "prompt",
                        llm_script=Path("/tmp/fake.sh"),
                        cwd=PROJECT_ROOT,
                        retries=2,
                        attempts_dir=attempts_dir,
                    )

            self.assertEqual(mocked_run.call_count, 2)
            self.assertEqual(result.clean, '{"ok": true}')
            self.assertEqual(len(result.attempt_dirs), 2)
            self.assertTrue((attempts_dir / "llm_attempt_01" / "client_result.json").exists())
            self.assertTrue((attempts_dir / "llm_attempt_02" / "client_result.json").exists())

    def test_llm_client_tolerates_non_utf8_process_output(self):
        """Verify llm client tolerates non utf8 process output."""
        class FakeProcess:
            """Group fake process behavior."""
            returncode = 1
            stdout = b""
            stderr = b"bad stderr: \xe3"

        with mock.patch.object(llm_client.subprocess, "run", return_value=FakeProcess()):
            with self.assertRaisesRegex(RuntimeError, "LLM call failed"):
                llm_client.call_llm("prompt", llm_script=Path("/tmp/fake.sh"), cwd=PROJECT_ROOT, retries=0)

    def test_llm_client_calls_bd_data_api_directly_for_large_prompts(self):
        """Verify llm client calls bd data api directly for large prompts."""
        captured = {}

        class FakeResponse:
            """Group fake response behavior."""
            status = 200

            def __enter__(self):
                """Handle enter."""
                return self

            def __exit__(self, exc_type, exc, tb):
                """Handle exit."""
                return False

            def read(self):
                """Handle read."""
                return json.dumps({"choices": [{"message": {"content": "pong"}}]}).encode("utf-8")

        def fake_urlopen(request, timeout):
            """Handle fake urlopen."""
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse()

        with mock.patch.object(llm_client, "resolve_bd_data_api_key", return_value="sk-test"):
            with mock.patch.object(urllib.request, "urlopen", side_effect=fake_urlopen):
                with mock.patch.object(
                    llm_client.subprocess,
                    "run",
                    side_effect=AssertionError("shell should not run"),
                ):
                    result = llm_client.call_llm(
                        "prompt",
                        llm_script=Path("/tmp/bd-data-chat.sh"),
                        cwd=PROJECT_ROOT,
                        retries=0,
                    )

        body = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual(result.clean, "pong")
        self.assertEqual(body["model"], "gemini-3.1-pro-preview")
        self.assertEqual(body["messages"][0]["content"], "prompt")
        self.assertEqual(body["reasoning_effort"], "high")
        self.assertEqual(captured["timeout"], 1800)

    def test_llm_client_sets_bd_data_long_output_defaults(self):
        """Verify llm client sets bd data long output defaults."""
        payload = llm_client.build_bd_data_payload(
            "prompt",
            Path("/tmp/bd-data-chat.sh"),
            stage_id="07_episode_planning",
        )
        options = llm_client.llm_runtime_options(Path("/tmp/bd-data-chat.sh"), stage_id="07_episode_planning")

        self.assertEqual(payload["max_tokens"], 65536)
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertEqual(options["transport"], "direct_http")

    def test_llm_runtime_options_are_stage_specific(self):
        """Verify llm runtime options are stage specific."""
        script = Path("/tmp/bd-data-chat.sh")

        stage01 = llm_client.llm_runtime_options(script, stage_id="01_novel_summary")
        stage07 = llm_client.llm_runtime_options(script, stage_id="07_episode_planning")

        self.assertEqual(stage01["BD_DATA_MAX_TOKENS"], "16384")
        self.assertEqual(stage07["BD_DATA_MAX_TOKENS"], "65536")

    def test_llm_client_uses_stdin_and_high_tokens_for_dodo_pipeline(self):
        """Verify llm client uses stdin and high tokens for dodo pipeline."""
        script = Path("/tmp/dodo_sonnet46_pipeline.sh")

        self.assertEqual(llm_client.build_llm_command(script, "很长的prompt"), ["bash", str(script)])
        self.assertEqual(llm_client.build_llm_stdin(script, "很长的prompt"), "很长的prompt".encode("utf-8"))

        stage07 = llm_client.llm_runtime_options(script, stage_id="07_episode_planning")
        stage08 = llm_client.llm_runtime_options(script, stage_id="08_script_body_generation")
        stage03 = llm_client.llm_runtime_options(script, stage_id="03_plot_character_extract")

        self.assertEqual(stage07["EFFORT_LEVELS"], "high")
        self.assertEqual(stage07["DODO_ENABLE_THINKING"], "0")
        self.assertEqual(stage07["DODO_THINKING_DISPLAY"], "hidden")
        self.assertEqual(stage03["MAX_TOKENS"], "64000")
        self.assertEqual(stage07["MAX_TOKENS"], "64000")
        self.assertEqual(stage08["EFFORT_LEVELS"], "high")
        self.assertLess(int(stage08["MAX_TOKENS"]), int(stage07["MAX_TOKENS"]))

    def test_llm_client_uses_baidu_oneapi_opus_46_as_default(self):
        """Verify llm client uses baidu oneapi opus 46 as default."""
        self.assertEqual(
            llm_client.FALLBACK_LLM_SCRIPT.name,
            "run_baidu_oneapi_claude_opus_4_6.sh",
        )
        self.assertTrue(llm_client.FALLBACK_LLM_SCRIPT.exists())

        script = Path("/tmp/run_baidu_oneapi_claude_opus_4_6.sh")
        self.assertEqual(llm_client.build_llm_command(script, "很长的prompt"), ["bash", str(script)])
        self.assertEqual(llm_client.build_llm_stdin(script, "很长的prompt"), "很长的prompt".encode("utf-8"))
        options = llm_client.llm_runtime_options(script, stage_id="07_episode_planning")
        self.assertEqual(options["preset"], "baidu-oneapi-claude-opus-4.6")
        self.assertEqual(options["model"], "Claude Opus 4.6")
        self.assertEqual(options["max_tokens"], "128000")
        self.assertEqual(options["output_config.effort"], "high")
        self.assertEqual(options["stream"], "1")
        self.assertEqual(options["env_file"], "/Users/cjlbd/Desktop/Code/.env-baidu-oneapi-data-0708")

    def test_oneapi_bounded_json_stages_disable_hidden_thinking_but_keep_high_effort(self):
        """Verify oneapi bounded json stages disable hidden thinking but keep high effort."""
        script = Path("/tmp/run_baidu_oneapi_claude_opus_4_6.sh")
        with mock.patch.dict("os.environ", {}, clear=True):
            stage02 = llm_client.llm_runtime_options(script, stage_id="02_storyline_understanding")
            stage04 = llm_client.llm_runtime_options(script, stage_id="04_adaptation_direction")
            stage04a = llm_client.llm_runtime_options(script, stage_id="04a_flashback_screening")
            stage04b = llm_client.llm_runtime_options(script, stage_id="04b_dramatic_release_map")
            stage05 = llm_client.llm_runtime_options(script, stage_id="05_plot_character_adaptation")
            stage06 = llm_client.llm_runtime_options(script, stage_id="06_script_outline_design")
            stage07 = llm_client.llm_runtime_options(script, stage_id="07_episode_planning")
            stage08 = llm_client.llm_runtime_options(script, stage_id="08_script_body_generation")
            stage05_env = llm_client.build_llm_env(script, stage_id="05_plot_character_adaptation")

        self.assertEqual(stage02["thinking.type"], "disabled")
        self.assertEqual(stage04["thinking.type"], "disabled")
        self.assertEqual(stage04a["thinking.type"], "disabled")
        self.assertEqual(stage04b["thinking.type"], "disabled")
        self.assertEqual(stage05["thinking.type"], "disabled")
        self.assertEqual(stage06["thinking.type"], "disabled")
        self.assertEqual(stage07["thinking.type"], "disabled")
        self.assertEqual(stage08["thinking.type"], "disabled")
        self.assertEqual(stage05["output_config.effort"], "high")
        self.assertEqual(stage05["max_tokens"], "128000")
        self.assertEqual(stage05_env["BAIDU_ONEAPI_THINKING_TYPE"], "disabled")
        self.assertEqual(stage05_env["BAIDU_ONEAPI_EFFORT"], "high")

    def test_oneapi_wrapper_marks_empty_stream_as_retryable_failure(self):
        """Verify oneapi wrapper marks empty stream as retryable failure."""
        script_text = llm_client.FALLBACK_LLM_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("Error: empty response from OneAPI", script_text)
        self.assertIn("Error: truncated response from OneAPI", script_text)
        self.assertIn('"max_tokens" in stop_reasons', script_text)
        self.assertIn('event.get("type") == "message_stop"', script_text)
        self.assertIn("Error: incomplete response from OneAPI (missing terminal event)", script_text)
        self.assertIn("transport_parser_result.json", script_text)
        self.assertIn("raise SystemExit(1)", script_text)

    def test_llm_client_writes_immutable_attempt_artifacts(self):
        """Verify llm client writes immutable attempt artifacts."""
        completed = mock.Mock(returncode=0, stdout=b'{"ok": true}', stderr=b'')
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch("subprocess.run", return_value=completed) as run_mock:
            attempts_dir = Path(tmpdir) / "attempts"
            result = llm_client.call_llm(
                "prompt",
                llm_script=Path("/tmp/run_baidu_oneapi_claude_opus_4_6.sh"),
                cwd=Path(tmpdir),
                retries=0,
                attempts_dir=attempts_dir,
            )

        attempt_dir = Path(result.attempt_dirs[0])
        self.assertEqual(attempt_dir.name, "llm_attempt_01")
        self.assertEqual(run_mock.call_args.kwargs["env"]["LLM_ATTEMPT_DIR"], str(attempt_dir))

    def test_partial_generation_summary_replaces_stale_pass(self):
        """Verify partial generation summary replaces stale pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "partial_state")
            pipeline_runner.write_json(paths.final / "qa_summary.json", {"overall_status": "PASS"})

            pipeline_runner.write_partial_generation_summary(
                paths,
                run_id="partial_state",
                target_episodes=5,
                generated_episodes=[1, 2],
                current_artifact="08_script_body_generation_ep003",
                failure={"category": "transport", "error": "missing terminal event"},
            )

            qa = json.loads((paths.final / "qa_summary.json").read_text(encoding="utf-8"))
            state = json.loads((paths.root / "run_state.json").read_text(encoding="utf-8"))
        self.assertEqual(qa["overall_status"], "PARTIAL")
        self.assertEqual(state["status"], "partial")
        self.assertEqual(state["continuous_completed_prefix"], 2)

    def test_llm_client_still_allows_explicit_rd_dodo_template(self):
        """Verify llm client still allows explicit rd dodo template."""
        script = Path("/tmp/rd_dodo_api_template.sh")
        self.assertEqual(llm_client.build_llm_command(script, "很长的prompt"), ["bash", str(script)])
        self.assertEqual(llm_client.build_llm_stdin(script, "很长的prompt"), "很长的prompt".encode("utf-8"))
        self.assertEqual(
            llm_client.llm_runtime_options(script, stage_id="07_episode_planning")["preset"],
            "dodo-sonnet-4.6",
        )

    def test_clean_llm_output_strips_leaked_thinking_prefix(self):
        """Verify clean llm output strips leaked thinking prefix."""
        raw = '<thinking>\n分析过程\n```json\n{"ok": true}\n```\n---\nmodel: claude-sonnet-4-6 | stop: end_turn'

        self.assertEqual(llm_client.clean_llm_output(raw), '```json\n{"ok": true}\n```')

    def test_clean_llm_output_prefers_text_after_closed_thinking_block(self):
        """Verify clean llm output prefers text after closed thinking block."""
        raw = (
            '<thinking>\n分析过程\n```json\n{"draft": true}\n```\n</thinking>\n'
            '{"block_plan":{"block_id":2},"episode_outlines":[]}\n'
            '---\nmodel: claude-opus-4-6 | stop: end_turn'
        )

        self.assertEqual(
            llm_client.clean_llm_output(raw),
            '{"block_plan":{"block_id":2},"episode_outlines":[]}',
        )

    def test_clean_llm_output_strips_bracketed_thinking_prefix(self):
        """Verify clean llm output strips bracketed thinking prefix."""
        raw = '[thinking]\n分析过程\n```json\n{"ok": true}\n```\n---\nmodel: claude-sonnet-4-6 | stop: end_turn'

        self.assertEqual(llm_client.clean_llm_output(raw), '```json\n{"ok": true}\n```')

    def test_llm_client_rejects_empty_bd_data_length_response(self):
        """Verify llm client rejects empty bd data length response."""
        data = {
            "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
            "usage": {"completion_tokens": 65536},
        }

        with self.assertRaisesRegex(RuntimeError, "finish_reason=length"):
            llm_client.extract_bd_data_text(data)

    def test_validate_episode_sequence_requires_exact_target_count(self):
        """Verify validate episode sequence requires exact target count."""
        episodes = [{"episode_num": idx, "title": f"第{idx}集"} for idx in range(1, 81)]

        validators.validate_episode_sequence(episodes, target_episodes=80)

        with self.assertRaisesRegex(ValueError, "target_episodes"):
            validators.validate_episode_sequence(episodes[:-1], target_episodes=80)

    def test_validate_target_episodes_range_accepts_40_to_100_only(self):
        """Verify validate target episodes range accepts 40 to 100 only."""
        for target in (40, 60, 80, 100):
            validators.validate_target_episodes_range(target)

        for target in (39, 101):
            with self.assertRaisesRegex(ValueError, "40-100"):
                validators.validate_target_episodes_range(target)

    def test_expand_allowed_character_names_expands_parent_group_aliases(self):
        """Verify expand allowed character names expands parent group aliases."""
        expanded = validators.expand_allowed_character_names(["女主父母", "父母"])

        self.assertIn("父亲", expanded)
        self.assertIn("母亲", expanded)
        self.assertIn("女主父亲", expanded)
        self.assertIn("女主母亲", expanded)

    def test_validate_final_script_quality_accepts_normalized_protagonist_alias(self):
        """Verify validate final script quality accepts normalized protagonist alias."""
        script = (
            "第一集\n"
            "\n"
            "1-1    客厅    日    内\n"
            "出场人物：女主、沈浩、球球\n"
            "△女主抱紧球球，沈浩站在门口低声抱怨。\n"
            "女主（后退半步）：球球今天跟我走。\n"
            "\n"
            "1-2    小区    日    外\n"
            "出场人物：女主、球球\n"
            "△女主牵着球球慢慢走出小区门口。\n"
            "女主（低头看球球）：别怕。"
        )
        episode = {"episode_num": 1, "required_character_names": ["女主"]}
        canonical = {"protagonist": "女主（未命名）", "character_names": ["女主（未命名）", "沈浩", "球球"]}
        derived = {"script_length_chars": "20-9999", "scenes_per_episode": "2-4"}

        validators.validate_final_script_quality(
            script,
            episode_outline=episode,
            canonical_story_lock=canonical,
            derived_config=derived,
        )

    def test_validate_final_script_quality_allows_repaired_single_scene_plan_count(self):
        """Verify validate final script quality allows repaired single scene plan count."""
        script = (
            "第三集\n"
            "\n"
            "3-1    旧厂会议室    日    内\n"
            "出场人物：陈寻、刘波、吴经理\n"
            "△刘波把追薪协议推到陈寻面前，吴经理站在门口。\n"
            "刘波（点着协议）：签了，五年底薪不追。\n"
            "陈寻（把协议推回）：不签。"
        )
        episode = {
            "episode_num": 3,
            "required_character_names": ["陈寻"],
            "scene_plan": [
                {
                    "scene_no": 1,
                    "location": "旧厂会议室",
                    "time": "日",
                    "space": "内",
                    "appearing_character_names": ["陈寻", "刘波", "吴经理"],
                    "scene_purpose": "追薪压价与拒签反制",
                    "must_include_beats": ["刘波推协议", "陈寻拒签"],
                    "scene_boundary_reason": "相邻内部节奏已合并为单一自然场",
                }
            ],
        }
        canonical = {"protagonist": "陈寻", "character_names": ["陈寻", "刘波", "吴经理"]}
        derived = {"script_length_chars": "20-9999", "scenes_per_episode": "2-4"}

        validators.validate_final_script_quality(
            script,
            episode_outline=episode,
            canonical_story_lock=canonical,
            derived_config=derived,
        )

    def test_run_config_validation_and_derivation(self):
        """Verify run config validation and derivation."""
        config = {
            "target_episodes": 40,
            "episode_duration_seconds": 90,
            "rewrite_intensity": "balanced",
            "character_background_policy": "minor_adjust",
            "subplot_policy": "moderate",
            "new_character_policy": "controlled",
            "source_preservation_level": "core_plot",
            "source_boundary_mode": "balanced_spark",
            "pacing_controls": {
                "epilogue_max_episodes": 2,
                "event_reuse_max_episodes": 3,
                "conflict_mode_streak_limit": 2,
                "major_climax_window": "36-39",
                "cross_block_bridge_max_episodes": 1,
            },
            "market_tags": ["大女主", "复仇爽文"],
        }

        validators.validate_run_config(config)
        derived = pipeline_runner.derive_run_config(config)

        self.assertEqual(derived["block_count"], 4)
        self.assertEqual(derived["scenes_per_episode"], "2-4")
        self.assertEqual(derived["script_length_chars"], "650-780")
        self.assertEqual(derived["event_pool_size"], "12-16")
        self.assertEqual(derived["major_climax_window"], "36-39")
        self.assertEqual(derived["epilogue_max_episodes"], 2)
        self.assertGreaterEqual(derived["new_character_budget"], 1)

        invalid = dict(config)
        invalid["episode_duration_seconds"] = 75
        with self.assertRaisesRegex(ValueError, "episode_duration_seconds"):
            validators.validate_run_config(invalid)

    def test_validate_longform_blocks_follow_dynamic_block_count(self):
        """Verify validate longform blocks follow dynamic block count."""
        blocks = [
            {"block_id": 1, "episode_count": 10},
            {"block_id": 2, "episode_count": 10},
            {"block_id": 3, "episode_count": 10},
            {"block_id": 4, "episode_count": 10},
        ]

        validators.validate_longform_blocks(blocks, target_episodes=40, expected_block_count=4)

        with self.assertRaisesRegex(ValueError, "expected 4"):
            validators.validate_longform_blocks(blocks[:-1], target_episodes=40, expected_block_count=4)

    def test_validate_adapted_plot_points_require_trace_or_new_type(self):
        """Verify validate adapted plot points require trace or new type."""
        validators.validate_adapted_plot_points(
            [
                {"id": 1, "title": "保留复仇主线", "source_plot_point_ids": [1]},
                {"id": 2, "title": "新增校门口污蔑", "adaptation_type": "new_expansion"},
            ]
        )

        with self.assertRaisesRegex(ValueError, "source_plot_point_ids"):
            validators.validate_adapted_plot_points([{"id": 3, "title": "无追溯"}])

    def test_validate_event_pool_requires_trace_or_expansion_type(self):
        """Verify validate event pool requires trace or expansion type."""
        validators.validate_event_pool_trace(
            [
                {"id": 1, "title": "保留花生酱反噬", "source_plot_point_ids": [1]},
                {"id": 2, "title": "新增校门口围攻", "expansion_type": "new_expansion"},
            ]
        )

        with self.assertRaisesRegex(ValueError, "source_plot_point_ids"):
            validators.validate_event_pool_trace([{"id": 3, "title": "无追溯事件"}])

    def test_validate_event_pool_contract_requires_longform_fields(self):
        """Verify validate event pool contract requires longform fields."""
        event_pool = [
            {
                "id": 1,
                "title": "谣言引爆",
                "function": "压力升级",
                "source_plot_point_ids": [1],
                "expansion_type": "strengthen",
                "target_block": 1,
                "episode_window": {"start": 1, "end": 10},
                "not_before_episode": 1,
                "not_after_episode": 10,
                "expected_episode_span": 2,
                "importance_level": "A",
                "conflict_mode": "public_shaming",
                "pattern_family": "rumor_counterattack",
                "source_anchor": "源故事中的造谣羞辱",
                "delta_from_source": "放大围观压力",
                "legal_moral_risk": "low",
                "content_sensitivity_risk": "low",
                "child_beats": ["造谣", "取证", "反击"],
            }
        ]

        validators.validate_event_pool_contract(event_pool, derived_config={"event_pool_size": "1-2"})

        missing = [dict(event_pool[0])]
        missing[0].pop("source_anchor")
        with self.assertRaisesRegex(ValueError, "source_anchor"):
            validators.validate_event_pool_contract(missing, derived_config={"event_pool_size": "1-2"})

        no_anchor = [dict(event_pool[0], source_anchor="无")]
        with self.assertRaisesRegex(ValueError, "source_anchor"):
            validators.validate_event_pool_contract(no_anchor, derived_config={"event_pool_size": "1-2"})

        high_risk = [
            dict(
                event_pool[0],
                id=10,
                title="诱饵入局",
                source_anchor="用诱饵让反派进入封闭房间承受果报",
                delta_from_source="主角故意透露财物位置引诱对方入局",
                legal_moral_risk="high",
                child_beats=["故意透露财物藏匿点", "反派进入房间", "主角旁观"],
            )
        ]
        validators.validate_event_pool_contract(high_risk, derived_config={"event_pool_size": "1-2"})

        content_harm = [
            dict(
                event_pool[0],
                id=15,
                title="暗室反噬",
                source_anchor="反派被侵犯过程被摄像头完整记录",
                delta_from_source="把性暴力结果作为高潮公开处刑",
                legal_moral_risk="low",
                child_beats=["刘大勇暴力捂嘴侵犯", "摄像头记录施暴全过程", "村民围观不堪入目现场"],
            )
        ]
        validators.validate_event_pool_contract(content_harm, derived_config={"event_pool_size": "1-2"})

        public_privacy_harm = [
            dict(
                event_pool[0],
                id=16,
                title="当众甩证",
                source_anchor="主角移交偷拍视频证据",
                delta_from_source="女主当众播放监控视频并让全村公开处刑性污名源头",
                legal_moral_risk="low",
                content_sensitivity_risk="low",
                child_beats=["公开播放监控视频", "全村公开处刑隐私证据"],
            )
        ]
        validators.validate_event_pool_contract(public_privacy_harm, derived_config={"event_pool_size": "1-2"})

    def test_validate_episode_asset_references_require_known_ids(self):
        """Verify validate episode asset references require known ids."""
        validators.validate_episode_asset_references(
            [{"episode_num": 1, "event_ids": [1], "foreshadowing_ids": [2]}],
            event_pool=[{"id": 1}],
            foreshadowing_pool=[{"id": 2}],
        )

        with self.assertRaisesRegex(ValueError, "unknown foreshadowing_ids"):
            validators.validate_episode_asset_references(
                [{"episode_num": 1, "event_ids": [1], "foreshadowing_ids": [99]}],
                event_pool=[{"id": 1}],
                foreshadowing_pool=[{"id": 2}],
            )

    def test_validate_episode_longform_contract_blocks_repetition_and_epilogue_overrun(self):
        """Verify validate episode longform contract blocks repetition and epilogue overrun."""
        event_pool = [
            {
                "id": 1,
                "target_block": 1,
                "episode_window": {"start": 1, "end": 10},
                "not_before_episode": 1,
                "not_after_episode": 10,
                "expected_episode_span": 3,
            },
            {
                "id": 2,
                "target_block": 2,
                "episode_window": {"start": 11, "end": 20},
                "not_before_episode": 11,
                "not_after_episode": 20,
                "expected_episode_span": 3,
            },
        ]
        derived = {
            "event_reuse_max_episodes": 3,
            "conflict_mode_streak_limit": 2,
            "epilogue_max_episodes": 1,
        }

        valid = [
            {
                "episode_num": 1,
                "block_id": 1,
                "event_ids": [1],
                "main_conflict": "谣言压迫升级",
                "counterattack": "主角留证",
                "conflict_mode": "rumor",
                "pattern_family": "rumor_counterattack",
                "source_anchor": "源故事造谣",
                "boundary_check": {
                    "risk_level": "low",
                    "protagonist_action": "留证",
                    "why_allowed": "依法取证",
                    "mitigation": "不主动伤害",
                },
                "appearing_character_names": ["沈念"],
                "is_epilogue": False,
            },
            {
                "episode_num": 2,
                "block_id": 1,
                "event_ids": [1],
                "main_conflict": "亲属围攻",
                "counterattack": "主角反问",
                "conflict_mode": "family_pressure",
                "pattern_family": "family_pressure",
                "source_anchor": "源故事围观",
                "boundary_check": {
                    "risk_level": "low",
                    "protagonist_action": "反问",
                    "why_allowed": "语言反击",
                    "mitigation": "不主动伤害",
                },
                "appearing_character_names": ["沈念"],
                "is_epilogue": False,
            },
        ]

        validators.validate_episode_longform_contract(
            valid,
            event_pool=event_pool,
            derived_config=derived,
            allowed_character_names=["沈念"],
        )

        wrong_block = [dict(valid[0], episode_num=11, block_id=2)]
        with self.assertRaisesRegex(ValueError, "target_block"):
            validators.validate_episode_longform_contract(
                wrong_block,
                event_pool=event_pool,
                derived_config=derived,
                allowed_character_names=["沈念"],
            )

        repeated_mode = [dict(valid[0], episode_num=idx, conflict_mode="rumor") for idx in (1, 2, 3)]
        with self.assertRaisesRegex(ValueError, "conflict_mode"):
            validators.validate_episode_longform_contract(
                repeated_mode,
                event_pool=event_pool,
                derived_config=derived,
                allowed_character_names=["沈念"],
            )

        too_many_epilogues = [
            dict(valid[0], episode_num=9, is_epilogue=True),
            dict(valid[1], episode_num=10, is_epilogue=True),
        ]
        with self.assertRaisesRegex(ValueError, "epilogue"):
            validators.validate_episode_longform_contract(
                too_many_epilogues,
                event_pool=event_pool,
                derived_config=derived,
                allowed_character_names=["沈念"],
            )

    def test_validate_episode_longform_contract_records_boundary_and_blocks_unknown_characters(self):
        """Verify validate episode longform contract records boundary and blocks unknown characters."""
        event_pool = [
            {
                "id": 1,
                "target_block": 1,
                "episode_window": {"start": 1, "end": 3},
                "not_before_episode": 1,
                "not_after_episode": 3,
                "expected_episode_span": 2,
                "pattern_family": "evidence",
            },
        ]
        derived = {"event_reuse_max_episodes": 3, "conflict_mode_streak_limit": 2, "epilogue_max_episodes": 2}
        base = {
            "episode_num": 1,
            "block_id": 1,
            "event_ids": [1],
            "main_conflict": "反派逼迫主角",
            "counterattack": "主角留证",
            "conflict_mode": "evidence",
            "pattern_family": "evidence",
            "source_anchor": "源故事取证",
            "boundary_check": {
                    "risk_level": "low",
                    "protagonist_action": "留证",
                    "why_allowed": "依法取证",
                    "mitigation": "不主动伤害",
                },
            "appearing_character_names": ["沈念"],
            "is_epilogue": False,
        }

        risky = dict(
            base,
            boundary_check=(
                {"risk_level": "high", "protagonist_action": "沈念给证人喂药制造中毒", "why_allowed": "保护证人", "mitigation": "无"}
            ),
        )
        validators.validate_episode_longform_contract(
            [risky],
            event_pool=event_pool,
            derived_config=derived,
            allowed_character_names=["沈念"],
        )

        induced_trap = dict(
            base,
            main_conflict="主角必须让反派自愿进入房间承受果报",
            counterattack="主角故意透露财物位置，引诱反派入局",
            source_anchor="诱导反派进入封闭房间",
        )
        validators.validate_episode_longform_contract(
            [induced_trap],
            event_pool=event_pool,
            derived_config=derived,
            allowed_character_names=["沈念"],
        )

        false_accusation = dict(
            base,
            main_conflict="反派反咬是沈念设局下药陷害",
            counterattack="沈念提供人证证明自己不在场",
            boundary_check=(
                {"risk_level": "low", "protagonist_action": "提供人证", "why_allowed": "无罪辩护", "mitigation": "无"}
            ),
        )
        validators.validate_episode_longform_contract(
            [false_accusation],
            event_pool=event_pool,
            derived_config=derived,
            allowed_character_names=["沈念"],
        )

        self_entry = dict(
            base,
            main_conflict="东屋成为前世惨死地，也是沈念今生复仇的诱饵笼子",
            counterattack="沈念提着行李走入东屋，悄悄点开手机录音",
            boundary_check=(
                {"risk_level": "low", "protagonist_action": "假意顺从避开锋芒", "why_allowed": "战术撤退", "mitigation": "无"}
            ),
        )
        validators.validate_episode_longform_contract(
            [self_entry],
            event_pool=event_pool,
            derived_config=derived,
            allowed_character_names=["沈念"],
        )

        unknown = dict(base, appearing_character_names=["沈念", "老孙"])
        with self.assertRaisesRegex(ValueError, "appearing_character_names"):
            validators.validate_episode_longform_contract(
                [unknown],
                event_pool=event_pool,
                derived_config=derived,
                allowed_character_names=["沈念"],
            )

        annotated = dict(base, appearing_character_names=["沈念", "陈峰 (电话)"])
        validators.validate_episode_longform_contract(
            [annotated],
            event_pool=event_pool,
            derived_config=derived,
            allowed_character_names=["沈念", "陈峰"],
        )

        group_alias = dict(base, appearing_character_names=["沈念", "村民"])
        validators.validate_episode_longform_contract(
            [group_alias],
            event_pool=event_pool,
            derived_config=derived,
            allowed_character_names=["沈念", "民兵及村民"],
        )

        overloaded_epilogue = dict(base, is_epilogue=True, event_ids=[1, 2, 3])
        with self.assertRaisesRegex(ValueError, "epilogue event"):
            validators.validate_episode_longform_contract(
                [overloaded_epilogue],
                event_pool=(
                    event_pool
                    + [
                        {
                            "id": 2,
                            "target_block": 1,
                            "episode_window": {"start": 1, "end": 3},
                            "not_before_episode": 1,
                            "not_after_episode": 3,
                            "expected_episode_span": 1,
                        },
                        {
                            "id": 3,
                            "target_block": 1,
                            "episode_window": {"start": 1, "end": 3},
                            "not_before_episode": 1,
                            "not_after_episode": 3,
                            "expected_episode_span": 1,
                        },
                    ]
                ),
                derived_config=derived,
                allowed_character_names=["沈念"],
            )

        content_harm_episode = dict(
            base,
            main_conflict="众人踹门目睹不堪入目的性侵现场",
            counterattack="主角播放监控记录的施暴全过程",
            source_anchor="把性暴力结果作为反派社死",
        )
        validators.validate_episode_longform_contract(
            [content_harm_episode],
            event_pool=event_pool,
            derived_config=derived,
            allowed_character_names=["沈念"],
        )

    def test_validate_episode_required_names_use_canonical_lock(self):
        """Verify validate episode required names use canonical lock."""
        validators.validate_episode_required_names(
            [{"episode_num": 1, "required_character_names": ["方华"]}],
            allowed_names=["方华", "方旭"],
        )

        with self.assertRaisesRegex(ValueError, "required_character_names"):
            validators.validate_episode_required_names(
                [{"episode_num": 1, "required_character_names": ["姜念"]}],
                allowed_names=["方华", "方旭"],
            )

    def test_validate_continuity_update_rejects_unknown_foreshadowing_ids(self):
        """Verify validate continuity update rejects unknown foreshadowing ids."""
        validators.validate_continuity_update_references(
            {"foreshadowing_status": [{"id": 1, "status": "投放"}]},
            foreshadowing_pool=[{"id": 1}],
        )

        with self.assertRaisesRegex(ValueError, "unknown foreshadowing"):
            validators.validate_continuity_update_references(
                {"foreshadowing_status": [{"id": 7, "status": "投放"}]},
                foreshadowing_pool=[{"id": 1}],
            )

    def test_merge_continuity_ledger_merges_foreshadowing_by_id(self):
        """Verify merge continuity ledger merges foreshadowing by id."""
        ledger = {"foreshadowing_status": [{"id": 1, "status": "投放"}]}
        merged = pipeline_runner.merge_continuity_ledger(
            ledger,
            episode={"episode_num": 1, "title": "第1集"},
            output={"final_script": "正文", "continuity_update": {"foreshadowing_status": [{"id": 1, "status": "回收"}]}},
        )

        self.assertEqual(merged["foreshadowing_status"], [{"id": 1, "status": "回收"}])

    def test_build_previous_episode_context_prioritizes_tail_and_bridge(self):
        """Verify build previous episode context prioritizes tail and bridge."""
        script = "# 第1集\n" + "开头铺垫。" * 120 + "\n沈念逼近王桂兰，低声说我给你准备了一份大礼。"
        previous_output = {
            "final_script": script,
            "state_update": {"audience_known": "沈念已经反击"},
            "continuity_update": {
                "next_episode_bridge": "王桂兰要求沈念翻包自证，引出录音反制。",
                "source_anchor_executed": "村口造谣被当众反击",
            },
        }

        context = pipeline_runner.build_previous_episode_context(
            episode={"episode_num": 1, "ending_hook": "沈念逼近王桂兰"},
            output=previous_output,
        )

        self.assertEqual(context["last_episode_num"], 1)
        self.assertIn("开头铺垫", context["last_script_head"])
        self.assertIn("我给你准备了一份大礼", context["last_script_tail"])
        self.assertNotEqual(context["last_script_head"], context["last_script_tail"])
        self.assertEqual(context["previous_next_bridge"], "王桂兰要求沈念翻包自证，引出录音反制。")
        self.assertEqual(
            context["opening_priority"],
            "从 last_script_tail 和 previous_next_bridge 的后一拍继续，不重复 last_script_head 已完成动作。",
        )

    def test_merge_continuity_ledger_keeps_tail_not_only_preview(self):
        """Verify merge continuity ledger keeps tail not only preview."""
        script = "# 第1集\n" + "开头铺垫。" * 80 + "\n沈念逼近王桂兰，低声说我给你准备了一份大礼。"
        merged = pipeline_runner.merge_continuity_ledger(
            {"foreshadowing_status": []},
            episode={"episode_num": 1, "title": "第1集", "ending_hook": "沈念逼近王桂兰"},
            output={"final_script": script, "continuity_update": {"next_episode_bridge": "下一集接翻包自证"}},
        )

        summary = merged["generated_episode_summaries"][0]
        self.assertIn("开头铺垫", summary["script_preview"])
        self.assertIn("我给你准备了一份大礼", summary["script_tail"])
        self.assertEqual(summary["next_episode_bridge"], "下一集接翻包自证")

    def test_compact_continuity_context_keeps_recent_three_without_old_script_excerpts(self):
        """Verify compact continuity context keeps recent three without old script excerpts."""
        ledger = {
            "audience_known": ["全公司已投票开除陈寻"],
            "character_known": {"陈寻": ["客户只认陈寻"]},
            "writer_private": ["王辉暗中转移订单"],
            "foreshadowing_status": [{"id": 1, "status": "未回收"}],
            "open_threads": ["合同归属未定"],
            "prop_positions": {"合同": "陈寻文件袋"},
            "next_episode_bridge": "陈寻走向会议室",
            "generated_episode_summaries": [
                {
                    "episode_num": index,
                    "title": f"第{index}集",
                    "script_preview": f"EP{index}旧开头" + "很长" * 80,
                    "script_tail": f"EP{index}旧结尾" + "很长" * 80,
                    "completed_beats": [f"第{index}集已完成动作"],
                    "next_episode_bridge": f"第{index}集桥接",
                }
                for index in range(1, 41)
            ],
        }

        compact = pipeline_runner.compact_continuity_context(ledger, recent_episode_count=3)

        self.assertEqual([item["episode_num"] for item in compact["recent_episode_summaries"]], [38, 39, 40])
        self.assertIn("合同归属未定", compact["open_threads"])
        self.assertEqual(compact["prop_positions"], {"合同": "陈寻文件袋"})
        compact_text = json.dumps(compact, ensure_ascii=False)
        self.assertNotIn("EP1旧开头", compact_text)
        self.assertNotIn("EP20旧结尾", compact_text)
        self.assertIn("EP40旧结尾", compact_text)
        self.assertLess(len(compact_text), 12000)

    def test_build_qa_summary_blocks_adjacent_script_rewind(self):
        """Verify build qa summary blocks adjacent script rewind."""
        stage_outputs = {
            "05_plot_character_adaptation": {"event_pool": [{"id": 1, "target_block": 1}], "foreshadowing_pool": []},
            "06_script_outline_design": {
                    "block_state_plan": [{"block_id": 1}],
                    "event_release_schedule": [{"block_id": 1}],
                },
        }
        episodes = [
            {
                "episode_num": 1,
                "block_id": 1,
                "event_ids": [1],
                "main_conflict": "王桂兰造谣",
                "counterattack": "沈念逼近王桂兰",
                "ending_hook": "沈念说要送大礼",
                "conflict_mode": "rumor",
                "pattern_family": "rumor",
            },
            {
                "episode_num": 2,
                "block_id": 1,
                "event_ids": [1],
                "main_conflict": "翻包自证",
                "counterattack": "沈念录音反制",
                "ending_hook": "警告王桂兰",
                "conflict_mode": "evidence",
                "pattern_family": "evidence",
            },
        ]
        final_scripts = [
            {
                "episode_num": 1,
                "final_script": "# 第1集\n王桂兰要求沈念翻包自证。沈念逼近王桂兰，说要送大礼。",
                "continuity_update": {"next_episode_bridge": "下一集应从翻包自证后一拍继续。"},
            },
            {
                "episode_num": 2,
                "final_script": "# 第2集\n王桂兰要求沈念翻包自证。沈念逼近王桂兰，说要送大礼。她重新拿出录音。",
                "continuity_update": {"next_episode_bridge": "进入下一轮反击。"},
            },
        ]

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            episodes,
            target_episodes=2,
            derived_config={"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2},
            final_scripts=final_scripts,
            validation_mode="strict",
        )

        self.assertEqual(qa["check_results"]["adjacent_opening_continuity"], "BLOCK")
        self.assertTrue(any(item.get("check") == "adjacent_opening_continuity" for item in qa["blocking_issues"]))

    def test_build_qa_summary_collect_mode_warns_adjacent_script_rewind_without_blocking(self):
        """Verify build qa summary collect mode warns adjacent script rewind without blocking."""
        stage_outputs = {
            "05_plot_character_adaptation": {"event_pool": [{"id": 1, "target_block": 1}], "foreshadowing_pool": []},
            "06_script_outline_design": {
                    "block_state_plan": [{"block_id": 1}],
                    "event_release_schedule": [{"block_id": 1}],
                },
        }
        episodes = [
            {
                "episode_num": 1,
                "block_id": 1,
                "event_ids": [1],
                "main_conflict": "王桂兰造谣",
                "counterattack": "沈念逼近王桂兰",
                "ending_hook": "沈念说要送大礼",
                "conflict_mode": "rumor",
                "pattern_family": "rumor",
            },
            {
                "episode_num": 2,
                "block_id": 1,
                "event_ids": [1],
                "main_conflict": "翻包自证",
                "counterattack": "沈念录音反制",
                "ending_hook": "警告王桂兰",
                "conflict_mode": "evidence",
                "pattern_family": "evidence",
            },
        ]
        final_scripts = [
            {
                "episode_num": 1,
                "final_script": "# 第1集\n王桂兰要求沈念翻包自证。沈念逼近王桂兰，说要送大礼。",
                "continuity_update": {"next_episode_bridge": "下一集应从翻包自证后一拍继续。"},
            },
            {
                "episode_num": 2,
                "final_script": "# 第2集\n王桂兰要求沈念翻包自证。沈念逼近王桂兰，说要送大礼。她重新拿出录音。",
                "continuity_update": {"next_episode_bridge": "进入下一轮反击。"},
            },
        ]

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            episodes,
            target_episodes=2,
            derived_config={"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2},
            final_scripts=final_scripts,
            validation_mode="collect",
        )

        self.assertEqual(qa["validation_mode"], "collect")
        self.assertEqual(qa["generation_status"], "PASS")
        self.assertEqual(qa["quality_status"], "WARN")
        self.assertEqual(qa["overall_status"], "PASS")
        self.assertEqual(qa["check_results"]["adjacent_opening_continuity"], "WARN")
        self.assertFalse(qa["blocking_issues"])
        self.assertTrue(any(item.get("check") == "adjacent_opening_continuity" for item in qa["warnings"]))

    def test_build_qa_summary_collect_mode_keeps_episode_numbering_hard_block(self):
        """Verify build qa summary collect mode keeps episode numbering hard block."""
        stage_outputs = {
            "05_plot_character_adaptation": {"event_pool": [], "foreshadowing_pool": []},
            "06_script_outline_design": {
                    "block_state_plan": [{"block_id": 1}],
                    "event_release_schedule": [{"block_id": 1}],
                },
        }
        episodes = [
            {
                "episode_num": 1,
                "block_id": 1,
                "event_ids": [],
                "main_conflict": "冲突",
                "counterattack": "反击",
                "ending_hook": "钩子",
            },
            {
                "episode_num": 3,
                "block_id": 1,
                "event_ids": [],
                "main_conflict": "冲突",
                "counterattack": "反击",
                "ending_hook": "钩子",
            },
        ]

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            episodes,
            target_episodes=3,
            validation_mode="collect",
        )

        self.assertEqual(qa["generation_status"], "BLOCK")
        self.assertEqual(qa["overall_status"], "BLOCK")
        self.assertEqual(qa["quality_status"], "PASS")
        self.assertTrue(any(item.get("check") == "episode_numbering" for item in qa["blocking_issues"]))

    def test_build_qa_summary_strict_mode_keeps_quality_blockers(self):
        """Verify build qa summary strict mode keeps quality blockers."""
        stage_outputs = {
            "05_plot_character_adaptation": {"event_pool": [{"id": 1, "target_block": 1}], "foreshadowing_pool": []},
            "06_script_outline_design": {
                    "block_state_plan": [{"block_id": 1}],
                    "event_release_schedule": [{"block_id": 1}],
                },
        }
        episodes = [
            {
                "episode_num": 1,
                "block_id": 1,
                "event_ids": [1],
                "main_conflict": "王桂兰造谣",
                "counterattack": "沈念逼近王桂兰",
                "ending_hook": "沈念说要送大礼",
                "conflict_mode": "rumor",
                "pattern_family": "rumor",
            },
            {
                "episode_num": 2,
                "block_id": 1,
                "event_ids": [1],
                "main_conflict": "翻包自证",
                "counterattack": "沈念录音反制",
                "ending_hook": "警告王桂兰",
                "conflict_mode": "evidence",
                "pattern_family": "evidence",
            },
        ]
        final_scripts = [
            {"episode_num": 1, "final_script": "# 第1集\n王桂兰要求沈念翻包自证。沈念逼近王桂兰，说要送大礼。"},
            {"episode_num": 2, "final_script": "# 第2集\n王桂兰要求沈念翻包自证。沈念逼近王桂兰，说要送大礼。"},
        ]

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            episodes,
            target_episodes=2,
            derived_config={"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2},
            final_scripts=final_scripts,
            validation_mode="strict",
        )

        self.assertEqual(qa["validation_mode"], "strict")
        self.assertEqual(qa["generation_status"], "PASS")
        self.assertEqual(qa["quality_status"], "WARN")
        self.assertEqual(qa["overall_status"], "BLOCK")
        self.assertTrue(any(item.get("check") == "adjacent_opening_continuity" for item in qa["blocking_issues"]))

    def test_build_qa_summary_ignores_repeated_cast_lines_in_adjacent_scripts(self):
        """Verify build qa summary ignores repeated cast lines in adjacent scripts."""
        stage_outputs = {
            "05_plot_character_adaptation": {"event_pool": [{"id": 1, "target_block": 1}], "foreshadowing_pool": []},
            "06_script_outline_design": {
                    "block_state_plan": [{"block_id": 1}],
                    "event_release_schedule": [{"block_id": 1}],
                },
        }
        episodes = [
            {
                "episode_num": 1,
                "block_id": 1,
                "event_ids": [1],
                "conflict_mode": "pressure",
                "pattern_family": "pressure",
            },
            {
                "episode_num": 2,
                "block_id": 1,
                "event_ids": [1],
                "conflict_mode": "evidence",
                "pattern_family": "evidence",
            },
        ]
        final_scripts = [
            {
                "episode_num": 1,
                "final_script": "第一集\n\n1-1    旧厂会议室    日    内\n出场人物：陈寻、吴经理\n△吴经理把平板推到陈寻面前。\n陈寻（看着平板）：我知道了。",
            },
            {
                "episode_num": 2,
                "final_script": "第二集\n\n2-1    旧厂人事谈话室    日    内\n出场人物：陈寻、吴经理\n△陈寻把支票折好放进口袋。\n吴经理（指着协议）：你现在签字。",
            },
        ]

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            episodes,
            target_episodes=2,
            derived_config={"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2},
            final_scripts=final_scripts,
            validation_mode="strict",
        )

        self.assertEqual(qa["check_results"]["adjacent_opening_continuity"], "PASS")

    def test_build_qa_summary_blocks_repeated_completed_check_prop_state(self):
        """Verify build qa summary blocks repeated completed check prop state."""
        stage_outputs = {
            "05_plot_character_adaptation": {"event_pool": [{"id": 1, "target_block": 1}], "foreshadowing_pool": []},
            "06_script_outline_design": {
                    "block_state_plan": [{"block_id": 1}],
                    "event_release_schedule": [{"block_id": 1}],
                },
        }
        episodes = [
            {
                "episode_num": 1,
                "block_id": 1,
                "event_ids": [1],
                "conflict_mode": "pressure",
                "pattern_family": "pressure",
            },
            {
                "episode_num": 2,
                "block_id": 1,
                "event_ids": [1],
                "conflict_mode": "evidence",
                "pattern_family": "evidence",
            },
        ]
        final_scripts = [
            {
                "episode_num": 1,
                "final_script": "第一集\n\n1-1    旧厂会议室    日    内\n出场人物：陈寻、吴经理\n△陈寻把五千元支票折好，放进外套口袋。",
                "continuity_update": {"completed_beats": ["五千元支票交付，陈寻收入口袋但未签字"]},
            },
            {
                "episode_num": 2,
                "final_script": "第二集\n\n2-1    旧厂人事谈话室    日    内\n出场人物：陈寻、吴经理\n△桌上摆着一份离职协议和一张五千元支票。\n陈寻（低头）：我不签。",
                "continuity_update": {"completed_beats": []},
            },
        ]

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            episodes,
            target_episodes=2,
            derived_config={"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2},
            final_scripts=final_scripts,
            validation_mode="strict",
        )

        self.assertEqual(qa["check_results"]["completed_prop_continuity"], "BLOCK")
        self.assertTrue(any(item.get("check") == "completed_prop_continuity" for item in qa["blocking_issues"]))

    def test_build_qa_summary_blocks_check_prop_teleport_from_table_to_pocket(self):
        """Verify build qa summary blocks check prop teleport from table to pocket."""
        stage_outputs = {
            "05_plot_character_adaptation": {"event_pool": [{"id": 1, "target_block": 1}], "foreshadowing_pool": []},
            "06_script_outline_design": {
                    "block_state_plan": [{"block_id": 1}],
                    "event_release_schedule": [{"block_id": 1}],
                },
        }
        episodes = [
            {
                "episode_num": 1,
                "block_id": 1,
                "event_ids": [1],
                "conflict_mode": "pressure",
                "pattern_family": "pressure",
            },
            {
                "episode_num": 2,
                "block_id": 1,
                "event_ids": [1],
                "conflict_mode": "evidence",
                "pattern_family": "evidence",
            },
        ]
        final_scripts = [
            {
                "episode_num": 1,
                "final_script": "第一集\n\n1-1    刘波办公室    日    内\n出场人物：陈寻、刘波\n△合同和支票摆在桌上，没有人动。\n陈寻（起身）：我不签。",
            },
            {
                "episode_num": 2,
                "final_script": "第二集\n\n2-1    旧厂走廊    日    内\n出场人物：陈寻、刘波\n△陈寻从衣兜取出支票，塞回刘波手里。\n陈寻（看着刘波）：你留着。",
            },
        ]

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            episodes,
            target_episodes=2,
            derived_config={"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2},
            final_scripts=final_scripts,
            validation_mode="strict",
        )

        self.assertEqual(qa["check_results"]["completed_prop_continuity"], "BLOCK")
        prop_issue = next(item for item in qa["blocking_issues"] if item.get("check") == "completed_prop_continuity")
        self.assertTrue(
            any(item.get("issue") == "check_prop_teleports_from_table_to_pocket" for item in prop_issue["items"]),
        )

    def test_apply_report_only_issues_to_qa_summary_collect_mode_warns_episode_validation_errors(self):
        """Verify apply report only issues to qa summary collect mode warns episode validation errors."""
        qa = {
            "overall_status": "PASS",
            "generation_status": "PASS",
            "quality_status": "PASS",
            "validation_mode": "collect",
            "blocking_issues": [],
            "warnings": [],
            "check_results": {"forbidden_script_idioms": "PASS"},
        }
        report_only_issues = [
            {
                "stage": "08_script_body_generation",
                "artifact_id": "08_script_body_generation_ep001",
                "episode_num": 1,
                "errors": [{"check": "final_script_quality", "error": "missing cast member"}],
            }
        ]

        updated = pipeline_runner.apply_report_only_issues_to_qa_summary(qa, report_only_issues)

        self.assertEqual(updated["overall_status"], "PASS")
        self.assertEqual(updated["generation_status"], "PASS")
        self.assertEqual(updated["quality_status"], "WARN")
        self.assertEqual(updated["check_results"]["report_only_validation"], "WARN")
        self.assertFalse(updated["blocking_issues"])
        self.assertEqual(updated["warnings"][0]["check"], "report_only_validation")

    def test_apply_report_only_issues_to_qa_summary_strict_mode_blocks_episode_validation_errors(self):
        """Verify apply report only issues to qa summary strict mode blocks episode validation errors."""
        qa = {
            "overall_status": "PASS",
            "generation_status": "PASS",
            "quality_status": "PASS",
            "validation_mode": "strict",
            "blocking_issues": [],
            "warnings": [],
            "check_results": {"forbidden_script_idioms": "PASS"},
        }
        report_only_issues = [
            {
                "stage": "08_script_body_generation",
                "artifact_id": "08_script_body_generation_ep001",
                "episode_num": 1,
                "errors": [{"check": "final_script_quality", "error": "missing cast member"}],
            }
        ]

        updated = pipeline_runner.apply_report_only_issues_to_qa_summary(qa, report_only_issues)

        self.assertEqual(updated["overall_status"], "BLOCK")
        self.assertEqual(updated["generation_status"], "PASS")
        self.assertEqual(updated["quality_status"], "WARN")
        self.assertEqual(updated["check_results"]["report_only_validation"], "BLOCK")
        self.assertEqual(updated["blocking_issues"][0]["check"], "report_only_validation")

    def test_validation_check_report_only_defaults_to_collect_mode(self):
        """Verify validation check report only defaults to collect mode."""
        self.assertTrue(pipeline_runner.validation_check_is_report_only("final_script_quality"))
        self.assertTrue(pipeline_runner.validation_check_is_report_only("continuity_update_references"))
        self.assertFalse(pipeline_runner.validation_check_is_report_only("stage_output"))
        self.assertFalse(pipeline_runner.validation_check_is_report_only("stage_output", validation_mode="collect"))
        self.assertFalse(
            pipeline_runner.validation_check_is_report_only("final_script_quality", validation_mode="strict"),
        )
        self.assertFalse(pipeline_runner.validation_check_is_report_only("stage_output", report_only_validation=True))
        self.assertTrue(
            pipeline_runner.validation_check_is_report_only("final_script_quality", report_only_validation=True),
        )

    def test_parser_defaults_to_collect_validation_and_strict_flag(self):
        """Verify parser defaults to collect validation and strict flag."""
        parser = pipeline_runner.build_parser()

        default_args = parser.parse_args(["--novel", "docs/example.txt"])
        strict_args = parser.parse_args(["--novel", "docs/example.txt", "--strict-validation"])
        report_only_args = parser.parse_args(["--novel", "docs/example.txt", "--report-only-validation"])

        self.assertEqual(pipeline_runner.resolve_validation_mode(default_args), "collect")
        self.assertEqual(pipeline_runner.resolve_validation_mode(strict_args), "strict")
        self.assertEqual(pipeline_runner.resolve_validation_mode(report_only_args), "collect")

    def test_dodo_empty_json_traceback_is_transient(self):
        """Verify dodo empty json traceback is transient."""
        self.assertTrue(llm_client.is_transient_error("json.decoder.JSONDecodeError: Expecting value"))
        self.assertTrue(llm_client.is_transient_error("Error: empty response from Dodo API"))
        self.assertTrue(llm_client.is_transient_error("Error: non-JSON response from Dodo API"))

    def test_qa_blockers_are_report_only_only_distinguishes_hard_blockers(self):
        """Verify qa blockers are report only only distinguishes hard blockers."""
        self.assertTrue(
            pipeline_runner.qa_blockers_are_report_only_only(
                {"blocking_issues": [{"check": "report_only_validation", "items": []}]}
            )
        )
        self.assertFalse(
            pipeline_runner.qa_blockers_are_report_only_only(
                {
                    "blocking_issues": [
                        {"check": "report_only_validation", "items": []},
                        {"check": "event_window_mismatches", "items": []},
                    ]
                }
            )
        )

    def test_canonical_story_lock_includes_source_plot_point_characters(self):
        """Verify canonical story lock includes source plot point characters."""
        lock = pipeline_runner.build_canonical_story_lock(
            source_plot_points=[{"id": 1, "characters": ["沈念", "赵强"], "title": "拒写谅解书"}],
            character_bible=[{"name": "沈念", "role": "女主"}],
            novel_summary={"immutable_elements": []},
            adaptation_direction={"must_keep": [], "forbidden_changes": []},
        )

        self.assertIn("赵强", lock["character_names"])

    def test_invalidate_artifact_cache_removes_only_target_artifact(self):
        """Verify invalidate artifact cache removes only target artifact."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = pipeline_runner.RunPaths(
                root=root,
                prompts=root / "prompts",
                outputs=root / "outputs",
                parsed=root / "parsed",
                logs=root / "logs",
                manifests=root / "manifests",
                final=root / "final",
            )
            for folder in (paths.prompts, paths.outputs, paths.logs, paths.manifests):
                folder.mkdir(parents=True)
            target_files = [
                paths.prompts / "08_script_body_generation_ep018.prompt.md",
                paths.outputs / "08_script_body_generation_ep018.raw.md",
                paths.outputs / "08_script_body_generation_ep018.clean.json",
                paths.logs / "08_script_body_generation_ep018.log.json",
                paths.manifests / "08_script_body_generation_ep018.manifest.json",
            ]
            keep_file = paths.outputs / "08_script_body_generation_ep017.clean.json"
            for path in target_files + [keep_file]:
                path.write_text("x", encoding="utf-8")
            pipeline_runner.write_localization_report(
                paths,
                "08_script_body_generation_ep017",
                {"stage_id": "08_script_body_generation", "status": "PASS"},
            )
            pipeline_runner.write_localization_report(
                paths,
                "08_script_body_generation_ep018",
                {"stage_id": "08_script_body_generation", "status": "WARN"},
            )
            pipeline_runner.write_unmapped_fields_report(
                paths,
                artifact_id="08_script_body_generation_ep018",
                stage_id="08_script_body_generation",
                fields=[{"path": "08.extra", "key": "extra", "value": 1}],
            )
            pipeline_runner.write_normalization_report(
                paths,
                artifact_id="08_script_body_generation_ep018",
                stage_id="08_script_body_generation",
                report={"operation_count": 1, "changed_paths": ["final_script"]},
            )
            duplicate_report = paths.parsed / "localization_reports" / "08_script_body_generation_ep018 2.json"
            duplicate_report.write_text(
                (paths.parsed / "localization_reports" / "08_script_body_generation_ep018.json").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )
            self.assertEqual(pipeline_runner.refresh_localization_summary(paths)["total_artifacts"], 2)

            pipeline_runner.invalidate_artifact_cache(paths, "08_script_body_generation_ep018")

            self.assertTrue(keep_file.exists())
            self.assertFalse(any(path.exists() for path in target_files))
            self.assertFalse(
                (paths.parsed / "localization_reports" / "08_script_body_generation_ep018.json").exists()
            )
            self.assertFalse(
                (paths.parsed / "unmapped_fields" / "08_script_body_generation_ep018.json").exists()
            )
            self.assertFalse(
                (paths.parsed / "normalization_reports" / "08_script_body_generation_ep018.json").exists()
            )
            localization_summary = json.loads(
                (paths.parsed / "localization_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(localization_summary["total_artifacts"], 1)
            self.assertEqual(
                localization_summary["artifacts"][0]["artifact_id"],
                "08_script_body_generation_ep017",
            )

    def test_validate_final_script_quality_checks_length_scenes_and_names(self):
        """Verify validate final script quality checks length scenes and names."""
        script = (
            "第一集\n"
            "\n"
            "1-1    家中    夜    内\n"
            "出场人物：方华\n"
            "△方华看见花生酱，后退一步。\n"
            "方华（放下筷子）：我不吃。\n"
            "\n"
            "1-2    门口    夜    外\n"
            "出场人物：方华、方旭\n"
            "△方旭堵在门口，方华把碗放回桌面。\n"
            "方旭（伸手拦住）：你去哪？\n"
            "方华（拿起手机）：出去报警。"
        )
        episode = {"episode_num": 1, "required_character_names": ["方华", "方旭"]}
        lock = {"protagonist": "方华", "character_names": ["方华", "方旭"]}
        derived = {"script_length_chars": "20-200", "scenes_per_episode": "2-4"}

        validators.validate_final_script_quality(
            script,
            episode_outline=episode,
            canonical_story_lock=lock,
            derived_config=derived,
        )

        group_script = (
            "第三十五集\n"
            "\n"
            "35-1    村口    夜    外\n"
            "出场人物：沈念、民兵\n"
            "△沈念带着民兵赶到，手电照向门口。\n"
            "沈念（抬手）：先别进去。\n"
            "\n"
            "35-2    现场门口    夜    外\n"
            "出场人物：沈念、村民\n"
            "△村民举着手电筒围住现场，沈念把人拦在门外。\n"
            "村民（压低声音）：里面有人。"
        )
        validators.validate_final_script_quality(
            group_script,
            episode_outline={"episode_num": 35, "required_character_names": ["沈念", "民兵及村民"]},
            canonical_story_lock={"protagonist": "沈念", "character_names": ["沈念", "民兵及村民"]},
            derived_config=derived,
        )

        with self.assertRaisesRegex(ValueError, "missing required character"):
            validators.validate_final_script_quality(
                script.replace("方旭", "姜宝"),
                episode_outline=episode,
                canonical_story_lock=lock,
                derived_config=derived,
            )
        with self.assertRaisesRegex(ValueError, "forbidden cinematic"):
            validators.validate_final_script_quality(
                script + "\n[音效] 心跳声。",
                episode_outline=episode,
                canonical_story_lock=lock,
                derived_config={"script_length_chars": "20-300", "scenes_per_episode": "2-4"},
            )
        with self.assertRaisesRegex(ValueError, "forbidden cinematic"):
            validators.validate_final_script_quality(
                script + "\n方旭（画外音）：她回来了。",
                episode_outline=episode,
                canonical_story_lock=lock,
                derived_config={"script_length_chars": "20-300", "scenes_per_episode": "2-4"},
            )
        with self.assertRaisesRegex(ValueError, "forbidden cinematic"):
            validators.validate_final_script_quality(
                script + "\n方旭像被雷劈了一样站在门口。",
                episode_outline=episode,
                canonical_story_lock=lock,
                derived_config={"script_length_chars": "20-300", "scenes_per_episode": "2-4"},
            )

    def test_validate_final_script_quality_blocks_episode_word_caps(self):
        """Verify validate final script quality blocks episode word caps."""
        def script_with_length(episode_num: int, target_chars: int) -> str:
            """Handle script with length."""
            template = "\n".join(
                [
                    f"第{episode_num}集",
                    "",
                    f"{episode_num}-1    公司门口    日    外",
                    "出场人物：陈寻、吴经理",
                    "△陈寻站在门口，手里拿着被踢出群的手机。{filler}",
                    "陈寻（举起手机）：我先确认一件事。",
                    "",
                    f"{episode_num}-2    楼道    日    内",
                    "出场人物：陈寻、吴经理",
                    "△吴经理挡在楼道口，陈寻把合同文件夹夹在胳膊下。",
                    "吴经理（指着手机）：你已经不是公司的人。",
                ]
            )
            current = len(re.sub(r"\s+", "", template.format(filler="")))
            filler = "字" * max(0, target_chars - current)
            script = template.format(filler=filler)
            self.assertEqual(len(re.sub(r"\s+", "", script)), target_chars)
            return script

        lock = {"protagonist": "陈寻", "character_names": ["陈寻", "吴经理"]}
        derived = {"script_length_chars": "20-2000", "scenes_per_episode": "2-4"}

        validators.validate_final_script_quality(
            script_with_length(2, 950),
            episode_outline={"episode_num": 2, "required_character_names": ["陈寻", "吴经理"]},
            canonical_story_lock=lock,
            derived_config=derived,
        )

        with self.assertRaisesRegex(ValueError, r"episode 4 final_script word cap.*800"):
            validators.validate_final_script_quality(
                script_with_length(4, 801),
                episode_outline={"episode_num": 4, "required_character_names": ["陈寻", "吴经理"]},
                canonical_story_lock=lock,
                derived_config=derived,
            )

        with self.assertRaisesRegex(ValueError, r"episode 2 final_script word cap.*1000"):
            validators.validate_final_script_quality(
                script_with_length(2, 1001),
                episode_outline={"episode_num": 2, "required_character_names": ["陈寻", "吴经理"]},
                canonical_story_lock=lock,
                derived_config=derived,
            )

    def test_validate_final_script_quality_allows_below_pacing_target(self):
        """Verify validate final script quality allows below pacing target."""
        script = "\n".join(
            [
                "第四集",
                "",
                "4-1    公司前台    日    内",
                "出场人物：陈寻、吴经理",
                "△陈寻把文件夹放到前台桌面，吴经理站在门旁。",
                "陈寻（看着吴经理）：我只确认合同编号。",
                "",
                "4-2    公司走廊    日    内",
                "出场人物：陈寻、吴经理",
                "△吴经理挡住门，陈寻把文件夹合上。",
                "吴经理（伸手拦门）：你不能进去。",
            ]
        )
        validators.validate_final_script_quality(
            script,
            episode_outline={"episode_num": 4, "required_character_names": ["陈寻", "吴经理"]},
            canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理"]},
            derived_config={"script_length_chars": "600-800", "scenes_per_episode": "2-4"},
        )

    def test_validate_final_script_quality_allows_front_desk_area_as_location(self):
        """Verify validate final script quality allows front desk area as location."""
        script = "\n".join(
            [
                "第一集",
                "",
                "1-1    高铁站出站口    日    外",
                "出场人物：陈寻",
                "△陈寻拖着行李箱走出出站闸机。",
                "陈寻（看着手机）：我回来了。",
                "",
                "1-2    旧厂公司前台区    日    内",
                "出场人物：陈寻、吴经理、沈星",
                "△陈寻拉着行李箱推门进入，前台区几名员工抬头看了一眼，沈星站在靠墙位置。",
                "吴经理（迎上前）：陈寻，正好，省得我打电话了。",
            ]
        )

        validators.validate_final_script_quality(
            script,
            episode_outline={"episode_num": 1, "required_character_names": ["陈寻", "吴经理", "沈星"]},
            canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理", "沈星"]},
            derived_config={"script_length_chars": "20-1000", "scenes_per_episode": "2-4"},
        )

    def test_validate_final_script_quality_still_blocks_visible_front_desk_role(self):
        """Verify validate final script quality still blocks visible front desk role."""
        script = "\n".join(
            [
                "第一集",
                "",
                "1-1    公司前台区    日    内",
                "出场人物：陈寻、吴经理",
                "△陈寻推门进入，前台抬头看了他一眼。",
                "吴经理（迎上前）：你来了。",
                "",
                "1-2    公司走廊    日    内",
                "出场人物：陈寻、吴经理",
                "△吴经理挡在门口。",
                "陈寻（停步）：手续给我。",
            ]
        )

        with self.assertRaisesRegex(ValueError, r"missing cast member.*前台"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 1, "required_character_names": ["陈寻", "吴经理"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理"]},
                derived_config={"script_length_chars": "20-1000", "scenes_per_episode": "2-4"},
            )

    def test_validate_final_script_quality_allows_names_inside_screen_text(self):
        """Verify validate final script quality allows names inside screen text."""
        script = "\n".join(
            [
                "第一集",
                "",
                "1-1    酒店大堂    日    内",
                "出场人物：陈寻",
                "△手机屏幕显示：吴经理发送投票——「陈寻屡次出差未打卡，建议开除」。",
                "△头像列表逐一划过：吴经理、刘波、沈星……无一例外。",
                "陈寻（盯着屏幕）：全票。",
                "",
                "1-2    公司办公室    日    内",
                "出场人物：吴经理、刘波、沈星",
                "△吴经理站在白板前，刘波站在侧面，沈星低头看手机。",
                "吴经理（指向屏幕）：今天发邮件。",
            ]
        )

        validators.validate_final_script_quality(
            script,
            episode_outline={"episode_num": 1, "required_character_names": ["陈寻"]},
            canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理", "刘波", "沈星"]},
            derived_config={"script_length_chars": "20-1000", "scenes_per_episode": "2-4"},
        )

    def test_validate_final_script_quality_allows_screen_subject_name_without_cast(self):
        """Verify validate final script quality allows screen subject name without cast."""
        script = "\n".join(
            [
                "第一集",
                "",
                "1-1    公司工位区及电梯口    日    内",
                "出场人物：陈寻、吴经理",
                "△吴经理手机屏幕仍亮着，刘波发起投票的截图还停在页面上。",
                "陈寻（看着屏幕）：我拍下来了。",
            ]
        )

        validators.validate_final_script_quality(
            script,
            episode_outline={"episode_num": 1, "required_character_names": ["陈寻", "吴经理"]},
            canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理", "刘波"]},
            derived_config={"script_length_chars": "20-1000", "scenes_per_episode": "1-3"},
        )

    def test_validate_final_script_quality_blocks_forbidden_idioms(self):
        """Verify validate final script quality blocks forbidden idioms."""
        script = (
            "第一集\n"
            "\n"
            "1-1    公司门口    日    外\n"
            "出场人物：陈寻、吴经理\n"
            "△吴经理脸上闪过一丝得意，把手机举到陈寻面前。\n"
            "陈寻（看着手机）：你继续。\n"
            "\n"
            "1-2    楼道    日    内\n"
            "出场人物：陈寻、吴经理\n"
            "△陈寻把合同夹在胳膊下，吴经理伸手拦住门。\n"
            "吴经理（淡淡道）：你已经被开除了。"
        )

        with self.assertRaisesRegex(ValueError, r"forbidden script idiom.*闪过一丝"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 1, "required_character_names": ["陈寻", "吴经理"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理"]},
                derived_config={"script_length_chars": "20-400", "scenes_per_episode": "2-4"},
            )

    def test_validate_final_script_quality_blocks_nonvisual_stuck_speech(self):
        """Verify validate final script quality blocks nonvisual stuck speech."""
        script = (
            "第一集\n"
            "\n"
            "1-1    公司门口    日    外\n"
            "出场人物：陈寻、沈星\n"
            "△沈星张了张嘴，话卡在嗓子里。\n"
            "陈寻（看着沈星）：你说。\n"
            "\n"
            "1-2    楼道    日    内\n"
            "出场人物：陈寻、沈星\n"
            "△沈星低头后退半步。\n"
            "沈星（抬手）：我解释。"
        )

        with self.assertRaisesRegex(ValueError, r"forbidden script idiom.*话卡在嗓子里"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 1, "required_character_names": ["陈寻", "沈星"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "沈星"]},
                derived_config={"script_length_chars": "20-400", "scenes_per_episode": "2-4"},
            )

    def test_validate_final_script_quality_blocks_sms_subtitle(self):
        """Verify validate final script quality blocks sms subtitle."""
        script = (
            "第五集\n"
            "\n"
            "5-1    街边长椅    夜    外\n"
            "出场人物：陈寻\n"
            "△陈寻坐在长椅上，手机屏幕亮起。\n"
            "【字幕：吴经理：48小时内交回档案。】\n"
            "\n"
            "5-2    陈寻住处    夜    内\n"
            "出场人物：陈寻\n"
            "△陈寻推门进屋，把手机放到桌上。"
        )

        with self.assertRaisesRegex(ValueError, r"forbidden script idiom.*短信内容误用字幕"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 5, "required_character_names": ["陈寻"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理"]},
                derived_config={"script_length_chars": "20-400", "scenes_per_episode": "2-4"},
            )

    def test_collect_final_script_quality_errors_reports_multiple_same_episode_errors(self):
        """Verify collect final script quality errors reports multiple same episode errors."""
        script = "\n".join(
            [
                "第一集",
                "",
                "1-1    公司前台区    日    内",
                "出场人物：陈寻、吴经理",
                "△陈寻推门进入，前台抬头看了他一眼。",
                "【字幕：发起人：刘波】",
                "吴经理（低头，没有开口）：",
                "",
                "1-2    公司走廊    日    内",
                "出场人物：陈寻、吴经理",
                "△吴经理挡在门口。",
                "陈寻（停步）：手续给我。",
            ]
        )

        errors = validators.collect_final_script_quality_errors(
            script,
            episode_outline={"episode_num": 1, "required_character_names": ["陈寻", "吴经理"]},
            canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理"]},
            derived_config={"script_length_chars": "20-1000", "scenes_per_episode": "2-4"},
        )

        joined = "\n".join(errors)
        self.assertIn("短信内容误用字幕", joined)
        self.assertIn("dialogue text is empty", joined)
        self.assertIn("missing cast member(s): ['前台']", joined)

        with self.assertRaisesRegex(ValueError, r"短信内容误用字幕.*dialogue text is empty.*missing cast member"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 1, "required_character_names": ["陈寻", "吴经理"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理"]},
                derived_config={"script_length_chars": "20-1000", "scenes_per_episode": "2-4"},
            )

    def test_validate_final_script_quality_blocks_nonvisual_voice_tags(self):
        """Verify validate final script quality blocks nonvisual voice tags."""
        script = (
            "第一集\n"
            "\n"
            "1-1    公司门口    日    外\n"
            "出场人物：陈寻、吴经理\n"
            "△吴经理把协议推到陈寻面前。\n"
            "陈寻（沉声）：我需要看完整规定。\n"
            "\n"
            "1-2    楼道    日    内\n"
            "出场人物：陈寻、吴经理\n"
            "△陈寻合上文件夹，吴经理站在门口。\n"
            "吴经理（抬手拦住门）：你不能进去。"
        )

        with self.assertRaisesRegex(ValueError, r"forbidden script idiom.*非可视化声线标签"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 1, "required_character_names": ["陈寻", "吴经理"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理"]},
                derived_config={"script_length_chars": "20-400", "scenes_per_episode": "2-4"},
            )

        vo_script = (
            "第五集\n"
            "\n"
            "5-1    陈寻住处    夜    内\n"
            "出场人物：陈寻、王辉\n"
            "△陈寻接起电话，把手机放到桌面。\n"
            "王辉（VO，语气随意）：我这边随时。\n"
            "\n"
            "5-2    楼道    夜    内\n"
            "出场人物：陈寻\n"
            "△陈寻拿起外套走向门口。"
        )
        with self.assertRaisesRegex(ValueError, r"forbidden script idiom.*非可视化声线标签"):
            validators.validate_final_script_quality(
                vo_script,
                episode_outline={"episode_num": 5, "required_character_names": ["陈寻", "王辉"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "王辉"]},
                derived_config={"script_length_chars": "20-400", "scenes_per_episode": "2-4"},
            )

    def test_validate_final_script_quality_blocks_voice_volume_and_tone_tags(self):
        """Verify validate final script quality blocks voice volume and tone tags."""
        script = "第四集\n\n4-1    咖啡厅门口    日    外\n出场人物：陈寻、刘波\n△陈寻接起电话。\n刘波（VO，声调升高）：你现在在哪儿？\n陈寻（音量不低）：不用了。"

        with self.assertRaisesRegex(ValueError, r"forbidden script idiom.*非可视化声线标签"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 4, "required_character_names": ["陈寻", "刘波"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "刘波"]},
                derived_config={"script_length_chars": "20-400", "scenes_per_episode": "1-4"},
            )

    def test_validate_final_script_quality_blocks_bare_dialogue(self):
        """Verify validate final script quality blocks bare dialogue."""
        script = (
            "第一集\n"
            "\n"
            "1-1    公司门口    日    外\n"
            "出场人物：陈寻、吴经理\n"
            "△吴经理把协议推到陈寻面前。\n"
            "陈寻：我不签。\n"
            "\n"
            "1-2    楼道    日    内\n"
            "出场人物：陈寻、吴经理\n"
            "△陈寻合上文件夹，吴经理站在门口。\n"
            "吴经理（抬手拦住门）：你不能进去。"
        )

        with self.assertRaisesRegex(ValueError, r"dialogue missing action parentheses"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 1, "required_character_names": ["陈寻", "吴经理"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理"]},
                derived_config={"script_length_chars": "20-400", "scenes_per_episode": "2-4"},
            )

    def test_validate_final_script_quality_blocks_action_only_dialogue(self):
        """Verify validate final script quality blocks action only dialogue."""
        script = (
            "第一集\n"
            "\n"
            "1-1    公司门口    日    外\n"
            "出场人物：陈寻、吴经理\n"
            "△吴经理把协议推到陈寻面前。\n"
            "陈寻（看了吴经理一眼）：（转身走向门口）\n"
            "\n"
            "1-2    楼道    日    内\n"
            "出场人物：陈寻、吴经理\n"
            "△陈寻合上文件夹，吴经理站在门口。\n"
            "吴经理（抬手拦住门）：你不能进去。"
        )

        with self.assertRaisesRegex(ValueError, r"dialogue text is action-only"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 1, "required_character_names": ["陈寻", "吴经理"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理"]},
                derived_config={"script_length_chars": "20-400", "scenes_per_episode": "2-4"},
            )

    def test_validate_final_script_quality_blocks_empty_dialogue_line(self):
        """Verify validate final script quality blocks empty dialogue line."""
        script = (
            "第一集\n"
            "\n"
            "1-1    公司门口    日    外\n"
            "出场人物：陈寻、吴经理\n"
            "△吴经理把协议推到陈寻面前。\n"
            "陈寻（直接挂断电话）：\n"
            "\n"
            "1-2    楼道    日    内\n"
            "出场人物：陈寻、吴经理\n"
            "△陈寻合上文件夹，吴经理站在门口。\n"
            "吴经理（抬手拦住门）：你不能进去。"
        )

        with self.assertRaisesRegex(ValueError, r"dialogue text is empty"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 1, "required_character_names": ["陈寻", "吴经理"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理"]},
                derived_config={"script_length_chars": "20-400", "scenes_per_episode": "2-4"},
            )

    def test_validate_final_script_quality_blocks_other_location_action_inside_scene(self):
        """Verify validate final script quality blocks other location action inside scene."""
        script = (
            "第三集\n"
            "\n"
            "3-1    旧公司大楼门口    日    外\n"
            "出场人物：陈寻、刘波\n"
            "△陈寻站在门口，手机屏幕亮着。\n"
            "△刘波站在办公室窗边，盯着楼下的陈寻。\n"
            "刘波（VO）：你别闹。\n"
            "\n"
            "3-2    街边    日    外\n"
            "出场人物：陈寻\n"
            "△陈寻把手机放进口袋。"
        )

        with self.assertRaisesRegex(ValueError, r"location break"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 3, "required_character_names": ["陈寻", "刘波"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "刘波"]},
                derived_config={"script_length_chars": "20-500", "scenes_per_episode": "2-4"},
            )

    def test_validate_final_script_quality_allows_location_token_inside_document_object(self):
        """Verify validate final script quality allows location token inside document object."""
        script = "\n".join(
            [
                "第三集",
                "",
                "3-1    公司会议室    日    内",
                "出场人物：陈寻、刘波",
                "△陈寻拿起厂房合同递给刘波，合同封面夹着厂房平面图。",
                "刘波（翻开合同）：这份协议我第一次见。",
                "",
                "3-2    公司走廊    日    内",
                "出场人物：陈寻",
                "△陈寻把合同放进文件袋。",
            ]
        )

        validators.validate_final_script_quality(
            script,
            episode_outline={"episode_num": 3, "required_character_names": ["陈寻", "刘波"]},
            canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "刘波"]},
            derived_config={"script_length_chars": "20-800", "scenes_per_episode": "2-4"},
        )

    def test_normalize_script_scene_heading_expands_walk_out_from_meeting_room_path(self):
        """Verify normalize script scene heading expands walk out from meeting room path."""
        script = "\n".join(
            [
                "第一集",
                "",
                "1-1    公司前台及走廊及工位    日    内",
                "出场人物：陈寻、吴经理",
                "△吴经理从走廊尽头走出会议室，挡在陈寻面前。",
                "陈寻（看向吴经理）：你终于出来了。",
            ]
        )

        normalized = pipeline_runner.normalize_script_scene_heading_visible_space(script)

        self.assertIn("1-1    公司前台及走廊及工位及会议室外    日    内", normalized)

    def test_validate_final_script_quality_blocks_missing_background_visible_cast(self):
        """Verify validate final script quality blocks missing background visible cast."""
        script = "\n".join(
            [
                "第四集",
                "",
                "4-1    咖啡馆内    日    内",
                "出场人物：陈寻、刘波",
                "△赵敏端起咖啡杯，视线扫过这张桌子。",
                "陈寻（看向刘波）：你解释。",
            ]
        )

        with self.assertRaisesRegex(ValueError, r"missing cast member.*赵敏"):
            validators.validate_final_script_quality(
                script,
                episode_outline=(
                    {
                        "episode_num": 4,
                        "required_character_names": ["陈寻"],
                        "appearing_character_names": ["陈寻", "刘波", "赵敏"],
                    }
                ),
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "刘波", "赵敏"]},
                derived_config={"script_length_chars": "20-1000", "scenes_per_episode": "1-3"},
            )

    def test_validate_final_script_quality_blocks_visible_gaze_actor_missing_from_cast(self):
        """Verify validate final script quality blocks visible gaze actor missing from cast."""
        script = "\n".join(
            [
                "第五集",
                "",
                "5-1    咖啡馆内    日    内",
                "出场人物：陈寻、刘波",
                "△赵敏视线跟随陈寻背影到门口，将杯子放回桌面，没有起身。",
                "陈寻（看向刘波）：你解释。",
            ]
        )

        with self.assertRaisesRegex(ValueError, r"missing cast member.*赵敏"):
            validators.validate_final_script_quality(
                script,
                episode_outline=(
                    {
                        "episode_num": 5,
                        "required_character_names": ["陈寻"],
                        "appearing_character_names": ["陈寻", "刘波", "赵敏"],
                    }
                ),
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "刘波", "赵敏"]},
                derived_config={"script_length_chars": "20-1000", "scenes_per_episode": "1-3"},
            )

    def test_validate_final_script_quality_blocks_dialogue_with_triangle_prefix(self):
        """Verify validate final script quality blocks dialogue with triangle prefix."""
        script = "\n".join(
            [
                "第三集",
                "",
                "3-2    出租屋室内    日    内",
                "出场人物：陈寻、王辉",
                "△陈寻（点头）：好，我准时到。",
            ]
        )

        with self.assertRaisesRegex(ValueError, r"dialogue line must not start with △"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 3, "required_character_names": ["陈寻", "王辉"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "王辉"]},
                derived_config={"script_length_chars": "20-800", "scenes_per_episode": "1-3"},
            )

    def test_validate_final_script_quality_allows_directional_location_reference(self):
        """Verify validate final script quality allows directional location reference."""
        script = "\n".join(
            [
                "第一集",
                "",
                "1-1    公司大厅及前台区    日    内",
                "出场人物：陈寻、前台",
                "△前台没有抬头，只是用手指了指走廊方向。",
                "陈寻（看向前台）：吴经理在吗？",
            ]
        )

        validators.validate_final_script_quality(
            script,
            episode_outline={"episode_num": 1, "required_character_names": ["陈寻"]},
            canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻"]},
            derived_config={"script_length_chars": "20-500", "scenes_per_episode": "1-3"},
        )

    def test_validate_final_script_quality_blocks_filing_timeline_contradiction(self):
        """Verify validate final script quality blocks filing timeline contradiction."""
        script = (
            "第一集\n"
            "\n"
            "1-1    公司门口    日    外\n"
            "出场人物：陈寻、吴经理\n"
            "△吴经理把协议推到陈寻面前。\n"
            "陈寻（把手机放到桌上）：材料已经交律师备案了，备案今天完成。\n"
            "\n"
            "1-2    楼道    日    内\n"
            "出场人物：陈寻、吴经理\n"
            "△陈寻打开备案平台，点击上传。\n"
            "△手机屏幕弹出：「文件上传成功」。"
        )

        with self.assertRaisesRegex(ValueError, r"filing timeline contradiction"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 1, "required_character_names": ["陈寻", "吴经理"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理"]},
                derived_config={"script_length_chars": "20-400", "scenes_per_episode": "2-4"},
            )

    def test_validate_final_script_quality_blocks_phone_direction_contradiction(self):
        """Verify validate final script quality blocks phone direction contradiction."""
        script = (
            "第五集\n"
            "\n"
            "5-1    陈寻住处    夜    内\n"
            "出场人物：陈寻\n"
            "△陈寻手机屏幕显示：来电——吴经理。\n"
            "△陈寻看了一眼，将手机翻扣在桌面。\n"
            "\n"
            "5-2    旧厂办公室    夜    内\n"
            "出场人物：吴经理\n"
            "△吴经理手机屏幕显示：未接来电——陈寻。"
        )

        with self.assertRaisesRegex(ValueError, r"phone direction contradiction"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 5, "required_character_names": ["陈寻", "吴经理"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理"]},
                derived_config={"script_length_chars": "20-400", "scenes_per_episode": "2-4"},
            )

        display_script = (
            "第五集\n"
            "\n"
            "5-1    陈寻住处    夜    内\n"
            "出场人物：陈寻\n"
            "△陈寻手机屏幕显示：来电显示：吴经理。\n"
            "△陈寻看了一眼，按下拒接键，屏幕息屏。\n"
            "\n"
            "5-2    旧厂办公室    夜    内\n"
            "出场人物：吴经理\n"
            "△吴经理盯着手机屏幕：【未接来电：陈寻】。"
        )
        with self.assertRaisesRegex(ValueError, r"phone direction contradiction"):
            validators.validate_final_script_quality(
                display_script,
                episode_outline={"episode_num": 5, "required_character_names": ["陈寻", "吴经理"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理"]},
                derived_config={"script_length_chars": "20-400", "scenes_per_episode": "2-4"},
            )

    def test_validate_episode_narration_device_plan_blocks_budget_overuse(self):
        """Verify validate episode narration device plan blocks budget overuse."""
        episodes = [
            {
                "episode_num": 1,
                "narration_device_plan": {
                    "planned_os_count": 3,
                    "planned_flashback_count": 2,
                    "planned_vo_count": 0,
                    "reason": "前三集铺垫",
                    "visual_replacement_strategy": "用合同文件和电话录音替代解释",
                },
            },
            {
                "episode_num": 2,
                "narration_device_plan": {
                    "planned_os_count": 1,
                    "planned_flashback_count": 0,
                    "planned_vo_count": 0,
                    "reason": "补充主角判断",
                    "visual_replacement_strategy": "用对话追问替代",
                },
            },
        ]

        with self.assertRaisesRegex(ValueError, r"narration device budget.*OS\+flashback.*<= 5"):
            validators.validate_narration_device_plan_budget(episodes)

    def test_validate_episode_flashback_alignment_requires_approved_ids(self):
        """Verify validate episode flashback alignment requires approved ids."""
        flashback_screening = pipeline_runner.dry_run_payload("04a_flashback_screening", {})
        episodes = [
            {
                "episode_num": 1,
                "narration_device_plan": {
                    "planned_os_count": 0,
                    "planned_flashback_count": 1,
                    "planned_flashback_quota_count": 1,
                    "planned_vo_count": 0,
                    "reason": "需要闪回解释旧合同",
                    "visual_replacement_strategy": "无法用当下证据替代",
                    "approved_time_deviation_ids": [],
                },
            }
        ]

        with self.assertRaisesRegex(ValueError, r"planned flashback requires approved_time_deviation_ids"):
            validators.validate_episode_flashback_screening_alignment(
                episodes,
                flashback_screening=flashback_screening,
            )

    def test_validate_episode_flashback_alignment_blocks_unknown_and_rewrite_ids(self):
        """Verify validate episode flashback alignment blocks unknown and rewrite ids."""
        flashback_screening = pipeline_runner.dry_run_payload("04a_flashback_screening", {})
        flashback_screening["retained_time_deviations"] = [
            {
                "id": "td_a_001",
                "grade": "A",
                "position": "第1章",
                "characters": ["陈寻"],
                "content_summary": "旧合同真相",
                "q1_structure_necessity": "否",
                "q2_information_necessity": "是",
                "decision": "有条件保留",
                "reason": "反转必需",
                "quota_count": 1,
            }
        ]
        flashback_screening["rewrite_time_deviations"] = [
            {
                "id": "td_b_001",
                "grade": "B",
                "position": "第2章",
                "characters": ["陈寻"],
                "content_summary": "温情回忆",
                "q1_structure_necessity": "否",
                "q2_information_necessity": "否",
                "decision": "改写为顺叙",
                "reason": "仅渲染情绪",
                "quota_count": 0,
            }
        ]

        with self.assertRaisesRegex(ValueError, r"unknown approved_time_deviation_ids"):
            validators.validate_episode_flashback_screening_alignment(
                [
                    {
                        "episode_num": 1,
                        "narration_device_plan": {
                            "planned_os_count": 0,
                            "planned_flashback_count": 1,
                            "planned_flashback_quota_count": 1,
                            "planned_vo_count": 0,
                            "reason": "需要闪回",
                            "visual_replacement_strategy": "无法替代",
                            "approved_time_deviation_ids": ["td_missing"],
                        },
                    }
                ],
                flashback_screening=flashback_screening,
            )

        with self.assertRaisesRegex(ValueError, r"cannot reference B/C time deviation"):
            validators.validate_episode_flashback_screening_alignment(
                [
                    {
                        "episode_num": 2,
                        "narration_device_plan": {
                            "planned_os_count": 0,
                            "planned_flashback_count": 1,
                            "planned_flashback_quota_count": 1,
                            "planned_vo_count": 0,
                            "reason": "误用装饰级回忆",
                            "visual_replacement_strategy": "应改当下反应",
                            "approved_time_deviation_ids": ["td_b_001"],
                        },
                    }
                ],
                flashback_screening=flashback_screening,
            )

    def test_validate_episode_flashback_alignment_allows_a_grade_as_os_or_visualized(self):
        """Verify validate episode flashback alignment allows a grade as os or visualized."""
        flashback_screening = pipeline_runner.dry_run_payload("04a_flashback_screening", {})
        flashback_screening["retained_time_deviations"] = [
            {
                "id": "td_a_001",
                "grade": "A",
                "position": "第1章",
                "characters": ["陈寻"],
                "content_summary": "旧合同真相",
                "q1_structure_necessity": "否",
                "q2_information_necessity": "是",
                "decision": "可保留",
                "reason": "信息必要",
                "quota_count": 1,
            }
        ]
        episodes = [
            {
                "episode_num": 10,
                "narration_device_plan": {
                    "planned_os_count": 1,
                    "planned_flashback_count": 0,
                    "planned_flashback_quota_count": 0,
                    "planned_vo_count": 0,
                    "reason": "A 级旧事改成当下判断",
                    "visual_replacement_strategy": "用合同编号和一句OS承接旧信息",
                    "approved_flashback_time_deviation_ids": [],
                    "approved_os_time_deviation_ids": ["td_a_001"],
                    "visualized_time_deviation_ids": ["td_a_001"],
                    "deleted_or_rewritten_time_deviation_ids": [],
                },
            }
        ]

        validators.validate_episode_flashback_screening_alignment(episodes, flashback_screening=flashback_screening)

    def test_validate_episode_flashback_alignment_blocks_b_grade_in_flashback_field(self):
        """Verify validate episode flashback alignment blocks b grade in flashback field."""
        flashback_screening = pipeline_runner.dry_run_payload("04a_flashback_screening", {})
        flashback_screening["rewrite_time_deviations"] = [
            {
                "id": "td_b_001",
                "grade": "B",
                "position": "第2章",
                "characters": ["陈寻"],
                "content_summary": "装饰性回忆",
                "q1_structure_necessity": "否",
                "q2_information_necessity": "否",
                "decision": "改顺叙",
                "reason": "没有结构必要",
                "quota_count": 0,
            }
        ]

        with self.assertRaisesRegex(ValueError, r"cannot reference B/C time deviation"):
            validators.validate_episode_flashback_screening_alignment(
                [
                    {
                        "episode_num": 11,
                        "narration_device_plan": {
                            "planned_os_count": 0,
                            "planned_flashback_count": 1,
                            "planned_flashback_quota_count": 0,
                            "planned_vo_count": 0,
                            "reason": "误把B级写成闪回",
                            "visual_replacement_strategy": "应改成当下道具",
                            "approved_flashback_time_deviation_ids": ["td_b_001"],
                            "approved_os_time_deviation_ids": [],
                            "visualized_time_deviation_ids": [],
                            "deleted_or_rewritten_time_deviation_ids": [],
                        },
                    }
                ],
                flashback_screening=flashback_screening,
            )

    def test_validate_episode_flashback_alignment_allows_s_without_quota(self):
        """Verify validate episode flashback alignment allows s without quota."""
        flashback_screening = pipeline_runner.dry_run_payload("04a_flashback_screening", {})
        flashback_screening["retained_time_deviations"] = [
            {
                "id": "td_s_001",
                "grade": "S",
                "position": "第1章",
                "characters": ["陈寻"],
                "content_summary": "双时空结构",
                "q1_structure_necessity": "是",
                "q2_information_necessity": "是",
                "decision": "保留",
                "reason": "结构装置本身",
                "quota_count": 0,
            }
        ]
        episodes = [
            {
                "episode_num": 1,
                "narration_device_plan": {
                    "planned_os_count": 0,
                    "planned_flashback_count": 1,
                    "planned_flashback_quota_count": 0,
                    "planned_vo_count": 0,
                    "reason": "S级双时空结构",
                    "visual_replacement_strategy": "S级豁免，不转顺叙",
                    "approved_time_deviation_ids": ["td_s_001"],
                },
            }
        ]

        validators.validate_episode_flashback_screening_alignment(episodes, flashback_screening=flashback_screening)
        validators.validate_narration_device_plan_budget(episodes)

    def test_validate_final_script_quality_blocks_flashback_count_above_plan(self):
        """Verify validate final script quality blocks flashback count above plan."""
        script = (
            "第一集\n"
            "\n"
            "1-1    公司门口    日    外\n"
            "出场人物：陈寻、吴经理\n"
            "【闪回】\n"
            "△陈寻把合同递给客户。\n"
            "【闪出】\n"
            "【闪回】\n"
            "△客户在合同上签字。\n"
            "【闪出】\n"
            "陈寻（拿起手机）：现在说清楚。"
        )

        with self.assertRaisesRegex(ValueError, r"flashback_count=2>planned_flashback_count=1"):
            validators.validate_final_script_quality(
                script,
                episode_outline={
                    "episode_num": 1,
                    "required_character_names": ["陈寻", "吴经理"],
                    "narration_device_plan": {
                        "planned_os_count": 0,
                        "planned_flashback_count": 1,
                        "planned_flashback_quota_count": 1,
                        "planned_vo_count": 0,
                        "reason": "只允许一次闪回",
                        "visual_replacement_strategy": "第二段改当下证据",
                        "approved_time_deviation_ids": ["td_a_001"],
                    },
                    "scene_plan": [
                        {
                            "scene_no": 1,
                            "location": "公司门口",
                            "time": "日",
                            "space": "外",
                            "appearing_character_names": ["陈寻", "吴经理"],
                            "scene_purpose": "flashback",
                            "must_include_beats": ["合同来源"],
                            "scene_boundary_reason": "A 级闪回",
                        }
                    ],
                },
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理", "客户"]},
                derived_config={"script_length_chars": "20-400", "scenes_per_episode": "1-4"},
            )

    def test_count_narration_devices_counts_phone_vo_scene_once(self):
        """Verify count narration devices counts phone vo scene once."""
        script = "\n".join(
            [
                "第三集",
                "",
                "3-1    咖啡店    夜    内",
                "出场人物：陈寻、于涛",
                "△陈寻接起电话。",
                "于涛（VO）：你出来了？",
                "陈寻：出来了。",
                "于涛（VO）：明天见。",
                "",
                "3-2    公司门口    日    外",
                "出场人物：陈寻、王辉",
                "王辉（VO）：合同我看过了。",
            ]
        )

        usage = validators.count_narration_devices(script)

        self.assertEqual(usage["vo_count"], 3)

    def test_count_narration_devices_counts_vo_with_extra_parenthetical_text(self):
        """Verify count narration devices counts vo with extra parenthetical text."""
        script = "\n".join(
            [
                "第四集",
                "",
                "4-1    咖啡厅门口    日    外",
                "出场人物：陈寻、刘波",
                "刘波（VO，声调升高）：你现在在哪儿？",
                "陈寻（按掉电话）：不用了。",
            ]
        )

        usage = validators.count_narration_devices(script)

        self.assertEqual(usage["vo_count"], 1)

    def test_validate_final_script_quality_blocks_nonstandard_vo_parentheses(self):
        """Verify validate final script quality blocks nonstandard vo parentheses."""
        script = "第四集\n\n4-1    咖啡厅门口    日    外\n出场人物：陈寻、刘波\n△陈寻接起电话。\n刘波（VO，接通）：你现在在哪儿？"

        with self.assertRaisesRegex(ValueError, r"forbidden script idiom.*VO括号只能写VO"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 4, "required_character_names": ["陈寻", "刘波"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "刘波"]},
                derived_config={"script_length_chars": "20-400", "scenes_per_episode": "1-4"},
            )

    def test_validate_final_script_quality_blocks_usage_above_plan(self):
        """Verify validate final script quality blocks usage above plan."""
        script = (
            "第一集\n"
            "\n"
            "1-1    公司门口    日    外\n"
            "出场人物：陈寻、吴经理\n"
            "△陈寻盯着手机上的退群提示。\n"
            "陈寻（OS）：这家公司离开我的单子就撑不住。\n"
            "陈寻（看着屏幕）：我先打个电话。\n"
            "\n"
            "1-2    公司门口    日    外\n"
            "出场人物：陈寻、吴经理\n"
            "【闪回】\n"
            "△陈寻把合同文件推到客户面前。\n"
            "客户（点头）：这个单子只认你。\n"
            "【闪出】"
        )

        with self.assertRaisesRegex(ValueError, r"narration device usage exceeds episode plan"):
            validators.validate_final_script_quality(
                script,
                episode_outline={
                    "episode_num": 1,
                    "required_character_names": ["陈寻", "吴经理"],
                    "narration_device_plan": {
                        "planned_os_count": 0,
                        "planned_flashback_count": 0,
                        "planned_vo_count": 0,
                        "reason": "不用内心和闪回",
                        "visual_replacement_strategy": "用电话和文件交代",
                    },
                    "scene_plan": [
                        {
                            "scene_no": 1,
                            "location": "公司门口",
                            "time": "日",
                            "space": "外",
                            "appearing_character_names": ["陈寻", "吴经理"],
                            "scene_purpose": "pressure",
                            "must_include_beats": ["陈寻被踢出群"],
                            "scene_boundary_reason": "当下压力",
                        },
                        {
                            "scene_no": 2,
                            "location": "公司门口",
                            "time": "日",
                            "space": "外",
                            "appearing_character_names": ["陈寻", "吴经理"],
                            "scene_purpose": "flashback",
                            "must_include_beats": ["客户认陈寻"],
                            "scene_boundary_reason": "闪回解释合同来源",
                        },
                    ],
                },
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理", "客户"]},
                derived_config={"script_length_chars": "20-400", "scenes_per_episode": "2-4"},
            )

    def test_validate_final_script_quality_requires_scene_cast_lines_for_new_format(self):
        """Verify validate final script quality requires scene cast lines for new format."""
        script = (
            "第一集\n"
            "\n"
            "1-1    村口    日    外\n"
            "△沈念把手机放到桌上。\n"
            "沈念（抬头）：你继续说。\n"
            "\n"
            "1-2    门口    日    外\n"
            "出场人物：沈念、王桂兰\n"
            "△王桂兰堵住门口，沈念按下录音键。\n"
            "王桂兰（指着她）：你别跑。"
        )
        derived = {"script_length_chars": "20-200", "scenes_per_episode": "2-4"}

        with self.assertRaisesRegex(ValueError, r"scene 1-1 missing 出场人物"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 1, "required_character_names": ["沈念", "王桂兰"]},
                canonical_story_lock={"protagonist": "沈念", "character_names": ["沈念", "王桂兰"]},
                derived_config=derived,
            )

    def test_validate_final_script_quality_requires_cast_to_list_visible_or_speaking_roles(self):
        """Verify validate final script quality requires cast to list visible or speaking roles."""
        script = (
            "第五集\n"
            "\n"
            "5-1    陈寻住所楼下街道    日    外\n"
            "出场人物：陈寻\n"
            "△陈寻走出楼道，吴经理从另一栋楼门口快步走出，招手拦下一辆出租车。\n"
            "陈寻（上车）：高峰大厦。\n"
            "\n"
            "5-2    王辉办公室    日    内\n"
            "出场人物：陈寻、王辉\n"
            "△接线员拿起话筒，低声拨出一个号码。\n"
            "王辉（看向陈寻）：等你准备好。"
        )

        with self.assertRaisesRegex(ValueError, r"scene 5-1 missing cast member"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 5, "required_character_names": ["陈寻"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理", "王辉"]},
                derived_config={"script_length_chars": "20-800", "scenes_per_episode": "2-4"},
            )

    def test_validate_final_script_quality_detects_resting_visible_actor_missing_from_cast(self):
        """Verify validate final script quality detects resting visible actor missing from cast."""
        scripts = (
            "第一集\n1-1    ICU病房    日    内\n出场人物：爷爷\n△方华睁开眼睛，手指动了一下。",
            "第一集\n1-1    方家客厅    日    内\n出场人物：方华\n△客厅沙发上方旭半躺着，手机横在胸前。",
        )
        for script in scripts:
            with self.subTest(script=script), self.assertRaisesRegex(ValueError, r"missing cast member"):
                validators.validate_final_script_quality(
                    script,
                    episode_outline=(
                        {
                            "episode_num": 1,
                            "required_character_names": ["方华"],
                            "appearing_character_names": ["方华", "方旭", "爷爷"],
                        }
                    ),
                    canonical_story_lock={"protagonist": "方华", "character_names": ["方华", "方旭", "爷爷"]},
                    derived_config={"script_length_chars": "10-800", "scenes_per_episode": "1-3"},
                )

    def test_normalize_script_scene_cast_adds_generic_role_from_non_prefix_visible_action(self):
        """Verify normalize script scene cast adds generic role from non prefix visible action."""
        script = "\n".join(
            [
                "第五集",
                "",
                "5-1    王辉办公室    日    内",
                "出场人物：陈寻、王辉",
                "△陈寻看向桌边，助理把文件放到桌上后退到门边。",
                "王辉（看向陈寻）：等你准备好。",
            ]
        )

        normalized = pipeline_runner.normalize_script_scene_cast_from_visible_actions(script)

        self.assertIn("出场人物：陈寻、王辉、助理", normalized)

    def test_normalize_script_scene_cast_does_not_invent_action_fragments_as_people(self):
        """Verify normalize script scene cast does not invent action fragments as people."""
        script = "\n".join(
            [
                "第四集",
                "",
                "4-1    校园走廊    日    内",
                "出场人物：方华、林老师",
                "△她松开书包带，把录取通知放在桌上。",
                "△方华快步走到门口，方华的笔掉在地上。",
                "△震动从手机传来，清晨光线落在窗台，两人同时回头。",
                "林老师（按住通知）：你先去上课。",
            ]
        )

        normalized = pipeline_runner.normalize_script_scene_cast_from_visible_actions(
            script,
            allowed_character_names={"方华", "林老师", "爷爷"},
        )

        cast_line = next(line for line in normalized.splitlines() if line.startswith("出场人物："))
        for invalid in ("她松", "方华快步", "方华的笔", "震动", "清晨光线", "两人"):
            self.assertNotIn(invalid, cast_line)
        self.assertEqual(cast_line, "出场人物：方华、林老师")

    def test_default_script_density_uses_writing_target_not_relaxed_tolerance(self):
        """Verify default script density uses writing target not relaxed tolerance."""
        for episode_num in (1, 2, 3, 4, 40):
            with self.subTest(episode_num=episode_num):
                density = pipeline_runner.build_default_target_script_density(ep_num=episode_num)
                self.assertEqual(density["target_range_chars"], "650-780")
                self.assertEqual(density["minimum_effective_chars"], 650)
                self.assertEqual(density["maximum_chars"], 780)

    def test_normalize_script_scene_cast_trims_aspect_marker_after_name(self):
        """Verify normalize script scene cast trims aspect marker after name."""
        script = "\n".join(
            [
                "第一集",
                "",
                "1-1    公司大厅    日    内",
                "出场人物：陈寻、吴经理",
                "△吴经理已站在工位区中央，双手背在身后。",
                "吴经理（看向陈寻）：公司有个决议。",
            ]
        )

        normalized = pipeline_runner.normalize_script_scene_cast_from_visible_actions(script)

        self.assertIn("出场人物：陈寻、吴经理\n", normalized)
        self.assertNotIn("吴经理已", normalized.splitlines()[3])

    def test_validate_final_script_quality_requires_cast_for_retreating_visible_role(self):
        """Verify validate final script quality requires cast for retreating visible role."""
        script = (
            "第二集\n"
            "\n"
            "2-1    公司会议室    日    内\n"
            "出场人物：陈寻、吴经理\n"
            "△沈星已退到门口，背对会议室。\n"
            "吴经理（把文件推给陈寻）：签字。\n"
            "\n"
            "2-2    公司走廊    日    内\n"
            "出场人物：陈寻\n"
            "△陈寻走出会议室。"
        )

        with self.assertRaisesRegex(ValueError, r"missing cast member.*沈星"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 2, "required_character_names": ["陈寻", "吴经理"]},
                canonical_story_lock={"protagonist": "陈寻", "character_names": ["陈寻", "吴经理", "沈星"]},
                derived_config={"script_length_chars": "20-400", "scenes_per_episode": "2-4"},
            )

    def test_validate_episode_scene_plan_blocks_visible_doorway_exit_as_cast_change(self):
        """Verify validate episode scene plan blocks visible doorway exit as cast change."""
        episode = {
            "episode_num": 2,
            "scene_plan": [
                {
                    "scene_no": 1,
                    "location": "公司会议室",
                    "time": "日",
                    "space": "内",
                    "appearing_character_names": ["陈寻", "吴经理", "沈星"],
                    "scene_purpose": "查看投票名单",
                    "must_include_beats": ["沈星站在门边"],
                    "scene_boundary_reason": "核心揭示场",
                },
                {
                    "scene_no": 2,
                    "location": "公司会议室",
                    "time": "日",
                    "space": "内",
                    "appearing_character_names": ["陈寻", "吴经理"],
                    "scene_purpose": "签署离职文件",
                    "must_include_beats": ["沈星退至门口，陈寻签字"],
                    "scene_boundary_reason": "沈星退至门口，人物构成发生变化",
                },
            ],
        }

        with self.assertRaisesRegex(ValueError, r"removes visible doorway cast"):
            validators.validate_episode_scene_plan_boundaries(episode)

    def test_validate_final_script_quality_rejects_same_setting_same_cast_adjacent_scene(self):
        """Verify validate final script quality rejects same setting same cast adjacent scene."""
        script = (
            "第一集\n"
            "\n"
            "1-1    村口大树下    日    外\n"
            "出场人物：沈念、王桂兰、大妈们\n"
            "△沈念把手机放到石桌上，王桂兰伸手去挡。\n"
            "沈念（抬手避开）：你早上出门的时候，嘴上是抹了开塞露吗？\n"
            "\n"
            "1-2    村口大树下    日    外\n"
            "出场人物：沈念、王桂兰、大妈们\n"
            "△大妈们停下嗑瓜子，王桂兰站在原地没动。\n"
            "王桂兰（瞪着她）：你敢骂我？\n"
            "沈念（看着手机）：我只是在复述你刚才的话。"
        )

        with self.assertRaisesRegex(ValueError, r"adjacent scenes 1-1 and 1-2 repeat same setting and cast"):
            validators.validate_final_script_quality(
                script,
                episode_outline={"episode_num": 1, "required_character_names": ["沈念", "王桂兰"]},
                canonical_story_lock={"protagonist": "沈念", "character_names": ["沈念", "王桂兰", "大妈们"]},
                derived_config={"script_length_chars": "20-400", "scenes_per_episode": "2-4"},
            )

    def test_validate_final_script_quality_allows_flashback_boundary(self):
        """Verify validate final script quality allows flashback boundary."""
        script = (
            "第一集\n"
            "\n"
            "1-1    村口大树下    日    外\n"
            "出场人物：沈念、王桂兰\n"
            "△沈念把手机放到石桌上，王桂兰伸手去挡。\n"
            "沈念（抬手避开）：你刚才的话，我录下来了。\n"
            "\n"
            "1-2    村口大树下    日    外\n"
            "出场人物：沈念、王桂兰\n"
            "【闪回】\n"
            "△王桂兰站在同一棵树下，把话重复给围观的人听。\n"
            "王桂兰（压低声音）：她在城里做什么，你们懂。\n"
            "【闪回结束】"
        )

        validators.validate_final_script_quality(
            script,
            episode_outline={"episode_num": 1, "required_character_names": ["沈念", "王桂兰"]},
            canonical_story_lock={"protagonist": "沈念", "character_names": ["沈念", "王桂兰"]},
            derived_config={"script_length_chars": "20-400", "scenes_per_episode": "2-4"},
        )

    def test_validate_final_script_quality_allows_real_location_or_cast_change(self):
        """Verify validate final script quality allows real location or cast change."""
        script = (
            "第一集\n"
            "\n"
            "1-1    村口大树下    日    外\n"
            "出场人物：沈念、王桂兰、大妈们\n"
            "△沈念把手机放到石桌上，王桂兰伸手去挡。\n"
            "沈念（抬手避开）：你继续说。\n"
            "\n"
            "1-2    村委会门口    日    外\n"
            "出场人物：沈念、王桂兰、村干部\n"
            "△村干部走到门口，沈念把录音文件名亮给他看。\n"
            "村干部（看向王桂兰）：这话是谁传的？"
        )

        validators.validate_final_script_quality(
            script,
            episode_outline={"episode_num": 1, "required_character_names": ["沈念", "王桂兰"]},
            canonical_story_lock={"protagonist": "沈念", "character_names": ["沈念", "王桂兰", "村干部", "大妈们"]},
            derived_config={"script_length_chars": "20-400", "scenes_per_episode": "2-4"},
        )

    def test_build_episode_outlines_includes_scene_plan(self):
        """Verify build episode outlines includes scene plan."""
        outlines = pipeline_runner.build_episode_outlines(
            40,
            canonical_story_lock={"protagonist": "沈念", "character_names": ["沈念", "王桂兰"]},
        )

        scene_plan = outlines[0].get("scene_plan")
        self.assertIsInstance(scene_plan, list)
        self.assertTrue(scene_plan)
        for key in (
            "scene_no",
            "location",
            "time",
            "space",
            "appearing_character_names",
            "scene_purpose",
            "must_include_beats",
            "scene_boundary_reason",
        ):
            self.assertIn(key, scene_plan[0])

        narration_plan = outlines[0].get("narration_device_plan")
        self.assertIsInstance(narration_plan, dict)
        for key in (
            "planned_os_count",
            "planned_flashback_count",
            "planned_vo_count",
            "reason",
            "visual_replacement_strategy",
        ):
            self.assertIn(key, narration_plan)

    def test_clip_blocks_for_episode_limit_trims_partial_generation(self):
        """Verify clip blocks for episode limit trims partial generation."""
        blocks = pipeline_runner.build_longform_blocks(40)

        clipped = pipeline_runner.clip_blocks_for_episode_limit(blocks, 5)

        self.assertEqual(len(clipped), 1)
        self.assertEqual(clipped[0]["start_episode"], 1)
        self.assertEqual(clipped[0]["end_episode"], 5)
        self.assertEqual(clipped[0]["episode_count"], 5)

    def test_episode_planning_chunks_partial_block_into_single_episode_calls(self):
        """Verify episode planning chunks partial block into single episode calls."""
        blocks = pipeline_runner.build_longform_blocks(40)
        clipped = pipeline_runner.clip_blocks_for_episode_limit(blocks, 5)

        chunks = pipeline_runner.split_blocks_for_episode_chunks(clipped, max_episodes_per_chunk=1)

        self.assertEqual(len(chunks), 5)
        self.assertEqual(
            [(item["start_episode"], item["end_episode"], item["episode_count"]) for item in chunks],
            [(1, 1, 1), (2, 2, 1), (3, 3, 1), (4, 4, 1), (5, 5, 1)],
        )
        self.assertEqual([item["_source_block_id"] for item in chunks], [1, 1, 1, 1, 1])
        self.assertEqual([item["_chunk_index"] for item in chunks], [1, 2, 3, 4, 5])

    def test_episode_planning_chunk_artifact_ids_include_episode_range(self):
        """Verify episode planning chunk artifact ids include episode range."""
        block = {
            "block_id": 1,
            "start_episode": 3,
            "end_episode": 3,
            "episode_count": 1,
            "_source_block_id": 1,
            "_chunk_index": 3,
            "_chunk_count": 5,
        }

        artifact_id = pipeline_runner.episode_planning_block_artifact_id(block)

        self.assertEqual(artifact_id, "07_episode_planning.block_01_ep003_003")

    def test_validate_final_script_quality_accepts_new_episode_scene_format(self):
        """Verify validate final script quality accepts new episode scene format."""
        script = "\n".join(
            [
                "第一集",
                "",
                "1-1    餐厅    夜    内",
                "出场人物：方华、爷爷",
                "△方华把花生酱推到桌边，爷爷按住碗沿。",
                "方华（盯着碗）：我不吃。",
                "爷爷（皱眉，OS）：她今天不对劲。",
                "",
                "1-2    门口    夜    内",
                "出场人物：方华、爷爷",
                "△方华拿起手机，屏幕上停着录音文件。",
                "爷爷（伸手）：你要拿这个吓唬谁？",
                "方华（后退一步）：我只让大家听原话，（VO）证据从这一刻开始留好。",
                "方华（按下播放）：你刚才说的话，都在这里（特写）。",
                "△VO同时与画面进行：手机屏幕显示录音时长继续增加。",
                "【字幕：录音保存成功】",
            ]
        )
        episode = {"episode_num": 1, "required_character_names": ["方华", "爷爷"]}
        lock = {"protagonist": "方华", "character_names": ["方华", "爷爷"]}
        derived = {"script_length_chars": "20-400", "scenes_per_episode": "2-4"}

        validators.validate_final_script_quality(
            script,
            episode_outline=episode,
            canonical_story_lock=lock,
            derived_config=derived,
        )

    def test_validate_final_script_quality_treats_boundary_and_content_harm_as_warning_surface(self):
        """Verify validate final script quality treats boundary and content harm as warning surface."""
        episode = {"episode_num": 36, "required_character_names": ["沈念"]}
        lock = {"protagonist": "沈念", "character_names": ["沈念", "王桂兰", "刘大勇"]}
        derived = {"script_length_chars": "20-400", "scenes_per_episode": "2-4"}
        script = (
            "第三十六集\n"
            "\n"
            "36-1    东屋    夜    内\n"
            "出场人物：沈念、刘大勇、王桂兰\n"
            "△沈念站在门边，手机屏幕停在监控回放列表。\n"
            "沈念（按住手机）：这段不能公开播。\n"
            "\n"
            "36-2    院门    夜    外\n"
            "出场人物：沈念、村民\n"
            "△村民围在院门外，沈念把手机收进口袋。\n"
            "沈念（拦住众人）：人先别进去，等处理。"
        )
        output = {"continuity_update": {"boundary_risk": "high"}}

        validators.validate_final_script_quality(
            script,
            episode_outline=episode,
            canonical_story_lock=lock,
            derived_config=derived,
            stage_output=output,
        )

    def test_export_stage_table_writes_chinese_headers(self):
        """Verify export stage table writes chinese headers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "stages.csv"

            rows = export_stage_table.export_stage_table(output)

            self.assertEqual(len(rows), 13)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertIn("环节ID", reader.fieldnames)
                self.assertIn("输入输出映射关系", reader.fieldnames)

    def test_dry_run_creates_manifest_and_final_summary(self):
        """Verify dry run creates manifest and final summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            novel = PROJECT_ROOT / "docs" / "固执爷爷听不懂人话.txt"

            pipeline_runner.main(
                [
                    "--novel",
                    str(novel),
                    "--run-id",
                    "dryrun_test",
                    "--runs-dir",
                    str(runs_dir),
                    "--target-episodes",
                    "80",
                    "--generate-episodes",
                    "1",
                    "--dry-run",
                ]
            )

            root = runs_dir / "dryrun_test"
            self.assertFalse((root / "manifests" / "00a_global_config.manifest.json").exists())
            self.assertTrue((root / "manifests" / "01_novel_summary.manifest.json").exists())
            self.assertTrue((root / "manifests" / "08_script_body_generation_ep001.manifest.json").exists())
            self.assertTrue((root / "final" / "run_summary.json").exists())
            self.assertTrue((root / "final" / "qa_summary.json").exists())
            summary = json.loads((root / "final" / "run_summary.json").read_text(encoding="utf-8"))
            self.assertTrue(summary["dry_run"])
            self.assertEqual(summary["target_episodes"], 80)
            resolution = json.loads((root / "parsed" / "00a_global_config_resolution.json").read_text(encoding="utf-8"))
            self.assertEqual(resolution["source"], "user_overrides")
            self.assertEqual(resolution["resolved_run_config"]["target_episodes"], 80)
            summary_prompt = (root / "prompts" / "01_novel_summary.prompt.md").read_text(encoding="utf-8")
            self.assertIn("改编为80集短漫剧", summary_prompt)
            self.assertNotIn("40-100集", summary_prompt)
            qa_summary = json.loads((root / "final" / "qa_summary.json").read_text(encoding="utf-8"))
            self.assertTrue(qa_summary["episode_continuity"]["numbering_continuous"])
            self.assertEqual(qa_summary["release_status"], "PASS")
            self.assertEqual(summary["release_status"], "PASS")
            transaction_schedule = json.loads(
                (root / "parsed" / "05_transaction_schedule.json").read_text(encoding="utf-8")
            )
            self.assertEqual(transaction_schedule["status"], "PASS")
            ownership_report = json.loads(
                (root / "parsed" / "07_transaction_ownership_report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(ownership_report["status"], "PASS")
            self.assertTrue((root / "final" / "release_preflight.json").exists())
            self.assertTrue((root / "parsed" / "08_proposed_delta_ep001.json").exists())
            episode_outlines = json.loads((root / "parsed" / "07_episode_outlines.json").read_text(encoding="utf-8"))
            self.assertEqual(len(episode_outlines), 1)
            self.assertEqual([item["episode_num"] for item in episode_outlines], [1])
            self.assertIn("event_ids", episode_outlines[0])
            self.assertIn("required_character_names", episode_outlines[0])
            self.assertTrue((root / "manifests" / "07_episode_planning.block_01_ep001_001.manifest.json").exists())
            self.assertTrue((root / "outputs" / "07_episode_planning.merge.json").exists())
            stage07 = json.loads((root / "outputs" / "07_episode_planning.clean.json").read_text(encoding="utf-8"))
            self.assertEqual(set(stage07.keys()), {"episode_allocation", "block_plans", "episode_outlines"})
            self.assertTrue((root / "parsed" / "localization_summary.json").exists())
            self.assertTrue((root / "parsed" / "localization_reports" / "01_novel_summary.json").exists())
            ascii_json_keys = {
                key
                for prompt_path in (root / "prompts").glob("*.prompt.md")
                for key in re.findall(
                    r'^\s*"([a-z_][a-z0-9_]*)"\s*:',
                    prompt_path.read_text(encoding="utf-8"),
                    flags=re.M,
                )
            }
            self.assertEqual(ascii_json_keys, set())
            clean_files_with_repair_traces = [
                path.name
                for path in (root / "outputs").glob("*.clean.json")
                if "_repair_trace" in path.read_text(encoding="utf-8")
            ]
            self.assertEqual(clean_files_with_repair_traces, [])
            self.assertTrue((root / "readable_outputs" / "index.md").exists())
            self.assertTrue((root / "readable_outputs" / "parse_report.json").exists())

    def test_dry_run_no_render_clean_md_flag_skips_readable_outputs(self):
        """Verify dry run no render clean md flag skips readable outputs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            novel = PROJECT_ROOT / "docs" / "固执爷爷听不懂人话.txt"

            pipeline_runner.main(
                [
                    "--novel",
                    str(novel),
                    "--run-id",
                    "dryrun_no_readable_test",
                    "--runs-dir",
                    str(runs_dir),
                    "--target-episodes",
                    "40",
                    "--generate-episodes",
                    "1",
                    "--dry-run",
                    "--no-render-clean-md",
                ]
            )

            root = runs_dir / "dryrun_no_readable_test"
            self.assertFalse((root / "readable_outputs").exists())

    def test_dry_run_render_clean_md_flag_generates_readable_outputs(self):
        """Verify dry run render clean md flag generates readable outputs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "runs"
            novel = PROJECT_ROOT / "docs" / "固执爷爷听不懂人话.txt"

            pipeline_runner.main(
                [
                    "--novel",
                    str(novel),
                    "--run-id",
                    "dryrun_readable_test",
                    "--runs-dir",
                    str(runs_dir),
                    "--target-episodes",
                    "40",
                    "--generate-episodes",
                    "1",
                    "--dry-run",
                    "--render-clean-md",
                ]
            )

            root = runs_dir / "dryrun_readable_test"
            readable = root / "readable_outputs"
            self.assertTrue((readable / "index.md").exists())
            self.assertTrue((readable / "parse_report.json").exists())
            self.assertTrue((readable / "parse_report.md").exists())
            self.assertTrue((readable / "01_novel_summary.md").exists())
            self.assertTrue((readable / "08_script_body_generation_ep001.md").exists())
            novel_summary_md = (readable / "01_novel_summary.md").read_text(encoding="utf-8")
            self.assertFalse(novel_summary_md.startswith("# 原著摘要"))
            self.assertNotIn("生成时间", novel_summary_md)
            report = json.loads((readable / "parse_report.json").read_text(encoding="utf-8"))
            self.assertGreaterEqual(report["total_clean_json_files"], 9)
            self.assertIn("01_novel_summary.clean.json", report["field_coverage_by_file"])
            self.assertEqual(
                report["field_coverage_by_file"]["01_novel_summary.clean.json"]["coverage_status"],
                "PASS",
            )

    def test_longform_dry_run_payloads_have_required_schema(self):
        """Verify longform dry run payloads have required schema."""
        stage04a = pipeline_runner.dry_run_payload("04a_flashback_screening", {})
        for key in (
            "flashback_overview",
            "retained_time_deviations",
            "rewrite_time_deviations",
            "deleted_time_deviations",
            "quota_policy",
        ):
            self.assertIn(key, stage04a)

        stage05 = pipeline_runner.dry_run_payload(
            "05_plot_character_adaptation",
            {
                "target_episodes": 80,
                "derived_config": pipeline_runner.derive_run_config(
                    pipeline_runner.merge_run_config(
                        pipeline_runner.DEFAULT_RUN_CONFIG,
                        {"target_episodes": 80},
                    )
                ),
            },
        )
        for key in ("macro_arcs", "event_pool", "conflict_engine", "expanded_character_network", "foreshadowing_pool"):
            self.assertIn(key, stage05)
        self.assertGreaterEqual(len(stage05["macro_arcs"]), 6)
        self.assertGreaterEqual(len(stage05["event_pool"]), 20)

        stage07 = pipeline_runner.dry_run_payload("07_episode_planning", {"target_episodes": 80})
        for key in ("episode_allocation", "block_plans", "episode_outlines"):
            self.assertIn(key, stage07)
        self.assertEqual(len(stage07["episode_outlines"]), 80)

        stage08 = pipeline_runner.dry_run_payload(
            "08_script_body_generation",
            {"episode_outline": {"episode_num": 1, "title": "第1集"}},
        )
        for key in ("final_script", "state_update", "continuity_update"):
            self.assertIn(key, stage08)

    def test_dry_run_payloads_do_not_leak_fixed_fixture_terms(self):
        """Verify dry run payloads do not leak fixed fixture terms."""
        payload = {
            "stage01": pipeline_runner.dry_run_payload("01_novel_summary", {}),
            "blocks": pipeline_runner.build_longform_blocks(40),
            "episodes": pipeline_runner.build_episode_outlines(40),
        }
        text = json.dumps(payload, ensure_ascii=False)
        for forbidden in ("方华", "方旭", "张晓霞", "花生酱", "高考", "清北", "爷爷"):
            self.assertNotIn(forbidden, text)

    def test_normalize_stage_output_promotes_nested_chapter_key_events(self):
        """Verify normalize stage output promotes nested chapter key events."""
        normalized = pipeline_runner.normalize_stage_output(
            "01_novel_summary",
            {
                "chapter_summaries": [
                    {"chapter_id": 1, "key_events": [{"id": "1-1", "event": "村口造谣"}]},
                    {"chapter_id": 2, "key_events": [{"id": "2-1", "event": "主角留证"}]},
                ]
            },
        )

        self.assertEqual([item["id"] for item in normalized["key_events"]], ["1-1", "2-1"])

    def test_normalize_stage_output_preserves_event_meta_language(self):
        """Verify normalize stage output preserves event meta language."""
        normalized = pipeline_runner.normalize_stage_output(
            "05_plot_character_adaptation",
            {
                "event_pool": [
                    {
                        "id": 13,
                        "title": "删除性侵高潮",
                        "source_anchor": "源故事中的强暴与乱伦丑态",
                        "delta_from_source": "删除性侵过程并交给警方",
                        "child_beats": ["强奸未遂仍在child beat里应由validator继续拦截"],
                    }
                ]
            },
        )
        event = normalized["event_pool"][0]

        self.assertEqual(event["title"], "删除性侵高潮")
        self.assertEqual(event["source_anchor"], "源故事中的强暴与乱伦丑态")
        self.assertEqual(event["child_beats"][0]["action"], "强奸未遂仍在child beat里应由validator继续拦截")
        self.assertNotIn("safety_rewrite_trace", event)

    def test_normalize_stage_output_preserves_induced_trap_event_boundary(self):
        """Verify normalize stage output preserves induced trap event boundary."""
        normalized = pipeline_runner.normalize_stage_output(
            "05_plot_character_adaptation",
            {
                "event_pool": [
                    {
                        "id": 10,
                        "title": "截获买凶险恶图谋",
                        "function": "危机预警/揭露阴谋",
                        "source_plot_point_ids": [6],
                        "expansion_type": "new_bridge",
                        "target_block": 3,
                        "episode_window": {"start": 24, "end": 26},
                        "not_before_episode": 23,
                        "not_after_episode": 28,
                        "expected_episode_span": 3,
                        "importance_level": "A",
                        "conflict_mode": "secret_discovery",
                        "pattern_family": "pressure_escalation",
                        "source_anchor": "王桂兰买通刘大勇让其去东屋施暴",
                        "delta_from_source": "主角提前截获犯罪密谋。",
                        "legal_moral_risk": "low",
                        "content_sensitivity_risk": "low",
                        "child_beats": ["沈念不退反进，决定利用这个阴谋将他们彻底送入地狱。"],
                    }
                ]
            },
        )
        event = normalized["event_pool"][0]

        self.assertEqual(event["source_anchor"], "王桂兰买通刘大勇让其去东屋施暴")
        self.assertIn("送入地狱", event["child_beats"][0]["action"])
        self.assertEqual(event["legal_moral_risk"], "low")
        self.assertEqual(event["content_sensitivity_risk"], "low")
        self.assertNotIn("safety_rewrite_trace", event)
        validators.validate_event_pool_contract([event], derived_config={"event_pool_size": "1-1"})

    def test_cache_manifest_must_match_dry_run_prompt_and_inputs(self):
        """Verify cache manifest must match dry run prompt and inputs."""
        prompt = "任务：{title}"
        values = {"title": "测试"}
        rendered = prompt_renderer.render_template(prompt, values)
        stage = {
            "stage_id": "01_novel_summary",
            "stage_name": "小说梳理",
            "prompt_file": "prompts/clean/01_小说梳理_novel_summary.md",
        }
        manifest = {
            "dry_run": True,
            "prompt_sha256": pipeline_runner.sha256_text(rendered),
            "input_value_hashes": {
                    key: pipeline_runner.sha256_text(prompt_renderer.stringify(value))
                    for key, value in values.items()
                },
            "runner_sha256": "stale-runner-hash",
            "stage_behavior_sha256": pipeline_runner.stage_behavior_sha256(stage),
            "llm_runtime_options": {},
            "llm_script": "",
        }

        self.assertTrue(
            pipeline_runner.cached_artifact_matches(
                manifest,
                dry_run=True,
                prompt=rendered,
                values=values,
                llm_script_path=None,
                stage=stage,
            ),
        )
        self.assertFalse(
            pipeline_runner.cached_artifact_matches(
                manifest,
                dry_run=False,
                prompt=rendered,
                values=values,
                llm_script_path=Path("/tmp/model.sh"),
                stage=stage,
            )
        )

    def test_cache_manifest_rejects_legacy_runner_hash_without_stage_behavior(self):
        """Verify cache manifest rejects legacy runner hash without stage behavior."""
        prompt = "任务：{title}"
        values = {"title": "测试"}
        rendered = prompt_renderer.render_template(prompt, values)
        stage = {
            "stage_id": "03_plot_character_extract",
            "stage_name": "情节人物提取",
            "prompt_file": "prompts/clean/03_情节人物提取_plot_character_extract.md",
        }
        legacy_manifest = {
            "dry_run": True,
            "prompt_sha256": pipeline_runner.sha256_text(rendered),
            "input_value_hashes": {
                    key: pipeline_runner.sha256_text(prompt_renderer.stringify(value))
                    for key, value in values.items()
                },
            "runner_sha256": "legacy-runner-hash",
            "llm_runtime_options": {},
            "llm_script": "",
        }

        self.assertFalse(
            pipeline_runner.cached_artifact_matches(
                legacy_manifest,
                dry_run=True,
                prompt=rendered,
                values=values,
                llm_script_path=None,
                stage=stage,
            )
        )

    def test_cache_manifest_checks_llm_script_and_output_hash(self):
        """Verify cache manifest checks llm script and output hash."""
        prompt = "任务：{title}"
        values = {"title": "测试"}
        rendered = prompt_renderer.render_template(prompt, values)
        stage = {
            "stage_id": "01_novel_summary",
            "stage_name": "小说梳理",
            "prompt_file": "prompts/clean/01_小说梳理_novel_summary.md",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            script = root / "model.sh"
            output = root / "stage.clean.json"
            script.write_text("#!/bin/sh\necho one\n", encoding="utf-8")
            output.write_text(json.dumps({"ok": True}, ensure_ascii=False, indent=2), encoding="utf-8")
            manifest = {
                "dry_run": False,
                "prompt_sha256": pipeline_runner.sha256_text(rendered),
                "input_value_hashes": {
                        key: pipeline_runner.sha256_text(prompt_renderer.stringify(value))
                        for key, value in values.items()
                    },
                "runner_sha256": "stale-runner-hash",
                "stage_behavior_sha256": pipeline_runner.stage_behavior_sha256(stage),
                "llm_runtime_options": {},
                "llm_script": str(script),
                "llm_script_sha256": pipeline_runner.file_sha256(script),
                "output_sha256": pipeline_runner.clean_json_artifact_sha256(output),
            }

            self.assertTrue(
                pipeline_runner.cached_artifact_matches(
                    manifest,
                    dry_run=False,
                    prompt=rendered,
                    values=values,
                    llm_script_path=script,
                    output_path=output,
                    stage=stage,
                )
            )
            script.write_text("#!/bin/sh\necho two\n", encoding="utf-8")
            self.assertFalse(
                pipeline_runner.cached_artifact_matches(
                    manifest,
                    dry_run=False,
                    prompt=rendered,
                    values=values,
                    llm_script_path=script,
                    output_path=output,
                    stage=stage,
                )
            )
            script.write_text("#!/bin/sh\necho one\n", encoding="utf-8")
            output.write_text(json.dumps({"ok": False}, ensure_ascii=False, indent=2), encoding="utf-8")
            self.assertFalse(
                pipeline_runner.cached_artifact_matches(
                    manifest,
                    dry_run=False,
                    prompt=rendered,
                    values=values,
                    llm_script_path=script,
                    output_path=output,
                    stage=stage,
                )
            )

    def test_force_reuse_preserves_existing_manifest_provenance(self):
        """Verify force reuse preserves existing manifest provenance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "run")
            stage = {
                "stage_id": "01_novel_summary",
                "stage_name": "小说梳理",
                "prompt_file": "prompts/clean/01_小说梳理_novel_summary.md",
            }
            clean_path = paths.outputs / "01_novel_summary.clean.json"
            manifest_path = paths.manifests / "01_novel_summary.manifest.json"
            clean_path.write_text(
                json.dumps({"novel_summary": "旧产物", "chapter_summaries": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            original_manifest = {"stage_id": "01_novel_summary", "llm_script": "/old/model.sh"}
            manifest_path.write_text(json.dumps(original_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

            data = pipeline_runner.call_stage(
                paths,
                stage,
                {},
                dry_run=False,
                llm_script_path=Path("/new/model.sh"),
                timeout=1,
                force_reuse=True,
                prompt_override="reuse",
            )

            self.assertEqual(data["novel_summary"], "旧产物")
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8")), original_manifest)

    def test_force_reuse_persists_new_canonical_normalization_and_keeps_llm_provenance(self):
        """Verify force reuse persists new canonical normalization and keeps llm provenance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "run")
            stage = {
                "stage_id": "01_novel_summary",
                "stage_name": "小说梳理",
                "prompt_file": "prompts/clean/01_小说梳理_novel_summary.md",
            }
            clean_path = paths.outputs / "01_novel_summary.clean.json"
            manifest_path = paths.manifests / "01_novel_summary.manifest.json"
            clean_path.write_text(
                json.dumps(
                    {
                        "novel_summary": "旧产物",
                        "chapter_summaries": [{"key_events": ["事件一"]}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            original_manifest = {
                "stage_id": "01_novel_summary",
                "llm_script": "/old/model.sh",
                "output_sha256": "old",
            }
            manifest_path.write_text(
                json.dumps(original_manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            data = pipeline_runner.call_stage(
                paths,
                stage,
                {},
                dry_run=False,
                llm_script_path=Path("/new/model.sh"),
                timeout=1,
                force_reuse=True,
                prompt_override="reuse",
            )

            persisted = json.loads(clean_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(data["key_events"], ["事件一"])
            self.assertEqual(persisted["key_events"], ["事件一"])
            self.assertEqual(manifest["llm_script"], "/old/model.sh")
            self.assertEqual(
                manifest["deterministic_repairs"][-1]["repair"],
                "normalize_forced_reuse_clean",
            )

    def test_resume_flags_parse_stage_boundaries(self):
        """Verify resume flags parse stage boundaries."""
        args = pipeline_runner.build_parser().parse_args(
            [
                "--novel",
                "docs/source.txt",
                "--resume-from",
                "07_episode_planning",
                "--reuse-through",
                "06_script_outline_design",
            ]
        )

        self.assertEqual(args.resume_from, "07_episode_planning")
        self.assertEqual(args.reuse_through, "06_script_outline_design")

    def test_stage_boundary_supports_04a_flashback_screening(self):
        """Verify stage boundary supports 04a flashback screening."""
        self.assertEqual(pipeline_runner.normalize_stage_boundary("04a"), "04a_flashback_screening")
        self.assertEqual(pipeline_runner.stage_after("04_adaptation_direction"), "04a_flashback_screening")
        self.assertEqual(pipeline_runner.stage_after("04a_flashback_screening"), "04b_dramatic_release_map")
        self.assertEqual(pipeline_runner.stage_after("04b_dramatic_release_map"), "05_plot_character_adaptation")

    def test_stage_boundary_supports_00a_global_config(self):
        """Verify stage boundary supports 00a global config."""
        self.assertEqual(pipeline_runner.normalize_stage_boundary("00a"), "00a_global_config")
        self.assertEqual(pipeline_runner.stage_after("00a_global_config"), "01_novel_summary")

    def test_reuse_through_04a_keeps_flashback_screening_and_clears_05_downstream(self):
        """Verify reuse through 04a keeps flashback screening and clears 05 downstream."""
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "run")
            for artifact_id in (
                "04a_flashback_screening",
                "05_plot_character_adaptation",
                "06_script_outline_design",
            ):
                for directory, suffix in (
                    (paths.outputs, ".clean.json"),
                    (paths.logs, ".log.json"),
                    (paths.manifests, ".manifest.json"),
                ):
                    (directory / f"{artifact_id}{suffix}").write_text("{}", encoding="utf-8")

            pipeline_runner.invalidate_from_stage(
                paths,
                pipeline_runner.stage_after("04a_flashback_screening"),
                generate_episodes=0,
            )

            self.assertTrue((paths.outputs / "04a_flashback_screening.clean.json").exists())
            self.assertFalse((paths.outputs / "05_plot_character_adaptation.clean.json").exists())
            self.assertFalse((paths.outputs / "06_script_outline_design.clean.json").exists())

    def test_invalidate_from_stage_removes_stage_and_downstream_only(self):
        """Verify invalidate from stage removes stage and downstream only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "run")
            for artifact_id in (
                "04a_flashback_screening",
                "06_script_outline_design",
                "07_episode_planning",
                "08_script_body_generation_ep001",
                "08_script_body_generation_ep002",
            ):
                for directory, suffix in (
                    (paths.outputs, ".clean.json"),
                    (paths.logs, ".log.json"),
                    (paths.manifests, ".manifest.json"),
                ):
                    (directory / f"{artifact_id}{suffix}").write_text("{}", encoding="utf-8")

            pipeline_runner.invalidate_from_stage(paths, "07_episode_planning", generate_episodes=2)

            self.assertTrue((paths.outputs / "04a_flashback_screening.clean.json").exists())
            self.assertTrue((paths.outputs / "06_script_outline_design.clean.json").exists())
            self.assertFalse((paths.outputs / "07_episode_planning.clean.json").exists())
            self.assertFalse((paths.outputs / "08_script_body_generation_ep001.clean.json").exists())

    def test_build_episode_event_options_limits_ids_by_episode_window(self):
        """Verify build episode event options limits ids by episode window."""
        event_pool = [
            {
                "id": 1,
                "target_block": 1,
                "episode_window": {"start": 1, "end": 3},
                "not_before_episode": 1,
                "not_after_episode": 3,
            },
            {
                "id": 16,
                "target_block": 1,
                "episode_window": {"start": 5, "end": 7},
                "not_before_episode": 4,
                "not_after_episode": 8,
            },
        ]

        options = pipeline_runner.build_episode_event_options(event_pool, target_episodes=8)
        by_episode = {item["episode_num"]: item for item in options}

        self.assertEqual(by_episode[3]["valid_event_ids"], [1])
        self.assertEqual(by_episode[4]["valid_event_ids"], [])
        self.assertEqual(by_episode[5]["valid_event_ids"], [16])
        self.assertEqual(by_episode[8]["valid_event_ids"], [])

    def test_build_episode_event_options_assigns_one_event_and_one_or_two_beats(self):
        """Verify build episode event options assigns one event and one or two beats."""
        event_pool = [
            {
                "id": 1,
                "target_block": 1,
                "episode_window": {"start": 1, "end": 1},
                "child_beats": [
                    {"child_beat_id": "E1-B1", "action": "回到当下"},
                ],
            },
            {
                "id": 2,
                "target_block": 1,
                "episode_window": {"start": 2, "end": 6},
                "child_beats": [
                    {"child_beat_id": f"E2-B{index}", "action": f"动作{index}"}
                    for index in range(1, 7)
                ],
            },
        ]

        options = pipeline_runner.build_episode_event_options(event_pool, target_episodes=6)
        by_episode = {item["episode_num"]: item for item in options}

        self.assertEqual(by_episode[1]["assigned_event_id"], 1)
        self.assertEqual(by_episode[1]["assigned_child_beat_ids"], ["E1-B1"])
        self.assertEqual(by_episode[2]["assigned_event_id"], 2)
        self.assertEqual(by_episode[2]["assigned_child_beat_ids"], ["E2-B1", "E2-B2"])
        self.assertEqual(by_episode[3]["assigned_child_beat_ids"], ["E2-B3"])
        self.assertEqual(by_episode[6]["assigned_child_beat_ids"], ["E2-B6"])

    def test_repair_episode_event_ids_preserves_model_semantics_for_warning(self):
        """Verify repair episode event ids preserves model semantics for warning."""
        event_pool = [
            {
                "id": 2,
                "target_block": 1,
                "episode_window": {"start": 3, "end": 4},
                "not_before_episode": 3,
                "not_after_episode": 4,
            },
            {
                "id": 3,
                "target_block": 1,
                "episode_window": {"start": 5, "end": 7},
                "not_before_episode": 5,
                "not_after_episode": 7,
            },
        ]
        episodes = [{"episode_num": 4, "block_id": 1, "event_ids": [3]}]

        repaired = pipeline_runner.repair_episode_event_ids(episodes, event_pool=event_pool, target_episodes=7)

        self.assertEqual(repaired[0]["event_ids"], [3])
        self.assertNotIn("event_id_repair_trace", repaired[0])

    def test_initialize_report_only_issue_log_discards_previous_attempt_items(self):
        """Verify initialize report only issue log discards previous attempt items."""
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "issue_log_reset_test")
            pipeline_runner.write_report_only_issue_log(
                paths,
                [{"stage": "08_script_body_generation", "artifact_id": "old", "errors": []}],
            )

            pipeline_runner.initialize_report_only_issue_log(paths)
            payload = json.loads((paths.parsed / "full_run_issue_log.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["issues"], [])

    def test_repair_event_pool_window_gaps_extends_previous_event(self):
        """Verify repair event pool window gaps extends previous event."""
        event_pool = [
            {"id": 14, "target_block": 3, "episode_window": {"start": 27, "end": 29}, "expected_episode_span": 3},
            {"id": 15, "target_block": 4, "episode_window": {"start": 31, "end": 33}, "expected_episode_span": 3},
        ]
        blocks = [
            {"block_id": 3, "start_episode": 21, "end_episode": 30},
            {"block_id": 4, "start_episode": 31, "end_episode": 40},
        ]

        repaired = pipeline_runner.repair_event_pool_window_gaps(event_pool, blocks)
        event14 = next(item for item in repaired if item["id"] == 14)

        self.assertEqual(event14["episode_window"], {"start": 27, "end": 30})
        self.assertEqual(event14["not_after_episode"], 30)
        self.assertEqual(event14["expected_episode_span"], 4)
        self.assertTrue(event14["event_window_repair_trace"])

    def test_repair_event_pool_window_gaps_covers_leading_block_gap(self):
        """Verify repair event pool window gaps covers leading block gap."""
        event_pool = [
            {
                "id": 17,
                "target_block": 4,
                "episode_window": {"start": 33, "end": 38},
                "not_before_episode": 33,
                "not_after_episode": 38,
                "expected_episode_span": 6,
            },
            {
                "id": 18,
                "target_block": 4,
                "episode_window": {"start": 39, "end": 40},
                "not_before_episode": 39,
                "not_after_episode": 40,
                "expected_episode_span": 2,
            },
        ]
        blocks = [{"block_id": 4, "start_episode": 31, "end_episode": 40}]

        repaired = pipeline_runner.repair_event_pool_window_gaps(event_pool, blocks)
        event17 = next(item for item in repaired if item["id"] == 17)

        self.assertEqual(event17["episode_window"], {"start": 31, "end": 38})
        self.assertEqual(event17["not_before_episode"], 31)
        self.assertEqual(event17["expected_episode_span"], 8)

    def test_repair_event_pool_window_gaps_aligns_expected_span_with_window(self):
        """Verify repair event pool window gaps aligns expected span with window."""
        event_pool = [
            {
                "id": 3,
                "target_block": 1,
                "episode_window": {"start": 5, "end": 8},
                "not_before_episode": 5,
                "not_after_episode": 8,
                "expected_episode_span": 3,
            },
            {
                "id": 4,
                "target_block": 1,
                "episode_window": {"start": 9, "end": 10},
                "not_before_episode": 9,
                "not_after_episode": 10,
                "expected_episode_span": 2,
            },
        ]
        blocks = [{"block_id": 1, "start_episode": 1, "end_episode": 10}]

        repaired = pipeline_runner.repair_event_pool_window_gaps(event_pool, blocks)
        event3 = next(item for item in repaired if item["id"] == 3)

        self.assertEqual(event3["episode_window"], {"start": 5, "end": 8})
        self.assertEqual(event3["expected_episode_span"], 4)
        self.assertEqual(event3["event_window_repair_trace"][0]["reason"], "align_expected_episode_span_with_window")

    def test_repair_event_pool_window_gaps_does_not_expand_beyond_child_beat_capacity(self):
        """Verify repair event pool window gaps does not expand beyond child beat capacity."""
        event_pool = [
            {
                "id": 1,
                "target_block": 1,
                "episode_window": {"start": 1, "end": 3},
                "not_before_episode": 1,
                "not_after_episode": 3,
                "expected_episode_span": 3,
                "child_beats": [
                    {"child_beat_id": f"E1-B{index}", "action": f"动作{index}"}
                    for index in range(1, 5)
                ],
            }
        ]
        blocks = [{"block_id": 1, "start_episode": 1, "end_episode": 10}]

        repaired = pipeline_runner.repair_event_pool_window_gaps(event_pool, blocks)
        event = repaired[0]

        self.assertEqual(event["episode_window"], {"start": 1, "end": 4})
        self.assertEqual(event["not_after_episode"], 4)
        self.assertEqual(event["expected_episode_span"], 4)
        self.assertEqual(
            event["event_window_repair_trace"][0]["reason"],
            "partition_block_for_deterministic_child_beat_schedule",
        )

    def test_repair_event_pool_window_gaps_partitions_block_without_overlap(self):
        """Verify repair event pool window gaps partitions block without overlap."""
        event_pool = [
            {
                "id": 1,
                "target_block": 1,
                "episode_window": {"start": 1, "end": 4},
                "expected_episode_span": 4,
                "child_beats": [
                    {"child_beat_id": f"E1-B{index}", "action": f"动作{index}"}
                    for index in range(1, 5)
                ],
            },
            {
                "id": 2,
                "target_block": 1,
                "episode_window": {"start": 4, "end": 8},
                "expected_episode_span": 5,
                "child_beats": [
                    {"child_beat_id": f"E2-B{index}", "action": f"动作{index}"}
                    for index in range(1, 7)
                ],
            },
        ]
        blocks = [{"block_id": 1, "start_episode": 1, "end_episode": 8}]

        repaired = pipeline_runner.repair_event_pool_window_gaps(event_pool, blocks)
        windows = [item["episode_window"] for item in repaired]

        self.assertEqual(windows[0]["start"], 1)
        self.assertEqual(windows[-1]["end"], 8)
        self.assertEqual(windows[0]["end"] + 1, windows[1]["start"])
        for item in repaired:
            span = item["episode_window"]["end"] - item["episode_window"]["start"] + 1
            self.assertLessEqual(span, len(item["child_beats"]))
            self.assertLessEqual(len(item["child_beats"]), span * 2)

    def test_build_episode_planning_values_compacts_long_upstream_inputs(self):
        """Verify build episode planning values compacts long upstream inputs."""
        long_text = "长证据" * 80
        event_pool = [
            {
                "id": 1,
                "title": "重生当场反杀造谣",
                "function": long_text,
                "source_plot_point_ids": [1],
                "target_block": 1,
                "episode_window": {"start": 1, "end": 2},
                "not_before_episode": 1,
                "not_after_episode": 2,
                "conflict_mode": "public_confrontation",
                "pattern_family": "verbal_counterattack",
                "source_anchor": long_text,
                "delta_from_source": long_text,
                "child_beats": [
                    {
                        **pipeline_runner._build_dry_run_transaction(1, index),
                        "action": long_text,
                    }
                    for index in range(1, 6)
                ],
                "model_reasoning_notes": long_text,
            }
        ]
        stage_outputs = {
            "03_plot_character_extract": {
                "source_plot_points": [
                        {"id": 1, "title": "村口造谣", "event": long_text, "function": long_text, "characters": ["沈念"]},
                    ]
            },
            "05_plot_character_adaptation": {
                "event_pool": event_pool,
                "conflict_engine": {"primary": long_text},
                "expanded_character_network": [{"name": "沈念", "camp": "正义", "function": long_text, "extra": long_text}],
                "foreshadowing_pool": [{"id": 1, "setup": long_text, "payoff": long_text, "related_arc": 1}],
            },
            "06_script_outline_design": {
                "global_outline": "全剧大纲",
                "longform_blocks": [{"block_id": 1, "start_episode": 1, "end_episode": 2}],
                "phase_breakdown": [],
                "episode_budget": [],
                "event_release_schedule": [],
                "block_event_plan": [],
                "climax_guardrails": {},
                "block_state_plan": [],
                "qa_rules": [],
            },
        }
        canonical_story_lock = {
            "protagonist": "沈念",
            "character_names": ["沈念", "王桂兰"],
            "source_plot_points": stage_outputs["03_plot_character_extract"]["source_plot_points"],
            "must_keep": [long_text],
        }

        values = pipeline_runner.build_episode_planning_values(
            prompt_context={"run_config": {}, "derived_config": {}, "target_episodes": 2},
            stage_outputs=stage_outputs,
            canonical_story_lock=canonical_story_lock,
            target_episodes=2,
            transaction_schedule={
                "status": "PASS",
                "transactions": {
                    "E1-B1": {
                        **event_pool[0]["child_beats"][0],
                        "transaction_id": "E1-B1",
                        "owner_event_id": "1",
                        "owner_block_id": 1,
                        "owner_episode": 1,
                    },
                    "E1-B2": {
                        **event_pool[0]["child_beats"][1],
                        "transaction_id": "E1-B2",
                        "owner_event_id": "1",
                        "owner_block_id": 1,
                        "owner_episode": 2,
                    },
                },
                "episodes": [
                    {
                        "episode_num": 1,
                        "assigned_event_id": 1,
                        "authorized_transaction_ids": ["E1-B1"],
                    },
                    {
                        "episode_num": 2,
                        "assigned_event_id": 1,
                        "authorized_transaction_ids": ["E1-B2"],
                    },
                ],
            },
        )

        self.assertEqual(values["episode_event_options"][0]["valid_event_ids"], [1])
        self.assertEqual(values["canonical_story_lock"]["character_names"], ["沈念", "王桂兰"])
        self.assertNotIn("model_reasoning_notes", values["event_pool"][0])
        self.assertLessEqual(
            len(values["event_pool"][0]["source_anchor"]),
            pipeline_runner.PLANNING_TEXT_CLIP_CHARS + 3,
        )
        self.assertEqual(len(values["event_pool"][0]["child_beats"]), 5)
        self.assertNotIn("extra", values["expanded_character_network"][0])

    def test_build_episode_planning_values_keeps_full_event_pool_for_repairs(self):
        """Verify build episode planning values keeps full event pool for repairs."""
        event = {
            "id": 1,
            "target_block": 1,
            "episode_window": {"start": 1, "end": 4},
            "source_anchor": "源锚",
            "child_beats": ["第1集：A", "第2集：B", "第3集：C", "第4集：D"],
        }
        stage_outputs = {
            "03_plot_character_extract": {"source_plot_points": []},
            "05_plot_character_adaptation": {
                "event_pool": [event],
                "conflict_engine": {},
                "expanded_character_network": [],
                "foreshadowing_pool": [],
            },
            "06_script_outline_design": {
                "global_outline": {},
                "longform_blocks": [{"block_id": 1, "start_episode": 1, "end_episode": 4, "episode_count": 4}],
                "phase_breakdown": [],
                "episode_budget": [],
                "event_release_schedule": [],
                "block_event_plan": [],
                "climax_guardrails": [],
                "block_state_plan": [],
                "qa_rules": [],
            },
        }

        values = pipeline_runner.build_episode_planning_values(
            prompt_context={"run_config": {}, "derived_config": {}, "target_episodes": 40},
            stage_outputs=stage_outputs,
            canonical_story_lock={"character_names": ["女主"], "protagonist": "女主"},
            target_episodes=40,
        )

        self.assertEqual(len(values["event_pool"][0]["child_beats"]), 4)
        self.assertEqual(len(values["_full_event_pool_for_repair"][0]["child_beats"]), 4)

    def test_episode_planning_block_values_filter_scope_and_carry_handoff(self):
        """Verify episode planning block values filter scope and carry handoff."""
        blocks = [
            {
                "block_id": 1,
                "phase": "篇章1",
                "title": "首战",
                "start_episode": 1,
                "end_episode": 2,
                "episode_count": 2,
                "goal": "破局",
                "antagonist": "反派",
                "hook": "追问",
            },
            {
                "block_id": 2,
                "phase": "篇章2",
                "title": "扩散",
                "start_episode": 3,
                "end_episode": 4,
                "episode_count": 2,
                "goal": "扩散",
                "antagonist": "围观者",
                "hook": "新证据",
            },
        ]
        values = {
            "target_episodes": 4,
            "run_config": {},
            "derived_config": {},
            "longform_blocks": blocks,
            "phase_breakdown": blocks,
            "episode_budget": blocks,
            "event_release_schedule": blocks,
            "block_event_plan": blocks,
            "block_state_plan": blocks,
            "event_pool": [
                {"id": 1, "target_block": 1, "episode_window": {"start": 1, "end": 2}},
                {"id": 2, "target_block": 2, "episode_window": {"start": 3, "end": 4}},
            ],
            "episode_event_options": [
                {"episode_num": 1, "valid_event_ids": [1]},
                {"episode_num": 2, "valid_event_ids": [1]},
                {"episode_num": 3, "valid_event_ids": [2]},
                {"episode_num": 4, "valid_event_ids": [2]},
            ],
            "foreshadowing_pool": [],
            "canonical_story_lock": {"character_names": ["沈念"], "protagonist": "沈念"},
            "expanded_character_network": [],
            "conflict_engine": {},
            "qa_rules": [],
        }
        handoff = {
            "last_two_episode_summaries": [{"episode_num": 2, "closing_beat": "旧证据被看见"}],
            "cumulative_consumed_child_beat_ids": ["E1-B1"],
            "last_story_time": {
                "day_index": 2,
                "time_label": "第二天傍晚",
                "elapsed_from_previous": "当日",
            },
            "active_prop_registry": [
                {
                    "prop_id": "PROP_PHONE",
                    "prop_name": "手机",
                    "holder": "沈念",
                    "location": "沈念手中",
                    "last_updated_episode_num": 2,
                }
            ],
        }

        block_values = pipeline_runner.build_episode_planning_block_values(
            values,
            block=blocks[1],
            previous_handoff=handoff,
            next_block=None,
        )

        compact_handoff = block_values["episode_planning_scope"]["previous_handoff"]
        self.assertEqual(compact_handoff["last_two_episode_summaries"][0]["closing_beat"], "旧证据被看见")
        self.assertEqual(compact_handoff["cumulative_consumed_child_beat_ids"], ["E1-B1"])
        self.assertEqual(compact_handoff["last_story_time"]["day_index"], 2)
        self.assertEqual(compact_handoff["active_prop_registry"][0]["location"], "沈念手中")
        self.assertEqual([item["id"] for item in block_values["event_pool"]], [2])
        self.assertEqual([item["episode_num"] for item in block_values["episode_event_options"]], [3, 4])
        self.assertEqual(block_values["episode_event_options"][0]["valid_event_ids"], [2])

    def test_episode_planning_block_values_only_exposes_legal_unconsumed_event_beats(self):
        """Verify episode planning block values only exposes legal unconsumed event beats."""
        block = {
            "block_id": 1,
            "phase": "篇章1",
            "title": "首战",
            "start_episode": 2,
            "end_episode": 2,
            "episode_count": 1,
            "goal": "破局",
            "antagonist": "爷爷",
            "hook": "追问",
        }
        values = {
            "target_episodes": 4,
            "run_config": {},
            "derived_config": {},
            "longform_blocks": [block],
            "phase_breakdown": [],
            "episode_budget": [],
            "event_release_schedule": [],
            "block_event_plan": [],
            "block_state_plan": [],
            "event_pool": [
                {
                    "id": 1,
                    "target_block": 1,
                    "episode_window": {"start": 1, "end": 2},
                    "child_beats": [
                        {"child_beat_id": "E1-B1", "action": "旧动作", "completion_evidence": "旧证据"},
                    ],
                },
                {
                    "id": 2,
                    "target_block": 1,
                    "episode_window": {"start": 2, "end": 3},
                    "child_beats": [
                        {"child_beat_id": "E2-B1", "action": "新动作一", "completion_evidence": "新证据一"},
                        {"child_beat_id": "E2-B2", "action": "新动作二", "completion_evidence": "新证据二"},
                    ],
                },
                {
                    "id": 3,
                    "target_block": 1,
                    "episode_window": {"start": 3, "end": 4},
                    "child_beats": [
                        {"child_beat_id": "E3-B1", "action": "未来动作", "completion_evidence": "未来证据"},
                    ],
                },
            ],
            "episode_event_options": [
                {"episode_num": 2, "valid_event_ids": [1, 2]},
            ],
            "foreshadowing_pool": [],
            "canonical_story_lock": {"character_names": ["方华"], "protagonist": "方华"},
            "expanded_character_network": [],
            "conflict_engine": {},
            "qa_rules": [],
        }

        block_values = pipeline_runner.build_episode_planning_block_values(
            values,
            block=block,
            previous_handoff={"cumulative_consumed_child_beat_ids": ["E1-B1", "E2-B1"]},
            next_block=None,
        )

        self.assertEqual(block_values["episode_event_options"], [{"episode_num": 2, "valid_event_ids": [2]}])
        self.assertEqual([item["id"] for item in block_values["event_pool"]], [2])
        self.assertEqual(
            [item["child_beat_id"] for item in block_values["event_pool"][0]["child_beats"]],
            ["E2-B2"],
        )

    def test_episode_planning_block_values_exposes_only_locally_assigned_beats(self):
        """Verify episode planning block values exposes only locally assigned beats."""
        block = {
            "block_id": 1,
            "phase": "篇章1",
            "title": "首战",
            "start_episode": 2,
            "end_episode": 3,
            "episode_count": 2,
            "goal": "破局",
            "antagonist": "爷爷",
            "hook": "追问",
        }
        values = {
            "target_episodes": 3,
            "event_pool": [
                {
                    "id": 2,
                    "target_block": 1,
                    "episode_window": {"start": 2, "end": 3},
                    "child_beats": [
                        {"child_beat_id": "E2-B1", "action": "动作一", "completion_evidence": "证据一"},
                        {"child_beat_id": "E2-B2", "action": "动作二", "completion_evidence": "证据二"},
                        {"child_beat_id": "E2-B3", "action": "动作三", "completion_evidence": "证据三"},
                    ],
                }
            ],
            "episode_event_options": [
                {
                    "episode_num": 2,
                    "valid_event_ids": [2],
                    "assigned_event_id": 2,
                    "assigned_child_beat_ids": ["E2-B1", "E2-B2"],
                },
                {
                    "episode_num": 3,
                    "valid_event_ids": [2],
                    "assigned_event_id": 2,
                    "assigned_child_beat_ids": ["E2-B3"],
                },
            ],
            "phase_breakdown": [],
            "episode_budget": [],
            "event_release_schedule": [],
            "block_event_plan": [],
            "block_state_plan": [],
        }

        block_values = pipeline_runner.build_episode_planning_block_values(
            values,
            block=block,
            previous_handoff={},
            next_block=None,
        )

        self.assertEqual(
            [item["child_beat_id"] for item in block_values["event_pool"][0]["child_beats"]],
            ["E2-B1", "E2-B2", "E2-B3"],
        )
        self.assertEqual(
            block_values["episode_event_options"][0]["assigned_child_beat_ids"],
            ["E2-B1", "E2-B2"],
        )

    def test_episode_planning_block_normalizer_applies_local_schedule(self):
        """Verify episode planning block normalizer applies local schedule."""
        block = {
            "block_id": 1,
            "start_episode": 2,
            "end_episode": 2,
            "episode_count": 1,
        }
        block_values = {
            "episode_planning_scope": {
                "current_block": block,
                "previous_handoff": {},
            },
            "episode_event_options": [
                {
                    "episode_num": 2,
                    "valid_event_ids": [2],
                    "assigned_event_id": 2,
                    "assigned_child_beat_ids": ["E2-B1", "E2-B2"],
                }
            ],
            "_full_event_pool_for_repair": [
                {
                    "id": 2,
                    "child_beats": [
                        {"child_beat_id": "E2-B1", "action": "动作一", "completion_evidence": "证据一"},
                        {"child_beat_id": "E2-B2", "action": "动作二", "completion_evidence": "证据二"},
                    ],
                }
            ],
            "prop_registry": [],
        }
        raw = {
            "episode_outlines": [
                {
                    "episode_num": 2,
                    "event_ids": [99],
                    "consumed_child_beat_ids": ["E99-B1"],
                    "consumed_child_beats": ["错误动作"],
                    "target_script_density": {
                        "must_cover_beats": [
                            {"beat_id": "X1", "action": "错误动作", "completion_evidence": "错误证据"}
                        ],
                        "scene_char_budgets": [
                            {"scene_no": 1, "target_chars": 700, "must_cover_beat_ids": ["X1"]}
                        ],
                    },
                }
            ]
        }

        normalized = pipeline_runner.normalize_episode_planning_block_output(raw, block_values)
        episode = normalized["episode_outlines"][0]

        self.assertEqual(episode["block_id"], 1)
        self.assertEqual(episode["event_ids"], [2])
        self.assertEqual(episode["consumed_child_beat_ids"], ["E2-B1", "E2-B2"])
        self.assertEqual(episode["consumed_child_beats"], ["动作一", "动作二"])
        self.assertEqual(
            [item["beat_id"] for item in episode["target_script_density"]["must_cover_beats"]],
            ["E2-B1", "E2-B2"],
        )
        assigned_budget_ids = [
            beat_id
            for item in episode["target_script_density"]["scene_char_budgets"]
            for beat_id in item["must_cover_beat_ids"]
        ]
        self.assertEqual(assigned_budget_ids, ["E2-B1", "E2-B2"])

    def test_script_outline_normalizer_inherits_macro_arc_boundaries(self):
        """Verify script outline normalizer inherits macro arc boundaries."""
        raw = pipeline_runner.dry_run_payload("06_script_outline_design", {"target_episodes": 40})
        raw["longform_blocks"][1]["start_episode"] = 11
        raw["longform_blocks"][1]["end_episode"] = 25
        raw["longform_blocks"][1]["episode_count"] = 15
        raw["longform_blocks"][2]["start_episode"] = 26
        raw["longform_blocks"][2]["episode_count"] = 5
        macro_arcs = [
            {"arc_id": 1, "title": "一", "episode_range": "1-10"},
            {"arc_id": 2, "title": "二", "episode_range": "11-20"},
            {"arc_id": 3, "title": "三", "episode_range": "21-30"},
            {"arc_id": 4, "title": "四", "episode_range": "31-40"},
        ]

        normalized, report = pipeline_runner.normalize_stage_output_with_report(
            "06_script_outline_design",
            raw,
            normalization_context={"macro_arcs": macro_arcs},
        )

        self.assertEqual(
            [
                (item["start_episode"], item["end_episode"], item["episode_count"])
                for item in normalized["longform_blocks"]
            ],
            [(1, 10, 10), (11, 20, 10), (21, 30, 10), (31, 40, 10)],
        )
        self.assertEqual(normalized["event_release_schedule"][1]["episode_range"], {"start": 11, "end": 20})
        self.assertEqual(report["status"], "CHANGED")

    def test_episode_prop_plan_ids_remap_reserved_collision_and_reuse_by_name(self):
        """Verify episode prop plan ids remap reserved collision and reuse by name."""
        episodes = [
            {
                "episode_num": 3,
                "prop_continuity_plan": [
                    {"prop_id": "PROP013", "prop_name": "第二罐花生酱"},
                ],
            },
            {
                "episode_num": 4,
                "prop_continuity_plan": [
                    {"prop_id": "PROP013", "prop_name": "第二罐花生酱"},
                ],
            },
        ]
        registry = [
            {
                "prop_id": "PROP013",
                "prop_name": "考试作弊禁考通知",
                "created_episode": 11,
            }
        ]

        normalized = pipeline_runner.normalize_episode_prop_plan_ids(
            episodes,
            prop_registry=registry,
            previous_handoff={},
        )

        first_id = normalized[0]["prop_continuity_plan"][0]["prop_id"]
        self.assertEqual(first_id, "PROP_EP003_01")
        self.assertEqual(normalized[1]["prop_continuity_plan"][0]["prop_id"], first_id)

    def test_episode_planning_handoff_accumulates_child_beats_and_prop_registry(self):
        """Verify episode planning handoff accumulates child beats and prop registry."""
        previous = {
            "cumulative_consumed_child_beat_ids": ["E1-B1"],
            "active_prop_registry": [
                {
                    "prop_id": "PROP_PHONE",
                    "prop_name": "手机",
                    "holder": "方华",
                    "location": "书桌上",
                    "last_updated_episode_num": 1,
                }
            ],
        }
        block_output = {
            "episode_outlines": [
                {
                    "episode_num": 2,
                    "title": "带走证件",
                    "consumed_child_beat_ids": ["E2-B1"],
                    "prop_continuity_plan": [
                        {
                            "prop_id": "PROP_PHONE",
                            "prop_name": "手机",
                            "end_holder": "方华",
                            "end_location": "书包侧袋",
                        },
                        {
                            "prop_id": "PROP_EXAM_DOCUMENTS",
                            "prop_name": "准考证和身份证",
                            "end_holder": "方华",
                            "end_location": "书包内",
                        },
                    ],
                }
            ],
            "state_delta": {
                "block_id": 1,
                "unresolved_threads": ["爷爷继续追赶"],
                "running_character_state": {"方华": "已离家"},
                "next_block_handoff": "方华到达林可家",
            },
        }

        handoff = pipeline_runner.build_episode_planning_handoff(
            block_output,
            previous_handoff=previous,
        )

        self.assertEqual(handoff["cumulative_consumed_child_beat_ids"], ["E1-B1", "E2-B1"])
        registry = {item["prop_id"]: item for item in handoff["active_prop_registry"]}
        self.assertEqual(registry["PROP_PHONE"]["location"], "书包侧袋")
        self.assertEqual(registry["PROP_PHONE"]["last_updated_episode_num"], 2)
        self.assertEqual(registry["PROP_EXAM_DOCUMENTS"]["holder"], "方华")

    def test_episode_planning_chunk_scope_does_not_treat_next_chunk_as_next_parent_block(self):
        """Verify episode planning chunk scope does not treat next chunk as next parent block."""
        parent = {
            "block_id": 1,
            "phase": "起势",
            "title": "首战",
            "start_episode": 1,
            "end_episode": 5,
            "episode_count": 5,
            "goal": "第五集完成出走并进入考场",
            "hook": "考场外发现异常",
        }
        chunks = pipeline_runner.split_blocks_for_episode_chunks([parent], max_episodes_per_chunk=1)
        values = {
            "target_episodes": 5,
            "event_pool": [],
            "episode_event_options": [],
            "phase_breakdown": [],
            "episode_budget": [],
            "event_release_schedule": [],
            "block_event_plan": [],
            "block_state_plan": [],
        }

        block_values = pipeline_runner.build_episode_planning_block_values(
            values,
            block=chunks[1],
            next_block=chunks[2],
        )
        scope = block_values["episode_planning_scope"]

        self.assertEqual(scope["parent_block_episode_range"], {"start": 1, "end": 5})
        self.assertFalse(scope["chunk_is_parent_block_end"])
        self.assertEqual(scope["next_chunk_episode_range"], {"start": 3, "end": 3})
        self.assertEqual(scope["next_block_target"], {})

    def test_episode_planning_block_prompt_keeps_full_chinese_episode_contract(self):
        """Verify episode planning block prompt keeps full chinese episode contract."""
        import llm_schema_localization

        block = {
            "block_id": 1,
            "phase": "篇章1",
            "title": "首战",
            "start_episode": 1,
            "end_episode": 2,
            "episode_count": 2,
            "goal": "破局",
            "antagonist": "反派",
            "hook": "追问",
        }
        values = {
            "target_episodes": 2,
            "run_config": {},
            "derived_config": {},
            "longform_blocks": [block],
            "phase_breakdown": [],
            "episode_budget": [],
            "event_release_schedule": [],
            "block_event_plan": [],
            "block_state_plan": [],
            "event_pool": [{"id": 1, "target_block": 1, "episode_window": {"start": 1, "end": 2}}],
            "episode_event_options": [
                    {"episode_num": 1, "valid_event_ids": [1]},
                    {"episode_num": 2, "valid_event_ids": [1]},
                ],
            "foreshadowing_pool": [],
            "canonical_story_lock": {"character_names": ["沈念"], "protagonist": "沈念"},
            "expanded_character_network": [],
            "conflict_engine": {},
            "qa_rules": [],
        }

        block_values = pipeline_runner.build_episode_planning_block_values(values, block=block)
        prompt = pipeline_runner.render_episode_planning_block_prompt(block_values)

        for field in ("模式家族", "原著锚点", "边界检查", "出场人物姓名", "是否尾声"):
            self.assertIn(field, prompt)
        for field in ("pattern_family", "source_anchor", "boundary_check", "appearing_character_names", "is_epilogue"):
            self.assertNotIn(field, prompt)
        self.assertIn("不得用简化情节字段替代", prompt)
        self.assertIn("允许出现人物名", prompt)
        self.assertIn("不得新增神婆", prompt)
        self.assertIn("跨篇章的第一集开场节拍", prompt)
        self.assertIn("已消耗子情节点", prompt)
        self.assertIn("本集授权事务", prompt)
        self.assertIn("不能漂移到别的事件ID", prompt)
        self.assertIn("分集大纲", prompt)
        self.assertNotIn("篇章分批计划", prompt)
        self.assertNotIn("状态增量", prompt)
        self.assertIn("顶层必须只有 `分集大纲`", prompt)
        for key in (
            "main_conflict",
            "scene_plan",
            "must_include_beats",
            "opening_beat",
            "closing_beat",
            "next_episode_start_state",
            "approved_flashback_time_deviation_ids",
            "approved_os_time_deviation_ids",
            "visualized_time_deviation_ids",
        ):
            self.assertIn(f"`{llm_schema_localization.FIELD_LABELS[key]}`", prompt)
        for invalid_alias in (
            "`主冲突`",
            "`自然分场计划`",
            "`必须包含的情节点`",
            "`开场节拍`",
            "`收尾节拍`",
            "`下集开始状态`",
            "`已批准闪回时间线偏离ID`",
            "`已批准OS时间线偏离ID`",
            "`已可视化时间线偏离ID`",
        ):
            self.assertNotIn(invalid_alias, prompt)
        registered_labels = set(llm_schema_localization.FIELD_LABELS.values()) | {
            label
            for value_map in llm_schema_localization.CONTEXTUAL_FIELD_LABELS_BY_PARENT.values()
            for label in value_map.values()
        }
        allowed_literals = {"{", "}", "某人（VO，语气...）", "人物（VO）：台词"}
        self.assertEqual(
            {
                term
                for term in re.findall(r"`([^`\n]+)`", prompt)
                if term not in registered_labels and term not in allowed_literals
            },
            set(),
        )

    def test_episode_planning_block_prompt_hides_future_reserved_prop_ids(self):
        """Verify episode planning block prompt hides future reserved prop ids."""
        block = {
            "block_id": 1,
            "phase": "篇章1",
            "title": "首战",
            "start_episode": 1,
            "end_episode": 1,
            "episode_count": 1,
            "goal": "破局",
            "antagonist": "反派",
            "hook": "追问",
        }
        values = {
            "target_episodes": 1,
            "run_config": {},
            "derived_config": {},
            "longform_blocks": [block],
            "phase_breakdown": [],
            "episode_budget": [],
            "event_release_schedule": [],
            "block_event_plan": [],
            "block_state_plan": [],
            "event_pool": [],
            "episode_event_options": [],
            "foreshadowing_pool": [],
            "prop_registry": [
                {
                    "prop_id": f"PROP{index:03d}",
                    "prop_name": f"道具{index}",
                    "created_episode": index,
                }
                for index in range(1, 15)
            ],
            "canonical_story_lock": {"character_names": ["沈念"], "protagonist": "沈念"},
            "expanded_character_network": [],
            "conflict_engine": {},
            "qa_rules": [],
        }

        prompt = pipeline_runner.render_episode_planning_block_prompt(
            pipeline_runner.build_episode_planning_block_values(values, block=block)
        )

        self.assertIn("PROP001", prompt)
        self.assertNotIn("PROP013", prompt)
        self.assertNotIn("PROP014", prompt)

    def test_episode_planning_block_merge_preserves_model_episode_numbers_for_validation(self):
        """Verify episode planning block merge preserves model episode numbers for validation."""
        blocks = [
            {
                "block_id": 1,
                "phase": "篇章1",
                "title": "首战",
                "start_episode": 1,
                "end_episode": 2,
                "episode_count": 2,
                "goal": "破局",
                "antagonist": "反派",
                "hook": "追问",
            },
            {
                "block_id": 2,
                "phase": "篇章2",
                "title": "扩散",
                "start_episode": 3,
                "end_episode": 4,
                "episode_count": 2,
                "goal": "扩散",
                "antagonist": "围观者",
                "hook": "新证据",
            },
        ]
        block_values = {
            "episode_planning_scope": {
                "current_block": blocks[1],
                "global_target_episodes": 4,
                "mode": "internal_block",
            }
        }
        raw_block2 = {
            "block_plan": blocks[1],
            "episode_outlines": [
                {"episode_num": 1, "title": "第3集", "closing_beat": "证人开口", "next_episode_start_state": "证人继续说"},
                {"episode_num": 2, "title": "第4集", "closing_beat": "围观者转向", "next_episode_start_state": "新证据出现"},
            ],
            "state_delta": {"running_character_state": {"沈念": "转为主动"}},
        }

        normalized_block2 = pipeline_runner.normalize_episode_planning_block_output(raw_block2, block_values)
        merged = pipeline_runner.merge_episode_planning_blocks(
            [
                {
                    "block_plan": blocks[0],
                    "episode_outlines": [
                        {"episode_num": 1, "title": "第1集"},
                        {"episode_num": 2, "title": "第2集"},
                    ],
                    "state_delta": {},
                },
                normalized_block2,
            ],
            blocks,
        )

        self.assertEqual(set(merged.keys()), {"episode_allocation", "block_plans", "episode_outlines"})
        self.assertEqual([item["episode_num"] for item in merged["episode_outlines"]], [1, 1, 2, 2])
        self.assertNotIn("episode_num_repair_trace", merged["episode_outlines"][2])
        self.assertEqual(merged["episode_allocation"][1]["start_episode"], 3)

    def test_episode_planning_block_ignores_model_state_and_derives_fixed_handoff(self):
        """Verify episode planning block ignores model state and derives fixed handoff."""
        block = {
            "block_id": 1,
            "phase": "开局",
            "title": "当场脱身",
            "start_episode": 1,
            "end_episode": 1,
            "episode_count": 1,
            "goal": "逃离控制",
            "antagonist": "爷爷",
            "hook": "爷爷追到学校",
            "foreshadowing_plan": "投放录取短信",
        }
        block_values = {
            "episode_planning_scope": {
                "current_block": block,
                "global_target_episodes": 40,
                "mode": "internal_block",
            }
        }
        raw = {
            "block_plan": {**block, "本批集数": 1},
            "episode_outlines": [
                {
                    "episode_num": 1,
                    "title": "重生当日",
                    "state_change": {"方华": "开始主动逃离"},
                    "unresolved_threads_after_episode": ["爷爷会追到学校"],
                    "next_episode_start_state": "方华已到校门口",
                    "event_ids": [1, 2],
                    "event_consumption_status": "completed",
                    "foreshadowing_ids": [1],
                }
            ],
            "state_delta": {
                "累计OS消耗": 9,
                "next_block_handoff": {"自由子键": "不应保留"},
            },
        }

        normalized = pipeline_runner.normalize_episode_planning_block_output(raw, block_values)

        self.assertEqual(set(normalized["block_plan"]), set(block))
        self.assertEqual(
            set(normalized["state_delta"]),
            {
                "block_id",
                "completed_episode_range",
                "running_character_state",
                "unresolved_threads",
                "next_block_handoff",
                "completed_event_ids",
                "active_event_ids",
                "foreshadowing_ids",
            },
        )
        self.assertEqual(normalized["state_delta"]["running_character_state"], {"方华": "开始主动逃离"})
        self.assertEqual(normalized["state_delta"]["next_block_handoff"], "方华已到校门口")
        self.assertEqual(normalized["state_delta"]["completed_event_ids"], [1, 2])
        self.assertEqual(normalized["state_delta"]["active_event_ids"], [])

    def test_episode_planning_block_preserves_story_time_regression_for_validation(self):
        """Verify episode planning block preserves story time regression for validation."""
        block = {
            "block_id": 2,
            "phase": "推进",
            "title": "次日追查",
            "start_episode": 5,
            "end_episode": 5,
            "episode_count": 1,
        }
        block_values = {
            "episode_planning_scope": {
                "current_block": block,
                "global_target_episodes": 40,
                "mode": "internal_block",
                "previous_handoff": {
                    "last_story_time": {
                        "day_index": 4,
                        "time_label": "夜",
                        "elapsed_from_previous": "当日夜晚",
                    }
                },
            }
        }
        raw = {
            "episode_outlines": [
                {
                    "episode_num": 5,
                    "title": "次日追查",
                    "story_time": {
                        "day_index": 3,
                        "time_label": "日",
                        "elapsed_from_previous": "次日早晨",
                    },
                }
            ]
        }

        normalized = pipeline_runner.normalize_episode_planning_block_output(raw, block_values)
        episode = normalized["episode_outlines"][0]

        self.assertEqual(episode["story_time"]["day_index"], 3)
        self.assertNotIn("story_time_repair_trace", episode)

    def test_episode_planning_normalizes_scalar_contract_lists_before_local_handoff(self):
        """Verify episode planning normalizes scalar contract lists before local handoff."""
        payload = {
            "episode_outlines": [
                {
                    "episode_num": 1,
                    "event_ids": 1,
                    "foreshadowing_ids": "FS-1",
                    "consumed_child_beats": "吃下第一口菜",
                    "required_character_names": "方华",
                    "appearing_character_names": None,
                    "adapted_plot_point_ids": 2,
                    "unresolved_threads_after_episode": "花生酱尚未处理",
                    "scene_plan": {
                        "scene_no": "1-1",
                        "appearing_character_names": "方华",
                        "must_include_beats": "收起录取短信",
                        "visible_space_tokens": "厨房",
                    },
                    "narration_device_plan": {
                        "approved_flashback_time_deviation_ids": "TD-1",
                        "approved_os_time_deviation_ids": None,
                        "visualized_time_deviation_ids": "TD-2",
                        "deleted_or_rewritten_time_deviation_ids": [],
                    },
                    "target_script_density": {
                        "must_cover_beats": "拒绝吃菜",
                        "optional_compression_beats": None,
                    },
                }
            ]
        }

        normalized, report = pipeline_runner.normalize_stage_output_with_report(
            "07_episode_planning",
            payload,
        )
        episode = normalized["episode_outlines"][0]

        self.assertEqual(episode["event_ids"], [1])
        self.assertEqual(episode["foreshadowing_ids"], ["FS-1"])
        self.assertEqual(episode["consumed_child_beats"], ["吃下第一口菜"])
        self.assertEqual(episode["required_character_names"], ["方华"])
        self.assertEqual(episode["appearing_character_names"], [])
        self.assertEqual(episode["adapted_plot_point_ids"], [2])
        self.assertEqual(episode["unresolved_threads_after_episode"], ["花生酱尚未处理"])
        self.assertIsInstance(episode["scene_plan"], list)
        self.assertEqual(episode["scene_plan"][0]["appearing_character_names"], ["方华"])
        self.assertEqual(episode["scene_plan"][0]["must_include_beats"], ["收起录取短信"])
        self.assertEqual(episode["scene_plan"][0]["visible_space_tokens"], ["厨房"])
        self.assertEqual(
            episode["narration_device_plan"]["approved_flashback_time_deviation_ids"],
            ["TD-1"],
        )
        self.assertEqual(episode["narration_device_plan"]["approved_os_time_deviation_ids"], [])
        self.assertEqual(episode["target_script_density"]["must_cover_beats"], ["拒绝吃菜"])
        self.assertEqual(episode["target_script_density"]["optional_compression_beats"], [])
        self.assertIn(
            "normalize_episode_contract_list_fields",
            [item["operation"] for item in report["operations"]],
        )

    def test_episode_planning_chunk_merge_preserves_public_block_allocation(self):
        """Verify episode planning chunk merge preserves public block allocation."""
        allocation_blocks = [
            {
                "block_id": 1,
                "phase": "篇章1",
                "title": "首战",
                "start_episode": 1,
                "end_episode": 3,
                "episode_count": 3,
                "goal": "破局",
                "antagonist": "反派",
                "hook": "追问",
                "foreshadowing_plan": {"plant": []},
            }
        ]
        call_blocks = pipeline_runner.split_blocks_for_episode_chunks(allocation_blocks, max_episodes_per_chunk=1)
        block_outputs = [
            {
                "block_plan": call_blocks[0],
                "episode_outlines": [{"episode_num": 1, "title": "第1集"}],
                "state_delta": {},
            },
            {
                "block_plan": call_blocks[1],
                "episode_outlines": [{"episode_num": 2, "title": "第2集"}],
                "state_delta": {},
            },
            {
                "block_plan": call_blocks[2],
                "episode_outlines": [{"episode_num": 3, "title": "第3集"}],
                "state_delta": {},
            },
        ]

        merged = pipeline_runner.merge_episode_planning_blocks(
            block_outputs,
            call_blocks,
            allocation_blocks=allocation_blocks,
        )

        self.assertEqual(len(merged["block_plans"]), 1)
        self.assertEqual(
            merged["episode_allocation"],
            [{"block_id": 1, "start_episode": 1, "end_episode": 3, "episode_count": 3}],
        )
        self.assertEqual([item["episode_num"] for item in merged["episode_outlines"]], [1, 2, 3])

    def test_repair_episode_pattern_family_streaks_uses_conflict_mode_trace(self):
        """Verify repair episode pattern family streaks uses conflict mode trace."""
        data = {
            "episode_outlines": [
                {"episode_num": 1, "pattern_family": "oppression_escalation", "conflict_mode": "moral_blackmail"},
                {"episode_num": 2, "pattern_family": "oppression_escalation", "conflict_mode": "information_warfare"},
                {"episode_num": 3, "pattern_family": "oppression_escalation", "conflict_mode": "conspiracy_execution"},
            ]
        }

        repaired = pipeline_runner.repair_episode_pattern_family_streaks(data, max_streak=2)
        episode3 = repaired["episode_outlines"][2]

        self.assertEqual(episode3["pattern_family"], "hidden_conspiracy")
        self.assertEqual(episode3["pattern_family_repair_trace"][0]["original_pattern_family"], "oppression_escalation")
        self.assertEqual(episode3["pattern_family_repair_trace"][0]["conflict_mode"], "conspiracy_execution")

    def test_repair_episode_pattern_family_streaks_uses_chinese_conflict_mode(self):
        """Verify repair episode pattern family streaks uses chinese conflict mode."""
        data = {
            "episode_outlines": [
                {"episode_num": 3, "pattern_family": "合同武器", "conflict_mode": "经济威胁"},
                {"episode_num": 4, "pattern_family": "合同武器", "conflict_mode": "情报博弈"},
                {"episode_num": 5, "pattern_family": "合同武器", "conflict_mode": "资源拉拢"},
            ]
        }

        repaired = pipeline_runner.repair_episode_pattern_family_streaks(data, max_streak=2)
        episode5 = repaired["episode_outlines"][2]

        self.assertEqual(episode5["pattern_family"], "资源拉拢")
        self.assertEqual(episode5["pattern_family_repair_trace"][0]["original_pattern_family"], "合同武器")
        self.assertEqual(episode5["pattern_family_repair_trace"][0]["conflict_mode"], "资源拉拢")

    def test_repair_episode_scene_plan_boundaries_merges_same_setting_same_cast(self):
        """Verify repair episode scene plan boundaries merges same setting same cast."""
        data = {
            "episode_outlines": [
                {
                    "episode_num": 3,
                    "scene_plan": [
                        {
                            "scene_no": 1,
                            "location": "旧厂会议室",
                            "time": "日",
                            "space": "内",
                            "appearing_character_names": ["陈寻", "刘波", "吴经理"],
                            "scene_purpose": "刘波推追薪协议",
                            "must_include_beats": ["刘波将追薪协议推到陈寻面前"],
                            "scene_boundary_reason": "施压动作",
                        },
                        {
                            "scene_no": 2,
                            "location": "旧厂会议室",
                            "time": "日",
                            "space": "内",
                            "appearing_character_names": ["陈寻", "刘波", "吴经理"],
                            "scene_purpose": "陈寻拒签转身离开",
                            "must_include_beats": ["陈寻将协议推回", "刘波拍桌威胁"],
                            "scene_boundary_reason": "连续动作延续，与scene_no 1实为同一连续场",
                        },
                    ],
                }
            ]
        }

        repaired = pipeline_runner.repair_episode_scene_plan_boundaries(data)
        episode = repaired["episode_outlines"][0]

        self.assertEqual(len(episode["scene_plan"]), 1)
        self.assertEqual(episode["scene_plan"][0]["scene_no"], 1)
        self.assertIn("陈寻将协议推回", episode["scene_plan"][0]["must_include_beats"])
        self.assertEqual(episode["scene_plan_repair_trace"][0]["reason"], "same_setting_same_cast_merge")

    def test_repair_episode_narration_device_plans_adds_default_zero_plan(self):
        """Verify repair episode narration device plans adds default zero plan."""
        repaired = pipeline_runner.repair_episode_narration_device_plans([{"episode_num": 1}])

        plan = repaired[0]["narration_device_plan"]
        self.assertEqual(plan["planned_os_count"], 0)
        self.assertEqual(plan["planned_flashback_count"], 0)
        self.assertEqual(plan["planned_vo_count"], 0)
        self.assertEqual(
            repaired[0]["narration_device_plan_repair_trace"][0]["reason"],
            "missing_narration_device_plan_default_zero",
        )

    def test_repair_episode_narration_device_plans_allows_planned_phone_vo(self):
        """Verify repair episode narration device plans allows planned phone vo."""
        repaired = pipeline_runner.repair_episode_narration_device_plans(
            [
                {
                    "episode_num": 3,
                    "scene_plan": [
                        {
                            "scene_no": 3,
                            "scene_purpose": "于涛主动来电，陈寻确认见面意向",
                            "must_include_beats": ["于涛电话主动说听说陈寻离职了"],
                        }
                    ],
                    "narration_device_plan": {
                        "planned_os_count": 0,
                        "planned_flashback_count": 0,
                        "planned_vo_count": 0,
                        "reason": "用当下动作和电话推进",
                        "visual_replacement_strategy": "用手机屏幕和对话替代说明",
                    },
                }
            ]
        )

        plan = repaired[0]["narration_device_plan"]
        self.assertEqual(plan["planned_vo_count"], 1)
        self.assertIn(
            "scene_plan_requires_vo_budget",
            [item["reason"] for item in repaired[0]["narration_device_plan_repair_trace"]],
        )

    def test_repair_episode_character_name_fields_unifies_aliases_and_required_appearing(self):
        """Verify repair episode character name fields unifies aliases and required appearing."""
        data = {
            "episode_outlines": [
                {
                    "episode_num": 31,
                    "required_character_names": ["女主（未命名）", "沈浩"],
                    "appearing_character_names": ["女主（未命名）"],
                }
            ]
        }

        repaired = pipeline_runner.repair_episode_character_name_fields(
            data,
            allowed_character_names=["女主（未命名）", "女主", "沈浩"],
        )
        episode = repaired["episode_outlines"][0]

        self.assertEqual(episode["required_character_names"], ["女主", "沈浩"])
        self.assertEqual(episode["appearing_character_names"], ["女主", "沈浩"])
        self.assertTrue(episode["character_name_repair_trace"])

    def test_repair_episode_character_name_fields_adds_phone_voice_role_to_scene_plan(self):
        """Verify repair episode character name fields adds phone voice role to scene plan."""
        data = {
            "episode_outlines": [
                {
                    "episode_num": 1,
                    "required_character_names": ["陈寻", "王辉"],
                    "appearing_character_names": ["陈寻", "王辉"],
                    "scene_plan": [
                        {
                            "scene_no": 3,
                            "location": "咖啡馆",
                            "time": "傍晚",
                            "space": "内",
                            "appearing_character_names": ["陈寻"],
                            "scene_purpose": "电话钩子",
                            "must_include_beats": ["陈寻拨出王辉电话，听筒传来「喂，陈总」"],
                            "scene_boundary_reason": "时间推移",
                        }
                    ],
                }
            ]
        }

        repaired = pipeline_runner.repair_episode_character_name_fields(
            data,
            allowed_character_names=["陈寻", "王辉"],
        )

        scene = repaired["episode_outlines"][0]["scene_plan"][0]
        self.assertEqual(scene["appearing_character_names"], ["陈寻", "王辉"])
        trace = repaired["episode_outlines"][0]["character_name_repair_trace"]
        self.assertEqual(trace[0]["field"], "scene_plan.appearing_character_names")
        self.assertEqual(trace[0]["added_mentioned_names"], ["王辉"])

    def test_repair_episode_child_beat_accounting_adds_explicit_episode_beats(self):
        """Verify repair episode child beat accounting adds explicit episode beats."""
        data = {
            "episode_outlines": [
                {
                    "episode_num": 1,
                    "block_id": 1,
                    "event_ids": [1],
                    "consumed_child_beats": ["第1集：女主日常遛球球"],
                    "event_consumption_status": "ongoing",
                },
                {
                    "episode_num": 2,
                    "block_id": 1,
                    "event_ids": [1],
                    "consumed_child_beats": ["第2集：闪回领养球球"],
                    "event_consumption_status": "completed",
                },
                {
                    "episode_num": 3,
                    "block_id": 1,
                    "event_ids": [2],
                    "consumed_child_beats": ["第3集：沈浩嫌弃狗毛"],
                    "event_consumption_status": "ongoing",
                },
            ]
        }
        event_pool = [
            {
                "id": 1,
                "target_block": 1,
                "episode_window": {"start": 1, "end": 3},
                "child_beats": [
                    "第1集：女主日常遛球球，展示老狗行动迟缓但默契十足",
                    "第2集：闪回小学一百分领球球回家，建立15年时间锚",
                    "第3集：球球生病去宠物医院，女主焦虑守夜，暗示老狗时日无多",
                ],
            }
        ]

        repaired = pipeline_runner.repair_episode_child_beat_accounting(data, event_pool=event_pool)
        episode2 = repaired["episode_outlines"][1]
        episode3 = repaired["episode_outlines"][2]

        self.assertEqual(episode2["event_consumption_status"], "partial")
        self.assertIn(1, episode3["event_ids"])
        self.assertIn("第3集：球球生病去宠物医院，女主焦虑守夜，暗示老狗时日无多", episode3["consumed_child_beats"])
        self.assertEqual(episode3["event_consumption_status"], "completed")
        self.assertTrue(episode3["child_beat_accounting_repair_trace"])

    def test_repair_cross_block_opening_recap_uses_previous_bridge(self):
        """Verify repair cross block opening recap uses previous bridge."""
        data = {
            "episode_outlines": [
                {
                    "episode_num": 20,
                    "block_id": 2,
                    "closing_beat": "漏斗被强行塞入嘴中，糊状物灌下，女主满嘴是血地咳嗽。",
                    "next_episode_start_state": "女主被迫咽下食物后，在黑夜中第一次尝试磨柱。",
                    "consumed_child_beats": ["钢铁漏斗灌食"],
                },
                {
                    "episode_num": 21,
                    "block_id": 3,
                    "opening_beat": "漏斗被强行塞入嘴中，糊状物灌下，女主满嘴是血地咳嗽。",
                },
            ]
        }

        repaired = pipeline_runner.repair_cross_block_opening_recap(data)
        episode21 = repaired["episode_outlines"][1]

        self.assertIn("第一次尝试磨柱", episode21["opening_beat"])
        self.assertTrue(episode21["opening_beat_repair_trace"])

    def test_repair_episode_conflict_mode_streaks_uses_action_trace(self):
        """Verify repair episode conflict mode streaks uses action trace."""
        data = {
            "episode_outlines": [
                {
                    "episode_num": 7,
                    "conflict_mode": "physical_confrontation",
                    "pattern_family": "counterattack_burst",
                    "counterattack": "女主用热奶茶砸向车窗逼停车辆",
                },
                {
                    "episode_num": 8,
                    "conflict_mode": "physical_confrontation",
                    "pattern_family": "counterattack_burst",
                    "counterattack": "女主被掐出淤青后砸碎手机和玻璃",
                },
                {
                    "episode_num": 9,
                    "conflict_mode": "physical_confrontation",
                    "pattern_family": "physical_coercion",
                    "main_conflict": "侄子摔狗后女主扇耳光",
                },
            ]
        }

        repaired = pipeline_runner.repair_episode_conflict_mode_streaks(data, max_streak=2)
        episode9 = repaired["episode_outlines"][2]

        self.assertEqual(episode9["conflict_mode"], "pet_abuse_public_retaliation")
        self.assertEqual(episode9["conflict_mode_repair_trace"][0]["original_conflict_mode"], "physical_confrontation")

    def test_repair_episode_conflict_mode_streaks_splits_chase_phases(self):
        """Verify repair episode conflict mode streaks splits chase phases."""
        data = {
            "episode_outlines": [
                {
                    "episode_num": 31,
                    "conflict_mode": "chase_pursuit",
                    "pattern_family": "final_showdown",
                    "main_conflict": "沈浩开大灯在山道追杀女主",
                },
                {
                    "episode_num": 32,
                    "conflict_mode": "chase_pursuit",
                    "pattern_family": "final_showdown",
                    "main_conflict": "女主向老人求助用座机报警定位",
                },
                {
                    "episode_num": 33,
                    "conflict_mode": "chase_pursuit",
                    "pattern_family": "pursuit_escalation",
                    "main_conflict": "沈浩驾车撞破院门和土屋",
                },
            ]
        }

        repaired = pipeline_runner.repair_episode_conflict_mode_streaks(data, max_streak=2)

        self.assertEqual(repaired["episode_outlines"][2]["conflict_mode"], "vehicle_crash_assault")

    def test_repair_episode_active_motion_fields_replaces_empty_non_epilogue_motion(self):
        """Verify repair episode active motion fields replaces empty non epilogue motion."""
        data = {
            "episode_outlines": [
                {
                    "episode_num": 1,
                    "title": "幸福基线",
                    "main_conflict": "无外部直接冲突",
                    "counterattack": "无",
                    "required_character_names": ["女主"],
                    "source_anchor": "球球十五年陪伴",
                    "is_epilogue": False,
                }
            ]
        }

        repaired = pipeline_runner.repair_episode_active_motion_fields(data)
        episode = repaired["episode_outlines"][0]

        self.assertNotIn("无", episode["counterattack"])
        self.assertIn("active_motion_repair_trace", episode)
        self.assertEqual(len(episode["active_motion_repair_trace"]), 2)

    def test_repair_episode_character_name_fields_adds_known_names_mentioned_in_outline(self):
        """Verify repair episode character name fields adds known names mentioned in outline."""
        data = {
            "episode_outlines": [
                {
                    "episode_num": 1,
                    "required_character_names": ["女主"],
                    "appearing_character_names": ["女主"],
                    "opening_beat": "婆婆盯着女主怀里的球球，要求把狗送走",
                    "closing_beat": "女主抱紧球球回房",
                }
            ]
        }

        repaired = pipeline_runner.repair_episode_character_name_fields(
            data,
            allowed_character_names=["女主", "婆婆", "球球"],
        )
        episode = repaired["episode_outlines"][0]

        self.assertEqual(episode["appearing_character_names"], ["女主", "婆婆", "球球"])
        self.assertTrue(any("added_mentioned_names" in item for item in episode["character_name_repair_trace"]))

    def test_build_qa_summary_has_go_no_go_status(self):
        """Verify build qa summary has go no go status."""
        stage_outputs = {
            "05_plot_character_adaptation": {"event_pool": [{"id": 1, "target_block": 1}], "foreshadowing_pool": []},
            "06_script_outline_design": {"block_state_plan": [], "event_release_schedule": []},
        }
        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            [{"episode_num": 1, "block_id": 2, "event_ids": [1], "main_conflict": "冲突", "counterattack": "反击"}],
            target_episodes=1,
            derived_config={"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2},
        )

        self.assertEqual(qa["overall_status"], "PASS")
        self.assertEqual(qa["generation_status"], "PASS")
        self.assertEqual(qa["quality_status"], "WARN")
        self.assertFalse(qa["blocking_issues"])
        self.assertTrue(qa["warnings"])

    def test_build_qa_summary_warns_on_boundary_and_content_sensitivity_without_blocking(self):
        """Verify build qa summary warns on boundary and content sensitivity without blocking."""
        stage_outputs = {
            "05_plot_character_adaptation": {
                "event_pool": [
                    {
                        "id": 1,
                        "target_block": 1,
                        "episode_window": {"start": 1, "end": 1},
                        "not_before_episode": 1,
                        "not_after_episode": 1,
                        "content_sensitivity_risk": "high",
                        "title": "风险证据",
                        "source_anchor": "全村公开播放隐私视频",
                    }
                ],
                "foreshadowing_pool": [],
            },
            "06_script_outline_design": {
                    "block_state_plan": [{"block_id": 1}],
                    "event_release_schedule": [{"block_id": 1}],
                },
        }
        episode = {
            "episode_num": 1,
            "block_id": 1,
            "event_ids": [1],
            "main_conflict": "冲突",
            "counterattack": "反击",
            "ending_hook": "钩子",
            "conflict_mode": "rumor",
            "pattern_family": "rumor",
            "boundary_check": {
                    "risk_level": "high",
                    "protagonist_action": "当众反制",
                    "why_allowed": "原著激烈冲突",
                    "mitigation": "记录为风险",
                },
            "content_sensitivity_check": {"risk_level": "high", "risk_reason": "熟人围观压力强", "mitigation": "不写露骨过程"},
        }

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            [episode],
            target_episodes=1,
            derived_config={"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2},
        )

        self.assertEqual(qa["overall_status"], "PASS")
        self.assertFalse(any(item.get("check") == "content_sensitivity" for item in qa["blocking_issues"]))
        self.assertFalse(any(item.get("check") == "boundary_risk" for item in qa["blocking_issues"]))
        self.assertEqual(qa["check_results"]["boundary_risk"], "WARN")
        self.assertEqual(qa["check_results"]["content_sensitivity"], "WARN")
        self.assertTrue(any(item.get("check") == "content_sensitivity" for item in qa["warnings"]))
        self.assertTrue(any(item.get("check") == "boundary_risk" for item in qa["warnings"]))
        self.assertTrue(qa["longform_pacing"]["content_sensitivity_risks"])

    def test_build_qa_summary_blocks_narration_device_budget_overuse(self):
        """Verify build qa summary blocks narration device budget overuse."""
        stage_outputs = {
            "05_plot_character_adaptation": {
                "event_pool": [{"id": 1, "target_block": 1, "episode_window": {"start": 1, "end": 2}}],
                "foreshadowing_pool": [],
            },
            "06_script_outline_design": {
                    "block_state_plan": [{"block_id": 1}],
                    "event_release_schedule": [{"block_id": 1}],
                },
        }
        episodes = [
            {
                "episode_num": 1,
                "block_id": 1,
                "event_ids": [1],
                "main_conflict": "开除通知",
                "counterattack": "陈寻确认合同",
                "ending_hook": "客户只认陈寻",
                "conflict_mode": "dismissal_pressure",
                "pattern_family": "workplace_counter",
                "narration_device_plan": {
                    "planned_os_count": 3,
                    "planned_flashback_count": 2,
                    "planned_vo_count": 0,
                    "reason": "前三集铺垫",
                    "visual_replacement_strategy": "用电话和合同替代解释",
                },
            },
            {
                "episode_num": 2,
                "block_id": 1,
                "event_ids": [1],
                "main_conflict": "老板压价",
                "counterattack": "陈寻转向竞品厂",
                "ending_hook": "竞品老板给合同",
                "conflict_mode": "contract_turn",
                "pattern_family": "business_counter",
                "narration_device_plan": {
                    "planned_os_count": 1,
                    "planned_flashback_count": 0,
                    "planned_vo_count": 0,
                    "reason": "补充判断",
                    "visual_replacement_strategy": "用文件夹动作替代",
                },
            },
        ]

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            episodes,
            target_episodes=2,
            derived_config={"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2},
            validation_mode="strict",
        )

        self.assertEqual(qa["check_results"]["narration_device_budget"], "BLOCK")
        self.assertTrue(any(item.get("check") == "narration_device_budget" for item in qa["blocking_issues"]))

    def test_build_qa_summary_blocks_flashback_screening_misalignment(self):
        """Verify build qa summary blocks flashback screening misalignment."""
        flashback_screening = pipeline_runner.dry_run_payload("04a_flashback_screening", {})
        flashback_screening["retained_time_deviations"] = []
        flashback_screening["rewrite_time_deviations"] = [
            {
                "id": "td_b_001",
                "grade": "B",
                "position": "第1章",
                "characters": ["陈寻"],
                "content_summary": "温情回忆",
                "q1_structure_necessity": "否",
                "q2_information_necessity": "否",
                "decision": "改写为顺叙",
                "reason": "仅渲染情绪",
                "quota_count": 0,
            }
        ]
        stage_outputs = {
            "04a_flashback_screening": flashback_screening,
            "05_plot_character_adaptation": {
                "event_pool": [{"id": 1, "target_block": 1, "episode_window": {"start": 1, "end": 1}}],
                "foreshadowing_pool": [],
            },
            "06_script_outline_design": {
                    "block_state_plan": [{"block_id": 1}],
                    "event_release_schedule": [{"block_id": 1}],
                },
        }
        episodes = [
            {
                "episode_num": 1,
                "block_id": 1,
                "event_ids": [1],
                "main_conflict": "旧事施压",
                "counterattack": "陈寻拿证据",
                "ending_hook": "回忆被翻出",
                "conflict_mode": "evidence_turn",
                "pattern_family": "evidence_turn",
                "narration_device_plan": {
                    "planned_os_count": 0,
                    "planned_flashback_count": 1,
                    "planned_flashback_quota_count": 1,
                    "planned_vo_count": 0,
                    "reason": "误用装饰级回忆",
                    "visual_replacement_strategy": "本应转为当下证据",
                    "approved_time_deviation_ids": ["td_b_001"],
                },
            }
        ]

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            episodes,
            target_episodes=1,
            derived_config={"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2},
            validation_mode="strict",
        )

        self.assertEqual(qa["check_results"]["flashback_screening_alignment"], "BLOCK")
        self.assertTrue(any(item.get("check") == "flashback_screening_alignment" for item in qa["blocking_issues"]))

    def test_build_qa_summary_blocks_forbidden_script_idioms(self):
        """Verify build qa summary blocks forbidden script idioms."""
        stage_outputs = {
            "05_plot_character_adaptation": {
                "event_pool": [{"id": 1, "target_block": 1, "episode_window": {"start": 1, "end": 1}}],
                "foreshadowing_pool": [],
            },
            "06_script_outline_design": {
                    "block_state_plan": [{"block_id": 1}],
                    "event_release_schedule": [{"block_id": 1}],
                },
        }
        episode = {
            "episode_num": 1,
            "block_id": 1,
            "event_ids": [1],
            "main_conflict": "开除通知",
            "counterattack": "陈寻确认合同",
            "ending_hook": "客户只认陈寻",
            "conflict_mode": "dismissal_pressure",
            "pattern_family": "workplace_counter",
            "narration_device_plan": {
                "planned_os_count": 0,
                "planned_flashback_count": 0,
                "planned_vo_count": 0,
                "reason": "用当下对话交代",
                "visual_replacement_strategy": "用手机退群提示替代旁白",
            },
        }
        final_scripts = [
            {
                "episode_num": 1,
                "final_script": "第一集\n\n1-1    公司门口    日    外\n出场人物：陈寻、吴经理\n△吴经理脸上闪过一丝得意。\n陈寻（看着手机）：你继续。",
            }
        ]

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            [episode],
            target_episodes=1,
            derived_config={"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2},
            final_scripts=final_scripts,
            validation_mode="strict",
        )

        self.assertEqual(qa["check_results"]["forbidden_script_idioms"], "BLOCK")
        self.assertTrue(any(item.get("check") == "forbidden_script_idioms" for item in qa["blocking_issues"]))

    def test_build_qa_summary_warns_on_missing_consumed_child_beats_without_blocking(self):
        """Verify build qa summary warns on missing consumed child beats without blocking."""
        stage_outputs = {
            "05_plot_character_adaptation": {
                "event_pool": [
                    {
                        "id": 1,
                        "target_block": 1,
                        "episode_window": {"start": 1, "end": 1},
                        "title": "关键事件",
                    }
                ],
                "foreshadowing_pool": [],
            },
            "06_script_outline_design": {
                    "block_state_plan": [{"block_id": 1}],
                    "event_release_schedule": [{"block_id": 1}],
                },
        }
        episode = {
            "episode_num": 1,
            "block_id": 1,
            "event_ids": [1],
            "main_conflict": "冲突",
            "counterattack": "反击",
            "ending_hook": "钩子",
            "conflict_mode": "evidence_turn",
            "pattern_family": "evidence_turn",
            "boundary_check": {
                    "risk_level": "low",
                    "protagonist_action": "留证",
                    "why_allowed": "剧情需要",
                    "mitigation": "无",
                },
            "content_sensitivity_check": {"risk_level": "low", "risk_reason": "无", "mitigation": "无"},
            "consumed_child_beats": [],
        }

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            [episode],
            target_episodes=1,
            derived_config={"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2},
        )

        self.assertEqual(qa["overall_status"], "PASS")
        self.assertEqual(qa["check_results"]["child_beat_accounting"], "WARN")
        self.assertTrue(any(item.get("check") == "child_beat_accounting" for item in qa["warnings"]))

    def test_build_qa_summary_warns_when_completed_event_child_beats_are_not_covered(self):
        """Verify build qa summary warns when completed event child beats are not covered."""
        stage_outputs = {
            "05_plot_character_adaptation": {
                "event_pool": [
                    {
                        "id": 1,
                        "target_block": 1,
                        "episode_window": {"start": 1, "end": 2},
                        "title": "偷狗执行",
                        "child_beats": ["亲戚用备用钥匙进屋", "侄子抱球球上车"],
                    }
                ],
                "foreshadowing_pool": [],
            },
            "06_script_outline_design": {
                    "block_state_plan": [{"block_id": 1}],
                    "event_release_schedule": [{"block_id": 1}],
                },
        }
        episode = {
            "episode_num": 1,
            "block_id": 1,
            "event_ids": [1],
            "main_conflict": "亲戚上门制造压力",
            "counterattack": "女主反锁卧室",
            "ending_hook": "门外响起钥匙声",
            "conflict_mode": "home_intrusion",
            "pattern_family": "home_intrusion",
            "boundary_check": {"risk_level": "low", "protagonist_action": "反锁", "why_allowed": "自保", "mitigation": "无"},
            "content_sensitivity_check": {"risk_level": "low", "risk_reason": "无", "mitigation": "无"},
            "consumed_child_beats": ["亲戚上门送礼", "安排车位等待"],
            "event_consumption_status": "completed",
        }

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            [episode],
            target_episodes=1,
            derived_config={"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2},
        )

        self.assertEqual(qa["overall_status"], "PASS")
        self.assertEqual(qa["check_results"]["child_beat_accounting"], "WARN")
        self.assertFalse(any(item.get("check") == "child_beat_accounting" for item in qa["blocking_issues"]))
        warning = next(item for item in qa["warnings"] if item.get("check") == "child_beat_accounting")
        self.assertTrue(
            any(item.get("issue") == "completed_event_child_beats_not_covered" for item in warning["items"]),
        )

    def test_build_qa_summary_uses_stable_child_beat_alignment_without_legacy_warning(self):
        """Verify build qa summary uses stable child beat alignment without legacy warning."""
        stage_outputs = {
            "05_plot_character_adaptation": {
                "event_pool": [
                    {
                        "id": 1,
                        "target_block": 1,
                        "episode_window": {"start": 1, "end": 1},
                        "title": "关键事件",
                        "child_beats": [
                            {
                                "child_beat_id": "E1-B1",
                                "action": "主角拿到证据",
                                "completion_evidence": "证据出现在主角手中",
                            }
                        ],
                    }
                ],
                "foreshadowing_pool": [],
            },
            "06_script_outline_design": {
                "block_state_plan": [{"block_id": 1}],
                "event_release_schedule": [{"block_id": 1}],
            },
        }
        episode = {
            "episode_num": 1,
            "block_id": 1,
            "event_ids": [1],
            "consumed_child_beat_ids": ["E1-B1"],
            "event_consumption_status": "completed",
            "main_conflict": "争夺证据",
            "counterattack": "主角保存证据",
            "ending_hook": "对手发现证据丢失",
            "conflict_mode": "evidence_turn",
            "pattern_family": "evidence_turn",
            "boundary_check": {"risk_level": "low"},
            "content_sensitivity_check": {"risk_level": "low"},
        }

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            [episode],
            target_episodes=1,
            derived_config={"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2},
        )

        self.assertEqual(qa["check_results"]["event_child_beat_alignment"], "PASS")
        self.assertEqual(qa["check_results"]["child_beat_accounting"], "PASS")
        self.assertFalse(any(item.get("check") == "child_beat_accounting" for item in qa["warnings"]))

    def test_build_qa_summary_warns_when_script_mentions_unlisted_appearing_character(self):
        """Verify build qa summary warns when script mentions unlisted appearing character."""
        stage_outputs = {
            "05_plot_character_adaptation": {
                "event_pool": [{"id": 1, "target_block": 1, "episode_window": {"start": 1, "end": 1}, "title": "家中施压"}],
                "foreshadowing_pool": [],
                "expanded_character_network": [{"name": "女主"}, {"name": "婆婆"}, {"name": "球球"}],
            },
            "06_script_outline_design": {
                    "block_state_plan": [{"block_id": 1}],
                    "event_release_schedule": [{"block_id": 1}],
                },
        }
        episode = {
            "episode_num": 1,
            "block_id": 1,
            "event_ids": [1],
            "main_conflict": "婆婆逼女主送走球球",
            "counterattack": "女主拒绝",
            "ending_hook": "婆婆暗中打电话",
            "conflict_mode": "family_pressure",
            "pattern_family": "family_pressure",
            "appearing_character_names": ["女主", "球球"],
            "boundary_check": {"risk_level": "low", "protagonist_action": "拒绝", "why_allowed": "自保", "mitigation": "无"},
            "content_sensitivity_check": {"risk_level": "low", "risk_reason": "无", "mitigation": "无"},
        }

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            [episode],
            target_episodes=1,
            derived_config={"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2},
            final_scripts=[{"episode_num": 1, "final_script": "# 第1集\n婆婆盯着女主怀里的球球，低声说必须送走。"}],
            canonical_story_lock={"character_names": ["女主", "婆婆", "球球"], "protagonist": "女主"},
        )

        self.assertEqual(qa["overall_status"], "PASS")
        self.assertEqual(qa["check_results"]["appearing_character_coverage"], "WARN")
        warning = next(item for item in qa["warnings"] if item.get("check") == "appearing_character_coverage")
        self.assertEqual(warning["items"][0]["missing_appearing_character_names"], ["婆婆"])

    def test_build_qa_summary_ignores_dialogue_only_character_mentions_for_coverage(self):
        """Verify build qa summary ignores dialogue only character mentions for coverage."""
        stage_outputs = {
            "05_plot_character_adaptation": {
                "event_pool": [{"id": 1, "target_block": 1, "episode_window": {"start": 1, "end": 1}, "title": "合同施压"}],
                "foreshadowing_pool": [],
                "expanded_character_network": [{"name": "陈寻"}, {"name": "刘波"}, {"name": "吴经理"}],
            },
            "06_script_outline_design": {
                    "block_state_plan": [{"block_id": 1}],
                    "event_release_schedule": [{"block_id": 1}],
                },
        }
        episode = {
            "episode_num": 1,
            "block_id": 1,
            "event_ids": [1],
            "main_conflict": "刘波施压",
            "counterattack": "陈寻拒绝",
            "ending_hook": "陈寻离开",
            "conflict_mode": "contract_pressure",
            "pattern_family": "business_pressure",
            "appearing_character_names": ["陈寻", "刘波"],
            "boundary_check": {"risk_level": "low", "protagonist_action": "拒绝", "why_allowed": "自保", "mitigation": "无"},
            "content_sensitivity_check": {"risk_level": "low", "risk_reason": "无", "mitigation": "无"},
        }
        script = "\n".join(
            [
                "第一集",
                "",
                "1-1    咖啡馆内    日    内",
                "出场人物：陈寻、刘波",
                "刘波（手按合同）：吴经理当时处理不当。",
                "陈寻（看着合同）：你继续。",
            ]
        )

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            [episode],
            target_episodes=1,
            derived_config=(
                {"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2, "script_length_chars": "20-800"}
            ),
            final_scripts=[{"episode_num": 1, "final_script": script}],
            canonical_story_lock={"character_names": ["陈寻", "刘波", "吴经理"], "protagonist": "陈寻"},
        )

        self.assertEqual(qa["check_results"]["appearing_character_coverage"], "PASS")

    def test_build_qa_summary_warns_on_short_script_pacing_without_blocking(self):
        """Verify build qa summary warns on short script pacing without blocking."""
        stage_outputs = {
            "05_plot_character_adaptation": {
                "event_pool": [{"id": 1, "target_block": 1, "episode_window": {"start": 1, "end": 1}, "title": "合同施压"}],
                "foreshadowing_pool": [],
                "expanded_character_network": [{"name": "陈寻"}, {"name": "刘波"}],
            },
            "06_script_outline_design": {
                    "block_state_plan": [{"block_id": 1}],
                    "event_release_schedule": [{"block_id": 1}],
                },
        }
        episode = {
            "episode_num": 1,
            "block_id": 1,
            "event_ids": [1],
            "main_conflict": "刘波施压",
            "counterattack": "陈寻拒绝",
            "ending_hook": "陈寻离开",
            "conflict_mode": "contract_pressure",
            "pattern_family": "business_pressure",
            "appearing_character_names": ["陈寻", "刘波"],
            "boundary_check": {"risk_level": "low", "protagonist_action": "拒绝", "why_allowed": "自保", "mitigation": "无"},
            "content_sensitivity_check": {"risk_level": "low", "risk_reason": "无", "mitigation": "无"},
        }
        short_script = "第一集\n\n1-1    咖啡馆内    日    内\n出场人物：陈寻、刘波\n△陈寻把合同推回。"

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            [episode],
            target_episodes=1,
            derived_config=(
                {"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2, "script_length_chars": "600-800"}
            ),
            final_scripts=[{"episode_num": 1, "final_script": short_script}],
            canonical_story_lock={"character_names": ["陈寻", "刘波"], "protagonist": "陈寻"},
        )

        self.assertEqual(qa["overall_status"], "PASS")
        self.assertEqual(qa["check_results"]["script_length_pacing"], "WARN")
        warning = next(item for item in qa["warnings"] if item.get("check") == "script_length_pacing")
        self.assertEqual(warning["items"][0]["target_min_chars"], 600)

    def test_build_qa_summary_warns_on_script_above_target_range_without_hard_cap(self):
        """Verify build qa summary warns on script above target range without hard cap."""
        stage_outputs = {
            "05_plot_character_adaptation": {
                "event_pool": [{"id": 1, "target_block": 1, "episode_window": {"start": 1, "end": 1}, "title": "合同施压"}],
                "foreshadowing_pool": [],
                "expanded_character_network": [{"name": "陈寻"}, {"name": "刘波"}],
            },
            "06_script_outline_design": {
                    "block_state_plan": [{"block_id": 1}],
                    "event_release_schedule": [{"block_id": 1}],
                },
        }
        episode = {
            "episode_num": 1,
            "block_id": 1,
            "event_ids": [1],
            "main_conflict": "刘波施压",
            "counterattack": "陈寻拒绝",
            "ending_hook": "陈寻离开",
            "conflict_mode": "contract_pressure",
            "pattern_family": "business_pressure",
            "appearing_character_names": ["陈寻", "刘波"],
            "boundary_check": {"risk_level": "low", "protagonist_action": "拒绝", "why_allowed": "自保", "mitigation": "无"},
            "content_sensitivity_check": {"risk_level": "low", "risk_reason": "无", "mitigation": "无"},
        }
        long_line = "△陈寻把合同逐页摊开，刘波抬手要按住纸面，陈寻把文件往回收。" * 28
        script = "\n".join(
            [
                "第一集",
                "",
                "1-1    咖啡馆内    日    内",
                "出场人物：陈寻、刘波",
                long_line,
                "陈寻（看向刘波）：你继续。",
            ]
        )

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            [episode],
            target_episodes=1,
            derived_config=(
                {"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2, "script_length_chars": "600-800"}
            ),
            final_scripts=[{"episode_num": 1, "final_script": script}],
            canonical_story_lock={"character_names": ["陈寻", "刘波"], "protagonist": "陈寻"},
        )

        self.assertEqual(qa["overall_status"], "PASS")
        self.assertEqual(qa["check_results"]["script_length_pacing"], "WARN")
        warning = next(item for item in qa["warnings"] if item.get("check") == "script_length_pacing")
        self.assertEqual(warning["items"][0]["target_max_chars"], 800)
        self.assertEqual(
            warning["items"][0]["detail"],
            "script is above configured pacing target; collect/report only, not a hard block",
        )

    def test_character_coverage_names_do_not_expand_bare_parent_aliases(self):
        """Verify character coverage names do not expand bare parent aliases."""
        names = pipeline_runner.collect_character_names_for_coverage(
            {"character_names": ["女主父母", "女主（未命名）"]},
            {"expanded_character_network": []},
        )

        self.assertIn("女主", names)
        self.assertIn("女主父母", names)
        self.assertIn("女主父亲", names)
        self.assertIn("女主母亲", names)
        self.assertNotIn("爸爸", names)
        self.assertNotIn("妈妈", names)

    def test_manifest_index_omits_stale_unrequested_episode_manifests(self):
        """Verify manifest index omits stale unrequested episode manifests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "manifest_test")
            for name in (
                "01_novel_summary.manifest.json",
                "07_episode_planning.block_01.manifest.json",
                "08_script_body_generation_ep001.manifest.json",
                "08_script_body_generation_ep010.manifest.json",
                "08_script_body_generation_ep011.manifest.json",
            ):
                (paths.manifests / name).write_text("{}", encoding="utf-8")

            index = pipeline_runner.build_manifest_index(paths, generated_episodes=[1, 10])

        self.assertIn("manifests/01_novel_summary.manifest.json", index)
        self.assertIn("manifests/07_episode_planning.block_01.manifest.json", index)
        self.assertIn("manifests/08_script_body_generation_ep001.manifest.json", index)
        self.assertIn("manifests/08_script_body_generation_ep010.manifest.json", index)
        self.assertNotIn("manifests/08_script_body_generation_ep011.manifest.json", index)

    def test_repair_episode_epilogue_budget_demotes_earliest_tail_episodes(self):
        """Verify repair episode epilogue budget demotes earliest tail episodes."""
        data = {
            "episode_outlines": [
                {"episode_num": 37, "is_epilogue": False},
                {"episode_num": 38, "is_epilogue": True},
                {"episode_num": 39, "is_epilogue": True},
                {"episode_num": 40, "is_epilogue": True},
            ]
        }

        repaired = pipeline_runner.repair_episode_epilogue_budget(data, max_epilogue=2)

        episodes = repaired["episode_outlines"]
        self.assertEqual([item["is_epilogue"] for item in episodes], [False, False, True, True])
        self.assertEqual(
            episodes[1]["epilogue_budget_repair_trace"][0]["reason"],
            "epilogue_budget_overrun_demote_earliest_tail_episode",
        )
        self.assertEqual(episodes[1]["epilogue_budget_repair_trace"][0]["kept_epilogue_episode_nums"], [39, 40])

    def test_repair_episode_narration_device_plans_counts_explicit_vo_and_phone_voice(self):
        """Verify repair episode narration device plans counts explicit vo and phone voice."""
        episodes = [
            {
                "episode_num": 1,
                "narration_device_plan": {
                    "planned_os_count": 0,
                    "planned_flashback_count": 0,
                    "planned_vo_count": 0,
                    "reason": "用屏幕信息替代旁白。",
                    "visual_replacement_strategy": "用手机和现场动作呈现。",
                },
                "scene_plan": [
                    {
                        "scene_no": 1,
                        "scene_purpose": "吴经理VO宣读群投票理由",
                        "must_include_beats": ["吴经理群消息VO：提请全员表决"],
                    },
                    {
                        "scene_no": 2,
                        "scene_purpose": "电话钩子",
                        "must_include_beats": ["陈寻拨出王辉电话，听筒传来「喂，陈总」"],
                    },
                ],
            }
        ]

        repaired = pipeline_runner.repair_episode_narration_device_plans(episodes)

        self.assertEqual(repaired[0]["narration_device_plan"]["planned_vo_count"], 2)
        self.assertIn(
            "scene_plan_requires_vo_budget",
            [item["reason"] for item in repaired[0]["narration_device_plan_repair_trace"]],
        )

    def test_llm_schema_localization_round_trips_nested_stage_payload(self):
        """Verify llm schema localization round trips nested stage payload."""
        import llm_schema_localization

        canonical = {
            "episode_outlines": [
                {
                    "episode_num": 1,
                    "main_conflict": "主角被逼当众表态",
                    "boundary_check": {
                        "risk_level": "high",
                        "protagonist_action": "举起合同反问",
                        "why_allowed": "属于自保",
                        "mitigation": "保留证据",
                    },
                    "scene_plan": [
                        {
                            "scene_no": 1,
                            "location": "会议室",
                            "time": "日",
                            "space": "内",
                            "scene_purpose": "flashback",
                        }
                    ],
                }
            ]
        }

        localized = llm_schema_localization.localize_prompt_value("episode_outlines", canonical["episode_outlines"])
        restored, report = llm_schema_localization.canonicalize_stage_output(
            "07_episode_planning",
            {"分集大纲": localized},
        )

        self.assertIn("分集大纲", llm_schema_localization.FIELD_LABELS.values())
        self.assertEqual(localized[0]["集号"], 1)
        self.assertEqual(localized[0]["边界检查"]["风险级别"], "高")
        self.assertEqual(localized[0]["分场计划"][0]["场次目的"], "闪回")
        self.assertEqual(restored["episode_outlines"], canonical["episode_outlines"])
        self.assertEqual(report["status"], "PASS")

    def test_llm_schema_localization_preserves_dynamic_object_keys(self):
        """Verify llm schema localization preserves dynamic object keys."""
        import llm_schema_localization

        value = {
            "global_outline": {
                "opening": "开局建立冲突",
                "climax": "高潮完成反击",
                "ending": "结局回收伏笔",
                "escalation_path": "冲突逐级升高",
            },
            "character_known": {
                "主角": {"证据状态": "已存档"},
                "陈寻": {"下一步": "去法务部"},
            },
            "phase_breakdown": {
                "开局篇": {"episode_range": "1-10", "dramatic_goal": "完成首战破局"},
            },
            "prop_positions": {"主角": "作为道具名时不得改键"},
            "running_character_state": {
                "主角": "作为人物名时不得改键",
                "protagonist": "主角总体转为主动",
                "key_relation": "关键关系出现松动",
                "antagonists": "反派开始付出代价",
            },
            "state_update": {
                "主角": "作为动态人物键不得改写",
                "audience_known_after_episode": ["主角已保全证据"],
                "character_known_after_episode": {"主角": ["对手已经知情"]},
                "next_episode_bridge": "下集进入法务部",
            },
        }

        localized = llm_schema_localization.localize_prompt_value("compact_continuity_context", value)
        restored, _ = llm_schema_localization.canonicalize_stage_output("08_script_body_generation", localized)

        self.assertIn("开局", localized["全季大纲"])
        self.assertIn("高潮", localized["全季大纲"])
        self.assertIn("主角", localized["角色已知信息"])
        self.assertIn("开局篇", localized["阶段拆解"])
        self.assertIn("主角", localized["道具位置"])
        self.assertIn("主角", localized["运行中人物状态"])
        self.assertIn("主角总体状态", localized["运行中人物状态"])
        self.assertIn("关键关系总体状态", localized["运行中人物状态"])
        self.assertIn("反派总体状态", localized["运行中人物状态"])
        self.assertIn("主角", localized["状态更新"])
        self.assertIn("本集后观众已知信息", localized["状态更新"])
        self.assertIn("本集后角色已知信息", localized["状态更新"])
        self.assertIn("下一集桥接", localized["状态更新"])
        self.assertEqual(restored, value)

    def test_llm_schema_localization_canonicalizes_episode_delta_v2_state_update(self):
        """Verify llm schema localization canonicalizes episode delta v2 state update."""
        import llm_schema_localization

        localized = {
            "契约版本": "08_episode_delta_v2",
            "最终剧本正文": "第一集",
            "状态更新": {
                "观众事实变更": [
                    {
                        "事实ID": "F1",
                        "变更操作": "新增",
                        "说明": "观众知道手机被拿走",
                        "正文证据": "手机在爷爷手中",
                    }
                ],
                "角色认知变更": [
                    {
                        "变更角色姓名": "方华",
                        "事实ID": "F1",
                        "变更操作": "新增",
                        "说明": "方华知道爷爷拿走手机",
                        "正文证据": "方华看见爷爷拿手机",
                    }
                ],
                "作者私有事实变更": [],
                "下一集桥接": "方华去取回手机",
            },
            "连续性更新": {
                "已完成节拍ID": ["E1-B1"],
                "伏笔变更": [],
                "未解决线索变更": [],
                "关键道具状态变更": [],
                "末场事实": {
                    "地点": "方家客厅",
                    "末场在场人物姓名": ["方华", "爷爷"],
                    "末场可见结果": "爷爷把手机放进口袋",
                },
                "分场边界检查": {
                    "场次数": 1,
                    "同场景拆分次数": 0,
                    "允许同场景拆分": [],
                    "合并说明": "无硬拆场",
                },
                "叙事手法实际使用": {
                    "OS次数": 0,
                    "闪回次数": 0,
                    "VO次数": 0,
                    "已使用替代策略": "用当下动作说明",
                },
            },
        }

        restored, report = llm_schema_localization.canonicalize_stage_output(
            "08_script_body_generation",
            localized,
        )

        self.assertEqual(restored["state_update"]["audience_fact_changes"][0]["fact_id"], "F1")
        self.assertEqual(restored["state_update"]["character_knowledge_changes"][0]["character_name"], "方华")
        self.assertEqual(restored["state_update"]["next_episode_bridge"], "方华去取回手机")
        self.assertEqual(report["unknown_key_paths"], [])
        self.assertEqual(report["status"], "PASS")

    def test_llm_schema_localization_accepts_english_and_rejects_conflicting_aliases(self):
        """Verify llm schema localization accepts english and rejects conflicting aliases."""
        import llm_schema_localization

        restored, report = llm_schema_localization.canonicalize_stage_output(
            "01_novel_summary",
            {"novel_summary": "摘要", "核心钩子": "钩子"},
        )

        self.assertEqual(restored, {"novel_summary": "摘要", "core_hook": "钩子"})
        self.assertEqual(report["status"], "WARN")
        self.assertIn("01_novel_summary.novel_summary", report["english_fallback_paths"])

        with self.assertRaisesRegex(ValueError, r"01_novel_summary\.novel_summary conflicting bilingual keys"):
            llm_schema_localization.canonicalize_stage_output(
                "01_novel_summary",
                {"novel_summary": "英文键值", "原著摘要": "中文键值"},
            )

    def test_llm_schema_localization_normalizes_operation_synonyms(self):
        """Verify llm schema localization normalizes operation synonyms."""
        restored, report = llm_schema_localization.canonicalize_stage_output(
            "08_script_body_generation",
            {
                "连续性更新": {
                    "未解决线索变更": [
                        {"线索ID": "THREAD_1", "变更操作": "关闭", "说明": "线索已完成"},
                        {"线索ID": "THREAD_2", "变更操作": "建立", "说明": "新线索"},
                    ],
                    "关键道具状态变更": [
                        {
                            "道具ID": "PROP_1",
                            "变更操作": "退役",
                            "当前持有人": "无",
                            "位置": "下水道",
                            "状态": "已销毁",
                            "正文证据": "空瓶留在水槽边",
                        }
                    ],
                }
            },
        )

        operations = [
            item["operation"]
            for item in restored["continuity_update"]["open_thread_changes"]
        ]
        self.assertEqual(operations, ["resolve", "add"])
        self.assertEqual(
            restored["continuity_update"]["prop_state_changes"][0]["operation"],
            "retire",
        )
        self.assertEqual(report["status"], "PASS")

    def test_08_normalizer_preserves_terminal_operation_semantics(self):
        """Verify 08 normalizer preserves terminal operation semantics."""
        normalized = pipeline_runner.normalize_stage_output(
            "08_script_body_generation",
            {
                "final_script": "第1集",
                "state_update": {},
                "continuity_update": {
                    "open_thread_changes": [
                        {
                            "thread_id": "THREAD_1",
                            "operation": "update",
                            "detail": "该线索已关闭",
                        }
                    ],
                    "prop_state_changes": [
                        {
                            "prop_id": "PROP_JAR",
                            "operation": "update",
                            "holder": "无",
                            "location": "垃圾桶",
                            "status": "已丢弃",
                        },
                        {
                            "prop_id": "PROP_DIARY",
                            "operation": "无变化",
                            "holder": "方华",
                            "location": "抽屉",
                            "status": "未变化",
                        },
                    ],
                },
            },
        )

        continuity = normalized["continuity_update"]
        self.assertEqual(continuity["open_thread_changes"][0]["operation"], "update")
        self.assertEqual(len(continuity["prop_state_changes"]), 2)
        self.assertEqual(continuity["prop_state_changes"][0]["operation"], "update")
        self.assertEqual(continuity["prop_state_changes"][1]["operation"], "无变化")

    def test_llm_schema_localization_preserves_unknowns_and_folds_equal_aliases(self):
        """Verify llm schema localization preserves unknowns and folds equal aliases."""
        import llm_schema_localization

        restored, report = llm_schema_localization.canonicalize_stage_output(
            "04a_flashback_screening",
            {
                "source_type": "短篇小说",
                "来源类型": "短篇小说",
                "自定义补充": {"等级": "S", "是否启用": True, "备注": None},
            },
        )

        self.assertEqual(restored["source_type"], "短篇小说")
        self.assertEqual(restored["自定义补充"], {"grade": "S", "是否启用": True, "备注": None})
        self.assertEqual(report["status"], "WARN")
        self.assertIn("04a_flashback_screening.source_type", report["duplicate_equal_paths"])
        self.assertIn("04a_flashback_screening.自定义补充", report["unknown_key_paths"])
        self.assertIn("04a_flashback_screening.自定义补充.是否启用", report["unknown_key_paths"])

    def test_contract_projection_removes_unknown_fixed_fields_and_keeps_delta_items(self):
        """Verify contract projection removes unknown fixed fields and keeps delta items."""
        import stage_contracts

        data = {
            "schema_version": "08_episode_delta_v2",
            "final_script": "第一集",
            "state_update": {
                "audience_fact_changes": [{"fact_id": "F1", "operation": "add", "detail": "已存证", "evidence": "屏幕"}],
                "character_knowledge_changes": [
                        {
                            "character_name": "方华",
                            "fact_id": "F1",
                            "operation": "add",
                            "detail": "已存证",
                            "evidence": "屏幕",
                        },
                    ],
                "private_fact_changes": [],
                "next_episode_bridge": "爷爷赶到学校",
                "临时状态": "不应进入clean",
            },
            "continuity_update": {
                "completed_beat_ids": ["E1-B1"],
                "foreshadowing_changes": [],
                "open_thread_changes": [],
                "prop_state_changes": [],
                "last_scene_state": {"location": "学校", "present_character_names": ["方华"], "visible_result": "已存证"},
                "scene_boundary_check": {
                    "scene_count": 1,
                    "same_setting_split_count": 0,
                    "allowed_same_setting_splits": [],
                    "merge_note": "无硬拆场",
                    "临时说明": "不应进入clean",
                },
                "narration_device_usage": {
                    "os_count": 0,
                    "flashback_count": 0,
                    "vo_count": 0,
                    "replacement_strategy_used": "当下动作",
                },
            },
            "模型自由总结": {"价值": "不应进入clean"},
        }

        projected, unmapped = stage_contracts.project_contract_data("08_script_body_generation", data)

        self.assertNotIn("模型自由总结", projected)
        self.assertNotIn("临时说明", projected["continuity_update"]["scene_boundary_check"])
        self.assertNotIn("临时状态", projected["state_update"])
        self.assertEqual(projected["state_update"]["character_knowledge_changes"][0]["character_name"], "方华")
        self.assertEqual(
            [item["path"] for item in unmapped],
            [
                "08_script_body_generation.continuity_update.scene_boundary_check.临时说明",
                "08_script_body_generation.state_update.临时状态",
                "08_script_body_generation.模型自由总结",
            ],
        )

    def test_adaptation_market_tag_priority_has_closed_bilingual_item_contract(self):
        """Verify adaptation market tag priority has closed bilingual item contract."""
        localized = {
            "改编方向": "强化主角主动反击",
            "目标基调": "现实压迫",
            "改编原则": [],
            "必须保留要素": [],
            "可扩展内容": [],
            "长篇扩写策略": "分篇章升级",
            "市场标签优先级": [
                {
                    "标签": "高考逆袭",
                    "剧情动作": "用成绩对比完成反击",
                    "自由备注": "不得进入 clean",
                }
            ],
            "原创边界": {"原著保留比例": "60%", "原创扩写比例": "40%", "风险说明": "不改核心梗"},
            "原著保留契约": {"必须保留内容": [], "必须保留事实ID": [], "可扩展内容": [], "单集检查方式": "逐集核对"},
            "主角行动边界": {"允许范围": [], "主角允许主动策略": [], "风险示例": [], "风险应对": "保留证据"},
            "事件释放原则": [],
            "尾声预算": {"最大集数": 2, "允许功能": []},
            "保留规则": [],
            "禁止改动": [],
        }

        canonical, localization_report = llm_schema_localization.canonicalize_stage_output(
            "04_adaptation_direction",
            localized,
        )
        projected, unmapped = stage_contracts.project_contract_data(
            "04_adaptation_direction",
            canonical,
        )
        contract_report = stage_contracts.validate("04_adaptation_direction", projected)

        self.assertEqual(
            projected["market_tag_priority"],
            [{"tag": "高考逆袭", "dramatic_action": "用成绩对比完成反击"}],
        )
        self.assertIn(
            "04_adaptation_direction.market_tag_priority[0].自由备注",
            localization_report["unknown_key_paths"],
        )
        self.assertEqual(
            [item["path"] for item in unmapped],
            ["04_adaptation_direction.market_tag_priority[0].自由备注"],
        )
        self.assertEqual(contract_report["status"], "PASS")

    def test_adaptation_market_tag_priority_requires_dramatic_action(self):
        """Verify adaptation market tag priority requires dramatic action."""
        data = {
            "adaptation_direction": "强化主角反击",
            "target_tone": "强冲突",
            "change_principles": [{"principle": "保留核心梗", "why": "情绪债强", "impact_on_story": "支撑长线"}],
            "must_keep": ["源故事核心伤害"],
            "can_expand": ["外部见证者"],
            "longform_strategy": "分篇章递进",
            "market_tag_priority": [{"tag": "高考逆袭"}],
            "originality_boundary": {
                    "source_retention_ratio": "60%",
                    "original_expansion_ratio": "40%",
                    "risk_note": "不改核心梗",
                },
            "source_preservation_contract": {
                    "must_preserve": ["核心伤害"],
                    "can_expand": ["证据线"],
                    "per_episode_check": "每集核对",
                },
            "protagonist_action_boundary": {"allowed": ["留证"], "risk_examples": ["公开反击"], "risk_response": "记录风险"},
            "event_release_principles": ["终局事件后置"],
            "epilogue_budget": {"max_episodes": 1, "allowed_functions": ["收束"]},
            "retention_rules": ["每篇保留情绪债"],
            "forbidden_changes": ["不得改名"],
        }
        report = stage_contracts.validate(
            "04_adaptation_direction",
            data,
        )

        self.assertEqual(report["status"], "FAIL")
        self.assertIn(
            "04_adaptation_direction.market_tag_priority[0].dramatic_action missing",
            report["errors"],
        )

    def test_stage05_conflict_templates_have_closed_bilingual_item_contract(self):
        """Verify stage05 conflict templates have closed bilingual item contract."""
        localized = {
            "宏观弧线": [],
            "冲突引擎": {
                "施压模板": [
                    {
                        "模板ID": "P1",
                        "模板名称": "亲情控制",
                        "模式": "以关心为名施压",
                        "适用弧线ID": [1],
                        "变体示例": ["收走手机"],
                        "自由备注": "不得进入 clean",
                    }
                ],
                "反击模板": [],
                "反转模板": [],
                "反单调规则": [],
            },
            "扩展人物网络": [],
            "伏笔池": [],
            "关键道具实体表": [],
        }

        canonical, localization_report = llm_schema_localization.canonicalize_stage_output(
            "05_plot_character_adaptation",
            localized,
        )
        projected, unmapped = stage_contracts.project_contract_data(
            "05_plot_character_adaptation",
            canonical,
            profile="05_foundation",
        )
        contract_report = stage_contracts.validate(
            "05_plot_character_adaptation",
            projected,
            profile="05_foundation",
        )

        self.assertEqual(
            projected["conflict_engine"]["pressure_templates"],
            [{
                "template_id": "P1",
                "template_name": "亲情控制",
                "mode": "以关心为名施压",
                "applicable_arc_ids": [1],
                "variant_examples": ["收走手机"],
            }],
        )
        self.assertIn(
            "05_plot_character_adaptation.conflict_engine.pressure_templates[0].自由备注",
            localization_report["unknown_key_paths"],
        )
        self.assertEqual(
            [item["path"] for item in unmapped],
            ["05_plot_character_adaptation.conflict_engine.pressure_templates[0].自由备注"],
        )
        self.assertEqual(contract_report["status"], "PASS")

    def test_stage05_conflict_template_missing_nested_field_fails_contract(self):
        """Verify stage05 conflict template missing nested field fails contract."""
        data = {
            "macro_arcs": [],
            "conflict_engine": {
                "pressure_templates": [{
                    "template_id": "P1",
                    "template_name": "亲情控制",
                    "mode": "以关心为名施压",
                    "applicable_arc_ids": [1],
                }],
                "counterattack_templates": [],
                "reversal_templates": [],
                "anti_monotony_rules": [],
            },
            "expanded_character_network": [],
            "foreshadowing_pool": [],
            "prop_registry": [],
        }

        report = stage_contracts.validate(
            "05_plot_character_adaptation",
            data,
            profile="05_foundation",
        )

        self.assertEqual(report["status"], "FAIL")
        self.assertIn(
            "05_plot_character_adaptation.conflict_engine.pressure_templates[0].variant_examples missing",
            report["errors"],
        )

    def test_call_stage_writes_unmapped_sidecar_and_keeps_clean_canonical(self):
        """Verify call stage writes unmapped sidecar and keeps clean canonical."""
        raw_response = json.dumps(
            {
                "原著摘要": "主角被逼放弃高考。",
                "核心钩子": "重生后当场逃离。",
                "情绪债": ["亲情控制"],
                "扩写资产": ["校园阻断"],
                "不可改元素": ["主角重生"],
                "潜在支线": [],
                "未展开人物": [],
                "开放伏笔": [],
                "章节梗概": [],
                "关键事件": [],
                "模型自由总结": {"价值": "仅保留在审计中"},
            },
            ensure_ascii=False,
        )
        result = llm_client.LLMResult(
            raw=raw_response,
            clean=raw_response,
            returncode=0,
            elapsed_seconds=0.1,
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "unmapped_runner_test")
            stage = pipeline_runner.stage_map()["01_novel_summary"]
            with mock.patch.object(llm_client, "call_llm", return_value=result):
                data = pipeline_runner.call_stage(
                    paths,
                    stage,
                    {
                        "run_config": {"target_episodes": 40},
                        "derived_config": {"block_count": 4},
                        "source_text": "测试小说全文",
                        "chapter_chunks": [],
                    },
                    dry_run=False,
                    llm_script_path=Path("/tmp/fake-llm.sh"),
                    timeout=30,
                )

            sidecar = json.loads(
                (paths.parsed / "unmapped_fields" / "01_novel_summary.json").read_text(encoding="utf-8")
            )
            saved_clean = json.loads(
                (paths.outputs / "01_novel_summary.clean.json").read_text(encoding="utf-8")
            )

        self.assertNotIn("模型自由总结", data)
        self.assertEqual(data, saved_clean)
        self.assertEqual(sidecar["status"], "WARN")
        self.assertEqual(sidecar["field_count"], 1)
        self.assertEqual(sidecar["fields"][0]["path"], "01_novel_summary.模型自由总结")
        self.assertEqual(sidecar["fields"][0]["value"], {"价值": "仅保留在审计中"})

    def test_call_stage_preserves_script_quality_issues_for_validation(self):
        """Verify call stage preserves script quality issues for validation."""
        raw_response = json.dumps(
            {
                "最终剧本正文": (
                    "第一集\n"
                    "1-1    方家卧室    日    内\n"
                    "出场人物：方华\n"
                    "△方华（收起录取短信）：我现在就走。"
                ),
                "状态更新": {},
                "连续性更新": {
                    "观众已知信息": [],
                    "角色已知信息": {},
                    "作者私有信息": [],
                    "伏笔状态": [],
                    "下一集桥接": "方华出门",
                    "已使用冲突模式": "当场脱身",
                    "已执行原著锚点": "收下录取结果",
                    "边界风险": "低",
                    "内容敏感风险": "低",
                    "开场连续性检查": "首集开场",
                    "已完成情节": ["收到录取短信"],
                    "分场边界检查": {
                        "场次数": 1,
                        "同场景拆分次数": 0,
                        "允许同场景拆分": [],
                        "合并说明": "无硬拆场",
                    },
                    "叙事手法实际使用": {
                        "OS次数": 0,
                        "闪回次数": 0,
                        "VO次数": 0,
                        "已使用替代策略": "当下动作",
                    },
                },
            },
            ensure_ascii=False,
        )
        result = llm_client.LLMResult(
            raw=raw_response,
            clean=raw_response,
            returncode=0,
            elapsed_seconds=0.1,
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "normalization_report_test")
            stage = pipeline_runner.stage_map()["08_script_body_generation"]
            with mock.patch.object(llm_client, "call_llm", return_value=result):
                data = pipeline_runner.call_stage(
                    paths,
                    stage,
                    {
                        "run_config": {"target_episodes": 40},
                        "derived_config": {},
                        "canonical_story_lock": {},
                        "compact_continuity_context": {},
                        "foreshadowing_pool": [],
                        "flashback_screening": {},
                        "episode_outline": {},
                        "block_state_plan": [],
                        "remaining_episode_plan": [],
                        "recent_conflict_modes": [],
                        "protagonist_action_boundary": {},
                        "previous_context": {},
                        "character_state": {},
                    },
                    dry_run=False,
                    llm_script_path=Path("/tmp/fake-llm.sh"),
                    timeout=30,
                )
            report = json.loads(
                (paths.parsed / "normalization_reports" / "08_script_body_generation.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertIn("\n△方华（收起录取短信）：", data["final_script"])
        self.assertNotIn(
            "normalize_script_dialogue_triangle_prefix",
            [item["operation"] for item in report["operations"]],
        )

    def test_call_stage_writes_parser_repair_report(self):
        """Verify call stage writes parser repair report."""
        raw_response = '{"原著摘要": "方华说"走"", "核心钩子": "当场反击"}'
        result = llm_client.LLMResult(
            raw=raw_response,
            clean=raw_response,
            returncode=0,
            elapsed_seconds=0.1,
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "parser_report_test")
            stage = pipeline_runner.stage_map()["01_novel_summary"]
            with mock.patch.object(llm_client, "call_llm", return_value=result):
                pipeline_runner.call_stage(
                    paths,
                    stage,
                    {
                        "run_config": {"target_episodes": 40},
                        "derived_config": {"block_count": 4},
                        "source_text": "测试小说全文",
                        "chapter_chunks": [],
                    },
                    dry_run=False,
                    llm_script_path=Path("/tmp/fake-llm.sh"),
                    timeout=30,
                )

            report = json.loads(
                (paths.parsed / "parser_reports" / "01_novel_summary.json").read_text(encoding="utf-8")
            )
            summary = json.loads((paths.parsed / "parser_summary.json").read_text(encoding="utf-8"))

        self.assertEqual(report["status"], "WARN")
        self.assertIn(
            "escape_unescaped_string_quotes",
            [item["operation"] for item in report["operations"]],
        )
        self.assertEqual(summary["artifacts_repaired"], 1)
        self.assertEqual(summary["artifacts_with_discarded_content"], 0)

    def test_call_stage_does_not_invent_missing_07_contract_fields(self):
        """Verify call stage does not invent missing 07 contract fields."""
        raw_response = json.dumps(
            {
                "episode_allocation": [],
                "block_plans": [],
                "episode_outlines": [
                    {
                        "episode_num": 1,
                        "scene_plan": [
                            {
                                "scene_no": 1,
                                "location": "学校",
                                "time": "日",
                                "space": "内",
                                "appearing_character_names": ["方华"],
                                "scene_purpose": "pressure",
                                "must_include_beats": ["方华进入教室"],
                                "scene_boundary_reason": "地点变化",
                                "visible_space_tokens": ["教室"],
                            }
                        ],
                        "narration_device_plan": pipeline_runner.build_default_narration_device_plan(),
                    }
                ],
            },
            ensure_ascii=False,
        )
        result = llm_client.LLMResult(
            raw=raw_response,
            clean=raw_response,
            returncode=0,
            elapsed_seconds=0.1,
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "normalizer_projection_test")
            stage = pipeline_runner.stage_map()["07_episode_planning"]
            with mock.patch.object(llm_client, "call_llm", return_value=result):
                data = pipeline_runner.call_stage(
                    paths,
                    stage,
                    {"run_config": {}, "derived_config": {}},
                    dry_run=False,
                    llm_script_path=Path("/tmp/fake-llm.sh"),
                    timeout=30,
                    prompt_override="请输出分集规划 JSON",
                )
            report = json.loads(
                (paths.parsed / "normalization_reports" / "07_episode_planning.json").read_text(
                    encoding="utf-8"
                )
            )

        episode = data["episode_outlines"][0]
        self.assertNotIn("target_script_density", episode)
        self.assertNotIn("target_script_density_repair_trace", episode)
        self.assertNotIn(
            "episode_outlines[0].target_script_density_repair_trace",
            report["discarded_trace_paths"],
        )

    def test_stage_contract_requires_structured_foreshadowing_status_items(self):
        """Verify stage contract requires structured foreshadowing status items."""
        import stage_contracts

        data = {
            "schema_version": "08_episode_delta_v2",
            "final_script": "第一集",
            "state_update": {
                    "audience_fact_changes": [],
                    "character_knowledge_changes": [],
                    "private_fact_changes": [],
                    "next_episode_bridge": "下一拍",
                },
            "continuity_update": {
                "completed_beat_ids": [],
                "foreshadowing_changes": [{"id": "F01", "operation": "add"}],
                "open_thread_changes": [],
                "prop_state_changes": [],
                "last_scene_state": {"location": "家中", "present_character_names": [], "visible_result": "关门"},
                "scene_boundary_check": {
                    "scene_count": 1,
                    "same_setting_split_count": 0,
                    "allowed_same_setting_splits": [],
                    "merge_note": "无",
                },
                "narration_device_usage": {
                    "os_count": 0,
                    "flashback_count": 0,
                    "vo_count": 0,
                    "replacement_strategy_used": "当下动作",
                },
            },
        }

        report = stage_contracts.validate("08_script_body_generation", data)

        self.assertIn(
            "08_script_body_generation.continuity_update.foreshadowing_changes[0].detail missing",
            report["errors"],
        )

    def test_stage05_event_targets_distribute_low_bound_across_arcs(self):
        """Verify stage05 event targets distribute low bound across arcs."""
        arcs = [
            {"arc_id": 1, "episode_range": "1-5"},
            {"arc_id": 2, "episode_range": "6-10"},
            {"arc_id": 3, "episode_range": "11-15"},
        ]

        specs = pipeline_runner.build_stage05_event_specs(arcs, event_pool_size="8-12")

        self.assertEqual([item["event_count"] for item in specs], [3, 3, 2])
        self.assertEqual([item["start_event_id"] for item in specs], [1, 4, 7])

    def test_stage05_event_specs_raise_count_to_keep_each_event_within_three_episodes(self):
        """Verify stage05 event specs raise count to keep each event within three episodes."""
        arcs = [
            {"arc_id": 1, "episode_range": "1-10"},
            {"arc_id": 2, "episode_range": "11-20"},
            {"arc_id": 3, "episode_range": "21-30"},
            {"arc_id": 4, "episode_range": "31-40"},
        ]

        specs = pipeline_runner.build_stage05_event_specs(
            arcs,
            event_pool_size="12-16",
            max_event_span=3,
        )

        self.assertEqual([item["event_count"] for item in specs], [4, 4, 4, 4])
        self.assertEqual(specs[-1]["end_event_id"], 16)

    def test_projection_profile_contract_checks_only_chunk_fields_and_nested_items(self):
        """Verify projection profile contract checks only chunk fields and nested items."""
        valid_foundation = {
            "macro_arcs": [],
            "conflict_engine": {
                "pressure_templates": [],
                "counterattack_templates": [],
                "reversal_templates": [],
                "anti_monotony_rules": [],
            },
            "expanded_character_network": [],
            "foreshadowing_pool": [],
            "prop_registry": [],
        }
        foundation_report = stage_contracts.validate(
            "05_plot_character_adaptation",
            valid_foundation,
            profile="05_foundation",
        )
        invalid_event_chunk = {
            "event_pool": [
                {
                    "id": 1,
                    "title": "离家",
                    "function": "起势",
                    "source_plot_point_ids": [1],
                    "expansion_type": "new_expansion",
                    "target_block": 1,
                    "episode_window": "1-3",
                    "not_before_episode": 1,
                    "not_after_episode": 3,
                    "expected_episode_span": 3,
                    "importance_level": "A",
                    "conflict_mode": "家庭阻挠",
                    "pattern_family": "当场反击",
                    "source_anchor": "录取通知",
                    "delta_from_source": "扩写离家阻力",
                    "legal_moral_risk": "low",
                    "content_sensitivity_risk": "low",
                }
            ]
        }
        event_report = stage_contracts.validate(
            "05_plot_character_adaptation",
            invalid_event_chunk,
            profile="05_event_chunk",
        )

        self.assertEqual(foundation_report["errors"], [])
        self.assertIn(
            "05_plot_character_adaptation.event_pool[0].child_beats missing",
            event_report["errors"],
        )
        self.assertFalse(any("macro_arcs missing" in item for item in event_report["errors"]))

    def test_call_stage_writes_chunk_contract_report_before_failing(self):
        """Verify call stage writes chunk contract report before failing."""
        raw_response = json.dumps({"事件池": [{"ID": 1}]}, ensure_ascii=False)
        result = llm_client.LLMResult(
            raw=raw_response,
            clean=raw_response,
            returncode=0,
            elapsed_seconds=0.1,
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "chunk_contract_test")
            stage = pipeline_runner.stage_map()["05_plot_character_adaptation"]
            with mock.patch.object(llm_client, "call_llm", return_value=result):
                with self.assertRaisesRegex(ValueError, r"event_pool\[0\].title missing"):
                    pipeline_runner.call_stage(
                        paths,
                        stage,
                        {"run_config": {}, "derived_config": {}},
                        dry_run=False,
                        llm_script_path=Path("/tmp/fake-llm.sh"),
                        timeout=30,
                        artifact_id="05_plot_character_adaptation.arc_01.events",
                        prompt_override="生成事件池",
                        contract_projection_profile="05_event_chunk",
                    )

            report = json.loads(
                (
                    paths.parsed
                    / "contract_reports"
                    / "05_plot_character_adaptation.arc_01.events.contract_report.json"
                ).read_text(encoding="utf-8")
            )

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["contract_profile"], "05_event_chunk")

    def test_stage05_fanout_uses_projection_profiles_and_stage_timeout(self):
        """Verify stage05 fanout uses projection profiles and stage timeout."""
        foundation = {
            "macro_arcs": [
                {
                    "arc_id": 1,
                    "title": "起势",
                    "episode_range": "1-5",
                    "dramatic_goal": "脱身",
                    "pressure_source": "家庭",
                    "payoff": "离开",
                    "source_plot_point_ids": [1],
                },
                {
                    "arc_id": 2,
                    "title": "反制",
                    "episode_range": "6-10",
                    "dramatic_goal": "自立",
                    "pressure_source": "造谣",
                    "payoff": "澄清",
                    "source_plot_point_ids": [2],
                },
            ],
            "conflict_engine": {
                "pressure_templates": [],
                "counterattack_templates": [],
                "reversal_templates": [],
                "anti_monotony_rules": [],
            },
            "expanded_character_network": [],
            "foreshadowing_pool": [],
        }
        event_chunks = [
            {"event_pool": [{"id": 1, "source_plot_point_ids": [1]}]},
            {"event_pool": [{"id": 2, "source_plot_point_ids": [2]}]},
        ]
        calls: list[dict[str, Any]] = []

        def fake_call_stage(*args, **kwargs):
            """Handle fake call stage."""
            calls.append(kwargs)
            if kwargs["contract_projection_profile"] == "05_foundation":
                return foundation
            return event_chunks.pop(0)

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "stage05_fanout_test")
            stage = pipeline_runner.stage_map()["05_plot_character_adaptation"]
            with mock.patch.object(pipeline_runner, "call_stage", side_effect=fake_call_stage):
                merged = pipeline_runner.run_plot_character_adaptation_stage(
                    paths,
                    stage,
                    {
                        "target_episodes": 10,
                        "derived_config": {"event_pool_size": "2-4"},
                        "source_plot_points": [{"id": 1}, {"id": 2}],
                    },
                    dry_run=False,
                    llm_script_path=Path("/tmp/fake-llm.sh"),
                    timeout=900,
                )
            trace = json.loads(
                (paths.parsed / "05_plot_character_adaptation_fanout_trace.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(
            [call["contract_projection_profile"] for call in calls],
            ["05_foundation", "05_event_chunk", "05_event_chunk"],
        )
        self.assertTrue(all(call["timeout"] == 900 for call in calls))
        self.assertEqual([item["id"] for item in merged["event_pool"]], [1, 2])
        self.assertEqual(
            set(merged),
            {
                "macro_arcs",
                "event_pool",
                "conflict_engine",
                "expanded_character_network",
                "foreshadowing_pool",
                "mapping_trace",
            },
        )
        self.assertEqual(len(merged["mapping_trace"]), 2)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{64}", item["output_sha256"]) for item in trace))

    def test_parser_has_dedicated_stage05_timeout_default(self):
        """Verify parser has dedicated stage05 timeout default."""
        args = pipeline_runner.build_parser().parse_args(["--novel", "novel.txt"])

        self.assertEqual(args.stage_05_timeout, 900)

    def test_prompt_renderer_supports_chinese_placeholder_and_localizes_structured_value(self):
        """Verify prompt renderer supports chinese placeholder and localizes structured value."""
        rendered = prompt_renderer.render_template(
            "## 全局运行配置\n{全局运行配置}",
            {"run_config": {"target_episodes": 40, "rewrite_intensity": "balanced"}},
        )

        self.assertIn('"目标集数": 40', rendered)
        self.assertIn('"改写强度": "平衡"', rendered)
        self.assertNotIn("target_episodes", rendered)

    def test_localization_accepts_current_location_alias_without_losing_conflicts(self):
        """Verify localization accepts current location alias without losing conflicts."""
        canonical, report = llm_schema_localization.canonicalize_stage_output(
            "05_plot_character_adaptation",
            {"初始状态": {"当前持有人": "方华", "当前地点": "书包", "状态": "完好"}},
        )

        self.assertEqual(canonical["initial_state"]["location"], "书包")
        self.assertIn(
            "05_plot_character_adaptation.initial_state.location",
            report["translated_key_paths"],
        )
        with self.assertRaises(llm_schema_localization.LocalizationConflictError):
            llm_schema_localization.canonicalize_stage_output(
                "05_plot_character_adaptation",
                {
                    "初始状态": {
                        "地点": "桌上",
                        "当前地点": "书包",
                    }
                },
            )

    def test_stage05_foundation_prompt_uses_exact_prop_initial_state_labels(self):
        """Verify stage05 foundation prompt uses exact prop initial state labels."""
        prompt = pipeline_runner.render_stage05_foundation_prompt({})

        self.assertIn('"地点": ""', prompt)
        self.assertNotIn('"当前地点": ""', prompt)
        self.assertIn("地点键必须写 `地点`", prompt)

    def test_llm_field_labels_are_unique_cover_contracts_and_power_readable_renderer(self):
        """Verify llm field labels are unique cover contracts and power readable renderer."""
        import llm_schema_localization
        import stage_contracts

        labels = llm_schema_localization.FIELD_LABELS
        contextual_labels = [
            label
            for value_map in llm_schema_localization.CONTEXTUAL_FIELD_LABELS_BY_PARENT.values()
            for label in value_map.values()
        ]
        contract_keys = {
            key
            for rules in stage_contracts.STAGE_CONTRACTS.values()
            for rule in rules
            for key in rule.keys
        }
        model_input_keys = {
            key
            for stage in pipeline_runner.load_stages()
            if stage.get("model")
            for key in stage.get("inputs", [])
        }

        self.assertEqual(len(labels), len(set(labels.values())))
        self.assertEqual(len(contextual_labels), len(set(contextual_labels)))
        for value_map in llm_schema_localization.CONTEXTUAL_FIELD_LABELS_BY_PARENT.values():
            for canonical, localized in value_map.items():
                if localized in llm_schema_localization.CHINESE_TO_FIELD:
                    self.assertEqual(llm_schema_localization.CHINESE_TO_FIELD[localized], canonical)
        self.assertEqual(sorted(contract_keys - labels.keys()), [])
        self.assertEqual(sorted(model_input_keys - labels.keys()), [])
        self.assertIs(clean_json_to_md.FIELD_LABELS, labels)

    def test_call_stage_canonicalizes_chinese_response_and_writes_localization_report(self):
        """Verify call stage canonicalizes chinese response and writes localization report."""
        raw_response = json.dumps(
            {
                "原著摘要": "主角被公司开除后反击。",
                "核心钩子": "全公司离不开被开除的人。",
            },
            ensure_ascii=False,
        )
        result = llm_client.LLMResult(
            raw=raw_response,
            clean=raw_response,
            returncode=0,
            elapsed_seconds=0.1,
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = pipeline_runner.create_run_paths(Path(tmpdir), "localization_runner_test")
            stage = pipeline_runner.stage_map()["01_novel_summary"]
            with mock.patch.object(llm_client, "call_llm", return_value=result):
                data = pipeline_runner.call_stage(
                    paths,
                    stage,
                    {
                        "run_config": {"target_episodes": 40, "rewrite_intensity": "balanced"},
                        "derived_config": {"block_count": 4},
                        "source_text": "测试小说全文",
                        "chapter_chunks": [],
                    },
                    dry_run=False,
                    llm_script_path=Path("/tmp/fake-llm.sh"),
                    timeout=30,
                )

            clean = json.loads((paths.outputs / "01_novel_summary.clean.json").read_text(encoding="utf-8"))
            report = json.loads(
                (paths.parsed / "localization_reports" / "01_novel_summary.json").read_text(encoding="utf-8")
            )
            summary = json.loads((paths.parsed / "localization_summary.json").read_text(encoding="utf-8"))
            manifest = json.loads((paths.manifests / "01_novel_summary.manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(data, clean)
        self.assertEqual(clean["novel_summary"], "主角被公司开除后反击。")
        self.assertEqual(
            (paths.outputs / "01_novel_summary.raw.md").name,
            "01_novel_summary.raw.md",
        )
        self.assertEqual(report["status"], "PASS")
        self.assertIn("01_novel_summary.novel_summary", report["translated_key_paths"])
        self.assertEqual(summary["status_counts"]["PASS"], 1)
        self.assertEqual(manifest["prompt_schema_locale"], "zh-CN")
        self.assertEqual(manifest["localization_status"], "PASS")

    def test_call_stage_writes_localization_report_on_alias_conflict_or_json_failure(self):
        """Verify call stage writes localization report on alias conflict or json failure."""
        import llm_schema_localization

        cases = (
            (
                "alias_conflict",
                json.dumps(
                    {"novel_summary": "英文键值", "原著摘要": "中文键值"},
                    ensure_ascii=False,
                ),
                llm_schema_localization.LocalizationConflictError,
            ),
            ("json_failure", "这不是JSON", json.JSONDecodeError),
        )
        for case_name, raw_response, expected_error in cases:
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as tmpdir:
                paths = pipeline_runner.create_run_paths(Path(tmpdir), case_name)
                stage = pipeline_runner.stage_map()["01_novel_summary"]
                result = llm_client.LLMResult(
                    raw=raw_response,
                    clean=raw_response,
                    returncode=0,
                    elapsed_seconds=0.1,
                    stderr="",
                )
                with mock.patch.object(llm_client, "call_llm", return_value=result):
                    with self.assertRaises(expected_error):
                        pipeline_runner.call_stage(
                            paths,
                            stage,
                            {
                                "run_config": {"target_episodes": 40},
                                "derived_config": {"block_count": 4},
                                "source_text": "测试小说全文",
                                "chapter_chunks": [],
                            },
                            dry_run=False,
                            llm_script_path=Path("/tmp/fake-llm.sh"),
                            timeout=30,
                        )

                report = json.loads(
                    (paths.parsed / "localization_reports" / "01_novel_summary.json").read_text(
                        encoding="utf-8"
                    )
                )
                summary = json.loads(
                    (paths.parsed / "localization_summary.json").read_text(encoding="utf-8")
                )
                self.assertEqual(report["status"], "FAIL")
                self.assertEqual(summary["status_counts"]["FAIL"], 1)
                if case_name == "alias_conflict":
                    self.assertIn(
                        "01_novel_summary.novel_summary",
                        report["conflicting_alias_paths"],
                    )
                else:
                    self.assertIn("parse_error", report)

    def test_all_model_prompt_templates_use_chinese_contract_and_standard_sections(self):
        """Verify all model prompt templates use chinese contract and standard sections."""
        import llm_schema_localization
        import stage_contracts

        stages = [item for item in pipeline_runner.load_stages() if item.get("model")]
        required_sections = (
            "# 任务目标",
            "## 本环节边界",
            "## 输入材料",
            "## 输出 JSON 示例",
            "## 执行规则",
            "## 输出前自检",
        )
        for stage in stages:
            stage_id = stage["stage_id"]
            prompt = (PROJECT_ROOT / stage["prompt_file"]).read_text(encoding="utf-8")
            with self.subTest(stage_id=stage_id):
                for section in required_sections:
                    self.assertIn(section, prompt)
                placeholders = prompt_renderer.PLACEHOLDER_RE.findall(prompt)
                self.assertTrue(placeholders)
                self.assertTrue(
                    all(name in llm_schema_localization.PROMPT_PLACEHOLDER_ALIASES for name in placeholders),
                )
                contract_keys = {
                    key
                    for rule in stage_contracts.STAGE_CONTRACTS[stage_id]
                    for key in rule.keys
                }
                for key in contract_keys:
                    self.assertIn(llm_schema_localization.FIELD_LABELS[key], prompt)
                    self.assertIsNone(re.search(rf"(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])", prompt))

    def test_normalize_event_child_beats_only_wraps_legacy_strings(self):
        """Verify normalize event child beats only wraps legacy strings."""
        normalized = pipeline_runner.normalize_event_child_beats(
            {
                "event_pool": [
                    {
                        "id": 3,
                        "child_beats": [
                            "爷爷拿走手机",
                            {"child_beat_id": "模型自由ID", "action": "方华发现拒接记录", "completion_evidence": "屏幕出现拒接记录"},
                        ],
                    }
                ]
            }
        )

        beats = normalized["event_pool"][0]["child_beats"]
        self.assertEqual([item["child_beat_id"] for item in beats], ["E3-B1", "模型自由ID"])
        self.assertEqual(beats[0]["action"], "爷爷拿走手机")
        self.assertEqual(beats[0]["completion_evidence"], "")
        self.assertEqual(beats[1]["completion_evidence"], "屏幕出现拒接记录")

    def test_normalize_episode_child_beat_references_derives_legacy_text(self):
        """Verify normalize episode child beat references derives legacy text."""
        event_pool = pipeline_runner.normalize_event_child_beats(
            {"event_pool": [{"id": 2, "child_beats": ["爷爷拿走手机", "手机拒接来电"]}]}
        )["event_pool"]

        normalized = pipeline_runner.normalize_episode_child_beat_references(
            {"episode_outlines": [{"episode_num": 1, "consumed_child_beats": ["手机拒接来电"]}]},
            event_pool=event_pool,
        )

        episode = normalized["episode_outlines"][0]
        self.assertEqual(episode["consumed_child_beat_ids"], ["E2-B2"])
        self.assertEqual(episode["consumed_child_beats"], ["手机拒接来电"])

    def test_event_child_beat_alignment_rejects_cross_event_reference(self):
        """Verify event child beat alignment rejects cross event reference."""
        event_pool = pipeline_runner.normalize_event_child_beats(
            {
                "event_pool": [
                    {"id": 2, "child_beats": ["爷爷拿走手机"]},
                    {"id": 3, "child_beats": ["方华阳台逃生"]},
                ]
            }
        )["event_pool"]
        episodes = [
            {
                "episode_num": 2,
                "event_ids": [2],
                "consumed_child_beat_ids": ["E3-B1"],
                "event_consumption_status": "ongoing",
            }
        ]

        findings = validators.event_child_beat_alignment_findings(episodes, event_pool=event_pool)

        self.assertTrue(any(item["issue"] == "child_beat_belongs_to_undeclared_event" for item in findings))
        with self.assertRaisesRegex(ValueError, "event child beat alignment failed"):
            validators.validate_episode_child_beat_references(episodes, event_pool=event_pool)

    def test_event_child_beat_alignment_reports_declared_event_without_own_beat(self):
        """Verify event child beat alignment reports declared event without own beat."""
        event_pool = pipeline_runner.normalize_event_child_beats(
            {"event_pool": [{"id": 1, "child_beats": ["持续施压"]}, {"id": 2, "child_beats": ["主角逃离"]}]}
        )["event_pool"]
        findings = validators.event_child_beat_alignment_findings(
            [
                {
                    "episode_num": 2,
                    "event_ids": [1, 2],
                    "consumed_child_beat_ids": ["E2-B1"],
                    "event_consumption_status": "ongoing",
                }
            ],
            event_pool=event_pool,
        )

        item = next(value for value in findings if value["issue"] == "declared_event_without_own_child_beat_id")
        self.assertEqual(item["event_id"], "1")

    def test_event_child_beat_alignment_reports_owner_window_violation(self):
        """Verify event child beat alignment reports owner window violation."""
        event_pool = pipeline_runner.normalize_event_child_beats(
            {
                "event_pool": [
                    {
                        "id": 3,
                        "episode_window": {"start": 7, "end": 10},
                        "child_beats": ["收到录取通知", "办理入学"],
                    }
                ]
            }
        )["event_pool"]

        findings = validators.event_child_beat_alignment_findings(
            [
                {
                    "episode_num": 5,
                    "event_ids": [3],
                    "consumed_child_beat_ids": ["E3-B1"],
                    "event_consumption_status": "ongoing",
                }
            ],
            event_pool=event_pool,
        )

        item = next(
            value
            for value in findings
            if value["issue"] == "child_beat_consumed_outside_owner_event_window"
        )
        self.assertEqual(item["owner_event_id"], "3")
        self.assertEqual(item["window"], {"start": 7, "end": 10})

    def test_event_child_beat_alignment_requires_completed_event_coverage(self):
        """Verify event child beat alignment requires completed event coverage."""
        event_pool = pipeline_runner.normalize_event_child_beats(
            {"event_pool": [{"id": 5, "child_beats": ["拿出准考证", "显示十七个未接来电"]}]}
        )["event_pool"]
        findings = validators.event_child_beat_alignment_findings(
            [
                {
                    "episode_num": 5,
                    "event_ids": [5],
                    "consumed_child_beat_ids": ["E5-B1"],
                    "event_consumption_status": "completed",
                }
            ],
            event_pool=event_pool,
        )

        completed = next(item for item in findings if item["issue"] == "completed_event_child_beat_ids_not_covered")
        self.assertEqual(completed["missing_child_beat_ids"], ["E5-B2"])

    def test_merge_continuity_ledger_updates_structured_prop_positions(self):
        """Verify merge continuity ledger updates structured prop positions."""
        merged = pipeline_runner.merge_continuity_ledger(
            {"foreshadowing_status": [], "prop_positions": {}},
            episode={"episode_num": 3, "title": "手机被拿走"},
            output={
                "final_script": "第三集",
                "continuity_update": {
                    "prop_state_updates": [
                        {
                            "prop_id": "PROP_PHONE_FANGHUA",
                            "prop_name": "方华的手机",
                            "holder": "爷爷",
                            "location": "爷爷手中",
                            "status": "可用",
                            "change_evidence": "△爷爷从方华手里拿走手机。",
                        }
                    ]
                },
            },
        )

        state = merged["prop_positions"]["PROP_PHONE_FANGHUA"]
        self.assertEqual(state["holder"], "爷爷")
        self.assertEqual(state["updated_episode"], 3)

    def test_merge_continuity_ledger_preserves_prop_identity_on_id_collision(self):
        """Verify merge continuity ledger preserves prop identity on id collision."""
        ledger = {
            "prop_positions": {
                "D2": {
                    "prop_name": "营养糊",
                    "holder": "无",
                    "location": "马桶",
                    "status": "已丢弃",
                    "updated_episode": 2,
                }
            }
        }
        output = {
            "continuity_update": {
                "prop_state_updates": [
                    {
                        "prop_id": "D2",
                        "prop_name": "备用手机",
                        "holder": "方华",
                        "location": "枕头下",
                        "status": "可用",
                        "change_evidence": "方华拿出备用手机",
                    }
                ]
            }
        }

        merged = pipeline_runner.merge_continuity_ledger(
            ledger,
            episode={"episode_num": 3, "title": "备用手机"},
            output=output,
        )

        self.assertEqual(merged["prop_positions"]["D2"]["prop_name"], "营养糊")
        self.assertEqual(merged["prop_identity_conflicts"][0]["incoming_prop_name"], "备用手机")
        compact = pipeline_runner.compact_continuity_context(merged)
        self.assertEqual(compact["prop_identity_conflicts"][0]["conflict_episode_num"], 3)

    def test_prop_lifecycle_reappearance_warns_without_new_lineage(self):
        """Verify prop lifecycle reappearance warns without new lineage."""
        scripts = [
            {
                "episode_num": 1,
                "final_script": "第一集\n△方华把三罐花生酱扔进垃圾桶。",
                "continuity_update": {
                    "prop_state_updates": [
                        {
                            "prop_id": "PROP_PEANUT_BUTTER",
                            "prop_name": "三罐花生酱",
                            "holder": "无",
                            "location": "公共垃圾桶",
                            "status": "已丢弃",
                        }
                    ]
                },
            },
            {
                "episode_num": 3,
                "final_script": "第三集\n△爷爷从罐里舀出花生酱拌进碗里。",
                "continuity_update": {"prop_state_updates": []},
            },
        ]

        findings = pipeline_runner.analyze_prop_lifecycle_reappearance(scripts)

        self.assertEqual(findings[0]["issue"], "retired_prop_reappears_without_new_lineage")
        self.assertEqual(findings[0]["from_episode"], 1)
        self.assertEqual(findings[0]["to_episode"], 3)

    def test_prop_lifecycle_reappearance_allows_visible_new_lineage_id(self):
        """Verify prop lifecycle reappearance allows visible new lineage id."""
        scripts = [
            {
                "episode_num": 1,
                "final_script": "第一集\n△旧花生酱被扔进垃圾桶。",
                "continuity_update": {
                    "prop_state_updates": [
                        {
                            "prop_id": "PROP_OLD_PEANUT_BUTTER",
                            "prop_name": "花生酱",
                            "holder": "无",
                            "location": "垃圾桶",
                            "status": "已丢弃",
                        }
                    ]
                },
            },
            {
                "episode_num": 2,
                "final_script": "第二集\n△爷爷拆开新买的花生酱。",
                "continuity_update": {
                    "prop_state_updates": [
                        {
                            "prop_id": "PROP_NEW_PEANUT_BUTTER",
                            "prop_name": "花生酱",
                            "holder": "爷爷",
                            "location": "爷爷手中",
                            "status": "新购",
                        }
                    ]
                },
            },
        ]

        self.assertEqual(pipeline_runner.analyze_prop_lifecycle_reappearance(scripts), [])

    def test_prop_state_continuity_reports_holder_jump_and_missing_script_evidence(self):
        """Verify prop state continuity reports holder jump and missing script evidence."""
        output = {
            "final_script": "第四集\n4-1    林悦家    日    内\n出场人物：方华\n△方华走进客厅。",
            "continuity_update": {
                "prop_state_updates": [
                    {
                        "prop_id": "PROP_PHONE_FANGHUA",
                        "prop_name": "方华的手机",
                        "holder": "方华",
                        "location": "方华手中",
                        "status": "可用",
                        "change_evidence": "△爷爷把手机还给方华。",
                    }
                ]
            },
        }
        episode = {
            "episode_num": 4,
            "prop_continuity_plan": [
                {
                    "prop_id": "PROP_PHONE_FANGHUA",
                    "prop_name": "方华的手机",
                    "start_holder": "方华",
                    "start_location": "方华手中",
                    "end_holder": "方华",
                    "end_location": "方华手中",
                    "transfer_action": "",
                    "completion_evidence": "方华拿着手机",
                }
            ],
        }
        previous = {
            "PROP_PHONE_FANGHUA": {
                "prop_name": "方华的手机",
                "holder": "爷爷",
                "location": "爷爷手中",
            }
        }

        findings = validators.prop_state_continuity_findings(
            output,
            episode_outline=episode,
            previous_prop_positions=previous,
        )

        self.assertTrue(any(item["issue"] == "prop_plan_start_state_mismatch" for item in findings))
        self.assertTrue(any(item["issue"] == "prop_change_evidence_not_found_in_script" for item in findings))

    def test_prop_location_compatibility_allows_more_specific_container(self):
        """Verify prop location compatibility allows more specific container."""
        self.assertTrue(validators.prop_location_states_compatible("林可家客房书包内", "林可家客房·方华书包侧袋内"))
        self.assertTrue(validators.prop_location_states_compatible("林可家客房书包内", "书包侧袋"))
        self.assertTrue(validators.prop_location_states_compatible("书包侧袋", "方华房间·书包侧袋内"))
        self.assertFalse(validators.prop_location_states_compatible("方华手中", "方华书桌上"))
        self.assertFalse(validators.prop_location_states_compatible("已冲入马桶", "床底"))

    def test_prop_evidence_matching_allows_punctuation_and_partial_clause_variation(self):
        """Verify prop evidence matching allows punctuation and partial clause variation."""
        script = (
            "△方华推开卫生间门，反锁。她蹲在马桶前，将碗里的糊一倾而下全部倒入马桶，"
            "糊顺着瓷壁滑落。她按下冲水键，水声哗响。"
        )
        evidence = "△方华蹲在马桶前，将碗里的糊一倾而下全部倒入马桶，糊顺着瓷壁滑落。她按下冲水键，水声哗响。"
        self.assertTrue(validators.prop_evidence_matches_script(evidence, script))
        self.assertTrue(
            validators.prop_evidence_matches_script(
                "△方华把手机放下，翻开桌上最上面那本复习笔记。",
                "△方华把手机放下，翻开桌上最上面那本复习笔记，翻到夹着书签的那一页。",
            )
        )
        self.assertFalse(validators.prop_evidence_matches_script("方华把手机藏进床底并删除记录", "方华拿起手机看了一眼"))

    def test_prop_continuity_plan_reports_id_reused_for_different_name(self):
        """Verify prop continuity plan reports id reused for different name."""
        common = {
            "start_holder": "方华",
            "start_location": "方华手中",
            "end_holder": "方华",
            "end_location": "方华手中",
            "transfer_action": "无变化",
            "completion_evidence": "方华持有",
        }
        findings = validators.prop_continuity_plan_findings(
            [
                {"episode_num": 1, "prop_continuity_plan": [{"prop_id": "D2", "prop_name": "营养糊", **common}]},
                {"episode_num": 2, "prop_continuity_plan": [{"prop_id": "D2", "prop_name": "备用旧手机", **common}]},
            ]
        )

        item = next(value for value in findings if value["issue"] == "prop_id_reused_for_different_name")
        self.assertEqual(item["previous_prop_name"], "营养糊")
        self.assertEqual(item["current_prop_name"], "备用旧手机")

    def test_structured_prop_state_quality_is_warning_only_in_collect_mode(self):
        """Verify structured prop state quality is warning only in collect mode."""
        stage_outputs = {
            "05_plot_character_adaptation": {"event_pool": [], "foreshadowing_pool": []},
            "06_script_outline_design": {"block_state_plan": [], "event_release_schedule": []},
        }
        episode = {
            "episode_num": 1,
            "block_id": 1,
            "event_ids": [],
            "consumed_child_beat_ids": [],
            "main_conflict": "爷爷拿走手机",
            "counterattack": "方华要求归还",
            "ending_hook": "手机仍在爷爷手里",
            "conflict_mode": "道具争夺",
            "pattern_family": "家庭冲突",
            "boundary_check": {"risk_level": "low"},
            "content_sensitivity_check": {"risk_level": "low"},
            "prop_continuity_plan": [
                {
                    "prop_id": "PROP_PHONE",
                    "prop_name": "手机",
                    "start_holder": "方华",
                    "start_location": "方华手中",
                    "end_holder": "爷爷",
                    "end_location": "爷爷手中",
                    "transfer_action": "爷爷拿走手机",
                    "completion_evidence": "爷爷拿着手机",
                }
            ],
        }
        final_scripts = [
            {
                "episode_num": 1,
                "final_script": "第一集\n1-1    家中    日    内\n出场人物：方华、爷爷\n△爷爷拿走手机。",
                "continuity_update": {"prop_state_updates": []},
            }
        ]

        qa = pipeline_runner.build_qa_summary(
            stage_outputs,
            [episode],
            target_episodes=1,
            derived_config={"epilogue_max_episodes": 1, "conflict_mode_streak_limit": 2},
            final_scripts=final_scripts,
            validation_mode="collect",
        )

        self.assertEqual(qa["overall_status"], "PASS")
        self.assertEqual(qa["check_results"]["prop_state_continuity"], "WARN")
        self.assertTrue(any(item.get("check") == "prop_state_continuity" for item in qa["warnings"]))

    def test_stage_contract_requires_event_child_beat_object_fields(self):
        """Verify stage contract requires event child beat object fields."""
        report = validators.stage_contract_report(
            "05_plot_character_adaptation",
            {
                "macro_arcs": [],
                "event_pool": [{"child_beats": [{"child_beat_id": "E1-B1", "action": "拿走手机"}]}],
                "conflict_engine": {},
                "expanded_character_network": [],
                "foreshadowing_pool": [],
                "mapping_trace": [],
            },
        )

        self.assertIn(
            "05_plot_character_adaptation.event_pool[0].child_beats[0].completion_evidence missing",
            report["errors"],
        )

    def test_stage_contract_requires_prop_state_update_fields(self):
        """Verify stage contract requires prop state update fields."""
        report = validators.stage_contract_report(
            "08_script_body_generation",
            {
                "schema_version": "08_episode_delta_v2",
                "final_script": "第一集",
                "state_update": {
                        "audience_fact_changes": [],
                        "character_knowledge_changes": [],
                        "private_fact_changes": [],
                        "next_episode_bridge": "下一拍",
                    },
                "continuity_update": {
                    "completed_beat_ids": [],
                    "foreshadowing_changes": [],
                    "open_thread_changes": [],
                    "scene_boundary_check": {
                            "scene_count": 1,
                            "same_setting_split_count": 0,
                            "allowed_same_setting_splits": [],
                            "merge_note": "",
                        },
                    "narration_device_usage": {
                            "os_count": 0,
                            "flashback_count": 0,
                            "vo_count": 0,
                            "replacement_strategy_used": "",
                        },
                    "last_scene_state": {"location": "家中", "present_character_names": [], "visible_result": ""},
                    "prop_state_changes": [
                            {
                                "prop_id": "PROP_PHONE",
                                "operation": "update",
                                "holder": "爷爷",
                                "location": "爷爷手中",
                                "status": "可用",
                            },
                        ],
                },
            },
        )

        self.assertIn(
            "08_script_body_generation.continuity_update.prop_state_changes[0].evidence missing",
            report["errors"],
        )


if __name__ == "__main__":
    unittest.main()
