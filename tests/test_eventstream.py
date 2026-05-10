"""测试 AWS EventStream 编解码器。"""

import json
import struct
import binascii
import pytest
from kiro_proxy.eventstream import EventStreamEncoder, EventStreamDecoder, EventStreamMessage, _crc32


class TestEventStreamEncoder:
    def setup_method(self):
        self.encoder = EventStreamEncoder()

    def test_encode_assistant_response(self):
        """测试编码 assistantResponseEvent。"""
        data = self.encoder.encode_assistant_response("Hello", "deepseek-3.2")
        assert len(data) > 0
        decoder = EventStreamDecoder()
        messages = decoder.decode(data)
        assert len(messages) == 1
        assert messages[0].event_type == "assistantResponseEvent"
        payload = messages[0].payload_json
        assert payload["content"] == "Hello"
        assert payload["modelId"] == "deepseek-3.2"

    def test_encode_context_usage(self):
        """测试编码 contextUsageEvent。"""
        data = self.encoder.encode_context_usage(5.0)
        decoder = EventStreamDecoder()
        messages = decoder.decode(data)
        assert len(messages) == 1
        assert messages[0].event_type == "contextUsageEvent"
        assert messages[0].payload_json["contextUsagePercentage"] == 5.0

    def test_encode_metering(self):
        """测试编码 meteringEvent。"""
        data = self.encoder.encode_metering(0.01)
        decoder = EventStreamDecoder()
        messages = decoder.decode(data)
        assert len(messages) == 1
        assert messages[0].event_type == "meteringEvent"
        payload = messages[0].payload_json
        assert payload["unit"] == "credit"
        assert payload["usage"] == 0.01

    def test_build_full_response(self):
        """测试构造完整响应包含 3 个事件。"""
        data = self.encoder.build_full_response("Test response", "deepseek-3.2")
        decoder = EventStreamDecoder()
        messages = decoder.decode(data)
        assert len(messages) == 3
        assert messages[0].event_type == "assistantResponseEvent"
        assert messages[1].event_type == "contextUsageEvent"
        assert messages[2].event_type == "meteringEvent"

    def test_encode_chinese_content(self):
        """测试中文内容编码。"""
        data = self.encoder.encode_assistant_response("你好世界", "deepseek-3.2")
        decoder = EventStreamDecoder()
        messages = decoder.decode(data)
        assert messages[0].payload_json["content"] == "你好世界"

    def test_frame_structure(self):
        """验证帧结构：total_length、headers_length、CRC 字段正确。"""
        data = self.encoder.encode_assistant_response("hi", "deepseek-3.2")
        # total_length 字段
        total_length = struct.unpack(">I", data[0:4])[0]
        assert total_length == len(data)
        # headers_length 字段
        headers_length = struct.unpack(">I", data[4:8])[0]
        assert headers_length > 0
        # prelude_crc 校验
        prelude_crc_stored = struct.unpack(">I", data[8:12])[0]
        prelude_crc_calc = _crc32(data[0:8])
        assert prelude_crc_stored == prelude_crc_calc
        # message_crc 校验
        msg_crc_stored = struct.unpack(">I", data[-4:])[0]
        msg_crc_calc = _crc32(data[:-4])
        assert msg_crc_stored == msg_crc_calc

    def test_headers_contain_required_fields(self):
        """验证 headers 包含 :event-type、:content-type、:message-type。"""
        data = self.encoder.encode_assistant_response("test", "deepseek-3.2")
        decoder = EventStreamDecoder()
        messages = decoder.decode(data)
        headers = messages[0].headers
        assert ":event-type" in headers
        assert ":content-type" in headers
        assert ":message-type" in headers
        assert headers[":message-type"] == "event"
        assert headers[":content-type"] == "application/json"


