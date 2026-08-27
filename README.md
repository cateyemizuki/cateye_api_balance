# 麦麦钱包（MaiBot 插件）

为麦麦（MaiBot）框架的插件，用于获取指定 API Key 的账户余额：

- 通过配置的余额查询接口（**GET 请求**）获取余额 JSON；
- 使用配置的 **LLM 模型**（默认 `deepseek v4 flash`）将余额 JSON 总结为**清晰的中文报告**（账户是否可用、各币种总额/赠金/充值余额等）；
- 提供指令 `/wallet`（**单条信息合并转发**返回）与 LLM 工具 `get_api_balance`。

默认适配 **DeepSeek 开放平台**余额接口（`https://api.deepseek.com/user/balance`）与模型接口（`https://api.deepseek.com/chat/completions`），认证方式默认为 `Authorization: Bearer <API_KEY>`；`client_type` 支持 openai/anthropic/gemini/cohere/deepseek/xai/mistral/huggingface/baidu 等多种客户端兼容格式，与认证方式自由组合，可通过配置切换适配其他常见平台。

**v1.0.1 起：查询与总结分别配置 API Key** ——「查询配置」`[balance].api_key` 是要查余额平台的 Key，「总结配置」`[summary].api_key` 是大模型总结用的 Key。两个都为空则不工作；只配置其中一个时自动复用另一个（例如查余额与总结都走同一个 DeepSeek Key，只填 `[balance].api_key` 即可）。

## 功能特性

- **余额获取**：以 GET 请求调用配置的余额接口，携带查询配置（`[balance]`）的认证请求头。
- **LLM 总结**：通过**独立的模型接口 URL**（`[summary].llm_url`，OpenAI 兼容系列自动补全 `/chat/completions`，POST 请求，与余额接口为不同 API）把接口返回的余额 JSON 交给 LLM 总结为中文报告（默认 deepseek v4 flash，可配置模型、最大输出 token、超时时间）。**总结使用「总结配置」`[summary]` 下的 API Key**（`[summary].api_key`；为空时自动复用 `[balance].api_key`）。支持**客户端兼容格式切换**（`[summary].client_type`：openai/anthropic/gemini/cohere/deepseek/xai/mistral/huggingface/baidu），与认证方式自由组合可跑通大部分平台；默认不发送 `max_tokens`（`send_max_tokens = false`，由平台自动决定输出长度，规避部分上游不接受该参数的问题）。
- **可配置提示词**：提示词每项为一行（可添加多项），代码读取时自动分行拼接，并在尾部自动补充 `JSON数据：` 与余额 JSON，无需手工粘贴数据。
- **指令 `/wallet`**：**实时**获取余额并返回信息式结果（**单条信息合并转发**发出，插件已声明 `send.forward` 能力），同时会**覆盖/更新本地缓存**（供工具调用使用）。
- **LLM 工具 `get_api_balance`**：查看你的余额/存款（**纯娱乐玩梗用，非真实货币，不涉及隐私**）。用户向 bot 提及钱、余额、存款、零花钱、饭钱、钱包、请客等话题时，模型**应毫不犹豫地**调用该工具查余额并用俏皮夸张的语气回应（把余额说成"龙门币""小金库""饭钱"），让对话更有趣味性。**工具无参数**（API Key 与余额接口 URL 仅从插件配置读取，不接受 LLM 传入，防止 SSRF 与 Key 泄露）；**工具调用优先使用本地缓存**（默认每 2 小时才通过 API 获取一次新数据，超期才实时刷新），返回结果不显示时间戳。
- **缓存机制**：AI 总结与原始 JSON 持久化到本地（`data/plugins/<plugin_id>/wallet_cache.json`）并附时间戳；工具调用时代码层判断时间戳与当前时间差是否超过配置间隔（`cache_minutes`，默认 120 分钟），超过才调用与指令相同的链路刷新，未超过直接用本地数据。**即使超期插件也不会主动更新**，只有工具被调用且发现需要更新时才更新。`/wallet` 指令始终实时获取并覆盖缓存。
- **超时行为约定**：
  - 指令查询（`/wallet`）：LLM 总结超时通过 QQ 信息返回错误，同时控制台打印日志；
  - 工具调用（`get_api_balance`）：超时仅在控制台打印错误日志，不主动发送 QQ 消息。

