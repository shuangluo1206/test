"""Utilities for the short novel script pipeline."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]
SKILL_ROOT = SCRIPT_DIR.parent
STAGES_PATH = SKILL_ROOT / "references" / "pipeline-stages.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs" / "260622-短篇小说扩写剧本管线环节表.csv"

HEADERS = [
    "环节ID",
    "环节名称",
    "所属阶段",
    "作用",
    "是否调用模型",
    "prompt文件",
    "输入参数",
    "输出参数",
    "输入输出映射关系",
    "依赖上游",
    "校验规则",
    "备注",
]


def load_stages() -> list[dict[str, Any]]:
    """Handle load stages."""
    return json.loads(STAGES_PATH.read_text(encoding="utf-8"))


def stage_to_row(stage: dict[str, Any]) -> dict[str, str]:
    """Handle stage to row."""
    return {
        "环节ID": stage["stage_id"],
        "环节名称": stage["stage_name"],
        "所属阶段": stage["phase"],
        "作用": stage["purpose"],
        "是否调用模型": "是" if stage["model"] else "否",
        "prompt文件": stage.get("prompt_file", ""),
        "输入参数": ", ".join(stage.get("inputs", [])),
        "输出参数": ", ".join(stage.get("outputs", [])),
        "输入输出映射关系": stage.get("mapping", ""),
        "依赖上游": ", ".join(stage.get("depends_on", [])),
        "校验规则": stage.get("validation", ""),
        "备注": stage.get("notes", ""),
    }


def validate_stage_assets(stages: list[dict[str, Any]]) -> None:
    """Handle validate stage assets."""
    if len(stages) != 13:
        raise ValueError(f"pipeline must define 13 stages, got {len(stages)}")
    stage_ids = [stage["stage_id"] for stage in stages]
    if len(stage_ids) != len(set(stage_ids)):
        raise ValueError("stage_id values must be unique")
    for stage in stages:
        prompt_file = stage.get("prompt_file") or ""
        if stage.get("model"):
            if not prompt_file:
                raise ValueError(f"{stage['stage_id']} is a model stage but has no prompt_file")
            if not (PROJECT_ROOT / prompt_file).exists():
                raise FileNotFoundError(f"prompt file missing for {stage['stage_id']}: {prompt_file}")
        elif prompt_file:
            raise ValueError(f"{stage['stage_id']} is local stage but defines prompt_file")


def export_stage_table(output: str | Path = DEFAULT_OUTPUT) -> list[dict[str, str]]:
    """Handle export stage table."""
    stages = load_stages()
    validate_stage_assets(stages)
    rows = [stage_to_row(stage) for stage in stages]
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main(argv: list[str] | None = None) -> None:
    """Handle main."""
    parser = argparse.ArgumentParser(description="Export the short novel pipeline stage table.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--check", action="store_true", help="Validate stage config and prompt assets while exporting.")
    args = parser.parse_args(argv)
    rows = export_stage_table(args.output)
    if args.check:
        print(f"OK: exported {len(rows)} stages to {args.output}")


if __name__ == "__main__":
    main()
