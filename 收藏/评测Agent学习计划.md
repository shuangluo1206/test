# 评测工程师 Agent — 学习与开发计划

> 目标：读懂 my-easy-pi 源码 → 从零造一个「帮你跑 bench 评测的垂直 Agent」（简历项目）
>
> 参考仓库：`/Users/luoshuangshuang/Downloads/my-easy-pi-main/`（只当字典，卡住才翻）
>
> 制定日期：2026-09-28

---

## 一、项目是什么

**不复制 my-easy-pi 源码**，借鉴其分层思想，自己设计实现一个垂直领域 Agent：

- 通用教程项目都是「写代码的 Agent」，我做的是「**审代码的 Agent**」——评估 Agent 的 Agent
- 工具层全部换血为评测工具，Agent 循环理解后自己实现
- 接百度 key（自写 ERNIE Provider，参考 openai-compat 骨架）→ 简历叙事：百度背景 + 内部模型生态适配

**一句话简历**：
> 自研垂直领域 Coding Agent：手写 Agent 循环与工具分发（非框架），含多模型成本路由

---

## 二、时间预期（勿自欺）

总投入 **~23h，建议 5~6 天**（每天 4~5h 有效注意时间）。

| 环节 | 耗时 |
|---|---|
| 读核心三层源码（阶段一~三） | ~6.5h |
| 设计自己的架构 | ~2h |
| 写代码 + 调试 | ~10h |
| 联调（百度 key、真跑一轮） | ~3h |
| 沖价 + 修边界 | ~2h |

**时间紧的压缩版下限（~13h / 3 天）**：
只读阶段一+二 → MVP（Agent 循环 + `run_eval` + `read_trials` 两个工具 + 百度 Provider）→ 先跑通闭环再增量。

⚠️ 一天完成是幻觉：教程标 10.5h 是纯阅读。简历项目的价值在细节沉淀（loop 的坑、SSE 断流、retry 退避），不是「完成」那一刻。

---

## 三、读码路线（先读后写，每阶段有检查点）

### 阶段一：AI 层（~2h）—「Agent 的通信协议」

读 4 个文件（顺序 = 依赖顺序）：

| # | 文件 | 行数 | 带着这个问题读 |
|---|---|---|---|
| 1 | `src/ai/types.ts` | 177 | LLM 的输入输出长什么样？`ToolCall` 为何是整个系统的枢纽？ |
| 2 | `src/ai/registry.ts` | 57 | 怎么做到「换一个模型不动其他代码」？ |
| 3 | `src/ai/providers/anthropic.ts` | 219 | 流式 SSE 怎么解析？工具调用参数怎么从字节流拼出来？ |
| 4 | `src/ai/openai-compat.ts` | 147 | 为什么写一个 OpenAI 兼容层，DeepSeek/GLM/百度就都能接？ |

⭐ 百度 key 接入点就在这层。Provider = 抹平 HTTP 协议差异的适配器。

**检查点（读完回找 Claude 对答案）**：
1. `ToolCall` 长什么样（几个字段）？
2. `Model` 接口有哪些方法？
3. `LLMEvent` 有哪几种？

**✅ 2026-09-30 已对过答案（全部出自 types.ts）**：
1. `ToolCall` = **3 个字段**：`id`（回传结果对号入座）/ `name`（调哪个工具）/ `args`（已 parse 的对象，不是字符串）。它是模型到代码世界的唯一动作通道，串起 5 处：LLMEvent 生产 → loop 拼装 → 工具执行分发 → LLMMessage 记账 → buildRequestBody 回传
2. `Model` 接口 = **2 属性 + 3 方法**：`id` / `provider`；`stream(context, options)`（唯一干活方法，返回 AsyncIterable<LLMEvent>）/ `supportsTools()` / `supportsThinking()`。定义在 types.ts:118，三家实现在 anthropic.ts:69 / openai.ts:67 / deepseek.ts:67，loop.ts:285 是唯一调用点
3. `LLMEvent` **6 种**：`text_delta`（吐字）/ `tool_call_start`（要工具，带 id+name）/ `tool_call_delta`（参数碎片）/ `thinking_delta`（思考）/ `error` / `done`（stopReason 区分 end_turn 还是 tool_use）

