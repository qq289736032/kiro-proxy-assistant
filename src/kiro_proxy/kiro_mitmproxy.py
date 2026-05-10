"""Kiro mitmproxy 核心代理脚本。

拦截 Kiro 的 /generateAssistantResponse 请求，
转换格式后转发到 LiteLLM，再将响应转换回 EventStream 格式。

用法: mitmdump -s kiro_mitmproxy.py --listen-port 9080 --ssl-insecure
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any

# 确保 src 目录在 sys.path 中（mitmdump -s 加载时相对导入不可用）
_SRC_DIR = Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import yaml
from mitmproxy import http

from kiro_proxy.request_converter import RequestConverter
from kiro_proxy.response_adapter import ResponseAdapter
from kiro_proxy.model_router import ModelRouter
from kiro_proxy.stats_collector import StatsCollector
from kiro_proxy.providers.router import build_router

# 全局日志详细级别
LOG_DETAIL_LEVEL = 1

logger = logging.getLogger(__name__)


class CaptureManager:
    """原始数据捕获管理器，用于记录未知包结构和调试信息。"""
    
    def __init__(self, config: Dict):
        self.enabled = config.get("enable_capture", False)
        self.capture_path = Path(config.get("capture_path", "~/.kiro-proxy/captures/")).expanduser()
        
        if self.enabled:
            self.capture_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Capture enabled, path: {self.capture_path}")
    
    def capture_request(self, flow: http.HTTPFlow, metadata: Dict[str, Any]) -> Optional[str]:
        """捕获原始请求数据。"""
        if not self.enabled:
            return None
        
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            capture_id = f"{timestamp}_{metadata.get('client_id', 'unknown')}"
            filename = self.capture_path / f"{capture_id}_request.json"
            
            capture_data = {
                "timestamp": datetime.now().isoformat(),
                "capture_id": capture_id,
                "type": "request",
                "metadata": metadata,
                "request": {
                    "method": flow.request.method,
                    "url": flow.request.pretty_url,
                    "headers": dict(flow.request.headers),
                    "body": flow.request.text,
                    "body_size": len(flow.request.text) if flow.request.text else 0
                }
            }
            
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(capture_data, f, ensure_ascii=False, indent=2)
            
            _log_detail(2, f"[{metadata.get('client_id')}] Request captured: {filename.name}")
            return capture_id
            
        except Exception as e:
            logger.warning(f"Failed to capture request: {e}")
            return None
    
    def capture_response(self, capture_id: str, response_data: Dict[str, Any], metadata: Dict[str, Any]) -> None:
        """捕获响应数据。"""
        if not self.enabled or not capture_id:
            return
        
        try:
            filename = self.capture_path / f"{capture_id}_response.json"
            
            capture_data = {
                "timestamp": datetime.now().isoformat(),
                "capture_id": capture_id,
                "type": "response",
                "metadata": metadata,
                "response": response_data
            }
            
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(capture_data, f, ensure_ascii=False, indent=2)
            
            _log_detail(2, f"[{metadata.get('client_id')}] Response captured: {filename.name}")
            
        except Exception as e:
            logger.warning(f"Failed to capture response: {e}")

# Kiro 后端域名
KIRO_BACKEND = "q.us-east-1.amazonaws.com"

# 需要拦截的路径
INTERCEPT_PATH = "/generateAssistantResponse"

# 默认配置文件路径（相对于此脚本的项目根目录）
_DEFAULT_CONFIG = Path(__file__).parent.parent.parent / "config.yaml"


def _load_config(config_path: Path = _DEFAULT_CONFIG) -> Dict:
    """加载 YAML 配置文件，不存在则返回默认配置。"""
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load config {config_path}: {e}")
    return {}


def _log_detail(level: int, message: str, *args, **kwargs) -> None:
    """根据详细级别记录日志。
    
    Args:
        level: 所需的详细级别（0=minimal, 1=normal, 2=detailed, 3=full）
        message: 日志消息
    """
    if LOG_DETAIL_LEVEL >= level:
        logger.debug(message, *args, **kwargs)


def _setup_logging(config: Dict) -> None:
    """根据配置设置日志级别和格式。"""
    logging_cfg = config.get("logging", {})
    
    # 日志级别（环境变量优先，然后配置文件，最后默认 INFO）
    log_level_str = os.environ.get("KIRO_PROXY_LOG_LEVEL", 
                                  logging_cfg.get("level", "INFO")).upper()
    
    try:
        log_level = getattr(logging, log_level_str)
    except AttributeError:
        log_level = logging.INFO
        logger.warning(f"Invalid log level '{log_level_str}', using INFO")
    
    # 日志格式
    log_format = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    
    # 清除现有的处理器
    logging.getLogger().handlers.clear()
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(log_format))
    
    # 创建根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)
    
    # 设置模块特定日志级别
    modules_cfg = logging_cfg.get("modules", {})
    for module_name, module_level in modules_cfg.items():
        try:
            module_logger = logging.getLogger(f"kiro_proxy.{module_name}")
            module_logger.setLevel(getattr(logging, module_level.upper()))
            _log_detail(2, f"Module '{module_name}' log level set to {module_level}")
        except AttributeError:
            logger.warning(f"Invalid log level '{module_level}' for module '{module_name}'")
    
    # 存储详细级别配置供其他模块使用
    global LOG_DETAIL_LEVEL
    LOG_DETAIL_LEVEL = logging_cfg.get("detail_level", 1)
    
    logger.info(f"Logging configured: level={logging.getLevelName(log_level)}, detail_level={LOG_DETAIL_LEVEL}")


class KiroProxyAddon:
    """Kiro 代理 mitmproxy addon。"""

    def __init__(self):
        config = _load_config()

        # 设置日志（必须在其他初始化之前）
        _setup_logging(config)

        routing_cfg = config.get("model_routing", {})
        logging_cfg = config.get("logging", {})

        self.request_converter = RequestConverter()
        self.response_adapter = ResponseAdapter()
        self.model_router = ModelRouter(routing_cfg)
        self.stats = StatsCollector()

        # 初始化捕获管理器
        self.capture_manager = CaptureManager(logging_cfg)

        # Provider 路由（替代硬编码的 LiteLLM 调用）
        self.provider_router = build_router(_DEFAULT_CONFIG)

        # 从配置读取代理地址
        proxy_cfg = config.get("proxy", {})
        proxy_host = proxy_cfg.get("host", "127.0.0.1")
        proxy_port = proxy_cfg.get("port", 9080)
        logger.info(f"KiroProxyAddon initialized, proxy at http://{proxy_host}:{proxy_port}")

    def done(self) -> None:
        """mitmproxy 停止时释放 Provider 资源。"""
        try:
            self.provider_router.close_all()
            logger.info("KiroProxyAddon: providers closed")
        except Exception as e:
            logger.warning(f"Error closing providers: {e}")

    def request(self, flow: http.HTTPFlow) -> None:
        """请求拦截处理。"""
        # 只处理目标域名
        if KIRO_BACKEND not in flow.request.pretty_host:
            return

        # 只拦截 generateAssistantResponse
        if flow.request.path != INTERCEPT_PATH:
            logger.debug(f"Passthrough: {flow.request.method} {flow.request.path}")
            return

        if flow.request.method != "POST":
            return

        client_id = f"{flow.client_conn.peername[0]}:{flow.client_conn.peername[1]}" if flow.client_conn.peername else "unknown"
        logger.info(f"[{client_id}] Intercepting: POST {INTERCEPT_PATH}")

        # 捕获原始请求（如果启用）
        capture_id = None
        metadata = {
            "client_id": client_id,
            "path": INTERCEPT_PATH,
            "timestamp": datetime.now().isoformat()
        }
        
        try:
            # 获取 agent mode
            agent_mode = self.request_converter.get_agent_mode(flow.request)
            logger.info(f"[{client_id}]   Agent mode: {agent_mode}")
            
            # 更新 metadata
            metadata["agent_mode"] = agent_mode
            
            # 捕获请求
            capture_id = self.capture_manager.capture_request(flow, metadata)

            # 转换请求
            openai_request = self.request_converter.convert(flow.request)
            if openai_request is None:
                logger.error(f"[{client_id}]   Request conversion failed, passing through")
                return

            # 根据详细级别记录请求信息
            if LOG_DETAIL_LEVEL >= 2:  # detailed 或 full
                _log_detail(2, f"[{client_id}] Raw request body (first 2000 chars): {flow.request.text[:2000]}")
                _log_detail(2, f"[{client_id}] Converted OpenAI request: {json.dumps(openai_request, ensure_ascii=False)[:2000]}")
            elif LOG_DETAIL_LEVEL >= 1:  # normal
                # 只记录关键信息摘要
                request_summary = {
                    "messages_count": len(openai_request.get("messages", [])),
                    "has_tools": "tools" in openai_request,
                    "model": openai_request.get("model", "unknown")
                }
                _log_detail(1, f"[{client_id}] Request summary: {request_summary}")

            # 模型路由
            meta = openai_request.pop("_meta", {})
            selected_model = self.model_router.select_model(
                openai_request,
                agent_mode=meta.get("agent_mode", "vibe"),
                kiro_model_id=meta.get("kiro_model_id", "")
            )
            openai_request["model"] = selected_model
            logger.info(f"[{client_id}]   Routed to model: {selected_model}")

            # 路由到 Provider 并调用
            provider = self.provider_router.route(selected_model)
            provider_name = provider.config.name
            logger.info(f"[{client_id}]   Using provider: {provider_name}")
            llm_response = provider.complete(openai_request)

            if llm_response is None:
                logger.error(f"[{client_id}]   Provider '{provider_name}' call failed")
                eventstream_data = self.response_adapter.create_error_response(
                    f"Failed to get response from {provider_name}"
                )
            else:
                # 根据详细级别记录响应信息
                if LOG_DETAIL_LEVEL >= 3:  # full
                    _log_detail(3, f"[{client_id}] Full LLM response: {json.dumps(llm_response, ensure_ascii=False)}")
                elif LOG_DETAIL_LEVEL >= 2:  # detailed
                    _log_detail(2, f"[{client_id}] LLM response (first 2000 chars): {json.dumps(llm_response, ensure_ascii=False)[:2000]}")
                elif LOG_DETAIL_LEVEL >= 1:  # normal
                    # 记录响应摘要
                    if llm_response.get("choices"):
                        choice = llm_response["choices"][0]
                        finish_reason = choice.get("finish_reason", "unknown")
                        has_content = bool(choice.get("message", {}).get("content"))
                        has_tool_calls = bool(choice.get("message", {}).get("tool_calls"))
                        response_summary = {
                            "finish_reason": finish_reason,
                            "has_content": has_content,
                            "has_tool_calls": has_tool_calls
                        }
                        _log_detail(1, f"[{client_id}] Response summary: {response_summary}")

                kiro_model_id = meta.get("kiro_model_id", "deepseek-3.2")
                if agent_mode == "intent-classification":
                    eventstream_data = self.response_adapter.adapt_intent_classification(
                        llm_response
                    )
                else:
                    # 返回實際調用的模型名，而不是 Kiro 發來的原始 modelId
                    eventstream_data = self.response_adapter.adapt(
                        llm_response, model_id=selected_model
                    )

                # 记录工具调用信息（如果有）
                if llm_response.get("choices"):
                    choice = llm_response["choices"][0]
                    if choice.get("finish_reason") == "tool_calls":
                        tool_calls = choice.get("message", {}).get("tool_calls", [])
                        if tool_calls:
                            tool_names = [tc.get('function', {}).get('name', 'unknown') for tc in tool_calls]
                            logger.info(f"[{client_id}]   Tool calls detected: {tool_names}")

                            # 详细记录工具调用参数
                            if LOG_DETAIL_LEVEL >= 2:
                                for i, tc in enumerate(tool_calls):
                                    func = tc.get("function", {})
                                    _log_detail(2, f"[{client_id}]   Tool {i+1}: {func.get('name')}, args: {func.get('arguments', '{}')[:500]}")

            flow.response = self.response_adapter.build_http_response(eventstream_data)
            self.stats.record_request(KIRO_BACKEND, selected_model)
            self.stats.record_response(200)
            logger.info(f"[{client_id}]   Response injected successfully")

            # 捕获响应（如果启用）
            if llm_response is not None:
                response_metadata = metadata.copy()
                response_metadata.update({
                    "selected_model": selected_model,
                    "provider": provider_name,
                    "kiro_model_id": meta.get("kiro_model_id", "deepseek-3.2"),
                    "status": "success"
                })

                response_data = {
                    "llm_response": llm_response,
                    "eventstream_size": len(eventstream_data) if eventstream_data else 0,
                    "has_tool_calls": bool(llm_response.get("choices") and
                                          llm_response["choices"][0].get("finish_reason") == "tool_calls")
                }

                self.capture_manager.capture_response(capture_id, response_data, response_metadata)

        except Exception as e:
            logger.error(f"[{client_id}]   Error processing request: {e}", exc_info=True)
            logger.info(f"[{client_id}]   Falling back to passthrough")
            
            # 捕获错误响应
            error_metadata = metadata.copy()
            error_metadata.update({
                "error": str(e),
                "error_type": type(e).__name__,
                "status": "error"
            })
            
            error_data = {
                "error": str(e),
                "error_type": type(e).__name__,
                "traceback": self._format_exception(e)
            }
            
            self.capture_manager.capture_response(capture_id, error_data, error_metadata)

    def _format_exception(self, e: Exception) -> str:
        """格式化异常信息为字符串。"""
        import traceback
        return "".join(traceback.format_exception(type(e), e, e.__traceback__))


# mitmproxy addon 实例
addons = [KiroProxyAddon()]
