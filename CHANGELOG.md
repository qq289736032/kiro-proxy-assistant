# Changelog

## [0.2.0] - 2026-05-10

### Added
- Multi-provider architecture: LiteLLMProvider + DirectProvider abstraction
- ProviderRouter with model-based routing and fallback
- Smart model routing based on task type (code/analysis/creative/simple)
- Intent-classification routing (fast lightweight model)
- `stats` CLI command for request statistics
- `setup` CLI command for configuration guide
- Tool calls support (toolUseEvent frames, not embedded in assistant response)
- File logging with configurable level and detail level
- Raw data capture mode for debugging
- Port availability check before starting proxy
- Process health check after startup (2-second wait + kill verification)

### Changed
- CLI now verifies process is alive after `start` instead of blind success
- Tool calls use independent `toolUseEvent` frames (3 per tool: declare → input → stop)
- `<｜DSML｜function_calls>` marker added before tool call sequences
- Request converter handles toolUses → tool_calls and toolResults → tool role
- Response adapter handles text + tool calls mixed responses
- Config-driven model routing (YAML file instead of hardcoded)

### Fixed
- Tool call EventStream frame format (was embedded in assistantResponseEvent)
- Port already-in-use detection before binding
- Process crash detection with log tail on failure

## [0.1.0] - 2026-05-08

### Added
- Initial proof of concept
- AWS EventStream binary codec (encoder/decoder)
- Request converter (conversationState → OpenAI format)
- Response adapter (OpenAI → EventStream frames)
- mitmproxy addon for request interception and response injection
- Basic CLI (start/stop/status/logs)
- Protocol documentation from captured data
