from app.services.skill_learning_store import render_learning_overlay


def test_global_learning_overlay_generalizes_without_cross_project_plot_leakage():
    batches = [
        {
            "schema": "NARRATIVE_BUILTIN_SKILL_LEARNING_V2",
            "batch_id": "old-project-1",
            "source": "chapter-2-review",
            "events": [
                {
                    "reviewer": "continuity-plot-reviewer",
                    "category": "continuity",
                    "pattern_signature": "sig-continuity",
                    "reason": (
                        "赵六不得持有库账，周虎必须先复量。"
                        "触发 MICRO_CONTINUITY_GAP 与 CUSTODY_CHAIN_GAP。"
                    ),
                    "suggestion": "把赵六手里的账本交回县衙，再让周虎复核。",
                    "excerpt": "赵六抱着库账站在门口。",
                },
                {
                    "reviewer": "character-dialogue-reviewer",
                    "category": "dialogue",
                    "pattern_signature": "sig-dialogue",
                    "reason": "孙成这句话过度工整，触发 ORALITY_GAP。",
                    "suggestion": "改成孙成当场真正会说的话。",
                    "excerpt": "孙成说：先记少了多少。",
                },
            ],
        }
    ]

    writer = render_learning_overlay("writer", batches)
    reader = render_learning_overlay("reader", batches)
    combined = writer + "\n" + reader

    # Generalized capability and labels transfer.
    assert "连续性与事实" in combined
    assert "人物与对白" in combined
    assert "MICRO_CONTINUITY_GAP" in combined
    assert "CUSTODY_CHAIN_GAP" in combined
    assert "ORALITY_GAP" in combined
    assert "项目专名" in reader
    assert "跨作品污染" in writer

    # Raw project evidence must never become another project's prompt context.
    for leaked in [
        "赵六",
        "周虎",
        "孙成",
        "库账",
        "县衙",
        "把赵六手里的账本交回县衙",
        "赵六抱着库账站在门口",
    ]:
        assert leaked not in combined


def test_unclassified_raw_rejection_stays_evidence_only():
    batches = [
        {
            "schema": "NARRATIVE_BUILTIN_SKILL_LEARNING_V2",
            "batch_id": "one-off",
            "source": "human",
            "events": [
                {
                    "reviewer": "reader",
                    "category": "misc",
                    "pattern_signature": "sig-one-off",
                    "reason": "阿甲把一盆特定颜色的花放错了窗台。",
                    "suggestion": "把花搬回东窗。",
                    "excerpt": "那盆花在西窗。",
                }
            ],
        }
    ]

    assert render_learning_overlay("writer", batches) == ""
    assert render_learning_overlay("reader", batches) == ""
