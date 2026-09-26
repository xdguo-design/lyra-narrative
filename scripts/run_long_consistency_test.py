from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from app.db import connect, init_db
from app.services.ai_service import assist
from app.services.book_pipeline import _create_task
from app.services.continuity_service import (
    capture_story_state,
    latest_story_state,
    repair_repetition,
    render_story_state,
    repetition_report,
)
from app.services.workflow_service import _run_step, _task_context


PROJECT_TITLE = "长篇一致性专项测试"
PROJECT_GENRE = "都市悬疑 / 科幻"
OUTPUT_DIR = Path(
    os.getenv("NARRATIVE_OUTPUT_DIR", "artifacts/long-consistency-test")
)
CHAPTER_COUNT = 8
PRIOR_WINDOW = 16000

CHARACTER_BIBLE = """# 冻结人物卡
- 沈砚：36 岁，地铁供电工程师；右手食指缺失末节；做决定前会无意识摩挲右手食指残端。七年前弟弟沈舟失踪。沈砚不知道事故真正原因。
- 姜岚：31 岁，声学取证工程师；对青霉素严重过敏；平时只称沈砚“沈工”，除非两人关系发生明确转折。她知道沈舟曾参与站台实验，但最初隐瞒。
- 周启明：52 岁，停运站旧站长；左腿旧伤，不能快速奔跑；他想销毁实验记录，因为当年的越权决定出自他本人。
- 沈舟：失踪时 22 岁。故事开始时他不在原世界正常时间线上，任何“回来”都必须遵守世界规则，不能无代价复活。
"""

WORLD_BIBLE = """# 冻结世界规则
1. 青屿站异常窗口每天只在 00:07:00 到 00:07:47 出现，总长 47 秒；窗口结束后异常列车与跨界入口同时消失。
2. 异常状态下无线电、手机网络和蓝牙都无法跨越站台边界传递有效信息；只有站内既有的有线模拟设备能在同一侧工作。
3. 红色陶瓷“相位票”每完成一次跨界就永久失去一道刻痕；三道刻痕全部消失后不能再次跨界，不能充能恢复。
4. 跨界不会改写原世界历史，只会让人进入另一条已存在的分支；因此不能靠跨界让死者在原世界复活，也不能抹掉已经发生的事故。
5. 异常列车只停靠青屿站废弃 2 号站台；不能临时改停其他站，不能在白天出现。
6. 所有后续能力和现象必须能从以上规则推导，禁止为了脱困新增规则。
"""

OUTLINE = """# 八章压力测试章纲
第1章：沈砚与姜岚进入封闭青屿站，首次确认 47 秒窗口与异常列车，留下若干现场状态细节。
第2章：两人追查旧实验记录，关系出现裂缝，并遭遇一次必须付出代价的跨界尝试。
第3章：周启明被迫加入，三人的利益冲突公开化；一个关键道具发生明确的所有权转移。
第4章：调查失败造成不可逆的现场损坏，撤离路线减少；人物必须带着上一章后果继续行动。
第5章：姜岚的隐瞒被揭开，沈砚与她的称谓和关系发生一次有原因的转折。
第6章：第二次高风险行动验证世界规则极限，不能用新增设定化解困境。
第7章：早期伤势、道具、知识差和路线状态必须继续影响行动，人物不能恢复成初始状态。
第8章：高潮与收束必须同时回收人物冲突和世界规则；不得改写历史、无代价复活或突然恢复已消耗资源。
"""

CHAPTER_BRIEFS = [
    """第一章必须自然写入这些动态事实，但不要把它们写成设定表：沈砚在撬开配电柜时左掌被铜片划出一道较深伤口并临时包扎；姜岚随身的银色录音笔摔裂外壳但仍能录音；第一次跨界由沈砚完成，因此相位票从三道刻痕变成两道。后续章节不会再重复提醒这些事实。""",
    """第二章继续推进旧实验记录调查。姜岚因为隐瞒沈舟相关资料与沈砚发生第一次正面冲突。安排一次紧迫动作场面，但必须尊重沈砚左掌伤势、姜岚的设备状态与相位票剩余刻痕。""",
    """第三章让周启明正式加入并暴露部分责任。安排一把黄铜检修钥匙由姜岚明确交给沈砚保管，从这一刻起钥匙所有权在沈砚手中，除非正文之后明确发生再次交接。""",
    """第四章一次失败行动导致 B 出口楼梯整体塌落并被混凝土与钢筋封死，判定为本书后续不可用路线。不要增加新的超自然能力。""",
    """第五章揭开姜岚早已知道沈舟参与实验。经过冲突后，她第一次直接叫沈砚“沈砚”；这一称谓变化必须有情绪和关系依据，之后可以沿用，但不能假装两人从一开始就这样称呼。""",
    """第六章进行第二次高风险跨界。相位票刻痕必须在既有消耗基础上继续递减；无线通信限制仍然有效；周启明左腿旧伤必须限制他的机动能力。""",
    """第七章把早期累积后果全部带进危机：左掌伤势、录音笔损坏、钥匙归属、B 出口封死、相位票消耗、人物已经知道的秘密都要对行动产生影响，但不要用回顾式清单复述。""",
    """第八章完成高潮与收束。必须遵守 47 秒窗口、跨界不改写原历史、相位票不可恢复等硬规则；沈舟问题必须有代价地解决，不能无条件复活；结局要体现人物前面做过的选择。""",
]


