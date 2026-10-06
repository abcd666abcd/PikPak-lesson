# 02. 阿里云 OSS 直连上传陷阱与迅雷 GCID 秒传算法

> 核心经验：往 PikPak 绑定的阿里云 OSS 节点上传大文件时，必须强制绕过本地 HTTP/SOCKS 代理直连；文件大于 100MB 时禁止单次 PUT，必须采用标准分片上传（Multipart Upload）。

---

## 1. 致命排障复盘：本地代理引发的 10054 写入超时

### 故障现象
在使用 Python 的 `requests` 库或命令行向 PikPak 申请的阿里云 OSS STS 临时上传节点（如 `vip-lixian-07.mypikpak.com`）执行大文件上传时，经常在上传到 10%~30% 时抛出致命网络异常：
- `ConnectionResetError: [WinError 10054] 远程主机强迫关闭了一个现有的连接`
- `requests.exceptions.ConnectionError: The write operation timed out`

### 根因分析
在很多开发者的 Windows 机器上，通常运行有本地网络代理软件（如 Clash、v2ray，端口 `7890`），且系统环境变量中配置了 `HTTP_PROXY` 和 `HTTPS_PROXY`。
- Python 的 `requests` 库在发起 HTTPS 请求时，会自动读取环境变量并通过本地代理服务器转发。
- 阿里云 OSS 的上传节点对长连接的大包写入极其敏感。通过本地代理建立的二级隧道传输几百兆视频数据流时，本地代理客户端的连接池与缓冲区容易发生 Socket 写入阻塞或被远端 OSS 判定连接超时主动切断（RST），从而直接报 10054。

### 终极解决方案：强制直连
向阿里云 OSS 发起任何数据传输请求时，**必须显式禁用代理**，强制建立直连 TCP 通道：
```python
DIRECT_PROXIES = {"http": None, "https": None}

# 上传分片时强制指定 proxies
response = requests.put(part_url, data=chunk_data, proxies=DIRECT_PROXIES, timeout=90)
```
实测直连后，全国各网络环境下上传速率均稳定在 1.2 MB/s ~ 3.5 MB/s 以上，再无一次 10054 异常。

---

## 2. 大文件分片上传 (Multipart Upload) 标准实现

PikPak 接口在上传大于 100MB 的文件时，若直接使用单次 PUT 上传，不仅极易断连，且断连后必须从零重新上传。必须采用标准的 S3 / 阿里云 OSS 分片上传协议：

### 阶段 1：申请槽位并提取 STS 凭证
调用 `POST https://api-drive.mypikpak.com/drive/v1/files`，携带文件元数据（大小、哈希、父目录），获取返回的 `resumable.params`：
- `access_key_id`
- `secret_access_key`
- `security_token`
- `bucket`, `key`, `endpoint`

### 阶段 2：初始化分片上传 (Initiate Multipart Upload)
```http
POST https://{bucket}.{endpoint}/{key}?uploads HTTP/1.1
x-oss-security-token: {security_token}
Authorization: OSS {ak}:{signature}
```
OSS 会返回一个唯一的 XML 响应，其中包含 `<UploadId>...</UploadId>`。

### 阶段 3：按 10MB 分片循环上传 (Upload Part)
将视频文件切分成 10MB 分块：
```http
PUT https://{bucket}.{endpoint}/{key}?partNumber={1..N}&uploadId={upload_id} HTTP/1.1
Content-Length: {chunk_len}
x-oss-security-token: {security_token}
Authorization: OSS {ak}:{signature}
```
记录每个分片上传成功后 OSS 返回响应头中的 `ETag`。

### 阶段 4：合并分片 (Complete Multipart Upload)
将所有收集到的 `PartNumber` 和 `ETag` 组装为 XML 发送合并请求：
```xml
<CompleteMultipartUpload>
  <Part><PartNumber>1</PartNumber><ETag>"..."</ETag></Part>
  <Part><PartNumber>2</PartNumber><ETag>"..."</ETag></Part>
</CompleteMultipartUpload>
```
OSS 在服务端瞬间组装完整文件。

---

## 3. 迅雷 GCID 秒传算法原理

PikPak 支持与迅雷相同的 GCID（Global Content Identifier）哈希算法。在上传大文件前计算其 GCID，并在创建文件时提交：
- 如果云端文件库中已存在相同 GCID 的文件，PikPak 会在创建槽位时直接返回 `phase: PHASE_TYPE_COMPLETE`；
- 无需上传任何分片，实现 **0 耗时瞬间转存入库**。

### Python GCID 计算算法实现
```python
import os
import hashlib

def gcid_hash_file(path):
    h = hashlib.sha1()
    size = os.path.getsize(path)
    psize = 0x40000  # 初始块大小 256KB
    while size / psize > 0x200 and psize < 0x200000:
        psize = psize << 1
    with open(path, 'rb') as stream:
        data = stream.read(psize)
        while data:
            h.update(hashlib.sha1(data).digest())
            data = stream.read(psize)
    return h.hexdigest().upper()
```
