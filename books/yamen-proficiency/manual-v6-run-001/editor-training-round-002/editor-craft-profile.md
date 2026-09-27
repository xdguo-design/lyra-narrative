# Editor Craft Profile

EDITOR_CRAFT_PROFILE_V1

【Selection Judgment】STABLE
- 在上下级/工作与家庭/经济两种场景中，能先判断哪些句子应该 NO_TOUCH / PRESERVE，而不是默认“都要改”。
- 能识别解释性判断与真正的人物动作差异。
- 已证明“删得少”也可以是正确编辑结果。

【Voice Preservation】STABLE
- 能保住赵六的绕与怕吃亏、周虎的少解释、陈安的现实计算、小满的短硬、柳氏的生活事实。
- Round 1 曾把赵六修成普通下属，Coach 后已纠正。
- Round 2 未复发。

【Anti-Overediting】STABLE
- 能保留“娘是娘，你是你”这类不漂亮但属于人物缺点的句子。
- 不再把所有表达修成完整、理性、克制的标准中文。

【Reader Improvement】STABLE
- 两轮 After 均未新增 critical Reader Gap。
- Round 2 在不损声音的前提下减少两处解释。
- Reader 理解与阅读动力不下降。

【Fact/Intent Preservation】STABLE
- 两轮均未改变事实、人物动机、信息来源、事件顺序。
- 已记录 EF002：Editor 不得替周虎新增“总得有人守”式解释。

【当前失败模式】
1. 更顺 = 更好：容易把角色毛刺修平。
2. 更快 = 更好：容易把具体代价压成抽象概括。
3. 管理者对白容易被补足解释，改变权力关系。
4. “清楚”容易被误用为把潜台词说完整。

【失败样本】
- EF001：赵六绕话被修成“我昨晚没休息好，恐怕守不了夜”。
- EF002：给周虎新增“总得有人守”。
- EF003：把小满/家庭具体代价压成“家里继续等他”。
- EF004：试图把“娘是娘，你是你”修成更讲理的完整解释。

【通过标准】
- 至少两类场景 Reader Gate 不下降：已通过。
- 至少三名人物声音编辑前后可辨认：已通过。
- 0 fact-drift：已通过。
- 0 critical Reader Gap：已通过。
- 至少一次主动 NO_TOUCH 保住人物毛刺：已通过。

【等级结论】
STABLE

【尚未达到 TRANSFERABLE 的原因】
尚未完成第三类“调查/对峙”或“动作/危险”场景编辑迁移。正式重写前 Gate 要求 STABLE，当前已满足；若希望 Editor 达到 TRANSFERABLE，再补第三类迁移。

【正式编辑激活规则】
1. 先判 NO_TOUCH，再判怎么改。
2. 人物口语比“准确表达”优先。
3. 不替强势人物补解释，不替回避人物补诚实。
4. 只删读者已经能得到的解释，不删因果支点。
5. After Reader 不能比 Before 更困惑。
6. 一旦编辑后人物更像同一个人，回退。
