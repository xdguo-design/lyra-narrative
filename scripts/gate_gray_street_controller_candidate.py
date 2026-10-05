from __future__ import annotations
import asyncio, json, re
from pathlib import Path
from app.db import init_db
from app.services.book_pipeline import _create_task
from app.services.workflow_service import _run_step
from scripts.generate_gray_street_chapter01 import CANON_PATH, configure_provider, create_project

REQUEST=Path(".github/requests/gray-street-controller-gate.json")
OUT=Path("artifacts/gray-street-controller-gate")
PLAN=Path("books/gray-street/arc/ch01-05-plan.md")
SPECS=[
("blind-reader","普通读者","是否自然好读、人物是否活、哪里像AI或想跳过。"),
("cadence-character-reader","商业读者","节奏、人物记忆点、悬念与继续阅读欲。"),
("blind-natural-reader","文学自然度读者","作者总结、模板句、不是A而是B、机械转折、碎句。"),
("character-voice-reviewer","人物读者","人物是否有独立利益、选择和声音，是否工具化。"),
("blind-dialogue-reader","对白读者","裸对白、问卷式轮流、规章腔、信息倾倒、机械动作。"),
("continuity-reviewer","连续性审核","时间、地点、道具、权限、因果、前文接口。"),
("character-dialogue-reviewer","人物对白专项","人物关系、对白口语真实性、身体与空间是否在场。"),
("language-rhythm-reviewer","语言节奏专项","完整段落、中长句群、AI解释句、小短句和节奏。"),
]
def verdict(t):
 m=re.search(r"VERDICT\s*[:：]\s*(PASS|FAIL)",t,re.I); return m.group(1).upper() if m else "FAIL"
def chapter_rules(chapter,title):
 if chapter==1:
  return "第一节按 Canon 中的第一节冻结目标和执行锁审核。"
 labels={2:"第二节",3:"第三节",4:"第四节",5:"第五节"}
 plan=PLAN.read_text(encoding="utf-8")
 heading=f"## {labels.get(chapter, f'第{chapter}节')}《{title}》"
 start=plan.find(heading)
 if start<0:
  return f"当前审核第{chapter}节《{title}》；不得套用第一节专属规则。"
 end=plan.find("\n## ",start+len(heading))
 block=plan[start:end if end>=0 else len(plan)].strip()
 common_start=plan.find("## 前五节共同硬规则")
 common=plan[common_start:].strip() if common_start>=0 else ""
 return block+"\n\n"+common

def static_gate(text,chapter):
 failures=[]
 if re.search(r"(?:并)?不是[^。！？\n]{0,48}(?:而是|只是)",text): failures.append("not-A-but-B")
 paras=[p.strip() for p in re.split(r"\n\s*\n",text) if p.strip()]
 pure=[bool(re.fullmatch(r"[“\"][^\n]{1,220}[”\"][。！？?!…]*",p)) for p in paras]
 streak=best=0
 for q in pure: streak=streak+1 if q else 0; best=max(best,streak)
 if best>=2: failures.append(f"dialogue-streak:{best}")
 prose=[p for p,q in zip(paras,pure) if not q]
 ratio=sum(1 for p in prose if len(re.sub(r"\s+","",p))<=30)/max(1,len(prose))
 if ratio>0.1: failures.append(f"short-ratio:{ratio:.1%}")
 if chapter==1:
  for tok in ["十一月三日","两点十四","四日","EVAN GREY","银色怀表一枚，运行状态异常，待验","黑色马车"]:
   if tok not in text: failures.append("missing:"+tok)
 return {"pass":not failures,"failures":failures,"short_ratio":ratio,"dialogue_streak":best}