串起来记一条数据流：`Model.stream()` 吐事件 → 事件拼成 `ToolCall` → 执行 → 结果作为新消息喂回下一轮 `stream()`——这个环就是阶段二 loop.ts 那个 `while` 转的东西

### 阶段二：Agent 循环（~3h）— 项目的灵魂

只读 `src/agent/loop.ts`（583 行）+ `src/agent/queue.ts`（78 行），做三件事：

1. **找出主循环**：`while` 在哪？退出条件是什么？（LLM 说「我不再要工具」）
2. **画出一次完整循环的事件流**：
   `user message → llm stream → tool call → tool result → llm stream → ...`
3. **看懂三个钩子**：`beforeToolCall` / `afterToolCall` / `transformContext`
   → 将来的「判分器前置检查」就挂在钩子上，**这是垂直化的关键接口**

辅助：`src/agent/permission.ts`（188 行，权限系统怎么拦截工具调用，评测场景可简化但要懂原理）

**✅ 2026-09-30 学完，三件事答案：**

1. **主循环**：`while (true)` 在 loop.ts:173 的 `runLoop()`。三个出口：① 模型不再要工具且队列空（L212-230）→ break；② 所有工具返回 `terminate: true`（L260-262）→ break；③ prompt 入口 `isStreaming` 检查（L131-133）拒绝并发。出口①里有隐藏门：模型说完但 steering/followUp 队列有货 → continue 不下班（L221-226）。
2. **事件流**：`agent_start → [turn_start → (text_delta / tool_call_start / tool_call_delta → done 收官拼装) → message_end → tool_execution_start/end → turn_end] × N → agent_end`。拼装有两条路：流式（start 开罐→delta 片片 +=→done 时 JSON.parse，parse 失败兜底塞原始串 L347-353）与非流式（event.args 已完整直接入列 L309-316）。usage 是从 done 事件上用类型断言「蹭」出来的非规范字段（L287-294），因各家塞的位置不统一。
3. **三钩子**（都在 AgentLoopConfig 声明、构造时注入）：
   - `transformContext`（执行在 L177-179）：每轮发给 LLM 之前改历史。→ 我的用法：trajectory 大 JSON 摘要瘦身
   - `beforeToolCall`（执行在 L379-401）：工具执行前拦截。block 后不执行但会塞一条 isError toolResult（内容=拒绝理由）回历史，模型能看到并换姿势重试。→ 我的用法：判分器前置检查、参数校验
   - `afterToolCall`（执行在 L492-504）：工具执行后。返回 terminate:true 可触发出口②优雅收尾。→ 我的用法：分数达标提前收尾
   - **核心认知：循环骨架各家一模一样，垂直化差异全在钩子+工具层**

queue.ts：双队列（steering 高优/followUp 低优）+ next()，生效点在出口①的隐藏门。abort() 只断流不杀工具进程——长跑工具必须自己响应 signal（L443 传了，用不用看工具）。

**检验题 3/3 通过**：① block 的 toolCall 也会造一条 isError toolResult 入历史（2 条消息、1 条真执行）；② abort → signal 传给 stream() → fetch 断连 → for await 抛 AbortError 被 catch，循环不炸；③ toolResult 先入历史再判 terminate，否则 break 后历史凭空缺结果，续跑时模型会困惑重调

### 阶段三：工具层（~1.5h）— 将来全部换血的地方

- `src/tools/registry.ts` — 工具怎么注册、schema 怎么描述给 LLM
- `src/tools/builtin/bash.ts`（62 行）等，挑 2~3 个

⭐ 核心公式：**一个工具 = 名字 + 参数 schema + 执行函数**。读懂公式比读懂实现重要。

**✅ 2026-09-30 学完（读了 registry.ts 36 行 + read.ts + bash.ts + agent/types.ts 类型递进）：**

