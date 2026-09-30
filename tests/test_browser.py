from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.fixture(scope="module")
def live_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    data_dir = tmp_path_factory.mktemp("browser")
    db_file = Path(data_dir) / "browser.db"

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    env = os.environ.copy()
    env.update(
        {
            "NOVEL_DB_PATH": str(db_file),
            "NOVEL_SEED_DEMO": "1",
            "NOVEL_AI_KIND": "demo",
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base_url}/api/health", timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        process.terminate()
        raise RuntimeError("browser test server did not become healthy")

    try:
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_workbench_theme_autosave_and_mobile_navigation(live_server: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()

        desktop = browser.new_page(viewport={"width": 1440, "height": 1000})
        desktop_errors: list[str] = []
        desktop.on("pageerror", lambda error: desktop_errors.append(str(error)))
        desktop.goto(live_server, wait_until="networkidle")

        expect(desktop).to_have_title("NarrativeOS · 长篇小说创作工作台")
        expect(desktop.locator("#workflowBoard")).to_be_visible()
        expect(desktop.locator("#themeSelect")).to_be_visible()

        desktop.get_by_role("button", name="AI 编辑").click()
        expect(desktop.locator("#editor")).to_be_visible()

        desktop.locator("#themeSelect").select_option("neo")
        expect(desktop.locator("html")).to_have_attribute("data-theme", "neo")
        desktop.reload(wait_until="networkidle")
        expect(desktop.locator("html")).to_have_attribute("data-theme", "neo")
        desktop.get_by_role("button", name="AI 编辑").click()

        editor = desktop.locator("#editor")
        editor.fill("浏览器 E2E 自动保存测试。")
        expect(desktop.locator("#saveState")).to_contain_text("已保存", timeout=5000)
        desktop.reload(wait_until="networkidle")
        expect(desktop.locator("#editor")).to_have_value("浏览器 E2E 自动保存测试。")

        desktop.get_by_role("button", name="章节任务流线").click()
        expect(desktop.locator("#newTaskBtn")).to_be_visible()
        expect(desktop.locator("#preflightContentRepoBtn")).to_be_visible()
        expect(desktop.locator("#importContentRepoBtn")).to_be_visible()
        desktop.get_by_role("button", name="项目记忆").click()
        expect(desktop.locator("#addMemoryBtn")).to_be_visible()
        desktop.get_by_role("button", name="技法知识库").click()
        expect(desktop.locator("#addSkillBtn")).to_be_visible()
        assert desktop_errors == []

        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile_errors: list[str] = []
        mobile.on("pageerror", lambda error: mobile_errors.append(str(error)))
        mobile.goto(live_server, wait_until="networkidle")

        expect(mobile.locator("#mobileNavBtn")).to_be_visible()
        expect(mobile.locator("#themeSelect")).to_be_visible()
        expect(mobile.locator(".assistant")).to_be_visible()

        mobile.locator("#mobileNavBtn").click()
        expect(mobile.locator(".sidebar")).to_be_visible()
        mobile.locator("#mobileNavBtn").click()
        expect(mobile.locator(".sidebar")).to_be_hidden()

        overflow = mobile.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 1
        assert mobile_errors == []

        browser.close()


def test_workbench_opens_task_flow_with_global_navigation(live_server: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page.goto(live_server, wait_until="networkidle")

        expect(page.locator("body")).to_have_attribute("data-workspace", "workflow")
        expect(page.get_by_role("navigation", name="工作区导航")).to_be_visible()
        expect(page.locator("#workflowBoard")).to_be_visible()
        expect(page.locator("#workflowBoard")).not_to_contain_text("先选择一个章节")
        expect(page.locator("#chapterContext")).to_be_visible()
        expect(page.get_by_role("button", name="模型与技能")).to_be_visible()
        sidebar_overflow = page.locator(".sidebar-scroll").evaluate(
            "element => element.scrollWidth - element.clientWidth"
        )
        assert sidebar_overflow <= 1

        page.get_by_role("button", name="模型与技能").click()
        expect(page.locator("#providerList")).to_be_visible()
        expect(page.get_by_role("button", name="角色知识库")).to_be_visible()
        page.get_by_role("button", name="角色知识库").click()
        expect(page.locator("#characterList")).to_be_visible()

        browser.close()


def test_task_flow_renders_persisted_task_and_run_nodes(live_server: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page.goto(live_server, wait_until="networkidle")
        page.locator("#newTaskBtn").click()
        dialog = page.get_by_role("dialog", name="新建写作任务")
        dialog.get_by_label("任务目标").fill("浏览器原型回归写作任务")
        dialog.get_by_role("button", name="创建任务").click()

        task = page.locator("[data-task-node]").filter(
            has_text="浏览器原型回归写作任务"
        )
        expect(task).to_be_visible()
        expect(page.locator("#taskList")).to_be_hidden()
        expect(page.get_by_text("项目全部任务", exact=True)).to_be_visible()
        task.get_by_role("button", name="运行").click()
        expect(page.locator("[data-run-node]").first).to_be_visible(timeout=15000)
        expect(page.locator("#workflowLegend")).to_be_visible()
        page.locator("#closeTaskBtn").click()
        task.get_by_role("button", name="详情").click()
        expect(page.locator("#taskDialog")).to_be_visible()
        browser.close()


def test_assistant_tools_remain_accessible_at_tablet_width(live_server: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 860, "height": 764})
        page.goto(live_server, wait_until="networkidle")

        expect(page.locator(".assistant")).to_be_visible()
        page.get_by_role("button", name="AI 编辑").click()
        expect(page.locator("#aiResult")).to_be_visible()
        document_overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        tab_overflow = page.locator(".tabs").evaluate(
            "element => element.scrollWidth - element.clientWidth"
        )
        assert document_overflow <= 1
        assert tab_overflow <= 1

        page.locator("#aiInstruction").fill("继续写一段悬疑情节")
        page.locator('[data-ai="continue"]').click()
        expect(page.locator("#replaceAiBtn")).to_be_enabled(timeout=10000)
        expect(page.locator("#aiResult")).to_contain_text("演示续写")
        result_bottom = page.locator("#aiResult").evaluate(
            "element => element.getBoundingClientRect().bottom"
        )
        assert result_bottom <= 765

        page.get_by_role("button", name="模型与技能").click()
        expect(page.locator("#newProviderBtn")).to_be_visible()
        page.get_by_role("button", name="角色知识库").click()
        expect(page.locator("#addCharacterBtn")).to_be_visible()

        browser.close()


def test_project_creation_uses_accessible_workbench_dialog(live_server: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.on("dialog", lambda dialog: dialog.dismiss())
        page.goto(live_server, wait_until="networkidle")

        page.get_by_role("button", name="新建作品").click()

        dialog = page.get_by_role("dialog", name="新建作品")
        expect(dialog).to_be_visible(timeout=1000)
        dialog.get_by_label("作品名称").fill("表单测试作品")
        dialog.get_by_label("作品类型").fill("悬疑")
        dialog.get_by_label("作品简介").fill("浏览器表单回归。")
        dialog.get_by_role("button", name="创建作品").click()

        expect(page.locator("#projectTitle")).to_contain_text("表单测试作品")
        page.locator("#newProjectBtn").click()
        cancelled_dialog = page.get_by_role("dialog", name="新建作品")
        cancelled_dialog.get_by_label("作品名称").fill("不应创建的作品")
        cancelled_dialog.get_by_label("作品名称").press("Escape")
        expect(cancelled_dialog).to_be_hidden()
        expect(page.locator("#newProjectBtn")).to_be_focused()
        expect(page.locator("#projectSelect")).not_to_contain_text("不应创建的作品")
        browser.close()


def test_project_delete_uses_cancellable_workbench_confirmation(live_server: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.on("dialog", lambda dialog: dialog.dismiss())
        page.goto(live_server, wait_until="networkidle")
        page.locator("#newProjectBtn").click()
        form_dialog = page.get_by_role("dialog", name="新建作品")
        form_dialog.get_by_label("作品名称").fill("确认框测试作品")
        form_dialog.get_by_role("button", name="创建作品").click()

        page.locator("#deleteProjectBtn").click()
        confirm_dialog = page.get_by_role("dialog", name="删除作品")
        expect(confirm_dialog).to_be_visible(timeout=1000)
        expect(confirm_dialog).to_contain_text("确认框测试作品")
        confirm_dialog.get_by_role("button", name="取消", exact=True).click()
        expect(page.locator("#projectSelect")).to_contain_text("确认框测试作品")

        page.locator("#deleteProjectBtn").click()
        page.get_by_role("dialog", name="删除作品").get_by_role(
            "button", name="删除作品"
        ).click()
        expect(page.locator("#projectSelect")).not_to_contain_text("确认框测试作品")
        browser.close()


def test_chapter_creation_uses_workbench_dialog_and_required_validation(
    live_server: str,
) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.on("dialog", lambda dialog: dialog.dismiss())
        page.goto(live_server, wait_until="networkidle")

        page.get_by_role("button", name="新章节").click()

        dialog = page.get_by_role("dialog", name="新建章节")
        expect(dialog).to_be_visible(timeout=1000)
        expect(dialog.get_by_label("章节标题")).to_be_focused()
        dialog.get_by_label("章节标题").fill("")
        dialog.get_by_role("button", name="创建章节").click()
        expect(dialog.locator("[aria-invalid='true']")).to_have_count(1)
        assert dialog.locator("[aria-invalid='true']").get_attribute(
            "aria-describedby"
        )
        expect(dialog.locator("[aria-invalid='true']")).to_be_focused()
        expect(dialog.get_by_role("alert")).to_contain_text("必填")

        dialog.get_by_label("章节标题").fill("回归章节")
        dialog.get_by_role("button", name="创建章节").click()
        expect(page.locator("#chapterList")).to_contain_text("回归章节")

        page.get_by_role("button", name="AI 编辑").click()
        page.locator("#editor").fill("第一版正文。")
        page.wait_for_timeout(1100)
        expect(page.locator("#saveState")).to_contain_text("已保存")
        page.locator("#editor").fill("第二版正文。")
        page.wait_for_timeout(1100)
        expect(page.locator("#saveState")).to_contain_text("已保存")
        page.locator("#historyBtn").click()
        expect(page.locator("#historyDialog")).to_be_visible()
        # Newest first: v3 is the second edit, v2 is the first saved edit.
        first_version = page.locator(".history-item").nth(1)
        first_version.get_by_role("button", name="恢复").click()
        restore_confirmation = page.get_by_role("dialog", name="恢复章节版本")
        restore_confirmation.get_by_role("button", name="取消", exact=True).click()
        expect(page.locator("#editor")).to_have_value("第二版正文。")

        first_version.get_by_role("button", name="恢复").click()
        page.get_by_role("dialog", name="恢复章节版本").get_by_role(
            "button", name="恢复版本"
        ).click()
        expect(page.locator("#editor")).to_have_value("第一版正文。")
        browser.close()


def test_writing_task_uses_dialog_and_persists_approved_revision(live_server: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.on("dialog", lambda dialog: dialog.dismiss())
        page.goto(live_server, wait_until="networkidle")
        project_id = page.locator("#projectSelect").input_value()
        chapters = page.request.get(
            f"{live_server}/api/projects/{project_id}/chapters"
        ).json()
        chapter_id = chapters[0]["id"]
        versions_before = page.request.get(
            f"{live_server}/api/chapters/{chapter_id}/versions"
        ).json()

        page.get_by_role("button", name="章节任务流线").click()
        page.locator("#newTaskBtn").click()

        form_dialog = page.get_by_role("dialog", name="新建写作任务")
        expect(form_dialog).to_be_visible(timeout=1000)
        form_dialog.get_by_label("任务目标").fill("揭示一条新的悬疑线索")
        form_dialog.get_by_label("补充要求").fill("保持当前视角，不新增人物。")
        skills_field = form_dialog.get_by_label("本次使用的 Skills")
        skill_values = skills_field.evaluate(
            "element => Array.from(element.options).map(option => option.value)"
        )
        assert skill_values
        skills_field.select_option([skill_values[0]])
        form_dialog.get_by_role("button", name="创建任务").click()
        task = page.locator("[data-task-node]").filter(
            has_text="揭示一条新的悬疑线索"
        )
        expect(task).to_be_visible()

        task.get_by_role("button", name="运行").click()
        approve_button = page.get_by_role("button", name="确认写入章节")
        expect(approve_button).to_be_enabled(timeout=10000)
        approve_button.click()

        approval_dialog = page.get_by_role("dialog", name="确认写入章节")
        expect(approval_dialog).to_be_visible(timeout=1000)
        approval_dialog.get_by_label("确认备注").fill("浏览器审批回归")
        approval_dialog.get_by_role("button", name="确认写入章节").click()
        expect(page.locator("#taskDialog")).to_be_hidden(timeout=5000)

        chapter = page.request.get(f"{live_server}/api/chapters/{chapter_id}").json()
        versions_after = page.request.get(
            f"{live_server}/api/chapters/{chapter_id}/versions"
        ).json()
        assert "演示续写" in chapter["content"]
        assert len(versions_after) == len(versions_before) + 1

        page.locator("#newTaskBtn").click()
        reject_form = page.get_by_role("dialog", name="新建写作任务")
        reject_form.get_by_label("任务目标").fill("测试退回路径")
        reject_form.get_by_role("button", name="创建任务").click()
        rejected_task = page.locator("[data-task-node]").filter(
            has_text="测试退回路径"
        )
        expect(rejected_task).to_be_visible()
        task_count = len(page.request.get(
            f"{live_server}/api/projects/{project_id}/tasks"
        ).json())
        rejected_task.get_by_role("button", name="运行").click()
        reject_button = page.locator("#taskDialog").get_by_role(
            "button", name="退回", exact=True
        )
        expect(reject_button).to_be_enabled(timeout=10000)
        reject_button.click()
        reject_dialog = page.get_by_role("dialog", name="退回写作任务")
        reject_dialog.get_by_role("button", name="退回任务").click()
        expect(reject_dialog.locator("[aria-invalid='true']")).to_have_count(1)
        reject_dialog.get_by_label("退回原因").fill("线索揭示得太早，请延后。")
        reject_dialog.get_by_role("button", name="退回任务").click()
        expect(page.locator("#taskDialog")).to_be_hidden(timeout=5000)
        tasks_after = page.request.get(
            f"{live_server}/api/projects/{project_id}/tasks"
        ).json()
        assert len(tasks_after) == task_count
        assert tasks_after[0]["status"] == "rejected"
        chapter_after_rejection = page.request.get(
            f"{live_server}/api/chapters/{chapter_id}"
        ).json()
        assert chapter_after_rejection["content"] == chapter["content"]
        browser.close()


def test_content_preflight_errors_use_workbench_notice(live_server: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.on("dialog", lambda dialog: dialog.dismiss())
        page.goto(live_server, wait_until="networkidle")

        page.get_by_role("button", name="章节任务流线").click()
        page.locator("#preflightContentRepoBtn").click()

        notice = page.get_by_role("dialog", name="内容库预检未通过")
        expect(notice).to_be_visible(timeout=1000)
        expect(notice).to_contain_text("内容库预检未通过")
        notice.get_by_role("button", name="知道了").click()
        expect(notice).to_be_hidden()
        browser.close()


def test_memory_skill_character_world_and_repository_forms(live_server: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(live_server, wait_until="networkidle")
        project_id = page.locator("#projectSelect").input_value()

        page.get_by_role("button", name="项目记忆").click()
        page.locator("#addMemoryBtn").click()
        dialog = page.get_by_role("dialog", name="新建作品记忆")
        dialog.get_by_label("记忆标题").fill("回归记忆")
        dialog.get_by_label("记忆内容").fill("主角曾见过这枚徽章。")
        dialog.get_by_label("立即确认这条记忆").check()
        dialog.get_by_role("button", name="创建记忆").click()
        expect(page.locator("#memoryList")).to_contain_text("回归记忆")
        memories = page.request.get(
            f"{live_server}/api/projects/{project_id}/memories"
        ).json()
        memory = next(item for item in memories if item["title"] == "回归记忆")
        assert memory["confirmed"] == 1

        page.request.patch(
            f"{live_server}/api/memories/{memory['id']}",
            data={"content": "主角曾见过这枚旧徽章。"},
        )
        page.reload(wait_until="networkidle")
        page.get_by_role("button", name="项目记忆").click()
        memory_card = page.locator("#memoryList .info-card").filter(
            has_text="回归记忆"
        )
        memory_card.get_by_role("button", name="版本").click()
        version_dialog = page.get_by_role("dialog", name="恢复记忆版本")
        expect(version_dialog.get_by_label("历史版本")).to_be_visible()
        version_dialog.get_by_label("历史版本").select_option("1")
        version_dialog.get_by_role("button", name="恢复版本").click()
        expect(page.locator("#memoryList")).to_contain_text("主角曾见过这枚徽章。")

        page.get_by_role("button", name="技法知识库").click()
        page.locator("#addSkillBtn").click()
        skill_dialog = page.get_by_role("dialog", name="新建写作 Skill")
        skill_dialog.get_by_label("技能名称").fill("悬疑线索")
        skill_dialog.get_by_label("技能正文 / 执行规则").fill("每章至少埋下一条可验证线索。")
        skill_dialog.get_by_role("button", name="创建 Skill").click()
        skill_card = page.locator("#skillList .info-card").filter(has_text="悬疑线索")
        expect(skill_card).to_be_visible()
        skill_card.get_by_role("button", name="新版本").click()
        publish_dialog = page.get_by_role("dialog", name="发布 悬疑线索 的新版本")
        publish_dialog.get_by_label("技能正文 / 执行规则").fill("线索必须在后文得到回应。")
        publish_dialog.get_by_label("版本说明").fill("加强回收要求")
        publish_dialog.get_by_role("button", name="发布版本").click()
        expect(skill_card).to_contain_text("v2")
        skill_card.get_by_role("button", name="历史").click()
        restore_skill_dialog = page.get_by_role("dialog", name="恢复 悬疑线索 的版本")
        restore_skill_dialog.get_by_label("历史版本").select_option("1")
        restore_skill_dialog.get_by_role("button", name="恢复版本").click()
        expect(skill_card).to_contain_text("v3")

        page.get_by_role("button", name="角色知识库").click()
        page.locator("#addCharacterBtn").click()
        character_dialog = page.get_by_role("dialog", name="新建人物卡")
        character_dialog.get_by_label("人物名").fill("林澈")
        character_dialog.get_by_label("角色定位").fill("记者")
        character_dialog.get_by_label("人物简介").fill("追查旧案的调查记者。")
        character_dialog.get_by_label("标签").fill("主角，调查")
        character_dialog.get_by_role("button", name="创建人物卡").click()
        expect(page.locator("#characterList")).to_contain_text("林澈")

        page.get_by_role("button", name="小说资料库").click()
        page.locator("#addWorldBtn").click()
        world_dialog = page.get_by_role("dialog", name="新建世界设定")
        world_dialog.get_by_label("设定名称").fill("旧城区档案馆")
        world_dialog.get_by_label("分类").fill("地点")
        world_dialog.get_by_label("设定内容").fill("每周一闭馆，地下库房需双人进入。")
        world_dialog.get_by_role("button", name="创建设定").click()
        expect(page.locator("#worldList")).to_contain_text("旧城区档案馆")

        page.get_by_role("button", name="章节任务流线").click()
        page.locator("#linkContentRepoBtn").click()
        repo_dialog = page.get_by_role("dialog", name="绑定作品内容库")
        repo_dialog.get_by_label("作品库目录 slug").fill("browser-regression")
        repo_dialog.get_by_role("button", name="保存绑定").click()
        expect(page.locator("#contentRepoStatus")).to_contain_text("browser-regression")
        browser.close()


def test_provider_and_ai_replace_confirmations_are_cancellable(live_server: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(live_server, wait_until="networkidle")
        project_id = page.locator("#projectSelect").input_value()
        chapter_id = page.request.get(
            f"{live_server}/api/projects/{project_id}/chapters"
        ).json()[0]["id"]
        page.get_by_role("button", name="模型与技能").click()
        page.locator("#newProviderBtn").click()
        page.locator("#providerName").fill("Dialog Regression Provider")
        page.locator("#saveProviderBtn").click()
        provider = page.locator("#providerList .provider-card").filter(
            has_text="Dialog Regression Provider"
        )
        expect(provider).to_be_visible()
        provider.get_by_role("button", name="删除").click()
        confirmation = page.get_by_role("dialog", name="删除 Provider")
        confirmation.get_by_role("button", name="取消", exact=True).click()
        expect(provider).to_be_visible()
        provider.get_by_role("button", name="删除").click()
        page.get_by_role("dialog", name="删除 Provider").get_by_role(
            "button", name="删除 Provider"
        ).click()
        expect(provider).to_have_count(0)

        page.get_by_role("button", name="AI 编辑").click()
        original_content = page.locator("#editor").input_value()
        versions_before_replacement = page.request.get(
            f"{live_server}/api/chapters/{chapter_id}/versions"
        ).json()
        page.locator("#aiInstruction").fill("补一段短续写")
        page.locator('[data-ai="continue"]').click()
        expect(page.locator("#replaceAiBtn")).to_be_enabled(timeout=10000)
        page.locator("#replaceAiBtn").click()
        page.get_by_role("dialog", name="替换章节正文").get_by_role(
            "button", name="取消", exact=True
        ).click()
        expect(page.locator("#editor")).to_have_value(original_content)
        page.locator("#replaceAiBtn").click()
        page.get_by_role("dialog", name="替换章节正文").get_by_role(
            "button", name="替换正文"
        ).click()
        expect(page.locator("#editor")).not_to_have_value(original_content)
        page.wait_for_timeout(1100)
        expect(page.locator("#saveState")).to_contain_text("已保存")
        saved_content = page.locator("#editor").input_value()
        versions_after_replacement = page.request.get(
            f"{live_server}/api/chapters/{chapter_id}/versions"
        ).json()
        assert len(versions_after_replacement) > len(versions_before_replacement)
        page.reload(wait_until="networkidle")
        expect(page.locator("#editor")).to_have_value(saved_content)
        browser.close()


def test_workbench_exposes_live_task_progress_ui() -> None:
    source = Path("app/static/app.js").read_text(encoding="utf-8")
    styles = Path("app/static/styles.css").read_text(encoding="utf-8")

    for marker in [
        "renderLiveTaskProgress",
        "startTaskPolling",
        "自动刷新中 · 约每 1.2 秒更新",
        "实际模型：",
        "GLM 深审 · 连续性 / 剧情 / 证据链",
    ]:
        assert marker in source

    for marker in [".task-progress", ".progress-run", ".live-indicator.is-live"]:
        assert marker in styles
