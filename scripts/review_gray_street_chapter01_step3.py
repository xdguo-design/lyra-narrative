from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from app.db import init_db
from app.services.workflow_service import _run_step
from scripts.generate_gray_street_chapter01 import configure_provider, create_project
from app.services.book_pipeline import _create_task

INPUT = Path("artifacts/step1-input/chapter-01-step1-draft.md")
OUTPUT_DIR = Path("artifacts/gray-street-chapter01-step3")


READERS = [
    (
        "blind-reader",
        "普通读者",
        """你是第一次看到这篇小说的普通中文读者。不要猜作者意图，不看设定资料。
只判断实际阅读体验：哪里顺、哪里假、哪里像AI、哪里人物突然像工具人、哪里想跳过、哪里看不懂但文本又假装你该懂。
特别警惕作者替人物解释、过度工整、台词像规章或说明书。
输出固定：
VERDICT: PASS 或 VERDICT: FAIL
TOP_ISSUES:
- 最多5条，必须引用正文短片段
READER_TRACE:
- 按阅读顺序记录明显卡点
KEEP:
- 最值得保留的2—3处
不要改写正文。""",
    ),
    (
        "blind-dialogue-reader",
        "对白读者",
        """你只作为对白读者盲读正文，不看人物卡。
检查：人物是否真的在说话而不是作者借嘴解释；是否连续一问一答；是否单方面长篇输出；台词是否过度理性、规章化、书面化；人物说话时身体、手上事情、空间和关系是否仍存在；动作是否只是机械贴标签。
输出固定：
VERDICT: PASS 或 VERDICT: FAIL
DIALOGUE_FAILURES:
- 每条给逐字短片段、人物、失败原因、严重程度 HIGH/MEDIUM/LOW
TURN_TAKING:
- 是否出现聊天框/问卷感
KEEP:
- 保留哪些真实话轮
不要提供整段重写答案。""",
    ),
    (
        "blind-artifice-reader",
        "自然度读者",
        """你是专门识别AI文风和作者痕迹的中文母语读者。
只看正文，检查：不是A而是B、否定后解释、作者总结心理、刻意金句、模板悬念、空洞比喻、形容词替代动作、自动生成式过渡、大量短句/单句段落、过于平均整齐的段落和句群。
意思正确不等于自然；第一眼像模型输出就指出。
输出固定：
VERDICT: PASS 或 VERDICT: FAIL
ARTIFICE:
- 逐字片段 + 标签 + 为什么像AI/作者手
CADENCE:
- 长短句和段落是否自然
KEEP:
- 最自然的片段特征
不要改写正文。""",
    ),
    (
        "cadence-character-reader",
        "商业阅读读者",
        """你是有大量长篇小说阅读经验的商业阅读读者。
不看设定，只看这一节能否让你继续读。检查主角是否有主动性、配角是否有记忆点、日常是否有生活感、异常进入是否自然、节奏是否靠短句/硬钩子/巧合强推、结尾是否真有续读欲。
不要因为信息量大或句子短就判“节奏好”。
输出固定：
VERDICT: PASS 或 VERDICT: FAIL
ENGAGEMENT:
- 开头/中段/异常段/结尾分别评价
CHARACTERS:
- 埃文、芬奇、贝恩、霍尔、房东是否像不同的人
DROP_POINTS:
- 哪些地方会让你放下书
KEEP:
- 最有潜力的部分
不要改写正文。""",
    ),
]


def _strip_title(text: str) -> str:
    text = text.strip()
    if text.startswith("# 第一节 怀表"):
        return text[len("# 第一节 怀表"):].strip()
    return text


def _verdict(text: str) -> str:
    match = re.search(r"VERDICT\s*[:：]\s*(PASS|FAIL)", text, flags=re.I)
    return match.group(1).upper() if match else "FAIL"


async def main() -> None:
    configure_provider()
    init_db()
    project_id, chapter_id = create_project()
    task_id = _create_task(
        project_id=project_id,
        chapter_id=chapter_id,
        goal="《灰街》第一节 Step 3 多读者盲读",
        instruction="只读，不改，不看 Canon 与专项 Reviewer 结果。",
    )

    draft = _strip_title(INPUT.read_text(encoding="utf-8"))

    async def run_reader(role: str, name: str, instruction: str):
        result = await _run_step(
            task_id=task_id,
            role=role,
            stage="gray-street-chapter01-step3-blind-read",
            mode="check",
            content=draft,
            instruction=instruction,
        )
        return {
            "role": role,
            "reader": name,
            "provider": result.provider,
            "model": result.model,
            "verdict": _verdict(result.content),
            "report": result.content,
        }

    results = await asyncio.gather(
        *(run_reader(role, name, prompt) for role, name, prompt in READERS)
    )
    fail_count = sum(1 for item in results if item["verdict"] != "PASS")
    summary = {
        "step": 3,
        "task_id": task_id,
        "reader_count": len(results),
        "pass_count": len(results) - fail_count,
        "fail_count": fail_count,
        "all_pass": fail_count == 0,
        "status": "multi_reader_complete",
        "next_step": "unified_revision",
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "multi-reader-review.json").write_text(
        json.dumps(
            {"summary": summary, "readers": results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
