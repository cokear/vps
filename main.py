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
BROWSER_IP_PROBE_URLS = [
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
]


def log(level, msg):
    print(f"[{level}] {msg}")


def mask_ip(ip):
    value = (ip or "").strip()
    if not value:
        return "unknown"

    if ":" in value:  # IPv6
        parts = value.split(":")
        if len(parts) >= 2:
            return ":".join(parts[:-2] + ["*", "*"])
        return "*:*"

    parts = value.split(".")  # IPv4
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.*.*"
    return value[:-2] + "**" if len(value) >= 2 else "**"


def mask_proxy(proxy):
    p = (proxy or "").strip()
    if not p:
        return "<none>"
    m = re.match(r"^([a-zA-Z0-9+.-]+://)", p)
    if m:
        return f"{m.group(1)}***"
    return "***"


def extract_ip_from_text(text):
    if not text:
        return ""

    m4 = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)
    if m4:
        return m4.group(0)

    m6 = re.search(r"\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b", text)
    if m6:
        return m6.group(0)

    return ""


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


def send_tg_text(token, chat_id, text):
    if not (token and chat_id and text):
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text},
            timeout=30,
        )
        log("INFO", "Telegram 文本发送成功")
    except Exception as e:
        log("ERROR", f"Telegram 文本发送失败: {e}")


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
    path = os.path.join(SS_DIR, f"{name}.html")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(sb.get_page_source())
        log("INFO", f"HTML: {name}")
    except Exception:
        pass


def finish(sb, tg_token, tg_chat_id, name, caption):
    dump_html(sb, name)
    img = screenshot(sb, name)
    if img:
        send_tg_photo(tg_token, tg_chat_id, img, caption)


def parse_account(raw):
    value = (raw or "").strip().replace("：", ":")
    idx = value.find(":")
    if idx <= 0 or idx == len(value) - 1:
        raise ValueError("vps8_ACCOUNTS 格式错误，应为 邮箱:密码")
    return value[:idx].strip(), value[idx + 1:].strip()


def get_account_from_env():
    user = (os.getenv("VPS8_USERNAME") or "").strip()
    pwd = (os.getenv("VPS8_PASSWORD") or "").strip()
    if user and pwd:
        return user, pwd

    raw = (os.getenv("vps8_ACCOUNTS") or os.getenv("VPS8_ACCOUNTS") or "").strip()
    if raw:
        return parse_account(raw)

    raise ValueError("缺少账号信息：请设置 VPS8_USERNAME/VPS8_PASSWORD 或 vps8_ACCOUNTS")


def is_signed(html):
    m = re.search(r"今日签到状态：\s*([^\n<]+)", html)
    if m:
        status = m.group(1).strip()
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
    m = re.search(r"当前积分：\s*<strong>(\d+)</strong>", html)
    return m.group(1) if m else "未知"


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


