"""测试请求转换器。"""

import json
import pytest
from unittest.mock import MagicMock
from kiro_proxy.request_converter import RequestConverter


def _make_request(body: dict, headers: dict = None) -> MagicMock:
    """构造模拟的 mitmproxy Request。"""
    request = MagicMock()
    request.content = json.dumps(body).encode("utf-8")
    request.headers = headers or {"x-amzn-kiro-agent-mode": "vibe"}
    return request


class TestRequestConverter:
    def setup_method(self):
        self.converter = RequestConverter()

    def test_basic_conversation(self):
        """测试基本对话转换。"""
        body = {
            "conversationState": {
                "conversationId": "test-123",
                "agentContinuationId": "cont-456",
                "agentTaskType": "vibe",
                "chatTriggerType": "MANUAL",
                "currentMessage": {
                    "userInputMessage": {
                        "content": "你好",
                        "modelId": "deepseek-3.2",
                        "origin": "AI_EDITOR",
                        "userInputMessageContext": {}
                    }
                },
                "history": []
            },
            "profileArn": "arn:aws:codewhisperer:us-east-1:123:profile/ABC"
        }

        result = self.converter.convert(_make_request(body))
        assert result is not None
        assert result["messages"] == [{"role": "user", "content": "你好"}]
        assert result["model"] == "deepseek-chat"

    def test_with_history(self):
        """测试带历史记录的转换。"""
        body = {
            "conversationState": {
                "conversationId": "test-123",
                "currentMessage": {
                    "userInputMessage": {
                        "content": "继续",
                        "modelId": "deepseek-3.2",
                        "origin": "AI_EDITOR"
                    }
                },
                "history": [
                    {"userInputMessage": {"content": "第一条消息", "modelId": "deepseek-3.2", "origin": "AI_EDITOR"}},
                    {"assistantResponseMessage": {"content": "第一条回复", "toolUses": []}},
                ]
            }
        }

        result = self.converter.convert(_make_request(body))
        assert result is not None
        assert len(result["messages"]) == 3
        assert result["messages"][0] == {"role": "user", "content": "第一条消息"}
        assert result["messages"][1] == {"role": "assistant", "content": "第一条回复"}
        assert result["messages"][2] == {"role": "user", "content": "继续"}

    def test_skips_intent_classifier_prompt(self):
        """测试跳过 intent classifier system prompt。"""
        body = {
            "conversationState": {
                "currentMessage": {
                    "userInputMessage": {
                        "content": "你是什么模型",
                        "modelId": "simple-task",
                        "origin": "AI_EDITOR"
                    }
                },
                "history": [
                    {"userInputMessage": {
                        "content": "You are an intent classifier for a language model...",
                        "modelId": "simple-task",
                        "origin": "AI_EDITOR"
                    }},
                    {"assistantResponseMessage": {
                        "content": "I will follow these instructions",
                        "toolUses": []
                    }},
                ]
            }
        }

        result = self.converter.convert(_make_request(body))
        assert result is not None
        # 应该只有 currentMessage，history 中的 classifier prompt 和占位回复被跳过
        assert len(result["messages"]) == 1
        assert result["messages"][0]["content"] == "你是什么模型"

    def test_environment_context_dedup(self):
        """测试 EnvironmentContext 去重。"""
        content = (
            "消息1\n\n<EnvironmentContext>\nfirst\n</EnvironmentContext>\n"
            "消息2\n\n<EnvironmentContext>\nsecond\n</EnvironmentContext>"
        )
        body = {
            "conversationState": {
                "currentMessage": {
                    "userInputMessage": {
                        "content": content,
                        "modelId": "deepseek-3.2",
                        "origin": "AI_EDITOR"
                    }
                },
                "history": []
            }
        }

        result = self.converter.convert(_make_request(body))
        # 应该只保留最后一个 EnvironmentContext
        msg_content = result["messages"][0]["content"]
        assert msg_content.count("<EnvironmentContext>") == 1
        assert "second" in msg_content

    def test_no_conversation_state(self):
        """测试缺少 conversationState 的情况。"""
        body = {"something": "else"}
        result = self.converter.convert(_make_request(body))
        assert result is None

    def test_meta_extraction(self):
        """测试元数据提取。"""
        body = {
            "conversationState": {
                "conversationId": "conv-123",
                "agentContinuationId": "cont-456",
                "currentMessage": {
                    "userInputMessage": {
                        "content": "test",
                        "modelId": "deepseek-3.2",
                        "origin": "AI_EDITOR"
                    }
                },
                "history": []
            }
        }

        headers = {"x-amzn-kiro-agent-mode": "vibe"}
        result = self.converter.convert(_make_request(body, headers))
        assert result["_meta"]["agent_mode"] == "vibe"
        assert result["_meta"]["kiro_model_id"] == "deepseek-3.2"
        assert result["_meta"]["conversation_id"] == "conv-123"

    def test_convert_tools(self):
        """测试工具定义格式转换（toolSpecification → OpenAI tools）。"""
        kiro_tools = [
            {
                "toolSpecification": {
                    "name": "execute_bash",
                    "description": "Execute a bash command.",
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", "description": "The command"},
                                "cwd": {"type": "string", "description": "Working directory"},
                            },
                            "required": ["command"],
                        }
                    }
                }
            },
            {
                "toolSpecification": {
                    "name": "list_directory",
                    "description": "List directory contents.",
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                            },
                        }
                    }
                }
            }
        ]

        result = self.converter.convert_tools(kiro_tools)
        assert len(result) == 2

        # 第一个工具
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "execute_bash"
        assert result[0]["function"]["description"] == "Execute a bash command."
        assert result[0]["function"]["parameters"]["type"] == "object"
        assert "command" in result[0]["function"]["parameters"]["properties"]

        # 第二个工具
        assert result[1]["function"]["name"] == "list_directory"

    def test_convert_tools_empty(self):
        """测试空工具列表。"""
        result = self.converter.convert_tools([])
        assert result == []

    def test_convert_tools_missing_name(self):
        """测试缺少 name 的工具被跳过。"""
        kiro_tools = [
            {"toolSpecification": {"description": "no name", "inputSchema": {"json": {}}}},
            {"toolSpecification": {"name": "valid_tool", "description": "ok", "inputSchema": {"json": {}}}},
        ]
        result = self.converter.convert_tools(kiro_tools)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "valid_tool"

    def test_tools_included_in_vibe_mode(self):
        """测试 vibe 模式下工具定义被包含在请求中。"""
        body = {
            "conversationState": {
                "currentMessage": {
                    "userInputMessage": {
                        "content": "list files",
                        "modelId": "deepseek-3.2",
                        "origin": "AI_EDITOR",
                        "userInputMessageContext": {
                            "tools": [
                                {
                                    "toolSpecification": {
                                        "name": "list_directory",
                                        "description": "List files",
                                        "inputSchema": {"json": {"type": "object", "properties": {"path": {"type": "string"}}}}
                                    }
                                }
                            ]
                        }
                    }
                },
                "history": []
            }
        }
        headers = {"x-amzn-kiro-agent-mode": "vibe"}
        result = self.converter.convert(_make_request(body, headers))
        assert "tools" in result
        assert len(result["tools"]) == 1
        assert result["tools"][0]["function"]["name"] == "list_directory"

    def test_tools_excluded_in_intent_classification(self):
        """测试 intent-classification 模式下工具定义不被包含。"""
        body = {
            "conversationState": {
                "currentMessage": {
                    "userInputMessage": {
                        "content": "hello",
                        "modelId": "simple-task",
                        "origin": "AI_EDITOR",
                        "userInputMessageContext": {
                            "tools": [
                                {"toolSpecification": {"name": "some_tool", "description": "x", "inputSchema": {"json": {}}}}
                            ]
                        }
                    }
                },
                "history": []
            }
        }
        headers = {"x-amzn-kiro-agent-mode": "intent-classification"}
        result = self.converter.convert(_make_request(body, headers))
        assert "tools" not in result

    def test_history_with_tool_uses(self):
        """测试历史消息中的 toolUses 被转换为 OpenAI tool_calls。"""
        body = {
            "conversationState": {
                "currentMessage": {
                    "userInputMessage": {
                        "content": "继续",
                        "modelId": "deepseek-3.2",
                        "origin": "AI_EDITOR"
                    }
                },
                "history": [
                    {"userInputMessage": {"content": "列出文件", "modelId": "deepseek-3.2", "origin": "AI_EDITOR"}},
                    {"assistantResponseMessage": {
                        "content": "",
                        "toolUses": [{
                            "toolUseId": "tooluse_abc123",
                            "name": "list_directory",
                            "input": {"path": "."}
                        }]
                    }},
                ]
            }
        }
        result = self.converter.convert(_make_request(body))
        assert result is not None
        messages = result["messages"]
        # 找到 assistant 消息
        assistant_msgs = [m for m in messages if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        assert "tool_calls" in assistant_msgs[0]
        tc = assistant_msgs[0]["tool_calls"][0]
        assert tc["function"]["name"] == "list_directory"
        assert tc["id"] == "call_abc123"  # tooluse_abc123 → call_abc123

    def test_history_with_tool_results(self):
        """测试历史消息中的 toolResults 被转换为 OpenAI tool role 消息。"""
        body = {
            "conversationState": {
                "currentMessage": {
                    "userInputMessage": {
                        "content": "分析结果",
                        "modelId": "deepseek-3.2",
                        "origin": "AI_EDITOR",
                        "userInputMessageContext": {
                            "toolResults": [{
                                "toolUseId": "tooluse_xyz789",
                                "content": [{"text": "file1.py\nfile2.py"}],
                                "status": "success"
                            }]
                        }
                    }
                },
                "history": []
            }
        }
        result = self.converter.convert(_make_request(body))
        assert result is not None
        messages = result["messages"]
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "call_xyz789"
        assert "file1.py" in tool_msgs[0]["content"]

    def test_full_tool_call_roundtrip(self):
        """测试完整的多轮工具调用历史转换。

        流程: user → assistant(tool_calls) → tool(result) → user
        """
        body = {
            "conversationState": {
                "currentMessage": {
                    "userInputMessage": {
                        "content": "好的，继续",
                        "modelId": "deepseek-3.2",
                        "origin": "AI_EDITOR"
                    }
                },
                "history": [
                    # 第一轮：用户请求
                    {"userInputMessage": {"content": "列出文件", "modelId": "deepseek-3.2", "origin": "AI_EDITOR"}},
                    # 第二轮：AI 调用工具
                    {"assistantResponseMessage": {
                        "content": "",
                        "toolUses": [{"toolUseId": "tooluse_111", "name": "list_directory", "input": {"path": "."}}]
                    }},
                    # 第三轮：工具结果发回
                    {"userInputMessage": {
                        "content": "",
                        "modelId": "deepseek-3.2",
                        "origin": "AI_EDITOR",
                        "userInputMessageContext": {
                            "toolResults": [{
                                "toolUseId": "tooluse_111",
                                "content": [{"text": "src/\ntests/\nREADME.md"}],
                                "status": "success"
                            }]
                        }
                    }},
                    # 第四轮：AI 基于结果回复
                    {"assistantResponseMessage": {"content": "项目包含 src、tests 目录", "toolUses": []}},
                ]
            }
        }
        result = self.converter.convert(_make_request(body))
        messages = result["messages"]

        roles = [m["role"] for m in messages]
        # 期望顺序: user, assistant(tool_calls), tool, assistant, user
        assert "user" in roles
        assert "tool" in roles
        assert roles.count("assistant") == 2

        # 验证 tool_call_id 一致性
        assistant_with_tools = next(m for m in messages if m["role"] == "assistant" and "tool_calls" in m)
        tool_msg = next(m for m in messages if m["role"] == "tool")
        assert assistant_with_tools["tool_calls"][0]["id"] == tool_msg["tool_call_id"]
