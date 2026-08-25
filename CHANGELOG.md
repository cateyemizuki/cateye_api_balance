# 更新日志

## 1.0.0（2026-08-xx）

- 首个版本。
- 功能：
  - 通过配置的余额接口（GET 请求）获取指定 API Key 的账户余额 JSON。
  - 使用 LLM（默认 deepseek v4 flash）将余额 JSON 总结为清晰的中文报告。
  - 指令 `/wallet`：返回信息式结果（单条信息合并转发发出，已声明 `send.forward` 能力）。
  - LLM 工具 `get_api_balance`：查看你的余额/存款（纯娱乐玩梗用、非真实货币、不涉及隐私）。用户提及钱、余额、存款、零花钱、饭钱、钱包、请客等话题时主动调用，用俏皮夸张的语气把余额说成"龙门币""小金库"等，增加聊天趣味性。工具调用优先使用本地缓存（默认每 2 小时才通过 API 获取一次新数据，超期才实时刷新），返回不显示时间戳。
  - 缓存机制：AI 总结、原始 JSON 与时间戳持久化到 `data/plugins/cateye_api_balance/wallet_cache.json`；工具调用时按 `cache_minutes`（默认 120 分钟）判断是否刷新，未超期直接用本地数据，插件不会主动更新；指令 `/wallet` 始终实时获取并覆盖缓存。
  - 可配置认证方式（默认 `Authorization: Bearer <API_KEY>`，支持 `x-api-key`、`x-goog-api-key`、`x-portkey-api-key`、`api-key` 等常见平台）。
  - 客户端兼容格式切换（`client_type`：openai/anthropic/gemini/cohere/deepseek/xai/mistral/huggingface/baidu），与认证方式自由组合可跑通大部分平台；模型接口 `llm_url` 填基础地址即可，OpenAI 兼容系列自动补全 `/chat/completions`。
  - `send_max_tokens` 开关：默认关闭，不在请求体中发送 `max_tokens`（由平台自动决定输出长度；部分上游模型如 Command Code `poolside/laguna-s-2.1-free` 不接受该参数，会返回 503）。
  - 模型接口报错时提取服务端错误详情（如 OpenAI 兼容的 `error.message`），便于定位模型名/认证等问题。
  - 思考模型（如 `tencent/hy3-paid`）空响应诊断：当模型只返回思考内容、正式回答被截断时，给出针对性提示。
  - 可配置提示词（每项一行，自动拼接，尾部自动补充 `JSON数据：` 与余额 JSON）。
  - 超时行为：指令查询超时经 QQ 信息返回错误（控制台也打印日志）；工具调用超时仅控制台打印日志。
