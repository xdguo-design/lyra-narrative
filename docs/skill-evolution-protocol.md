# NarrativeOS Skill Evolution Protocol v1

## 目标

把人工验收、外部读者、编辑、线上生成事故中发现的“模型还不会的问题”，转化为可版本化、可回归、可撤销的 Skill 能力。

核心原则：

> 人工发现问题不是永久新增一道人工工序，而是训练信号。
> 同类问题一旦被成功泛化并验证，后续必须由 Skill / Reader / Reviewer 自动承担。

本协议适用于：
- Writer Skill
- Reader Skill
- Editor Skill
- Reviewer / Gate
- Scene Director
- Character / Dialogue rules
- Failure Corpus
- 长篇结构 Gate

---

# 1. 触发条件

以下任一情况触发 Skill Evolution：

1. 人工验收发现自动流程已 PASS、但正文仍存在明确问题；
2. 用户指出一个可重复出现的质量问题；
3. 外部 Reader / Editor 发现现有 Gate 漏检；
4. 同类问题在两个以上章节重复出现；
5. 新模型 / Prompt / Pipeline 调整导致旧问题回归；
6. 原规则误杀正常文本，导致人物声音、节奏或题材特征被过度修平。

不触发：
- 单纯个人审美偏好；
- 只针对某个角色、某句话、某本书且无法泛化的问题；
- 作者明确选择的风格差异，且不破坏理解、人物或类型承诺。

---

# 2. 第一原则：先归因，不先改正文

发现漏检后，第一步不是直接修正文。

必须先记录：

SKILL_EVOLUTION_CASE_V1

【Case ID】
【来源】人工 / 用户 / Reader / Editor / 线上事故 / 回归失败
【原文】
【现有流程为什么放过】
【真正问题】
【影响层级】Writer / Reader / Editor / Reviewer / Pipeline
【是否可泛化】YES / NO
【相邻正常样本】
【候选标签】
【建议处置】

只有完成归因，才能进入 Skill 修改。

目的：
避免“看到一句不喜欢 → 加一条硬规则”，最终把 Skill 堆成互相冲突的偏好清单。

---

# 3. 泛化门槛

一个问题只有满足以下至少 2 项，才能升级成正式规则：

1. 能描述成“模式”，而不是只描述某一句；
2. 可构造至少 2 个不同场景下的失败样本；
3. 能写出至少 1 个“看起来相似但应该 PASS”的反例；
4. 能明确说明误报边界；
5. 能说明该问题应该由哪一层最早拦截；
6. 该问题对理解、人物、关系、类型、节奏或长期一致性有可解释影响。

若不能泛化：
- 记录为作品级 Note / Preference；
- 不升级全局 Skill。

---

# 4. 规则设计格式

每条新规则必须包含：

【Rule ID】
【名称】
【定义】
【为什么重要】
【FAIL 样本】
【PASS 样本】
【误报边界】
【最早责任层】
【阻断级别】
【最小修改边界】
【回归要求】

禁止只写：
- “对白更自然”
- “人物更鲜活”
- “语言更高级”
- “不要 AI 味”

这类不可执行描述不得进入正式 Skill。

---

# 5. 最早责任层原则

问题应尽量放到最早能够可靠处理它的层，而不是全部堆给最后 Reviewer。

推荐顺序：

Writer self-check
→ Specialized Reader
→ Reviewer
→ Editor / Revision
→ Approval

示例：

- 语义搭配错误：Writer + Reader D
- 对话人物可互换：Writer + Reader B
- 角色突然老实：Character / Dialogue Reader + Character Reviewer
- 长篇发动机重复：Genre / Long-form Gate
- 世界规则冲突：World Reviewer
- 过度编辑：Editor Skill + After Reader

若 Reader 能稳定抓住，不再保留额外人工 Reader 工位。

---

# 6. Failure Corpus

每个确认的新型失败必须分配稳定编号。

要求：
- 不覆盖旧编号；
- 保留最初真实失败样本；
- 写明旧机制为什么漏检；
- 写明新规则如何捕获；
- 记录误报边界。

Failure Corpus 是 Skill 的“事故历史”，不是漂亮示例库。

---

# 7. 正例 / 反例双向回归

任何新规则必须至少包含：

- FAIL 样本：规则必须抓住；
- PASS 样本：规则不得误杀。

例如“对白有性格”不能导致：
- 所有人都强行加口头禅；
- 每句都反问；
- 每场都必须争吵；
- 话少角色被迫说很多；
- 方言 / 口语被编辑成标准书面语。

只有 FAIL recall 和 PASS precision 同时满足，规则才能进入 STABLE。

---

# 8. Skill 版本升级

全局 Skill 修改必须升级整数版本。

规则：
- 新增可执行检查：版本 +1；
- 修改阻断条件：版本 +1；
- 修改误报边界：版本 +1；
- 仅修错字 / 文档排版：可不升级。

每次升级必须记录：
- From version
- To version
- Trigger Case
- 新增规则
- 回归集
- 已知风险
- Rollback 条件

---

# 9. 升级状态

