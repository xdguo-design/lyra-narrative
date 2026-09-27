# Chapter 2 Character Behavior Review

## INITIAL

### R012
【严重性】blocking
【处置级别】REWRITE_BLOCK
【问题类型】character / dialogue pressure
【问题定位】第二章开场盘问刘旺
【原片段】
“昨晚你推过这辆车？”
“我每天都推。”
“昨晚呢？”
“没有。”

【问题说明】
刘旺人物卡为“谨慎、怕事”，且陈安只是同级白役。原对白让陈安连续直问、刘旺连续直答，人物关系更像审讯者和嫌疑人；刘旺没有先装糊涂、把特殊行为说成日常、反问凭据或控制承认范围，违反人物卡。

【为什么必须整段重写】
问题不只是一两句措辞，而是整场信息释放顺序错误。刘旺后续又连续交代“孙成、五文、侧门、粮袋消失”，等于作者为了推进剧情让人物自动配合。

【重写目标】
- 陈安先问车和日常用途，不直接逼问昨夜。
- 刘旺先用“天天都推、谁都能用”稀释特殊性。
- 陈安只亮部分证据，不一次摊牌。
- 周虎到场后才有真正的身份压力。
- 鞋印现场复核后，刘旺只承认“推过一趟”。
- 周虎继续追责后，刘旺才承认孙成。
- 五文钱最后被单独追问才承认。

## R013
【严重性】blocking
【处置级别】DELETE
【问题类型】meta narration
【问题定位】柴房问答
【片段】“这句比前面那一串老实回答正常多了。”
【问题说明】这是作者评论修订效果，不属于小说叙事。
【处置】直接删除。

# RECHECK

## R012
- 刘旺是否先否认/日常化：PASS
- 是否在同级白役面前主动完整交代：NO
- 鞋印复核前是否承认推粮：NO
- 鞋印复核后是否只承认最小事实：PASS
- 孙成是否在周虎继续施压后才出现：PASS
- 五文钱是否单独追问后才承认：PASS
- 陈安是否连续审讯式逼问：NO
- 周虎是否承担身份压力与事实复核：PASS
- 人物卡与行为一致性：PASS
【复审结果】PASS

## R013
- 元叙事句是否已删除：PASS
【复审结果】PASS

## Regression checks
- Writer prompt contains character-card pressure/lying/information-threshold constraints: PASS
- Character Reviewer explicitly checks “谨慎/怕事的人是否过早坦白”: PASS
- Regression test added for character-card behavior constraints: PASS

Remaining blocking: 0
