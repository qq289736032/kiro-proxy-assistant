# Kiro Proxy Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](pyproject.toml)

A mitmproxy-based proxy that intercepts Kiro IDE's AI requests and routes them to your own LLM backend. Swap models, reduce costs, and gain visibility — without changing your Kiro workflow.

## How It Works

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
   │                                   │  select model by task type     │
   │                                   │                                │
   │                                   │  ProviderRouter                │
   │                                   │  ├─ LiteLLMProvider (default)  │
   │                                   │  └─ DirectProvider             │
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

## Features

- **Model freedom** — Route requests to any OpenAI-compatible API (DeepSeek, Gemini, Claude, OpenAI, etc.)
- **Multi-provider** — Mix LiteLLM proxy and direct API connections in one config
- **Smart routing** — Auto-selects model based on task type (code, analysis, creative, simple)
- **Full tool support** — All 23 Kiro tools work transparently (bash, file ops, search, web, etc.)
- **Monitoring** — Request stats, latency tracking, model usage breakdown
- **Drop-in replacement** — No changes to Kiro, just configure HTTP proxy

## Quick Start

### 1. Install

```bash
git clone https://github.com/qq289736032/kiro-proxy-assistant.git
cd kiro-proxy-assistant
python -m venv venv
source venv/bin/activate
pip install -e .
```

Trust the mitmproxy CA certificate:

```bash
mitmdump --listen-port 7080 &  # generates certificate on first run
sleep 2 && kill %1

sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  ~/.mitmproxy/mitmproxy-ca-cert.pem
```

### 2. Configure

```bash
cp config.yaml.example config.yaml
# Edit config.yaml with your LLM endpoint and API key
```

### 3. Start

```bash
kiro-proxy start
```

### 4. Configure Kiro

Open Kiro Settings (`Cmd+,`) → search "proxy" → set **Http: Proxy** to:

```
http://127.0.0.1:7080
```

Send a message in Kiro and verify with `kiro-proxy logs`.

## CLI Reference

| Command | Description |
|---------|-------------|
| `kiro-proxy start` | Start the proxy (background) |
| `kiro-proxy stop` | Stop the proxy |
| `kiro-proxy restart` | Restart the proxy |
| `kiro-proxy status` | Check if proxy is running |
| `kiro-proxy logs` | Tail real-time logs |
| `kiro-proxy stats` | View request statistics |
| `kiro-proxy setup` | Show configuration guide |
| `kiro-proxy start --port 7080` | Start on a custom port |

## Configuration

See [config.yaml.example](config.yaml.example) for all options.

### Environment Variables

Variables referenced as `${VAR}` in `config.yaml` are resolved from the environment:

```bash
export DEEPSEEK_API_KEY="sk-..."
export OPENAI_API_KEY="sk-..."
export KIRO_PROXY_LOG_LEVEL="DEBUG"
```

## Documentation

- [User Guide](docs/USER_GUIDE.md) — detailed setup and troubleshooting
- [Protocol Reference](docs/KIRO_PROTOCOL.md) — Kiro backend wire format
- [Code Review](docs/CODE_REVIEW.md) — architecture and code quality assessment

## Development

```bash
# Run tests
pytest tests/ -v

# Run proxy in foreground with verbose logging
mitmdump -p 7080 -s src/kiro_proxy/kiro_mitmproxy.py -v

# Code structure
src/kiro_proxy/
├── main.py              # CLI entry point
├── kiro_mitmproxy.py    # mitmproxy addon (core interception)
├── request_converter.py # conversationState → OpenAI format
├── response_adapter.py  # OpenAI → AWS EventStream
├── model_router.py      # Model selection by task type
├── eventstream.py       # AWS EventStream binary codec
├── stats_collector.py   # Request statistics
└── providers/           # LLM backend abstraction
    ├── router.py        # Provider routing engine
    ├── litellm_provider.py
    └── direct_provider.py
```

## Requirements

- Python 3.9+
- macOS (primary), Linux (experimental)
- Kiro IDE v0.12.155+

## License

MIT © 2026 Jisen