class TestEventStreamDecoder:
    def setup_method(self):
        self.decoder = EventStreamDecoder()
        self.encoder = EventStreamEncoder()

    def test_roundtrip_simple(self):
        """编码-解码往返：简单英文内容。"""
        content = "Hello, this is a test response."
        encoded = self.encoder.build_full_response(content)
        decoded = self.decoder.decode(encoded)
        assert len(decoded) == 3
        assert decoded[0].payload_json["content"] == content

    def test_roundtrip_chinese(self):
        """编码-解码往返：中文内容。"""
        content = "这是一个测试响应，包含中文字符。"
        encoded = self.encoder.build_full_response(content, "deepseek-3.2")
        decoded = self.decoder.decode(encoded)
        assert decoded[0].payload_json["content"] == content

    def test_roundtrip_long_content(self):
        """编码-解码往返：长内容（模拟真实 AI 回复）。"""
        content = "A" * 5000
        encoded = self.encoder.build_full_response(content)
        decoded = self.decoder.decode(encoded)
        assert decoded[0].payload_json["content"] == content

    def test_roundtrip_special_chars(self):
        """编码-解码往返：特殊字符（代码块、换行等）。"""
        content = '```python\ndef hello():\n    print("Hello, World!")\n```'
        encoded = self.encoder.build_full_response(content)
        decoded = self.decoder.decode(encoded)
        assert decoded[0].payload_json["content"] == content

    def test_multiple_frames_in_sequence(self):
        """解码连续多帧数据。"""
        frame1 = self.encoder.encode_assistant_response("chunk1", "deepseek-3.2")
        frame2 = self.encoder.encode_assistant_response("chunk2", "deepseek-3.2")
        frame3 = self.encoder.encode_context_usage(10.0)
        combined = frame1 + frame2 + frame3
        messages = self.decoder.decode(combined)
        assert len(messages) == 3
        assert messages[0].payload_json["content"] == "chunk1"
        assert messages[1].payload_json["content"] == "chunk2"
        assert messages[2].payload_json["contextUsagePercentage"] == 10.0

    def test_empty_data(self):
        """空数据不崩溃。"""
        messages = self.decoder.decode(b"")
        assert messages == []

    def test_incomplete_frame(self):
        """不完整帧不崩溃。"""
        messages = self.decoder.decode(b"\x00\x00\x00\x10")
        assert messages == []

    def test_decode_real_capture_format(self):
        """用真实抓包格式验证解码：手动构造一个符合协议的帧。

        基于 KIRO_PROTOCOL.md 中的帧结构：
        [total_len:4][headers_len:4][prelude_crc:4][headers][payload][message_crc:4]
        """
        # 构造一个 assistantResponseEvent 帧（模拟真实抓包数据格式）
        payload = json.dumps({"content": "test", "modelId": "simple-task"}).encode("utf-8")

        # 手动编码 headers（与 encoder 相同格式）
        headers_data = b""
        for name, value in {
            ":event-type": "assistantResponseEvent",
            ":content-type": "application/json",
            ":message-type": "event",
        }.items():
            nb = name.encode("utf-8")
            vb = value.encode("utf-8")
            headers_data += struct.pack("B", len(nb)) + nb
            headers_data += struct.pack("B", 7)  # string type
            headers_data += struct.pack(">H", len(vb)) + vb

        headers_len = len(headers_data)
        total_len = 12 + headers_len + len(payload) + 4

        prelude = struct.pack(">II", total_len, headers_len)
        prelude_crc = struct.pack(">I", _crc32(prelude))
        msg_without_crc = prelude + prelude_crc + headers_data + payload
        msg_crc = struct.pack(">I", _crc32(msg_without_crc))
        frame = msg_without_crc + msg_crc

        messages = self.decoder.decode(frame)
        assert len(messages) == 1
        assert messages[0].event_type == "assistantResponseEvent"
        assert messages[0].payload_json["content"] == "test"
        assert messages[0].payload_json["modelId"] == "simple-task"

    def test_intent_classification_response_format(self):
        """验证 intent-classification 响应格式（simple-task 模型）。"""
        intent_payload = '{"chat": 0.0, "do": 1.0, "spec": 0.0}'
        data = self.encoder.build_full_response(intent_payload, "simple-task")
        messages = self.decoder.decode(data)
        assert messages[0].event_type == "assistantResponseEvent"
        assert messages[0].payload_json["modelId"] == "simple-task"
        # 内容是 JSON 字符串
        content = messages[0].payload_json["content"]
        intent = json.loads(content)
        assert "chat" in intent
        assert "do" in intent
        assert "spec" in intent


class TestCRC32:
    def test_crc32_basic(self):
        """CRC32 基本计算。"""
        result = _crc32(b"hello")
        assert isinstance(result, int)
        assert 0 <= result <= 0xFFFFFFFF

    def test_crc32_deterministic(self):
        """相同输入产生相同 CRC32。"""
        assert _crc32(b"test") == _crc32(b"test")

    def test_crc32_different_inputs(self):
        """不同输入产生不同 CRC32。"""
        assert _crc32(b"hello") != _crc32(b"world")

    def test_crc32_empty(self):
        """空字节的 CRC32。"""
        result = _crc32(b"")
        assert result == 0x00000000
