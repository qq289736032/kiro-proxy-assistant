"""智能模型路由器。

基于 Kiro 的 agent-mode 和消息内容，选择最合适的 LiteLLM 模型。
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class ModelRouter:
    """基于请求特征选择最佳模型。"""

    def __init__(self, config: Optional[Dict] = None):
        config = config or {}

        # 从配置加载模型映射，提供合理默认值
        task_models = config.get("task_models", {})
        self.mode_model_mapping = {
            "intent-classification": config.get("intent_classification", "gpt-4o-mini"),
            "vibe": config.get("vibe_default", "deepseek-chat"),
        }
        self.task_model_mapping = {
            "code": task_models.get("code", "deepseek-chat"),
            "analysis": task_models.get("analysis", "gemini-2.5-flash"),
            "creative": task_models.get("creative", "claude-sonnet-4-20250514"),
            "simple": task_models.get("simple", "gpt-4o-mini"),
        }

        # 关键词匹配规则
        self.code_keywords = [
            "code", "python", "javascript", "typescript", "function", "debug",
            "algorithm", "syntax", "error", "implement", "class", "method",
            "compile", "build", "test", "refactor", "bug", "fix", "import",
            "variable", "array", "loop", "api", "database", "sql",
            "代码", "函数", "调试", "实现", "修复", "编译", "重构",
        ]

        self.analysis_keywords = [
            "analyze", "compare", "evaluate", "statistics", "trend", "pattern",
            "data", "insight", "research", "summary", "report", "explain",
            "分析", "比较", "评估", "统计", "趋势", "总结", "解释",
        ]

        self.creative_keywords = [
            "creative", "story", "write", "poem", "design", "imagine",
            "generate", "compose", "fiction", "narrative", "brainstorm",
            "创意", "故事", "写作", "设计", "想象", "头脑风暴",
        ]

        # 模型覆盖（配置文件中设置，或运行时调用 set_override）
        override = config.get("override", "")
        self._model_override: Optional[str] = override if override else None

    def select_model(self, request: Dict[str, Any],
                     agent_mode: str = "vibe",
                     kiro_model_id: str = "") -> str:
        """选择最合适的模型。

        Args:
            request: OpenAI 格式的请求
            agent_mode: Kiro agent 模式 (intent-classification / vibe)
            kiro_model_id: Kiro 原始 modelId

        Returns:
            选择的模型名称
        """
        # 1. 检查覆盖
        if self._model_override:
            logger.info(f"Using model override: {self._model_override}")
            return self._model_override

        # 2. intent-classification 模式用轻量模型
        if agent_mode == "intent-classification":
            model = self.mode_model_mapping.get("intent-classification", "gpt-4o-mini")
            logger.debug(f"Intent classification → {model}")
            return model

        # 3. 如果用户在 Kiro 下拉菜单显式选择了非默认模型，尊重选择
        #    Kiro 默认 modelId 为 "deepseek-3.2"，用户选其他模型时 modelId 变更为选中值
        if kiro_model_id and kiro_model_id not in ("deepseek-3.2", "simple-task", ""):
            logger.info(f"User-selected model: {kiro_model_id}")
            return kiro_model_id

        # 4. vibe 模式：基于内容分析选择
        task_type = self._identify_task_type(request)
        model = self.task_model_mapping.get(task_type, "deepseek-chat")
        logger.info(f"Task type: {task_type} → Model: {model}")
        return model

    def _identify_task_type(self, request: Dict[str, Any]) -> str:
        """分析请求内容，识别任务类型。"""
        messages = request.get("messages", [])
        if not messages:
            return "simple"

        # 取最后一条用户消息
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg.get("content", "")
                break

        if not last_user_msg:
            return "simple"

        content_lower = last_user_msg.lower()

        # 计算各类型得分
        code_score = sum(1 for kw in self.code_keywords if kw in content_lower)
        analysis_score = sum(1 for kw in self.analysis_keywords if kw in content_lower)
        creative_score = sum(1 for kw in self.creative_keywords if kw in content_lower)

        # 选择得分最高的类型（阈值 >= 2）
        scores = {
            "code": code_score,
            "analysis": analysis_score,
            "creative": creative_score,
        }

        max_type = max(scores, key=scores.get)
        if scores[max_type] >= 2:
            return max_type

        return "simple"

    def set_override(self, model: str):
        """设置模型覆盖（强制使用指定模型）。"""
        self._model_override = model
        logger.info(f"Model override set: {model}")

    def clear_override(self):
        """清除模型覆盖。"""
        self._model_override = None
        logger.info("Model override cleared")

    def get_available_models(self) -> List[str]:
        """获取可用模型列表。"""
        return list(set(self.task_model_mapping.values()) | set(self.mode_model_mapping.values()))