## 安装方式

1. 将本插件目录（含 `_manifest.json`、`plugin.py` 等文件）放入 MaiBot 的 `plugins/` 目录。
2. 重启 MaiBot，或在 WebUI 插件中心安装。
3. 插件依赖 `httpx`，已声明于 `_manifest.json`，Host 会自动安装。

> 兼容性声明：`host_application` `1.0.0 ~ 1.99.99`，`sdk` `2.0.0 ~ 2.99.99`（Manifest v2）。

## 配置说明

插件加载后由 Runner 在插件目录生成 `config.toml`，可在 WebUI 修改：

```toml
[plugin]
enabled = true
config_version = "1.0.1"

[balance]          # 查询配置：要查余额的平台
api_key = ""                                       # 要获取余额的 API Key（默认为空）
api_url = "https://api.deepseek.com/user/balance"   # 余额查询接口 URL（GET 请求）

[summary]          # 总结配置：LLM 总结用的平台
api_key = ""                                       # LLM 总结用的 API Key（默认为空；只配 [balance] 时自动复用）
summary_model = "deepseek v4 flash"                # 总结余额 JSON 的模型名（模型接口中的 model 字段）
client_type = "deepseek"                           # 客户端兼容格式（openai/anthropic/gemini/cohere/deepseek/xai/mistral/huggingface/baidu）
llm_url = "https://api.deepseek.com/chat/completions"  # 模型接口 URL（OpenAI 兼容系列自动补全 /chat/completions）
auth_header = "Authorization: Bearer"              # 认证方式："请求头名: 前缀"
max_tokens = 4096                                  # 总结时最大输出 token 数
send_max_tokens = false                            # 是否在请求体中发送 max_tokens（默认 false 不发送，由平台自动决定）
llm_timeout = 60                                   # LLM 总结超时（秒）
cache_minutes = 120                                # 工具调用获取余额的缓存间隔（分钟）

[prompt]
lines = [
    "请总结以下DeepSeek账户余额查询结果的JSON数据，提取关键信息：",
    "1. 账户是否可用（is_available）",
    "2. 各币种的总额、赠金和充值余额",
    "3. 用清晰的中文列出，标注币种，余额保留两位小数",
]
```