def wait_any_visible(sb, selectors, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        for sel in selectors:
            try:
                if sb.is_element_visible(sel):
                    return sel
            except Exception:
                pass
        time.sleep(0.5)
    return None


def get_page_blob(sb):
    body_text = ""
    html = ""
    try:
        if sb.is_element_present("body"):
            body_text = sb.get_text("body") or ""
    except Exception:
        pass
    try:
        html = sb.get_page_source() or ""
    except Exception:
        pass
    return f"{body_text}\n{html}"


def detect_chrome_error(blob):
    checks = [
        ("ERR_EMPTY_RESPONSE", "ERR_EMPTY_RESPONSE"),
        ("ERR_TUNNEL_CONNECTION_FAILED", "ERR_TUNNEL_CONNECTION_FAILED"),
        ("ERR_PROXY_CONNECTION_FAILED", "ERR_PROXY_CONNECTION_FAILED"),
        ("This page isn", "Chrome 错误页"),
        ("didn't send any data", "目标站无响应"),
    ]
    for key, msg in checks:
        if key in blob:
            return msg
    return ""


def detect_browser_exit_ip(sb, timeout=20):
    last_err = "unknown"

    for url in BROWSER_IP_PROBE_URLS:
        try:
            sb.open(url)
            end = time.time() + timeout

            while time.time() < end:
                blob = get_page_blob(sb)
                err = detect_chrome_error(blob)
                if err:
                    return False, f"{url} -> {err}"

                ip = extract_ip_from_text(blob)
                if ip:
                    return True, ip

                time.sleep(1)

            last_err = f"{url} -> timeout/no ip"
        except Exception as e:
            last_err = f"{url} -> {e}"

    return False, last_err


def handle_turnstile(sb, scene="page", max_attempts=3):
    try:
        has_ts = sb.execute_script(
            "return !!document.querySelector('.cf-turnstile, iframe[src*=\"turnstile\"], input[name=\"cf-turnstile-response\"]');"
        )
    except Exception:
        has_ts = False

    if not has_ts:
        log("INFO", f"[{scene}] 未检测到 Turnstile，跳过")
        return True

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
            try:
                token_ready = sb.execute_script(
                    """
                    var inp = document.querySelector('input[name="cf-turnstile-response"]');
                    return !!(inp && inp.value && inp.value.length > 20);
                    """
                )
            except Exception:
                token_ready = False

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

    email_selector = wait_any_visible(
        sb,
        ["#email", "input[name='email']", "input[type='email']"],
        timeout=15,
    )
    if not email_selector:
        blob = get_page_blob(sb)
        net_err = detect_chrome_error(blob)

        screenshot(sb, "01_login_no_email")
        dump_html(sb, "01_login_no_email")

        cur = "<unknown>"
        try:
            cur = sb.get_current_url()
        except Exception:
            pass

        if net_err:
            return False, f"登录页网络异常: {net_err}，当前URL: {cur}"
        return False, f"登录页未出现邮箱输入框，当前URL: {cur}"

    if not handle_turnstile(sb, "login"):
        return False, "登录验证失败"

    sb.clear(email_selector)
    sb.type(email_selector, email)
    sb.clear("#password")
    sb.type("#password", password)
    screenshot(sb, "02_form_filled")

    sb.wait_for_element_visible("button[type='submit']", timeout=10)
    sb.click("button[type='submit']")
    time.sleep(6)

    cur = ""
    try:
        cur = sb.get_current_url().lower()
    except Exception:
        pass
    if "login" in cur:
        screenshot(sb, "03_login_still_here")
        dump_html(sb, "03_login_still_here")
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

    if not sb.is_element_visible("#points-signin-submit"):
        screenshot(sb, "04_signin_no_button")
        dump_html(sb, "04_signin_no_button")
        return False, "签到失败", before_points, before_points, "找不到签到按钮"

    sb.click("#points-signin-submit")
    log("INFO", "已点击签到")
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
        msg = str(e)
        log("INFO", msg)
        send_tg_text(tg_token, tg_chat_id, f"VPS8 签到失败: {msg}")
        return False, msg

    log("INFO", f"代理: {mask_proxy(proxy)}")

    ok_req_ip, req_ip_or_err = detect_exit_ip(proxy=proxy or None)
    if ok_req_ip:
        log("INFO", f"请求出口IP(脱敏): {mask_ip(req_ip_or_err)}")
    else:
        log("WARN", f"请求出口IP检测失败: {req_ip_or_err}")

    display = None
    if platform.system().lower() == "linux" and not os.environ.get("DISPLAY"):
        try:
            display = Display(visible=False, size=(1366, 768))
            display.start()
            log("INFO", "虚拟显示已启动")
        except Exception as e:
            msg = f"虚拟显示失败: {e}"
            send_tg_text(tg_token, tg_chat_id, f"VPS8 签到失败: {msg}")
            return False, msg

    try:
        sb_kwargs = dict(uc=True, test=True, locale="zh-CN", headless2=False)
        if proxy:
            sb_kwargs["proxy"] = proxy

        with SB(**sb_kwargs) as sb:
            ok_bip, bip_or_err = detect_browser_exit_ip(sb, timeout=20)
            if ok_bip:
                log("INFO", f"浏览器出口IP(脱敏): {mask_ip(bip_or_err)}")
            else:
                screenshot(sb, "00_browser_ip_failed")
                dump_html(sb, "00_browser_ip_failed")
                reason = f"浏览器出口IP检测失败: {bip_or_err}"
                send_tg_text(tg_token, tg_chat_id, f"VPS8 签到失败: {reason}")
                return False, reason

            ok, reason = login(sb, email, password)
            if not ok:
                finish(
                    sb,
                    tg_token,
                    tg_chat_id,
                    "login_failed",
                    build_result_caption(email, "签到失败", fail_reason=reason),
                )
                send_tg_text(tg_token, tg_chat_id, f"VPS8 签到失败: {reason}")
                return False, reason

            success, result_text, before_points, current_points, fail_reason = do_signin(sb)
            caption = build_result_caption(email, result_text, before_points, current_points, fail_reason)
            finish(sb, tg_token, tg_chat_id, "signin_ok" if success else "signin_fail", caption)

            if not success:
                send_tg_text(tg_token, tg_chat_id, f"VPS8 签到失败: {fail_reason}")

            return success, (result_text if success else fail_reason)

    except Exception as e:
        traceback.print_exc()
        msg = f"异常: {str(e)[:200]}"
        send_tg_text(tg_token, tg_chat_id, f"VPS8 签到异常: {msg}")
        return False, msg
    finally:
        if display:
            display.stop()


if __name__ == "__main__":
    ok, msg = vps8_checkin()
    log("INFO", msg)
    if not ok:
        sys.exit(1)
