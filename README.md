# Kiro Proxy Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](pyproject.toml)
[![中文版](https://img.shields.io/badge/语言-中文版-blue)](README.zh-CN.md)

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

### 2. Trust mitmproxy CA certificate

> **⚠️ Security notice:** mitmproxy is a man-in-the-middle proxy. Installing its CA certificate means **this tool can decrypt all HTTPS traffic on your machine**, not just Kiro IDE's. This is because the operating system trusts mitmproxy's root certificate at the system level, allowing any traffic routed through this proxy to be decrypted. If you are not comfortable with this, remove the certificate after use (see `kiro-proxy remove-cert`).

**One-step setup:**

```bash
# Generates the certificate, installs it into the system trust store,
# and verifies everything is working
kiro-proxy install-cert
```

> This runs three steps automatically:
> 1. Starts mitmdump briefly to generate `~/.mitmproxy/mitmproxy-ca-cert.pem` (CA certificate) and `~/.mitmproxy/mitmproxy-ca.pem` (private key)
> 2. Installs the certificate into your OS trust store (requires admin password)
> 3. Verifies the certificate is properly trusted
>
> **Protect the private key** (`~/.mitmproxy/mitmproxy-ca.pem`) — anyone who obtains it can decrypt your HTTPS traffic. If you need to start fresh, run `kiro-proxy reinstall-cert`.

**Manual setup** (if the CLI command doesn't work on your system):

<details>
<summary>Click to expand manual instructions</summary>

**Step 1** — Start mitmdump to generate the CA certificate files (mitmproxy creates them automatically on first run):

```bash
# Start mitmdump, which triggers mitmproxy to generate CA certificates under ~/.mitmproxy/
mitmdump --listen-port 7080 &

# Wait for the cert file to appear, then kill the temporary process
# Using a polling loop is more reliable than a fixed sleep
while [ ! -f ~/.mitmproxy/mitmproxy-ca-cert.pem ]; do sleep 1; done
kill %1 2>/dev/null; wait %1 2>/dev/null
```

> This generates `~/.mitmproxy/mitmproxy-ca-cert.pem` (CA root certificate) and `~/.mitmproxy/mitmproxy-ca.pem` (private key). All subsequent TLS decryption depends on these files.

**Step 2** — Install the CA certificate into the system trust store (OS-specific):

**macOS:**

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  ~/.mitmproxy/mitmproxy-ca-cert.pem
```

> **Note:** On macOS Sequoia and later, you may need to grant your terminal "Full Disk Access" under System Settings → Privacy & Security before it can modify the system keychain.

**Windows (Admin PowerShell):**

```powershell
# Step 1: Generate certificate (press Ctrl+C after seeing output)
mitmdump --listen-port 7080

# Step 2: Install to system root store
certutil -addstore Root %USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.pem
```

**Linux:**

```bash
# Step 1: Generate certificate
mitmdump --listen-port 7080 &
while [ ! -f ~/.mitmproxy/mitmproxy-ca-cert.pem ]; do sleep 1; done
kill %1 2>/dev/null; wait %1 2>/dev/null

# Step 2: Install to system CA directory
sudo cp ~/.mitmproxy/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

</details>

**Verify the certificate is installed:**

```bash
kiro-proxy check-cert
```

#### Remove certificate

```bash
# Removes the certificate from the system trust store
kiro-proxy remove-cert
```

### 3. Configure

```bash
# macOS / Linux
cp config.yaml.example config.yaml

# Windows
copy config.yaml.example config.yaml
```

Edit `config.yaml` with your LLM endpoint and API key.

### 4. Start

```bash
# macOS / Linux — activate venv first (new terminal)
source venv/bin/activate
kiro-proxy start

# Windows — activate venv first (new terminal)
venv\Scripts\activate
kiro-proxy start
```

> After installation, you can also run `python3 -m kiro_proxy start` (or `python -m kiro_proxy start` on Windows) without activating the venv.

### 5. Configure Kiro

Open Kiro Settings (`Cmd+,`) → search "proxy" → set **Http: Proxy** to:

```
http://127.0.0.1:7080
```

### 6. Verify

Send a message in Kiro and check the logs:

```bash
kiro-proxy logs
```

If you see intercepted requests, everything is working.

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
| `kiro-proxy install-cert` | Generate and install CA certificate (one step) |
| `kiro-proxy reinstall-cert` | Force regenerate and reinstall CA certificate |
| `kiro-proxy remove-cert` | Remove CA certificate from system trust store |
| `kiro-proxy check-cert` | Check CA certificate status |

> Run `source venv/bin/activate` (macOS/Linux) or `venv\Scripts\activate` (Windows) in new terminals before using `kiro-proxy`. Alternatively, use `python3 -m kiro_proxy` (`python -m kiro_proxy` on Windows) without activation.

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
# Activate venv (if not already)
source venv/bin/activate

# Run tests
pytest tests/ -v

# Run proxy in foreground with verbose logging
mitmdump -p 7080 -s src/kiro_proxy/kiro_mitmproxy.py -v

# Or use Python module mode (no activation needed)
python3 -m kiro_proxy start

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
