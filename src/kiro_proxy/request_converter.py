"""请求转换器：conversationState → OpenAI Chat Completion 格式。

将 Kiro 的 AWS CodeWhisperer conversationState 请求格式
转换为 OpenAI 兼容的 Chat Completion 请求格式。
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional
from mitmproxy import http

logger = logging.getLogger(__name__)


class RequestConverter:
    """将 Kiro conversationState 请求转换为 OpenAI 格式。"""

    def __init__(self, default_model: str = "deepseek-chat"):
        self.default_model = default_model

    def convert(self, request: http.Request) -> Optional[Dict[str, Any]]:
        """转换 Kiro 请求为 OpenAI Chat Completion 格式。

        Returns:
            转换后的 OpenAI 格式请求字典，转换失败返回 None。
        """
        try:
            body = json.loads(request.content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Failed to parse request body: {e}")
            return None

        conversation_state = body.get("conversationState")
        if not conversation_state:
            logger.warning("No conversationState found in request body")
            return None

        # 提取 agent mode
        agent_mode = request.headers.get("x-amzn-kiro-agent-mode", "vibe")

        # 提取消息历史
        messages = self._extract_messages(conversation_state)

        # 构造 OpenAI 请求
        openai_request = {
            "model": self.default_model,
            "messages": messages,
            "stream": False,  # Phase 1: 非流式（Phase 2 将改为 True）
        }

        # 提取 modelId 用于路由参考
        current_msg = conversation_state.get("currentMessage", {})
        user_input = current_msg.get("userInputMessage", {})
        model_id = user_input.get("modelId", "")

        # 提取工具定义（仅 vibe 模式传递工具）
        if agent_mode != "intent-classification":
            tools_raw = user_input.get("userInputMessageContext", {}).get("tools", [])
            if tools_raw:
                openai_tools = self.convert_tools(tools_raw)
                if openai_tools:
                    openai_request["tools"] = openai_tools

        # 附加元数据（供 model_router 使用）
        openai_request["_meta"] = {
            "agent_mode": agent_mode,
            "kiro_model_id": model_id,
            "conversation_id": conversation_state.get("conversationId", ""),
            "agent_continuation_id": conversation_state.get("agentContinuationId", ""),
        }

        return openai_request

    def _extract_messages(self, conversation_state: Dict) -> List[Dict[str, Any]]:
        """从 conversationState 提取并转换消息历史为 OpenAI messages 格式。

        支持工具调用历史：
        - assistantResponseMessage.toolUses → assistant message with tool_calls
        - userInputMessage.toolResults → tool role messages
        """
        messages = []

        # 1. 处理 history
        history = conversation_state.get("history", [])
        for entry in history:
            if "userInputMessage" in entry:
                user_msg = entry["userInputMessage"]
                content = user_msg.get("content", "")

                # 跳过 intent classifier system prompt
                if self._is_intent_classifier_prompt(content):
                    continue

                # 检查是否有 toolResults（工具执行结果）
                tool_results = user_msg.get("userInputMessageContext", {}).get("toolResults", [])
                if tool_results:
                    # 每个 toolResult 转换为一条 tool role 消息
                    for tr in tool_results:
                        tool_use_id = tr.get("toolUseId", "")
                        # 将 tooluse_xxx 转换为 call_xxx 以匹配 OpenAI 格式
                        call_id = self._tooluse_id_to_call_id(tool_use_id)
                        content_list = tr.get("content", [])
                        tool_content = content_list[0].get("text", "") if content_list else ""
                        messages.append({
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": tool_content,
                        })
                elif content:
                    messages.append({
                        "role": "user",
                        "content": self._clean_content(content)
                    })

            elif "assistantResponseMessage" in entry:
                assistant_msg = entry["assistantResponseMessage"]
                content = assistant_msg.get("content", "")
                tool_uses = assistant_msg.get("toolUses", [])

                # 跳过占位回复
                if content.strip() == "I will follow these instructions" and not tool_uses:
                    continue

                msg: Dict[str, Any] = {"role": "assistant", "content": content or ""}

                # 如果有工具调用，转换为 OpenAI tool_calls 格式
                if tool_uses:
                    openai_tool_calls = []
                    for tu in tool_uses:
                        tool_use_id = tu.get("toolUseId", "")
                        call_id = self._tooluse_id_to_call_id(tool_use_id)
                        name = tu.get("name", "")
                        input_data = tu.get("input", {})
                        openai_tool_calls.append({
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(input_data, ensure_ascii=False),
                            }
                        })
                    msg["tool_calls"] = openai_tool_calls

                messages.append(msg)

        # 2. 处理 currentMessage
        current_msg = conversation_state.get("currentMessage", {})
        user_input = current_msg.get("userInputMessage", {})
        if user_input:
            content = user_input.get("content", "")
            # 检查 currentMessage 中是否有 toolResults
            tool_results = user_input.get("userInputMessageContext", {}).get("toolResults", [])
            if tool_results:
                for tr in tool_results:
                    tool_use_id = tr.get("toolUseId", "")
                    call_id = self._tooluse_id_to_call_id(tool_use_id)
                    content_list = tr.get("content", [])
                    tool_content = content_list[0].get("text", "") if content_list else ""
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": tool_content,
                    })
            elif content:
                messages.append({
                    "role": "user",
                    "content": self._clean_content(content)
                })

        # 确保至少有一条消息
        if not messages:
            messages = [{"role": "user", "content": ""}]

        return messages

    def _tooluse_id_to_call_id(self, tool_use_id: str) -> str:
        """将 Kiro 的 toolUseId 转换为 OpenAI 的 tool_call_id。

        规则：
        - "tooluse_xxx" → "call_xxx"
        - 其他格式直接返回（保持兼容）
        """
        if tool_use_id.startswith("tooluse_"):
            return "call_" + tool_use_id[8:]
        return tool_use_id

    def _is_intent_classifier_prompt(self, content: str) -> bool:
        """检测是否是 intent classifier 的 system prompt。"""
        indicators = [
            "You are an intent classifier",
            "classify the user's intent",
            "Do mode",
            "Spec mode",
        ]
        return any(indicator in content for indicator in indicators)

    def _clean_content(self, content: str) -> str:
        """清理消息内容，移除或保留 EnvironmentContext。

        策略：保留 EnvironmentContext（大多数模型能理解 XML 标签），
        但移除多余的重复 EnvironmentContext 块。
        """
        # 如果有多个 EnvironmentContext 块，只保留最后一个
        blocks = re.findall(
            r'<EnvironmentContext>.*?</EnvironmentContext>',
            content,
            re.DOTALL
        )

        if len(blocks) > 1:
            # 移除前面的重复块，只保留最后一个
            for block in blocks[:-1]:
                content = content.replace(block, "", 1)

        # 清理多余的空行
        content = re.sub(r'\n{3,}', '\n\n', content)

        return content.strip()

    def convert_tools(self, tools: List[Dict]) -> List[Dict[str, Any]]:
        """将 Kiro toolSpecification 列表转换为 OpenAI tools 格式。

        Kiro 格式:
          [{"toolSpecification": {"name": "...", "description": "...", "inputSchema": {"json": {...}}}}]

        OpenAI 格式:
          [{"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}]
        """
        openai_tools = []
        for tool in tools:
            spec = tool.get("toolSpecification", {})
            name = spec.get("name", "")
            description = spec.get("description", "")
            # inputSchema.json 就是 JSON Schema，直接作为 parameters
            parameters = spec.get("inputSchema", {}).get("json", {
                "type": "object",
                "properties": {},
            })

            if not name:
                continue

            openai_tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                }
            })

        return openai_tools

    def get_agent_mode(self, request: http.Request) -> str:
        """获取请求的 agent mode。"""
        return request.headers.get("x-amzn-kiro-agent-mode", "vibe")

    def is_intent_classification(self, request: http.Request) -> bool:
        """判断是否是 intent-classification 请求。"""
        return self.get_agent_mode(request) == "intent-classification"
