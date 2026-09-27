# Reader D Calibration Addendum

READER_NATURAL_FIRST_READ_CALIBRATION_V1

## 目标
验证 Reader D 能识别“语义能猜懂，但第一眼中文表达不自然 / 气质错误”的问题，而不是重复 Reader A 的语义理解检查。

## Sample 1｜第五章综合家庭场景
结果：PASS

检查：
- 对话两端语义同层；
- 家庭冲突没有靠作者段子制造笑点；
- 铜钱、药、米等词语搭配自然；
- 开场没有错误类型诱导；
- CHARACTER_ROUGHNESS 与作者别扭句可区分。

## Sample 2｜Transfer A 家庭 / 经济
结果：PASS

检查：
- “跟你欠债差不多久”“急才有钱”“我十三，不是三岁”虽有口语毛刺，但都明确属于陈小满声音；
- 不需要读者补词才能成立；
- 未发现 NATURALNESS_GAP / TONE_GAP。

## Sample 3｜Rewrite Chapter 1 Opening
原句：
“陈安醒过来的时候，先感觉到的不是头疼，是屁股。”

结果：FAIL

标签：
- NATURALNESS_GAP
- TONE_GAP

原因：
- “头疼”是症状/感觉；
- “屁股”是身体部位；
- 需自动补“屁股疼”才形成平行结构；
- 全书第一句先制造段子感，误导作品气质。

处置：
LOCAL_REWRITE

## Reader D Calibration Result
STABLE

通过依据：
- 能保留真正的人物口语毛刺；
- 能识别“能懂但怪”的作者叙述；
- 能识别语义层级错位；
- 能识别开篇类型第一印象偏移；
- 不把“读者能脑补”当 PASS。
