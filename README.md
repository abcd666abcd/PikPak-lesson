# PikPAK-lesson: PikPak 云盘自动化运维与流媒体转码实战

一套专为 **PikPak 云盘** 打造的高性能、自动化运维与流媒体转封装工程体系，旨在解决网盘离线下载后产生的格式混乱、Telegram 转存命名丢失、大文件上传超时以及跨设备远程管理等痛点。

---

## 🌟 核心特性

1. **⚡ 极速无损转封装 (Zero Quality Loss)**
   - 深入剖析 PikPak 离线产生的 `.m3u8` 文件本质（单一 MPEG-TS 流）。
   - 采用 FFmpeg 流复制模式 (`-c copy -movflags +faststart`)，数秒内完成数百兆视频的封装转换，**画质与音轨 100% 原样保真**，避免耗时费卡的二次重编码。
2. **🚀 阿里云 OSS 直连分片上传 (Bypass Proxy Trap)**
   - 彻底解决本地 HTTP 代理导致的大文件上传写入超时 (`WinError 10054` / `Connection Reset`)。
   - 完整实现 10MB 分片 Multipart Upload（STS 临时凭证解析、HMAC-SHA1 签名与 XML 合并）。
   - 内置迅雷 GCID 哈希算法，命中网盘秒传池时秒级完成。
3. **🧹 严格的零磁盘占用流转 (Zero Disk Footprint)**
   - 边下载、边封装、边上传、边删除，任意时刻本地磁盘仅保留当前单个流转文件。
   - 结合 Windows 文件句柄锁容错重试机制，任务执行完毕后本地工作目录彻底清空。
4. **🏷️ Telegram 转存乱序视频智能重命名**
   - 解决 Telegram 官方机器人转存时，因图文混发导致的随机临时名（`tmp...mp4`）与长串截断名。
   - 自动追溯文件属性中的 TG 原帖链接，根据入库毫秒级时间戳（`created_time`）正序 1:1 精准对齐文案分集。
   - 全云端 API 秒级重命名，零宽带下载。
5. **🤖 手机端 Telegram 远程遥控守护中枢 (本地电脑Gemini)**
   - 提供开箱即用的轻量 Telegram Bot，常驻本地后台。
   - 手机随手发送指令即可在电脑端执行网盘巡检、格式转码、智能重命名，并支持 PowerShell 命令远程调用。
   - 内置唯一用户 ID 白名单鉴权，杜绝安全隐患。

---

## 📁 目录结构

```text
PikPAK-lesson/
├── README.md               # 项目主说明文档
├── AGENTS.md               # 面向 AI Coding Agent 的开发规范与架构手册
├── config.example.json     # 配置模板文件（开源脱敏）
├── .gitignore              # Git 忽略文件（锁定敏感凭据与本地缓存）
│
├── core/                   # 核心基础库
│   ├── config.py           # 统一配置加载器
│   ├── pikpak_client.py    # PikPak 官方 MCP 协议与 REST API 客户端
│   └── oss_uploader.py     # 阿里云 OSS 直连分片上传器与迅雷 GCID 算法
│
├── tools/                  # 业务命令行工具集
│   ├── remux_mp4.py        # M3U8/TS 无损流复制转真 MP4 并回传工具
│   ├── tg_renamer.py       # 依据 Telegram 原帖文案批量智能重命名工具
│   └── check_folder.py     # 网盘指定文件夹快速巡检工具
│
├── bot/                    # 远程交互服务
│   └── tg_bot.py           # 【本地电脑Gemini】Telegram 交互守护程序
│
└── docs/                   # 进阶技术解析与避坑实录
    ├── 01-m3u8-remux.md    # M3U8 无损封装原理与生命周期设计
    ├── 02-oss-proxy-trap.md# 阿里云 OSS 代理 10054 超时排障与分片上传
    └── 03-telegram-flow.md # Telegram 转存闭环工作流最佳实践
```

---

## 🛠️ 快速开始

### 1. 环境准备
- **Python**: 3.10+
- **本地工具**: FFmpeg（需配置在系统 `PATH` 环境变量中）
- **依赖安装**:
  ```bash
  pip install requests pyTelegramBotAPI beautifulsoup4
  ```

### 2. 配置文件初始化
复制模板文件 `config.example.json` 为 `config.json`（该文件已被 `.gitignore` 自动忽略，安全不泄露）：
```bash
copy config.example.json config.json
```
在 `config.json` 中填入你的参数：
```json
{
  "pikpak_token": "你的_PikPak_Bearer_Token",
  "telegram_bot_token": "你的_Telegram_Bot_Token",
  "telegram_allowed_user_id": 123456789,
  "proxy_url": "http://127.0.0.1:7890",
  "default_work_dir": "D:\\aria2\\新建文件夹"
}
```

---

## 💻 核心工具使用示例

### 1. 巡检网盘指定文件夹
```bash
python tools/check_folder.py --folder <文件夹ID>
```

### 2. 批量将文件夹内 M3U8 无损转真 MP4 并回传
```bash
python tools/remux_mp4.py --folder <文件夹ID>
```

### 3. Telegram 视频智能重命名 (支持 Dry-Run 预览)
```bash
# 仅预览拟重命名列表
python tools/tg_renamer.py --folder <文件夹ID> --prefix "合集名-" --dry-run

# 真正执行云端改名
python tools/tg_renamer.py --folder <文件夹ID> --prefix "合集名-"
```

### 4. 启动 Telegram 远程运维机器人
```bash
python bot/tg_bot.py
```
启动后，可在手机 Telegram 向机器人发送：
- `/status`：查看电脑 CPU、磁盘空间及运行状态；
- `/account`：查看 PikPak 空间配额；
- `/ls <文件夹ID>`：远程查看网盘内容；
- `/cmd <PowerShell命令>`：远程执行电脑终端指令。

---

## 📚 深度技术文档

* [01. PikPak 云端 M3U8 的本质认知与极速无损转封装](docs/01-m3u8-remux.md)
* [02. 阿里云 OSS 直连上传陷阱与迅雷 GCID 秒传算法](docs/02-oss-proxy-trap.md)
* [03. Telegram 资源转存乱象溯源与全自动运维闭环](docs/03-telegram-flow.md)

---

## 📄 开源许可证
本项目基于 [MIT License](LICENSE) 开源。请遵守各平台服务协议与本地法律法规，仅用于个人合法数据管理。
