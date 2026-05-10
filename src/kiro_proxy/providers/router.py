"""Provider 路由引擎和配置加载。

ProviderRouter 根据模型名将请求分发到正确的 Provider。
路由策略：优先匹配 DirectProvider，未命中则回退到默认 Provider。
"""

import logging
from pathlib import Path
from typing import Optional

import yaml

from . import Provider, ProviderConfig, ModelNameMapper, resolve_env
from .litellm_provider import LiteLLMProvider
from .direct_provider import DirectProvider

logger = logging.getLogger(__name__)


class ProviderRouter:
    """Provider 路由引擎。

    管理多个 Provider 实例，根据模型名进行路由分发。
    """

    def __init__(self):
        self._providers: dict[str, Provider] = {}
        self._model_map: dict[str, str] = {}
        self._default_provider: Optional[Provider] = None
        self._model_mapper = ModelNameMapper()

    def register(self, provider: Provider):
        """注册 Provider，自动建立模型→Provider 映射。

        DirectProvider 必须声明 models 列表，LiteLLMProvider 作为默认不应注册。
        """
        self._providers[provider.config.name] = provider
        for model in provider.config.models:
            if model in self._model_map:
                logger.warning(f"Model '{model}' already mapped to '{self._model_map[model]}', "
                              f"overriding with '{provider.config.name}'")
            self._model_map[model] = provider.config.name
        logger.info(f"Registered provider '{provider.config.name}' with {len(provider.config.models)} models")

    def set_default(self, provider: Provider):
        """设置默认 Provider（当前为 LiteLLMProvider）。

        默认 Provider 不注册特定模型，它处理所有未匹配的请求。
        """
        self._default_provider = provider
        logger.info(f"Default provider set to '{provider.config.name}'")

    def set_model_mapper(self, mapper: ModelNameMapper):
        """设置模型名映射器。"""
        self._model_mapper = mapper

    def route(self, model: str) -> Provider:
        """根据模型名获取对应的 Provider。

        先尝试精确匹配，再回退到默认 Provider。
        如两者都不可用，回退到任意已注册的 DirectProvider。

        Args:
            model: 模型名（已通过 ModelNameMapper 解析）

        Returns:
            匹配的 Provider 实例

        Raises:
            ValueError: 没有任何 Provider 能处理该模型
        """
        provider_name = self._model_map.get(model)
        if provider_name:
            return self._providers[provider_name]
        if self._default_provider:
            return self._default_provider
        # 回退到任意已注册的 Provider
        if self._providers:
            fallback = next(iter(self._providers.values()))
            logger.info("Model '%s' not registered, falling back to provider '%s'",
                           model, fallback.config.name)
            return fallback
        raise ValueError(f"No provider found for model '{model}'")

    def resolve_model(self, kiro_model_id: str) -> str:
        """解析 Kiro 模型名为实际 API 模型名。"""
        return self._model_mapper.resolve(kiro_model_id)

    def close_all(self):
        """释放所有 Provider 的资源。"""
        for provider in self._providers.values():
            provider.close()
        if self._default_provider:
            self._default_provider.close()


def _load_config_yaml(path: Path) -> dict:
    """加载 YAML 配置文件。"""
    if not path.exists():
        logger.warning(f"Config file not found: {path}")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_router(config_path: Path) -> ProviderRouter:
    """从配置文件构建 ProviderRouter。

    向后兼容：仅有 `litellm` 段时自动构建单 Provider 路由。

    Args:
        config_path: config.yaml 的路径

    Returns:
        配置好的 ProviderRouter 实例
    """
    raw = _load_config_yaml(config_path)
    router = ProviderRouter()

    # 1. LiteLLMProvider（默认兜底）
    litellm_cfg = raw.get("litellm", {})
    if litellm_cfg.get("enabled", True):
        litellm_timeout = litellm_cfg.get("timeout", 60)
        litellm_provider = LiteLLMProvider(ProviderConfig(
            name="litellm",
            api_base=resolve_env(litellm_cfg.get("base_url", "https://test-ai.igovee.com")),
            api_key=resolve_env(litellm_cfg.get("api_key", "")),
            models=[],
            default_model=litellm_cfg.get("default_model"),
            extra_body={"retries": litellm_cfg.get("retries", 2)} if "retries" in litellm_cfg else None,
        ), timeout=float(litellm_timeout))
        router.set_default(litellm_provider)
    else:
        logger.info("LiteLLM provider disabled by config")

    # 2. DirectProvider（可选）
    for name, cfg in raw.get("direct_providers", {}).items():
        if not cfg.get("enabled", True):
            logger.info(f"DirectProvider '{name}' disabled by config")
            continue
        timeout = cfg.get("timeout", 60)
        direct_provider = DirectProvider(ProviderConfig(
            name=name,
            api_base=resolve_env(cfg["api_base"]),
            api_key=resolve_env(cfg["api_key"]),
            models=cfg.get("models", []),
            default_model=cfg.get("default_model"),
            extra_body=cfg.get("extra_body"),
        ), timeout=float(timeout))
        router.register(direct_provider)

    # 3. 模型名映射（可选）
    mapping_cfg = raw.get("model_name_mapping", {})
    if mapping_cfg:
        router.set_model_mapper(ModelNameMapper(mapping_cfg))

    # 4. 检查至少有一个 Provider 可用
    if not router._default_provider and not router._providers:
        raise RuntimeError(
            "No provider available: LiteLLM and all direct providers are disabled or not configured. "
            "Enable at least one provider in config.yaml"
        )

    return router
