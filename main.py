import os
import sys
import time
import random
import requests
import tempfile
import re
from xvfbwrapper import Xvfb
from DrissionPage import ChromiumPage, ChromiumOptions

try:
    import speech_recognition as sr
    from pydub import AudioSegment
except ImportError:
    pass


# ==============================================================================
# Telegram
# ==============================================================================
def send_tg_message(token, chat_id, message):
    if not token or not chat_id:
        print("未配置 TG_TOKEN 或 TG_CHAT_ID，跳过通知。")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "None"}
    try:
        requests.post(url, json=payload, timeout=10)
        print("✅ Telegram 通知发送成功！")
    except Exception as e:
        print(f"❌ Telegram 通知失败: {e}")

def send_tg_file(token, chat_id, file_path):
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendDocument"
        with open(file_path, "rb") as f:
            requests.post(url, data={"chat_id": chat_id}, files={"document": f})
        print(f"📎 已发送文件: {file_path}")
    except Exception as e:
        print(f"❌ 发送文件失败: {e}")


def debug_dump(page, tg_token, tg_chat_id, name):
    """保存截图 + HTML + 自动发送"""
    try:
        html_file = f"{name}.html"
        img_file = f"{name}.png"

        # 保存 HTML
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(page.html)

        # 截图
        page.get_screenshot(path=img_file, full_page=True)

        print(f"🧪 调试文件生成: {name}")

        # 发送到 TG
        # 只发送图片即可 send_tg_file(tg_token, tg_chat_id, html_file)
        send_tg_file(tg_token, tg_chat_id, img_file)

    except Exception as e:
        print(f"❌ debug_dump 失败: {e}")

# ==============================================================================
# 验证码破解
# ==============================================================================
class RecaptchaAudioSolver:
    def __init__(self, page):
        self.page = page

    def human_type(self, ele, text):
        ele.click()
        ele.clear()
        for c in text:
            ele.input(c, clear=False)
            time.sleep(random.uniform(0.05, 0.2))

    def solve(self, bframe):
        try:
            btn = bframe.ele('#recaptcha-audio-button', timeout=3)
            if not btn:
                return False
            btn.click()
            time.sleep(3)

            src = bframe.ele('#audio-source').attr('src')
            r = requests.get(src, timeout=10)

            with open("a.mp3", "wb") as f:
                f.write(r.content)

            sound = AudioSegment.from_mp3("a.mp3")
            sound.export("a.wav", format="wav")

            r = sr.Recognizer()
            with sr.AudioFile("a.wav") as s:
                audio = r.record(s)
                text = r.recognize_google(audio)

            box = bframe.ele('#audio-response')
            self.human_type(box, text)

            bframe.ele('#recaptcha-verify-button').click()
            time.sleep(3)

            return True
        except:
            return False


