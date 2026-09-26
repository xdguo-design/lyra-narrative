# Long-form Continuity Ledger

NarrativeOS 的长篇生成不再把“最近若干字符正文”当作唯一连续性来源。

## 目标

解决多章生成后常见的三类漂移：

1. 人物状态漂移：伤势、知识、称谓、秘密与关系变化被重置。
2. 世界规则漂移：道具次数恢复、地点损坏消失、规则被临时新增或反转。
3. 章节衔接漂移：上一章已经发生的场景再次重演，大段复制前文，伏笔静默丢失。

## Story State

每个通过审核的章节生成一份完整 Story State snapshot，包含：

- characters：人物位置、身体状态、已知信息、关系变化、当前目标
- items：道具持有人、位置、损坏/消耗状态、剩余次数
- locations：地点损坏、封锁与可达性
- world_counters：窗口、次数等硬约束的当前值
- revealed_facts：已经揭露且不能重新变成未知的事实
- open_threads / closed_threads：未回收与已回收伏笔
- last_scene：章末时间、地点、在场人物、钩子
- do_not_reset：下一章最容易被错误重置的事实

状态保存在 SQLite 表 `story_state_snapshots`。每个 AgentRun 会把实际使用的 Story State 记录进
`agent_run_resources`，resource_type 为 `story_state`，便于审计和复现。

## 章节生成策略

下一章使用两类上下文：

- Story State：权威事实来源，必须完整继承。
- 最近 6000 字符正文：只负责语言、场景、语气和章末动作承接。

早期正文即使从 prose window 中被截掉，早期造成的不可逆状态也必须继续存在于 Story State。

读取状态时使用严格章节边界：

```
chapter N -> latest Story State where chapter_number < N
```

因此重写第 2 章时不会错误读取旧版本第 8 章的未来状态。

## 单调状态门禁

Story State updater 输出后会做确定性校验，不只依赖模型自检：

- 已出现人物、道具、地点、世界计数不能静默消失。
- 人物已经知道的信息不能丢失。
- 已发生的关系变化不能回退。
- revealed_facts 必须单调保留。
- closed_threads 不能重新打开。
- open_threads 必须继续存在，或明确移动到 closed_threads。

继承上一版状态的文本条目要求逐字保留，避免同义改写被误判为丢失。

任何状态提取失败或状态回退都会产生 blocking finding，并停止继续生成后续章节。

## 重复门禁

章节在审核前和最终输出后都会执行确定性重复检测：

- 40 字以上的叙事块参与检测。
- 章内重复字符占比 >= 8% -> blocking。
- 与前文章节完全重复占比 >= 12% -> blocking。
- 同一叙事块重复 >= 4 次 -> blocking。

首次命中会进入 Continuity Repair；修复后仍超阈值则章节保持 reviewed/blocking，不进入下一章。

## API

- `GET /api/projects/{project_id}/story-state`：当前最新状态
- `GET /api/projects/{project_id}/story-states`：按章节查看状态历史

## 长篇专项验收

固定压力测试入口：

```
python scripts/run_long_consistency_test.py
```

或 GitHub Actions：

`Long Form Consistency Test`

固定检查人物一致性、世界观规则、章节衔接三项。

通过条件：

- blocking = 0
- major = 0
- 三项最低分 >= 8/10
- 正文长度足以触发 prose window 截断，证明测试确实依赖 Story State 而不是完整前文

基线测试（引入 Story State 前）为：

- 人物一致性：1/10
- 世界观规则：1/10
- 章节衔接：0/10
- blocking 15 / major 16 / minor 5
- 8 章约 49k 字符，从第 4 章起早期正文被上下文窗口截断

该基线用于后续回归比较，不代表当前实现已经通过验收。
