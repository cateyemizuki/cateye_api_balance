# 更新日志

## 1.0.5（2026-09-29）

- **安全加固（不改功能）**：
  - **`summary.llm_url` 接入出站 URL 护栏**：该 URL 携带总结用 API Key 出站，此前无任何校验，现与余额接口
    （`balance.api_url`）对称走同一套 `url_guard` 护栏（随插件分发的统一参考实现，来源 cateye_common）：
    仅允许 https、拒绝 URL 内嵌用户名/密码、拦截私网/环回/链路本地（含 169.254.169.254 云元数据）/CGNAT/
    组播/保留地址（IPv4 + IPv6 含 v4-mapped）。新增可选配置 `[summary].llm_allowed_hosts` 主机白名单
    （留空不启用），启用后进一步限制模型接口主机名。
  - **DNS 校验加固**：余额/模型接口 URL 校验的 DNS 解析改在线程池内执行（不再阻塞事件循环），
    异常捕获放宽为解析类错误全兜底；删除冗余的 169.254 判断。校验时解析的 IP 与 httpx 实际请求时
    再次解析的 IP 之间仍存在极小的 DNS 变更窗口（TOCTOU），因 httpx 无法钉住连接 IP，以全量解析逐 IP
    判黑尽力收敛，已在代码注释与 README「安全说明」注明该边界。
  - **错误回显脱敏**：`/wallet` 指令与工具调用失败时，聊天/LLM 侧只发简短通用话术
    （不含 URL/IP/状态码/上游错误详情），完整异常仅进控制台日志。
  - **缓存文件加固**：`wallet_cache.json` 改为 0o600 权限创建 + 临时文件 `os.replace` 原子写入
    （Windows 上权限收紧尽力而为），避免同机其他用户读取与读到半截 JSON。
- **默认总结模型更正**：`summary.summary_model` 默认值由 `deepseek v4 flash`（占位示例，并非真实模型 ID）
  更正为 DeepSeek 开放平台真实模型 ID `deepseek-chat`；使用其他平台仍需按平台填写真实模型名。
- 配置版本同步为 `1.0.5`（新增 `summary.llm_allowed_hosts` 字段；升级时 Runner 重建骨架会保留原有配置值，
  新字段按默认值空列表补齐，不启用白名单）。

## 1.0.4（2026-09-28）

- **适配 MaiBot 1.3.0 插件市场规范（WebUI 配置元数据补全）**：
  - 为全部配置字段补充英文翻译（`json_schema_extra.i18n`，至少 `en` 的 `label`/`hint`），
    为全部配置分组补充 `__ui_i18n__`（英文分组标题/描述）。
    1.3.0 的 WebUI 在缺少这些元数据时会直接把英文字段名当标题展示；
    补全后中文界面显示不变，英文界面不再出现裸字段名。
  - manifest `i18n.supported_locales` 增加 `en`。
- **兼容性不变**：宿主区间仍为 `1.0.0 ~ 1.99.99`、SDK 区间 `2.0.0 ~ 2.99.99`，
  同时兼容 MaiBot 1.2.x 与 1.3.0（策略 A，单 main 代码线）；
  插件未使用消息类 `@EventHandler`、未调用 `ctx.llm` 路由，无 1.2.x/1.3.0 行为差异影响。
- 配置版本同步为 `1.0.4`（仅元数据变化，字段结构不变；升级时 Runner 重建骨架会保留原有配置值）。
- 功能与行为无任何变化。

## 1.0.3（2026-09-12）

- **修复 `/wallet` 与工具调用报错 `'BalanceQueryConfig' object has no attribute 'auth_header'`**：
  1.0.1 拆分「查询配置 / 总结配置」时，`auth_header` 只被声明在 `[summary]`，
  但 `_fetch_balance()` 仍读取 `self.config.balance.auth_header`，导致余额查询必现 AttributeError。
  现已把 `auth_header` 补回 `[balance]`（默认 `Authorization: Bearer`），与 README / 1.0.1 变更说明的
  「余额接口用 `balance.auth_header`、模型接口用 `summary.auth_header`，可分别配置」保持一致。
- 同步修正模块 docstring 与 README 配置示例中遗漏的 `balance.auth_header`。
- 兼容性：配置版本升级到 `1.0.3` 后，Host 会以最新默认结构重建 `config.toml`；
  由于 `balance.auth_header` 重新出现在结构骨架中，旧配置里的该字段值会被保留。

## 1.0.2（2026-08-xx）

- 为全部配置项补充/完善了用户友好的中文注释与说明（悬停提示），完善配置节说明；插件功能与行为不变。

## 1.0.1（2026-08-xx）

- **配置拆为两个 API Key**：`[balance]` 查询配置（要查余额平台的 `api_key`/`api_url`）+ `[summary]` 总结配置（LLM 总结用的 `api_key`/模型/接口/认证/超时/缓存）。
- **Key 复用**：两个 api_key 都为空则不工作；只配置其中一个时自动复用另一个（查询与总结可各自独立认证）。
- **认证方式拆分**：余额接口（GET）使用「查询配置」`balance.auth_header`，模型接口（POST）使用「总结配置」`summary.auth_header`，可分别配置。
- 工具/指令提示语更新为「[balance] api_key 或 [summary] api_key 至少填写一个」。
- 文档（README / COMMANDS / CHANGELOG）同步更新配置结构说明。

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
