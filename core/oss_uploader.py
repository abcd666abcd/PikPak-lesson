"""
阿里云 OSS 直连分片上传与迅雷 GCID 秒传算法模块
关键特性：
1. 强制直连 OSS 节点，防止本地 HTTP/SOCKS 代理引发长连接写入超时 (10054)；
2. 10MB 分片 Multipart Upload，支持重试；
3. 迅雷 GCID 计算，命中网盘秒传池时秒级完成。
"""

import os
import sys
import time
import hashlib
import hmac
import base64
import requests
import xml.etree.ElementTree as ET
from email.utils import formatdate

# 强制直连代理，规避本地代理的 Socket 写入超时
DIRECT_PROXIES = {"http": None, "https": None}

def gcid_hash_file(path):
    """计算迅雷 GCID Hash，用于 PikPak 文件秒传与一致性校验"""
    h = hashlib.sha1()
    size = os.path.getsize(path)
    psize = 0x40000
    while size / psize > 0x200 and psize < 0x200000:
        psize = psize << 1
    with open(path, 'rb') as stream:
        data = stream.read(psize)
        while data:
            h.update(hashlib.sha1(data).digest())
            data = stream.read(psize)
    return h.hexdigest().upper()

def robust_post(url, headers, payload, max_retries=5):
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=35)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt == max_retries:
                raise
            time.sleep(2)

def multipart_upload_to_pikpak(file_path, target_name, parent_id, token, progress_cb=None):
    """
    分片上传本地文件到 PikPak (结合阿里云 OSS STS 临时凭据)
    :param file_path: 本地待上传文件绝对路径
    :param target_name: 网盘中展示的文件名
    :param parent_id: 目标网盘文件夹 ID
    :param token: PikPak Bearer Token
    :param progress_cb: 可选的进度回调函数 progress_cb(cur_part, total_parts, speed_mb_s)
    :return: 网盘新建文件的 ID
    """
    fsize = os.path.getsize(file_path)
    fhash = gcid_hash_file(file_path)

    # 1. 向 PikPak 申请上传槽位或触发秒传
    create_url = "https://api-drive.mypikpak.com/drive/v1/files"
    create_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "kind": "drive#file",
        "name": target_name,
        "size": str(fsize),
        "hash": fhash,
        "parent_id": parent_id,
        "upload_type": "UPLOAD_TYPE_RESUMABLE"
    }

    res_data = robust_post(create_url, create_headers, payload)

    # 命中秒传直接返回
    if "file" in res_data and res_data.get("file", {}).get("phase") == "PHASE_TYPE_COMPLETE":
        return res_data["file"]["id"], True

    params = res_data["resumable"]["params"]
    ak = params["access_key_id"]
    sk = params["secret_access_key"]
    st = params["security_token"]
    bucket = params["bucket"]
    key = params["key"]
    endpoint = params["endpoint"]

    base_url = f"https://{bucket}.{endpoint}/{key}"

    def oss_sign(method, subres, headers_dict):
        date_str = headers_dict.get("Date", "")
        oss_headers = []
        for k in sorted(headers_dict.keys()):
            if k.lower().startswith("x-oss-"):
                oss_headers.append(f"{k.lower()}:{headers_dict[k]}")
        canonical_oss = "\n".join(oss_headers) + "\n" if oss_headers else ""
        canonical_res = f"/{bucket}/{key}{subres}"
        string_to_sign = f"{method}\n\n\n{date_str}\n{canonical_oss}{canonical_res}"
        h = hmac.new(sk.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1)
        return f"OSS {ak}:{base64.b64encode(h.digest()).decode('utf-8')}"

    # 2. Initiate Multipart Upload
    date_val = formatdate(timeval=None, localtime=False, usegmt=True)
    init_headers = {
        "Date": date_val,
        "x-oss-security-token": st
    }
    init_headers["Authorization"] = oss_sign("POST", "?uploads", init_headers)
    resp = requests.post(f"{base_url}?uploads", headers=init_headers, proxies=DIRECT_PROXIES, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    upload_id = root.find("{http://doc.oss-cn-hangzhou.aliyuncs.com}UploadId").text

    # 3. 分片上传 (10MB 块)
    part_size = 10 * 1024 * 1024
    total_parts = (fsize + part_size - 1) // part_size
    parts = []

    with open(file_path, 'rb') as f:
        for part_number in range(1, total_parts + 1):
            chunk_data = f.read(part_size)
            chunk_len = len(chunk_data)

            success = False
            for retry in range(5):
                t0 = time.time()
                date_val = formatdate(timeval=None, localtime=False, usegmt=True)
                part_headers = {
                    "Date": date_val,
                    "Content-Length": str(chunk_len),
                    "x-oss-security-token": st
                }
                subres = f"?partNumber={part_number}&uploadId={upload_id}"
                part_headers["Authorization"] = oss_sign("PUT", subres, part_headers)

                try:
                    resp_part = requests.put(
                        f"{base_url}{subres}",
                        headers=part_headers,
                        data=chunk_data,
                        proxies=DIRECT_PROXIES,
                        timeout=90
                    )
                    resp_part.raise_for_status()
                    etag = resp_part.headers.get("ETag", "").strip('"')
                    parts.append((part_number, etag))
                    success = True
                    cost = max(time.time() - t0, 0.05)
                    speed = (chunk_len / (1024 * 1024)) / cost
                    if progress_cb:
                        progress_cb(part_number, total_parts, speed)
                    break
                except Exception:
                    time.sleep(2)

            if not success:
                raise RuntimeError(f"分片 {part_number}/{total_parts} 上传失败超过上限")

    # 4. Complete Multipart Upload
    parts_xml = ["<CompleteMultipartUpload>"]
    for p_num, etag in sorted(parts, key=lambda x: x[0]):
        parts_xml.append(f"  <Part><PartNumber>{p_num}</PartNumber><ETag>\"{etag}\"</ETag></Part>")
    parts_xml.append("</CompleteMultipartUpload>")
    complete_xml_body = "\n".join(parts_xml).encode("utf-8")

    date_val = formatdate(timeval=None, localtime=False, usegmt=True)
    comp_headers = {
        "Date": date_val,
        "Content-Type": "application/xml",
        "Content-Length": str(len(complete_xml_body)),
        "x-oss-security-token": st
    }
    comp_subres = f"?uploadId={upload_id}"
    comp_headers["Authorization"] = oss_sign("POST", comp_subres, comp_headers)

    comp_resp = requests.post(f"{base_url}{comp_subres}", headers=comp_headers, data=complete_xml_body, proxies=DIRECT_PROXIES, timeout=60)
    comp_resp.raise_for_status()

    # 5. 轮询云端确认入库
    task_id = res_data.get("task", {}).get("id")
    if task_id:
        task_url = f"https://api-drive.mypikpak.com/drive/v1/tasks/{task_id}"
        for _ in range(30):
            t_resp = requests.get(task_url, headers=create_headers, timeout=15)
            if t_resp.status_code == 200:
                t_json = t_resp.json()
                if t_json.get("phase") == "PHASE_TYPE_COMPLETE":
                    return t_json.get("file_id"), False
            time.sleep(1.5)

    return res_data.get("file", {}).get("id"), False
