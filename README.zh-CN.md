# Kiro Proxy Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](pyproject.toml)

基于 mitmproxy 的代理工具，拦截 Kiro IDE 的 AI 请求并将其路由到你自己的 LLM 后端。无需改变 Kiro 工作流即可自由切换模型、降低成本、获得可见性。

## 工作原理

```
Kiro IDE                        Kiro Proxy Assistant              Your LLM Backend
   │                                   │                                │
   │  POST /generateAssistantResponse  │                                │
   │  (conversationState + EventStream)│                                │
   ├──────────────────────────────────→│                                │
   │                                   │                                │
   │                                   │  RequestConverter              │
   │                                   │  conversationState → OpenAI    │
   │                                   │                                │
   │                                   │  ModelRouter                   │
   │                                   │  ├─ override (debug)          │
   │                                   │  ├─ user selection (Kiro UI)  │
   │                                   │  └─ content analysis (auto)   │
   │                                   │                                │
   │                                   │  ProviderRouter                │
   │                                   │  ├─ DirectProvider (exact     │
   │                                   │  │   match via config.models) │
   │                                   │  └─ LiteLLMProvider (fallback)│
   │                                   ├───────────────────────────────→│
   │                                   │  Chat Completion API           │
   │                                   │←───────────────────────────────│
   │                                   │                                │
   │                                   │  ResponseAdapter               │
   │                                   │  OpenAI → EventStream frames   │
   │                                   │                                │
   │  AWS EventStream (binary)         │                                │
   │←──────────────────────────────────│                                │
```

## 特性

- **模型自由** — 将请求路由到任意 OpenAI 兼容 API（DeepSeek、Gemini、Claude、OpenAI 等）
- **多 Provider** — 在同一个配置中混合使用 LiteLLM 代理和直连 API
- **智能路由** — 三层模型选择：优先尊重 Kiro UI 下拉菜单选择，其次基于内容自动路由（代码、分析、创意、简单问答）
- **自定义模型列表** — 拦截 `ListAvailableModels`，聚合所有 provider 的模型列表，过滤掉 thinking 模型
- **完整工具支持** — 全部 23 个 Kiro 工具透明可用（bash、文件操作、搜索、网页等）
- **监控** — 请求统计、延迟追踪、模型用量分布
- **即插即用** — 无需修改 Kiro，仅需配置 HTTP 代理

## 快速开始

### 1. 安装

**macOS / Linux:**

```bash
git clone https://github.com/qq289736032/kiro-proxy-assistant.git
cd kiro-proxy-assistant
python3 -m venv venv
source venv/bin/activate
python3 -m pip install -e .
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/qq289736032/kiro-proxy-assistant.git
cd kiro-proxy-assistant
python -m venv venv
venv\Scripts\activate
python -m pip install -e .
```

### 2. 信任 mitmproxy CA 证书

> **⚠️ 安全提示:** mitmproxy 是一个中间人代理（MITM）。安装它的 CA 证书意味着**本工具可以解密你机器上所有的 HTTPS 流量**，而不仅仅限于 Kiro IDE。这是因为操作系统级别信任了 mitmproxy 的根证书后，任何通过该代理的流量都可以被解密。如果你介意这一点，使用完毕后请执行 `kiro-proxy remove-cert` 移除证书。

**一键安装（推荐）：**

```bash
# 自动完成：生成证书 → 安装到系统信任存储 → 验证
kiro-proxy install-cert
```

> 这条命令自动执行三个步骤：
> 1. 短暂启动 mitmdump，生成 `~/.mitmproxy/mitmproxy-ca-cert.pem`（CA 根证书）和 `~/.mitmproxy/mitmproxy-ca.pem`（私钥）
> 2. 将证书安装到操作系统信任存储（需要管理员密码）
> 3. 验证证书是否已被系统信任
>
> **请妥善保护私钥文件**（`~/.mitmproxy/mitmproxy-ca.pem`）——任何人拿到它就能解密你的 HTTPS 流量。如需重新生成，请执行 `kiro-proxy reinstall-cert`。

**手动安装**（如果 CLI 命令在你的系统上不工作）：

<details>
<summary>展开查看手动操作步骤</summary>

**第一步** — 先生成 CA 证书文件：

```bash
# 启动 mitmdump，触发 mitmproxy 自动创建 CA 证书
mitmdump --listen-port 7080 &

# 等待证书文件生成完毕，然后关闭临时进程
while [ ! -f ~/.mitmproxy/mitmproxy-ca-cert.pem ]; do sleep 1; done
kill %1 2>/dev/null; wait %1 2>/dev/null
```

**第二步** — 将证书安装到系统信任存储：

**macOS:**

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  ~/.mitmproxy/mitmproxy-ca-cert.pem
```

> **注意:** macOS Sequoia 及更高版本可能需要先在"系统设置 → 隐私与安全性"中授予终端"完全磁盘访问权限"。

**Windows (管理员 PowerShell):**

```powershell
# 生成证书（看到输出后按 Ctrl+C 停止）
mitmdump --listen-port 7080

