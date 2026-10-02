# 短篇小说改长剧本管线

本项目用于把 7k-5w 字中文短篇小说扩写为配置目标集数的中文短漫剧剧本生产链路，默认测试样本为 `docs/固执爷爷听不懂人话.txt`。用户没有任何显式配置且当前 run 没有同小说历史配置时，`00a_global_config` 会阅读整篇小说推荐全局参数和标签，默认目标为 40 集。

## 目录

- `docs/`：只读输入资料，当前包含测试小说。
- `configs/`：用户可调的全局运行配置，控制目标集数、单集时长、改写强度和扩写策略。
- `prompts/clean/`：每个管线环节的干净 prompt 模板。
- `skills/short-novel-script-pipeline/`：项目内 Codex Skill 和可运行脚本。
- `outputs/`：对外交付表格等派生产物。
- `runs/`：每次运行的 prompt、输出、日志、manifest、阅读版 clean JSON、可选独立审稿和最终结果；此目录不入库。

## 交付物

- `outputs/260622-短篇小说扩写剧本管线环节表.csv`
- `configs/minimal_real_5ep.json`
- `configs/qingming_40ep.json`
- `configs/wangquan_40ep.json`
- `prompts/clean/00a_全局参数推荐_global_config.md`，以及 `01_小说摘要_novel_summary.md` 到 `08_剧本正文生成_script_body_generation.md`
- `skills/short-novel-script-pipeline/`
- `outputs/260707-RD批量造数据交付说明.md`

## RD 批量生产交付

RD 批量造数据时以 CLI 为主入口，直接调用 `skills/short-novel-script-pipeline/scripts/pipeline_runner.py`；项目内 Skill 作为 Codex 交互入口和流程说明一起交付，不作为批处理依赖。

交付包必须包含 `skills/short-novel-script-pipeline/`、`prompts/clean/`、`configs/`、`outputs/260622-短篇小说扩写剧本管线环节表.csv`、`outputs/260707-RD批量造数据交付说明.md`、`README.md`、`AGENTS.md`、默认 OneAPI Opus 4.6 调用脚本 `skills/short-novel-script-pipeline/scripts/run_oneapi_claude_opus_4_6.sh` 和无密钥 LLM API 调用模板 `skills/short-novel-script-pipeline/scripts/rd_api_template.sh`；不得包含 `runs/`、`.env`、token/API key、未授权小说源文档。

批量生产命令模板：

```bash
python3 skills/short-novel-script-pipeline/scripts/pipeline_runner.py \
  --novel <novel.txt> \
  --run-config configs/wangquan_40ep.json \
  --run-id <unique_run_id> \
  --generate-episodes 40 \
  --episode-retries 1 \
  --timeout 1800
```

05 现在使用“基础资产 + 按弧线事件池”分批生成，每次 05 模型调用默认独立超时为 900 秒，可用 `--stage-05-timeout` 调整；其他环节仍使用 `--timeout`。

真实 run 默认使用 `skills/short-novel-script-pipeline/scripts/run_oneapi_claude_opus_4_6.sh`，该脚本只读取 `~/.short2script/.env-oneapi` 中的 `base_url` / `ONEAPI_API_KEY`，默认模型为 `Claude Opus 4.6`、`max_tokens=128000`、`output_config.effort=high`，并使用流式响应避免长请求被零信任网关按空闲连接切断。如需改走 LLM 或 Gemini，必须显式传 `--llm-script <script>`，默认不走其他 Opus 渠道。

全局配置解析优先级固定为：用户 `--run-config` 或任一配置 CLI 覆盖 > 同一 `run_id` 且小说 `sha256` 一致的 `parsed/00_run_config.json` > `00a_global_config` 的 LLM 推荐。只要用户显式指定任一配置项，就不调用 00a，未指定字段使用本地默认值；进入 00a 时目标集数由本地锁定为 40，不依赖模型自觉保持。解析来源、是否调用模型、系统锁定值和最终配置写入 `parsed/00a_global_config_resolution.json`。

自动配置示例：

```bash
python3 skills/short-novel-script-pipeline/scripts/pipeline_runner.py \
  --novel <novel.txt> \
  --run-id <unique_run_id> \
  --generate-episodes 5
```

默认运行使用 `validation_mode=collect`，优先产出完整可审计结果。验收以 `runs/<run_id>/final/qa_summary.json` 为准：`overall_status=PASS`、`generation_status=PASS`、`blocking_issues=[]` 表示结构完整并已生成；`quality_status=WARN` 表示仍有剧作、格式、节奏、闪回/OS/VO、地点或人物台账问题需要审查。阶段结构问题会同步写入 `runs/<run_id>/parsed/contract_reports/*.contract_report.json`，contract fail 时先看报告中的精确字段路径，再看同名 clean/raw 输出。需要恢复质量硬 gate 时加 `--strict-validation`。

LLM 边界默认使用中文字段：`prompts/` 中的真实 query 和模型原始 `raw.md` 面向专家阅读；响应解析后立即转回英文 canonical schema。`clean.json` 仅保留 contract 声明的 canonical 字段；模型额外字段进入 `parsed/unmapped_fields/`，normalizer 的修复过程进入 `parsed/normalization_reports/`，JSON 自动修复进入 `parsed/parser_reports/`，不再混入 clean。如果 parser 为了恢复可解析 JSON 而丢弃截断尾部，`content_discarded=true` 会单独报警。旧英文响应和无冲突的中英混合响应可继续使用；中英同义键值冲突仍硬失败。语言转换审计位于 `parsed/localization_reports/`。

