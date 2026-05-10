# Kiro Proxy Assistant 用户指南

## 概述

Kiro Proxy Assistant 是一个中间人代理，将 Kiro IDE 的 AI 请求路由到您自己的 LLM 后端。通过此代理，您可以：

- 使用不同的 AI 模型（DeepSeek、Gemini、Claude 等）
- 通过 LiteLLM 聚合层或直连 API 调用模型
- 实现智能模型路由（基于任务类型自动选择最佳模型）
- 监控和统计 AI 使用情况
- 控制成本和延迟

## 快速开始

### 1. 安装

```bash
# 进入项目目录
cd /Users/jisen/project/WorkTool/kiro-proxy-assistant

# 安装依赖
pip install -e .

# 安装 mitmproxy CA 证书（仅首次）
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  ~/.mitmproxy/mitmproxy-ca-cert.pem

# 验证安装
kiro-proxy --version
```

### 2. 配置

编辑 `config.yaml` 文件：

```yaml
# LiteLLM 代理配置（默认兜底 Provider）
litellm:
  base_url: "https://test-ai.igovee.com"  # 您的 LiteLLM 地址
  api_key: "sk-..."                       # 您的 API key，支持 ${ENV_VAR} 语法
  timeout: 60
  retries: 2                              # 5xx/timeout 自动重试次数

# 直连 Provider（可选，不经过 LiteLLM）
direct_providers:
  deepseek:
    api_base: "https://api.deepseek.com"
    api_key: "${DEEPSEEK_API_KEY}"
    models: ["deepseek-v3", "deepseek-r1"]
    extra_body:                            # Provider 特有参数
      thinking: true
  openai:
    api_base: "https://api.openai.com"
    api_key: "${OPENAI_API_KEY}"
    models: ["gpt-4o", "gpt-4o-mini"]

# 代理监听端口
proxy:
  port: 7080
  host: "127.0.0.1"

# 模型路由配置（可选）
model_routing:
  intent_classification: "gemini-3.1-flash-lite"
  vibe_default: "deepseek-v3"
  task_models:
    code: "deepseek-v3"
    analysis: "gemini-3-flash"
    creative: "claude-sonnet-4.5"
    simple: "gemini-3.1-flash-lite"
  override: ""  # 留空使用自动路由，设置模型名可强制覆盖
```

### 3. 启动代理

```bash
# 启动代理
kiro-proxy start

# 检查状态
kiro-proxy status

# 查看日志
kiro-proxy logs
```

### 4. 配置 Kiro

1. 打开 Kiro Settings (Cmd+,)
2. 搜索 "proxy"
3. 设置 HTTP Proxy: `http://127.0.0.1:7080`
4. 保存设置

### 5. 验证

在 Kiro 中发送消息，查看代理日志：

```bash
kiro-proxy logs
# 应该看到类似:
# [127.0.0.1:54321] Intercepting: POST /generateAssistantResponse
# [127.0.0.1:54321] Agent mode: vibe
# [127.0.0.1:54321] Routed to model: deepseek-v3
# [127.0.0.1:54321] Using provider: litellm
# [127.0.0.1:54321] Response injected successfully
```

## CLI 命令

### 基本命令

```bash
# 启动代理
kiro-proxy start

# 停止代理
kiro-proxy stop

# 重启代理
kiro-proxy restart

# 检查状态
kiro-proxy status

# 查看实时日志
kiro-proxy logs

# 查看统计信息
kiro-proxy stats

# 显示设置指南
kiro-proxy setup
```

### 高级命令

```bash
# 使用特定端口启动
kiro-proxy start --port 7080

# 显示配置指南
kiro-proxy setup

# 查看帮助
kiro-proxy --help
kiro-proxy start --help
```

## 配置详解

### 配置文件位置

- 主配置文件: `config.yaml`（项目根目录）
- 用户配置文件: `~/.kiro-proxy/config.yaml`（可选，覆盖主配置）

### LiteLLM 配置

```yaml
litellm:
  base_url: "https://your-litellm-server.com"  # 必需
  api_key: "sk-..."                            # 必需，支持 ${ENV_VAR} 语法
  timeout: 60                                   # 可选，默认 60 秒
  retries: 2                                    # 可选，5xx/timeout 重试次数
```

