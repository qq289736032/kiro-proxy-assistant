#!/usr/bin/env python3
"""测试日志配置系统。"""

import sys
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.kiro_proxy.kiro_mitmproxy import _setup_logging, _log_detail, LOG_DETAIL_LEVEL
import logging
import yaml

def test_logging_levels():
    """测试不同日志级别。"""
    print("=== 测试日志级别 ===")
    
    # 测试配置
    test_configs = [
        {"logging": {"level": "INFO", "detail_level": 1}},
        {"logging": {"level": "DEBUG", "detail_level": 2}},
        {"logging": {"level": "DEBUG", "detail_level": 3}},
    ]
    
    for i, config in enumerate(test_configs):
        print(f"\n测试配置 {i+1}: {config}")
        
        # 重置日志系统
        logging.getLogger().handlers.clear()
        
        # 设置日志
        _setup_logging(config)
        
        logger = logging.getLogger(__name__)
        
        # 测试不同级别的日志
        logger.debug("这是一条 DEBUG 消息")
        logger.info("这是一条 INFO 消息")
        logger.warning("这是一条 WARNING 消息")
        logger.error("这是一条 ERROR 消息")
        
        # 测试详细级别
        for level in range(4):
            _log_detail(level, f"这是详细级别 {level} 的消息")

def test_module_logging():
    """测试模块特定日志级别。"""
    print("\n=== 测试模块日志级别 ===")
    
    config = {
        "logging": {
            "level": "DEBUG",
            "detail_level": 2,
            "modules": {
                "request_converter": "DEBUG",
                "response_adapter": "INFO",
                "eventstream": "WARNING"
            }
        }
    }
    
    # 重置日志系统
    logging.getLogger().handlers.clear()
    
    # 设置日志
    _setup_logging(config)
    
    # 测试不同模块的日志
    modules = ["request_converter", "response_adapter", "eventstream", "tool_calls"]
    
    for module in modules:
        module_logger = logging.getLogger(f"kiro_proxy.{module}")
        print(f"\n模块 '{module}' 的日志级别: {logging.getLevelName(module_logger.level)}")
        
        module_logger.debug(f"{module} - DEBUG 消息")
        module_logger.info(f"{module} - INFO 消息")
        module_logger.warning(f"{module} - WARNING 消息")

def test_capture_config():
    """测试捕获配置。"""
    print("\n=== 测试捕获配置 ===")
    
    configs = [
        {"logging": {"enable_capture": False}},
        {"logging": {"enable_capture": True, "capture_path": "~/.kiro-proxy/test_captures/"}},
    ]
    
    for i, config in enumerate(configs):
        print(f"\n捕获配置 {i+1}: {config}")
        
        from src.kiro_proxy.kiro_mitmproxy import CaptureManager
        
        capture_manager = CaptureManager(config.get("logging", {}))
        print(f"捕获启用: {capture_manager.enabled}")
        if capture_manager.enabled:
            print(f"捕获路径: {capture_manager.capture_path}")
            print(f"路径存在: {capture_manager.capture_path.exists()}")

if __name__ == "__main__":
    print("开始测试 Kiro Proxy 日志系统")
    print("=" * 50)
    
    test_logging_levels()
    test_module_logging()
    test_capture_config()
    
    print("\n" + "=" * 50)
    print("测试完成")