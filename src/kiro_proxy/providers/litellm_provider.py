"""LiteLLM Provider — 默认 AI 后端。

将请求透明转发到 LiteLLM 端点，行为与原有 `_call_litellm()` 一致。
"""

import logging
from typing import Optional

import httpx

from . import Provider, ProviderConfig

logger = logging.getLogger(__name__)


class LiteLLMProvider(Provider):
    """LiteLLM 聚合服务 Provider。

    可处理多个模型，作为默认兜底 Provider。
    """

    def __init__(self, config: ProviderConfig, timeout: float = 60):
        super().__init__(config)
        self._client = httpx.Client(timeout=timeout, verify=False)
        self._retries = config.extra_body.get("retries", 2) if config.extra_body else 2

    def complete(self, request: dict) -> Optional[dict]:
        """转发请求到 LiteLLM 端点，含自动重试。

        Args:
            request: OpenAI 格式的请求 dict

        Returns:
            OpenAI 格式的响应，失败返回 None
        """
        # 自动回退模型名
        request = self._resolve_request_model(request)

        url = f"{self.config.api_base.rstrip('/')}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        last_error = None
        max_retries = self._retries

        for attempt in range(max_retries + 1):
            try:
                response = self._client.post(url, json=request, headers=headers)

                if response.status_code == 200:
                    return response.json()
                elif response.status_code >= 500:
                    last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                    logger.warning(f"LiteLLM {response.status_code}, attempt {attempt + 1}/{max_retries + 1}")
                    if attempt < max_retries:
                        continue
                else:
                    logger.error(f"LiteLLM returned {response.status_code}: {response.text[:500]}")
                    return None

            except httpx.TimeoutException:
                last_error = "timeout"
                logger.warning(f"LiteLLM timeout, attempt {attempt + 1}/{max_retries + 1}")
                if attempt < max_retries:
                    continue
            except Exception as e:
                logger.error(f"LiteLLM request failed: {e}")
                return None

        logger.error(f"LiteLLM failed after {max_retries + 1} attempts: {last_error}")
        return None

    def close(self):
        try:
            self._client.close()
        except Exception as e:
            logger.warning(f"Error closing LiteLLM HTTP client: {e}")
