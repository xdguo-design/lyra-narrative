from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from app.db import connect, init_db
from app.services.book_pipeline import _create_task
from app.services.workflow_service import _parse_review_output, _run_step, _task_context

OUTPUT_DIR = Path("artifacts/gray-street-sections-06-10-fast")
CONTENT_ROOT = Path(os.getenv("GRAY_STREET_CONTENT_ROOT", "content-repo"))
LOCKED_SOURCE = CONTENT_ROOT / "novels/gray-street/versions/sections-01-05-platform-locked.md"
FALLBACK_SOURCE = CONTENT_ROOT / "novels/gray-street/versions/sections-01-05-reader-input-v1.md"
BRIEF_PATH = CONTENT_ROOT / "novels/gray-street/plans/sections-06-10-brief.md"
CANON_PATH = CONTENT_ROOT / "novels/gray-street/bible/project-canon.md"

REVIEW_FORMAT = """NARRATIVEOS_REVIEW_V3
没有问题只输出 NO_ISSUE。
每个问题必须包含：
严重性：High / Medium / Low
处置级别：REWRITE_BLOCK / LOCAL_REWRITE / POLISH / PASS
问题定位：
逐字片段：
问题说明：
修改边界：
必须保留事实：
执行目标：
建议动作：
复审结果=PENDING
多个问题用单独一行 --- 分隔。"""

