from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from scripts import run_gray_street_chapter as single

REQUEST = Path(".github/requests/gray-street-chapter-run.json")
OUT_ROOT = Path("artifacts/gray-street-chapter-run")
BOOK_ROOT = Path("books/gray-street/chapters")
MAX_ATTEMPTS_PER_CHAPTER = 4


def _failure_notes(gate: dict) -> str:
    parts: list[str] = []
    aggregate = gate.get("aggregate") or {}
    if aggregate.get("report"):
        parts.append("【总编 Gate】\n" + str(aggregate["report"]))
    for item in gate.get("reviews") or []:
        if item.get("verdict") != "PASS" and item.get("report"):
            parts.append(f"【{item.get('name','Reviewer')}】\n{item['report']}")
    return "\n\n".join(parts)[:14000]


async def _run_one(number: int, title: str, base_constraints: str) -> None:
    req = {
        "chapter_no": number,
        "title": title,
        "prior_file": f"books/gray-street/chapters/{number - 1:02d}.md",
        "requested_at": "batch-06-10",
        "chapter_constraints": base_constraints,
        "attempt": 1,
        "force_revision": False,
    }

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS_PER_CHAPTER + 1):
        req["attempt"] = attempt
        REQUEST.write_text(json.dumps(req, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            await single.main()
        except Exception as exc:
            last_error = exc
            chapter_out = OUT_ROOT / f"chapter-{number:02d}"
            candidate = chapter_out / f"chapter-{number:02d}-final.md"
            gate_file = chapter_out / "gate.json"
            if attempt >= MAX_ATTEMPTS_PER_CHAPTER:
                raise
            if candidate.exists() and gate_file.exists():
                seed_dir = OUT_ROOT / "batch-seeds"
                seed_dir.mkdir(parents=True, exist_ok=True)
                seed = seed_dir / f"chapter-{number:02d}-attempt-{attempt}.md"
                shutil.copyfile(candidate, seed)
                gate = json.loads(gate_file.read_text(encoding="utf-8"))
                req["seed_file"] = str(seed)
                req["force_revision"] = True
                req["manual_findings"] = _failure_notes(gate)
                req["chapter_constraints"] = (
                    base_constraints
                    + "\n本次属于同一章节的定点返修。必须优先修复总编 Gate 与失败 Reader 已确认的问题，"
                    + "不得为了返修新增谜题、角色、怀表规则或改变上一节已锁定事实。"
                )
                continue
            # Provider/transient failure before a candidate was persisted: rerun same chapter fresh.
            req.pop("seed_file", None)
            req.pop("manual_findings", None)
            req["force_revision"] = False
            continue

        chapter_out = OUT_ROOT / f"chapter-{number:02d}"
        final_file = chapter_out / f"chapter-{number:02d}-final.md"
        gate_file = chapter_out / "gate.json"
        if not final_file.exists() or not gate_file.exists():
            raise RuntimeError(f"chapter {number} returned without persisted gate artifacts")
        gate = json.loads(gate_file.read_text(encoding="utf-8"))
        if not gate.get("passed"):
            last_error = RuntimeError(f"chapter {number} returned without PASS")
            continue

        locked_dir = OUT_ROOT / "locked-chapters"
        locked_dir.mkdir(parents=True, exist_ok=True)
        locked_path = locked_dir / f"{number:02d}.md"
        shutil.copyfile(final_file, locked_path)
        shutil.copyfile(final_file, BOOK_ROOT / f"{number:02d}.md")
        return

    if last_error:
        raise last_error
    raise RuntimeError(f"chapter {number} exhausted attempts")


async def main() -> None:
    initial = json.loads(REQUEST.read_text(encoding="utf-8"))
    start = int(initial["chapter_no"])
    end = int(initial.get("batch_to") or start)
    if end < start:
        raise ValueError("batch_to must be >= chapter_no")

    constraints = str(initial.get("chapter_constraints") or "").strip()
    titles = dict(single.TITLES)

    for number in range(start, end + 1):
        chapter_constraints = constraints
        if number > start:
            chapter_constraints = (
                "必须严格承接刚刚通过 Gate 并写入 books/gray-street/chapters 的上一节。"
                "继续执行平台 POST5_CANON 与本节功能；不得复写上一节结尾，不得跳过因果。"
                "正文保持完整自然段落和自然长短句，不写台词墙、问卷式对白、作者总结。"
                "怀表只能使用前五节已验证现象，不新增能力；黑色马车不作为固定危险提示。"
            )
        await _run_one(number, titles.get(number, f"第{number}节"), chapter_constraints)

    combined_parts: list[str] = []
    for number in range(6, end + 1):
        path = BOOK_ROOT / f"{number:02d}.md"
        if path.exists():
            combined_parts.append(path.read_text(encoding="utf-8").strip())
    (OUT_ROOT / "gray-street-06-10-final.md").write_text(
        "\n\n---\n\n".join(combined_parts).strip() + "\n",
        encoding="utf-8",
    )
    (OUT_ROOT / "batch-manifest.json").write_text(
        json.dumps(
            {
                "start": start,
                "end": end,
                "completed": list(range(start, end + 1)),
                "all_single_chapter_gates_passed": True,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main())
