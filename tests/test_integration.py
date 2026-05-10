"""集成测试：完整的拦截-转换-返回流程。

测试 Kiro 请求 → 代理转换 → LiteLLM 模拟 → 代理适配 → Kiro 响应的完整流程。
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
import httpx
from mitmproxy import http

from kiro_proxy.kiro_mitmproxy import KiroProxyAddon, KIRO_BACKEND, INTERCEPT_PATH
from kiro_proxy.request_converter import RequestConverter
from kiro_proxy.response_adapter import ResponseAdapter
from kiro_proxy.model_router import ModelRouter


class TestIntegration:
    """集成测试类。"""
    
    def setup_method(self):
        """测试前准备。"""
        # 创建模拟配置
        self.mock_config = {
            "litellm": {
                "base_url": "https://test-ai.igovee.com",
                "api_key": "test-key",
                "timeout": 60
            },
            "model_routing": {
                "intent_classification": "gemini-3.1-flash-lite",
                "vibe_default": "deepseek-v3",
                "task_models": {
                    "code": "deepseek-v3",
                    "analysis": "gemini-3-flash",
                    "creative": "claude-sonnet-4.5",
                    "simple": "gemini-3.1-flash-lite"
                }
            },
            "logging": {
                "level": "INFO",
                "detail_level": 1
            }
        }
    
    def create_mock_flow(self, request_body, agent_mode="vibe"):
        """创建模拟的 mitmproxy flow。"""
        # 创建模拟的 mitmproxy flow
        mock_flow = Mock(spec=http.HTTPFlow)
        mock_flow.request = Mock(spec=http.Request)
        mock_flow.client_conn = Mock()
        mock_flow.client_conn.peername = ("127.0.0.1", 54321)
        
        # 设置请求属性
        mock_flow.request.method = "POST"
        mock_flow.request.path = INTERCEPT_PATH
        mock_flow.request.pretty_host = KIRO_BACKEND
        mock_flow.request.text = json.dumps(request_body)
        mock_flow.request.content = json.dumps(request_body).encode('utf-8')
        mock_flow.request.headers = {
            "x-amzn-kiro-agent-mode": agent_mode,
            "content-type": "application/json"
        }
        
        # 创建模拟的 HTTP 响应
        mock_flow.response = Mock(spec=http.Response)
        
        return mock_flow
    
    def test_kiro_request_to_openai_conversion(self):
        """测试 Kiro 请求到 OpenAI 格式的转换。"""
        # 模拟 Kiro 请求
        kiro_request_body = {
            "conversationState": {
                "currentMessage": {
                    "userInputMessage": {
                        "content": "Hello, how are you?",
                        "modelId": "deepseek-3.2",
                        "origin": "AI_EDITOR",
                        "userInputMessageContext": {
                            "tools": [
                                {
                                    "toolSpecification": {
                                        "description": "Execute bash command",
                                        "inputSchema": {
                                            "json": {
                                                "type": "object",
                                                "properties": {
                                                    "command": {"type": "string"}
                                                },
                                                "required": ["command"]
                                            }
                                        },
                                        "name": "execute_bash"
                                    }
                                }
                            ]
                        }
                    }
                },
                "history": [
                    {
                        "userInputMessage": {
                            "content": "Previous message",
                            "modelId": "deepseek-3.2"
                        }
                    },
                    {
                        "assistantResponseMessage": {
                            "content": "Previous response",
                            "modelId": "deepseek-3.2"
                        }
                    }
                ]
            },
            "profileArn": "arn:aws:codewhisperer:test"
        }
        
        mock_flow = self.create_mock_flow(kiro_request_body, agent_mode="vibe")
        
        # 创建转换器
        converter = RequestConverter()
        
        # 转换请求
        openai_request = converter.convert(mock_flow.request)
        
        # 验证转换结果
        assert openai_request is not None
        assert "messages" in openai_request
        assert len(openai_request["messages"]) == 3  # 历史 + 当前消息
        
        # 验证消息格式
        messages = openai_request["messages"]
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Previous message"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Previous response"
        assert messages[2]["role"] == "user"
        assert "Hello, how are you?" in messages[2]["content"]
        
        # 验证工具定义
        assert "tools" in openai_request
        assert len(openai_request["tools"]) == 1
        assert openai_request["tools"][0]["function"]["name"] == "execute_bash"
    
    def test_openai_response_to_eventstream_conversion(self):
        """测试 OpenAI 响应到 EventStream 格式的转换。"""
        # 模拟 OpenAI 响应
        openai_response = {
            "id": "chatcmpl-123",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "I'm doing well, thank you for asking!"
                    },
                    "finish_reason": "stop"
                }
            ],
            "model": "deepseek-chat",
            "usage": {"prompt_tokens": 10, "completion_tokens": 8}
        }
        
        # 创建适配器
        adapter = ResponseAdapter()
        
        # 转换响应
        eventstream_data = adapter.adapt(openai_response, model_id="deepseek-3.2")
        
        # 验证 EventStream 数据
        assert eventstream_data is not None
        assert len(eventstream_data) > 0
        
        # 解码验证
        from kiro_proxy.eventstream import EventStreamDecoder
        decoder = EventStreamDecoder()
        messages = decoder.decode(eventstream_data)
        
        # 应该包含 3 个事件
        assert len(messages) == 3
        assert messages[0].event_type == "assistantResponseEvent"
        assert messages[1].event_type == "contextUsageEvent"
        assert messages[2].event_type == "meteringEvent"
        
        # 验证内容
        payload = messages[0].payload_json
        assert payload["content"] == "I'm doing well, thank you for asking!"
        assert payload["modelId"] == "deepseek-3.2"
    
    def test_tool_calls_integration(self):
        """测试工具调用的集成流程。"""
        # 模拟包含工具调用的 OpenAI 响应
        openai_response = {
            "id": "chatcmpl-456",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_abc123",
                                "type": "function",
                                "function": {
                                    "name": "execute_bash",
                                    "arguments": '{"command": "ls -la", "explanation": "List files"}'
                                }
                            }
                        ]
                    },
                    "finish_reason": "tool_calls"
                }
            ],
            "model": "deepseek-chat"
        }
        
        # 创建适配器
        adapter = ResponseAdapter()
        
        # 转换响应
        eventstream_data = adapter.adapt(openai_response, model_id="deepseek-3.2")
        
        # 验证 EventStream 数据
        assert eventstream_data is not None
        
        # 解码验证
        from kiro_proxy.eventstream import EventStreamDecoder
        decoder = EventStreamDecoder()
        messages = decoder.decode(eventstream_data)
        
        # 应该包含多个事件：assistantResponseEvent（含<｜DSML｜function_calls>标记） + 3个 toolUseEvent + 收尾事件
        assert len(messages) >= 6
        
        # 检查第一个消息应该是 assistantResponseEvent（含<｜DSML｜function_calls>标记）
        assert messages[0].event_type == "assistantResponseEvent"
        payload0 = messages[0].payload_json
        assert "<｜DSML｜function_calls" in payload0["content"]
        
        # 检查 toolUseEvent 帧
        tool_use_events = [msg for msg in messages if msg.event_type == "toolUseEvent"]
        assert len(tool_use_events) >= 3  # 至少 3 帧（声明、输入、停止）
    
    def test_full_proxy_flow_with_mock_litellm(self):
        """测试完整的代理流程（使用模拟的 LiteLLM Provider）。"""
        # 模拟 Kiro 请求
        kiro_request_body = {
            "conversationState": {
                "currentMessage": {
                    "userInputMessage": {
                        "content": "Test message",
                        "modelId": "deepseek-3.2",
                        "origin": "AI_EDITOR"
                    }
                },
                "history": []
            }
        }

        mock_flow = self.create_mock_flow(kiro_request_body, agent_mode="vibe")

        # 模拟 Provider 响应
        mock_provider_response = {
            "id": "chatcmpl-test",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Test response from LiteLLM"
                    },
                    "finish_reason": "stop"
                }
            ],
            "model": "deepseek-chat"
        }

        # 模拟 Provider 和 Router
        mock_provider = Mock()
        mock_provider.complete.return_value = mock_provider_response
        mock_provider.config = Mock()
        mock_provider.config.name = "litellm"

        mock_router = Mock()
        mock_router.route.return_value = mock_provider

        # 创建代理 addon（使用模拟配置 + 模拟路由）
        with patch('kiro_proxy.kiro_mitmproxy._load_config', return_value=self.mock_config):
            with patch('kiro_proxy.kiro_mitmproxy._setup_logging'):
                with patch('kiro_proxy.kiro_mitmproxy.build_router', return_value=mock_router):
                    addon = KiroProxyAddon()

        # 执行请求处理
        addon.request(mock_flow)

        # 验证 Provider 被调用
        assert mock_provider.complete.called
        call_args = mock_provider.complete.call_args
        request_body = call_args[0][0]
        assert "messages" in request_body
        assert len(request_body["messages"]) == 1
        assert request_body["messages"][0]["role"] == "user"
        assert "Test message" in request_body["messages"][0]["content"]

        # 验证响应被注入
        assert mock_flow.response is not None
    
    def test_intent_classification_flow(self):
        """测试 intent-classification 流程。"""
        # 模拟 intent-classification 请求
        kiro_request_body = {
            "conversationState": {
                "currentMessage": {
                    "userInputMessage": {
                        "content": "Test intent classification",
                        "modelId": "simple-task",
                        "origin": "AI_EDITOR"
                    }
                },
                "history": []
            }
        }
        
        mock_flow = self.create_mock_flow(kiro_request_body, agent_mode="intent-classification")
        
        # 创建转换器
        converter = RequestConverter()
        
        # 转换请求
        openai_request = converter.convert(mock_flow.request)
        
        # 验证 intent-classification 的特殊处理
        assert openai_request is not None
        assert "_meta" in openai_request
        assert openai_request["_meta"]["agent_mode"] == "intent-classification"
        assert openai_request["_meta"]["kiro_model_id"] == "simple-task"
        
        # 验证消息内容
        messages = openai_request["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "Test intent classification" in messages[0]["content"]
    
    def test_error_handling_integration(self):
        """测试错误处理集成。"""
        # 模拟无效的 Kiro 请求（缺少必要字段）
        kiro_request_body = {
            "invalid": "request"
        }
        
        mock_flow = self.create_mock_flow(kiro_request_body, agent_mode="vibe")
        
        # 创建转换器
        converter = RequestConverter()
        
        # 转换请求（应该返回 None）
        openai_request = converter.convert(mock_flow.request)
        
        # 验证转换失败
        assert openai_request is None
    
    def test_model_routing_integration(self):
        """测试模型路由集成。"""
        # 创建模型路由器
        router_config = {
            "intent_classification": "gemini-3.1-flash-lite",
            "vibe_default": "deepseek-v3",
            "task_models": {
                "code": "deepseek-v3",
                "analysis": "gemini-3-flash",
                "creative": "claude-sonnet-4.5",
                "simple": "gemini-3.1-flash-lite"
            }
        }
        
        router = ModelRouter(router_config)
        
        # 测试代码任务
        code_request = {
            "messages": [{"role": "user", "content": "Write a Python function to sort a list"}],
            "_meta": {"agent_mode": "vibe", "kiro_model_id": "deepseek-3.2"}
        }
        
        code_model = router.select_model(code_request, agent_mode="vibe", kiro_model_id="deepseek-3.2")
        assert code_model == "deepseek-v3"
        
        # 测试分析任务
        analysis_request = {
            "messages": [{"role": "user", "content": "Analyze this data and provide insights"}],
            "_meta": {"agent_mode": "vibe", "kiro_model_id": "deepseek-3.2"}
        }
        
        analysis_model = router.select_model(analysis_request, agent_mode="vibe", kiro_model_id="deepseek-3.2")
        assert analysis_model == "gemini-3-flash"
        
        # 测试 intent-classification
        intent_request = {
            "messages": [{"role": "user", "content": "Test intent"}],
            "_meta": {"agent_mode": "intent-classification", "kiro_model_id": "simple-task"}
        }
        
        intent_model = router.select_model(intent_request, agent_mode="intent-classification", kiro_model_id="simple-task")
        assert intent_model == "gemini-3.1-flash-lite"