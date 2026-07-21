#!/usr/bin/env python3
"""Utilities for the short novel script pipeline."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import llm_client
import parsers


EDITORIAL_DIMENSIONS = (
    "欲望",
    "阻力",
    "选择",
    "代价",
    "可见结果",
    "尾钩",
    "主角主动性",
    "信息增量",
    "爽点兑现",
    "台词个性",
    "可拍摄性",
    "源故事情绪保留",
)
DEFAULT_EPISODE_WINDOWS = (3, 5, 10)


def read_json(path: Path, default: Any) -> Any:
    """Handle read json."""
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_run_context(run_dir: Path) -> dict[str, Any]:
    """Handle load run context."""
    outputs = run_dir / "outputs"
    parsed = run_dir / "parsed"
    final = run_dir / "final"
    episode_outputs: list[dict[str, Any]] = []
    for path in sorted(outputs.glob("08_script_body_generation_ep*.clean.json")):
        data = read_json(path, {})
        episode_outputs.append(
            {
                "artifact_id": path.name.removesuffix(".clean.json"),
                "episode_num": int(path.stem.split("ep")[-1].split(".")[0]),
                "final_script": data.get("final_script", ""),
                "state_update": data.get("state_update", {}),
                "continuity_update": data.get("continuity_update", {}),
            }
        )
    return {
        "run_id": run_dir.name,
        "novel_summary": read_json(outputs / "01_novel_summary.clean.json", {}),
        "source_fact_ledger": read_json(
            outputs / "03_plot_character_extract.clean.json",
            {},
        ).get("source_fact_ledger", []),
        "adaptation_direction": read_json(outputs / "04_adaptation_direction.clean.json", {}),
        "season_plan": read_json(outputs / "07_episode_planning.clean.json", {}),
        "season_plan_audit": read_json(parsed / "season_plan_audit.json", {}),
        "qa_summary": read_json(final / "qa_summary.json", {}),
        "episode_outputs": episode_outputs,
    }


def review_context_for_scope(
    context: dict[str, Any],
    *,
    mode: str,
    episode_limit: int | None = None,
) -> dict[str, Any]:
    """Handle review context for scope."""
    shared = {
        "run_id": context.get("run_id"),
        "novel_summary": context.get("novel_summary", {}),
        "source_fact_ledger": context.get("source_fact_ledger", []),
        "adaptation_direction": context.get("adaptation_direction", {}),
        "season_plan_audit": context.get("season_plan_audit", {}),
        "qa_warnings": context.get("qa_summary", {}).get("warnings", []),
    }
    season_plan = context.get("season_plan", {})
    if mode == "season":
        return {**shared, "season_plan": season_plan}
    limit = int(episode_limit or 0)
    outlines = [
        item
        for item in season_plan.get("episode_outlines", [])
        if isinstance(item, dict) and int(item.get("episode_num", 0)) <= limit
    ]
    scripts = [
        item
        for item in context.get("episode_outputs", [])
        if int(item.get("episode_num", 0)) <= limit
    ]
    return {**shared, "episode_outlines": outlines, "episode_outputs": scripts}


def build_review_prompt(*, context: dict[str, Any], mode: str, scope_label: str) -> str:
    """Handle build review prompt."""
    dimensions = "、".join(EDITORIAL_DIMENSIONS)
    return "\n\n".join(
        [
            "# 任务目标",
            f"你是中文短剧总编剧和导演。只读审查已有管线产物，审稿模式为{mode}，审查范围为{scope_label}。不要改写剧本，不要生成新分集，不要直接修改任何 prompt。",
            "## 判断原则",
            (
                "从观众是否继续追看和戏剧因果是否成立出发。区分确定性工程问题、文学判断和个人偏好；每个负面结论必须引用当前材料中的具体集数、情节或台词。改进建议必须定位到最早根因环节，并说明与"
                " schema、连续性、自由文本表达或 warning-only 机制的潜在冲突。"
            ),
            "## 固定审稿维度",
            dimensions,
            "## 输入材料",
            json.dumps(context, ensure_ascii=False, indent=2),
            "## 输出 JSON 契约",
            """{
  "审稿模式": "season或episodes",
  "审查范围": "",
  "总体判断": "",
  "维度评分": [
    {
      "维度": "欲望",
      "分数": 1,
      "证据": [""],
      "问题": [""],
      "改进建议": [""]
    }
  ],
  "阻断性问题": [],
  "优势": [],
  "根因分析": [
    {"问题": "", "最早根因环节": "", "根因": ""}
  ],
  "管线改进建议": [
    {"影响环节": "", "建议": "", "工程冲突": "", "取舍": ""}
  ]
}""",
            "## 输出规则",
            f"维度评分必须正好覆盖这12项且不重不漏：{dimensions}。分数使用1-10整数。没有问题或优势时写空数组。只返回单个合法 JSON 对象；第一字符是 {{，最后一字符是 }}。",
        ]
    )


def validate_review_report(report: dict[str, Any]) -> None:
    """Handle validate review report."""
    required = {"审稿模式", "审查范围", "总体判断", "维度评分", "阻断性问题", "优势", "根因分析", "管线改进建议"}
    missing = sorted(required - set(report))
    if missing:
        raise ValueError(f"editorial report missing fields: {missing}")
    scores = report.get("维度评分")
    if not isinstance(scores, list):
        raise ValueError("editorial report 维度评分 must be a list")
    dimensions = [str(item.get("维度", "")) for item in scores if isinstance(item, dict)]
    if set(dimensions) != set(EDITORIAL_DIMENSIONS) or len(dimensions) != len(EDITORIAL_DIMENSIONS):
        raise ValueError(f"editorial dimensions mismatch: {dimensions}")
    for index, item in enumerate(scores):
        score = item.get("分数") if isinstance(item, dict) else None
        if not isinstance(score, int) or not 1 <= score <= 10:
            raise ValueError(f"维度评分[{index}].分数 must be an integer from 1 to 10")


def _list_lines(values: Any, *, empty: str = "无") -> list[str]:
    """Handle list lines."""
    if not isinstance(values, list) or not values:
        return [f"- {empty}"]
    return [f"- {str(item) if not isinstance(item, dict) else json.dumps(item, ensure_ascii=False)}" for item in values]


def render_review_markdown(report: dict[str, Any]) -> str:
    """Handle render review markdown."""
    lines = [
        f"# {report.get('审查范围', '审稿报告')}",
        "",
        f"**总体判断：** {report.get('总体判断', '')}",
        "",
        "## 维度评分",
        "",
    ]
    for item in report.get("维度评分", []):
        lines.extend(
            [
                f"### {item.get('维度')}：{item.get('分数')}/10",
                "",
                "**证据**",
                *_list_lines(item.get("证据", [])),
                "",
                "**问题**",
                *_list_lines(item.get("问题", [])),
                "",
                "**改进建议**",
                *_list_lines(item.get("改进建议", [])),
                "",
            ]
        )
    for title, key in (("阻断性问题", "阻断性问题"), ("优势", "优势"), ("根因分析", "根因分析"), ("管线改进建议", "管线改进建议")):
        lines.extend([f"## {title}", "", *_list_lines(report.get(key, [])), ""])
    return "\n".join(lines).rstrip() + "\n"


def parse_episode_windows(value: str) -> tuple[int, ...]:
    """Handle parse episode windows."""
    windows = sorted({int(item.strip()) for item in value.split(",") if item.strip()})
    if not windows or any(item <= 0 for item in windows):
        raise ValueError("episode windows must contain positive integers")
    return tuple(windows)


def run_review(
    *,
    run_dir: Path,
    mode: str,
    episode_windows: tuple[int, ...] = DEFAULT_EPISODE_WINDOWS,
    llm_script_path: Path | None = None,
    timeout: int = 1800,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Handle run review."""
    context = load_run_context(run_dir)
    output_dir = run_dir / "editorial_review"
    output_dir.mkdir(parents=True, exist_ok=True)
    scopes: list[tuple[str, int | None]]
    if mode == "season":
        scopes = [("全季07规划", None)]
    else:
        scopes = [(f"EP1-{limit}", limit) for limit in episode_windows]
    available_episode_count = len(context.get("episode_outputs", []))
    results: list[dict[str, Any]] = []
    resolved_script = None if dry_run else (llm_script_path or llm_client.resolve_llm_script())
    if resolved_script is not None:
        resolved_script = resolved_script.expanduser().resolve()
    for scope_label, limit in scopes:
        artifact_id = "season" if limit is None else f"episodes_ep001_{limit:03d}"
        if limit is not None and available_episode_count < limit:
            results.append(
                {
                    "artifact_id": artifact_id,
                    "scope": scope_label,
                    "status": "SKIPPED",
                    "reason": f"only {available_episode_count} episode scripts available",
                },
            )
            continue
        review_context = review_context_for_scope(context, mode=mode, episode_limit=limit)
        prompt = build_review_prompt(context=review_context, mode=mode, scope_label=scope_label)
        prompt_path = output_dir / f"{artifact_id}.prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        if dry_run:
            results.append(
                {"artifact_id": artifact_id, "scope": scope_label, "status": "DRY_RUN", "prompt": prompt_path.name},
            )
            continue
        attempt_root = output_dir / "attempts" / artifact_id / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        result = llm_client.call_llm(
            prompt,
            llm_script=resolved_script,
            cwd=run_dir,
            timeout=timeout,
            retries=2,
            stage_id="editorial_review",
            attempts_dir=attempt_root,
        )
        (output_dir / f"{artifact_id}.raw.md").write_text(result.raw, encoding="utf-8")
        report = parsers.parse_json_payload(result.clean)
        if not isinstance(report, dict):
            raise ValueError(f"{artifact_id} editorial response must be a JSON object")
        validate_review_report(report)
        (output_dir / f"{artifact_id}.json").write_text(json.dumps(
            report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output_dir / f"{artifact_id}.md").write_text(render_review_markdown(report), encoding="utf-8")
        results.append(
            {"artifact_id": artifact_id, "scope": scope_label, "status": "PASS", "report": f"{artifact_id}.md"},
        )
    summary = {
        "run_id": run_dir.name,
        "mode": mode,
        "dry_run": dry_run,
        "results": results,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    """Handle build parser."""
    parser = argparse.ArgumentParser(description="Read-only editorial review for an existing pipeline run.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--mode", choices=("season", "episodes"), required=True)
    parser.add_argument("--episode-windows", default="3,5,10")
    parser.add_argument("--llm-script", default=None)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    """Handle main."""
    args = build_parser().parse_args(argv)
    summary = run_review(
        run_dir=Path(args.run_dir),
        mode=args.mode,
        episode_windows=parse_episode_windows(args.episode_windows),
        llm_script_path=Path(args.llm_script) if args.llm_script else None,
        timeout=args.timeout,
        dry_run=args.dry_run,
    )
    print(
        (
            f"OK: editorial review artifacts written to {Path(args.run_dir) / 'editorial_review'} ("
            f"{len(summary['results'])} scopes)"
        ),
    )


if __name__ == "__main__":
    main()
