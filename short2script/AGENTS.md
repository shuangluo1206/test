# 项目协作规范

## 目标

搭建短篇小说扩写 40-100 集中文短漫剧剧本的可追溯管线，交付项目内 Skill、环节 CSV 和干净 prompt 文件夹。

## 目录规则

- `docs/` 保存只读输入资料，不在此目录写模型输出或中间结果。
- `configs/` 保存用户可调的运行配置，例如目标集数、单集时长、改写强度和支线策略。
- `prompts/clean/` 保存可交付 prompt 模板，不夹带模型 response、日志或分析说明。
- `skills/` 保存项目内 Codex Skill，每个 Skill 独立目录。
- `outputs/` 保存 CSV、报告、交付清单等派生产物。
- `runs/` 保存每次执行产物，包含 prompt、raw output、clean output、parsed、logs、manifests、readable_outputs、final；此目录可随时重跑生成，不入库。
- `runs/<run_id>/editorial_review/` 只保存对既有运行产物的独立只读审稿结果；审稿不得改写 clean JSON、不得回写 prompt，也不得改变生成 run 的 gate 或状态。

## 修改规则

- 不修改业务方源文档：`/Users/cjlbd/Documents/ChengObsidian/资料/业务方文档/260622-【短篇小说扩写剧本】剧本需求.md`。
- 不修改测试小说：`docs/固执爷爷听不懂人话.txt`。
- 不修改新增验收小说：`docs/清明回村，村口情报组织造谣我在城里做皮肉生意-96858.txt`。
- 需要调整目录或交付约定时，先更新本文件或 `README.md`，再改实践。
- 不写入 `.env`、token、密码或任何密钥。
- 不自动执行 `git push`。

## 验证规则

改完脚本、prompt、Skill 或 stage 配置后，至少运行：

```bash
python3 -m unittest skills/short-novel-script-pipeline/scripts/test_pipeline_tools.py
python3 /Users/cjlbd/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/short-novel-script-pipeline
python3 skills/short-novel-script-pipeline/scripts/export_stage_table.py --check
python3 skills/short-novel-script-pipeline/scripts/pipeline_runner.py --novel docs/固执爷爷听不懂人话.txt --run-config configs/minimal_real_5ep.json --run-id dryrun_config_5ep --generate-episodes 5 --dry-run
python3 skills/short-novel-script-pipeline/scripts/pipeline_runner.py --novel docs/清明回村，村口情报组织造谣我在城里做皮肉生意-96858.txt --run-config configs/qingming_40ep.json --run-id dryrun_qingming_40ep --generate-episodes 5 --dry-run
```