# 安装到系统根证书存储
certutil -addstore Root %USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.pem
```

**Linux:**

```bash
# 生成证书
mitmdump --listen-port 7080 &
while [ ! -f ~/.mitmproxy/mitmproxy-ca-cert.pem ]; do sleep 1; done
kill %1 2>/dev/null; wait %1 2>/dev/null

# 安装到系统 CA 目录
sudo cp ~/.mitmproxy/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

</details>

**验证证书已安装：**

```bash
kiro-proxy check-cert
```

#### 移除证书

```bash
# 从系统信任存储中移除证书
kiro-proxy remove-cert
```

### 3. 配置

```bash
# macOS / Linux
cp config.yaml.example config.yaml

# Windows
copy config.yaml.example config.yaml
```

编辑 `config.yaml`，填入你的 LLM 端点地址和 API 密钥。

### 4. 启动

```bash
# macOS / Linux — 先激活虚拟环境（新终端）
source venv/bin/activate
kiro-proxy start

# Windows — 先激活虚拟环境（新终端）
venv\Scripts\activate
kiro-proxy start
```

> 安装后，也可以在不激活虚拟环境的情况下运行 `python3 -m kiro_proxy start`（Windows 上为 `python -m kiro_proxy start`）。

### 5. 配置 Kiro

打开 Kiro 设置（`Cmd+,`）→ 搜索 "proxy" → 将 **Http: Proxy** 设置为：

```
http://127.0.0.1:7080
```

### 6. 验证

在 Kiro 中发送一条消息，然后查看日志：

```bash
kiro-proxy logs
```

如果看到被拦截的请求记录，说明一切正常。

## CLI 命令参考

| 命令 | 说明 |
|------|------|
| `kiro-proxy start` | 启动代理（后台运行，自动配置 Kiro proxy 设置） |
| `kiro-proxy stop` | 停止代理 |
| `kiro-proxy restart` | 重启代理 |
| `kiro-proxy status` | 查看代理运行状态 |
| `kiro-proxy logs` | 实时查看日志 |
| `kiro-proxy stats` | 查看请求统计 |
| `kiro-proxy setup` | 显示配置指引 |
| `kiro-proxy install-cert` | 一键生成并安装 CA 证书 |
| `kiro-proxy reinstall-cert` | 强制重新生成并安装 CA 证书 |
| `kiro-proxy remove-cert` | 从系统信任存储移除 CA 证书 |
| `kiro-proxy check-cert` | 查看 CA 证书状态 |

> 在新终端中使用 `kiro-proxy` 命令前，需要先执行 `source venv/bin/activate`（macOS/Linux）或 `venv\Scripts\activate`（Windows）。也可以使用 `python3 -m kiro_proxy`（Windows 上为 `python -m kiro_proxy`）无需激活环境。

## 配置说明

完整选项参见 [config.yaml.example](config.yaml.example)。

### 环境变量

`config.yaml` 中以 `${VAR}` 形式引用的变量会从环境变量中读取：

```bash
export DEEPSEEK_API_KEY="sk-..."
export OPENAI_API_KEY="sk-..."
export KIRO_PROXY_LOG_LEVEL="DEBUG"
```

## 文档

- [用户指南](docs/USER_GUIDE.md) — 详细设置与故障排查
- [协议参考](docs/KIRO_PROTOCOL.md) — Kiro 后端通信协议格式
- [代码审查](docs/CODE_REVIEW.md) — 架构与代码质量评估

## 开发

```bash
# 激活虚拟环境（如果尚未激活）
source venv/bin/activate

# 运行测试
pytest tests/ -v

# 前台运行代理并输出详细日志
mitmdump -p 7080 -s src/kiro_proxy/kiro_mitmproxy.py -v

# 或使用 Python 模块模式运行（无需激活环境）
python3 -m kiro_proxy start

# 代码结构
src/kiro_proxy/
├── main.py              # CLI 入口（Click）
├── cli.py               # CLI 输出格式化
├── kiro_mitmproxy.py    # mitmproxy 插件（核心拦截逻辑）
├── request_converter.py # conversationState → OpenAI 格式
├── response_adapter.py  # OpenAI → AWS EventStream
├── model_router.py      # 模型选择（override → 用户选择 → 内容）
├── eventstream.py       # AWS EventStream 二进制编解码
├── stats_collector.py   # 请求统计
├── cert_manager.py      # CA 证书生命周期管理
└── providers/           # LLM 后端抽象
    ├── __init__.py      # Provider ABC, ProviderConfig, ModelNameMapper
    ├── router.py        # Provider 路由引擎
    ├── litellm_provider.py
    └── direct_provider.py
```

## 系统要求

- Python 3.9+
- macOS（主力支持）、Linux（实验性支持）
- Kiro IDE v0.12.155+

## 许可证

MIT © 2026 Jisen

---

[English Version](README.md)