- **公式落地**：name（模型喊的）+ parameters schema（模型照着传参）+ execute（loop.ts:440 按 name 查 registry 后调它，返回必须是 ToolResult 形状 `{content:[{type:'text',text}]}`，不是裸字符串）
- **ToolRegistry 与 ModelRegistry 同一个套路**：`Map<名字, 实体>` + register/get/list，换血 = 换注册条目。将来这个模式要手写两遍
- **类型递进三层**（agent/types.ts 注释写明设计意图）：`Tool`（纯类型）→ `AgentTool extends Tool`（+execute）→ `ToolDefinition extends AgentTool`（+icon/category/dangerLevel UI 属性）。我的项目用前两层即可
- **bash.ts 值得抄的三个点**：① signal 一路传到底（长跑 run_eval 必须响应，否则取消按钮按了没反应 L38）；② onUpdate 流式回传（30 分钟黑盒→日志逐段冒出来 L33-34）；③ factory 模式注入 Operations（测试时换 fake ops 不用真跑 L14）
- **检验题 答案**：① ModelContext 时把全部工具的 schema 现发一遍（loop.ts:185-193），运行时注册新工具下一轮立刻生效；② 同名注册静默覆盖（Map.set），getTool 拿到后注册的——工具名要集中定义成常量防手滑；③ 循环不崩，loop.ts:472-486 的 try/catch 把异常变成 isError toolResult（内容=错误消息），模型能看到并重试；工具内部再 catch 一层是双层保险（read.ts:31-35 示范）

### 读码纪律

- **先自己啃代码，卡住再看 `docs/` 章节文档**——文档替你理解的部分就是面试被问住的部分
- 配套文档在 `docs/02-ai-layer/`、`docs/03-agent-layer/`、`docs/04-tools-layer/`

---

## 四、开发阶段（读完后，在新目录从零写）

### Step 1：架构设计（~2h）

找 Claude 出架构设计稿（模块划分 / 工具清单 / 循环定制点），自己审完再动手。
**不在 my-easy-pi 目录里改，新建自己的仓库。**

### Step 2：工具层设计（换血对象）

| 通用 Agent 的工具 | → 我的评测工具 |
|---|---|
| read/write file | `run_eval` 跑一轮试标 |
| bash | `read_trials` 读 trajectory.jsonl |
| grep/glob | `diff_gt` 比对 groundtruth |
| ... | `score_probe` 抽查判分点 |

Agent 循环的差异化行为：agent 看到 trials 结果 → 自己发现「C34 三轮全缺」→ 主动去 Grep 清单定位原因。

### Step 3：实现顺序

1. AI 层：types + ERNIE Provider（百度 key，照 openai-compat 骨架自己写）
2. Agent 循环：手写 while + 工具分发（不用框架）
3. 工具层：先 2 个（run_eval + read_trials）跑通 MVP，再增量加
4. 联调：真跑一轮评测，调 SSE 断流 / retry 退避 / 参数拼装
5. 可选亮点：多模型成本路由（简单任务走便宜模型）→ 挂在主线上当加分章节

### 工具环境

- TS 项目用 VS Code（Claude Code 全程可直接参与：读文件 / 跑测试 / 即时纠错）
- 若走 Java 重写版则用 IDEA（B 方案备选，未启用）

---

## 五、进度跟踪

- [x] 阶段一：AI 层读码 + 检查点三问通过（2026-09-30）
- [x] 阶段二：loop.ts 三件事做完（主循环 / 事件流 / 三钩子）（2026-09-30，检验题 3/3）
- [x] 阶段三：工具公式理解（2026-09-30，检验题 3/3）
- [x] Step 1：架构设计稿评审通过（2026-09-30）
- [x] Step 2~3：MVP 跑通（M1 AI 层冒烟 + M2 Agent 循环 fake 演示，2026-09-30）
- [x] 真跑一轮评测联调成功（M3：run_eval/read_trials 真工具 + GLM-5.3 真模型，2026-10-01，模型准确揪出轨迹里埋的 write_file 丢 path 坑）
- [x] M4 三钩子上线（瘦身/前置校验/达标收尾各验一例，2026-10-01，M2/M3 回归全 PASS）
- [x] （可选）多模型路由亮点完成（M5：当轮无缝切换 + write_file 丢 path 质量降级，2026-10-01，299e810）
- [x] 写进简历（2026-10-01 草稿完成：Downloads/简历-my-eval-agent项目栏.md，含完整版/精简版/电梯版/面试9问）

---

## 六、备忘

- my-easy-pi 总 9830 行（含 TUI），核心三层仅 2540 行，逐行中文注释
- 面试必问预判：「Agent 循环怎么转」「工具调用怎么实现」「工具执行失败怎么处理」——答案都在 loop.ts
- 相关记忆：秋招 4 个简历项目的取舍见 `Downloads/求职项目计划.md`
