# Kiro 后端协议完整文档

**基于实际抓包数据 (2026-05-08)**
**Kiro 版本**: 0.12.155
**后端**: q.us-east-1.amazonaws.com (Amazon Q / CodeWhisperer Streaming API)

---

## 1. 架构概览

```
┌─────────────┐     HTTPS      ┌──────────────────────────────────┐
│  Kiro IDE   │ ──────────────→ │  q.us-east-1.amazonaws.com       │
│  (Electron) │                 │  (AWS CodeWhisperer Streaming)   │
└─────────────┘                 └──────────────────────────────────┘
      │                                       │
      │  POST /mcp                            │  JSON-RPC 2.0
      │  POST /generateAssistantResponse      │  AWS EventStream
      │  GET  /getUsageLimits                 │  JSON
      │                                       │
```

## 2. 端点清单

| 端点 | 方法 | 用途 | 响应格式 |
|------|------|------|----------|
| `/mcp` | POST | MCP 工具发现 (tools/list) | JSON (JSON-RPC 2.0) |
| `/generateAssistantResponse` | POST | AI 对话生成 | AWS EventStream (binary) |
| `/getUsageLimits` | GET | 用量/配额查询 | JSON |

## 3. 认证

### Bearer Token 格式
```
Authorization: Bearer <session_token>:<signature>
```

- **session_token**: `aoaAAAAA...` 开头的 AWS SSO session token
- **signature**: ECDSA 签名 (MGUC... 格式)
- **完整示例**: `Bearer aoaAAAAAGn9Nd4z0ryEQ3KpN...:<ECDSA_SIGNATURE>`

### Profile ARN
```
x-amzn-kiro-profile-arn: arn:aws:codewhisperer:us-east-1:<account_id>:profile/<profile_id>
```

## 4. 客户端标识

### User-Agent
```
aws-sdk-js/1.0.34 ua/2.1 os/darwin#24.5.0 lang/js md/nodejs#22.22.0 
api/codewhispererstreaming#1.0.34 m/E 
KiroIDE-<version>-<build_hash>
```

### x-amz-user-agent
```
aws-sdk-js/1.0.34 KiroIDE-0.12.155-<build_hash>
```

## 5. 请求流程（一次用户消息）

```
用户在 Kiro 中发送消息
         │
         ▼
┌─────────────────────────────────────┐
│ ① POST /mcp                         │
│    body: {"method":"tools/list"}     │
│    → 获取服务端 MCP 工具列表          │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│ ② POST /generateAssistantResponse   │
│    header: x-amzn-kiro-agent-mode:  │
│            intent-classification     │
│    modelId: "simple-task"            │
│    → 意图分类 (chat/do/spec)         │
└─────────────────────────────────────┘
         │
         ▼ (可能重复一次确认)
┌─────────────────────────────────────┐
│ ③ POST /generateAssistantResponse   │
│    header: x-amzn-kiro-agent-mode:  │
│            vibe                      │
│    modelId: "deepseek-3.2"           │
│    → 实际 Agent 执行                 │
│    (包含完整工具定义 ~470KB)          │
└─────────────────────────────────────┘
         │
         ▼ (Agent 可能多轮 tool use)
┌─────────────────────────────────────┐
│ ④ POST /generateAssistantResponse   │
│    → Agent 后续轮次                  │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│ ⑤ GET /getUsageLimits               │
│    → 查询用量配额                    │
└─────────────────────────────────────┘
```

## 6. `/mcp` 端点详情

### 请求
```json
{
  "id": "tools_list",
  "jsonrpc": "2.0",
  "method": "tools/list"
}
```

### 响应
```json
{
  "error": null,
  "id": "tools_list",
  "jsonrpc": "2.0",
  "result": {
    "tools": [
      {
        "name": "web_search",
        "description": "WebSearch looks up information...",
        "inputSchema": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string",
              "description": "The search query. Must be 200 characters or less."
            }
          },
          "required": ["query"]
        }
      }
    ]
  }
}
```

**注意**: 这是服务端提供的 MCP 工具（如 web_search），与客户端本地工具（如 execute_bash, read_file 等）不同。

## 7. `/generateAssistantResponse` 端点详情

### 7.1 请求结构

#### Headers
```
content-type: application/json
x-amzn-kiro-agent-mode: intent-classification | vibe
x-amzn-kiro-profile-arn: arn:aws:codewhisperer:...
Authorization: Bearer <token>
```

