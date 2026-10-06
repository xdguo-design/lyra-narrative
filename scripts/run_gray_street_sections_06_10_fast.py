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
开场：第一笔归还后的第二天早晨，埃文提前到格兰特事务所，银牌核验单对不上实物去向，事务所内部高级文员要求他当天补交接说明。
推进：埃文重查克莱遗产的原始附页，发现一条此前被归入“旧港务杂项”的未结记录：七码头资产处内部物件“七号箱”，状态栏长期写“待处置”，没有合法出库签名。记录旁的旧编号与SV-7同源，但正文不解释SV含义。
现实压力：汤普森以警官身份来电/到访，告知鲍勃·费恩已死亡；埃文因前一日刚去过十三号仓，成为必须说明行踪的关联证人。汤普森只提供警方有权告诉证人的最少信息，不泄露完整案卷。
人物行动：红发女人不再只远远出现。她通过一个现实动作改变局势，例如在事务所外截走一份本应送达的旧港务回函、或短暂与埃文擦肩并故意留下可识别线索。她仍戴手套。
结尾：埃文意识到七号箱不是“七码头第七扇门”，而是一件被资产处登记过、后来失去合法去向的实物。现实责任让他无法退出。

## 第七节　第七码头资产处
开场：埃文一边准备警方询问，一边用遗产清算员可合法申请的旧资产核验权限追查七号箱，不潜入、不冒充警员。
推进：港务旧档案或转移目录显示，七号箱曾由第七码头资产处管理，六年前被列入内部转运，但最终签收人一栏不是米拉或克莱，而是“维尔”。名字来自合法档案，不从怀表弹出。
人物冲突：汤普森怀疑埃文隐瞒了十三号仓的真实目的；埃文不得不承认银牌存在，却仍保留怀表异常。事务所同时催他补银牌交接。
红发女人：她第一次与埃文有近距离、短促、带利益目的的接触，只确认“钥匙不等于箱子”，不讲世界观。
结尾：埃文拿到“维尔”的全名或足够身份信息，准备去找人。

## 第八节　已死的维尔
开场：埃文按现实路径查找维尔——旧雇员名册、住址登记、报纸讣告或公证记录。
核心反转：维尔已经死了，而且不是最近才死；死亡时间早于近期围绕七号箱发生的某项签收/续费/转移记录。由此产生真正的制度矛盾：有人仍在使用死者身份，或旧授权仍在被调用。
连续性：不要宣布鬼魂签字，也不要直接下结论是伪造；先把可验证事实摆在一起。
米拉：埃文没有立刻找她，兑现“如果再看见SV-7别来找我”的警告压力；但他开始确认她隐瞒的不是一个简单旧组织。
结尾：一条近期记录把“维尔”与旧盐场重新连起来，且时间落在克莱死亡前后。

## 第九节　旧盐场交易
开场：埃文不是去重复“十三号仓取东西”，而是去完成/观察一笔已经被现实记录触发的交易或交接。
交易对象：可由红发女人或她安排的中间人出现；交易围绕七号箱的“保管权/位置/钥匙条件/一份旧文件”展开，不直接给箱子。
冲突：红发女人与埃文目标不一致。她要阻止某个人先拿到箱子，埃文要搞清费恩为什么死、自己的账目为什么被卷入。
米拉：在交易前后被迫重新介入。她必须交出一项有限、可验证的信息，并为之前隐瞒付出关系代价；她仍不解释完整SV-7机制。
行动危险：来自现实人物、跟踪、抢夺、封锁或交易破裂，不用怀表突然救场。
结尾：七号箱的位置第一次被确认，或者其当前持有人被确认；同时暴露“第二笔”即将被触发。

## 第十节　第二笔
阶段高潮：埃文到达七号箱所在处，现实人物多方目的发生碰撞。箱子的开启必须依赖此前已存在的钥匙/授权/保管条件，而不是新法术。
回收：红发女人为何九天前取钥匙得到一个阶段性答案，但身份和最终动机仍保留更深一层。
第二笔：箱内内容或随箱文书让“第二笔”成为现实可指向的债/归还对象；怀表可以在此极少量回应，但不能替代发现过程。
状态变化：至少改变两项——七号箱由未知位置变成已打开/被转移；埃文与米拉关系发生实质变化；汤普森对埃文从单纯怀疑转为承认其卷入更深事件；红发女人从试探转为公开行动。
结尾：用现实行动后果收束，例如有人带走关键物、警方封锁现场、埃文失去事务所资格或不得不做下一步选择。不要只靠一行新字结束。"""

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
        instruction=focus + "\n\n" + REVIEW_FORMAT,
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
        _review(
            task_id,
            draft,
            "dialogue",
            "character-dialogue-reviewer",
            """检查人物动机和对白。对白必须与角色利益、已知信息和机构身份相符；不要把功能角色写成说明书。""",
        ),
        _review(
            task_id,
            draft,
            "rhythm",
            "language-rhythm-reviewer",
            """检查语言节奏与段落自然度。只抓真实问题，不做审美偏好式过度重写。""",
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
        "mode": "fast-batch",
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