def configure_runtime() -> dict[str, str]:
    protocol = os.getenv("NARRATIVE_PROVIDER_PROTOCOL", "openai-compatible").strip()
    model = os.getenv("NARRATIVE_PROVIDER_MODEL", "sensenova-6.8-flash-lite").strip()
    provider = os.getenv("NARRATIVE_PROVIDER_NAME", "长篇一致性测试").strip()
    base_url = os.getenv("NARRATIVE_PROVIDER_BASE_URL", "").strip()
    os.environ["NOVEL_AI_KIND"] = protocol
    os.environ["NOVEL_AI_MODEL"] = model
    os.environ["NOVEL_AI_PROVIDER_NAME"] = provider
    os.environ["NOVEL_AI_API_KEY_ENV"] = "NARRATIVE_PROVIDER_API_KEY"
    if base_url:
        os.environ["NOVEL_AI_BASE_URL"] = base_url
    os.environ.setdefault("NOVEL_AI_MAX_TOKENS", "8000")
    os.environ.setdefault("NOVEL_SEED_DEMO", "0")
    return {
        "provider": provider,
        "protocol": protocol,
        "model": model,
        "base_url": base_url,
    }


def seed_project() -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO projects(title,description,genre) VALUES(?,?,?)",
            (
                PROJECT_TITLE,
                "用于检测多章生成后的角色、世界规则和章节衔接漂移。",
                PROJECT_GENRE,
            ),
        )
        project_id = int(cur.lastrowid)
        for kind, title, content in (
            ("character", "冻结人物卡", CHARACTER_BIBLE),
            ("world", "冻结世界规则", WORLD_BIBLE),
            ("outline", "八章压力测试章纲", OUTLINE),
        ):
            conn.execute(
                """
                INSERT INTO memories(
                    project_id,kind,title,content,source_type,source_ref,confirmed
                ) VALUES(?,?,?,?,?,?,1)
                """,
                (
                    project_id,
                    kind,
                    title,
                    content,
                    "test",
                    f"long-consistency:{kind}",
                ),
            )
    return project_id


def clean_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fence = re.match(r"^\s*\`\`\`(?:json)?\s*(.*?)\s*\`\`\`\s*$", candidate, re.S)
    if fence:
        candidate = fence.group(1).strip()
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", candidate, re.S)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {
        "score": 0,
        "issues": [
            {
                "severity": "blocking",
                "chapters": [],
                "problem": "审稿输出无法解析为 JSON",
                "evidence": candidate[:1000],
            }
        ],
        "raw": candidate,
    }


def count_severity(audits: dict[str, dict[str, Any]], severity: str) -> int:
    total = 0
    for audit in audits.values():
        issues = audit.get("issues") or []
        total += sum(
            1
            for issue in issues
            if str(issue.get("severity", "")).lower() == severity
        )
    return total