- `balance.api_key`：**要获取余额的 API Key**（查询平台的凭据，默认为空）。与 `summary.api_key` 二选一即可：**只配其中一个时自动复用另一个**；两个都为空时 `/wallet` 与工具会提示未配置。
- `balance.api_url`：API Key 提供方提供的**余额获取 URL**（GET 请求），默认为 DeepSeek 开放平台。**安全约束：仅支持 https，且拒绝私网/环回/链路本地/云元数据地址（如 127.0.0.1、10.x、169.254.169.254），防止 SSRF 与 API Key 泄露**；工具 `get_api_balance` 只从配置读取该值，不接受 LLM 传入。`/wallet` 指令同样走该配置。
- `summary.api_key`：**LLM 总结用的 API Key**（模型平台的凭据，默认为空）。与 `balance.api_key` 二选一即可：**只配其中一个时自动复用另一个**；两个都为空时不工作。查询与总结的认证方式（`auth_header`）也可分别配置。
- `summary.summary_model`：总结余额 JSON 的**模型名**（即模型接口请求体中的 `model` 字段）。默认使用余额获取平台所提供的模型（`deepseek v4 flash`）。
- `summary.client_type`：**客户端兼容格式**（决定模型接口的**请求体格式与响应解析**，不参与 URL 拼接）：`openai` / `anthropic` / `gemini` / `cohere` / `deepseek` / `xai` / `mistral` / `huggingface` / `baidu`。与 `auth_header` **自由组合**，可跑通大部分 API 平台（详见下方平台对应表）。
- `summary.llm_url`：**模型接口 URL**。支持 `{model}` 占位符替换（用于模型名需出现在 URL 中的平台，如 Gemini：`https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`）。**OpenAI 兼容系列（openai/deepseek/xai/mistral/huggingface/baidu）会自动补全 `/chat/completions`**：可填基础地址（如 `https://api.commandcode.ai/provider/v1`，自动补全为 `/provider/v1/chat/completions`）或完整端点（如 `https://api.deepseek.com/chat/completions`，直接使用）；非 OpenAI 兼容系列（anthropic/gemini/cohere）原样使用。注意：**余额查询接口（`balance.api_url`）与模型接口是不同的 API**，需单独设置；默认指向 DeepSeek 开放平台模型接口。
- `summary.auth_header`：**模型接口（POST）的认证方式**，格式为 `请求头名: 前缀`，默认 `Authorization: Bearer`（即发送 `Authorization: Bearer <summary.api_key>`）。若平台要求请求头直接填 API Key（无前缀），写成 `自定义请求头名:` 即可（前缀留空）。余额接口（GET）的认证方式见「查询配置」`balance.auth_header`（v1.0.1 起两者独立配置，均可自定义）。
- `summary.max_tokens`：控制 LLM 总结时输出的最大 token 数（默认 4096；仅在 `send_max_tokens` 为 `true` 时发送）。
- `summary.send_max_tokens`：是否在模型请求体中发送 `max_tokens` 参数（默认 `false`，不发送，由平台自动决定输出长度）。**部分上游模型不接受 `max_tokens`**（实测 Command Code 的 `poolside/laguna-s-2.1-free` 带上 `max_tokens` 会返回 `503 overloaded_error`）；而**思考模型**（如 `tencent/hy3-paid`）在 `max_tokens` 过小时思考占满上限会被截断。默认关闭可规避这两类问题（Anthropic Messages API 的 `max_tokens` 为必填字段，开关关闭时仍会发送，使用 `max_tokens` 配置值兜底）。
- `summary.llm_timeout`：LLM 总结超时时间（秒，默认 60）。超时后：指令查询通过 QQ 信息返回错误（控制台也打印日志）；工具调用仅在控制台打印错误日志。
- `summary.cache_minutes`：**工具调用获取余额的缓存间隔**（分钟，默认 120，即 2 小时）。工具调用时若距上次获取未超过该间隔，直接使用本地缓存数据（AI 总结 + 原始 JSON，持久化于 `data/plugins/<plugin_id>/wallet_cache.json`）；超过才调用 API 重新获取并更新缓存。**即使超期插件也不会主动更新**，只有工具被调用且发现需要更新时才更新。指令 `/wallet` 始终实时获取并覆盖缓存。
- `prompt.lines`：总结提示词，**每一项为一行**，WebUI 中为可添加多项的配置项，代码读取时自动分行拼接。**尾部的「JSON数据：」与 `{json_data}`（接口返回的余额 JSON）不写进配置项**，由代码在拼接后自动补充。
- `plugin.config_version`（配置版本）与插件版本同步（`SUPPORTED_CONFIG_VERSION` 常量），用于检查配置文件是否需要更新，UI 中隐藏、不可手动修改。

### 平台对应表（客户端兼容格式 × 认证方式）

`[summary].client_type` 决定**模型接口的请求体格式与响应解析**，`[summary].llm_url` 为**模型接口 URL（OpenAI 兼容系列自动补全 `/chat/completions`，其余原样使用）**，`[summary].auth_header` 决定**模型接口认证方式**，三者自由组合，可跑通大部分 API 平台：

