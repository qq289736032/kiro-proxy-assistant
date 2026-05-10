"""响应适配器：OpenAI 响应 → AWS EventStream 格式。

将 LiteLLM/OpenAI 的 Chat Completion 响应转换为
Kiro 期望的 AWS EventStream 二进制流格式。
"""

import json
import logging
from typing import Dict, Any, List, Optional
from mitmproxy import http

from .eventstream import EventStreamEncoder

logger = logging.getLogger(__name__)


class ResponseAdapter:
    """将 OpenAI 响应转换为 Kiro 期望的 AWS EventStream 格式。"""

    def __init__(self):
        self.encoder = EventStreamEncoder()

    def adapt(self, openai_response: Dict[str, Any],
              model_id: str = "deepseek-3.2") -> bytes:
        """将 OpenAI 响应转换为 EventStream 二进制数据。

        自动检测响应类型：
        - finish_reason == "tool_calls" → 先发送文本帧（含 <｜DSML｜function_calls> 标记），再发送工具调用帧
        - 其他 → 文本回复帧
        """
        choices = openai_response.get("choices", [])
        if choices:
            choice = choices[0]
            finish_reason = choice.get("finish_reason", "")

            # 工具调用响应
            if finish_reason == "tool_calls":
                tool_uses = self._extract_tool_calls(openai_response)
                if tool_uses:
                    logger.info(f"  Tool calls detected: {[t['name'] for t in tool_uses]}")
                    
                    # 先提取文本内容（如果有的话）
                    message = choice.get("message", {})
                    text_content = message.get("content", "")
                    
                    frames = b""
                    
                    # 1. 如果有文本内容，先发送文本帧
                    if text_content:
                        # 在文本内容后添加 <｜DSML｜function_calls> 标记
                        if not text_content.endswith("\n\n<｜DSML｜function_calls"):
                            text_content += "\n\n<｜DSML｜function_calls"
                        frames += self.encoder.encode_assistant_response(text_content, model_id)
                    else:
                        # 如果没有文本内容，发送空的文本帧加上 <｜DSML｜function_calls> 标记
                        frames += self.encoder.encode_assistant_response("<｜DSML｜function_calls", model_id)
                    
                    # 2. 发送工具调用帧序列
                    frames += self.adapt_tool_calls(tool_uses, model_id)
                    
                    return frames
                else:
                    logger.error(f"  finish_reason=tool_calls but no tool_calls extracted: {openai_response}")
                    return self.create_error_response("Tool call extraction failed", model_id)

        # 文本回复
        content = self._extract_content(openai_response)
        if content is None:
            logger.error(f"Failed to extract content from response: {openai_response}")
            return self.create_error_response("Failed to get response from AI model.", model_id)

        return self.encoder.build_full_response(content, model_id)

    def adapt_tool_calls(self, tool_uses: List[Dict[str, Any]],
                         model_id: str = "deepseek-3.2") -> bytes:
        """将工具调用列表转换为 toolUseEvent 帧序列。

        根据真实抓包数据，每个工具调用需要 3 个 toolUseEvent 帧：
        1. 声明帧: {"name": "...", "toolUseId": "..."}
        2. 输入帧: {"name": "...", "toolUseId": "...", "input": "JSON string"}
        3. 停止帧: {"name": "...", "toolUseId": "...", "stop": true}

        Args:
            tool_uses: Kiro 格式的工具调用列表：
                [{"toolUseId": "tooluse_xxx", "name": "execute_bash", "input": {...}}]
            model_id: 返回给 Kiro 的 modelId
        """
        frames = b""
        
        for tool_use in tool_uses:
            name = tool_use["name"]
            tool_use_id = tool_use["toolUseId"]
            input_data = tool_use["input"]
            
            # 1. 声明帧
            frames += self.encoder.encode_tool_use_start(name, tool_use_id)
            
            # 2. 输入帧
            frames += self.encoder.encode_tool_use_input(name, tool_use_id, input_data)
            
            # 3. 停止帧
            frames += self.encoder.encode_tool_use_stop(name, tool_use_id)
        
        # 4. 收尾的 assistantResponseEvent（空内容）
        frames += self.encoder.encode_assistant_response("", model_id)
        
        # 5. contextUsageEvent
        frames += self.encoder.encode_context_usage(5.0)
        
        # 6. meteringEvent
        frames += self.encoder.encode_metering(0.01)
        
        return frames

    def adapt_intent_classification(self, openai_response: Dict[str, Any]) -> bytes:
        """适配 intent-classification 响应。

        intent-classification 的响应应该是 JSON 格式：
        {"chat": 0.0, "do": 1.0, "spec": 0.0}
        """
        content = self._extract_content(openai_response)

        if content:
            try:
                intent = json.loads(content)
                if all(k in intent for k in ("chat", "do", "spec")):
                    pass  # 有效的 intent 响应
                else:
                    content = '{"chat": 0.0, "do": 1.0, "spec": 0.0}'
            except json.JSONDecodeError:
                content = '{"chat": 0.0, "do": 1.0, "spec": 0.0}'
        else:
            content = '{"chat": 0.0, "do": 1.0, "spec": 0.0}'

        return self.encoder.build_full_response(content, "simple-task")

    def create_error_response(self, error_msg: str,
                              model_id: str = "deepseek-3.2") -> bytes:
        """创建错误响应的 EventStream 数据。"""
        content = f"I encountered an error: {error_msg}"
        return self.encoder.build_full_response(content, model_id)

    def build_http_response(self, eventstream_data: bytes) -> http.Response:
        """构造完整的 HTTP Response 对象。"""
        return http.Response.make(
            200,
            eventstream_data,
            {
                "Content-Type": "application/vnd.amazon.eventstream",
                "X-XSS-Protection": "1; mode=block",
                "Strict-Transport-Security": "max-age=47304000; includeSubDomains",
                "X-Frame-Options": "DENY",
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
                "x-amzn-kiro-conversation-id": "",
            }
        )

    def _extract_tool_calls(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从 OpenAI 响应中提取 tool_calls，转换为 Kiro toolUses 格式。

        OpenAI 格式:
            tool_calls: [{"id": "call_xxx", "type": "function",
                          "function": {"name": "...", "arguments": "{...}"}}]

        Kiro 格式:
            toolUses: [{"toolUseId": "tooluse_xxx", "name": "...", "input": {...}}]
        """
        choices = response.get("choices", [])
        if not choices:
            return []

        message = choices[0].get("message", {})
        tool_calls = message.get("tool_calls", [])
        if not tool_calls:
            return []

        kiro_tool_uses = []
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")
            if not name:
                continue

            # 解析 arguments JSON 字符串
            arguments_str = func.get("arguments", "{}")
            try:
                input_data = json.loads(arguments_str)
            except json.JSONDecodeError:
                input_data = {"raw": arguments_str}

            # 转换 tool_call id: "call_xxx..." → "tooluse_xxx..."
            raw_id = tc.get("id", "")
            tool_use_id = self._convert_tool_id(raw_id)

            kiro_tool_uses.append({
                "toolUseId": tool_use_id,
                "name": name,
                "input": input_data,
            })

        return kiro_tool_uses

    def _convert_tool_id(self, raw_id: str) -> str:
        """将 LLM 的 tool call id 转换为 Kiro 的 toolUseId 格式。

        规则：
        - 如果已经是 "tooluse_" 前缀，直接返回
        - 如果是 "call_" 前缀，替换为 "tooluse_"，保留更多字符避免冲突
        - 其他情况，加上 "tooluse_" 前缀和哈希后缀确保唯一性
        """
        if raw_id.startswith("tooluse_"):
            return raw_id
        if raw_id.startswith("call_"):
            # 去掉 __thought__xxx 后缀（LiteLLM 有时会附加）
            base_id = raw_id.split("__thought__")[0]
            # 取 call_ 后面的部分，使用更长的截取长度避免冲突
            # 使用前 32 个字符，这应该足够避免大多数冲突
            suffix = base_id[5:][:32]  # "call_" 后最多 32 字符
            return f"tooluse_{suffix}"
        # 其他格式，加上前缀和哈希后缀确保唯一性
        import hashlib
        # 使用 SHA-256 前 8 个字符作为哈希后缀
        hash_suffix = hashlib.sha256(raw_id.encode()).hexdigest()[:8]
        return f"tooluse_{raw_id[:24]}_{hash_suffix}"

    def _extract_content(self, response: Dict[str, Any]) -> Optional[str]:
        """从 OpenAI 响应中提取文本内容。

        注意：当 message.content 为 None（工具调用场景）时返回 None，
        而不是空字符串，以便调用方正确区分两种情况。
        """
        choices = response.get("choices", [])
        if choices:
            choice = choices[0]
            # 非流式响应
            message = choice.get("message", {})
            if message:
                content = message.get("content")
                # content 为 None 表示工具调用，不是空文本
                if content is not None:
                    return content
                # 如果有 tool_calls，返回 None 让调用方处理
                if message.get("tool_calls"):
                    return None
                # content=None 且无 tool_calls：异常情况，返回 None
                return None
            # 流式响应的最终结果
            delta = choice.get("delta", {})
            if delta:
                return delta.get("content", "")
            # text completion 格式
            if "text" in choice:
                return choice["text"]

        # 其他可能的格式
        if "content" in response:
            return response["content"]
        if "result" in response:
            return response["result"]
        if "text" in response:
            return response["text"]

        return None
