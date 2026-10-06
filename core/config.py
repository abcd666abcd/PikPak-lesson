"""
配置加载器：支持从当前项目 config.json、系统环境变量或 ~/.gemini/config/ 读取凭证
优先保证开源安全性，严禁硬编码敏感信息
"""

import os
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def load_config():
    config = {
        "pikpak_token": "",
        "telegram_bot_token": "",
        "telegram_allowed_user_id": 0,
        "proxy_url": os.environ.get("HTTP_PROXY", "http://127.0.0.1:7890"),
        "default_work_dir": r"D:\aria2\新建文件夹",
    }
    
    # 1. 尝试读取项目根目录的 config.json (已被 .gitignore 忽略)
    cfg_path = PROJECT_ROOT / "config.json"
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
                config.update(user_cfg)
        except Exception as e:
            print(f"[警告] 读取 config.json 失败: {e}")

    # 2. 环境变量覆盖
    if os.environ.get("PIKPAK_TOKEN"):
        config["pikpak_token"] = os.environ["PIKPAK_TOKEN"]
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        config["telegram_bot_token"] = os.environ["TELEGRAM_BOT_TOKEN"]
    if os.environ.get("TELEGRAM_ALLOWED_USER_ID"):
        try:
            config["telegram_allowed_user_id"] = int(os.environ["TELEGRAM_ALLOWED_USER_ID"])
        except ValueError:
            pass

    # 3. 若仍无 PikPak Token，尝试从系统全局配置 ~/.gemini/config/mcp_config.json 兜底
    if not config["pikpak_token"]:
        global_mcp = Path.home() / ".gemini" / "config" / "mcp_config.json"
        if global_mcp.exists():
            try:
                with open(global_mcp, "r", encoding="utf-8") as f:
                    mcp_data = json.load(f)
                auth = mcp_data.get("mcpServers", {}).get("pikpak", {}).get("headers", {}).get("Authorization", "")
                if auth.startswith("Bearer "):
                    config["pikpak_token"] = auth.split("Bearer ", 1)[1].strip()
            except Exception:
                pass

    return config