新能力采用四级状态：

CANDIDATE
- 刚从人工问题抽象出来；
- 尚未证明 Reader / Writer 稳定识别。

CALIBRATING
- 已写规则和回归样本；
- 正在用旧失败 + 正常样本验证。

STABLE
- 原失败可稳定抓取；
- 正常样本无明显误杀；
- 已接入正式 Pipeline。

TRANSFERABLE
- 已在至少 2 种不同场景 / 作品 / 人物关系中验证。

只有 STABLE 以上能力可以作为 blocking Gate。

---

# 10. 正式升级流程

## Step 1 — Capture
记录真实漏检，不修改原始失败证据。

## Step 2 — Diagnose
说明：
- 为什么 Writer 没挡住；
- 为什么 Reader 没发现；
- 为什么 Reviewer / Editor 放行。

## Step 3 — Generalize
从“这一句错了”抽象为可重复模式。

## Step 4 — Boundary
给出：
- FAIL 反例；
- PASS 正例；
- 误报边界。

## Step 5 — Assign Owner
确定 Writer / Reader / Editor / Reviewer 中谁最早负责。

## Step 6 — Version
修改 Skill，并提升版本。

## Step 7 — Regression
新增测试 / regression corpus。

## Step 8 — Replay
用升级后的 Skill 重新审核最初失败正文。

要求：
旧失败必须 FAIL。

## Step 9 — Repair
只有自动 Gate 已能识别后，才允许 Writer / Revision 修改正文。

## Step 10 — Recheck
修改后重新运行同一 Gate。

## Step 11 — Promote
满足条件后：
CANDIDATE → CALIBRATING → STABLE。

## Step 12 — Remove Human Crutch
如果之前临时增加了人工检查步骤，Skill STABLE 后必须移除永久人工工位。

---

# 11. 升级失败与回滚

出现以下任一情况，应回滚或降级新规则：

1. 大量正常人物口语被误判；
2. Writer 为通过 Gate 开始机械套模板；
3. Reader 输出大量低价值“可能有问题”；
4. 新规则和既有规则发生冲突；
5. 同一类文本在不同轮次判定剧烈波动；
6. 通过率下降但真实质量没有提高；
7. 为规避规则产生新的 AI 痕迹。

回滚不删除事故记录。
Failure Corpus 与 Case 保留。

---

# 12. 冲突优先级

规则冲突时：

事实 / 因果 / 世界规则
>
人物动机 / 信息边界
>
读者理解
>
对话真实性 / 自然度
>
节奏 / 审美
>
个人风格偏好

例如：
为了让对白更有性格，不能改变人物已知事实；
为了让句子更自然，不能修改关键线索来源。

---

# 13. 对本次两个真实 Case 的应用

## Case SE-001｜“头疼 vs 屁股”
来源：人工首读。

旧机制：
Reader 能理解；Editor 误认成人物毛刺。

泛化：
“能理解但自然中文第一眼发怪”。

升级结果：
- Writer Natural First-Read
- Reader D
- F016
- Naturalness regression corpus
- 独立 Final Human 工位最终移除

状态：
STABLE

## Case SE-002｜陈安 / 赵六对白过于简单
来源：人工首读。

问题：
对白信息正确、人物动机也基本正确，但大量句子只承担“问 / 答 / 推剧情”，两个人说话的可交换性过高。

泛化：
“功能性对白通过了动机检查，却没有声音、关系和策略差异”。

升级：
- Writer Dialogue Authenticity Gate
- Reader B B01—B12
- Dialogue regression corpus
- DIALOGUE_VOICE_GAP / DIALOGUE_FUNCTIONAL_GAP / RELATIONSHIP_VOICE_GAP

状态：
CALIBRATING

## Case SE-003｜人物只有嘴，没有身体
来源：人工首读。

问题：
对白即使有不同人物声音，人物一开口后身体、表情、手上任务、伤势和空间位置仍可能消失；机械补“皱眉/看了看/沉默”也不能解决。

泛化：
“对话场景缺少带性格的非语言行为与并行任务，人物退化成聊天框”。

升级：
- Writer Embodied Dialogue Gate
- Reader B B13—B18
- EMBODIED_DIALOGUE_GAP / GENERIC_ACTION_GAP
- Embodied Dialogue Regression Corpus
- Character Designer 增加语言指纹 + 非语言指纹
- Scene Director 增加对话身体线

误报边界：
- 不要求每句对白有动作；
- 紧急行动、命令、快速确认可高比例纯对白；
- 动作少的克制人物可以 PASS，只要动作与空间仍有选择性。

状态：
CALIBRATING

## Case SE-004｜更深层的机器人式互动
来源：人工继续验收。

问题：
即使人物已经有不同台词、动作和表情，仍可能存在更深层机器人味：
- 过度理性，人物准确解释自己；
- 不维护面子和自我形象；
- 熟人没有关系记忆；
- 对话话轮过度整齐；
- 情绪没有余波；
- 不同人物感知同质。

泛化：
“人物互动缺少自我包装、共同历史、话轮不对称、情绪残留和感知差异”。