00 会给原著段落生成稳定 `source_anchor_id`；02 评估自然改编容量但不改变用户配置集数；03 维护带行动者、动作、结果和证据锚点的 `source_fact_ledger`。04a 完成闪回筛选后，04b 固定全季逐集的欲望、阻力、选择、即时代价、可见结果和钩子，05-08 只消费对应 `DR_EPxxx`。04b 运行时拆成一次全局基础调用和每批最多 5 集的目标调用，终集单独生成，再由本地确定性合并为同一个 canonical clean，避免长响应尾项持续漏字段并明确终集钩子是余韵而非新悬念。05 的事件必须引用 `source_fact_ids`、`dramatic_target_ids` 并说明 `dramatic_delta`；每个子情节点是带 effect ID 和可选类型化 `process_transition` 的状态事务。runner 本地建立不可变事务表，07 只能消耗本集授权事务。07 merge 后输出全季审计；collect 模式只报警。

事务排期区分“新事务开头的时间锚点”和“事务内部等待后续结果”：前者用于切分集数，后者才属于非原子事务。考试、查分、申请、正式结果、通知和执行使用类型化阶段，不能跳级。05 某个事件分片若违反事务语义，runner 只把该分片的完整原输出和精确问题交回模型修复，最多两次，并在 `parsed/05_semantic_retry_failures/` 保留失败证据。05 的 `macro_arcs` 是 06 篇章边界的唯一来源；07 的事件、事务、道具初态和事实前态由本地 registry 确定性回填，不依赖模型重复抄写。05 道具表提供激活集数与初始状态，runner 在首个可变更集数前把实体写入账本。08 必须为每个授权 effect ID 返回正文逐字证据；事务、效果证据或 ledger 操作任一不合法时，剧本仍保留，但本集 delta 整体记为 `STATE_UNCOMMITTED`，不会部分污染权威状态。strict 模式同时停止运行。

08 每集只调用一次模型，返回 `08_episode_delta_v2` 的 `final_script + state_update + continuity_update`。模型只看到当前集去重执行单、最近 3 集完整剧本、active 连续性视图、最多 5 集且不超过 1000 字符的后续事件保留表，以及本集相关原著事实/闪回授权/主角边界；完整历史由本地 v2 ledger 维护并落盘。`prop_state_changes` 等变化使用稳定 ID 和 `add/update/resolve/retire`，不再让模型回传累计账本。每次 API attempt 与 `run_state.json` 都保留可审计状态；缺少 SSE 完整终止事件、API/解析/硬契约失败才中断，内容质量继续 warning-only。

默认会把 `outputs/*.clean.json` 转成专家可读 Markdown，输出到 `runs/<run_id>/readable_outputs/`，包含入口 `index.md`、每个 clean JSON 对应的 `.md`、`parse_report.json` 和 `parse_report.md`；解析模块按 clean JSON 原字段顺序直接展开，正文第一行就是第一个 JSON 字段，不再插入文件标题、生成时间，也不再生成“摘要 + 完整信息”的双层内容。模块会递归渲染所有 JSON path，正文优先显示中文阅读名，未知英文字段以“未登记字段 + 原字段名”显示并进入报告。新版渲染会清理旧阅读层遗留的 `*.readable.json` 和 `index.json`，避免误打开旧 JSON。需要减少产物时加 `--no-render-clean-md` 关闭。已有 run 可事后补生成：

```bash
python3 skills/short-novel-script-pipeline/scripts/clean_json_to_md.py --run-dir runs/<run_id>
```

独立审稿不属于默认生成 gate，也不会自动改剧本或 prompt。它只读取已有 run，可分别审查完整 07 全季规划，或审查 EP1-3 / EP1-5 / EP1-10：

```bash
python3 skills/short-novel-script-pipeline/scripts/editorial_review.py --run-dir runs/<run_id> --mode season
python3 skills/short-novel-script-pipeline/scripts/editorial_review.py --run-dir runs/<run_id> --mode episodes
```

结果写入 `runs/<run_id>/editorial_review/`，同时保存中文 Markdown、结构化评分、原始响应和不可变 attempt。审稿只用于人工决定是否从 5 集升级到 10 / 30 / full run。

## 常用命令

```bash
python3 -m unittest skills/short-novel-script-pipeline/scripts/test_pipeline_tools.py
python3 quick_validate.py skills/short-novel-script-pipeline
python3 skills/short-novel-script-pipeline/scripts/export_stage_table.py --check
python3 skills/short-novel-script-pipeline/scripts/pipeline_runner.py --novel docs/固执爷爷听不懂人话.txt --run-config configs/minimal_real_5ep.json --run-id dryrun_config_5ep --generate-episodes 5 --dry-run
```

真实最小跑通使用解析后的全局配置生成规划和前 5 集正文。默认 5 集和 full run 都不因内容质量问题中断，问题统一进入 `warnings` 和 `parsed/full_run_issue_log.json`；只有 API/解析/字段契约缺失、08 缺核心字段、集数不足或 `episode_num` 不连续会阻断。完整真实生成不是最小验收项，后续可按成本和稳定性拆分执行：

```bash
python3 skills/short-novel-script-pipeline/scripts/pipeline_runner.py --novel docs/固执爷爷听不懂人话.txt --run-config configs/minimal_real_5ep.json --run-id run_opus46_minimal_5ep --generate-episodes 5
```

40 集新小说验收命令：

```bash
python3 skills/short-novel-script-pipeline/scripts/pipeline_runner.py --novel docs/清明回村，村口情报组织造谣我在城里做皮肉生意-96858.txt --run-config configs/qingming_40ep.json --run-id run_qingming_40ep_10ep --generate-episodes 10
```
