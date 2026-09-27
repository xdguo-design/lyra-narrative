# Reader Three-Perspective Calibration Protocol v1

## 目的
Reader Gate 不再由一个 Reader 同时承担所有判断。三个 Reader 彼此独立，只看正文，不看人物卡、Scene Card、作者意图、Coach 反馈和其他 Reader 的结论。

## Reader A — 首读理解
只回答：
1. 发生了什么？
2. 人物当前在做什么？
3. 哪些因果第一次读就能连起来？
4. 哪些地方需要回读？
5. 每个未知项标记：
   - INTENTIONAL_UNKNOWN
   - READER_GAP
   - AMBIGUOUS_GAP

### 通过标准
- critical semantic / causal gap = 0
- 重要动作对象明确
- 未知项可命名
- 不依赖后文或作者说明修复当前语义

## Reader B — 人物 / 关系
只回答：
1. 每个人此刻想要什么？
2. 谁在阻碍谁？
3. 谁拥有筹码？
4. 谁让步了，为什么？
5. 场景结束后关系发生了什么变化？
6. 哪个关系变化正文没落地？

### 通过标准
- 主人物目标可区分
- 至少一个人物不为剧情自动合作
- 关系变化能由动作/对白指出，不靠主题说明
- critical motivation / relationship gap = 0

## Reader C — 阅读动力
只回答：
1. 这一场最想继续看的问题是什么？
2. 好奇来自未知，还是来自没看懂？
3. 结尾有没有制造具体下一步期待？
4. 哪些信息抢走注意力但没有回报？
5. 是否想继续读下一场？为什么？

### 通过标准
- 至少形成一个具体下一步期待
- curiosity != confusion
- 主要记忆点与场景目标一致
- 非调查场景不能被案件悬念吞掉
- 不靠 AI 总结句或硬钩子制造继续阅读

## Reader D — 自然首读 / 气质
只回答：
1. 有没有“意思能懂，但第一眼就是怪”的句子？
2. 对比、转折、排比两端是否处于同一语义层级？
3. 有没有必须靠自动补词才能成立的省略？
4. 幽默来自人物/处境，还是作者在抖机灵？
5. 开篇前三段让人误判成了什么类型？
6. 有没有一句话语法勉强成立，但母语直觉明显不自然？

### 强制标签
- NATURALNESS_GAP：能猜懂，但中文表达本身别扭、搭配失衡、层级错位或需要补词。
- TONE_GAP：单句/段落把作品气质带偏，尤其开篇误导类型。
- AUTHOR_JOKE_GAP：笑点主要来自作者抖机灵，而非人物与处境。
- CHARACTER_ROUGHNESS：不标准但明确属于人物声音，可保留。

### 通过标准
- 开篇前三段 NATURALNESS_GAP = 0
- 开篇前三段 TONE_GAP = 0
- 关键转折与章尾 NATURALNESS_GAP = 0
- 对比结构两端语义同层
- 不以“读者能脑补”作为通过理由
- 不把作者别扭句误判为“人物毛刺”

### 正式失败样本
“陈安醒过来的时候，先感觉到的不是头疼，是屁股。”

为什么失败：
- “头疼”是感觉/症状，“屁股”是身体部位，不在同一语义层级；
- 读者必须自动补成“屁股疼”才勉强平行；
- 作为全书第一句，段子感先于底层生存感，形成 TONE_GAP。

判定：
NATURALNESS_GAP + TONE_GAP / LOCAL_REWRITE

## 总 Gate
四个 Reader 独立完成后才汇总。

PASS：
- A/B/C/D 全部通过；
- 0 critical semantic / causal / motivation / relationship gap；
- 开篇/关键句 0 NATURALNESS_GAP / TONE_GAP；
- Momentum Reader 的期待与本场类型承诺一致。

LOCAL_REWRITE：
- 单句/相邻句造成局部语义、关系或注意力误导。

REWRITE_BLOCK：
- 三个 Reader 对“这场在干什么”得出不同核心解释；
- 人物目标/关系变化只存在于作者材料；
- 阅读动力主要来自困惑；
- 场景核心类型被另一条线完全吞掉。
