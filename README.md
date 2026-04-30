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

### 编译

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

custom_providers:
  - name: zenlocal
    base_url: http://127.0.0.1:9015
    transport: anthropic_messages
    key_env: ZENLOCAL_API_KEY
```

### 3. 运行

```bash
ZENLOCAL_API_KEY="test" hermes -m "minimax-m2.5-free" --provider zenlocal
```

## 管理面板

启动后访问 `http://127.0.0.1:9015/admin`

## License

MIT