async def audit(
    *,
    category: str,
    rubric: str,
    manuscript: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    instruction = f"""你正在执行 NarrativeOS 长篇一致性专项验收，只检查【{category}】，不要评价文风好坏。

冻结人物：
{CHARACTER_BIBLE}

冻结世界规则：
{WORLD_BIBLE}

八章基准：
{OUTLINE}

专项检查标准：
{rubric}

下面是完整八章正文。必须跨章比对，尤其检查第1-4章形成的状态是否在第6-8章漂移：
---BEGIN MANUSCRIPT---
{manuscript}
---END MANUSCRIPT---

只输出 JSON，不要 Markdown：
{{
  "score": 0到10的整数,
  "summary": "一句话结论",
  "issues": [
    {{
      "severity": "blocking|major|minor",
      "chapters": [1, 7],
      "problem": "明确说明冲突",
      "evidence": "简短说明两处相互冲突的事实"
    }}
  ]
}}
没有问题时 issues 必须是空数组。blocking=违反冻结硬规则或让主因果无法成立；major=明显跨章人物/状态/承接矛盾；minor=不影响主因果的小漂移。"""
    result = await assist(mode="check", content="", instruction=instruction)
    return clean_json(result.content), {
        "provider": result.provider,
        "model": result.model,
    }


async def main() -> None:
    runtime = configure_runtime()
    init_db()
    project_id = seed_project()
    chapters: list[dict[str, Any]] = []
    prior_manuscript = ""

    for index, brief in enumerate(CHAPTER_BRIEFS, start=1):
        task_id = _create_task(
            project_id=project_id,
            chapter_id=None,
            goal=f"完成长篇一致性专项测试第 {index}/{CHAPTER_COUNT} 章",
            instruction=brief,
        )
        context = _task_context(task_id, project_id)
        story_state = latest_story_state(project_id)
        story_state_context = render_story_state(story_state)
        prior = prior_manuscript[-6000:] if prior_manuscript else "这是第一章，没有前文。"
        result = await _run_step(
            task_id=task_id,
            role="writer",
            stage=f"long-consistency-chapter-{index:02d}",
            mode="continue",
            content="",
            instruction="\n\n".join(
                [
                    f"当前为第 {index}/{CHAPTER_COUNT} 章。",
                    brief,
                    context,
                    story_state_context,
                    "最近前文片段（仅用于语气与章末承接；事实以 Story State 为准，不得复制）：\n" + prior,
                    """写 2200-2800 个中文字符的完整章节。Story State 是权威历史：既有伤势、道具状态、人物知识差、称谓变化和路线状态不得重置。不得重复已经发生过的“第一次”、揭密、交接、跨界或对峙场景；不得新增世界规则。用场景和行动体现连续性，不要列清单。只输出当前章节正文。""",
                ]
            ),
        )
        chapter = result.content.strip()
        if not chapter:
            raise RuntimeError(
                f"chapter {index} returned empty content; consistency result is invalid"
            )

        chapter, repeat = await repair_repetition(
            task_id=task_id,
            chapter_number=index,
            draft=chapter,
            prior_manuscript=prior_manuscript,
            story_state_context=story_state_context,
        )
        if repetition_report(chapter, prior_manuscript)["blocking"]:
            raise RuntimeError(
                f"chapter {index} still has blocking repetition after repair"
            )

        new_state = await capture_story_state(
            task_id=task_id,
            project_id=project_id,
            chapter_id=None,
            chapter_number=index,
            chapter_content=chapter,
        )

        print(
            f"chapter {index}: {len(chapter)} chars, "
            f"recent prose sent={len(prior)} chars, "
            f"state chapter={new_state['chapter_number']}",
            flush=True,
        )
        chapters.append(
            {
                "number": index,
                "task_id": task_id,
                "prior_total_chars": len(prior_manuscript),
                "prior_chars_sent": len(prior),
                "earliest_history_truncated": len(prior_manuscript) > PRIOR_WINDOW,
                "characters": len(chapter),
                "repetition": repeat,
                "story_state": new_state,
                "content": chapter,
            }
        )
        prior_manuscript += f"\n\n# 第{index}章\n\n{chapter}"

    manuscript = "\n\n".join(
        f"# 第{item['number']}章\n\n{item['content']}" for item in chapters
    )

    audits: dict[str, dict[str, Any]] = {}
    audit_models: dict[str, dict[str, str]] = {}
    specs = {
        "人物一致性": "核对人物固定生理特征、知识边界、称谓变化、秘密揭露、关系变化和伤势延续。重点检查人物是否在后章恢复成初始状态，或知道了自己不应知道的信息。",
        "世界观规则": "逐条核对 47 秒窗口、无线通信限制、相位票刻痕消耗且不可恢复、跨界不改写原历史、列车停靠限制。任何临时新增能力、规则反转或无代价复活都必须指出。",
        "章节衔接": "检查上一章造成的动作后果是否进入下一章：左掌伤势、录音笔状态、黄铜钥匙归属、B出口封死、相位票剩余刻痕、已揭露秘密、人物位置与章末钩子。重点检查第1-4章状态在第7-8章是否丢失。",
    }
    for category, rubric in specs.items():
        audits[category], audit_models[category] = await audit(
            category=category,
            rubric=rubric,
            manuscript=manuscript,
        )

    blocking = count_severity(audits, "blocking")
    major = count_severity(audits, "major")
    minor = count_severity(audits, "minor")
    scores = [
        int(audit.get("score", 0))
        for audit in audits.values()
        if str(audit.get("score", "")).isdigit()
    ]
    minimum_score = min(scores) if scores else 0
    stress_reached = any(
        item["earliest_history_truncated"] for item in chapters
    )
    if not stress_reached:
        status = "INSUFFICIENT_CONTEXT_STRESS"
    else:
        status = (
            "PASS"
            if blocking == 0 and major == 0 and minimum_score >= 8
            else "DRIFT_DETECTED"
        )

    report = {
        "status": status,
        "runtime": runtime,
        "chapter_count": CHAPTER_COUNT,
        "manuscript_characters": len(manuscript),
        "context_window": {
            "prior_window_characters": PRIOR_WINDOW,
            "chapters_with_earliest_history_truncated": [
                item["number"]
                for item in chapters
                if item["earliest_history_truncated"]
            ],
        },
        "summary": {
            "blocking": blocking,
            "major": major,
            "minor": minor,
            "minimum_score": minimum_score,
        },
        "audits": audits,
        "audit_models": audit_models,
        "chapters": [
            {
                key: value
                for key, value in item.items()
                if key not in {"content", "story_state"}
            }
            for item in chapters
        ],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "manuscript.md").write_text(manuscript, encoding="utf-8")
    for item in chapters:
        (OUTPUT_DIR / f"chapter-{item['number']:02d}.md").write_text(
            item["content"],
            encoding="utf-8",
        )

    print("LONG_CONSISTENCY_REPORT")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