FAST_OUTLINE = """## 第六节　七号箱
开场只在格兰特事务所：第一笔归还后的第二天早晨，事务所内部高级文员露西·克劳要求埃文补写银牌核验/交接说明。银牌已经在米拉手里，争议是手续未闭合，不是银牌仍在埃文手里，也不是米拉突然成了克莱继承人或受益人。
埃文为补说明重查克莱遗产袋，在旧港务票据夹层找到一张被正式清单漏掉的“第七码头资产处保管附页”：物件名称只写“七号封存箱”，旧记号栏有SV-7，状态是“待移交”，没有最终签收。它证明七号箱是实体保管物，不是七码头第七扇门；但不解释SV代表什么。
汤普森以警官身份来事务所找埃文，告知：鲍勃·费恩今晨被发现死在十三号仓后办公室附近，死亡必定发生在埃文昨天下午离开之后；警方暂未给最终死因。因为仓库工人能证明埃文昨天去过，他需要去警署补一份证人陈述。汤普森不知道怀表，不负责事务所账。
埃文离开事务所去警署前，红发女人第一次主动近距离接触。她戴黑手套，把一张从旧港务回函上撕下的存根塞回埃文手里——她此前拿走了原回函，因为不想让“七号箱”按普通遗产物件被直接封存。她只说：“钥匙已经离开十三号仓，但箱子从来不在那里。”她不解释身份。
章末：存根的旧保管编号让埃文确认，七号箱六年前由第七码头资产处转入“港务旧档临时保管”，签收栏只有一个姓：维尔。现实上的银牌手续、警方证人身份和七号箱未结资产三条线同时压住他。

## 第七节　第七码头资产处
埃文先去警署完成证人陈述，再以遗产清算员的合法身份申请查旧港务档案。汤普森在问询中只追问十三号仓、银牌和费恩最后接触情况；埃文承认自己将刻着MIRA ALVA的银牌交给米拉，但暂不提怀表会出现文字。
港务档案室里，埃文凭克莱遗产清算授权调到六年前的转存卡和旧雇员名册。转存卡显示：七号封存箱由第七码头资产处内部转出，签收人为“E. WEIR”；雇员名册把这个缩写落地为“艾玛·维尔”，女性，曾任资产处保管文员/登记员。此处只确认身份，不提前说她已死。
档案员能确认的是纸面事实：七号箱在转存后没有合法销毁记录，也没有回到港务总库。埃文因此要查艾玛·维尔后来的去向。
红发女人在档案馆外与埃文短促交锋。她试图拿走埃文抄下的转存编号，被埃文拦住。她明确表达自己的利益：她手里的旧钥匙只能打开七号箱所在保管处的一道机械锁，不能证明箱子归她；埃文的清算身份能让旧记录重新进入合法流程，她需要他，但不信任他。
章末：埃文记下艾玛·维尔最后登记住址，准备通过公开死亡/住址档案找她。

## 第八节　已死的维尔
埃文从市政死亡登记、旧报纸讣告和港务离职卡三处交叉确认：艾玛·维尔三年前已经死亡。死因不重要，不虚构阴谋式尸检；三份公开记录时间一致。
真正矛盾来自港务旧档的一张最近调用附记：克莱死亡前九天，一份“七号封存箱临时查验”手续引用了艾玛·维尔留下的旧授权编号。这里不是电子系统、不是门禁日志，而是一张纸质申请的授权栏仍写着她的编号。申请最终没有完成正式出库，所以只能证明有人仍在用死者旧授权，不能直接证明伪造者是谁，更不能宣布鬼魂。
埃文从申请的去向栏看到“旧盐场公共寄存区”，这与十三号仓不是同一个保管点；七码头资产处撤销后，一部分无人接收的封存物曾被临时放在那里。
埃文忍住没有立刻去找米拉。他先给汤普森留下一份合法的资料副本，只说明“有人在使用死者授权号”；汤普森因此同意把这条线并入费恩死亡的背景调查，但不把警方内部材料交给埃文。
章末：红发女人通过电话/当面要求埃文明天下午到旧盐场公共寄存区，带清算员证件；她会带那把九天前从十三号仓取出的钥匙。她没有说要打开箱子，只说“先确认它还在不在”。

## 第九节　旧盐场交易
地点是旧盐场公共寄存区的旧计量房和地下干燥库，不是十三号仓。这里仍靠纸质登记、机械锁和人工看守。
红发女人按约带来那把封存钥匙。她终于给出一项有限、可验证的解释：十四年前克莱签的是一份长期“代领钥匙授权”，她九天前只是依法把钥匙从十三号仓领走；那份授权允许取钥匙，不允许取七号箱，所以她一直需要一个能合法查验克莱遗产的人。不要解释她与克莱全部关系。
米拉主动出现，因为埃文此前交给她的SV-7/05银牌在旧资产处规则里可以证明她是曾经的登记相关人。她承认“05”是她当年的编号，但拒绝解释SV完整含义；她也承认自己早就知道艾玛·维尔三年前死亡，却故意没告诉埃文。埃文因此与她发生真正的信任冲突。
三人向看守提出查验时发现：七号箱仍在登记册上，但当天上午有人拿一张引用艾玛旧授权号的纸质调取单来要求转移，因缺少现持有人签字而被看守扣下。也就是说，有现实中的另一方正在抢先处理箱子。
冲突升级为现实抢夺：有人来夺那张调取单/登记簿，红发女人阻拦，埃文护住纸面证据；不使用怀表救场。汤普森因埃文事先留下地址/资料而带警员赶到，依法控制现场。
章末：警方和看守共同确认七号箱就在地下干燥库，尚未被转走。汤普森允许在看守和警方见证下做一次“不开封外观核验”，但是否开箱必须先处理钥匙与登记责任。红发女人把钥匙正式交到汤普森手里备案，避免第十节凭空出现。

## 第十节　第二笔
开场承接第九节同一现场。当晚/稍后，在看守、汤普森、埃文、米拉在场的情况下，警方把钥匙作为临时证物登记后，用它开启地下干燥库的外门；七号箱本体是一只旧黑铁封存箱，外部编号SV-7，封条已老化但未被近期破坏。
因箱子属于克莱遗产未结资产且牵涉费恩死亡背景，汤普森允许埃文只做清单核验，不允许任何人私自带走。米拉确认箱体侧面曾经有五个身份牌槽位，其中05本应属于她，现在是空的。
开箱后不要出现隐藏继承人、信托、律师秘密组织或新超自然规则。箱内主要是旧资产处的纸质移交账册、几只油纸小包和一块银质身份牌。账册证明当年有五个编号对象，05一栏已在当天被手写标成“归还”；另一只油纸包标04，里面的银牌刻着“SV-7 / 04”和“EMMA WEIR”。
这给“第二笔”一个现实对象：艾玛·维尔的银牌需要归还，但她已经死了。红发女人九天前取钥匙的阶段性答案也落地：她知道克莱想重新核对箱内遗留物，所以先把钥匙拿走，防止别人提前开箱；她仍不交代更深身份。
怀表只在埃文看见04银牌以后极轻地走一下；内盖可以只出现“第二笔”三个字，或者完全不出现新规则。不要写“第二笔已触发”的游戏提示，也不要让红发女人解释怀表。
阶段状态变化：七号箱从未知去向变成警方封存证物；埃文与米拉关系因她隐瞒维尔死讯而破裂但被迫继续合作；红发女人失去钥匙控制权；汤普森承认这是现实案件的一部分但仍不相信超自然。
章末用现实后果：汤普森封箱并带走登记，要求埃文次日上午到警署补正式证词；同时事务所来人通知，因银牌手续和警方介入，埃文的克莱遗产清算权限被临时冻结。埃文站在盐场门口，手里只剩自己的怀表，而“第二笔”指向一个已经死了三年的人。"""