async def main():
 req=json.loads(REQUEST.read_text(encoding="utf-8")); chapter=int(req["chapter_no"]); title=req["title"]; path=Path(req["candidate_path"])
 configure_provider(); init_db(); pid,cid=create_project(); tid=_create_task(project_id=pid,chapter_id=cid,goal=f"审核《灰街》第{chapter}节《{title}》外部总编候选稿",instruction="只审核不改稿")
 text=path.read_text(encoding="utf-8").strip()
 if text.startswith("# "): text="\n".join(text.splitlines()[2:]).strip()
 canon=CANON_PATH.read_text(encoding="utf-8")
 if chapter > 1:
  marker="## \u7b2c\u4e00\u8282\u300a\u6000\u8868\u300b\u51bb\u7ed3\u76ee\u6807"
  if marker in canon:
   canon=canon.split(marker,1)[0]
 rules=chapter_rules(chapter,title)
 prior=""
 if req.get("prior_path") and Path(req["prior_path"]).exists(): prior=Path(req["prior_path"]).read_text(encoding="utf-8")[-6500:]
 async def one(role,name,focus):
  try:
   extra=""
   if chapter==1: extra="冻结事实：当天十一月三日，怀表日期窗显示四日是故意异常，不能判时间线错误。"
   r=await _run_step(task_id=tid,role=role,stage=f"controller-gate-ch{chapter:02d}",mode="check",content=text,instruction=f"""你是{name}。{focus}
这是正式 Gate，只审核，不重写。只要出现明显AI解释腔、连续裸对白、问卷式对白、人物工具化、成片小短句、真正连续性/因果错误，就 FAIL。
{extra}
第一行严格输出 VERDICT: PASS 或 VERDICT: FAIL，后面最多列5条逐字证据。
当前章节冻结规则：\n{rules}\n必要前文：{prior}\n项目 Canon 摘要：{canon[-4500:]}""")
   return {"name":name,"verdict":verdict(r.content),"report":r.content,"provider":r.provider,"model":r.model}
  except Exception as e: return {"name":name,"verdict":"ERROR","error":f"{type(e).__name__}: {e}"}
 rs=await asyncio.gather(*(one(*x) for x in SPECS)); sg=static_gate(text,chapter)

 compact_reviews=json.dumps(rs,ensure_ascii=False)[:22000]
 non_pass=[item for item in rs if item["verdict"]!="PASS"]
 if not non_pass and sg["pass"]:
  aggregate=type("GateResult",(),{"content":"VERDICT: PASS\nALL_REVIEWERS_PASS","provider":"","model":""})()
 else:
  aggregate=await _run_step(
   task_id=tid,
   role="master-reader",
   stage=f"controller-aggregate-ch{chapter:02d}",
   mode="check",
   content=text,
   instruction=f"""你是《灰街》的总编 Gate。前面已经有 8 路独立读者/专项 Reviewer。你的任务不是投票，而是核对证据、消解互相矛盾的意见，并给最终 PASS/FAIL。

硬规则：
1. 静态硬 Gate 只要失败，最终必须 FAIL。
2. 任一 Reviewer 如果指出了有逐字证据、且你核对正文后确认存在的【明显 AI 解释腔 / 连续裸对白或问卷式对白 / 人物明显工具化或说话时身体与场景消失 / 真正的 Canon、因果、权限、时间线错误】，必须 FAIL。
3. 单纯审美偏好、轻微可润色项、与正文不符的误判、重复意见，不得单独阻断。
4. Reviewer ERROR 不是自动 FAIL。若同一维度已有其他正常 Reviewer 覆盖，且你直接核对正文未发现硬伤，可标记 COVERED_ERROR；若关键维度完全无人覆盖才 FAIL。
5. 不得按多数票机械判定；必须逐条核对 FAIL 的证据是否真实存在。
6. 若当前审核第一节，十一月三日与日期窗四日属于冻结异常；若当前章节大于第一节，严禁使用第一节专属目标或执行锁判定当前章节，出现这种意见必须标记 SCOPE_MISMATCH 并驳回。
7. 用户明确讨厌小短句、连续裸对白、“不是A而是B”作者总结。这三类属于硬规则，不得以风格偏好放过。

第一行严格输出 VERDICT: PASS 或 VERDICT: FAIL。
随后输出：
【确认的硬伤】没有则写 NONE
【驳回的误判/轻微项】
【Reviewer Error 覆盖判断】
【最终理由】

静态 Gate：
{json.dumps(sg,ensure_ascii=False)}

当前章节冻结规则：\n{rules}\n\n独立 Reviewer：\n{compact_reviews}\n\n项目 Canon 摘要：
{canon[-5000:]}
"""
 )
 master_verdict=verdict(aggregate.content)
 passed=sg["pass"] and master_verdict=="PASS"
 OUT.mkdir(parents=True,exist_ok=True)
 (OUT/"gate.json").write_text(json.dumps({"passed":passed,"static":sg,"reviews":rs,"aggregate":{"verdict":master_verdict,"report":aggregate.content,"provider":aggregate.provider,"model":aggregate.model}},ensure_ascii=False,indent=2),encoding="utf-8")
 (OUT/f"chapter-{chapter:02d}-candidate.md").write_text(f"# 第{chapter}节 {title}\n\n"+text+"\n",encoding="utf-8")
 print(json.dumps({"passed":passed,"chapter":chapter,"master":master_verdict,"static":sg},ensure_ascii=False),flush=True)
 if not passed: raise RuntimeError("controller aggregate gate failed")
if __name__=="__main__": asyncio.run(main())
