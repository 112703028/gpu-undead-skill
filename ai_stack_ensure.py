"""確保 AI-Stack 專案裡有一個 GPU 容器;沒有的話自動建立。

用法:
    python ai_stack_ensure.py                # 檢查,不存在就建立
    python ai_stack_ensure.py --check-only   # 只檢查,不建立
    python ai_stack_ensure.py --dry-run      # 走完建立精靈但不按最後的送出
    python ai_stack_ensure.py --headed       # 顯示瀏覽器視窗(除錯用)
    python ai_stack_ensure.py --test-wizard  # 容器已存在時,測試建立精靈(不送出)

結束碼:
    0  容器已存在,什麼都沒做
    10 容器不存在,已建立
    11 容器不存在(--check-only)
    1  失敗(登入失敗、找不到按鈕等,截圖存在 logs/)

設定放在同資料夾的 .env,參考 .env.example。
"""
import argparse
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
LOGS = HERE / "logs"


def load_config():
    cfg = {}
    env_file = HERE / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    for k in list(cfg) + [k for k in os.environ if k.startswith("AI_STACK_")]:
        if k in os.environ:
            cfg[k] = os.environ[k]
    return cfg


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def shot(page, name):
    LOGS.mkdir(exist_ok=True)
    path = LOGS / f"{datetime.now():%Y%m%d_%H%M%S}_{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        log(f"截圖: {path}")
    except Exception:
        pass


def settle(page, ms=1500):
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        pass
    page.wait_for_timeout(ms)


def login(page, cfg):
    page.goto(cfg["AI_STACK_URL"], wait_until="networkidle", timeout=60000)
    if "/account/login" in page.url:
        page.fill("#account", cfg["AI_STACK_USER"])
        page.fill("#password", cfg["AI_STACK_PASS"])
        page.click("button[type=submit]:not([name=goToHome])")
        try:
            # 登入頁與首頁網址都含 /ai-stack/,以側邊欄選單出現當作真正登入完成
            page.wait_for_selector("text=機器學習專案", timeout=30000)
        except PWTimeout:
            raise RuntimeError("登入失敗,請檢查 .env 的帳號密碼")
    settle(page, 2000)
    log("登入成功")


def open_project(page, project, cfg):
    if "/account/login" in page.url:
        log("被登出了,重新登入")
        login(page, cfg)
    page.click("text=機器學習專案")
    settle(page)
    page.click("text=專案列表")
    settle(page)
    page.click(f"text={project}")
    page.wait_for_url(re.compile(r"project-detail"), timeout=30000)
    settle(page, 3000)


def container_state(page):
    """回傳容器列表文字(空字串代表沒有容器)。"""
    # 容器列表右上角分頁文字是 "1 - 1 of 1" 或 "0 of 0",等它出現代表資料載入完成
    page.wait_for_function(
        "() => /\\d+\\s*(-\\s*\\d+)?\\s*of\\s*\\d+/.test(document.body.innerText)",
        timeout=30000,
    )
    page.wait_for_timeout(1500)
    # 頁面上第一個分頁文字屬於容器列表,第二個是任務列表
    pager = page.locator("text=/\\d+\\s*of\\s*\\d+/").first.inner_text()
    count = int(re.search(r"of\s*(\d+)", pager).group(1))
    if count == 0:
        return ""
    rows = page.locator("table.table").first.locator("tbody tr")
    return " | ".join(re.sub(r"\s+", " ", rows.nth(i).inner_text()) for i in range(rows.count()))


def tab_enabled(page, name):
    tab = page.locator(f"[role=tab]:has-text('{name}')").first
    return tab.count() > 0 and tab.get_attribute("aria-disabled") != "true"