#### Body 结构
```json
{
  "conversationState": {
    "agentContinuationId": "<uuid>",
    "agentTaskType": "vibe",
    "chatTriggerType": "MANUAL",
    "conversationId": "<uuid>",
    "currentMessage": {
      "userInputMessage": {
        "content": "<用户消息文本 + EnvironmentContext>",
        "modelId": "simple-task" | "deepseek-3.2",
        "origin": "AI_EDITOR",
        "userInputMessageContext": {
          "tools": [...]  // 仅在 vibe 模式下包含
        }
      }
    },
    "history": [
      {
        "userInputMessage": { "content": "...", "modelId": "...", "origin": "..." }
      },
      {
        "assistantResponseMessage": { "content": "...", "toolUses": [] }
      }
    ]
  },
  "profileArn": "arn:aws:codewhisperer:us-east-1:<account>:profile/<id>"
}
```

### 7.2 Agent 模式

#### `intent-classification` 模式
- **modelId**: `"simple-task"` (轻量模型)
- **用途**: 将用户意图分类为 chat/do/spec
- **history[0]**: 包含完整的 intent classifier system prompt
- **响应**: `{"chat": 0.0, "do": 1.0, "spec": 0.0}`
- **请求大小**: ~5-6KB

#### `vibe` 模式
- **modelId**: `"deepseek-3.2"` (主力模型)
- **用途**: 实际的 Agent 执行
- **userInputMessageContext.tools**: 包含完整的工具定义 schema
- **请求大小**: ~470KB (因为包含所有工具定义)
- **响应**: 流式 EventStream

### 7.3 工具定义 (在 vibe 模式中)

客户端提供的工具列表：
| 工具名 | 用途 |
|--------|------|
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
| `web_search` | 网络搜索 (远程MCP) |
| `web_fetch` | 获取网页内容 |
| `disclose_context` | 激活 Skills |
| `invoke_sub_agent` | 调用子 Agent |
| `create_hook` | 创建 Hook |
| `kiro_powers` | 管理 Powers |

### 7.4 响应格式 (AWS EventStream)

响应使用 `application/vnd.amazon.eventstream` 格式，是 AWS 自定义的二进制流协议。

#### EventStream 帧结构
```
[4 bytes: total_length][4 bytes: headers_length][4 bytes: prelude_crc]
[headers...][payload...][4 bytes: message_crc]
```

#### 事件类型

**1. assistantResponseEvent** — AI 回复内容 (流式 token)
```json
{"content": "token文本", "modelId": "simple-task"}
```

**2. contextUsageEvent** — 上下文使用率
```json
{"contextUsagePercentage": 2.8294999599456787}
```

**3. meteringEvent** — 计费信息
```json
{"unit": "credit", "unitPlural": "credits", "usage": 0.008162768026533996}
```

## 8. `/getUsageLimits` 端点详情

### 请求
```
GET /getUsageLimits?origin=AI_EDITOR&profileArn=<arn>&resourceType=AGENTIC_REQUEST
```

### 响应
```json
{
  "nextDateReset": 1780272000.0,
  "subscriptionInfo": {
    "subscriptionTitle": "KIRO FREE",
    "type": "Q_DEVELOPER_STANDALONE_FREE",
    "upgradeCapability": "UPGRADE_CAPABLE"
  },
  "usageBreakdownList": [
    {
      "displayName": "Credit",
      "displayNamePlural": "Credits",
      "freeTrialInfo": {
        "currentUsage": 137,
        "freeTrialExpiry": 1779095637149,
        "freeTrialStatus": "ACTIVE",
        "usageLimit": 500
      },
      "usageLimit": 50,
      "overageRate": 0.04,
      "resourceType": "CREDIT",
      "unit": "INVOCATIONS"
    }
  ],
  "userInfo": {
    "userId": "d-9067c98495.14889498-9041-701c-4550-39b102767c08"
  }
}
```

## 9. 消息格式细节

### EnvironmentContext 注入
Kiro 自动在用户消息中注入环境上下文：
```xml
<EnvironmentContext>
This information is provided as context about user environment. Only consider it if it's relevant to the user request ignore it otherwise.

<OPEN-EDITOR-FILES>
<file name="/Users/jisen/project/WorkTool/kiro_capture.py" />
</OPEN-EDITOR-FILES>

<ACTIVE-EDITOR-FILE>
<file name="/Users/jisen/project/WorkTool/kiro_capture.py" />
</ACTIVE-EDITOR-FILE>
</EnvironmentContext>
```

### Intent Classifier System Prompt
history[0] 中包含完整的意图分类 prompt，指导模型输出：
```json
{"chat": 0.0, "do": 1.0, "spec": 0.0}
```

### Assistant 响应格式 (history 中)
```json
{
  "assistantResponseMessage": {
    "content": "回复文本...",
    "toolUses": []
  }
}
```

