"""
PikPak 文件夹快速巡检工具
"""

import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.config import load_config
from core.pikpak_client import PikPakClient

sys.stdout.reconfigure(encoding='utf-8')

def parse_size_str(val):
    if isinstance(val, (int, float)):
        return float(val) / (1024 * 1024)
    if not val:
        return 0.0
    val_str = str(val).strip().upper()
    if val_str.endswith("GB"):
        return float(val_str[:-2].strip()) * 1024
    if val_str.endswith("MB"):
        return float(val_str[:-2].strip())
    if val_str.endswith("KB"):
        return float(val_str[:-2].strip()) / 1024
    try:
        return float(val_str) / (1024 * 1024)
    except ValueError:
        return 0.0

def inspect_folder(folder_id):
    cfg = load_config()
    client = PikPakClient(token=cfg.get("pikpak_token"))

    res = client.list_files(parent_id=folder_id, limit=100)
    files = res.get("files", [])
    print(f"\n📁 文件夹 ID: {folder_id}")
    print(f"📄 共包含 {len(files)} 个项目：\n")

    mp4_count = 0
    m3u8_count = 0
    dir_count = 0

    for f in files:
        name = f.get("name", "")
        size_mb = parse_size_str(f.get("size", 0))
        fid = f.get("id")
        kind = f.get("kind", "")
        if name.lower().endswith(".mp4"):
            mp4_count += 1
            tag = "[MP4]"
        elif name.lower().endswith(".m3u8"):
            m3u8_count += 1
            tag = "[M3U8]"
        elif "folder" in kind:
            dir_count += 1
            tag = "[DIR]"
        else:
            tag = "[FILE]"
        print(f"  {tag:<7} {size_mb:>8.2f} MB | ID: {fid} | {name}")

    print("\n" + "-" * 40)
    print(f"统计: MP4: {mp4_count} 个, M3U8: {m3u8_count} 个, 文件夹: {dir_count} 个\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PikPak 文件夹快速巡检工具")
    parser.add_argument("--folder", required=True, help="PikPak 目标文件夹 ID")
    args = parser.parse_args()
    inspect_folder(args.folder)
