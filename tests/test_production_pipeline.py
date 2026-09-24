from __future__ import annotations

import os

os.environ["NOVEL_DB_PATH"] = "/tmp/narrative-os-production-test.db"
os.environ["NOVEL_SEED_DEMO"] = "0"

from fastapi.testclient import TestClient

from app.db import db_path
from app.main import app
from app.services import production_pipeline
from app.services.ai_service import AssistResult


def setup_function():
    path = db_path()
    if path.exists():
        path.unlink()


def test_production_pipeline_refuses_demo_provider():
    previous = os.environ.get("NOVEL_AI_KIND")
    os.environ["NOVEL_AI_KIND"] = "demo"
    try:
        with TestClient(app) as client:
            project_id = client.post(
                "/api/projects",
                json={"title": "平台生产测试", "genre": "科幻"},
            ).json()["id"]
            response = client.post(
                f"/api/projects/{project_id}/production-runs",
                json={"brief": "写一部关于废弃地铁站与双现实的科幻悬疑小说。"},
            )
            assert response.status_code == 409
            assert "禁止使用 demo/mock provider" in response.json()["detail"]
    finally:
        if previous is None:
            os.environ.pop("NOVEL_AI_KIND", None)
        else:
            os.environ["NOVEL_AI_KIND"] = previous


def test_full_production_pipeline_reviews_rewrites_and_requires_human_approval(monkeypatch):
    previous_kind = os.environ.get("NOVEL_AI_KIND")
    os.environ["NOVEL_AI_KIND"] = "openai-compatible"
    review_counts = {"world": 0}

    async def fake_assist(*, mode: str, content: str, instruction: str = ""):
        if mode == "check":
            if "world-science-reviewer" in instruction and review_counts["world"] == 0:
                review_counts["world"] += 1
                return AssistResult(
                    content=(
                        "DECISION: REJECT\n"
                        "严重性: blocking\n"
                        "问题: 科学底层规则没有说明能量来源与边界。\n"
                        "建议: 明确装置只维持跨分支相干，不创造宇宙。"
                    ),
                    provider="fake",
                    model="pipeline-test",
                )
            return AssistResult(
                content="DECISION: PASS\n问题: NONE",
                provider="fake",
                model="pipeline-test",
            )

        outputs = {
            "architect": (
                "# 故事架构\n主题：失去与占有。\n"
                "核心冲突：兄妹分处两个现实；有人试图永久转移另一个现实的人。"
            ),
            "world": (
                "# 世界规则\nMIRROR 只维持两个既存现实的残余相干，不创造宇宙。\n"
                "窗口有固定时间上限。"
            ),
            "characters": (
                "# 人物与矛盾\n林桥隐瞒异常；林夏隐瞒六年观察；"
                "周越对事故负有责任并继续越线实验。"
            ),
            "outline": (
                "# 章节大纲\n第一章发现列车并选择隐瞒；"
                "中段揭示人物秘密；高潮由双端解列完成。"
            ),
            "draft": "# 第一章 七年前停运的站\n\n这是由 NarrativeOS Writer 生成的平台正文。",
            "enrich": content + "\n\n站台深处的低频嗡鸣逐渐逼近。",
            "polish": content + "\n\n林桥没有后退。",
            "revise": content + "\n\n[Revision 已解决 blocking 问题]",
        }
        return AssistResult(
            content=outputs.get(mode, content),
            provider="fake",
            model="pipeline-test",
        )

    monkeypatch.setattr(production_pipeline, "assist", fake_assist)

    try:
        with TestClient(app) as client:
            project_id = client.post(
                "/api/projects",
                json={"title": "零点站台·平台重写", "genre": "科幻悬疑"},
            ).json()["id"]
            chapter_id = client.get(
                f"/api/projects/{project_id}/chapters"
            ).json()[0]["id"]

            before = client.get(f"/api/chapters/{chapter_id}").json()
            assert before["content"] == ""

            response = client.post(
                f"/api/projects/{project_id}/production-runs",
                json={
                    "brief": (
                        "创作《零点站台》。先做架构、科学世界观、人物矛盾与章节大纲，"
                        "再写第一章；禁止全员好人，科幻规则必须前后一致。"
                    )
                },
            )
            assert response.status_code == 201
            run = response.json()
            assert run["status"] == "awaiting_approval"
            assert "NarrativeOS Writer" in run["final_chapter"]

            stages = [item["stage"] for item in run["artifacts"]]
            assert "architecture" in stages
            assert "world" in stages
            assert "characters" in stages
            assert "outline" in stages
            assert "chapter-draft" in stages
            assert "chapter-enrich" in stages
            assert "chapter-final" in stages

            world_artifacts = [
                item for item in run["artifacts"] if item["stage"] == "world"
            ]
            assert len(world_artifacts) == 2
            assert world_artifacts[0]["status"] == "rejected"
            assert world_artifacts[1]["status"] == "accepted"
            assert any(
                review["decision"] == "REJECT"
                for review in world_artifacts[0]["reviews"]
            )

            final_artifact = [
                item
                for item in run["artifacts"]
                if item["stage"] == "chapter-final"
            ][-1]
            assert len(final_artifact["reviews"]) == 5
            assert all(
                review["decision"] == "PASS"
                for review in final_artifact["reviews"]
            )

            unchanged = client.get(f"/api/chapters/{chapter_id}").json()
            assert unchanged["content"] == ""

            approved = client.post(
                f"/api/production-runs/{run['id']}/approval",
                json={"decision": "approved", "note": "人工终审通过"},
            )
            assert approved.status_code == 200
            assert approved.json()["status"] == "approved"

            changed = client.get(f"/api/chapters/{chapter_id}").json()
            assert "NarrativeOS Writer" in changed["content"]

            memories = client.get(
                f"/api/projects/{project_id}/memories"
            ).json()
            production_kinds = {
                item["kind"]
                for item in memories
                if item["source_type"] == "production"
            }
            assert production_kinds == {
                "architecture",
                "world",
                "characters",
                "outline",
            }
    finally:
        if previous_kind is None:
            os.environ.pop("NOVEL_AI_KIND", None)
        else:
            os.environ["NOVEL_AI_KIND"] = previous_kind
