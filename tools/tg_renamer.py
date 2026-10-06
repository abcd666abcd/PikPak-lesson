"""
PikPak 智能 Telegram 乱序转存批量重命名工具
功能：
1. 读取网盘内视频元数据中保留的原始 Telegram 帖子链接；
2. 抓取原帖文案，自动解析各分集序号与详细剧情描述；
3. 根据视频文件的毫秒级入库时间戳（created_time）严谨对齐；
4. 全程调用云端重命名 API，秒级完成，零下载，零磁盘占用。
"""

import sys
import re
import argparse
import requests
from bs4 import BeautifulSoup
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.config import load_config
from core.pikpak_client import PikPakClient

sys.stdout.reconfigure(encoding='utf-8')

def clean_desc(text, max_len=60):
    text = re.sub(r'[\\/:*?"<>|\r\n]', '', text).strip()
    return text[:max_len].strip()

def fetch_tg_post_lines(tg_url, proxy=None):
    """抓取 Telegram 公开频道预览页面的正文分行"""
    # 转换为公开预览通道链接
    clean_url = tg_url.replace("t.me/", "t.me/s/").split("?")[0]
    proxies = {"http": proxy, "https": proxy} if proxy else None
    resp = requests.get(clean_url, proxies=proxies, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    og_desc = soup.find('meta', property='og:description')
    if og_desc and og_desc.get('content'):
        return [l.strip() for l in og_desc['content'].split('\n') if l.strip()]
    return []

def parse_items_from_lines(lines):
    """从原帖文本中提取 (编号, 描述) 元组列表"""
    items = []
    for l in lines:
        # 支持各种数字与括号格式：如 "11. (原创33...)"、"30.(原创88...)" 等
        m = re.search(r'[\(（](?:原创)?(\d+)[^\)）]*[\)）]\s*(.*)$', l)
        if not m:
            m = re.search(r'原创(\d+)[^\s]*\s*(.*)$', l)
        if m:
            num = m.group(1)
            desc = clean_desc(m.group(2))
            items.append((num, desc))
    return items

def rename_folder_from_tg(folder_id, prefix="30岁堂姐-", dry_run=False):
    cfg = load_config()
    client = PikPakClient(token=cfg.get("pikpak_token"))
    proxy = cfg.get("proxy_url")

    print(f"=== 扫描网盘文件夹: {folder_id} ===")
    folder_detail = client.get_file(folder_id)
    tg_url = folder_detail.get("params", {}).get("url")
    if not tg_url:
        print(f"[错误] 文件夹 {folder_id} 未找到 Telegram 原帖链接 (params.url)")
        return

    print(f"检测到 Telegram 原帖链接: {tg_url}")
    lines = fetch_tg_post_lines(tg_url, proxy=proxy)
    items = parse_items_from_lines(lines)
    print(f"解析到原帖分集条目: {len(items)} 条")

    # 获取文件夹内所有文件并按入库时间排序
    res = client.list_files(parent_id=folder_id, limit=100)
    files = res.get("files", [])
    # 按照入库时间戳严格排序
    files_sorted = sorted(files, key=lambda x: x.get("created_time", ""))
    print(f"文件夹内现有文件数: {len(files_sorted)} 个\n")

    if not items:
        print("[错误] 未能从原帖提取到分集条目，终止。")
        return

    used_tags = []
    print("---------------- 改名前后对照预览 ----------------")
    for f, item in zip(files_sorted, items):
        fid = f.get("id")
        old_name = f.get("name")
        num, desc = item
        new_name = f"{prefix}原创{num} {desc}.mp4"
        used_tags.append(num)

        print(f"  原名称: {old_name}")
        print(f"  ==> 拟改成: {new_name}")

        if not dry_run:
            try:
                client.rename(fid, new_name)
                print(f"      [成功更名]")
            except Exception as e:
                print(f"      [更名失败: {e}]")
        print()

    if not dry_run and used_tags:
        new_folder_title = f"{prefix.rstrip('-')} - 原创{used_tags[0]}-{used_tags[-1]}"
        try:
            client.rename(folder_id, new_folder_title)
            print(f"  -> 文件夹本身已更新为: {new_folder_title}")
        except Exception as e:
            print(f"  -> 文件夹重命名失败: {e}")

    print("--------------------------------------------------")
    if dry_run:
        print("当前为 Dry-Run 模式，未实际修改。如确认无误请去掉 --dry-run 执行。")
    else:
        print("全部文件云端规范重命名完毕！")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PikPak Telegram 转存视频智能重命名工具")
    parser.add_argument("--folder", required=True, help="PikPak 目标文件夹 ID")
    parser.add_argument("--prefix", default="30岁堂姐-", help="统一命名前缀 (默认: 30岁堂姐-)")
    parser.add_argument("--dry-run", action="store_true", help="仅预览改名对照表，不实际执行")
    args = parser.parse_args()

    rename_folder_from_tg(args.folder, prefix=args.prefix, dry_run=args.dry_run)
