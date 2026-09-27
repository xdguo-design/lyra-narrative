# Pre-Rewrite Improvement Report — 2026-09-27

作品：《穿成县衙白役，我把熟练度肝满了》

本报告整理 Reader 三视角、三章 mini-arc、Genre Promise Matrix 三项小说改进任务的结果、失败样本、通过标准与提交记录。

## 1. Reader Three-Perspective Calibration

### 训练对象
- 第五章综合家庭场景
- Transfer A 家庭 / 经济
- Transfer B 上级 / 工作

### Reader A — 首读理解
通过标准：
- critical semantic / causal gap = 0
- 重要动作对象明确
- 未知项可以命名
- 不依赖后文修复当下语义

结果：PASS / STABLE

### Reader B — 人物 / 关系
通过标准：
- 主要人物目标可区分
- 至少一人不自动合作
- 关系变化可从动作 / 对白指出
- critical motivation / relationship gap = 0

结果：PASS / STABLE

### Reader C — 阅读动力
通过标准：
- 有具体下一步期待
- curiosity != confusion
- 记忆点与本场目标一致
- 非调查场景不被案件吞掉
- 不靠总结句硬钩读者

结果：PASS / STABLE

### 真实失败 RC001
原句：
“等赵六到了城南，小满大概已经知道今晚那扇门不用等了。”

问题：
县衙后门与城南家门形成同等合理指向。

判定：
AMBIGUOUS_GAP / LOCAL_REWRITE

修复：
“等赵六到了城南，小满大概也知道，今晚不用给他留门了。”

复审：
PASS

### Reader 提交记录
- Protocol: f9dfbcd7bfa189400a103858861143210ea334c7
- Round 1: b4b11811c19ae767dd9485e36dba0ac38eb6f7e1
- Round 2: 04a7432f84e6843bf908ab8bae4eb2599b44d5b7
- Round 3 failure: d248ec0fe41d71c7491cba01b6ff3674331a27f4
- Round 3 rewrite: 041068bf3f771a2202fdd361cd4ef72ccc5b7ef4
- Round 3 recheck: 6265cf1f069a0807ff2fb608db1954198366b9b9
- Reader Profile: ee4e06159e90976149ac221f8ccb886cdef0c949

## 2. Three-Chapter Mini-Arc

### 模拟章节
1. 《三天》——家庭 / 债务谈判
2. 《六文工钱》——县衙工作 / 身份
3. 《别往人多的地方追》——调查 / 行动

均为训练稿，不进入正史。

### 通过标准
- 三章主要发动机不同
- 开场机制不同
- 不重复同一证据发现结构
- 不重复同一种章尾
- 家庭 / 钱 / 身份 / 熟练度持续影响选择
- 主角缺点与能力都产生代价
- 系统只在真实练习 + 结果后出现

### 失败样本
LONG001 — WATCH
赵六“怕亏 / 算钱”存在固定笑点风险。
处置：正式重写中禁止每次赵六出场都靠谈钱制造幽默。

LONG002 — LOCAL_REWRITE
Ch2 / Ch3 连续以“还差九文”做章尾。
处置：
保留 Ch2 数字目标；
Ch3 改为：
“他把衣里的六枚铜钱按回去，跟着周虎往县衙走。”

复审：PASS

### Mini-Arc 结果
PASS / STABLE

### 提交记录
- Ch1: a3e705f966e60d54a6dc44333b0bff4803b527a6
- Ch2: 848b9a15408b7a54784a9f4c819e91af0914813a
- Ch3 initial: fe6f1d3445f4f1e8f56be292d49e2a3126717c8c
- Review: b64f1fff7237f45588d403e926148e6825d1e857
- Ch3 rewrite: 48f2b8a0487f2507db0cbcaeaf0e243fe742b6eb
- Recheck: 683a4b41959391a68de126ed64868459fa69dd4c

## 3. Genre Promise Matrix

冻结六类承诺：
1. 底层县衙生存
2. 钱 / 债 / 家庭
3. 熟练度真实成长
4. 身份 / 职业晋升
5. 县城生活与社会层级
6. 案件与危险

### 硬通过标准
每 5—8 章：
至少 3 个非调查 Promise 必须真实改变人物选择或结果。

### Anti-Drift
- GP001 案件吞书
- GP002 家庭装饰化
- GP003 贫穷口号化
- GP004 身份虚化
- GP005 系统打卡
- GP006 职业成长跳级
- GP007 县城工具化
- GP008 爽点无成本

### 结果
PASS / FROZEN v1

### 提交记录
- Genre Promise Matrix: c865ff09f52161144947dccae2fa868d1ba8c89d

## 4. Writer Profile Upgrade

新增动作/长篇证据后：
- Scene Direction：TRANSFERABLE
- Character Behavior：TRANSFERABLE
- Language Rhythm：TRANSFERABLE
- Reader Semantic Boundary：STABLE
- Long-Form Variation：STABLE

提交：
5c5fce98fde161a408f4a1c8e6dbc20a39830bbd

## 5. Rewrite Freeze Pack

小说训练门槛全部通过后，已冻结：
- Architecture
- Proficiency Rules
- Characters
- Writer v2
- Editor
- Reader Calibration
- Failure Corpus
- Genre Promise Matrix
- Long-Form Training

提交：
d02524cb99a58d86a05330212c46d4350df1fc31

## 6. Readiness

Pre-Rewrite Status 已更新为：
小说改进 / 训练门槛 ALL PASS。

提交：
46472d6ae76dc11c56c54b52e8d4e1e3a982f70c

注意：
“小说训练已就绪”与“线上平台已部署并通过真实模型验收”是两个不同门槛。
正式正文可以从训练角度开始重写；平台产品发布仍需线上部署验收。
