"""
PikPak 官方 MCP 协议与 REST API 客户端
不包含任何硬编码凭据，由 core.config 统一注入
"""

import sys
import json
import requests
from core.config import load_config

MCP_URL = "https://pikpak.ai/mcp"
DRIVE_API_BASE = "https://api-drive.mypikpak.com/drive/v1"

class PikPakClient:
    def __init__(self, token=None, base_url=MCP_URL):
        cfg = load_config()
        self.token = token or cfg.get("pikpak_token", "")
        if not self.token:
            raise ValueError("未检测到有效的 PikPak Token，请在 config.json 中配置 pikpak_token 或设置环境变量 PIKPAK_TOKEN")
        
        self.base_url = base_url
        self.session_id = None
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.msg_id = 1
        self._init_session()

    def _init_session(self):
        init_payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pikpak-lesson-client", "version": "1.0.0"}
            }
        }
        resp = requests.post(self.base_url, headers=self.headers, json=init_payload, timeout=15)
        resp.raise_for_status()
        self.session_id = resp.headers.get("mcp-session-id")
        if self.session_id:
            self.headers["mcp-session-id"] = self.session_id
        requests.post(
            self.base_url,
            headers=self.headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            timeout=15
        )

    def _next_id(self):
        cur = self.msg_id
        self.msg_id += 1
        return cur

    def call_tool(self, tool_name, arguments=None):
        if arguments is None:
            arguments = {}
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        resp = requests.post(self.base_url, headers=self.headers, json=payload, timeout=25)
        resp.raise_for_status()
        res = resp.json()
        if "error" in res:
            raise RuntimeError(f"MCP 错误: {res['error']}")
        content_items = res.get("result", {}).get("content", [])
        if content_items and content_items[0].get("type") == "text":
            text = content_items[0].get("text", "")
            try:
                return json.loads(text)
            except Exception:
                return text
        return res.get("result")

    # 快捷方法封装
    def list_files(self, parent_id="", limit=100):
        args = {"limit": limit}
        if parent_id:
            args["parent_id"] = parent_id
        return self.call_tool("ls", args)

    def get_file(self, file_id):
        return self.call_tool("get", {"id": file_id})

    def rename(self, file_id, new_name):
        return self.call_tool("rename", {"id": file_id, "name": new_name})

    def delete_files(self, file_ids):
        return self.call_tool("rm", {"ids": file_ids})

    def account_info(self):
        return self.call_tool("account_info")