def print_connection_info(page, cfg):
    """到「容器管理 > 容器列表」讀 SSH 指令、Jupyter 連結與掛載並印出。
    連接埠每次重建都會變,所以每次都重新讀。容器剛建立時「服務資訊」分頁是停用的,
    要等容器進入運行中才會啟用,所以會等待(預設最多 180 秒,可用 AI_STACK_START_WAIT 調整)。
    讀不到只警告,不影響結束碼。"""
    try:
        page.locator("text=容器管理").first.click()
        page.wait_for_timeout(1000)
        page.locator("text=容器列表").first.click()
        settle(page, 3000)
        row = page.locator("table.table").first.locator("tbody tr").first
        deadline = time.time() + int(cfg.get("AI_STACK_START_WAIT", "180"))
        while True:
            if not tab_enabled(page, "內部掛載"):  # 分頁全停用代表沒有選到列
                row.locator("td").nth(1).click()
                page.wait_for_timeout(1500)
            if tab_enabled(page, "服務資訊"):
                break
            if time.time() > deadline:
                raise RuntimeError("容器還沒進入運行中,服務資訊分頁尚未啟用")
            log("容器還在啟動,等待中...")
            refresh = page.locator("button[name=refresh_btn]").first
            if refresh.count() and refresh.is_visible():
                refresh.click()
            page.wait_for_timeout(10000)

        page.locator("[role=tab]:has-text('服務資訊')").first.click()
        page.wait_for_timeout(3000)
        body = page.inner_text("body")
        ssh = re.search(r"ssh\s+\S+@\S+\s+-p\s+\d+", body)
        if not ssh:
            raise RuntimeError("服務資訊裡找不到 ssh 指令")
        print(f"SSH: {ssh.group(0)}", flush=True)
        jupyter = page.locator("a:has-text('連結')").first
        if jupyter.count():
            print(f"JUPYTER: {jupyter.get_attribute('href')}", flush=True)

        # 內部掛載:列出實際掛載,讓使用者(與 agent)確認資料路徑有沒有掛上
        page.locator("[role=tab]:has-text('內部掛載')").first.click()
        page.wait_for_timeout(2500)
        panel = page.locator("[role=tabpanel]", has_text="掛載路徑").first  # 頁面有多個面板,多數是空的
        if panel.count():
            # 表格欄位是「名稱 / 掛載路徑 / 唯讀」,取資料列轉成 名稱->路徑
            cells = [c.strip() for c in panel.locator("tbody td").all_inner_texts() if c.strip()]
            mounts = [f"{cells[i]} -> {cells[i + 1]}" for i in range(0, len(cells) - 2, 3)]
            print(f"MOUNT: {'; '.join(mounts) if mounts else '(沒有掛載)'}", flush=True)
    except Exception as e:
        log(f"警告: 讀不到連線資訊 ({type(e).__name__}: {str(e).splitlines()[0]})")
        shot(page, "connection_info")


def open_create_wizard(page, via_toolbar=False):
    if via_toolbar:
        # 容器列表工具列的「+」,容器已存在時也看得到(--test-wizard 用)
        page.locator("button[name=create]").first.click()
    else:
        page.locator("button[name=emptyStatesButton]:has-text('建立容器')").first.click()
    page.wait_for_url(re.compile(r"container-management/creator"), timeout=30000)
    settle(page)


def next_step(page):
    page.click("button:has-text('下一步')")
    page.wait_for_timeout(2500)


MOUNT_PREFIX = "/mnt/"  # 網站的掛載路徑輸入框前面固定有 /mnt/


def mount_storage(page, cfg):
    """步驟 3:勾選「掛載儲存裝置」,選儲存、填路徑、(選填)設為 Jupyter 工作目錄。"""
    sub_path = cfg["AI_STACK_MOUNT_PATH"].strip()[len(MOUNT_PREFIX):]
    storage = cfg.get("AI_STACK_MOUNT_STORAGE", "").strip()
    page.locator("xpath=//*[normalize-space(text())='掛載儲存裝置']/following::mat-checkbox[1]").click()
    page.wait_for_timeout(1500)
    page.locator("button:has-text('選擇儲存裝置')").first.click()
    dlg = page.locator("mat-dialog-container").first
    dlg.wait_for()
    page.wait_for_timeout(1500)

    rows = dlg.locator("tbody tr")
    if rows.count() == 0:
        raise RuntimeError("沒有可掛載的儲存裝置")
    row = rows.filter(has_text=storage).first if storage else rows.first
    if storage and rows.filter(has_text=storage).count() == 0:
        raise RuntimeError(f"找不到儲存裝置 {storage}(可用: {[re.sub(r'\s+', ' ', r) for r in rows.all_inner_texts()]})")
    name = re.sub(r"\s+", " ", row.inner_text()).strip()
    # 必須點名稱儲存格;點列上的核取方塊只會讓畫面打勾,網站內部不會真的選取
    row.locator("td").nth(1).click()
    dlg.locator("input[name=path]").wait_for(timeout=10000)
    dlg.locator("input[name=path]").fill(sub_path)
    if cfg.get("AI_STACK_MOUNT_JUPYTER_WORKSPACE", "0") == "1":
        dlg.locator("mat-slide-toggle").click()
    page.wait_for_timeout(500)
    dlg.locator("button:text-is('確認')").click()
    page.wait_for_timeout(2000)
    if page.locator("mat-dialog-container").count():
        raise RuntimeError("掛載對話框沒有關閉,可能有欄位未通過驗證")
    log(f"已設定掛載: {name} -> {MOUNT_PREFIX}{sub_path}")


