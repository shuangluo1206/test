#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utilities for the short novel script pipeline."""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


from llm_schema_localization import FIELD_LABELS

@dataclass
class RenderTracker:
    """Group render tracker behavior."""
    rendered_paths: set[str] = field(default_factory=set)
    failed_paths: dict[str, str] = field(default_factory=dict)
    unknown_field_labels: dict[str, set[str]] = field(default_factory=dict)

    def mark_rendered(self, path: str) -> None:
        """Handle mark rendered."""
        if path:
            self.rendered_paths.add(path)

    def mark_failed(self, path: str, error: str) -> None:
        """Handle mark failed."""
        if path:
            self.failed_paths[path] = error


def markdown_heading(level: int, title: str) -> str:
    """Handle markdown heading."""
    safe_level = min(max(level, 1), 6)
    return f"{'#' * safe_level} {title}"


def clean_artifact_id(clean_path: Path) -> str:
    """Handle clean artifact id."""
    name = clean_path.name
    if name.endswith(".clean.json"):
        return name[: -len(".clean.json")]
    return clean_path.stem


def collect_json_paths(value: Any, base_path: str = "") -> list[str]:
    """Handle collect json paths."""
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{base_path}.{key}" if base_path else str(key)
            paths.append(child_path)
            paths.extend(collect_json_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{base_path}[{index}]" if base_path else f"[{index}]"
            paths.append(child_path)
            paths.extend(collect_json_paths(child, child_path))
    return paths


def build_coverage_report(
    *,
    all_paths: list[str],
    rendered_paths: list[str] | set[str],
    failed_paths: list[str] | set[str],
) -> dict[str, Any]:
    """Handle build coverage report."""
    all_path_set = set(all_paths)
    rendered_path_set = set(rendered_paths)
    failed_path_set = set(failed_paths)
    unrendered = sorted(all_path_set - rendered_path_set - failed_path_set)
    return {
        "total_json_paths": len(all_paths),
        "rendered_json_paths": sorted(rendered_path_set & all_path_set),
        "failed_json_paths": sorted(failed_path_set & all_path_set),
        "unrendered_json_paths": unrendered,
        "coverage_status": "PASS" if not unrendered and not failed_path_set else "FAIL",
    }


def fenced_text(value: str) -> str:
    """Handle fenced text."""
    fence = "```"
    if "```" in value:
        fence = "````"
    return f"{fence}text\n{value}\n{fence}"


def display_label(field_name: str, path: str, tracker: RenderTracker) -> str:
    """Handle display label."""
    label = FIELD_LABELS.get(field_name)
    if label is None:
        tracker.unknown_field_labels.setdefault(field_name, set()).add(path)
        if re.search(r"[\u4e00-\u9fff]", field_name):
            return field_name
        return f"未登记字段 {field_name}"
    return label


def format_expert_scalar(value: Any) -> str:
    """Handle format expert scalar."""
    if value is None:
        return "空值"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        if not value:
            return "无"
        return "、".join(format_expert_scalar(item) for item in value)
    if isinstance(value, dict):
        if not value:
            return "空对象"
        parts = []
        for key, child in value.items():
            label = FIELD_LABELS.get(str(key), str(key))
            parts.append(f"{label}：{format_expert_scalar(child)}")
        return "；".join(parts)
    text = str(value)
    return text if text else "空字符串"


def scalar_to_expert_markdown(value: Any, field_name: str | None = None) -> str:
    """Handle scalar to expert markdown."""
    if isinstance(value, str) and ("\n" in value or field_name == "final_script"):
        return "\n" + fenced_text(value)
    return format_expert_scalar(value)


def render_expert_value(
    value: Any,
    *,
    path: str,
    field_name: str | None,
    tracker: RenderTracker,
    level: int,
    title_override: str | None = None,
) -> list[str]:
    """Handle render expert value."""
    lines: list[str] = []
    if path:
        tracker.mark_rendered(path)
    title = title_override
    if title is None and field_name:
        title = display_label(field_name, path, tracker)

    if isinstance(value, dict):
        if path:
            lines.append(markdown_heading(level, title or "信息项"))
        if not value:
            lines.append("- 空对象")
            return lines
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            child_level = level + 1 if path else level
            try:
                if is_scalar(child):
                    tracker.mark_rendered(child_path)
                    child_label = display_label(str(key), child_path, tracker)
                    rendered = scalar_to_expert_markdown(child, str(key))
                    if rendered.startswith("\n"):
                        lines.append(f"**{child_label}：**{rendered}")
                    else:
                        lines.append(f"- {child_label}：{rendered}")
                else:
                    lines.extend(
                        render_expert_value(
                            child,
                            path=child_path,
                            field_name=str(key),
                            tracker=tracker,
                            level=child_level,
                        )
                    )
            except Exception as exc:  # pragma: no cover - defensive path-level reporting
                tracker.mark_failed(child_path, str(exc))
                lines.append(f"- {display_label(str(key), child_path, tracker)}：解析失败，{exc}")
        return lines

    if isinstance(value, list):
        if path:
            lines.append(markdown_heading(level, title or "列表"))
        lines.append(f"- 数量：{len(value)}")
        if not value:
            lines.append("- 空列表")
            return lines
        if all(is_scalar(item) for item in value):
            for item_index, item in enumerate(value):
                item_path = f"{path}[{item_index}]" if path else f"[{item_index}]"
                tracker.mark_rendered(item_path)
                lines.append(f"- {scalar_to_expert_markdown(item)}")
            return lines
        for item_index, item in enumerate(value):
            item_path = f"{path}[{item_index}]" if path else f"[{item_index}]"
            lines.extend(
                render_expert_value(
                    item,
                    path=item_path,
                    field_name=None,
                    tracker=tracker,
                    level=level + 1,
                    title_override=f"第{item_index + 1}项",
                )
            )
        return lines

    rendered = scalar_to_expert_markdown(value, field_name)
    if path:
        if rendered.startswith("\n"):
            lines.append(f"**{title or path}：**{rendered}")
        else:
            lines.append(f"- {title or path}：{rendered}")
    else:
        lines.append(rendered)
    return lines


def is_scalar(value: Any) -> bool:
    """Handle is scalar."""
    return value is None or isinstance(value, (str, int, float, bool))


def render_markdown_for_data(artifact_id: str, data: Any) -> tuple[str, dict[str, Any], RenderTracker]:
    """Handle render markdown for data."""
    tracker = RenderTracker()
    lines = render_expert_value(data, path="", field_name=None, tracker=tracker, level=1)

    all_paths = collect_json_paths(data)
    coverage = build_coverage_report(
        all_paths=all_paths,
        rendered_paths=tracker.rendered_paths,
        failed_paths=set(tracker.failed_paths),
    )
    return "\n".join(lines).rstrip() + "\n", coverage, tracker


def render_clean_json_file(clean_path: Path, readable_dir: Path) -> dict[str, Any]:
    """Handle render clean json file."""
    artifact_id = clean_artifact_id(clean_path)
    md_name = f"{artifact_id}.md"
    try:
        data = json.loads(clean_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "clean_file": clean_path.name,
            "md_file": "",
            "status": "FAIL",
            "error": f"JSON parse failed: {exc}",
            "coverage": None,
            "unknown_field_labels": {},
            "render_errors": [{"file": clean_path.name, "path": "", "error": str(exc)}],
        }

    try:
        markdown, coverage, tracker = render_markdown_for_data(artifact_id, data)
        readable_dir.mkdir(parents=True, exist_ok=True)
        (readable_dir / md_name).write_text(markdown, encoding="utf-8")
        render_errors = [
            {"file": clean_path.name, "path": path, "error": error}
            for path, error in sorted(tracker.failed_paths.items())
        ]
        return {
            "clean_file": clean_path.name,
            "md_file": md_name,
            "status": coverage["coverage_status"],
            "error": "",
            "coverage": coverage,
            "unknown_field_labels": {key: sorted(paths) for key, paths in tracker.unknown_field_labels.items()},
            "render_errors": render_errors,
        }
    except Exception as exc:
        return {
            "clean_file": clean_path.name,
            "md_file": "",
            "status": "FAIL",
            "error": f"Markdown render failed: {exc}",
            "coverage": None,
            "unknown_field_labels": {},
            "render_errors": [{"file": clean_path.name, "path": "", "error": str(exc)}],
        }


def write_index(readable_dir: Path, report: dict[str, Any], file_results: list[dict[str, Any]]) -> None:
    """Handle write index."""
    lines = [
        "# Clean JSON 阅读输出索引",
        "",
        f"- run_id：`{report['run_id']}`",
        f"- total_clean_json_files：{report['total_clean_json_files']}",
        f"- rendered_files：{len(report['rendered_files'])}",
        f"- failed_files：{len(report['failed_files'])}",
        f"- parse_report：[`parse_report.md`](parse_report.md) / [`parse_report.json`](parse_report.json)",
        "",
        "## 阶段文件",
    ]
    for result in file_results:
        clean_file = result["clean_file"]
        md_file = result.get("md_file") or ""
        status = result["status"]
        if md_file:
            lines.append(f"- `{status}` [{md_file}]({md_file})（来源：`{clean_file}`）")
        else:
            lines.append(f"- `FAIL` `{clean_file}`：{result.get('error', '')}")
    (readable_dir / "index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_parse_report_md(readable_dir: Path, report: dict[str, Any]) -> None:
    """Handle write parse report md."""
    lines = [
        "# Clean JSON Markdown 解析报告",
        "",
        f"- run_id：`{report['run_id']}`",
        f"- outputs_dir：`{report['outputs_dir']}`",
        f"- readable_outputs_dir：`{report['readable_outputs_dir']}`",
        f"- total_clean_json_files：{report['total_clean_json_files']}",
        f"- rendered_files：{len(report['rendered_files'])}",
        f"- failed_files：{len(report['failed_files'])}",
        "",
        "## 文件覆盖率",
    ]
    for clean_file, coverage in report["field_coverage_by_file"].items():
        lines.append(
            f"- `{clean_file}`：`{coverage['coverage_status']}`；"
            f"total={coverage['total_json_paths']}；rendered={len(coverage['rendered_json_paths'])}；"
            f"failed={len(coverage['failed_json_paths'])}；unrendered={len(coverage['unrendered_json_paths'])}"
        )
        if coverage["unrendered_json_paths"]:
            for path in coverage["unrendered_json_paths"]:
                lines.append(f"  - 未渲染：`{path}`")
    lines.append("")
    lines.append("## 失败文件")
    if report["failed_files"]:
        for clean_file in report["failed_files"]:
            lines.append(f"- `{clean_file}`")
    else:
        lines.append("- 无")
    lines.append("")
    lines.append("## 未登记中文名字段")
    if report["unknown_field_labels"]:
        for item in report["unknown_field_labels"]:
            paths = "、".join(f"`{path}`" for path in item["paths"][:20])
            extra = "" if len(item["paths"]) <= 20 else f" 等 {len(item['paths'])} 处"
            lines.append(f"- `{item['field_name']}`：{paths}{extra}")
    else:
        lines.append("- 无")
    lines.append("")
    lines.append("## 渲染错误")
    if report["render_errors"]:
        for error in report["render_errors"]:
            path = error.get("path") or "文件级"
            lines.append(f"- `{error.get('file', '')}` `{path}`：{error.get('error', '')}")
    else:
        lines.append("- 无")
    (readable_dir / "parse_report.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def remove_legacy_readable_json_outputs(readable_dir: Path) -> list[str]:
    """Handle remove legacy readable json outputs."""
    removed: list[str] = []
    if not readable_dir.exists():
        return removed
    legacy_paths = list(readable_dir.glob("*.readable.json"))
    legacy_index = readable_dir / "index.json"
    if legacy_index.exists():
        legacy_paths.append(legacy_index)
    for path in sorted(set(legacy_paths)):
        if not path.is_file():
            continue
        path.unlink()
        removed.append(path.name)
    return removed


def render_run_clean_json_to_md(
    *,
    run_dir: str | Path | None = None,
    outputs_dir: str | Path | None = None,
    readable_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Handle render run clean json to md."""
    if run_dir is None and outputs_dir is None:
        raise ValueError("Either run_dir or outputs_dir is required")
    run_path = Path(run_dir) if run_dir is not None else None
    outputs_path = Path(outputs_dir) if outputs_dir is not None else (run_path / "outputs" if run_path else None)
    if outputs_path is None:
        raise ValueError("outputs_dir could not be resolved")
    readable_path = Path(readable_dir) if readable_dir is not None else (
        run_path / "readable_outputs" if run_path is not None else outputs_path.parent / "readable_outputs"
    )
    readable_path.mkdir(parents=True, exist_ok=True)
    removed_legacy_files = remove_legacy_readable_json_outputs(readable_path)
    clean_files = sorted(outputs_path.glob("*.clean.json"))
    file_results = [render_clean_json_file(path, readable_path) for path in clean_files]

    rendered_files = [result["clean_file"] for result in file_results if result.get("md_file")]
    failed_files = [result["clean_file"] for result in file_results if not result.get("md_file")]
    field_coverage_by_file = {
        result["clean_file"]: result["coverage"]
        for result in file_results
        if result.get("coverage") is not None
    }
    unknown_fields: dict[str, set[str]] = {}
    render_errors: list[dict[str, str]] = []
    for result in file_results:
        for field_name, paths in result.get("unknown_field_labels", {}).items():
            unknown_fields.setdefault(field_name, set()).update(paths)
        render_errors.extend(result.get("render_errors", []))
        if result.get("error"):
            render_errors.append({"file": result["clean_file"], "path": "", "error": result["error"]})

    report = {
        "run_id": run_path.name if run_path is not None else outputs_path.parent.name,
        "outputs_dir": str(outputs_path),
        "readable_outputs_dir": str(readable_path),
        "total_clean_json_files": len(clean_files),
        "rendered_files": rendered_files,
        "failed_files": failed_files,
        "field_coverage_by_file": field_coverage_by_file,
        "unknown_field_labels": [
            {"field_name": field_name, "paths": sorted(paths)}
            for field_name, paths in sorted(unknown_fields.items())
        ],
        "render_errors": render_errors,
        "removed_legacy_files": removed_legacy_files,
    }
    (readable_path / "parse_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_parse_report_md(readable_path, report)
    write_index(readable_path, report, file_results)
    return report


def build_parser() -> argparse.ArgumentParser:
    """Handle build parser."""
    parser = argparse.ArgumentParser(description="Render pipeline *.clean.json outputs into readable Markdown files.")
    parser.add_argument("--run-dir", default=None, help="Run directory, for example runs/<run_id>.")
    parser.add_argument("--outputs-dir", default=None, help="Directory containing *.clean.json files.")
    parser.add_argument("--readable-dir", default=None, help="Optional output directory for readable markdown.")
    return parser


def main(argv: list[str] | None = None) -> None:
    """Handle main."""
    parser = build_parser()
    args = parser.parse_args(argv)
    report = render_run_clean_json_to_md(
        run_dir=args.run_dir,
        outputs_dir=args.outputs_dir,
        readable_dir=args.readable_dir,
    )
    print(f"OK: rendered {len(report['rendered_files'])} clean json files to {report['readable_outputs_dir']}")


if __name__ == "__main__":
    main()
