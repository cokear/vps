import os
import re
import sys
import time
import platform
import traceback
import requests

from pyvirtualdisplay import Display
from seleniumbase import SB


LOGIN_URL = os.getenv("LOGIN_URL", "https://vps8.zz.cd/login")
SIGNIN_URL = os.getenv("SIGNIN_URL", "https://vps8.zz.cd/points/signin")
SS_DIR = os.getenv("SS_DIR", "screenshots")
IP_CHECK_URL = os.getenv("IP_CHECK_URL", "https://api.ipify.org?format=json")


def log(level, msg):
    print(f"[{level}] {msg}")


def mask_ip(ip):
    value = (ip or "").strip()
    if not value:
        return "unknown"

    if ":" in value:
        parts = value.split(":")
        if len(parts) >= 2:
            return ":".join(parts[:-2] + ["*", "*"])
        return "*:*"

    parts = value.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.*.*"
    return value[:-2] + "**" if len(value) >= 2 else "**"


def mask_proxy(proxy):
    p = (proxy or "").strip()
    if not p:
        return "<none>"
    m = re.match(r"^([a-zA-Z0-9+.-]+://)([^@]+)@(.+)$", p)
    if m:
        return f"{m.group(1)}***@{m.group(3)}"
    return p


def detect_exit_ip(proxy=None):
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        r = requests.get(IP_CHECK_URL, proxies=proxies, timeout=20)
        r.raise_for_status()
        ip = str(r.json().get("ip", "")).strip()
        if not ip:
            return False, "empty ip"
        return True, ip
    except Exception as e:
        return False, str(e)


def send_tg_photo(token, chat_id, path, caption=""):
    if not (token and chat_id and os.path.exists(path)):
        return
    try:
        with open(path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                files={"photo": f},
                data={"chat_id": chat_id, "caption": caption},
                timeout=30,
            )
        log("INFO", "Telegram 截图发送成功")
    except Exception as e:
        log("ERROR", f"Telegram 截图发送失败: {e}")


def screenshot(sb, name):
    os.makedirs(SS_DIR, exist_ok=True)
    path = os.path.join(SS_DIR, f"{name}.png")
    try:
        sb.save_screenshot(path)
        log("INFO", f"截图: {name}")
        return path
    except Exception as e:
        log("ERROR", f"截图失败 ({name}): {e}")
        return ""


def dump_html(sb, name):
    os.makedirs(SS_DIR, exist_ok=True)
    try:
        with open(os.path.join(SS_DIR, f"{name}.html"), "w", encoding="utf-8") as f:
            f.write(sb.get_page_source())
    except Exception:
        pass


def finish(sb, tg_token, tg_chat_id, name, caption):
    dump_html(sb, name)
    img = screenshot(sb, name)
    if img:
        send_tg_photo(tg_token, tg_chat_id, img, caption)


def parse_account(raw):
    value = (raw or "").strip().replace("：", ":")
    index = value.find(":")
    if index <= 0 or index == len(value) - 1:
        raise ValueError("vps8_ACCOUNTS 格式错误，应为 邮箱:密码")
    return value[:index].strip(), value[index + 1 :].strip()


def get_account_from_env():
    raw = (
        os.getenv("vps8_ACCOUNTS")
        or os.getenv("VPS8_ACCOUNTS")
        or ""
    ).strip()

    if raw:
        return parse_account(raw)

    username = (os.getenv("VPS8_USERNAME") or "").strip()
    password = (os.getenv("VPS8_PASSWORD") or "").strip()
    if username and password:
        return username, password

    raise ValueError("缺少账号信息：请设置 vps8_ACCOUNTS 或 VPS8_USERNAME/VPS8_PASSWORD")


def is_signed(html):
    match = re.search(r"今日签到状态：\s*([^\n<]+)", html)
    if match:
        status = match.group(1).strip()
        if status == "已签到":
            return True
        if status == "未签到":
            return False

    if "签到成功" in html and "今日签到状态" not in html:
        return True
    if "未签到" not in html and "当前连续签到" in html:
        return True
    return False


def extract_points(html):
    match = re.search(r"当前积分：\s*<strong>(\d+)</strong>", html)
    return match.group(1) if match else "未知"


def build_result_caption(account, result_text, before_points=None, current_points=None, fail_reason=None):
    lines = [
        "VPS8 每日签到",
        f"账号: {account}",
        f"签到结果: {result_text}",
    ]
    if before_points is not None:
        lines.append(f"签到前积分: {before_points}")
    if current_points is not None:
        lines.append(f"当前积分: {current_points}")
    if fail_reason:
        lines.append(f"失败原因: {fail_reason}")
    return "\n".join(lines)


