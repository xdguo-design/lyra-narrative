# Reader Calibration Profile

READER_CALIBRATION_PROFILE_V1

## 覆盖场景
1. 第五章综合家庭场景
2. Transfer A 家庭/经济
3. Transfer B 上级/工作

## Reader A — 首读理解
STABLE
- 三类场景能识别动作、因果与未知边界。
- Round 3 成功捕获 RC001 “那扇门”指代竞争。
- 修复后 0 critical semantic / causal gap。

## Reader B — 人物 / 关系
STABLE
- 能区分陈安的保护/控制、小满的参与权、赵六的成本意识、周虎的任务边界。
- 能识别“表面执行但关系变远”“实际松手但未正式同意”等非口头关系变化。
- 0 critical motivation / relationship gap after recheck。

## Reader C — 阅读动力
STABLE
- 家庭场景的期待落在钱/关系；
- 经济场景的期待落在小满实际承担；
- 工作场景的期待落在身份收益 + 家庭后果；
- 未被案件悬念统一吞掉。
- 能区分 curiosity 与 confusion。

## 失败样本
### RC001
“今晚那扇门不用等了。”
类型：AMBIGUOUS_GAP
原因：最近实体“县衙后门”与作者意图“城南家门”竞争。
处置：LOCAL_REWRITE
复审：PASS

## Gate 2 通过标准
- 3 个 Reader 独立视角均完成：PASS
- 代表场景 >= 3：PASS
- critical semantic gap = 0：PASS
- critical causal gap = 0：PASS
- critical motivation gap = 0：PASS
- critical relationship gap = 0：PASS
- curiosity != confusion：PASS
- 至少捕获并修复一个真实 Reader failure：PASS

## Gate 2
PASS / STABLE
