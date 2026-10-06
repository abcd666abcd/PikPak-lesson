"""
【本地电脑Gemini】Telegram 远程运维守护机器人
完全解耦敏感配置，通过 core.config 读取安全凭据
"""

import os
import sys
import time
import shutil
import subprocess
import telebot
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.config import load_config
from core.pikpak_client import PikPakClient

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

cfg = load_config()
BOT_TOKEN = cfg.get("telegram_bot_token")
ALLOWED_USER_ID = cfg.get("telegram_allowed_user_id")
PROXY_URL = cfg.get("proxy_url")

if not BOT_TOKEN:
    print("[错误] 未配置 telegram_bot_token，请在 config.json 或环境变量中设置。")
    sys.exit(1)

if PROXY_URL:
    telebot.apihelper.proxy = {'http': PROXY_URL, 'https': PROXY_URL}

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

try:
    pikpak_client = PikPakClient(token=cfg.get("pikpak_token"))
except Exception as e:
    print(f"[警告] PikPakClient 初始化失败: {e}")
    pikpak_client = None

def is_authorized(message):
    return message.from_user.id == ALLOWED_USER_ID

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if not is_authorized(message):
        bot.reply_to(message, "⛔ <b>未授权访问</b>\n抱歉，该机器人为个人私有本地电脑助手，仅允许主人使用。")
        return

    help_text = (
        "🤖 <b>本地电脑Gemini 已就绪！</b>\n\n"
        "我是你的专属本地电脑助手，已连接你的 Windows 电脑与 PikPak 云盘：\n\n"
        "📁 <b>PikPak 云盘运维：</b>\n"
        "• <code>/account</code> - 查看网盘账号空间与 VIP 状态\n"
        "• <code>/ls [文件夹ID]</code> - 查看指定文件夹内的视频列表\n"
        "• <code>/convert [文件夹ID]</code> - 一键将 M3U8 无损转码为真 MP4 并回传\n"
        "• <code>/rename [文件夹ID]</code> - 自动拉取 TG 原帖描述完成规范重命名\n\n"
        "💻 <b>本地电脑指令与状态：</b>\n"
        "• <code>/status</code> - 查看电脑磁盘空间与运行状态\n"
        "• <code>/cmd [命令]</code> - 在电脑上执行 PowerShell 命令（如 <code>/cmd dir D:\\</code>）\n\n"
        "直接向我发送任何文字或链接，我也会尽力协助你！"
    )
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['status'])
def cmd_status(message):
    if not is_authorized(message): return
    total_c, _, free_c = shutil.disk_usage("C:")
    total_d, _, free_d = shutil.disk_usage("D:")
    
    status_text = (
        "📊 <b>本地电脑运行状态：</b>\n\n"
        f"• <b>系统时间：</b> {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"• <b>网络代理：</b> {PROXY_URL or '直连'} (正常在线)\n"
        f"• <b>C 盘剩余：</b> {free_c / (1024**3):.1f} GB / {total_c / (1024**3):.1f} GB\n"
        f"• <b>D 盘剩余：</b> {free_d / (1024**3):.1f} GB / {total_d / (1024**3):.1f} GB\n"
        f"• <b>工作区：</b> {cfg.get('default_work_dir')}\n"
    )
    bot.reply_to(message, status_text)

@bot.message_handler(commands=['account'])
def cmd_account(message):
    if not is_authorized(message): return
    if not pikpak_client:
        bot.reply_to(message, "❌ PikPak 客户端未就绪")
        return
    try:
        info = pikpak_client.account_info()
        quota = info.get("quota", {})
        used_gb = int(quota.get("usage", 0)) / (1024**3)
        limit_gb = int(quota.get("limit", 0)) / (1024**3)
        msg = (
            "☁️ <b>PikPak 云盘账号信息：</b>\n\n"
            f"• <b>空间占用：</b> {used_gb:.2f} GB / {limit_gb:.2f} GB\n"
            f"• <b>使用比例：</b> {(used_gb/max(limit_gb,1))*100:.1f}%\n"
        )
        bot.reply_to(message, msg)
    except Exception as e:
        bot.reply_to(message, f"❌ 查询失败: {e}")

@bot.message_handler(commands=['ls'])
def cmd_ls(message):
    if not is_authorized(message): return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "⚠️ 请提供文件夹 ID，例如：<code>/ls VP3E9hnUrDtv30ftAvk92Rweo2</code>")
        return
    folder_id = args[1]
    bot.send_chat_action(message.chat.id, 'typing')
    try:
        res = pikpak_client.list_files(parent_id=folder_id, limit=25)
        files = res.get("files", [])
        if not files:
            bot.reply_to(message, f"📁 文件夹 <code>{folder_id}</code> 为空。")
            return
        reply_lines = [f"📁 <b>文件夹内容 (前 {min(len(files), 20)} 项)：</b>\n"]
        for f in files[:20]:
            kind = "📁" if "folder" in f.get("kind", "") else "🎬"
            reply_lines.append(f"{kind} <code>{f.get('name')[:35]}</code> ({f.get('size')})")
        bot.reply_to(message, "\n".join(reply_lines))
    except Exception as e:
        bot.reply_to(message, f"❌ 查询异常: {e}")

@bot.message_handler(commands=['cmd'])
def cmd_execute(message):
    if not is_authorized(message): return
    cmd_str = message.text[5:].strip()
    if not cmd_str:
        bot.reply_to(message, "⚠️ 请提供要执行的命令，例如：<code>/cmd dir D:\\</code>")
        return
    bot.send_chat_action(message.chat.id, 'typing')
    try:
        res = subprocess.run(["powershell", "-Command", cmd_str], capture_output=True, text=True, timeout=30)
        output = res.stdout if res.returncode == 0 else (res.stderr or res.stdout)
        if not output.strip():
            output = "(命令执行成功，无输出内容)"
        if len(output) > 3500:
            output = output[:3500] + "\n...(内容过长已截断)"
        bot.reply_to(message, f"💻 <b>执行结果 (退出码: {res.returncode})：</b>\n<pre>{output}</pre>")
    except Exception as e:
        bot.reply_to(message, f"❌ 执行异常: {e}")

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    if not is_authorized(message): return
    text = message.text.strip()
    if "mypikpak.com/drive/all/" in text:
        parts = text.split("/drive/all/")
        if len(parts) > 1:
            fid = parts[1].split()[0].split("?")[0].strip()
            bot.reply_to(message, f"💡 检测到 PikPak 文件夹 ID: <code>{fid}</code>\n发送 <code>/ls {fid}</code> 查看列表，或在电脑运行重命名/转码工具。")
            return
    bot.reply_to(message, f"收到主人指令：<i>{text}</i>\n如需执行电脑操作，请使用 <code>/cmd 你的命令</code>；发送 <code>/help</code> 查看全部功能。")

def start_bot():
    print(f"[{time.strftime('%H:%M:%S')}] 🤖 本地电脑Gemini Bot 正在启动...")
    print(f"[{time.strftime('%H:%M:%S')}] 授权主人 ID: {ALLOWED_USER_ID}")
    bot.infinity_polling(timeout=20, long_polling_timeout=20)

if __name__ == "__main__":
    start_bot()