def run_wizard(page, cfg, dry_run):
    # 步驟 1: 基本資訊 (起始時間預設「立即執行」、結束時間預設「不指定」)
    page.fill("input[type=text] >> nth=0", cfg.get("AI_STACK_CONTAINER_NAME", "work1"))
    next_step(page)

    # 步驟 2: 建立資源
    # 順序很重要:選鏡像會重置 GPU 的選取,所以先鏡像、密碼,最後才選 GPU
    image = cfg.get("AI_STACK_IMAGE", "25.10-py3")
    page.click("button:has-text('請選擇鏡像')")
    page.wait_for_timeout(1500)
    page.click(f"text={image}")
    page.click("mat-dialog-actions button:text-is('選擇')")
    page.wait_for_timeout(1500)
    ssh_pass = cfg.get("AI_STACK_SSH_PASS") or cfg["AI_STACK_PASS"]
    pw = page.locator("input[type=password]")
    pw.first.fill(ssh_pass)
    page.wait_for_timeout(800)  # 「再次確認密碼」欄位要等第一格輸入後才會出現
    if pw.count() < 2:
        raise RuntimeError("找不到「再次確認密碼」欄位")
    pw.nth(1).fill(ssh_pass)

    # GPU 型號 / CUDA / 數量是必填 radio,畫面上的 active 只是預設樣式,必須真的點選
    gpu_model = cfg.get("AI_STACK_GPU_MODEL", "7960-RTX3090")
    cuda = cfg.get("AI_STACK_CUDA", "12.4")
    count = cfg.get("AI_STACK_GPU_COUNT", "1")
    page.locator(rf"text=/^\s*{re.escape(gpu_model)}/").first.click()
    page.wait_for_timeout(800)
    page.locator(rf"text=/-{re.escape(cuda)}\s*$/").first.click()
    page.locator(rf"text=/^\s*{count} 片\s*$/").first.click()
    page.wait_for_timeout(800)
    unchecked = page.evaluate(
        "() => ['optgpuType','optcudaVersion','optgpuQty'].filter("
        "n => !Array.from(document.querySelectorAll(`input[name=${n}]`)).some(e => e.checked))"
    )
    if unchecked:
        raise RuntimeError(f"這些必填選項沒有被選到: {unchecked}")
    hint = page.locator("text=/目前最大可用量為/").first
    if hint.count():
        log(f"GPU 提示: {re.sub(r'\s+', ' ', hint.inner_text())}")
    next_step(page)
    if page.locator("text=啟用 GPU").first.is_visible():
        raise RuntimeError("第 2 步沒有通過(仍停在建立資源頁),可能有必填欄位未填")

    # 步驟 3: 進階設定(全是選填,直接按「下一步 | 建立」)
    if cfg.get("AI_STACK_MOUNT_PATH"):
        mount_storage(page, cfg)
    shot(page, "wizard_step3")
    log("已到精靈第 3 步")
    if dry_run:
        log("--dry-run:停在這裡,不送出")
        return
    page.locator("button:has-text('下一步 | 建立')").first.click()
    page.wait_for_timeout(3000)
    # 若跳出確認對話框就按確認
    dialog = page.locator("mat-dialog-container")
    if dialog.count() and dialog.first.is_visible():
        log(f"確認對話框: {re.sub(r'\s+', ' ', dialog.first.inner_text())[:120]}")
        dialog.first.locator("button").filter(has_text=re.compile("確認|確定|是|建立")).last.click()
        page.wait_for_timeout(3000)
    shot(page, "after_submit")
    log("已送出建立")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--test-wizard", action="store_true", help="跳過偵測,從工具列進入精靈並 dry-run(測試用)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    cfg = load_config()
    for k in ("AI_STACK_URL", "AI_STACK_PROJECT", "AI_STACK_USER", "AI_STACK_PASS"):
        if not cfg.get(k):
            log(f"缺少設定 {k}(請填 .env)")
            return 1
    mount = cfg.get("AI_STACK_MOUNT_PATH", "").strip()
    if mount and not (mount.startswith(MOUNT_PREFIX) and len(mount) > len(MOUNT_PREFIX)):
        log(f"AI_STACK_MOUNT_PATH 必須以 {MOUNT_PREFIX} 開頭且後面要有名稱,例如 /mnt/data(目前是 {mount!r})")
        return 2
    # 失敗(結束碼 1)時重試;重試一開始會重新偵測,所以不會重複建立容器
    rc = 1
    for attempt in range(1, 4):
        rc = run_once(args, cfg)
        if rc != 1:
            break
        if attempt < 3:
            log(f"第 {attempt} 次失敗,5 秒後重試")
            time.sleep(5)
    return rc


def run_once(args, cfg):
    project = cfg["AI_STACK_PROJECT"]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=cfg.get("AI_STACK_BROWSER", "msedge"), headless=not args.headed)
        ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        page.set_default_timeout(30000)
        try:
            login(page, cfg)
            open_project(page, project, cfg)
            if args.test_wizard:
                open_create_wizard(page, via_toolbar=True)
                run_wizard(page, cfg, dry_run=True)
                return 11
            state = container_state(page)
            if state:
                log(f"容器已存在,不需處理: {state}")
                print_connection_info(page, cfg)
                return 0
            log("容器不存在")
            if args.check_only:
                return 11
            open_create_wizard(page)
            run_wizard(page, cfg, args.dry_run)
            if args.dry_run:
                return 11
            # 送出後回專案頁確認容器真的出現
            for _ in range(6):
                page.wait_for_timeout(5000)
                page.goto(cfg["AI_STACK_URL"], wait_until="networkidle")  # 重載讓側邊欄回到初始狀態
                open_project(page, project, cfg)
                state = container_state(page)
                if state:
                    log(f"建立成功: {state}")
                    print_connection_info(page, cfg)
                    return 10
            raise RuntimeError("已送出建立,但 30 秒內容器列表仍是空的")
        except Exception as e:
            log(f"失敗: {type(e).__name__}: {e}")
            shot(page, "error")
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
