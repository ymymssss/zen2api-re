# API 代理服务 - 跨平台版

将原本的 Windows EXE 工具逆向为可在 **Linux / Ubuntu / Termux** 上运行的 Python 应用。

## 项目说明

本项目包含两个 API 代理服务和一个 Web 管理面板：

| 服务 | 说明 | 默认端口 |
|------|------|---------|
| **zen2api** | OpenAI / Anthropic / Kilo 多模型代理 | 9016 |
| **grok2api** | Grok API 代理 | 8021 |
| **Web UI** | 中文管理控制面板 | 8081 |

## 环境要求

- Python 3.10+
- pip

## 快速安装

### 1. 克隆仓库

```bash
git clone https://github.com/ymymssss/zen2api-re.git
cd zen2api-re
```

### 2. 安装依赖

```bash
# zen2api 依赖
pip install -r zen2api/requirements.txt

# grok2api 依赖
pip install -r grok2api/requirements.txt
```

> **Termux 用户**：如遇到编译错误，先执行：
> ```bash
> pkg install python build-essential
> ```

### 3. 配置环境变量（可选）

```bash
# 复制配置模板
cp zen2api/.env.template zen2api/.env
cp grok2api/.env.template grok2api/.env

# 编辑配置
nano zen2api/.env
nano grok2api/.env
```

### 4. 启动服务

```bash
# 启动 zen2api
cd zen2api && ./start.sh &

# 启动 grok2api
cd grok2api && ./start.sh &

# 启动 Web 管理面板
cd webui && python3 -m http.server 8081 &
```

或手动指定端口：

```bash
# zen2api
cd zen2api && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 9016

# grok2api
cd grok2api && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8021
```

## 访问服务

启动后访问：

| 服务 | 地址 |
|------|------|
| Web 管理面板 | http://127.0.0.1:8081 |
| zen2api API | http://127.0.0.1:9016 |
| grok2api API | http://127.0.0.1:8021 |

## API 使用

### zen2api

```bash
# 健康检查
curl http://127.0.0.1:9016/health

# 查看可用模型
curl http://127.0.0.1:9016/v1/models

# 发送聊天请求
curl http://127.0.0.1:9016/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"minimax-m2.5-free","messages":[{"role":"user","content":"你好"}]}'

# 查看统计
curl http://127.0.0.1:9016/stats
```

### grok2api

```bash
# 健康检查
curl http://127.0.0.1:8021/health

# 查看模型
curl http://127.0.0.1:8021/v1/models
```

## 配置说明

### zen2api 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `ZEN2API_HOST` | 127.0.0.1 | 监听地址 |
| `ZEN2API_PORT` | 9016 | 监听端口 |
| `ZEN2API_KEY` | (空) | API Key（留空则不验证） |
| `ZEN2API_LOG_LEVEL` | INFO | 日志级别 |
| `ZEN2API_MODEL_DISCOVERY_ENABLED` | true | 自动发现模型 |

### grok2api 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `ZEN2API_GROK2API_HOST` | 127.0.0.1 | 监听地址 |
| `ZEN2API_GROK2API_PORT` | 8021 | 监听端口 |

## Web 管理面板

打开 http://127.0.0.1:8081 即可使用中文管理面板：

- **服务控制**：查看 zen2api / grok2api 运行状态
- **统计仪表盘**：总请求数、今日请求、Token 用量、缓存命中率
- **数据图表**：请求趋势、Token 趋势、状态码分布、Token 结构
- **配置管理**：在线修改 Host / Port / API Key

## 目录结构

```
.
├── zen2api/                    # zen2api 代理服务
│   ├── app/                    # 源码（21 个模块）
│   │   ├── main.py             # FastAPI 入口
│   │   ├── config.py           # 配置管理
│   │   ├── license_guard.py    # 已禁用
│   │   ├── openai_zen_proxy.py # OpenAI 代理
│   │   ├── anthropic_proxy.py  # Anthropic 代理
│   │   ├── kilo_proxy.py       # Kilo 代理
│   │   └── ...
│   ├── requirements.txt
│   ├── .env.template
│   └── start.sh
├── grok2api/                   # grok2api 代理服务
│   ├── app/                    # 源码（35 个模块）
│   │   ├── main.py
│   │   ├── core/               # 核心模块
│   │   ├── api/                # API 路由
│   │   ├── services/           # 业务逻辑
│   │   └── models/             # 数据模型
│   ├── requirements.txt
│   ├── .env.template
│   └── start.sh
├── webui/                      # Web 管理面板
│   └── index.html              # 单文件，无依赖
├── .gitignore
└── README.md
```

## 技术栈

- **框架**: FastAPI + Uvicorn
- **HTTP 客户端**: httpx (zen2api) / aiohttp (grok2api)
- **前端**: 纯 HTML/CSS/JS（无外部依赖）
- **Python 版本**: 3.10+（兼容 3.12）

## 逆向说明

本项目通过以下方式从原始 Windows EXE 重建：

1. 使用 `pyinstxtractor` 提取 PyInstaller 打包的 Python 字节码
2. 使用 `strings` 分析提取模块结构和函数签名
3. 手动重建 Python 源码（功能等效，非字节级一致）
4. 移除卡密验证和 AnyRouter 功能
5. 适配 Linux / Termux 环境

## 常见问题

### Q: 端口被占用怎么办？

修改 `.env` 文件中的端口号，或启动时指定：

```bash
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 9999
```

### Q: Termux 上安装依赖失败？

```bash
pkg install python build-essential openssl
pip install --upgrade pip
pip install -r requirements.txt
```

### Q: 如何后台运行？

```bash
nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 9016 > zen2api.log 2>&1 &
```

### Q: 如何停止服务？

```bash
pkill -f "uvicorn app.main:app"
pkill -f "http.server"
```

## 许可证

本项目仅供学习研究使用。
