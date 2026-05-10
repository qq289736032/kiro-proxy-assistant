"""Provider 抽象基类和公共类型。

所有 Provider 实现必须继承 `Provider` 基类并实现 `complete()` 方法。
"""

import os
import re
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


def resolve_env(value: str) -> str:
    """解析配置中的 ${ENV_VAR} 语法为环境变量值。

    Args:
        value: 可能包含 ${VAR} 引用的字符串

    Returns:
        解析后的字符串，未找到的环境变量替换为空字符串
    """

    def _replace(match):
        env_var = match.group(1)
        resolved = os.environ.get(env_var)
        if resolved is None:
            logger.warning(f"Environment variable '{env_var}' is not set, resolved to empty string")
            return ""
        return resolved

    return re.sub(r'\$\{(\w+)\}', _replace, value)


@dataclass
class ProviderConfig:
    """所有 Provider 共享的基础配置。

    Attributes:
        name: 配置中定义的唯一名称（如 "litellm", "deepseek-v4"）
        api_base: API 端点 URL（如 "https://api.deepseek.com"）
        api_key: API 密钥，支持 ${ENV_VAR} 语法
        models: 此 Provider 支持的模型列表。空列表表示可处理任何模型（用于默认 Provider）。
        default_model: 当请求的模型不在 models 列表中时，自动回退到此模型。
        extra_body: Provider 特有参数（如 DeepSeek 的 thinking），会在 complete() 中合并到请求。
    """
    name: str
    api_base: str
    api_key: str
    models: list = field(default_factory=list)
    default_model: Optional[str] = None
    extra_body: Optional[dict] = None


class Provider(ABC):
    """Provider 抽象基类。

    所有 AI 后端提供者必须实现此接口。
    当前仅支持非流式调用，后续可扩展流式。
    """

    def __init__(self, config: ProviderConfig):
        self.config = config

    def _resolve_request_model(self, request: dict) -> dict:
        """如果请求的模型不在本 Provider 的 models 列表中，自动回退到 default_model。

        这允许 model_routing 中写任意模型名，Provider 自动映射为实际可用的模型。
        """
        model = request.get("model", "")
        if self.config.default_model and self.config.models and model not in self.config.models:
            logger.info(
                "Model '%s' not in provider '%s' model list, "
                "falling back to default_model '%s'",
                model, self.config.name, self.config.default_model,
            )
            request = {**request, "model": self.config.default_model}
        return request

    @abstractmethod
    def complete(self, request: dict) -> dict:
        """非流式调用 LLM，返回完整响应。

        Args:
            request: OpenAI 格式的请求 dict
                {
                    "model": "deepseek-v4-pro",
                    "messages": [...],
                    "max_tokens": ...,
                }

        Returns:
            OpenAI 格式的响应 dict
                {
                    "id": "...",
                    "choices": [{"message": {...}, "finish_reason": "stop"}],
                    "usage": {...}
                }
        """

    def close(self):
        """释放 Provider 资源（如 HTTP 客户端）。"""
        pass


class ModelNameMapper:
    """Kiro 侧 modelId → API 实际模型名的映射器。

    同名映射可省略配置，只有需要别名时才配置映射。
    """

    def __init__(self, mapping: Optional[dict[str, str]] = None):
        self._mapping = mapping or {}

    def resolve(self, kiro_model_id: str) -> str:
        """将 Kiro 模型名转换为 API 模型名。

        Args:
            kiro_model_id: Kiro 请求中的 modelId

        Returns:
            API 侧的实际模型名，未映射时返回原值
        """
        return self._mapping.get(kiro_model_id, kiro_model_id)

    def register(self, kiro_name: str, api_name: str):
        self._mapping[kiro_name] = api_name
