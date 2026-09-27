            (task_id,),
        )

    base_content = chapter["content"] if chapter else ""
    context = _task_context(task_id, int(task["project_id"]))
    writer_instruction = "\n\n".join(
        item
        for item in [
            f"写作目标：{task['goal']}",
            str(task["instruction"] or "").strip(),
            context,
            "请生成可供审阅的完整草稿；不要直接覆盖现有章节。",
        ]
        if item
    )

    try:
        writer = await _run_step(
            task_id=task_id,
            role="writer",
            stage="draft",
            mode="continue",
            content=base_content,
            instruction=writer_instruction,
        )
    except Exception:
        with connect() as conn:
            conn.execute(
                "UPDATE writing_tasks SET status='failed',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (task_id,),
            )
        raise

    writer_output = writer.content.strip()
    if base_content.strip():
        draft_content = (
            base_content.rstrip() + "\n\n" + writer_output
            if writer_output
            else base_content
        )
    else:
        draft_content = writer_output

    with connect() as conn:
        conn.execute(
            "UPDATE writing_tasks SET draft=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (draft_content, task_id),
        )
        conn.execute("DELETE FROM review_findings WHERE task_id=?", (task_id,))

    reviewer_specs = [
        (
            "continuity-reviewer",
            "continuity",
            "检查人物状态、称谓、时间线、地点、道具和世界规则连续性。列出明确问题与修改建议；没有问题也要明确说明。",
        ),
        (
            "plot-reviewer",
            "plot",
            "检查剧情因果、动机、信息揭示、冲突推进和悬念是否成立。列出阻断项和建议项。",
        ),
        (
            "style-reviewer",
            "style",
            "检查叙述视角、节奏、句式、重复表达和语言风格。只给可执行修改意见。",
        ),
    ]

    successful_reviews: list[str] = []
    for reviewer, category, review_instruction in reviewer_specs:
        try:
            review = await _run_step(
                task_id=task_id,
                role=reviewer,
                stage="review",
                mode="check",
                content=draft_content,
                instruction="\n\n".join(
                    item
                    for item in [
                        review_instruction,
                        """NARRATIVEOS_REVIEW_V2
请严格使用统一审核格式；每个问题一块，多个问题用单独一行 --- 分隔；没有问题只输出 NO_ISSUE。
问题标识: R001 起递增
审核轮次: INITIAL
严重性: blocking|suggestion|info
处置级别: REWRITE_BLOCK|LOCAL_REWRITE|DELETE|POLISH|PASS
问题类型: continuity|causality|character|plot|exposition|dialogue|style|atmosphere
章节/场景: 可识别范围
段落范围: 可识别范围
片段: 必须逐字复制正文中的连续原文；没有具体片段写 NONE
问题: 一句话说明具体问题，禁止泛泛写“优化节奏/加强氛围”
判级理由: 说明为什么当前处置级别足够；REWRITE_BLOCK 必须说明为什么局部修改不足
最小修改范围: 只写最少需要改动的范围
允许联动范围: 必要时允许影响的相邻内容
不得触碰范围: 必须保持不变的前后文或状态
必须保留事实: 只列与当前问题直接相关的事实锚点
禁止新增内容: 针对当前问题列出禁止新增的人物/规则/线索/巧合/关系跳变/资源恢复
执行目标: 写成修改后可以客观检查的结果
建议: 一到三句可执行修改方向，不得发明新设定
复审要求: 说明修改后必须重新验证什么
复审结果: PENDING
注意：处置级别与严重性不是一回事；若影响事实、因果或人物意图，不得只判 POLISH。""",
                        context,
                    ]
                    if item
                ),
            )
        except RuntimeError as exc:
            with connect() as conn:
                conn.execute(
                    """
                    INSERT INTO review_findings(
                        task_id,reviewer,category,severity,summary,suggestion,status
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        task_id,
                        reviewer,
                        category,
                        "warning",
                        f"Reviewer 执行失败：{exc}",
                        "可重试该任务；其他 Reviewer 结果仍保留。",
                        "open",
                    ),
                )
            continue

        successful_reviews.append(f"[{category}] {review.content}")
        parsed_findings = _parse_review_output(review.content, draft_content)
        with connect() as conn:
            for finding in parsed_findings:
                cur = conn.execute(
                    """
                    INSERT INTO review_findings(
                        task_id,reviewer,category,severity,summary,suggestion,status
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        task_id,
                        reviewer,
                        category,
                        finding["severity"],
                        finding["summary"],
                        finding["suggestion"],
                        "open",