## 10. 关键常量

| 常量 | 值 |
|------|-----|
| 后端域名 | `q.us-east-1.amazonaws.com` |
| SDK 版本 | `aws-sdk-js/1.0.34` |
| API 名称 | `codewhispererstreaming#1.0.34` |
| 意图分类模型 | `simple-task` |
| Agent 主模型 | `deepseek-3.2` |
| 最大重试 | 3 次 |
| Profile ARN 格式 | `arn:aws:codewhisperer:<region>:<account>:profile/<id>` |
| 订阅类型 | `Q_DEVELOPER_STANDALONE_FREE` |
| Free Trial 额度 | 500 Credits |
| 超额费率 | $0.04/credit |

## 11. 代理拦截要点

### 需要拦截的请求
1. `POST /generateAssistantResponse` — 核心 AI 对话
2. `POST /mcp` — 可选，可以注入自定义工具

### 不需要拦截的请求
1. `GET /getUsageLimits` — 用量查询，可以透传

### 拦截难点
1. **AWS EventStream 响应**: 二进制协议，需要正确编解码
2. **请求体巨大**: vibe 模式 ~470KB，包含完整工具定义
3. **多轮对话**: Agent 可能多次调用 generateAssistantResponse
4. **认证透传**: Bearer token 需要保持有效

---

## 12. 工具调用帧格式 (toolUseEvent)

从 `212047_39`、`212558_60` 等抓包中解码确认的工具调用帧序列：

```
工具调用场景帧序列
═══════════════════

Phase 1 — 流式文本帧（可选，1~N 个 assistantResponseEvent）
───────────────────────────────────────────────────────────
assistantResponseEvent  {"content": "文本内容...",       "modelId": "deepseek-3.2"}
assistantResponseEvent  {"content": "...\n\n<｜DSML｜function_calls",
                                                         "modelId": "deepseek-3.2"}
  ↑ <｜DSML｜function_calls> 是流式文本标记，提示 Kiro 即将调用工具

Phase 2 — 工具调用帧（每工具 3 个 toolUseEvent）
───────────────────────────────────────────────
  Frame 2a: 声明
toolUseEvent  {"name": "execute_bash", "toolUseId": "tooluse_3rwwjuqbafUEMkqhykqaud"}

  Frame 2b: 输入参数（input 是 JSON-stringified 字符串）
toolUseEvent  {"input": "{\"command\":\"git status\",\"explanation\":\"...\"}",
               "name": "execute_bash",
               "toolUseId": "tooluse_3rwwjuqbafUEMkqhykqaud"}

  Frame 2c: 停止信号
toolUseEvent  {"name": "execute_bash", "stop": true,
               "toolUseId": "tooluse_3rwwjuqbafUEMkqhykqaud"}

Phase 3 — 收尾帧（固定）
───────────────────────
assistantResponseEvent  {"content": "",                    "modelId": "deepseek-3.2"}
contextUsageEvent       {"contextUsagePercentage": 15.2}
meteringEvent           {"unit": "credit", ...}
```

### 格式要点

1. **`toolUseEvent` 是独立事件类型** — `:event-type` header 值为 `toolUseEvent`（14 字节），非 `assistantResponseEvent` 的子字段
2. **`<｜DSML｜function_calls>` 是文本标记** — 以普通文本 token 通过 `assistantResponseEvent` 帧发送，不是特殊事件类型
3. **每工具 3 帧** — 声明 → 输入 → 停止，`toolUseId` 贯穿三帧保持一致
4. **收尾 `assistantResponseEvent`** — content 为空字符串，表示工具调用结束

## 13. 工具调用结果格式 (toolResults)

从 `212103_41` 等抓包确认的 toolResults 格式：

```json
{
  "userInputMessage": {
    "content": "",
    "modelId": "deepseek-3.2",
    "origin": "AI_EDITOR",
    "userInputMessageContext": {
      "toolResults": [{
        "toolUseId": "tooluse_RNsKjqJU4Nx9mlahvdp1il",
        "content": [{"text": "Directory: /Users/..."}],
        "status": "success"
      }]
    }
  }
}
```

toolResults 出现在：
- `history[].userInputMessage.userInputMessageContext.toolResults`（历史工具执行结果）
- `currentMessage.userInputMessage.userInputMessageContext.toolResults`（当前工具执行结果）

---

**文档版本**: 1.1
**更新内容**: 新增 toolUseEvent 帧格式（Section 12）、toolResults 格式（Section 13）
**数据来源**: mitmproxy 抓包 (2026-05-08 ~ 2026-05-10)
**抓包文件**: `kiro_captures/` 目录
