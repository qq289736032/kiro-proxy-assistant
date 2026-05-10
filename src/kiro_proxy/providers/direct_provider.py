"""Direct Provider — 直连 OpenAI-compatible API。

支持直接调用 DeepSeek、OpenAI 等模型的原始 API，不经过 LiteLLM 聚合层。
"""

import logging
from typing import Optional

import httpx

from . import Provider, ProviderConfig

logger = logging.getLogger(__name__)


class DirectProvider(Provider):
    """直连 Provider，用于直接调用模型原生 API。"""

    def __init__(self, config: ProviderConfig, timeout: float = 60):
        super().__init__(config)
        self._client = httpx.Client(timeout=timeout, verify=False)

    def complete(self, request: dict) -> Optional[dict]:
        """调用远端 API。

        在发送前会将配置中的 extra_body 合并到请求中，
        并自动回退 default_model（如果请求的模型不在 models 列表中）。

        Args:
            request: OpenAI 格式的请求 dict

        Returns:
            OpenAI 格式的响应，失败返回 None
        """
        # 自动回退模型名
        request = self._resolve_request_model(request)

        # 合并配置中的 extra_body 到请求
        if self.config.extra_body:
            existing = request.get("extra_body", {}) or {}
            merged = {**existing, **self.config.extra_body}
            if merged:
                request["extra_body"] = merged

        url = f"{self.config.api_base.rstrip('/')}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self._client.post(url, json=request, headers=headers)
            if response.status_code == 200:
                return response.json()

            logger.error(f"DirectProvider {self.config.name} returned {response.status_code}: {response.text[:500]}")
            return None

        except httpx.TimeoutException:
            logger.error(f"DirectProvider {self.config.name} timeout")
            return None
        except Exception as e:
            logger.error(f"DirectProvider {self.config.name} request failed: {e}")
            return None

    def close(self):
        try:
            self._client.close()
        except Exception as e:
            logger.warning(f"Error closing DirectProvider HTTP client: {e}")
