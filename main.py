# -*- coding: utf-8 -*-
import os
import sys
import time
import random
import requests
import re
import subprocess

from xvfbwrapper import Xvfb
from DrissionPage import ChromiumPage, ChromiumOptions

from cf_turnstile_helper import (
    detect_cloudflare_challenge,
    is_turnstile_present,
    handle_turnstile,
)


# ==============================================================================
# Telegram
# ==============================================================================
def send_tg_message(token, chat_id, message):
    if not token or not chat_id:
        print("未配置 TG_TOKEN 或 TG_CHAT_ID，跳过通知。")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": str(message), "parse_mode": "None"}
    try:
        requests.post(url, json=payload, timeout=10)
        print("✅ Telegram 通知发送成功")
    except Exception as e:
        print(f"❌ Telegram 通知失败: {e}")


def send_tg_file(token, chat_id, file_path):
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendDocument"
        with open(file_path, "rb") as f:
            requests.post(url, data={"chat_id": chat_id}, files={"document": f}, timeout=20)
        print(f"📎 已发送文件: {file_path}")
    except Exception as e:
        print(f"❌ 发送文件失败: {e}")


def debug_dump(page, tg_token, tg_chat_id, name):
    """保存截图 + HTML + 自动发送图片到 TG。"""
    try:
        html_file = f"{name}.html"
        img_file = f"{name}.png"

        with open(html_file, "w", encoding="utf-8") as f:
            f.write(page.html or "")

        page.get_screenshot(path=img_file, full_page=True)
        print(f"🧪 调试文件已生成: {name}")

        send_tg_file(tg_token, tg_chat_id, img_file)
    except Exception as e:
        print(f"❌ debug_dump 失败: {e}")


# ==============================================================================
# 输入辅助
# ==============================================================================
class HumanTyper:
    @staticmethod
    def type(ele, text):
        ele.click()
        try:
            ele.clear()
        except Exception:
            pass
        for c in str(text):
            ele.input(c, clear=False)
            time.sleep(random.uniform(0.05, 0.2))


# ==============================================================================
# Cloudflare Turnstile 适配
# ==============================================================================
class _TurnstileAdapter:
    """把 DrissionPage page 适配成 cf_turnstile_helper 需要的 sb 接口。"""

    def __init__(self, page):
        self.page = page

    def execute_script(self, script):
        return self.page.run_js(script)

    def get_page_source(self):
        return self.page.html or ""

    def get_title(self):
        try:
            return self.page.title or ""
        except Exception:
            return ""