### 直连 Provider 配置

```yaml
direct_providers:
  provider_name:                               # 自定义名称
    api_base: "https://api.provider.com"       # 必需
    api_key: "${API_KEY}"                      # 必需，支持环境变量引用
    models:                                    # 必需，该 Provider 支持的模型列表
      - "model-a"
      - "model-b"
    extra_body:                                # 可选，Provider 特有参数
      thinking: true
```

路由策略：优先按模型名匹配 `direct_providers`，未命中则回退到 `litellm` 默认 Provider。

### 模型路由配置

```yaml
model_routing:
  # intent-classification 模式使用的模型
  intent_classification: "gemini-3.1-flash-lite"
  
  # vibe 模式默认模型
  vibe_default: "deepseek-v3"
  
  # 任务类型 → 模型映射
  task_models:
    code: "deepseek-v3"           # 代码相关任务
    analysis: "gemini-3-flash"    # 分析相关任务
    creative: "claude-sonnet-4.5" # 创意相关任务
    simple: "gemini-3.1-flash-lite" # 简单任务
  
  # 强制覆盖（留空则使用自动路由）
  override: ""
```

### 日志配置

```yaml
logging:
  # 基本日志级别
  level: "INFO"  # DEBUG / INFO / WARNING / ERROR
  
  # 文件日志配置
  file: "~/.kiro-proxy/proxy.log"
  max_file_size: "10MB"  # 支持 KB/MB/GB
  backup_count: 5
  
  # 详细日志级别（仅在 DEBUG 时生效）
  # 0: minimal - 只记录错误和关键信息
  # 1: normal - 记录处理流程（默认）
  # 2: detailed - 记录请求/响应摘要
  # 3: full - 记录完整请求/响应内容
  detail_level: 1
  
  # 模块特定日志级别
  modules:
    request_converter: "INFO"
    response_adapter: "INFO"
    eventstream: "INFO"
    tool_calls: "INFO"
    
  # 原始数据捕获（用于调试）
  enable_capture: false
  capture_path: "~/.kiro-proxy/captures/"
```

## 环境变量

配置可以通过环境变量覆盖：

```bash
# 覆盖 LiteLLM 配置
export LITELLM_BASE_URL="https://custom-litellm.com"
export LITELLM_API_KEY="sk-custom-key"

# 覆盖日志级别
export KIRO_PROXY_LOG_LEVEL="DEBUG"

# Provider API Key（通过 config.yaml 中 ${VAR} 语法引用）
export DEEPSEEK_API_KEY="sk-..."
export OPENAI_API_KEY="sk-..."

# 启动代理（使用环境变量）
kiro-proxy start
```

## 功能特性

### 智能模型路由

代理根据消息内容自动选择最佳模型：

| 任务类型 | 检测关键词 | 路由模型 |
|----------|------------|----------|
| 代码任务 | `function`, `class`, `import`, `def`, `代码` | deepseek-v3 |
| 分析任务 | `分析`, `数据`, `统计`, `趋势`, `insight` | gemini-3-flash |
| 创意任务 | `故事`, `创意`, `营销`, `设计`, `creative` | claude-sonnet-4.5 |
| 简单任务 | 其他 | gemini-3.1-flash-lite |

### 工具调用支持

支持 Kiro 的所有内置工具（共 23 个）：

| 工具 | 用途 |
|------|------|
| `execute_bash` | 执行 bash 命令 |
| `control_bash_process` | 管理后台进程 |
| `list_processes` | 列出后台进程 |
| `get_process_output` | 读取进程输出 |
| `list_directory` | 列出目录内容 |
| `read_file` | 读取单个文件 |
| `read_files` | 读取多个文件 |
| `file_search` | 模糊文件搜索 |
| `grep_search` | 正则文本搜索 |
| `delete_file` | 删除文件 |
| `fs_write` | 创建/写入文件 |
| `fs_append` | 追加文件内容 |
| `str_replace` | 字符串替换 |
| `semantic_rename` | 语义重命名 |
| `smart_relocate` | 智能移动文件 |
| `get_diagnostics` | 获取代码诊断 |
| `read_code` | 读取代码结构 |
| `web_search` | 网络搜索（远程 MCP） |
| `web_fetch` | 获取网页内容 |
| `disclose_context` | 激活 Skills |
| `invoke_sub_agent` | 调用子 Agent |
| `create_hook` | 创建 Hook |
| `kiro_powers` | 管理 Powers |

