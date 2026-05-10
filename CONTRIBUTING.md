# Contributing

Thanks for your interest! This project is in early stage and contributions are welcome.

## Getting Started

1. Fork and clone the repo
2. Install dev dependencies: `pip install -e ".[dev]"`
3. Run tests: `pytest tests/ -v`

## Making Changes

- Keep pull requests focused on a single concern
- Add or update tests as needed
- Run existing tests before submitting: `pytest tests/ -v`
- Update docs if you change user-facing behavior

## Code Style

- Python 3.9+ type hints are used throughout — please maintain them
- 100 character line length (soft limit)
- Use descriptive names; comments are for non-obvious design decisions
- Log messages in English, comments/docs can be in English or Chinese

## Project Structure

```
src/kiro_proxy/
├── main.py              # CLI (Click commands)
├── kiro_mitmproxy.py    # mitmproxy addon
├── request_converter.py # Kiro → OpenAI format
├── response_adapter.py  # OpenAI → Kiro EventStream
├── model_router.py      # Task-based model selection
├── eventstream.py       # AWS EventStream codec
├── stats_collector.py   # Request stats
└── providers/           # LLM backends
    ├── router.py        # Provider routing
    ├── litellm_provider.py
    └── direct_provider.py
```

## Reporting Issues

Include:
- `kiro-proxy --version` output
- Error logs: `cat ~/.kiro-proxy/proxy.log | tail -50`
- Steps to reproduce

## License

MIT — by contributing, you agree your contributions will be licensed under the same terms.