def _activate_window():
    for cls in ["chrome", "chromium", "Chromium", "Chrome", "google-chrome"]:
        try:
            r = subprocess.run(
                ["xdotool", "search", "--onlyvisible", "--class", cls],
                capture_output=True,
                text=True,
                timeout=3,
            )
            wids = [w for w in r.stdout.strip().split("\n") if w.strip()]
            if wids:
                subprocess.run(
                    ["xdotool", "windowactivate", "--sync", wids[0]],
                    timeout=3,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(0.2)
                return
        except Exception:
            pass


def _xdotool_click(x, y):
    _activate_window()
    try:
        subprocess.run(["xdotool", "mousemove", "--sync", str(int(x)), str(int(y))], timeout=3, stderr=subprocess.DEVNULL)
        time.sleep(0.12)
        subprocess.run(["xdotool", "click", "1"], timeout=2, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _vps8_turnstile_container_click(page):
    """VPS8 特化兜底：基于 .cf-turnstile 容器定位点击（适配 closed shadow root）。"""
    try:
        info = page.run_js(
            """
            (() => {
                const host = document.querySelector('.cf-turnstile') || document.querySelector('[class*="turnstile"]');
                if (!host) return null;
                const r = host.getBoundingClientRect();
                if (!r || r.width <= 0 || r.height <= 0) return null;
                const sx = window.screenX || 0;
                const sy = window.screenY || 0;
                const bar = Math.max(0, (window.outerHeight || 0) - (window.innerHeight || 0));
                return {
                    viewportX: Math.round(r.left + Math.min(35, Math.max(18, r.width * 0.12))),
                    viewportY: Math.round(r.top + r.height / 2),
                    absX: Math.round(sx + r.left + Math.min(35, Math.max(18, r.width * 0.12))),
                    absY: Math.round(sy + bar + r.top + r.height / 2),
                    width: Math.round(r.width),
                    height: Math.round(r.height),
                };
            })();
            """
        )
    except Exception:
        info = None

    if not info:
        print("[cf][vps8-fallback] .cf-turnstile container not found")
        return False

    print(f"[cf][vps8-fallback] click at ({info['absX']},{info['absY']}) size=({info['width']}x{info['height']})")
    _xdotool_click(info["absX"], info["absY"])
    return True


def _vps8_turnstile_token_ready(page):
    try:
        return bool(
            page.run_js(
                """
                (() => {
                    const i = document.querySelector('input[name="cf-turnstile-response"]');
                    return !!(i && i.value && i.value.length > 20);
                })();
                """
            )
        )
    except Exception:
        return False


def _vps8_turnstile_fallback(page, stage_name):
    for attempt in range(6):
        if _vps8_turnstile_token_ready(page):
            print(f"[cf][vps8-fallback] solved before click (attempt {attempt + 1})")
            return True

        clicked = _vps8_turnstile_container_click(page)
        if not clicked:
            time.sleep(1.0)
            continue

        for _ in range(8):
            time.sleep(0.5)
            if _vps8_turnstile_token_ready(page):
                print(f"[cf][vps8-fallback] solved after click (attempt {attempt + 1})")
                return True

        print(f"[cf][vps8-fallback] attempt {attempt + 1} failed")

    print(f"[cf][vps8-fallback] {stage_name} failed after 6 attempts")
    return False


def solve_turnstile_if_needed(page, stage_name, tg_token, tg_chat_id):
    sb = _TurnstileAdapter(page)

    try:
        detected = detect_cloudflare_challenge(sb) or is_turnstile_present(sb)
    except Exception as e:
        print(f"[cf] {stage_name}: 检测异常: {e}")
        detected = False

    if not detected:
        print(f"[cf] {stage_name}: 未检测到 Turnstile，跳过")
        return True

    print(f"[cf] {stage_name}: 检测到 Turnstile，开始处理")
    ok = handle_turnstile(sb)
    if not ok:
        print(f"[cf] {stage_name}: 通用 helper 失败，尝试 VPS8 特化兜底")
        ok = _vps8_turnstile_fallback(page, stage_name)
    if ok:
        print(f"[cf] {stage_name}: Turnstile 通过")
        return True

    msg = f"❌ {stage_name} Turnstile 验证失败"
    send_tg_message(tg_token, tg_chat_id, msg)
    debug_dump(page, tg_token, tg_chat_id, f"{stage_name}_turnstile_failed")
    return False


# ==============================================================================
# 工具
# ==============================================================================
def extract_points(html):
    text = html or ""
    patterns = [
        r"当前积分\s*[:：]?\s*<strong>(\d+)</strong>",
        r"当前积分\s*[:：]?\s*(\d+)",
        r"积分\s*[:：]?\s*(\d+)",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


# ==============================================================================
# 主逻辑
# ==============================================================================
def vps8_checkin(url, proxy_url=None):
    tg_token = os.getenv("TG_TOKEN")
    tg_chat_id = os.getenv("TG_CHAT_ID")

    vdisplay = Xvfb(width=1280, height=720)
    vdisplay.start()

    success = False
    msg = ""
    page = None

    try:
        co = ChromiumOptions()
        co.set_browser_path('/usr/bin/google-chrome')
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-dev-shm-usage')
        co.headless(False)

        # 可选代理
        if proxy_url:
            try:
                co.set_proxy(proxy_url)
            except Exception:
                co.set_argument('--proxy-server', proxy_url)

        page = ChromiumPage(co)

        print("🌐 打开页面")
        page.get(url)
        time.sleep(8)

        # =========================
        # 登录前 Turnstile
        # =========================
        if not solve_turnstile_if_needed(page, "login", tg_token, tg_chat_id):
            return False, "❌ 登录前 Turnstile 验证失败"

        # =========================
        # 登录流程
        # =========================
        print("🔐 开始登录")
        send_tg_message(tg_token, tg_chat_id, "🔐 VPS8 签到程序开始登录")

        email = os.getenv("VPS8_USERNAME")
        password = os.getenv("VPS8_PASSWORD")
        if not email or not password:
            return False, "❌ 未配置 VPS8_USERNAME / VPS8_PASSWORD"

        email_input = page.ele('#email', timeout=6)
        password_input = page.ele('#password', timeout=6)
        if not email_input or not password_input:
            debug_dump(page, tg_token, tg_chat_id, "login_input_missing")
            return False, "❌ 找不到登录输入框"

        HumanTyper.type(email_input, email)
        HumanTyper.type(password_input, password)

        btn = page.ele('xpath://button[@type="submit"]', timeout=6)
        if not btn:
            debug_dump(page, tg_token, tg_chat_id, "login_button_missing")
            return False, "❌ 找不到登录按钮"

        btn.click()
        time.sleep(8)

        if "login" not in (page.url or "").lower():
            success = True
            msg = "🎉 登录成功"
            send_tg_message(tg_token, tg_chat_id, "🎉 VPS8 账号登录成功")
        else:
            debug_dump(page, tg_token, tg_chat_id, "login_failed")
            return False, "❌ 登录失败"

        # =========================
        # 进入签到页
        # =========================
        print("➡️ 进入签到页面")
        page.get("https://vps8.zz.cd/points/signin")
        time.sleep(8)
        send_tg_message(tg_token, tg_chat_id, "➡️ 进入签到处理页面")
        debug_dump(page, tg_token, tg_chat_id, "signin_page")

        # =========================
        # 签到前 Turnstile
        # =========================
        if not solve_turnstile_if_needed(page, "signin", tg_token, tg_chat_id):
            return False, "❌ 签到前 Turnstile 验证失败"

        html_now = page.html or ""
        if "已签到" in html_now:
            points = extract_points(html_now)
            msg = f"✅ 今天已签到，当前积分：{points or '未知'}"
            send_tg_message(tg_token, tg_chat_id, msg)
            debug_dump(page, tg_token, tg_chat_id, "already_signed")
            return True, msg

        print("🖱️ 点击签到按钮")
        btn = page.ele('#points-signin-submit', timeout=6)
        if not btn:
            debug_dump(page, tg_token, tg_chat_id, "signin_button_missing")
            return False, "❌ 找不到签到按钮"

        try:
            btn.click()
        except Exception:
            btn.click(by_js=True)

        time.sleep(6)

        html = page.html or ""
        if "已签到" in html or "签到成功" in html:
            points = extract_points(html)
            msg = f"✅ 签到成功，当前积分：{points or '未知'}"
            send_tg_message(tg_token, tg_chat_id, msg)
            debug_dump(page, tg_token, tg_chat_id, "signin_success")
            return True, msg

        debug_dump(page, tg_token, tg_chat_id, "signin_unknown")
        return True, "⚠️ 无法确认签到状态（请看截图）"

    except Exception as e:
        msg = f"🚨 异常: {str(e)[:200]}"

    finally:
        if page:
            try:
                page.quit()
            except Exception:
                pass
        vdisplay.stop()

    return success, msg


# ==============================================================================
# 入口
# ==============================================================================
if __name__ == "__main__":
    url = os.getenv("RENEW_URL")
    tg_token = os.getenv("TG_TOKEN")
    tg_chat_id = os.getenv("TG_CHAT_ID")
    proxy_url = os.getenv("ALL_PROXY") or os.getenv("all_proxy") or ""

    if not url:
        print("❌ 缺少 RENEW_URL")
        sys.exit(1)

    ok, msg = vps8_checkin(url, proxy_url=proxy_url)
    send_tg_message(tg_token, tg_chat_id, msg)

    if not ok:
        sys.exit(1)