升级：
- Writer Human Interaction Complexity Gate；
- Reader B B19—B26；
- F019—F024；
- Human Interaction Regression Corpus；
- Character Designer 增加自我形象 / 关系记忆 / 感知指纹；
- Scene Director 增加关系记忆触发、面子、话轮与余波、感知差异。

误报边界：
- 不要求人人含蓄；
- 不要求每场翻旧账；
- 不要求每句话都有情绪；
- 紧急行动可以高度对称；
- 关键危险可以被所有人同时注意。

状态：
CALIBRATING

## Case SE-005｜局部重写功能漂移与接口裂缝
来源：人工整章首读。

真实事故：
重写第一章陈安 × 赵六开场对白后：
1. 对话人物性显著增强；
2. 但“现代人穿越到大梁”的开篇确认被删除，后文仍直接使用“原主”；
3. 房内新增“运粮路线”问答后，房外旧段仍再次从零询问同一路线。

根因：
旧 LOCAL_REWRITE 只冻结事实和修改边界，没有冻结“场景必须完成的叙事功能”；同时只审修改块内部，没有强制做前后 Seam Check。

泛化：
- SCENE_FUNCTION_DRIFT：局部改写后原段必须完成的认知/身份/关系/规则/决定功能丢失；
- LOCAL_REWRITE_SEAM_GAP：修改块与前后文拼接后出现重复问答、重复介绍或状态重置。

升级：
- Writer v10 Local Rewrite Integrity；
- Refinement v8 Narrative Function Contract + Seam Contract；
- Reader Skill v5 明确 Blind Reader 与 Revision Integrity 的职责边界；
- Revision Integrity Reviewer 正式接入 Pipeline；
- F025 / F026；
- Revision Integrity Regression Corpus。

误报边界：
- 同一事实若第二次出现承担新证据、关系压力或验证功能，不算重复；
- 写法可以完全改变，只要 Narrative Function Contract 仍完整；
- Blind Reader 不负责比较 BEFORE / AFTER。

状态：
CALIBRATING

---

## Case SE-006｜作者施工痕迹与线索人工感
来源：普通读者多轮复读。

真实问题：
在前述自然度、人物、局部重写完整性均改善后，仍可出现更高一层的“作者手”：
- 动作/对白已经表达，旁白再解释；
- 开篇像在勾设定卡；
- 人物关系变化已经完成，对话仍循环；
- 人物声音/动作指纹被过度展示；
- 身体状态被持续播报；
- 调查形成线索阶梯或小空间线索过密；
- 记忆按剧情缺口精准补信息；
- 系统通过奖励时机认证判断；
- 多个“正好”形成巧合集群；
- 嫌疑人物动作连续配合证据展示。

泛化：
“正文逻辑可以完全成立，但读者仍能感到作者在控制理解、展示人物卡、发放线索或认证答案”。

升级：
- Writer v11 Author-Hand & Story-Flow Gate；
- Reader Skill v6 Reader C C01—C12；
- Refinement v9 Author-Hand Gate；
- blind-artifice-reader 正式接入每轮 Review Round；
- F027—F038；
- Author Artifice & Clue Flow Regression Corpus。

阻断边界：
- 单个轻微痕迹可 WATCH；
- 同一场景两类以上明确作者痕迹，或调查整体像教程关，blocking；
- 不允许通过机械塞假线索、废话、随机错误来“制造真实感”。

当前 Chapter 1 验证：
- CLUE_DENSITY_GAP：经蓝线/记忆/脚印空间与节拍重排后关闭；
- SYSTEM_CONFIRMATION_LEAK：经系统触发点前移到真实寻迹动作后关闭；
- COINCIDENCE_CLUSTER_GAP：经刘旺提前作为正常背景人物出现后明显降低；
- EVIDENCE_DISPLAY_STAGING：仍为当前章尾剩余重点问题；
- INTERPRETATION_ECHO_GAP / PREMISE_CHECKLIST_GAP / DIALOGUE_LOOP_GAP / VOICE_OVERPERFORMANCE_GAP / FINGERPRINT_OVERUSE_GAP / BODY_STATE_TICKER_GAP：仍可在第一章前半段找到样本，应由新 Reader C 自动报告。

状态：
CALIBRATING

---

# 14. Definition of Done

一次 Skill Evolution 只有同时满足以下条件才算完成：

- [ ] 真实 Case 被保存；
- [ ] 漏检根因被解释；
- [ ] 规则完成泛化；
- [ ] FAIL 样本存在；
- [ ] PASS 样本存在；
- [ ] 误报边界存在；
- [ ] Failure Corpus 更新；
- [ ] Skill 版本提升；
- [ ] 正式 Pipeline 接入；
- [ ] 回归约束存在；
- [ ] 原失败可被新 Gate 捕获；
- [ ] 正常表达未被误杀；
- [ ] 临时人工工位已移除或明确说明为何保留。

最后原则：

> 我们不是让模型“记住这句话不能这么写”，
> 而是让系统学会“为什么这一类写法不成立”。
