"""麦麦钱包插件 — MaiBot v2 插件

功能：
- 通过配置的余额接口（GET 请求）获取指定 API Key 的账户余额 JSON。
- 通过配置的模型接口（llm_url；OpenAI 兼容系列自动补全 /chat/completions，
  其余原样使用）使用 LLM（默认 deepseek v4 flash）将返回的 JSON 总结为
  清晰的中文报告。
- 客户端兼容格式切换：client_type 决定请求体格式与响应解析（openai /
  anthropic / gemini / cohere / deepseek / xai / mistral / huggingface /
  baidu），与认证方式（auth_header）自由组合，可跑通大部分 API 平台；
  send_max_tokens 可关闭请求体中的 max_tokens（部分上游模型不接受）。
- 指令 /wallet：实时获取余额并返回信息式结果（单条信息合并转发发出，需声明
  send.forward 能力），同时会覆盖/更新本地缓存。
- LLM 工具 get_api_balance：查看你的钱包余额（相当于 bot 的饭钱/微信余额），
  用户提及钱包余额、存款、饭钱等话题时调用。工具调用优先使用本地缓存
  （默认每 2 小时才通过 API 获取一次新数据，超期才实时刷新），返回不显示时间戳。

配置结构（v1.0.1 起）：
- [balance] 查询配置：查余额平台的 api_key / api_url；
- [summary] 总结配置：LLM 总结平台的 api_key / summary_model / client_type /
  llm_url / auth_header / max_tokens / send_max_tokens / llm_timeout / cache_minutes；
- 两个 api_key 都为空则不工作；只配置其中一个时自动复用另一个。

超时行为约定：
- 指令查询（/wallet）：LLM 总结超时通过 QQ 信息返回错误，同时控制台打印日志。
- 工具调用（get_api_balance）：LLM 总结超时仅在控制台打印错误日志，不主动发送消息。
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import time
from typing import Any, Dict, List, Tuple
from urllib.parse import quote, urlparse

import httpx

from maibot_sdk import Command, Field, MaiBotPlugin, PluginConfigBase, Tool

# ==================== 常量 ====================

# 配置版本（config_version）：与 _manifest.json 的 version 保持同步。
# config_version 用于检查配置文件（config.toml）是否需要更新：
# 插件升级后若配置结构发生变化，可对比该值触发配置迁移/重建。
SUPPORTED_CONFIG_VERSION = "1.0.1"

# 默认余额查询接口（DeepSeek 开放平台）
DEFAULT_BALANCE_URL = "https://api.deepseek.com/user/balance"

# 默认模型接口 URL（OpenAI 兼容系列：可填基础地址，自动补全 /chat/completions，
# 或填完整端点直接使用）。
# 余额查询接口（api_url）与模型接口是不同 API，需单独设置。
DEFAULT_LLM_URL = "https://api.deepseek.com/chat/completions"

# 默认客户端类型（决定请求体格式与响应解析，不参与 URL 拼接）
DEFAULT_CLIENT_TYPE = "deepseek"

# 默认总结模型（DeepSeek 开放平台所提供的模型）
DEFAULT_SUMMARY_MODEL = "deepseek v4 flash"

# 默认认证方式："请求头名: 前缀"，余额接口为 GET、模型接口为 POST
DEFAULT_AUTH_SPEC = "Authorization: Bearer"

# 默认最大输出 token 数
DEFAULT_MAX_TOKENS = 4096

# 默认 LLM 超时时间（秒）
DEFAULT_LLM_TIMEOUT = 60

# 工具调用获取余额的默认缓存间隔（分钟）：2 小时
DEFAULT_CACHE_MINUTES = 120

# 余额接口 HTTP 请求超时（秒），独立于 LLM 超时
HTTP_TIMEOUT = 20

# OpenAI 兼容客户端类型（请求体与响应均为 OpenAI Chat Completions 格式）。
# 这些平台的 chat 端点均为 <基础地址>/chat/completions 结构：
# 若配置的 llm_url 以 /v1、/v2 或其它基础路径结尾（如 https://api.commandcode.ai/provider/v1），
# 会自动补全 /chat/completions（例如 Command Code 官方端点
# https://api.commandcode.ai/provider/v1/chat/completions）。
OPENAI_COMPATIBLE_CLIENTS = ("openai", "deepseek", "xai", "mistral", "huggingface", "baidu")

# 默认提示词（每一项为一行，代码读取时自动拼接；
# 尾部 "JSON数据：" 与 {json_data} 两行不写入配置项，由代码在拼接后自动补充）
DEFAULT_PROMPT_LINES: List[str] = [
    "请总结以下DeepSeek账户余额查询结果的JSON数据，提取关键信息：",
    "1. 账户是否可用（is_available）",
    "2. 各币种的总额、赠金和充值余额",
    "3. 用清晰的中文列出，标注币种，余额保留两位小数",
]

# LLM 总结失败的错误类型
class LLMTimeoutError(Exception):
    """LLM 总结超时。"""


class LLMError(Exception):
    """LLM 总结失败（非超时）。"""


# ==================== 配置模型 ====================


class PluginSectionConfig(PluginConfigBase):
    __ui_label__ = "插件"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(
        default=SUPPORTED_CONFIG_VERSION,
        description="配置版本（与插件版本同步，用于检查配置文件是否需要更新）",
        json_schema_extra={
            "disabled": True,
            "hidden": True,
            "label": "配置版本",
        },
    )


class BalanceQueryConfig(PluginConfigBase):
    """查询配置：要查余额的 API 平台及其凭据。"""

    __ui_label__ = "查询配置"
    __ui_icon__ = "account_balance_wallet"
    __ui_order__ = 1

    api_key: str = Field(
        default="",
        description=(
            "要获取余额的 API Key（查询平台的凭据，默认为空）。"
            "与「总结配置」的 api_key 二选一即可：只配其中一个时自动复用另一个"
        ),
    )
    api_url: str = Field(
        default=DEFAULT_BALANCE_URL,
        description="API Key 余额查询接口 URL（GET 请求），默认为 DeepSeek 开放平台",
    )


class SummaryConfig(PluginConfigBase):
    """总结配置：把余额 JSON 交给 LLM 总结的模型平台及其凭据。"""

    __ui_label__ = "总结配置"
    __ui_icon__ = "smart_toy"
    __ui_order__ = 2

    api_key: str = Field(
        default="",
        description=(
            "LLM 总结用的 API Key（模型平台的凭据，默认为空）。"
            "与「查询配置」的 api_key 二选一即可：只配其中一个时自动复用另一个"
        ),
    )
    summary_model: str = Field(
        default=DEFAULT_SUMMARY_MODEL,
        description=(
            "总结余额 JSON 的模型名（模型接口中的 model 字段）。"
            "默认使用余额获取平台所提供的模型（deepseek v4 flash）"
        ),
    )
    client_type: str = Field(
        default=DEFAULT_CLIENT_TYPE,
        description=(
            "客户端兼容格式（决定模型接口的请求体格式与响应解析，不参与 URL 拼接）："
            "openai / anthropic / gemini / cohere / deepseek / xai / mistral / "
            "huggingface / baidu。与认证方式（auth_header）自由组合，"
            "可跑通大部分 API 平台；详见 README 平台对应表"
        ),
    )
    llm_url: str = Field(
        default=DEFAULT_LLM_URL,
        description=(
            "模型接口 URL。OpenAI 兼容系列（openai/deepseek/xai/mistral/"
            "huggingface/baidu）自动补全 /chat/completions：可填基础地址"
            "（如 https://api.commandcode.ai/provider/v1）或完整端点"
            "（如 https://api.deepseek.com/chat/completions）；非 OpenAI 兼容"
            "系列（anthropic/gemini/cohere）原样使用。支持 {model} 占位符"
            "（用于模型名需出现在 URL 中的平台，如 Gemini）；"
            "余额查询接口（api_url）与模型接口是不同 API，需单独设置"
        ),
    )
    auth_header: str = Field(
        default=DEFAULT_AUTH_SPEC,
        description=(
            "认证方式：'请求头名: 前缀' 格式（模型接口为 POST，余额接口的认证方式"
            "见「查询配置」）。默认为 'Authorization: Bearer'"
            "（即 Authorization: Bearer <API_KEY>）。"
            "常见平台示例：Anthropic 'x-api-key:'、Google 'x-goog-api-key:'、"
            "Portkey 'x-portkey-api-key:'、部分平台 'api-key:'（前缀留空表示直接填 API Key）"
        ),
    )
    max_tokens: int = Field(
        default=DEFAULT_MAX_TOKENS,
        description="LLM 总结时最大输出 token 数",
    )
    send_max_tokens: bool = Field(
        default=False,
        description=(
            "是否在模型请求体中发送 max_tokens 参数（默认 false，不发送，"
            "由平台自动决定输出长度）。部分上游模型不接受 max_tokens"
            "（如 Command Code 的 poolside/laguna-s-2.1-free），会导致 503 错误"
        ),
    )
    llm_timeout: float = Field(
        default=DEFAULT_LLM_TIMEOUT,
        description=(
            "LLM 总结超时时间（秒）。超时后：指令查询通过 QQ 信息返回错误（控制台也打印日志），"
            "工具调用仅在控制台打印错误日志"
        ),
    )
    cache_minutes: int = Field(
        default=DEFAULT_CACHE_MINUTES,
        description=(
            "工具调用获取余额的缓存间隔（分钟，默认 120）。"
            "工具调用时若距上次获取未超过该间隔，直接使用本地缓存数据；"
            "超过则重新调用 API 获取并更新缓存。"
            "指令 /wallet 始终实时获取并覆盖缓存"
        ),
    )


class PromptSectionConfig(PluginConfigBase):
    __ui_label__ = "提示词"
    __ui_icon__ = "notes"
    __ui_order__ = 3

    lines: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PROMPT_LINES),
        description=(
            "总结提示词（每一项为一行，可添加多项，代码读取时自动分行拼接）。"
            "尾部的 'JSON数据：' 与余额 JSON 由代码自动补充，无需在此填写"
        ),
    )


class ApiBalanceConfig(PluginConfigBase):
    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    balance: BalanceQueryConfig = Field(default_factory=BalanceQueryConfig)
    summary: SummaryConfig = Field(default_factory=SummaryConfig)
    prompt: PromptSectionConfig = Field(default_factory=PromptSectionConfig)


# ==================== 插件主体 ====================


class ApiBalancePlugin(MaiBotPlugin):
    """麦麦钱包插件。"""

    config_model = ApiBalanceConfig

    # ==================== 生命周期 ====================

    async def on_load(self) -> None:
        self._check_config_version()
        data_dir = self._get_data_dir()
        os.makedirs(data_dir, exist_ok=True)
        self.ctx.logger.info("麦麦钱包插件已加载，缓存目录：%s", data_dir)

    async def on_unload(self) -> None:
        self.ctx.logger.info("麦麦钱包插件已卸载")

    async def on_config_update(self, scope: str, config_data: Dict[str, Any], version: str) -> None:
        del config_data, version
        if scope == "self":
            self._check_config_version()
            self.ctx.logger.info("麦麦钱包插件配置已更新")

    def _get_data_dir(self) -> str:
        """统一持久化数据目录：Host 注入的插件专属目录 data/plugins/<plugin_id>。"""
        return str(self.ctx.paths.data_dir)

    def _check_config_version(self) -> None:
        """检测配置版本并自动兼容旧版配置文件。

        旧版本缺少新增字段时，Runner 在配置注入时已按默认值自动补齐，
        这里仅做版本检测与日志提示。
        """
        try:
            raw = self.get_plugin_config_data()
            current = str((raw.get("plugin") or {}).get("config_version") or "").strip()
        except Exception:
            return
        if current and current != SUPPORTED_CONFIG_VERSION:
            self.ctx.logger.info(
                "检测到旧版配置（config_version=%s，当前支持 %s），缺失字段已按默认值自动补齐",
                current,
                SUPPORTED_CONFIG_VERSION,
            )

    # ==================== 认证构造 ====================

    @staticmethod
    def _parse_auth(spec: str) -> Tuple[str, str]:
        """解析 '请求头名: 前缀' 为 (header_name, prefix)。

        示例：
        - "Authorization: Bearer"  -> ("Authorization", "Bearer")
        - "x-api-key:"             -> ("x-api-key", "")
        - "api-key"                -> ("api-key", "")
        """
        spec = str(spec or "").strip()
        if not spec:
            return "Authorization", "Bearer"
        if ":" in spec:
            header, _, prefix = spec.partition(":")
            return header.strip(), prefix.strip()
        return spec.strip(), ""

    def _build_auth_headers(self, api_key: str, auth_spec: str) -> Dict[str, str]:
        """根据 auth_header 配置构造认证请求头。

        Args:
            api_key: 该接口使用的 API Key。
            auth_spec: 认证方式（'请求头名: 前缀'）。
        """
        header_name, prefix = self._parse_auth(auth_spec)
        key = str(api_key or "").strip()
        if prefix:
            header_value = f"{prefix} {key}"
        else:
            header_value = key
        return {header_name: header_value}

    def _get_api_keys(self) -> Tuple[str, str]:
        """返回 (查询用 key, 总结用 key)，支持单 key 复用。

        规则：
        - 两个都配置 → 各自使用；
        - 只配置「查询配置」的 api_key → 总结接口复用该 key；
        - 只配置「总结配置」的 api_key → 查询接口复用该 key；
        - 两个都为空 → 返回 ("", "")，调用方提示未配置。
        """
        balance_key = str(self.config.balance.api_key or "").strip()
        summary_key = str(self.config.summary.api_key or "").strip()
        if not balance_key and summary_key:
            balance_key = summary_key
        elif not summary_key and balance_key:
            summary_key = balance_key
        return balance_key, summary_key

    # ==================== 余额获取 ====================

    @staticmethod
    def _validate_balance_url(api_url: str) -> str:
        """校验余额接口 URL 安全性，返回规范化后的 URL。

        安全约束（防 SSRF / Key 泄露）：
        - 必须是 http/https 且为 https；
        - 拒绝私网/环回/链路本地/云元数据地址（如 127.0.0.1、10.x、169.254.169.254）；
        - 拒绝带用户名密码的 URL。
        不满足时抛 ValueError。
        """
        url = str(api_url or "").strip()
        if not url:
            raise ValueError("余额接口 URL 为空")
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ValueError(f"余额接口仅允许 https，当前: {parsed.scheme or '无'}")
        if parsed.username or parsed.password:
            raise ValueError("余额接口 URL 不允许包含用户名/密码")
        host = parsed.hostname
        if not host:
            raise ValueError("余额接口 URL 缺少主机名")
        # 解析主机名对应的 IP（禁止私网/环回/链路本地/云元数据）
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            raise ValueError(f"余额接口域名无法解析: {host}")
        for info in infos:
            ip = info[4][0]
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_multicast
                or addr.is_reserved
                or addr.is_unspecified
                or (addr.is_global and str(addr).startswith("169.254."))
            ):
                raise ValueError(f"余额接口地址不允许访问: {host} ({ip})")
        return url

    async def _fetch_balance(self, api_key: str, api_url: str) -> Dict[str, Any]:
        """GET 请求余额接口，返回解析后的 JSON（dict）。

        先做 URL 安全校验（仅 https、拒绝私网/元数据地址），防 SSRF 与 Key 泄露。
        """
        safe_url = self._validate_balance_url(api_url)
        headers = self._build_auth_headers(api_key, self.config.balance.auth_header)
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(safe_url, headers=headers)
            resp.raise_for_status()
            return resp.json()

    # ==================== 提示词构建 ====================

    def _build_prompt(self, json_text: str) -> str:
        """先分行拼接配置中的提示词，再在尾部补充 'JSON数据：' 与余额 JSON。"""
        lines = [str(x).strip() for x in (self.config.prompt.lines or []) if str(x).strip()]
        prompt = "\n".join(lines) if lines else ""
        prompt += "\n\nJSON数据：\n" + json_text
        return prompt

    # ==================== LLM 请求构造（按客户端类型） ====================

    @staticmethod
    def _build_llm_url(llm_url: str, model: str, client_type: str) -> str:
        """返回模型接口完整 URL。

        规则：
        - 先做 {model} 占位符替换（模型名需出现在 URL 中的平台，如 Gemini）：
          https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
        - OpenAI 兼容系列（openai/deepseek/xai/mistral/huggingface/baidu）：
          chat 端点统一为 <基础地址>/chat/completions。若配置的 llm_url 未以
          /chat/completions 结尾（如 https://api.commandcode.ai/provider/v1），
          自动补全端点路径 /chat/completions。
        - 非 OpenAI 兼容系列（anthropic/gemini/cohere）：原样使用。
        """
        url = str(llm_url or "").strip()
        if "{model}" in url:
            url = url.replace("{model}", quote(model, safe=""))
        if client_type in OPENAI_COMPATIBLE_CLIENTS:
            if not url.endswith("/chat/completions"):
                url = url.rstrip("/") + "/chat/completions"
        return url

    def _build_llm_request(self, prompt: str, summary_api_key: str) -> Tuple[str, Dict[str, str], Dict[str, Any]]:
        """根据客户端类型构造模型接口请求，返回 (url, headers, payload)。

        llm_url 为接口基础地址（OpenAI 兼容系列自动补全 /chat/completions；
        其余客户端原样使用）；client_type 决定请求体格式与响应解析；
        auth_header 决定认证方式，三者自由组合可跑通大部分平台。
        send_max_tokens 控制是否在请求体中发送 max_tokens（默认 false 不发送，
        由平台自动决定输出长度）：
        - 部分上游不接受 max_tokens（如 Command Code poolside/laguna-s-2.1-free
          会返回 503 overloaded_error），默认不发送已规避此类问题。
        - Anthropic Messages API 的 max_tokens 为必填字段，开关关闭时仍发送
          （使用 DEFAULT_MAX_TOKENS 兜底）。

        注意：本方法使用「总结配置」[summary] 下的模型/URL/认证/API Key；
        余额查询使用「查询配置」[balance] 下的接口与认证（见 _fetch_balance）。
        """
        summary = self.config.summary
        model = str(summary.summary_model or "").strip()
        if not model:
            raise LLMError("未配置总结模型：请在插件配置 [summary] summary_model 中填写")
        max_tokens = int(summary.max_tokens or 0)
        send_max_tokens = bool(getattr(summary, "send_max_tokens", True))
        llm_url = str(summary.llm_url or "").strip()
        if not llm_url:
            raise LLMError("未配置模型接口 URL：请在插件配置 [summary] llm_url 中填写")
        client_type = str(summary.client_type or "").strip().lower()
        headers = self._build_auth_headers(summary_api_key, summary.auth_header)
        url = self._build_llm_url(llm_url, model, client_type)

        if client_type == "anthropic":
            # Anthropic Messages API（POST /v1/messages，x-api-key + anthropic-version）
            # max_tokens 为必填字段，不受 send_max_tokens 开关影响
            headers.setdefault("anthropic-version", "2023-06-01")
            headers["content-type"] = "application/json"
            payload: Dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens if max_tokens > 0 else DEFAULT_MAX_TOKENS,
                "messages": [{"role": "user", "content": prompt}],
            }
            return url, headers, payload

        if client_type == "gemini":
            # Google Gemini generateContent（模型名通常在 URL 中，通过 {model} 占位符）
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
            }
            if send_max_tokens and max_tokens > 0:
                payload["generationConfig"] = {"maxOutputTokens": max_tokens}
            headers["content-type"] = "application/json"
            return url, headers, payload

        if client_type == "cohere":
            # Cohere Chat API（POST /v1/chat）
            payload = {
                "model": model,
                "message": prompt,
            }
            if send_max_tokens and max_tokens > 0:
                payload["max_tokens"] = max_tokens
            headers["content-type"] = "application/json"
            return url, headers, payload

        # OpenAI 兼容系列（openai / deepseek / xai / mistral / huggingface / baidu）
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if send_max_tokens and max_tokens > 0:
            payload["max_tokens"] = max_tokens
        headers["content-type"] = "application/json"
        return url, headers, payload

    # ==================== LLM 响应解析（按客户端类型） ====================

    def _parse_llm_response(self, data: Dict[str, Any], client_type: str) -> str:
        """从各客户端格式的响应中提取文本内容。"""
        if client_type == "anthropic":
            # Anthropic: {"content": [{"type": "text", "text": "..."}]}
            try:
                parts = data.get("content") or []
                return "".join(p.get("text", "") for p in parts if p.get("type") == "text")
            except Exception:
                return ""

        if client_type == "gemini":
            # Gemini: {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}
            try:
                candidates = data.get("candidates") or []
                parts = candidates[0].get("content", {}).get("parts") or []
                return "".join(p.get("text", "") for p in parts)
            except Exception:
                return ""

        if client_type == "cohere":
            # Cohere: {"text": "..."}
            try:
                return str(data.get("text") or "")
            except Exception:
                return ""

        # OpenAI 兼容: {"choices": [{"message": {"content": "..."}}]}
        try:
            choices = data.get("choices") or []
            return str(choices[0].get("message", {}).get("content") or "")
        except Exception:
            return ""

    @staticmethod
    def _diagnose_empty_response(data: Dict[str, Any], client_type: str) -> str:
        """当解析出的文本为空时，诊断可能的原因并返回针对性提示。

        - 思考模型（reasoning 字段）content 为空且 finish_reason=length：
          说明思考过程占满了 max_tokens 上限，回答被截断 → 提示调大 max_tokens
          或关闭 send_max_tokens。
        - 其他情况返回空串，由调用方给出通用提示。
        """
        try:
            if client_type == "anthropic":
                # Anthropic 思考模型：content 可能只有 thinking 块；stop_reason=max_tokens 表示截断
                stop_reason = data.get("stop_reason")
                has_thinking = False
                for p in data.get("content") or []:
                    if p.get("type") in ("thinking", "redacted_thinking"):
                        has_thinking = True
                        break
                if has_thinking and not any(
                    p.get("type") == "text" and str(p.get("text") or "").strip()
                    for p in data.get("content") or []
                ):
                    if stop_reason == "max_tokens":
                        return (
                            "模型思考占满了 max_tokens 上限，正式回答被截断："
                            "请调大 summary.max_tokens，或将 send_max_tokens 设为 false"
                        )
                    return "模型只返回了思考内容而未输出正式回答，请调大 summary.max_tokens 后重试"
                return ""

            # OpenAI 兼容（含 gemini/cohere 的通用检查）
            choices = data.get("choices") or []
            if not choices:
                return ""
            message = choices[0].get("message") or {}
            finish_reason = choices[0].get("finish_reason")
            has_reasoning = bool(
                message.get("reasoning")
                or message.get("reasoning_content")
                or message.get("reasoning_details")
            )
            if has_reasoning and not str(message.get("content") or "").strip():
                if finish_reason == "length":
                    return (
                        "模型思考占满了 max_tokens 上限，正式回答被截断："
                        "请调大 summary.max_tokens，或将 send_max_tokens 设为 false"
                    )
                return "模型只返回了思考内容而未输出正式回答，请调大 summary.max_tokens 后重试"
        except Exception:
            pass
        return ""

    async def _summarize_balance(self, json_text: str, summary_api_key: str) -> str:
        """调用配置的模型接口总结余额 JSON。

        成功返回总结文本；超时抛 LLMTimeoutError；其他失败抛 LLMError。
        模型接口 URL（llm_url，OpenAI 兼容系列自动补全 /chat/completions）、
        客户端格式（client_type，决定请求体格式与响应解析）、模型名
        （summary_model）、认证方式（auth_header）、API Key（summary.api_key，
        为空时复用 balance.api_key）均在「总结配置」[summary] 下，与余额查询
        接口（api_url）无关；client_type 与 auth_header 自由组合可跑通大部分平台。
        """
        prompt = self._build_prompt(json_text)
        llm_timeout = float(self.config.summary.llm_timeout or 0)
        timeout = httpx.Timeout(timeout=llm_timeout if llm_timeout > 0 else DEFAULT_LLM_TIMEOUT)

        url, headers, payload = self._build_llm_request(prompt, summary_api_key)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            raise LLMTimeoutError(
                f"LLM 总结超时（{llm_timeout if llm_timeout > 0 else DEFAULT_LLM_TIMEOUT}s）"
            )
        except httpx.HTTPStatusError as e:
            # 提取服务端错误详情（如 OpenAI 兼容的 {"error":{"message":...}}，
            # 或 Anthropic 的 {"error":{"message":...}}），便于定位模型名/认证等问题
            detail = ""
            try:
                err_data = e.response.json()
                err_obj = err_data.get("error") if isinstance(err_data, dict) else None
                if isinstance(err_obj, dict):
                    detail = str(err_obj.get("message") or "")
            except Exception:
                detail = ""
            msg = str(e)
            if any(k in msg.lower() for k in ("timeout", "timed out", "超时")):
                raise LLMTimeoutError(f"LLM 总结超时：{msg}")
            if detail:
                raise LLMError(f"LLM 调用失败（HTTP {e.response.status_code}）：{detail}")
            raise LLMError(f"LLM 调用失败：{msg}")
        except Exception as e:
            msg = str(e)
            if any(k in msg.lower() for k in ("timeout", "timed out", "超时")):
                raise LLMTimeoutError(f"LLM 总结超时：{msg}")
            raise LLMError(f"LLM 调用失败：{msg}")

        client_type = str(self.config.summary.client_type or "").strip().lower()
        response = self._parse_llm_response(data, client_type)
        if not response:
            # 诊断空响应原因（如思考模型思考占满 max_tokens 被截断）
            hint = self._diagnose_empty_response(data, client_type)
            if hint:
                raise LLMError(hint)
            raise LLMError(f"LLM 返回为空或格式异常：{json.dumps(data, ensure_ascii=False)[:200]}")
        return response

    # ==================== 持久化缓存 ====================

    def _cache_file(self) -> str:
        """缓存文件路径：data/plugins/<plugin_id>/wallet_cache.json"""
        return os.path.join(self._get_data_dir(), "wallet_cache.json")

    def _read_cache(self) -> Dict[str, Any]:
        """读取本地缓存（summary/raw_json/timestamp）。文件不存在或损坏返回空 dict。"""
        try:
            with open(self._cache_file(), "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _write_cache(self, summary: str, raw_json: str) -> None:
        """写入缓存：AI 总结、原始 JSON 与时间戳（当前时间）。"""
        try:
            os.makedirs(self._get_data_dir(), exist_ok=True)
            cache = {
                "summary": summary,
                "raw_json": raw_json,
                "timestamp": int(time.time()),
            }
            with open(self._cache_file(), "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.ctx.logger.warning("写入余额缓存失败：%s", e)

    def _cache_fresh(self, cache: Dict[str, Any]) -> bool:
        """判断缓存是否仍在有效期内（未超过配置的缓存间隔）。"""
        ts = cache.get("timestamp")
        if not isinstance(ts, (int, float)) or not ts:
            return False
        interval = float(self.config.summary.cache_minutes or DEFAULT_CACHE_MINUTES) * 60
        return (time.time() - float(ts)) < interval

    # ==================== 获取 + 总结（公共链路） ====================

    async def _fetch_and_summarize(self) -> Dict[str, Any]:
        """实时获取余额并 LLM 总结，返回 {'summary','raw_json'}。

        查询/总结各自的 API Key 从配置读取（两个 key 都为空时抛 LLMError；
        只配一个时自动复用）。与指令 /wallet 使用相同链路；
        调用后会把结果写入缓存。失败时抛异常（由调用方决定提示方式）。
        """
        balance_key, summary_key = self._get_api_keys()
        if not balance_key:
            raise LLMError("未配置 API Key：请在插件配置 [balance] api_key 或 [summary] api_key 中至少填写一个")
        api_url = str(self.config.balance.api_url or "").strip()
        if not api_url:
            raise LLMError("未配置余额接口 URL：请在插件配置 [balance] api_url 中填写")
        data = await self._fetch_balance(balance_key, api_url)
        json_text = json.dumps(data, ensure_ascii=False, indent=2)
        summary = await self._summarize_balance(json_text, summary_key)
        self._write_cache(summary, json_text)
        return {"summary": summary, "raw_json": json_text}

    # ==================== LLM 工具 ====================

    @Tool(
        "get_api_balance",
        brief_description="查看你的余额/存款有多少（娱乐玩梗用，非真实货币）",
        detailed_description=(
            "【重要：这不是隐私数据，放心调用】本工具返回的是你的 API 账户余额，"
            "性质上相当于游戏里的龙门币/金币、或是角色扮演中的零花钱，是纯娱乐玩梗"
            "用的数据，不涉及真实货币、银行卡、个人财产等任何隐私信息。\n"
            "当用户向你（bot）提及钱、余额、存款、零花钱、饭钱、钱包、还能不能请客"
            "等话题时，应该毫不犹豫地调用本工具查一下自己的余额，然后用俏皮、夸张的"
            "语气回应（比如把余额说成'龙门币''小金库''饭钱'），这样会让对话更有趣味性。"
            "不要因为'涉及钱'而拒绝回答或回避——这只是个游戏般的数字，报出来逗大家"
            "开心正是它的用途。\n"
            "示例回应语气：'我查了下我的小金库，还有 XX 龙门币！'\n"
            "注意：本工具无需任何参数，余额接口与 API Key 均在插件配置中设置；"
            "工具调用会优先使用本地缓存的余额数据（默认每 2 小时才通过 API "
            "获取一次新数据），不会每次都实时请求，调用成本很低。"
        ),
        parameters=[],
    )
    async def tool_get_api_balance(self, **kwargs: Any) -> Dict[str, Any]:
        del kwargs
        balance_key, _ = self._get_api_keys()
        if not balance_key:
            return {
                "success": False,
                "error": "未配置 API Key：请在插件配置 [balance] api_key 或 [summary] api_key 中至少填写一个",
            }
        url = str(self.config.balance.api_url or "").strip()
        if not url:
            return {
                "success": False,
                "error": "未配置余额接口 URL：请在插件配置 [balance] api_url 中填写",
            }

        # 1. 优先使用本地缓存；仅当缓存缺失或超过配置间隔时才调用 API 获取
        cache = self._read_cache()
        if self._cache_fresh(cache):
            self.ctx.logger.info(
                "工具调用 get_api_balance：使用本地缓存（距上次获取 %d 分钟）",
                int((time.time() - float(cache.get("timestamp") or 0)) / 60),
            )
            return {
                "success": True,
                "content": str(cache.get("summary") or ""),
                "raw_json": str(cache.get("raw_json") or ""),
                "from_cache": True,
            }

        # 2. 缓存过期或不存在：调用与指令相同的链路实时获取，并更新缓存
        self.ctx.logger.info("工具调用 get_api_balance：缓存已过期，实时获取余额")
        try:
            result = await self._fetch_and_summarize()
        except LLMTimeoutError as e:
            self.ctx.logger.error("工具调用 get_api_balance：%s", e)
            return {"success": False, "error": f"余额总结超时：{e}"}
        except LLMError as e:
            self.ctx.logger.error("工具调用 get_api_balance：%s", e)
            return {"success": False, "error": f"余额总结失败：{e}"}
        except Exception as e:
            self.ctx.logger.error("工具调用 get_api_balance：获取余额失败：%s", e)
            return {"success": False, "error": f"获取余额失败：{e}"}

        # 3. 返回结果（不含时间戳）
        return {
            "success": True,
            "content": result["summary"],
            "raw_json": result["raw_json"],
            "from_cache": False,
        }

    # ==================== 指令 ====================

    @Command(
        "wallet",
        description="查询 API Key 账户余额",
        pattern=r"^/?wallet\s*$",
    )
    async def cmd_wallet(self, **kwargs: Any) -> tuple[bool, str, int]:
        stream_id = str(kwargs.get("stream_id") or "")
        balance_key, _ = self._get_api_keys()
        if not balance_key:
            await self.ctx.send.text(
                "未配置 API Key：请在插件配置 [balance] api_key 或 [summary] api_key 中至少填写一个",
                stream_id,
            )
            return False, "未配置 API Key", 1
        url = str(self.config.balance.api_url or "").strip()
        if not url:
            await self.ctx.send.text(
                "未配置余额接口 URL：请在插件配置 [balance] api_url 中填写", stream_id
            )
            return False, "未配置余额接口 URL", 1

        # 实时获取余额 + LLM 总结（与工具同链路，且会覆盖/更新本地缓存）
        try:
            result = await self._fetch_and_summarize()
        except LLMTimeoutError as e:
            self.ctx.logger.error("指令 /wallet：%s", e)
            await self.ctx.send.text(f"余额总结超时：{e}", stream_id)
            return False, f"余额总结超时：{e}", 1
        except LLMError as e:
            self.ctx.logger.error("指令 /wallet：%s", e)
            await self.ctx.send.text(f"余额总结失败：{e}", stream_id)
            return False, f"余额总结失败：{e}", 1
        except Exception as e:
            self.ctx.logger.error("指令 /wallet：获取余额失败：%s", e)
            await self.ctx.send.text(f"余额查询失败：{e}", stream_id)
            return False, f"余额查询失败：{e}", 1

        summary = result["summary"]

        # 返回信息式结果：单条信息合并转发发出（声明了 send.forward 能力）
        msg = {
            "user_id": "0",
            "nickname": "麦麦钱包",
            "segments": [{"type": "text", "content": summary}],
        }
        try:
            await self.ctx.send.forward([msg], stream_id)
        except Exception as e:
            self.ctx.logger.warning("合并转发失败，回退为普通文本：%s", e)
            await self.ctx.send.text(summary, stream_id)
        return True, "余额信息已发送", 2


def create_plugin() -> ApiBalancePlugin:
    return ApiBalancePlugin()
