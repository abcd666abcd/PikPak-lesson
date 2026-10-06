# PikPAK-lesson Agent 指南与架构手册 (AGENTS.md)

本文件专供 AI Coding Agent 跨会话读取，记录本项目的设计规范、开发约定与排障经验。所有业务逻辑与运维规则均在此文件内自闭环，不依赖且不污染全局配置。

---

## 1. 项目概览与目录架构

```text
PikPAK-lesson/
├── .gitignore               # 严格的安全过滤规则，严禁将 config.json 和 token 推送至远端
├── config.example.json      # 开源配置样例模板（脱敏）
├── config.json              # 本地专属配置文件（git ignored，存放本地真实凭据）
├── README.md                # 面向人类开发者的项目说明
├── AGENTS.md                # 本文件，面向 AI Agent 的工程规范与设计约定
│
├── core/                    # 核心基础层
│   ├── config.py            # 配置加载器（自动兼容本地 config.json 与环境变量）
│   ├── pikpak_client.py     # PikPak 官方 MCP 协议与 REST API 客户端
│   └── oss_uploader.py      # 阿里云 OSS 直连分片上传器与迅雷 GCID 秒传算法
│
├── tools/                   # 业务 CLI 工具集
│   ├── remux_mp4.py         # M3U8/TS 无损流复制转真 MP4 并回传网盘
│   ├── tg_renamer.py        # 依据 Telegram 原帖元数据智能重命名网盘视频
│   └── check_folder.py      # 网盘指定文件夹快速巡检工具
│
├── bot/                     # 远程交互层
│   └── tg_bot.py            # 【本地电脑Gemini】Telegram 交互守护程序
│
└── docs/                    # 核心经验与避坑文档
    ├── 01-m3u8-remux.md     # M3U8 无损封装原理
    ├── 02-oss-proxy-trap.md # 阿里云 OSS 代理 10054 超时排障与分片上传
    └── 03-telegram-flow.md  # Telegram 转存闭环工作流
```

---

## 2. 核心设计原则与安全红线 (不可违反)

1. **凭证隔离与开源安全**：
   - **绝对禁止**在任何代码、文档或日志中硬编码 PikPak Token、Telegram Bot Token、个人 User ID 等真实密钥。
   - 所有凭证统一由 `core.config.load_config()` 加载。
   - 提交 Git 仓库前必须确认 `config.json` 处于 `.gitignore` 保护之下。

2. **网络直连铁律 (规避 10054)**：
   - 向阿里云 OSS 上传分片时，必须使用 `DIRECT_PROXIES = {"http": None, "https": None}` 强制绕过本地代理。
   - 严禁通过本地 HTTP 代理（7890 等）传输大文件，否则会报 `ConnectionResetError 10054`。

3. **零本地磁盘残留承诺**：
   - 执行视频格式转换时，必须严格执行单文件闭环流水线（下载单个 -> FFmpeg 转封装 -> 直传 -> 立即删除临时文件）。
   - Windows 环境下删除文件需增加 `PermissionError` 容错重试。任务执行完毕后本地工作目录必须彻底清空。

4. **无损极速转封装**：
   - PikPak 离线产生的 M3U8 实质为 MPEG-TS 单流，严禁使用 `libx264` 二次重编码。
   - 必须使用 `ffmpeg -y -i input.ts -c copy -movflags +faststart output.mp4` 进行无损流复制。

5. **用户隐私规范**：
   - 遇到敏感视频文件时，严禁在交互界面和终端日志中直接输出露骨标题，必须进行脱敏或通配处理。

---

## 3. 常用运维与调用命令

```bash
# 1. 巡检指定文件夹内容
python tools/check_folder.py --folder <文件夹ID>

# 2. 批量将文件夹内的 M3U8 转封装为真 MP4 并回传
python tools/remux_mp4.py --folder <文件夹ID>

# 3. 依据 Telegram 原帖文案进行云端智能重命名 (支持 Dry-Run 预览)
python tools/tg_renamer.py --folder <文件夹ID> --prefix "30岁堂姐-" --dry-run
python tools/tg_renamer.py --folder <文件夹ID> --prefix "30岁堂姐-"

# 4. 启动 Telegram 远程运维机器人守护进程
python bot/tg_bot.py
```
