import time
import os
import json
import re
import random
import requests

# 智能环境配置：仅在未设置时才应用默认值
# 这样兼容 GitHub Actions 的 xvfb-run (会自动设置 DISPLAY) 和 Docker 环境
if "DISPLAY" not in os.environ:
    os.environ["DISPLAY"] = ":1"
    
if "XAUTHORITY" not in os.environ:
    # 仅当路径存在时才设置，避免在 GitHub Runner (home/runner) 中报错
    if os.path.exists("/home/headless/.Xauthority"):
        os.environ["XAUTHORITY"] = "/home/headless/.Xauthority"

print(f"[DEBUG] Env DISPLAY: {os.environ.get('DISPLAY')}")
print(f"[DEBUG] Env XAUTHORITY: {os.environ.get('XAUTHORITY')}")

from seleniumbase import SB

# ================= 配置区域 =================
PROXY_URL = os.getenv("PROXY", "")  # 代理
EMAIL = os.getenv("EMAIL")  # 邮箱
PASSWORD = os.getenv("PASSWORD")  # 密码
TG_TOKEN = os.getenv("TG_TOKEN")  # tg通知token
TG_CHAT_ID = os.getenv("TG_CHAT_ID")  # tg通知chat_id

# 目标 URL
LOGIN_PANEL = "https://idc-new.ulzix.com/login"
CHECKIN_URL = "https://idc-new.ulzix.com/pointmall/signin"
# ===========================================
PROXY_URL = os.getenv("BROWSER_PROXY", "127.0.0.1:8080")
class UlzixCheckin:
    def __init__(self):
        self.BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        self.screenshot_dir = os.path.join(self.BASE_DIR, "artifacts")
        if not os.path.exists(self.screenshot_dir):
            os.makedirs(self.screenshot_dir)

    def log(self, msg):
        timestamp = time.strftime('%H:%M:%S')
        print(f"[{timestamp}] [INFO] {msg}", flush=True)

    def human_wait(self, min_s=6, max_s=10):
        """随机模拟人类等待时间"""
        time.sleep(random.uniform(min_s, max_s))

    def move_mouse_human(self, sb):
        """模拟人类鼠标晃动预热"""
        try:
            # 在页面不同位置“晃悠”一下鼠标，打破机器人直线模式
            for _ in range(3):
                x = random.randint(100, 800)
                y = random.randint(100, 600)
                sb.slow_click(f"body", force=True) # 借用 slow_click 的移动特性，或者直接用 move_to
                time.sleep(random.uniform(0.5, 1.2))
        except: pass

    def send_telegram_notify(self, message, photo_path=None):
        """发送 Telegram 通知 (带图片)"""
        if not TG_TOKEN or not TG_CHAT_ID:
            self.log("⚠️ 未配置 TG_TOKEN 或 TG_CHAT_ID，跳过推送。")
            return
        
        try:
            if photo_path and os.path.exists(photo_path):
                url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
                with open(photo_path, 'rb') as f:
                    # caption 参数用于发送带文字的图片
                    requests.post(url, data={'chat_id': TG_CHAT_ID, 'caption': message}, files={'photo': f})
            else:
                url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
                requests.post(url, data={'chat_id': TG_CHAT_ID, 'text': message})
            
            self.log("✅ TG 推送已发送")
        except Exception as e:
            self.log(f"❌ TG 推送失败: {e}")

    def has_turnstile(self, sb):
        selectors = [
            'iframe[src*="turnstile"]',
            'iframe[src*="challenges.cloudflare.com"]',
            'input[name="cf-turnstile-response"]'
        ]

        for s in selectors:
            try:
                if sb.is_element_present(s):
                    return True
            except:
                pass

        return False

    def run(self):
        self.log("=" * 40)
        self.log("🚀 Ulzix - 签到流程")
        self.log("=" * 40)
        self.log("🎯 正在启动 Chrome 浏览器...")
        
        # 使用 headed=True 强制有头模式渲染到 VNC
        with SB(
            uc=True,            # 启用反检测模式
            test=True, 
            headed=True,        # 关键：强制有头模式
            headless=False,     # 明确禁用 headless
            xvfb=False,         # 禁用内部虚拟显示器，使用系统 DISPLAY
            locale="zh-CN",
            chromium_arg="--no-sandbox,--disable-dev-shm-usage,--disable-gpu,--window-position=0,0,--start-maximized,--lang=zh-CN",
            proxy=PROXY_URL if PROXY_URL else None
        ) as sb:
            try:
                self.log("✅ 浏览器已启动！")
                
                # ... (省略中间步骤，保持原有逻辑不变) ...
                
                # 1. IP 检测
                self.log("🌍 正在检测出口 IP...")
                try:
                    sb.open("https://api.ipify.org?format=json")
                    ip_val = json.loads(re.search(r'\{.*\}', sb.get_text("body")).group(0)).get('ip', 'Unknown')
                    parts = ip_val.split('.')
                    self.log(f"✅ 当前出口 IP: {parts[0]}.{parts[1]}.***.{parts[-1]}")
                except:
                    self.log("⚠️ IP 检测跳过...")

                # 2. 访问登录首页并登录
                self.log("🔗 访问登录首页...")
                sb.uc_open_with_reconnect(LOGIN_PANEL, reconnect_time=25)
                time.sleep(5)
                self.log("🖱️ 开始输入账户密码并登录...")
                # 输入邮箱
                sb.type("#email", EMAIL)
                # 输入密码
                sb.type("#password", PASSWORD)
                # 点击登录按钮
                sb.click("button[type='submit']")
                # 等待跳转
                time.sleep(10)
                #login_screenshot = f"{self.screenshot_dir}/acc.png"
                #sb.save_screenshot(login_screenshot)
                #self.send_telegram_notify("登录页面", login_screenshot)

                # 3. 进入签到页面
                self.log("🔗 进入签到页面")
                sb.uc_open_with_reconnect(CHECKIN_URL, reconnect_time=25)
                time.sleep(10)
                # 当前分数获取
                before_points = sb.get_text(".points-format")
                self.log(f"✅ 当前分数：{before_points}")
                #checkin_screenshot = f"{self.screenshot_dir}/checkin.png"
                #sb.save_screenshot(checkin_screenshot)
                #self.send_telegram_notify("签到页面", checkin_screenshot)                

                # 4. Cloudflare Turnstile验证
                self.log("⏳ 开始检查Turnstile验证")
                time.sleep(15)

                if self.has_turnstile(sb):
                    token = None
                    for i in range(2):
                        self.log(f"第 {i+1} 次尝试")
                        self.move_mouse_human(sb)
                        sb.uc_gui_click_captcha()
                        # 等待token
                        for _ in range(15):
                            time.sleep(10)
                            token = sb.get_attribute('input[name="cf-turnstile-response"]',"value")
                            if token:
                                break
                        if token:
                            self.log("✅ Cloudflare Turnstile验证成功")
                            print(f"Token length={len(token)}")
                            break
                        self.log("⚠️ click后没有token，尝试handle")
                        self.move_mouse_human(sb)
                        sb.uc_gui_handle_captcha()
                        time.sleep(10)
                        # handle后再次检查
                        token = sb.get_attribute('input[name="cf-turnstile-response"]',"value")
                        if token:
                            self.log("✅ handle后获取Token")
                            break
                    if not token:
                        self.log("❌ Cloudflare验证失败")
                        cf_screenshot = f"{self.screenshot_dir}/cf_failed.png"
                        sb.save_screenshot(cf_screenshot)
                        self.send_telegram_notify("CF失败", cf_screenshot)
                        return
                    self.log("🎉 CF验证完成")
                
                #cf_screenshot = f"{self.screenshot_dir}/cf.png"
                #sb.save_screenshot(cf_screenshot)
                #self.send_telegram_notify("Cloudflare", cf_screenshot)

                # 5.签到操作
                if not sb.is_element_present("#btn-signin"):
                    self.log("✅ 今日已签到")
                    # 连续签到天数获取
                    sign_days = sb.get_text(".text-muted.mb-3.mb-lg-4 span.fw-bold")
                    self.log(f"✅ 连续签到天数：{sign_days}")
                    final_screenshot = f"{self.screenshot_dir}/final.png"
                    sb.save_screenshot(final_screenshot)
                    self.send_telegram_notify(f"🎉Ulzix 签到流程\n✅今日已签到\n🚀当前积分：{before_points}\n🕒连续签到天数：{sign_days}", final_screenshot)
                else:
                    sb.click("#btn-signin")
                    self.log("✅ 已点击签到按钮")
                    time.sleep(5)
                    # 再次进入签到页面
                    sb.uc_open_with_reconnect(CHECKIN_URL, reconnect_time=25)
                    time.sleep(5)
                    # 连续签到天数获取
                    sign_days = sb.get_text(".text-muted.mb-3.mb-lg-4 span.fw-bold")
                    # 当前分数获取
                    after_points = sb.get_text(".points-format")
                    self.log(f"✅ 当前分数：{after_points}")
                    final_screenshot = f"{self.screenshot_dir}/final.png"
                    sb.save_screenshot(final_screenshot)
                    self.send_telegram_notify(f"🎉Ulzix 签到流程\n✅签到成功,签到前积分：{before_points}\n🚀签到后积分：{after_points}\n🕒连续签到天数：{sign_days}", final_screenshot)
                    

            except Exception as e:
                self.log(f"❌ 运行异常: {e}")
                import traceback
                traceback.print_exc()
                sb.save_screenshot(f"{self.screenshot_dir}/error.png")


if __name__ == "__main__":
    UlzixCheckin().run()
