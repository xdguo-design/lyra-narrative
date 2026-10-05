from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from app.db import init_db
from app.services.book_pipeline import _chapter_text_is_usable, _create_task
from app.services.workflow_service import _run_step
from scripts.generate_gray_street_chapter01 import CANON_PATH, configure_provider, create_project

INPUT = Path("artifacts/final1-input/chapter-01-final.md")
OUTPUT = Path("artifacts/gray-street-chapter01-final2")

REVIEWERS = [
    ("blind-reader","普通读者","只判断阅读是否自然、人物是否像活人、哪里像AI、哪里想跳。"),
    ("cadence-character-reader","商业读者","看节奏、人物记忆点、异常进入和继续阅读欲，不把短句多当成节奏好。"),
    ("blind-natural-reader","文学自然度读者","专抓作者总结、不是A而是B、模糊比喻、模板句、短句切割和机械过渡。"),
    ("character-voice-reviewer","人物读者","看埃文、芬奇、贝恩、霍尔、哈钦斯太太是否按自己的利益和关系行动。"),
    ("blind-dialogue-reader","对白读者","专抓规章腔、裸对白、问卷式问答、信息倾倒和机械动作填充。"),
    ("continuity-reviewer","连续性审核","检查时间、地点、道具、权限、因果。注意：当天十一月三日、怀表日期窗显示四日是冻结的超自然异常，不能当成时间线错误。"),
    ("character-dialogue-reviewer","人物对白专项","检查人物工具化、对白自然度、关系和身体是否仍在场。"),
    ("language-rhythm-reviewer","语言节奏专项","检查完整段落、中长句群、AI解释句和碎句。"),
]

def strip_title(t:str)->str:
    t=t.strip()
    return t[len("# 第一节 怀表"):].strip() if t.startswith("# 第一节 怀表") else t

def v(text:str)->str:
    m=re.search(r"VERDICT\s*[:：]\s*(PASS|FAIL)",text,re.I)
    return m.group(1).upper() if m else "FAIL"

def static_gate(text:str)->dict:
    failures=[]
    for tok in ["十一月三日","两点十四","四日","EVAN GREY","银色怀表一枚，运行状态异常，待验","黑色马车"]:
        if tok not in text: failures.append("missing:"+tok)
    if re.search(r"(?:并)?不是[^。！？\n]{0,48}(?:而是|只是)",text):
        failures.append("ai-template")
    banned=["这种基于","维持体面与距离的方式","似乎在等待什么","仿佛是从内部渗出来","他才允许自己"]
    for x in banned:
        if x in text: failures.append("banned:"+x)
    paras=[p.strip() for p in re.split(r"\n\s*\n",text) if p.strip()]
    pure=[bool(re.fullmatch(r"[“\"][^\n]{1,220}[”\"][。！？?!…]*",p)) for p in paras]
    streak=best=0
    for q in pure:
        streak=streak+1 if q else 0; best=max(best,streak)
    if best>=2: failures.append(f"dialogue-streak:{best}")
    prose=[p for p,q in zip(paras,pure) if not q]
    ratio=sum(1 for p in prose if len(re.sub(r"\s+","",p))<=32)/max(1,len(prose))
    if ratio>0.08: failures.append(f"short-ratio:{ratio:.1%}")
    return {"pass":not failures,"failures":failures,"short_ratio":ratio,"dialogue_streak":best}

async def reviews(task_id:int,text:str,canon:str):
    async def one(role,name,focus):
        try:
            r=await _run_step(task_id=task_id,role=role,stage="gray-ch01-final2-review",mode="check",content=text,
                instruction=f"""你是{name}。{focus}
这是最终 Gate。冻结事实：当天是十一月三日，怀表停在两点十四，日期窗显示四日；四日是故意的异常，不是时间线错误。怀表在触碰表冠后恢复走动，随后内盖自行形成 EVAN GREY 和数字 1。
只要仍有明显作者解释腔、规章腔、裸对白、问卷式对话、人物工具化、成片小短句或真正连续性错误，FAIL。
第一行严格输出 VERDICT: PASS 或 VERDICT: FAIL，后面最多5条逐字证据。
项目 Canon 摘要：
{canon[-5000:]}""")
            return {"name":name,"verdict":v(r.content),"report":r.content,"provider":r.provider,"model":r.model}
        except Exception as exc:
            return {"name":name,"verdict":"ERROR","error":f"{type(exc).__name__}: {exc}"}
    return await asyncio.gather(*(one(*x) for x in REVIEWERS))

