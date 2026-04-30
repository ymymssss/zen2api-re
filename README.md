# zen2api

多模型 API 代理服务，支持 Anthropic Messages 与 OpenAI Chat Completions 格式互转。

使用 Go 编写，单一二进制文件，零依赖运行。

## 支持的协议

| 端点 | 格式 | 上游 |
|------|------|------|
| `/v1/messages` | Anthropic Messages | Zen (passthrough) / Kilo (Anthropic→OpenAI 转换) |
| `/v1/chat/completions` | OpenAI Chat Completions | Zen (OpenAI→Anthropic 转换) |
| `/v1/responses` | OpenAI Responses | Zen (Responses→Anthropic 转换) |
| `/v1/models` | 模型列表 | 动态发现 + 静态配置 |
| `/admin` | Web 管理面板 | 内嵌 |

## 快速开始

### Termux 一键安装（推荐）

```bash
curl -fsSL https://raw.githubusercontent.com/ymymssss/zen2api-re/main/setup.sh | bash
```

脚本自动完成：环境检测 → 安装依赖 → 源码编译 → 安装到 PATH → 创建 `zen` 命令 → 写入环境变量 → 生成 Hermes 配置。

装完后直接 `zen` 启动，`zen status` 看状态，`zen stop` 停止。

### 手动编译

```bash
go build -o zen2api .
```

### 运行

```bash
ZEN2API_ENABLED=1 ZEN2API_PORT=9015 ./zen2api
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZEN2API_HOST` | `127.0.0.1` | 监听地址 |
| `ZEN2API_PORT` | `9015` | 监听端口 |
| `ZEN2API_KEY` | 空 | API 密钥（不设则不校验） |
| `ZEN2API_NON_MODAL_RPS` | `10` | 每 key 每秒请求数 |
| `ZEN2API_DEFAULT_MAX_TOKENS` | `8192` | 默认 max_tokens |
| `ZEN2API_MODEL_DISCOVERY_TTL_SECONDS` | `900` | 模型缓存 TTL |
| `ZEN_UPSTREAM_URL` | opencode.ai | Zen 上游地址 |
| `KILO_UPSTREAM_URL` | kilo.ai | Kilo 上游地址 |
| `ZEN2API_LOG_LEVEL` | `INFO` | 日志级别 |
| `ZEN2API_STATS_FILE` | `stats.json` | 统计数据文件 |

## 接入 Hermes Agent

### 1. 启动 zen2api

```bash
ZEN2API_ENABLED=1 ZEN2API_PORT=9015 ./zen2api
```

### 2. 配置 Hermes

在 `~/.hermes/config.yaml` 中添加：

```yaml
model: "minimax-m2.5-free"
provider: zenlocal

providers:
  zenlocal:
    name: ZenLocal
    base_url: http://127.0.0.1:9015
    transport: anthropic_messages
    key_env: ZENLOCAL_API_KEY
```

### 3. 运行

```bash
ZENLOCAL_API_KEY="test" hermes -m "minimax-m2.5-free" --provider zenlocal
```

## AI Agent 接入注意事项（重要）

以下事项 AI agent 容易出错，接入时请逐一检查。

### 1. `ZEN2API_ENABLED` 必须设为 `1`

值必须是字符串 `"1"`，不是 `"true"` 或 `"True"` 或 `"yes"`。虽然 `ZEN2API_ENABLED=true` 也能被 envBool 识别，但建议统一用 `1`。

```bash
# 正确
ZEN2API_ENABLED=1 ./zen2api

# 错误 — 服务不会启动
ZEN2API_ENABLED=false ./zen2api
```

如果未设置 `ZEN2API_ENABLED=1` 且也未开启 AnyRouter，进程会直接 Fatal 退出。

### 2. Hermes transport 类型必须是 `anthropic_messages`