FAST_WRITER_RULES = """【NarrativeOS Writer Skill v18 快速执行摘要】
- 正文以完整段落和自然长短句为主，短句只用于确有需要的冲击；禁止电报体、台词墙。
- 先让人物在现场做事、遇到阻力、承担后果，再解释必要信息；程序和账目必须服务冲突，不写成报告。
- 对白必须带试探、躲避、攻击、求证、拖延等人物意图，不做问答式资料传输。
- 重要物件维护状态账：地点、持有人、转柜/核验/领取/返还不可混写，同一物件不得无解释“离开两次”。
- 超自然原因可以未知，但已出现的可观测事实必须兼容；怀表不得成为万能导航器。
- 现实制度不会因超自然目标消失：遗产、警方权限、所有权、职业后果都要连续。
- 克制模型腔、作者总结、过度工整金句和高频“不是A，是B”。
- 现场每场抓2—3个值钱细节即可，优先人物动作、身体感受、视线和空间关系。
"""

FAST_CONTINUITY_CONTRACT = """【《灰街》6—10节硬连续性合同】
时间与保管链：
- 克莱死亡约四天前；埃文是在克莱死后才接触怀表。
- 第四节下午埃文亲眼见到鲍勃·费恩且与他交谈。因此费恩若在第六节死亡，只能死在埃文离开十三号仓之后，绝不能写“死亡时间在见面之前”。
- 钥匙：七年前与银牌一起入仓；六年前仅仓内转柜/单独封存，没有离库；克莱死亡前九天，红发女人凭旧授权正式领取离库。
- 银牌：第五节已由埃文亲手交给米拉，因此后续事务所只能追究“未完成核验/交接/所有权手续”，不能又写银牌仍由埃文持有或已在事务所保险柜。
- 七号箱不是七码头第七扇铁门。它是资产处登记过的实体保管物。
人物与机构：
- 汤普森始终是警官，不是事务所职员、埃文上级、特别监管组代理人或私人打手。
- 埃文是遗产清算员，不是克莱继承人；不得凭空出现“隐藏遗嘱让埃文继承”。
- 露西/事务所人员只处理事务所账目和声誉，不掌握警方内部信息，不写成秘密组织成员。
- 红发女人前文已出现：年轻、红发、戴手套；第四节结尾她在十三号仓二楼窗后出现。后文不得写成黑发。
维尔线：
- 第六节只出现“维尔”这个可追查名字，不擅自猜出多个互相冲突的全名。
- 第七节通过合法旧港务人事/资产档案确认其全名为“艾玛·维尔”，女性，曾与第七码头资产处有关。
- 第八节确认艾玛·维尔约三年前已经死亡；但克莱死亡前九天附近仍有一份与七号箱有关的记录调用了她留下的旧授权/签章样本。先判定“制度异常”，不直接宣布鬼魂或伪造者身份。

禁止新增或使用以下跑偏设定：阿尔瓦律所、米拉律师团队、隐藏继承人、克莱受益人/遗嘱继承、信托、恒温库、C-107、电子监控、门禁日志、加密权限库、特别监管组、tactical support、用假证件潜入。除格兰特事务所、警方、港务档案机构、十三号仓、米拉钟表铺、旧盐场公共寄存区外，不新增掌握主线秘密的大机构。
时代与制度：
- 世界已有煤气灯、有轨车、打字机、纸质档案、电话、少量汽车；禁止电子监控、加密权限库、数字系统、tactical support等现代词。
- 埃文查档必须走自己的清算授权、公开档案、公证/港务窗口或证人路径；禁止伪造证件、替换照片、冒充警察、无理由潜入。
- 警方信息只通过汤普森在权限范围内告知；汤普森不能把完整尸检和内部证据随便交给埃文。
章节接口：
- 第六节：现实账务后果 + 七号箱入口 + 费恩死亡（死在埃文离开后）+ 红发女人主动改变局势。
- 第七节：已知费恩死亡，不要再把死讯当新反转；追七码头资产处，确认艾玛·维尔身份。
- 第八节：确认维尔已死且近期仍有旧授权被调用；线索合法指向旧盐场。
- 第九节：旧盐场交易/交接，不重复十三号仓取银牌；米拉有限介入并为隐瞒付代价；若第十节需要字条或钥匙，本节必须明确交接。
- 第十节：七号箱位置/开启条件与第九节一致；不开“隐藏继承人”新设定；第二笔通过箱内实物/文件落地；汤普森依法行动；用现实后果收尾。
"""




