"""
PikPak 云端 M3U8/TS 批量极速无损流复制转真 MP4 并回传工具
特点：
- FFmpeg 流复制模式 (-c copy -movflags +faststart)，数秒完成，画质零损失；
- 逐个流转，下载单个 -> 转封装 -> 回传 -> 立即删除，工作区零磁盘残留；
- Windows 文件句柄锁安全容错删除。
"""

import os
import sys
import time
import argparse
import subprocess
import requests
import concurrent.futures
from pathlib import Path

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.config import load_config
from core.pikpak_client import PikPakClient
from core.oss_uploader import multipart_upload_to_pikpak

sys.stdout.reconfigure(encoding='utf-8')

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def safe_remove(path, max_retries=10, delay=0.8):
    """Windows 文件锁安全删除重试"""
    if not os.path.exists(path):
        return
    for _ in range(max_retries):
        try:
            os.remove(path)
            return
        except PermissionError:
            time.sleep(delay)
        except Exception as e:
            log(f"  [警告] 删除临时文件 {path} 异常: {e}")
            return

def download_file_multithread(url, target_path, total_size, num_threads=16):
    """多线程分块加速下载原始流"""
    t0 = time.time()
    chunk_size = 2 * 1024 * 1024  # 2MB 分块
    num_chunks = (total_size + chunk_size - 1) // chunk_size

    with open(target_path, 'wb') as f:
        f.seek(total_size - 1)
        f.write(b'\0')

    downloaded = 0
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=num_threads)
    last_log = time.time()

    def fetch_chunk(idx):
        nonlocal downloaded, last_log
        start = idx * chunk_size
        end = min((idx + 1) * chunk_size - 1, total_size - 1)
        headers = {'Range': f'bytes={start}-{end}'}
        for attempt in range(5):
            try:
                r = requests.get(url, headers=headers, timeout=30)
                if r.status_code in [200, 206]:
                    with open(target_path, 'r+b') as f:
                        f.seek(start)
                        f.write(r.content)
                    downloaded += len(r.content)
                    now = time.time()
                    if now - last_log > 6:
                        pct = (downloaded / total_size) * 100
                        speed = (downloaded / (1024*1024)) / max(now - t0, 0.1)
                        log(f"  -> 下载进度: {downloaded/(1024*1024):.1f}/{total_size/(1024*1024):.1f} MB ({pct:.1f}%), 速度: {speed:.2f} MB/s")
                        last_log = now
                    return True
            except Exception:
                time.sleep(1)
        raise RuntimeError(f"分块 {idx} 下载失败超过重试限制")

    futures = [executor.submit(fetch_chunk, i) for i in range(num_chunks)]
    concurrent.futures.wait(futures)
    executor.shutdown()

    total_time = time.time() - t0
    avg_speed = (total_size / (1024 * 1024)) / max(total_time, 0.1)
    log(f"  -> 下载完成，耗时 {total_time:.1f}s，平均速度: {avg_speed:.2f} MB/s")

def remux_to_mp4(input_path, output_path):
    """FFmpeg 流复制无损转封装"""
    t0 = time.time()
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-c", "copy",
        "-movflags", "+faststart",
        output_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg 转封装失败: {res.stderr.decode('utf-8', errors='ignore')}")
    cost = time.time() - t0
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    log(f"  -> FFmpeg 无损转封装完成，耗时 {cost:.1f}s (MP4大小: {size_mb:.1f} MB)")

def convert_folder(parent_id, work_dir=None, clean_old=True):
    cfg = load_config()
    client = PikPakClient(token=cfg.get("pikpak_token"))
    work_dir = work_dir or cfg.get("default_work_dir")
    os.makedirs(work_dir, exist_ok=True)

    log(f"=== 开始扫描文件夹: {parent_id} ===")
    res = client.list_files(parent_id=parent_id, limit=100)
    files = res.get("files", [])
    m3u8_files = [f for f in files if f.get("name", "").endswith(".m3u8")]

    log(f"发现待转封装 M3U8 文件: {len(m3u8_files)} 个")
    if not m3u8_files:
        log("没有待处理的 M3U8 文件。")
        return

    for idx, f in enumerate(m3u8_files, 1):
        fid = f["id"]
        fname = f["name"]
        target_name = fname[:-5] + ".mp4" if fname.endswith(".m3u8") else fname + ".mp4"

        # 详细信息拿真实下载直链与字节数
        f_detail = client.get_file(fid)
        download_url = f_detail.get("web_content_link")
        fsize = int(f_detail.get("size", 0))

        log("\n" + "=" * 50)
        log(f"[{idx}/{len(m3u8_files)}] 正在处理: {fname} ({fsize / (1024*1024):.2f} MB)")

        local_ts = os.path.join(work_dir, f"temp_{int(time.time())}.ts")
        local_mp4 = os.path.join(work_dir, f"converted_{int(time.time())}.mp4")

        try:
            # 1. 多线程下载原始 TS 流
            download_file_multithread(download_url, local_ts, fsize)

            # 2. FFmpeg 复制封装转为 MP4
            remux_to_mp4(local_ts, local_mp4)

            # 3. 立即删除中间 TS 释放空间
            safe_remove(local_ts)

            # 4. 直连分片回传到 PikPak
            log("  -> 开始直连回传 PikPak...")
            def progress(p, total, sp):
                log(f"    分片 [{p}/{total}] 成功 ({(p/total)*100:.1f}%), 速度: {sp:.2f} MB/s")

            new_id, is_rapid = multipart_upload_to_pikpak(
                local_mp4, target_name, parent_id, cfg["pikpak_token"], progress_cb=progress
            )
            status_desc = "秒传命中瞬间转存" if is_rapid else "分片上传完毕并已入库"
            log(f"  -> 云端新 MP4 就绪 ({status_desc}, ID: {new_id})")

            # 5. 清理云端原 M3U8
            if clean_old:
                log("  -> 将旧 M3U8 移入云端回收站...")
                client.delete_files([fid])
                log("  -> 旧文件已移入云端回收站！")

        finally:
            # 6. 本地严格清理保障零残留
            safe_remove(local_ts)
            safe_remove(local_mp4)
            log("  -> 本地临时缓存已清理，零磁盘占用。")

    log("\n" + "=" * 50)
    log(f"=== 全部 {len(m3u8_files)} 个视频转封装任务圆满完成！ ===")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PikPak M3U8 无损极速转封装并回传工具")
    parser.add_argument("--folder", required=True, help="PikPak 目标文件夹 ID")
    parser.add_argument("--work-dir", default=None, help="本地临时工作目录")
    parser.add_argument("--no-clean", action="store_true", help="不删除云端原 m3u8 文件")
    args = parser.parse_args()

    convert_folder(args.folder, work_dir=args.work_dir, clean_old=not args.no_clean)