代理会自动将 Kiro 的工具调用格式转换为 OpenAI `tool_calls` 格式，并在响应时还原为 Kiro 期望的 `toolUseEvent` 独立帧序列（每工具 3 帧：声明 → 输入 → 停止）。

### 意图分类 (Intent-Classification)

自动识别用户意图：
- `chat` - 普通聊天
- `do` - 执行任务
- `spec` - 创建规范

### 流式响应

支持非流式响应（Phase 1），流式响应在 Phase 2 中实现。

## 监控和统计

### 实时统计

```bash
kiro-proxy stats
```

输出示例：
```
Kiro Proxy Statistics
──────────────────────
Total Requests:  42
Total Responses: 42
Errors:          0
Avg Latency:     85.3ms

Model Usage:
  deepseek-v3: 25
  gemini-3-flash: 10
  gemini-3.1-flash-lite: 7
```

### 日志分析

日志文件位置：`~/.kiro-proxy/proxy.log`

关键日志模式：
```
# 请求拦截
[127.0.0.1:54321] Intercepting: POST /generateAssistantResponse

# 模型路由
[127.0.0.1:54321] Routed to model: deepseek-v3

# 工具调用
[127.0.0.1:54321] Tool calls detected: ['list_directory', 'read_file']

# 成功响应
[127.0.0.1:54321] Response injected successfully

# 错误处理
[127.0.0.1:54321] Error processing request: ...
[127.0.0.1:54321] Falling back to error response
```

## 故障排除

### 常见问题

#### 1. 代理无法启动

**症状**: `kiro-proxy start` 失败

**解决方案**:
```bash
# 检查端口占用
lsof -ti:7080

# 如果端口被占用
kill -9 $(lsof -ti:7080)

# 查看详细错误
tail -20 ~/.kiro-proxy/proxy.log
```

#### 2. Kiro 无法连接代理

**症状**: Kiro 显示连接错误

**解决方案**:
1. 验证代理正在运行: `kiro-proxy status`
2. 检查 Kiro proxy 设置: `http://127.0.0.1:7080`
3. 验证证书安装:
   ```bash
   security find-certificate -c "mitmproxy" -a
   ```
4. 重启 Kiro

#### 3. 没有 AI 回复

**症状**: Kiro 发送消息后无响应

**解决方案**:
```bash
# 检查代理日志
kiro-proxy logs

# 检查 LiteLLM 连接
curl -X POST https://test-ai.igovee.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"test"}]}'

# 启用详细日志
export KIRO_PROXY_LOG_LEVEL=DEBUG
kiro-proxy restart
```

#### 4. 工具调用不工作

**症状**: AI 不执行工具调用

**解决方案**:
1. 检查工具定义格式
2. 启��工具调用日志:
   ```yaml
   logging:
     modules:
       tool_calls: "DEBUG"
   ```
3. 重启代理

#### 5. 性能问题

**症状**: 响应延迟高

**解决方案**:
1. 检查网络连接
2. 查看延迟统计: `kiro-proxy stats`
3. 考虑使用更快的模型
4. 调整超时设置:
   ```yaml
   litellm:
     timeout: 30  # 减少超时时间
   ```

### 日志级别调试

根据问题类型启用不同日志级别：

```bash
# 基本问题排查
export KIRO_PROXY_LOG_LEVEL=INFO

# 详细调试
export KIRO_PROXY_LOG_LEVEL=DEBUG

# 工具调用问题
export KIRO_PROXY_LOG_LEVEL=DEBUG
# 并在 config.yaml 中设置:
# logging.modules.tool_calls: "DEBUG"

# 请求/响应格式问题
export KIRO_PROXY_LOG_LEVEL=DEBUG
# 并在 config.yaml 中设置:
# logging.detail_level: 2  # 或 3 查看完整内容
```