def _section5(text: str) -> str:
    match = re.search(r"^# 第五节[　 ]+.+?$", text, re.MULTILINE)
    if not match:
        raise RuntimeError("section 5 not found")
    return text[match.end():].strip()


def _create_project(source_text: str, canon: str, brief: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO projects(title,description,genre,status) VALUES(?,?,?,?)",
            ("灰街", "NarrativeOS fast batch: sections 6-10", "悬疑 / 怪谈", "draft"),
        )
        project_id = int(row.lastrowid)
        memories = [
            ("canon", "锁定Canon", canon),
            ("outline", "第6-10节硬约束", brief),
            (
                "continuity",
                "前五节交接",
                (
                    "第5节结束：银牌已交给米拉；怀表第一笔清空；SV-7极淡再现。"
                    "银牌仍存在遗产/核验/所有权后果。汤普森始终是警官，不是事务所职员。"
                    "红发女人此前已被费恩描述为年轻、红发、戴手套，并在十三号仓二楼窗后出现。"
                ),
            ),
        ]
        for kind, title, value in memories:
            m = conn.execute(
                "INSERT INTO memories(project_id,kind,title,content,source_type,source_ref,confirmed) VALUES(?,?,?,?,?,?,1)",
                (project_id, kind, title, value, "manual", f"gray-fast:{title}"),
            )
            conn.execute(
                "INSERT INTO memory_versions(memory_id,version,kind,title,content,confirmed,note) VALUES(?,?,?,?,?,?,?)",
                (m.lastrowid, 1, kind, title, value, 1, "Gray Street fast batch"),
            )

        chars = [
            ("埃文·格雷", "主角；遗产清算事务所职员", "理性、重证据和手续；不是警察。"),
            ("米拉·阿尔瓦", "钟表铺经营者；七码头资产处旧成员", "掌握部分历史但不讲完整规则。"),
            ("汤普森", "警官", "跨机构调查者；不负责事务所账务。"),
            ("红发女人", "身份未知；钥匙领取者", "红发、戴手套；已在前文出现，不是新空降角色。"),
        ]
        for name, role, profile in chars:
            conn.execute(
                "INSERT INTO characters(project_id,name,role,profile,tags) VALUES(?,?,?,?,?)",
                (project_id, name, role, profile, "[]"),
            )
    return project_id


def _compact_findings(outputs: list[str], draft: str, limit: int = 14000) -> str:
    rows: list[str] = []
    for idx, output in enumerate(outputs, start=1):
        try:
            findings = _parse_review_output(output, draft)
        except (TypeError, ValueError):
            findings = []
        for f in findings:
            if f.get("severity") == "info":
                continue
            row = [f"[{idx}] {str(f.get('severity') or '').upper()} {str(f.get('summary') or '').strip()}"]
            excerpt = str(f.get("excerpt") or "").strip()
            suggestion = str(f.get("suggestion") or "").strip()
            if excerpt:
                row.append("原文：" + excerpt[:600])
            if suggestion:
                row.append("动作：" + suggestion[:900])
            rows.append("\n".join(row))
    return ("\n\n".join(rows) or "无需要修改的问题。")[:limit]