# ==============================================================================
# 主逻辑
# ==============================================================================
def vps8_checkin(url, proxy_url=None):
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

        page = ChromiumPage(co)

        print("🌐 打开页面")
        page.get(url)
        time.sleep(10)

        # =========================
        # 登录验证码处理
        # =========================
        solved = False
        frame = page.get_frame('xpath://iframe[contains(@src,"recaptcha")]', timeout=5)

        if frame:
            box = frame.ele('#recaptcha-anchor', timeout=5)
            if box:
                box.click()
                time.sleep(5)

                if box.attr('aria-checked') == 'true':
                    solved = True
                else:
                    bframe = page.get_frame('xpath://iframe[contains(@src,"bframe")]', timeout=5)
                    if bframe:
                        solver = RecaptchaAudioSolver(page)
                        solved = solver.solve(bframe)

        if not solved:
            msg = "❌ 登录验证码失败"
            debug_dump(page, tg_token, tg_chat_id, "登录验证码处理失败")
            return success, msg

        print("✅ 登录验证码通过")

        # =========================
        # 登录流程
        # =========================
        print("🔐 开始登录")
        send_tg_message(tg_token, tg_chat_id, "🔐 VPS8签到程序开始登录")
        email = os.getenv("VPS8_USERNAME")
        password = os.getenv("VPS8_PASSWORD")

        if not email or not password:
            return False, "❌ 未配置账号密码"

        email_input = page.ele('#email', timeout=5)
        password_input = page.ele('#password', timeout=5)

        if not email_input:
            return False, "❌ 找不到邮箱输入框"

        solver = RecaptchaAudioSolver(page)

        solver.human_type(email_input, email)
        solver.human_type(password_input, password)

        btn = page.ele('xpath://button[@type="submit"]', timeout=3)
        if not btn:
            return False, "❌ 找不到登录按钮"

        btn.click()

        time.sleep(8)

        if "login" not in page.url.lower():
            success = True
            msg = "🎉 登录成功"
            send_tg_message(tg_token, tg_chat_id, "🎉 VPS8账号登录成功")
            # 看结果就行了 debug_dump(page, tg_token, tg_chat_id, "登录成功")
        else:
            msg = "❌ 登录失败"
            # 看结果就行了 send_tg_message(tg_token, tg_chat_id, "❌ VPS8账号登录失败")
            debug_dump(page, tg_token, tg_chat_id, "登录失败")
            return False, "❌ 登录失败"

        # =========================
        # 👉 签到流程
        # =========================
        print("➡️ 进入签到页面")
        page.get("https://vps8.zz.cd/points/signin")
        time.sleep(10)
        send_tg_message(tg_token, tg_chat_id, "➡️ 进入签到处理页面")
        debug_dump(page, tg_token, tg_chat_id, "进入签到页面")

        if "已签到" in page.html:
            match = re.search(r'当前积分：\s*<strong>(\d+)</strong>', page.html)
            if match:
                points = match.group(1)
            print(f"ℹ️ 今天已签到，当前积分：{points}")
            debug_dump(page, tg_token, tg_chat_id, "今天已签到")
            return True, f"✅ 今天已签到，当前积分：{points}"

        print("🔐 开始处理签到验证码")
        send_tg_message(tg_token, tg_chat_id, "🔐 开始处理签到验证码")        
        
        # =========================
        # 签到页面验证码处理
        # =========================
        solved = False
        frame = page.get_frame('xpath://iframe[contains(@src,"recaptcha")]', timeout=5)

        if frame:
            box = frame.ele('#recaptcha-anchor', timeout=5)
            if box:
                box.click()
                time.sleep(5)

                if box.attr('aria-checked') == 'true':
                    solved = True
                else:
                    bframe = page.get_frame('xpath://iframe[contains(@src,"bframe")]', timeout=5)
                    if bframe:
                        solver = RecaptchaAudioSolver(page)
                        solved = solver.solve(bframe)

        if not solved:
            msg = "❌ 签到页面验证码处理失败"
            # 看结果就行了 send_tg_message(tg_token, tg_chat_id, msg)
            debug_dump(page, tg_token, tg_chat_id, "签到页面验证码处理失败")
            return success, msg

        solver = RecaptchaAudioSolver(page)

        print("✅ 处理签到验证码完毕,已发送TG截图,请从截图查看结果")
        send_tg_message(tg_token, tg_chat_id, "✅ 处理签到验证码完毕,已发送TG截图,请从截图查看结果")
        debug_dump(page, tg_token, tg_chat_id, "captcha_result")

        time.sleep(10)
        print("🖱️ 点击签到按钮")
        btn = page.ele('#points-signin-submit', timeout=5)
        if not btn:
            print("❌ 找不到按钮")
            debug_dump(page, tg_token, tg_chat_id, "no_button")
            return False, "❌ 找不到签到按钮"
        try:
            btn.click()
        except:
            btn.click(by_js=True)

        time.sleep(6)

        # 判断结果
        html = page.html

        if "已签到" in html or "签到成功" in html:
            match = re.search(r'当前积分：\s*<strong>(\d+)</strong>', html)
            if match:
                points = match.group(1)
            print(f"🎉 签到成功，当前积分：{points}")
            send_tg_message(tg_token, tg_chat_id, f"✅ 签到成功，当前积分：{points}，请及时换取余额!!!")
            debug_dump(page, tg_token, tg_chat_id, "签到成功")
            return True, "🎉 签到成功"

        print("⚠️ 未确认签到状态")
        debug_dump(page, tg_token, tg_chat_id, "无法确认签到状态")
        return True, "⚠️ 未确认签到状态（看截图）"
    except Exception as e:
        msg = f"💥 异常: {str(e)[:200]}"

    finally:
        if page:
            try:
                page.quit()
            except:
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

    if not url:
        print("❌ 缺少 URL")
        sys.exit(1)

    ok, msg = vps8_checkin(url)
    send_tg_message(tg_token, tg_chat_id, msg)

    if not ok:
        sys.exit(1)