async def main():
    configure_provider(); init_db()
    project_id,chapter_id=create_project()
    task_id=_create_task(project_id=project_id,chapter_id=chapter_id,goal="彻底重写并锁定《灰街》第一节",instruction="不再做局部补丁。")
    canon=CANON_PATH.read_text(encoding="utf-8")
    source=strip_title(INPUT.read_text(encoding="utf-8"))
    r=await _run_step(task_id=task_id,role="revision-agent",stage="gray-ch01-final2-rewrite",mode="polish",content=source,
        instruction=f"""把《灰街》第一节整体重写到可以正式发布的程度。不要逐句修补旧稿，保留冻结事件，重新组织段落和话轮。

必须做到：
- 使用“第七码头街区事务所”作为办公室，不再用泛化的区公所。
- 开场先写雨天灰街和事务所日常；黑色无家徽马车不要在办公室门口提前出现，只在鸦巷现场作为背景被看见，结尾再确认其离开。
- 挂钟明确比正常时间快；贝恩习惯拨快，芬奇私下往回调。写出人物关系，但不要解释“这说明什么”。
- 芬奇推外勤要短、生活化、带自己的利益，不长篇自辩。
- 贝恩用缺口白瓷杯，少说解释性话；任务通过表单、钥匙、封条自然落地。
- 霍尔要有自己的职业判断和不耐烦，不能只站着递台词。不要在雨里擦匕首。
- 哈钦斯太太围绕欠租和家具损失说话。埃文先问出租家具清单；没有清单就先按死者财物登记，找到再改。不要背法条，不说“算侵占”这种法律宣判。
- 埃文必须实际使用封条/登记流程，体现基层小权力。
- 尸体描写具体克制，不用“没有伤痕、没有血迹”的空泛否定清单。
- 当天明确十一月三日。怀表停在两点十四；日期窗是四日；埃文触碰表冠后秒针恢复；表盖内侧的细痕在侧光里一笔笔形成 EVAN GREY，随后出现 1。写得具体，不用“金属有生命”“从内部渗出墨迹”等模板比喻。
- 发现异常后，埃文可以短暂失措，但职业习惯让他把异常先装袋、封存、登记；不要用旁白解释心理机制。
- 原句必须出现：银色怀表一枚，运行状态异常，待验。
- 正文以完整段落和自然中长句群为主；把短动作合并进句群，不要大量单句段落。
- 禁止“不是A而是B”“他不是不怕…”以及任何作者替人物总结关系/心理的句子。
- 禁止连续裸对白和问卷式一问一答。对白中的动作必须真实影响交流，不是机械填充。
- 第一节不解释神秘体系、官方机构和幕后贵族。
- 只输出完整正文。

冻结 Canon：
{canon}
""")
    text=r.content.strip()
    if not _chapter_text_is_usable(text): raise RuntimeError("rewrite unusable")
    rs=await reviews(task_id,text,canon)
    gate=static_gate(text)
    failed=[x for x in rs if x["verdict"]!="PASS"]
    passed=(not failed) and gate["pass"]
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/"chapter-01-final.md").write_text("# 第一节 怀表\n\n"+text+"\n",encoding="utf-8")
    (OUTPUT/"gate.json").write_text(json.dumps({"passed":passed,"static":gate,"reviews":rs},ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"passed":passed,"chars":len(text),"failed":[x["name"] for x in failed],"static":gate},ensure_ascii=False),flush=True)
    if not passed: raise RuntimeError("final2 gate failed")

if __name__=="__main__": asyncio.run(main())