async def _review(task_id: int, draft: str, kind: str, role: str, focus: str) -> str:
    result = await _run_step(
        task_id=task_id,
        role=role,
        stage=f"gray-fast-{kind}",
        mode="check",
        content=draft,
        instruction=(
            FAST_CONTINUITY_CONTRACT
            + "\n\n【复审已知前文】\n"
            + "这是第6—10节，读者已经读过第1—5节：克莱与费恩是两个不同人物；克莱在故事开场前已死，费恩在第4节仍活着；"
            + "SV-7从第1节起反复出现且故意尚未解释完整含义；怀表已经明确出现过‘归还第一笔’，所以第10节出现‘第二笔’属于回收，不是首次空降术语。"
            + "不要要求作者现在给SV-7下完整定义，也不要把‘克莱死亡前九天’误改成‘费恩死亡前九天’。"
            + "\n\n"
            + focus
            + "\n\n"
            + REVIEW_FORMAT
        ),
    )
    return result.content



def _extract_outline_section(outline: str, number: int) -> str:
    cn = {6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}[number]
    next_cn = {6: "七", 7: "八", 8: "九", 9: "十", 10: None}[number]
    start_match = re.search(
        rf"(?m)^#{1,3}\s*第{cn}节.*$|^第{cn}节.*$",
        outline,
    )
    if not start_match:
        return outline
    start = start_match.start()
    if next_cn is None:
        return outline[start:].strip()
    next_match = re.search(
        rf"(?m)^#{1,3}\s*第{next_cn}节.*$|^第{next_cn}节.*$",
        outline[start_match.end():],
    )
    if not next_match:
        return outline[start:].strip()
    end = start_match.end() + next_match.start()
    return outline[start:end].strip()


CANONICAL_SECTION_TITLES = {
    6: "七号箱",
    7: "第七码头资产处",
    8: "已死的维尔",
    9: "旧盐场交易",
    10: "第二笔",
}


def _normalize_section_heading(number: int, text: str) -> str:
    cn = {6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}[number]
    cleaned = text.strip()
    # Models may return '# 第十节', '## 第十节', or just '第十节'.
    # Strip only the first heading-like line; preserve the prose body verbatim.
    cleaned = re.sub(
        r"(?s)^\s*#{0,3}\s*第[六七八九十]节[^\n]*\n+",
        "",
        cleaned,
        count=1,
    ).strip()
    spill = re.search(r"(?m)^#{1,3}\s*第[六七八九十]节[^\n]*$", cleaned)
    if spill:
        cleaned = cleaned[: spill.start()].rstrip()
    return f"# 第{cn}节　{CANONICAL_SECTION_TITLES[number]}\n\n{cleaned}".strip()


def _section_body_length(text: str) -> int:
    body = re.sub(r"(?m)^#\s*第[六七八九十]节[^\n]*\n?", "", text, count=1)
    return len(body.strip())


async def _write_one_section(
    *,
    task_id: int,
    number: int,
    previous_tail: str,
    brief: str,
) -> str:
    cn = {6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}[number]
    section_outline = _extract_outline_section(FAST_OUTLINE, number)
    compact_brief = brief[-4200:]
    result = await _run_step(
        task_id=task_id,
        role="writer-fast",
        stage=f"gray-fast-draft-{number}",
        mode="continue",
        content=section_outline,
        instruction=(
            FAST_WRITER_RULES
            + "\n\n"
            + FAST_CONTINUITY_CONTRACT
            + "\n\n【上一节承接尾部】\n"
            + previous_tail[-3600:]
            + "\n\n【本节冻结大纲】\n"
            + section_outline
            + "\n\n【项目续写约束摘录】\n"
            + compact_brief
            + f"""
\n只写《灰街》第{cn}节完整正文，不写其他节。
目标 2600—3600 中文字符；至少2100字符。不要为了凑字数重复解释。
形成完整场景弧：现实任务 → 阻碍升级 → 人物主动选择 → 状态变化。
埃文始终是主要视角；汤普森始终是警官；红发女人是前文已出现角色。
不得新增超自然规则、新关键人物或巧合送线索。
标题格式：# 第{cn}节　<标题>。只输出标题与正文。"""
        ),
    )
    text = _normalize_section_heading(number, result.content)
    if _section_body_length(text) >= 2100:
        return text

    expanded = await _run_step(
        task_id=task_id,
        role="writer-fast",
        stage=f"gray-fast-expand-{number}",
        mode="expand",
        content=text,
        instruction=(
            FAST_WRITER_RULES
            + f"\n当前第{cn}节约{_section_body_length(text)}字符，仍是短章。"
            + "不改变事实、事件顺序、线索来源和章末状态，只补现场动作、空间移动、人物犹豫、潜台词和必要过渡。"
            + "扩到2600—3600中文字符，至少2100字符。只输出本节完整正文。"
        ),
    )
    return _normalize_section_heading(number, expanded.content)


