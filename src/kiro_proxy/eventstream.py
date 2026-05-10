"""AWS EventStream 编解码器。

基于 Kiro 抓包数据实现的 AWS EventStream 二进制协议编解码。

帧结构:
  [total_length:4][headers_length:4][prelude_crc:4]
  [headers...][payload...][message_crc:4]

Header 编码:
  [name_length:1][name:N][:type:1][value_length:2][value:M]
  type=7 表示 string 类型
"""

import struct
import json
import binascii
from typing import Dict, List, Any, Optional
from dataclasses import dataclass


def _crc32(data: bytes) -> int:
    """计算 CRC32（AWS EventStream 使用标准 CRC32）。"""
    return binascii.crc32(data) & 0xFFFFFFFF


@dataclass
class EventStreamMessage:
    """一个 EventStream 消息。"""
    headers: Dict[str, str]
    payload: bytes

    @property
    def event_type(self) -> Optional[str]:
        return self.headers.get(":event-type")

    @property
    def content_type(self) -> Optional[str]:
        return self.headers.get(":content-type")

    @property
    def payload_json(self) -> Optional[Dict]:
        if self.payload:
            try:
                return json.loads(self.payload.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None
        return None


class EventStreamDecoder:
    """解码 AWS EventStream 二进制流为消息列表。"""

    def decode(self, data: bytes) -> List[EventStreamMessage]:
        """解码完整的 EventStream 数据为消息列表。"""
        messages = []
        offset = 0

        while offset < len(data):
            if offset + 12 > len(data):
                break

            # 读取 prelude: total_length(4) + headers_length(4) + prelude_crc(4)
            total_length = struct.unpack(">I", data[offset:offset + 4])[0]
            headers_length = struct.unpack(">I", data[offset + 4:offset + 8])[0]
            # prelude_crc = struct.unpack(">I", data[offset + 8:offset + 12])[0]

            if offset + total_length > len(data):
                break

            # 解析 headers
            headers_start = offset + 12
            headers_end = headers_start + headers_length
            headers = self._decode_headers(data[headers_start:headers_end])

            # 解析 payload
            payload_start = headers_end
            payload_end = offset + total_length - 4  # 减去 message_crc
            payload = data[payload_start:payload_end]

            messages.append(EventStreamMessage(headers=headers, payload=payload))
            offset += total_length

        return messages

    def _decode_headers(self, data: bytes) -> Dict[str, str]:
        """解码 EventStream headers。"""
        headers = {}
        offset = 0

        while offset < len(data):
            # name length (1 byte)
            name_length = data[offset]
            offset += 1

            # name
            name = data[offset:offset + name_length].decode("utf-8")
            offset += name_length

            # type (1 byte), 7 = string
            header_type = data[offset]
            offset += 1

            if header_type == 7:  # string
                # value length (2 bytes, big-endian)
                value_length = struct.unpack(">H", data[offset:offset + 2])[0]
                offset += 2

                # value
                value = data[offset:offset + value_length].decode("utf-8")
                offset += value_length

                headers[name] = value
            else:
                # 其他类型暂不支持，跳过
                break

        return headers


class EventStreamEncoder:
    """编码消息为 AWS EventStream 二进制格式。"""

    def encode_message(self, event_type: str, payload: Dict[str, Any],
                       content_type: str = "application/json") -> bytes:
        """编码单个 EventStream 消息。"""
        # 编码 payload
        payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        # 编码 headers
        headers_bytes = self._encode_headers({
            ":event-type": event_type,
            ":content-type": content_type,
            ":message-type": "event",
        })

        headers_length = len(headers_bytes)
        # total = prelude(12) + headers + payload + message_crc(4)
        total_length = 12 + headers_length + len(payload_bytes) + 4

        # 构造 prelude
        prelude = struct.pack(">II", total_length, headers_length)
        prelude_crc = struct.pack(">I", _crc32(prelude))

        # 组装消息（不含 message_crc）
        message_without_crc = prelude + prelude_crc + headers_bytes + payload_bytes

        # 计算 message_crc
        message_crc = struct.pack(">I", _crc32(message_without_crc))

        return message_without_crc + message_crc

    def _encode_headers(self, headers: Dict[str, str]) -> bytes:
        """编码 headers 为二进制格式。"""
        result = b""

        for name, value in headers.items():
            name_bytes = name.encode("utf-8")
            value_bytes = value.encode("utf-8")

            # name_length(1) + name + type(1) + value_length(2) + value
            result += struct.pack("B", len(name_bytes))
            result += name_bytes
            result += struct.pack("B", 7)  # type = string
            result += struct.pack(">H", len(value_bytes))
            result += value_bytes

        return result

    def encode_assistant_response(self, content: str, model_id: str = "deepseek-3.2") -> bytes:
        """编码一个 assistantResponseEvent。

        Args:
            content: 文本回复内容
            model_id: 模型 ID

        Note:
            工具调用使用独立的 toolUseEvent 帧（encode_tool_use_start/input/stop），
            不要将 toolUses 嵌入 assistantResponseEvent。
        """
        return self.encode_message(
            event_type="assistantResponseEvent",
            payload={"content": content, "modelId": model_id}
        )

    def encode_tool_use_start(self, name: str, tool_use_id: str) -> bytes:
        """编码 toolUseEvent 声明帧（第一帧）。

        Args:
            name: 工具名称
            tool_use_id: 工具调用 ID
        """
        return self.encode_message(
            event_type="toolUseEvent",
            payload={"name": name, "toolUseId": tool_use_id}
        )

    def encode_tool_use_input(self, name: str, tool_use_id: str, input_data: Dict[str, Any]) -> bytes:
        """编码 toolUseEvent 输入参数帧（第二帧）。

        Args:
            name: 工具名称
            tool_use_id: 工具调用 ID
            input_data: 输入参数
        """
        return self.encode_message(
            event_type="toolUseEvent",
            payload={"name": name, "toolUseId": tool_use_id, "input": json.dumps(input_data)}
        )

    def encode_tool_use_stop(self, name: str, tool_use_id: str) -> bytes:
        """编码 toolUseEvent 停止帧（第三帧）。

        Args:
            name: 工具名称
            tool_use_id: 工具调用 ID
        """
        return self.encode_message(
            event_type="toolUseEvent",
            payload={"name": name, "toolUseId": tool_use_id, "stop": True}
        )

    def encode_context_usage(self, percentage: float = 5.0) -> bytes:
        """编码一个 contextUsageEvent。"""
        return self.encode_message(
            event_type="contextUsageEvent",
            payload={"contextUsagePercentage": percentage}
        )

    def encode_metering(self, usage: float = 0.01) -> bytes:
        """编码一个 meteringEvent。"""
        return self.encode_message(
            event_type="meteringEvent",
            payload={"unit": "credit", "unitPlural": "credits", "usage": usage}
        )

    def build_full_response(self, content: str, model_id: str = "deepseek-3.2") -> bytes:
        """构造完整的 EventStream 响应体（包含所有必要事件）。"""
        frames = b""

        # 1. assistantResponseEvent
        frames += self.encode_assistant_response(content, model_id)

        # 2. contextUsageEvent
        frames += self.encode_context_usage(5.0)

        # 3. meteringEvent
        frames += self.encode_metering(0.01)

        return frames
