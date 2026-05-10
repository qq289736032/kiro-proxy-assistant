"""测试响应适配器。"""

import json
import pytest
from kiro_proxy.response_adapter import ResponseAdapter
from kiro_proxy.eventstream import EventStreamDecoder


class TestResponseAdapter:
    def setup_method(self):
        self.adapter = ResponseAdapter()
        self.decoder = EventStreamDecoder()

    def test_adapt_standard_openai_response(self):
        """测试标准 OpenAI 响应适配。"""
        openai_response = {
            "id": "chatcmpl-123",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hello! How can I help you?"
                    },
                    "finish_reason": "stop"
                }
            ],
            "model": "deepseek-chat",
            "usage": {"prompt_tokens": 10, "completion_tokens": 8}
        }

        data = self.adapter.adapt(openai_response, model_id="deepseek-3.2")
        messages = self.decoder.decode(data)

        assert len(messages) == 3
        assert messages[0].event_type == "assistantResponseEvent"
        payload = messages[0].payload_json
        assert payload["content"] == "Hello! How can I help you?"
        assert payload["modelId"] == "deepseek-3.2"

    def test_adapt_intent_classification_valid(self):
        """测试有效的 intent classification 响应。"""
        openai_response = {
            "choices": [
                {
                    "message": {
                        "content": '{"chat": 0.0, "do": 1.0, "spec": 0.0}'
                    }
                }
            ]
        }

        data = self.adapter.adapt_intent_classification(openai_response)
        messages = self.decoder.decode(data)

        assert len(messages) == 3
        payload = messages[0].payload_json
        assert payload["modelId"] == "simple-task"
        content = json.loads(payload["content"])
        assert content["do"] == 1.0

    def test_adapt_intent_classification_invalid(self):
        """测试无效的 intent classification 响应（应返回默认值）。"""
        openai_response = {
            "choices": [
                {
                    "message": {
                        "content": "I don't understand the question."
                    }
                }
            ]
        }

        data = self.adapter.adapt_intent_classification(openai_response)
        messages = self.decoder.decode(data)

        payload = messages[0].payload_json
        content = json.loads(payload["content"])
        # 应该返回默认的 do 模式
        assert content == {"chat": 0.0, "do": 1.0, "spec": 0.0}

    def test_create_error_response(self):
        """测试错误响应构造。"""
        data = self.adapter.create_error_response("Something went wrong")
        messages = self.decoder.decode(data)

        assert len(messages) == 3
        payload = messages[0].payload_json
        assert "error" in payload["content"].lower() or "Something went wrong" in payload["content"]

    def test_build_http_response(self):
        """测试 HTTP Response 构造。"""
        eventstream_data = self.adapter.adapt(
            {"choices": [{"message": {"content": "test"}}]},
            model_id="deepseek-3.2"
        )

        response = self.adapter.build_http_response(eventstream_data)
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "application/vnd.amazon.eventstream"

    def test_adapt_empty_response(self):
        """测试空响应处理。"""
        data = self.adapter.adapt({}, model_id="deepseek-3.2")
        messages = self.decoder.decode(data)

        # 应该返回错误消息而不是崩溃
        assert len(messages) == 3
        payload = messages[0].payload_json
        assert "error" in payload["content"].lower() or "Error" in payload["content"]

    def test_adapt_tool_calls_response(self):
        """测试 tool_calls 响应被正确转换为 toolUseEvent 帧序列。"""
        openai_response = {
            "choices": [{
                "finish_reason": "tool_calls",
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_abc123def456",
                        "type": "function",
                        "function": {
                            "name": "execute_bash",
                            "arguments": '{"command": "ls -la", "explanation": "列出文件"}'
                        }
                    }]
                }
            }]
        }

        data = self.adapter.adapt(openai_response, model_id="deepseek-3.2")
        messages = self.decoder.decode(data)

        # 现在应该是 6 个消息：assistantResponseEvent（含<｜DSML｜function_calls>标记） + 3个 toolUseEvent + assistantResponseEvent（空） + contextUsageEvent + meteringEvent
        assert len(messages) >= 6
        
        # 检查第一个消息应该是 assistantResponseEvent（含<｜DSML｜function_calls>标记）
        assert messages[0].event_type == "assistantResponseEvent"
        payload0 = messages[0].payload_json
        assert "<｜DSML｜function_calls" in payload0["content"]
        assert payload0["modelId"] == "deepseek-3.2"
        
        # 检查第二个消息应该是 toolUseEvent（声明帧）
        assert messages[1].event_type == "toolUseEvent"
        payload1 = messages[1].payload_json
        assert payload1["name"] == "execute_bash"
        assert payload1["toolUseId"].startswith("tooluse_")
        
        # 检查第三个消息应该是 toolUseEvent（输入帧）
        assert messages[2].event_type == "toolUseEvent"
        payload2 = messages[2].payload_json
        assert payload2["name"] == "execute_bash"
        assert "input" in payload2
        
        # 检查第四个消息应该是 toolUseEvent（停止帧）
        assert messages[3].event_type == "toolUseEvent"
        payload3 = messages[3].payload_json
        assert payload3["name"] == "execute_bash"
        assert payload3.get("stop") == True
        
        # 检查收尾的 assistantResponseEvent（空内容）
        assistant_event_found = False
        for msg in messages:
            if msg.event_type == "assistantResponseEvent" and msg.payload_json["content"] == "":
                assistant_event_found = True
                payload = msg.payload_json
                assert payload["content"] == ""
                assert payload["modelId"] == "deepseek-3.2"
                break
        assert assistant_event_found

    def test_adapt_tool_calls_multiple(self):
        """测试多个 tool_calls 的处理。"""
        openai_response = {
            "choices": [{
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_111",
                            "type": "function",
                            "function": {"name": "list_directory", "arguments": '{"path": "."}'}
                        },
                        {
                            "id": "call_222",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": '{"path": "README.md"}'}
                        }
                    ]
                }
            }]
        }

        data = self.adapter.adapt(openai_response, model_id="deepseek-3.2")
        messages = self.decoder.decode(data)
        
        # 2个工具 * 3帧每个 = 6个 toolUseEvent
        tool_use_events = [msg for msg in messages if msg.event_type == "toolUseEvent"]
        assert len(tool_use_events) == 6  # 2个工具 * 3帧
        
        # 检查第一个工具的声明帧
        assert tool_use_events[0].payload_json["name"] == "list_directory"
        # 检查第二个工具的声明帧
        assert tool_use_events[3].payload_json["name"] == "read_file"

    def test_adapt_tool_id_conversion(self):
        """测试 tool call id 转换规则。"""
        openai_response = {
            "choices": [{
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call_abc123__thought__XXXYYY",
                        "type": "function",
                        "function": {"name": "execute_bash", "arguments": '{"command": "echo hi"}'}
                    }]
                }
            }]
        }

        data = self.adapter.adapt(openai_response, model_id="deepseek-3.2")
        messages = self.decoder.decode(data)
        
        # 找到第一个 toolUseEvent
        tool_use_events = [msg for msg in messages if msg.event_type == "toolUseEvent"]
        assert len(tool_use_events) >= 1
        
        tool_use_id = tool_use_events[0].payload_json["toolUseId"]
        # __thought__ 后缀应被去掉
        assert "__thought__" not in tool_use_id
        assert tool_use_id.startswith("tooluse_")

    def test_extract_content_none_for_tool_calls(self):
        """测试 message.content=None 时 _extract_content 返回 None。"""
        response = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{"id": "call_1", "function": {"name": "test", "arguments": "{}"}}]
                }
            }]
        }
        result = self.adapter._extract_content(response)
        assert result is None

    def test_extract_content_empty_string(self):
        """测试 message.content="" 时 _extract_content 返回空字符串（非 None）。"""
        response = {
            "choices": [{
                "message": {"content": ""}
            }]
        }
        result = self.adapter._extract_content(response)
        assert result == ""