def _validate_five_sections(text: str) -> dict[int, int]:
    lengths: dict[int, int] = {}
    cn_to_num = {"六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    pattern = re.compile(r"(?m)^# 第([六七八九十])节[^\n]*$")
    matches = list(pattern.finditer(text))
    for idx, match in enumerate(matches):
        number = cn_to_num[match.group(1)]
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        lengths[number] = len(text[match.end():end].strip())
    return lengths


async def main() -> int:
    init_db()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    source_path = LOCKED_SOURCE if LOCKED_SOURCE.exists() else FALLBACK_SOURCE
    if not source_path.exists():
        raise RuntimeError("sections 1-5 source missing")

    source_text = source_path.read_text(encoding="utf-8")
    canon = CANON_PATH.read_text(encoding="utf-8")
    brief = BRIEF_PATH.read_text(encoding="utf-8")
    project_id = _create_project(source_text, canon, brief)

    task_id = _create_task(
        project_id=project_id,
        chapter_id=None,
        goal="一次生成并修订《灰街》第6-10节连续正文",
        instruction="快速批处理，但必须遵守NarrativeOS Skill、Canon和多Reader Gate。",
    )
    _task_context(task_id, project_id)  # freeze/record platform task resources

    outline_text = FAST_OUTLINE
    (OUTPUT_DIR / "outline.md").write_text(outline_text + "\n", encoding="utf-8")

    section_drafts: list[str] = []
    previous_tail = _section5(source_text)
    for number in (6, 7, 8, 9, 10):
        section = await _write_one_section(
            task_id=task_id,
            number=number,
            previous_tail=previous_tail,
            brief=brief,
        )
        section_drafts.append(section)
        previous_tail = section
    draft = "\n\n".join(section.strip() for section in section_drafts).strip()
    draft_lengths = _validate_five_sections(draft)
    if set(draft_lengths) != {6, 7, 8, 9, 10}:
        raise RuntimeError(f"writer did not return all five sections: {draft_lengths}")
    if any(length < 2200 for length in draft_lengths.values()):
        raise RuntimeError(f"one or more sections remain under-length: {draft_lengths}")

    reviews = await asyncio.gather(
        _review(
            task_id,
            draft,
            "continuity",
            "continuity-plot-reviewer",
            """只审第6-10节的连续性、实体状态、权限、线索来源和前五节接缝。
重点检查：汤普森机构身份、银牌现实后果、钥匙保管链、红发女人既有伏笔、费恩死亡时间必须晚于埃文见到费恩、
维尔姓名/性别/死亡时间/近期授权记录、查档合法性、七号箱位置与钥匙交接、时代技术词。
未知超自然机制不是错误，已观测事实冲突才是错误。
任何上述跨节事实冲突都判High/REWRITE_BLOCK，不要降成偏好。""",
        ),
        _review(
            task_id,
            draft,
            "ordinary",
            "blind-reader",
            """你是普通读者。检查哪里不好读、人物假、推进硬、想跳过，以及是否自然想继续。
不要把不知道谜底本身当问题。""",
        ),
        _review(
            task_id,
            draft,
            "commercial",
            "master-reader",
            """你是商业阅读Reader。检查五节整体节奏、每节推进、人物记忆点、续读欲与章末状态变化。
不要要求大量短句或网文化碎段。""",
        ),
        _review(
            task_id,
            draft,
            "naturalness",
            "blind-natural-reader",
            """你是文学自然度Reader。检查AI味、模板句、作者替读者总结、办案纪要感、台词墙、碎短句和过度工整对白。""",
        ),
    )

    compact_reviews = _compact_findings(list(reviews), draft, limit=10000)

    async def revise_one(section_text: str, number: int) -> str:
        cn = {6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}[number]
        try:
            result = await _run_step(
                task_id=task_id,
                role="revision-fast",
                stage=f"gray-fast-revision-{number}",
                mode="polish",
                content=section_text,
                instruction=(
                    FAST_WRITER_RULES
                    + "\n\n"
                    + FAST_CONTINUITY_CONTRACT
                    + "\n\n【本轮多Reader精简问题】\n"
                    + compact_reviews[:7000]
                    + "\n\n【本节冻结大纲】\n"
                    + _extract_outline_section(FAST_OUTLINE, number)
                    + f"""
\n只修第{cn}节。只处理与本节有关的真实问题；普通偏好不得改Canon。
不得压缩成梗概，不得删现实后果、权限边界、线索来源或章末状态变化。
修订后至少2000中文字符。只输出本节完整正文。"""
                ),
            )
            revised_section = _normalize_section_heading(number, result.content)
            if _section_body_length(revised_section) >= 2000:
                return revised_section
        except RuntimeError:
            # A transient revision-model failure must not discard a complete
            # draft that already passed the length gate. Final readers still
            # review the preserved draft and can block delivery.
            pass
        return section_text

    draft_parts: dict[int, str] = {}
    pattern = re.compile(r"(?m)^# 第([六七八九十])节[^\n]*$")
    cn_to_num = {"六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    matches = list(pattern.finditer(draft))
    for idx, match in enumerate(matches):
        number = cn_to_num[match.group(1)]
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(draft)
        draft_parts[number] = draft[match.start():end].strip()

    revised_parts = await asyncio.gather(
        *[revise_one(draft_parts[number], number) for number in (6, 7, 8, 9, 10)]
    )
    revised = "\n\n".join(revised_parts).strip()
    revised_lengths = _validate_five_sections(revised)
    if set(revised_lengths) != {6, 7, 8, 9, 10}:
        raise RuntimeError(f"revision lost one or more sections: {revised_lengths}")
    if any(length < 2000 for length in revised_lengths.values()):
        raise RuntimeError(f"revision over-compressed one or more sections: {revised_lengths}")

    final_reviews = await asyncio.gather(
        _review(
            task_id,
            revised,
            "final-continuity",
            "continuity-plot-reviewer",
            """最终Gate：只检查是否还存在会阻断交付的连续性、状态、权限、因果、章间接缝问题。
没有blocking只输出NO_ISSUE。""",
        ),
        _review(
            task_id,
            revised,
            "final-reader",
            "blind-reader",
            """最终普通读者Gate：只抓会明显影响阅读、人物可信度或续读的问题。没有blocking只输出NO_ISSUE。""",
        ),
        _review(
            task_id,
            revised,
            "final-naturalness",
            "blind-natural-reader",
            """最终自然度Gate：只抓明显AI味、台词墙、碎短句、作者总结式问题。没有blocking只输出NO_ISSUE。""",
        ),
    )

    blocking = False
    for index, output in enumerate(final_reviews):
        for finding in _parse_review_output(output, revised):
            severity = finding.get("severity")
            if severity == "blocking":
                blocking = True
            # Final continuity gate is stricter than taste readers: any
            # remaining concrete continuity/action-chain finding blocks lock.
            if index == 0 and severity != "info":
                blocking = True

    (OUTPUT_DIR / "sections-06-10-fast.md").write_text(revised + "\n", encoding="utf-8")
    (OUTPUT_DIR / "outline.md").write_text(outline_text + "\n", encoding="utf-8")
    (OUTPUT_DIR / "reviews.json").write_text(
        json.dumps(
            {"initial": list(reviews), "final": list(final_reviews)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest = {
        "project": "灰街",
        "mode": "fast-core-gates",
        "source": str(source_path),
        "source_is_platform_locked": source_path == LOCKED_SOURCE,
        "sections": [6, 7, 8, 9, 10],
        "draft_lengths": draft_lengths,
        "final_lengths": revised_lengths,
        "final_blocking": blocking,
        "status": "awaiting_human_approval" if not blocking else "blocked",
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False), flush=True)
    return 0 if not blocking else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
