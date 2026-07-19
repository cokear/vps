import os
import re
import sys
import time
import platform
import requests

from pyvirtualdisplay import Display
from seleniumbase import SB

LOGIN_URL = "https://idc-new.ulzix.com/login"
SIGNIN_URL = "https://idc-new.ulzix.com/pointmall/signin"
SS_DIR = "screenshots"

# 【修复】防止本地无代理时强制连 8080 导致崩溃
PROXY_URL = os.getenv("BROWSER_PROXY", "")


def log(level, msg):
    print(f"[{level}] {msg}")


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


def mask_email(email):
    try:
        local, domain = (email or "").split("@", 1)
        if len(local) <= 2:
            masked = local[0] + "*"
        else:
            masked = local[0] + "*" * (len(local) - 2) + local[-1]
        return f"{masked}@{domain}"
    except Exception:
        return "***"


def parse_account(raw):
    value = (raw or "").strip()
    index = value.find(":")
    if index <= 0 or index == len(value) - 1:
        raise ValueError("ACCOUNTS 格式错误，应为 邮箱:密码")
    return value[:index].strip(), value[index + 1:].strip()


# 【修复核心】彻底根除“已连续签到”带来的误杀 Bug
def is_signed(html):
    if "今日还未签到" in html:
        return False
    if "今日已签到" in html:
        return True
    
    if 'id="btn-signin"' in html or "立即签到" in html:
        return False
        
    if "签到记录" in html:
        return True
        
    return False


def extract_points(html):
    match = re.search(r'data-points="(\d+)"', html)
    return match.group(1) if match else "未知"


def build_result_caption(account, result_text, before_points=None, current_points=None, fail_reason=None):
    lines = [
        "Ulzix 每日签到",
        f"🎮 账号：{account}",
        f"📊 签到结果: {result_text}",
    ]
    if before_points is not None:
        lines.append(f"🎉 签到前积分: {before_points}")
    if current_points is not None:
        lines.append(f"💰 当前积分: {current_points}")
    if fail_reason:
        lines.append(f"❌ 失败原因: {fail_reason}")
    return "\n".join(lines)


def handle_turnstile(sb, scene="page", max_attempts=3):
    log("INFO", f"[{scene}] 开始处理 Turnstile 验证")
    sb.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    # 【修复】增加刚进入时的缓冲时间，给慢速 CF 框架加载的余地
    time.sleep(5)

    for attempt in range(max_attempts):
        log("INFO", f"[{scene}] Turnstile 尝试 {attempt + 1}/{max_attempts}")
        try:
            sb.uc_gui_handle_captcha()
            log("INFO", f"[{scene}] 已调用 uc_gui_handle_captcha")
        except Exception as e:
            log("WARN", f"[{scene}] uc_gui_handle_captcha 失败: {e}")

        start = time.time()
        # 【终极修复】熬鹰模式：最多等待 150 秒（两分半），专治 CF 故意拖延加载
        while time.time() - start < 150:
            token_ready = sb.execute_script(
                """
                var inp = document.querySelector('input[name="cf-turnstile-response"]');
                return !!(inp && inp.value && inp.value.length > 20);
                """
            )
            if token_ready:
                log("INFO", f"[{scene}] ✅ Turnstile 通过")
                screenshot(sb, f"turnstile_ok_{scene}")
                return True

            success = sb.execute_script(
                """
                var el = document.getElementById('success');
                return el && getComputedStyle(el).display !== 'none';
                """
            )
            if success:
                log("INFO", f"[{scene}] Turnstile 显示成功元素")
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
    
    # 如果目标网站的登录页也有 Turnstile 验证，把下面这行开头的 '#' 删掉：
    # handle_turnstile(sb, "login")

    sb.wait_for_element_visible("#email", timeout=15)

    log("INFO", f"填写邮箱: {mask_email(email)}")
    # 【修复】精简输入操作
    sb.type("#email", email)
    time.sleep(0.5)

    sb.type("#password", password)
    time.sleep(0.5)

    screenshot(sb, "02_form_filled")

    sb.wait_for_element_visible('button[type="submit"]', timeout=10)
    sb.click('button[type="submit"]')
    time.sleep(6)

    if "login" in sb.get_current_url().lower():
        log("ERROR", "登录失败，仍停留在登录页面")
        return False, "登录失败"

    log("INFO", "登录成功")
    screenshot(sb, "03_login_success")
    return True, None


def do_signin(sb):
    log("INFO", "打开签到页")
    sb.uc_open_with_reconnect(SIGNIN_URL, reconnect_time=8)
    
    # 【终极修复】进入签到页面后，直接硬等 30 秒，给代理节点和 CF 充足的加载时间
    time.sleep(30)
    screenshot(sb, "04_signin_loaded")

    sb.wait_for_element_visible("body", timeout=10)

    initial_html = sb.get_page_source()
    before_points = extract_points(initial_html)
    
    # 这里使用的是全新修复的 is_signed 函数
    if is_signed(initial_html):
        log("INFO", "今日已签到")
        return True, "今日已签到", before_points, before_points, None

    if not handle_turnstile(sb, "signin"):
        return False, "签到失败", before_points, before_points, "签到验证失败"

    # 【修复】安全获取按钮状态，规避闪退风险
    if not sb.is_element_visible("#btn-signin"):
        log("ERROR", "找不到立即签到按钮")
        return False, "签到失败", before_points, before_points, "找不到签到按钮"

    sb.click("#btn-signin")
    log("INFO", "已点击立即签到")
    time.sleep(3)

    for i in range(10):
        time.sleep(2)
        html = sb.get_page_source()
        if is_signed(html):
            current_points = extract_points(html)
            log("INFO", f"签到成功，积分: {current_points}")
            return True, "签到成功", before_points, current_points, None
        log("INFO", f"等待签到结果... ({i + 1})")

    current_points = extract_points(sb.get_page_source())
    log("WARN", "签到状态未确认")
    return False, "签到失败", before_points, current_points, "未确认签到状态"


def Ulzix_checkin():
    tg_token = os.getenv("TG_BOT_TOKEN")
    tg_chat_id = os.getenv("TG_CHAT_ID")
    account_raw = os.getenv("ACCOUNTS")
    if not account_raw:
        return False, "缺少 ACCOUNTS"

    try:
        email, password = parse_account(account_raw)
    except Exception as e:
        return False, str(e)

    proxy = PROXY_URL.strip() if PROXY_URL else ""
    if proxy:
        log("INFO", f"使用代理: {proxy}")
    else:
        log("INFO", "未配置代理，直连")

    display = None
    if platform.system().lower() == "linux" and not os.environ.get("DISPLAY"):
        try:
            display = Display(visible=False, size=(1280, 720))
            display.start()
            log("INFO", "虚拟显示已启动")
        except Exception as e:
            return False, f"虚拟显示失败: {e}"

    try:
        with SB(
            uc=True,
            locale="zh-CN",
            headless2=False,
            proxy=proxy if proxy else None,
        ) as sb:
            ok, reason = login(sb, email, password)
            if not ok:
                finish(
                    sb,
                    tg_token,
                    tg_chat_id,
                    "login_failed",
                    build_result_caption(email, "签到失败", fail_reason=reason),
                )
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
        log("ERROR", f"脚本异常: {e}")
        import traceback
        traceback.print_exc()
        return False, f"异常: {str(e)[:200]}"
    finally:
        if display:
            display.stop()

    return False, "未知错误"  


if __name__ == "__main__":
    ok, msg = Ulzix_checkin()
    log("INFO", msg)
    if not ok:
        sys.exit(1)
