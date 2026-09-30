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
        expect(desktop.locator("#editor")).to_be_visible()
        expect(desktop.locator("#themeSelect")).to_be_visible()

        desktop.locator("#themeSelect").select_option("neo")
        expect(desktop.locator("html")).to_have_attribute("data-theme", "neo")
        desktop.reload(wait_until="networkidle")
        expect(desktop.locator("html")).to_have_attribute("data-theme", "neo")

        editor = desktop.locator("#editor")
        editor.fill("浏览器 E2E 自动保存测试。")
        expect(desktop.locator("#saveState")).to_contain_text("已保存", timeout=5000)
        desktop.reload(wait_until="networkidle")
        expect(desktop.locator("#editor")).to_have_value("浏览器 E2E 自动保存测试。")

        desktop.locator('[data-tab="tasks"]').click()
        expect(desktop.locator("#newTaskBtn")).to_be_visible()
        expect(desktop.locator("#preflightContentRepoBtn")).to_be_visible()
        expect(desktop.locator("#importContentRepoBtn")).to_be_visible()
        desktop.locator('[data-tab="memory"]').click()
        expect(desktop.locator("#addMemoryBtn")).to_be_visible()
        desktop.locator('[data-tab="skills"]').click()
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