### 原始数据捕获

对于复杂问题，启用原始数据捕获：

```yaml
logging:
  enable_capture: true
  capture_path: "~/.kiro-proxy/captures/"
```

捕获文件包含完整的请求/响应数据，用于离线分析。

## 高级用法

### 自定义模型路由

创建自定义路由规则：

```python
# 自定义路由逻辑示例
def custom_router(content: str, agent_mode: str) -> str:
    if "紧急" in content or "urgent" in content:
        return "claude-sonnet-4.5"  # 紧急任务使用 Claude
    
    if "中文" in content or "Chinese" in content:
        return "deepseek-v3"  # 中文任务使用 DeepSeek
    
    # 默认路由
    return "gemini-3.1-flash-lite"
```

### 多代理配置

运行多个代理实例：

```bash
# 实例 1（默认端口 7080）
kiro-proxy start

# 实例 2（不同端口）
kiro-proxy start --port 7081

# 在 Kiro 中切换代理
# http://127.0.0.1:7080 或 http://127.0.0.1:7081
```

### 集成测试

运行集成测试套件：

```bash
cd /Users/jisen/project/WorkTool/kiro-proxy-assistant
python -m pytest tests/ -v

# 运行特定测试
python -m pytest tests/test_integration.py -v
python -m pytest tests/test_response_adapter.py::TestResponseAdapter::test_adapt_tool_calls_response -v
```

## 安全注意事项

### 证书安全

- mitmproxy CA 证书应仅安装在受信任的设备上
- 不要共享证书私钥
- 定期更新证书

### API Key 安全

- 不要将 API key 提交到版本控制
- 使用环境变量或配置文件
- 定期轮换 API key

### 网络安全

- 代理仅在本地运行 (127.0.0.1)
- 不要将代理暴露到公网
- 使用 HTTPS 连接到 LiteLLM 或直连 Provider

## 更新和维护

### 更新代理

```bash
# 拉取最新代码
cd /Users/jisen/project/WorkTool/kiro-proxy-assistant
git pull

# 重新安装
pip install -e .

# 重启代理
kiro-proxy restart
```

### 清理日志

```bash
# 清理旧日志文件
rm -f ~/.kiro-proxy/proxy.log*
rm -f ~/.kiro-proxy/mitmdump.log*  # mitmdump 自身输出
rm -f ~/.kiro-proxy/captures/*.json  # 如果启用了捕获

# 重置统计
rm -f ~/.kiro-proxy/stats.json
```

### 性能监控

定期检查：
- 磁盘使用: `du -sh ~/.kiro-proxy/`
- 内存使用: `ps aux | grep mitmdump`
- 连接数: `netstat -an | grep :9080 | wc -l`

## 支持与反馈

### 获取帮助

1. 查看文档: `docs/` 目录
2. 检查日志: `kiro-proxy logs`
3. 运行诊断: `kiro-proxy status`

### 报告问题

报告问题时请提供：
1. Kiro Proxy 版本: `kiro-proxy --version`
2. 操作系统版本
3. 错误日志: `tail -50 ~/.kiro-proxy/proxy.log`
4. 复现步骤

### 功能请求

欢迎提交功能请求，包括：
- 新模型支持
- 高级路由规则
- 监控功能增强
- 性能优化

## 附录

### 兼容性

- **Kiro 版本**: v0.12.155+（已验证）
- **操作系统**: macOS（主要支持），Linux（实验性）
- **Python**: 3.9+
- **mitmproxy**: 10.0.0+

### 性能指标

- 启动时间: < 5秒
- 请求处理延迟: < 100ms（不含 LLM 响应时间）
- 内存占用: ~50MB
- 并发连接: 支持多用户

### 已知限制

1. 流式响应暂不支持（Phase 2）
2. 某些高级工具可能不完全兼容
3. 大规模并发需要性能优化
4. 跨平台支持有限

### 未来计划

- [ ] 流式响应支持
- [ ] Web 界面管理
- [ ] 高级路由规则引擎
- [ ] 插件系统
- [ ] 跨平台支持
- [ ] 集群部署