| 平台 | 标准认证方式 | 你的系统中需要配置（均为 `[summary]` 下的模型接口配置） |
|------|-------------|-------------------|
| OpenAI | `Authorization: Bearer <API_KEY>` | 客户端类型: `openai`<br>认证头: `Authorization: Bearer` |
| Anthropic (Claude) | `x-api-key: <API_KEY>` | 客户端类型: `anthropic`<br>认证头: `x-api-key` |
| Google Gemini (API Key模式) | `x-goog-api-key: <API_KEY>` | 客户端类型: `gemini`<br>认证头: `x-goog-api-key` |
| Google Gemini (OAuth模式) | `Authorization: Bearer <ACCESS_TOKEN>` | 客户端类型: `gemini`<br>认证头: `Authorization: Bearer` |
| Cohere | `Authorization: Bearer <API_KEY>` | 客户端类型: `cohere`<br>认证头: `Authorization: Bearer` |
| DeepSeek | `Authorization: Bearer <API_KEY>` | 客户端类型: `deepseek`<br>认证头: `Authorization: Bearer` |
| Command Code | `Authorization: Bearer <API_KEY>` | 客户端类型: `openai`（兼容模式）<br>认证头: `Authorization: Bearer`<br>接口 URL: `https://api.commandcode.ai/provider/v1`（自动补全 `/chat/completions`）<br>模型名需带前缀，如 `deepseek/deepseek-v4-flash`（可用 `GET /provider/v1/models` 查询）<br>部分免费模型（如 `poolside/laguna-s-2.1-free`）不接受 `max_tokens`，需将 `send_max_tokens` 设为 `false` |
| xAI (Grok) | `Authorization: Bearer <API_KEY>` | 客户端类型: `xai`<br>认证头: `Authorization: Bearer` |
| Mistral | `Authorization: Bearer <API_KEY>` | 客户端类型: `mistral`<br>认证头: `Authorization: Bearer` |
| Hugging Face | `Authorization: Bearer <API_KEY>` | 客户端类型: `huggingface`<br>认证头: `Authorization: Bearer` |
| 百度文心一言 | `Authorization: Bearer <ACCESS_TOKEN>`（需先通过OAuth2获取） | 客户端类型: `baidu`<br>认证头: `Authorization: Bearer` |
| 阿里通义千问 (兼容模式) | `Authorization: Bearer <API_KEY>` | 客户端类型: `openai` (兼容模式)<br>认证头: `Authorization: Bearer` |

> 说明：
> - **余额接口**（`balance.api_url`）始终为 GET 请求，使用「查询配置」`balance.auth_header` 认证与 `balance.api_key`；
> - **模型接口**（`[summary].llm_url`，POST 请求）使用「总结配置」`summary.auth_header` 认证与 `summary.api_key`（为空时复用 `balance.api_key`）；
> - **API Key 归属**：查余额与总结用的是不同平台的 Key 时，分别填 `[balance].api_key` 与 `[summary].api_key`；同一个 Key 时只填其中一个即可（自动复用）；
> - `[summary].llm_url` 填**该平台的模型接口地址**（OpenAI 兼容系列可填基础地址，插件自动补全 `/chat/completions`）：
>   - OpenAI 兼容系列：`https://api.openai.com/v1`（自动补全为 `/v1/chat/completions`）、`https://api.deepseek.com/chat/completions`（完整端点直接使用）、`https://api.commandcode.ai/provider/v1`（自动补全为 `/provider/v1/chat/completions`）等；
>   - Anthropic：`https://api.anthropic.com/v1/messages`；
>   - Gemini：`https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`（`{model}` 占位符会被替换为配置的模型名）；
>   - Cohere：`https://api.cohere.com/v1/chat`；
>   - 百度文心一言：`https://qianfan.baidubce.com/v2`（自动补全为 `/v2/chat/completions`）。
> - 若某平台同时提供 OpenAI 兼容端点和原生端点，推荐优先使用 OpenAI 兼容端点（`client_type: openai` + 对应认证头 + 兼容端点的完整 URL）。
> - **模型名（`summary_model`）格式需与平台一致**：部分平台要求带 provider 前缀（如 Command Code 的 `deepseek/deepseek-v4-flash`），不带前缀的模型名会导致上游路由失败（表现为 400/503）。可通过各平台的模型列表接口查询（如 Command Code 的 `GET /provider/v1/models`）。
> - **部分模型不接受 `max_tokens` 参数**：实测 Command Code 的 `poolside/laguna-s-2.1-free` 带上 `max_tokens` 会返回 `503 overloaded_error`。插件默认 `send_max_tokens = false`（不发送），已规避此类问题；如需发送可自行开启。
> - **思考模型（reasoning model）需要更大的 `max_tokens`**：如 `tencent/hy3-paid` 会先输出思考内容再输出正式回答，思考过程会占用大量 token 预算。若 `max_tokens` 太小，思考占满上限后正式回答会被截断（`content` 为空、`finish_reason=length`）。插件默认不发送 `max_tokens`（`send_max_tokens = false`），由平台自动决定输出长度；如需手动限制，请调大 `summary.max_tokens`。插件会在遇到此类情况时给出针对性错误提示。