即使调用 `/v1/chat/completions`（OpenAI 格式端点），Hermes 的 transport 也必须配置为 `anthropic_messages`。这是 Hermes 内部的概念——它决定了 Hermes 如何构造请求体，与 zen2api 的端点选择无关。

```yaml
# 正确
transport: anthropic_messages

# 错误 — AI agent 容易猜这个值
transport: openai_chat_completions
```

### 3. `key_env` 是环境变量名，不是密钥值

Hermes 配置中的 `key_env` 指向一个**环境变量的名字**，而不是 API key 本身。

```yaml
# 正确 — ZENLOCAL_API_KEY 是环境变量名，运行时从环境读取
key_env: ZENLOCAL_API_KEY

# 错误 — 不要把 key 值直接写在这里
key_env: sk-xxxx
```

如果 zen2api 未设置 `ZEN2API_KEY`（默认不校验），则 Hermes 传入任意值即可：`ZENLOCAL_API_KEY="any"`。

### 4. 模型名必须与 `/v1/models` 返回的一致

可用的模型 ID 由 zen2api 动态发现并合并 Zen 和 Kilo 上游后决定。启动后查看：

```bash
curl -s http://127.0.0.1:9015/v1/models | jq '.data[].id'
```

常见的模型 ID 示例：
- `minimax-m2.5-free`（Zen，Anthropic 原生协议）
- `kilo-auto/free`（Kilo，免费模型轮转，Anthropic→OpenAI 转换）
- `nvidia/nemotron-3-super-120b-a12b:free`（Kilo）

模型路由是自动的：Kilo 模型走 Anthropic→OpenAI 转换，其余走 Zen 直通。

### 5. Anthropic Messages 端点需要 `max_tokens`

请求 `/v1/messages`（Anthropic 格式）时，`max_tokens` 是必填字段。zen2api 会自动补默认值 8192，但不建议依赖。如果上游返回校验错误，检查是否缺了这个字段。

### 6. 端口默认 9015，不是 8080

```bash
# 正确
base_url: http://127.0.0.1:9015

# 错误 — agent 常猜 8080、3000、11434 等
base_url: http://127.0.0.1:8080
```

### 7. 启动即运行，无配置文件

zen2api 是零配置启动的，所有配置通过环境变量传入，没有 `.env` 文件、`config.yaml` 或 `config.json`。AI agent 不应尝试寻找或创建配置文件。

### 8. 不要尝试 `pip install` 或 `npm install`

zen2api 是 Go 编译的单一二进制文件，不是 Python 或 Node 项目。Agent 不应执行 `pip install -r requirements.txt` 或 `npm install`。

### 9. 流式响应默认支持

所有端点均支持 `stream: true`。非流式请求也正常运作。Agent 不应假设只支持其中一种模式。

### 10. 速率限制默认 10 RPS

每个 API key 每秒 10 个请求。Agent 并发调用时注意不要超过此限制，否则返回 429。

### 11. AnyRouter 是独立服务

AnyRouter 需要单独开启（`ZEN2API_ANYROUTER_ENABLED=1`），监听独立端口（默认 18888）。不开启则只有主代理服务。

### 12. API Key 认证

- 如果 `ZEN2API_KEY` 为空（默认），不校验任何认证，所有请求放行
- 如果设置了 `ZEN2API_KEY`，客户端必须通过 `x-api-key` header 或 `Authorization: Bearer <key>` 传入匹配的 key
- Hermes 通过 `key_env` 指定的环境变量自动添加 `x-api-key` header

### 13. 不要假设上游 URL 可直连

zen2api 是一个代理，上游 URL（`ZEN_UPSTREAM_URL`、`KILO_UPSTREAM_URL`）由服务端配置。客户端只需连接 zen2api 的地址即可。

### 14. 管理面板路径是 `/admin`

启动后访问 `http://127.0.0.1:9015/admin`，可以查看仪表盘、模型列表、系统配置、速率限制等。不是 `/`、`/ui`、`/dashboard`。

## License

MIT