def handle_turnstile(sb, scene="page", max_attempts=3):
    log("INFO", f"[{scene}] 开始处理 Turnstile 验证")
    sb.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)

    for attempt in range(max_attempts):
        log("INFO", f"[{scene}] Turnstile 尝试 {attempt + 1}/{max_attempts}")
        try:
            sb.uc_gui_click_captcha()
            log("INFO", f"[{scene}] 已调用 uc_gui_click_captcha")
        except Exception as e:
            log("WARN", f"[{scene}] uc_gui_click_captcha 失败: {e}")

        start = time.time()
        while time.time() - start < 20:
            token_ready = sb.execute_script(
                """
                var inp = document.querySelector('input[name="cf-turnstile-response"]');
                return !!(inp && inp.value && inp.value.length > 20);
                """
            )
            if token_ready:
                log("INFO", f"[{scene}] Turnstile 通过")
                screenshot(sb, f"turnstile_ok_{scene}")
                return True
            time.sleep(1)

        log("WARN", f"[{scene}] 当前尝试超时，重试...")
        sb.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

    log("ERROR", f"[{scene}] Turnstile 验证失败")
    screenshot(sb, f"turnstile_fail_{scene}")
    return False


def login(sb, email, password):
    log("INFO", "打开登录页")
    sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=8)
    time.sleep(5)
    screenshot(sb, "01_login_loaded")

    sb.wait_for_element_visible("#email", timeout=15)

    if not handle_turnstile(sb, "login"):
        return False, "登录验证失败"

    sb.clear("#email")
    sb.type("#email", email)
    sb.clear("#password")
    sb.type("#password", password)
    screenshot(sb, "02_form_filled")

    sb.click('button[type="submit"]')
    time.sleep(6)

    if "login" in sb.get_current_url().lower():
        return False, "登录失败，仍停留在登录页"

    screenshot(sb, "03_login_success")
    return True, None


def do_signin(sb):
    log("INFO", "打开签到页")
    sb.uc_open_with_reconnect(SIGNIN_URL, reconnect_time=8)
    time.sleep(5)
    screenshot(sb, "04_signin_loaded")

    sb.wait_for_element_visible("strong", timeout=10)

    html = sb.get_page_source()
    before_points = extract_points(html)
    if is_signed(html):
        return True, "今日已签到", before_points, before_points, None

    if not handle_turnstile(sb, "signin"):
        return False, "签到失败", before_points, before_points, "签到验证失败"

    sb.wait_for_element_visible("#points-signin-submit", timeout=10)
    sb.click("#points-signin-submit")
    time.sleep(3)

    for i in range(10):
        time.sleep(2)
        html = sb.get_page_source()
        if is_signed(html):
            current_points = extract_points(html)
            return True, "签到成功", before_points, current_points, None
        log("INFO", f"等待签到结果... ({i + 1})")

    current_points = extract_points(sb.get_page_source())
    return False, "签到失败", before_points, current_points, "未确认签到状态"


def vps8_checkin():
    tg_token = os.getenv("TG_BOT_TOKEN") or os.getenv("TG_TOKEN")
    tg_chat_id = os.getenv("TG_CHAT_ID")
    proxy = (os.getenv("PROXY") or "").strip()

    try:
        email, password = get_account_from_env()
    except Exception as e:
        return False, str(e)

    log("INFO", f"代理: {mask_proxy(proxy)}")

    ok_ip, ip_or_err = detect_exit_ip(proxy=proxy or None)
    if ok_ip:
        log("INFO", f"出口IP(脱敏): {mask_ip(ip_or_err)}")
    else:
        log("WARN", f"出口IP检测失败: {ip_or_err}")

    display = None
    if platform.system().lower() == "linux" and not os.environ.get("DISPLAY"):
        try:
            display = Display(visible=False, size=(1280, 720))
            display.start()
            log("INFO", "虚拟显示已启动")
        except Exception as e:
            return False, f"虚拟显示失败: {e}"

    try:
        sb_kwargs = dict(uc=True, test=True, locale="zh-CN", headless2=False)
        if proxy:
            sb_kwargs["proxy"] = proxy

        with SB(**sb_kwargs) as sb:
            ok, reason = login(sb, email, password)
            if not ok:
                finish(sb, tg_token, tg_chat_id, "login_failed", build_result_caption(email, "签到失败", fail_reason=reason))
                return False, reason

            success, result_text, before_points, current_points, fail_reason = do_signin(sb)
            finish(
                sb,
                tg_token,
                tg_chat_id,
                "signin_ok" if success else "signin_fail",
                build_result_caption(email, result_text, before_points, current_points, fail_reason),
            )
            return success, result_text if success else fail_reason
    except Exception as e:
        traceback.print_exc()
        return False, f"异常: {str(e)[:200]}"
    finally:
        if display:
            display.stop()


if __name__ == "__main__":
    ok, msg = vps8_checkin()
    log("INFO", msg)
    if not ok:
        sys.exit(1)