## 使用说明

### 指令

| 指令 | 功能 | 权限 |
|------|------|------|
| `/wallet` | **实时**查询配置中 API Key 的余额并返回信息式结果（单条信息合并转发发出），同时覆盖/更新本地缓存 | 所有人 |

### LLM 工具（自然语言触发）

| 工具 | 触发场景 | 参数 |
|------|---------|------|
| `get_api_balance` | 用户向 bot 提及钱、余额、存款、零花钱、饭钱、钱包、请客等话题（娱乐玩梗用） | 无（API Key 与余额接口 URL 仅从插件配置读取） |

> 触发场景：`get_api_balance` 返回的是 API 账户余额，性质相当于游戏里的龙门币/金币或角色扮演的零花钱，**纯娱乐玩梗用、非真实货币、不涉及隐私**。用户向 bot 提及钱包余额之类的话题时，bot 应毫不犹豫地调用该工具查余额，并用俏皮夸张的语气回应（把余额说成"龙门币""小金库"等），添加聊天趣味性。工具无参数（API Key 与余额接口 URL 仅从配置读取），优先使用本地缓存（默认每 2 小时才通过 API 获取一次新数据），返回不显示时间戳；`/wallet` 指令则始终实时获取。

## 数据存储

- 本插件不保存任何用户数据；API Key 仅存在于插件配置（`config.toml`）中（查询 Key 在 `[balance].api_key`，总结 Key 在 `[summary].api_key`）。
- **余额缓存**：AI 总结、原始 JSON 与时间戳持久化于 `data/plugins/<plugin_id>/wallet_cache.json`（供工具调用读取；`/wallet` 实时获取时覆盖）。
- **API Key 即敏感凭证，请勿提交到公开仓库**，`.gitignore` 已包含 `/config.toml` 与 `/data/`。

## 目录结构

```
cateye_api_balance/
├── _manifest.json      # 插件元信息（Manifest v2）
├── plugin.py           # 插件主体（配置 / 余额获取 / LLM 总结 / 指令 / LLM 工具）
├── README.md           # 本说明文档
├── COMMANDS.md         # 指令与触发词说明
├── CHANGELOG.md        # 更新日志
└── LICENSE             # MIT 许可证
```

## 免责声明

- 本插件仅用于个人学习与自动化查询用途，请遵守各 API 提供方的服务条款。
- API Key 属于敏感凭证，请妥善保管，勿泄露给他人。

---

## 致谢与来源

- 插件基于 [MaiBot 插件开发文档](https://docs.mai-mai.org/plugin/) 与 [maibot-plugin-sdk](https://github.com/Mai-with-u/maibot-plugin-sdk) 开发。
