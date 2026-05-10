import json
import time
import logging
from pathlib import Path
from typing import Dict, Any
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)

class StatsCollector:
    def __init__(self):
        self.stats_dir = Path.home() / ".kiro-proxy" / "stats"
        self.stats_dir.mkdir(parents=True, exist_ok=True)

        self.stats_file = self.stats_dir / "stats.json"

        self.current_stats = {
            "total_requests": 0,
            "total_responses": 0,
            "total_errors": 0,
            "average_latency": 0.0,
            "model_usage": defaultdict(int),
            "response_codes": defaultdict(int),
            "start_time": datetime.now().isoformat(),
            "last_request": None,
            "latencies": []
        }

        self.request_start_times = {}

    def record_request(self, host: str, model: str):
        self.current_stats["total_requests"] += 1
        self.current_stats["model_usage"][model] = self.current_stats["model_usage"].get(model, 0) + 1
        self.current_stats["last_request"] = datetime.now().isoformat()

        request_id = f"{host}_{time.time()}"
        self.request_start_times[request_id] = time.time()

        self._save_stats()

    def record_response(self, status_code: int):
        self.current_stats["total_responses"] += 1
        self.current_stats["response_codes"][str(status_code)] = \
            self.current_stats["response_codes"].get(str(status_code), 0) + 1

        if status_code >= 400:
            self.current_stats["total_errors"] += 1

        self._save_stats()

    def record_latency(self, request_id: str):
        if request_id in self.request_start_times:
            latency = (time.time() - self.request_start_times[request_id]) * 1000

            self.current_stats["latencies"].append(latency)

            if len(self.current_stats["latencies"]) > 1000:
                self.current_stats["latencies"] = self.current_stats["latencies"][-1000:]

            if len(self.current_stats["latencies"]) > 0:
                self.current_stats["average_latency"] = \
                    sum(self.current_stats["latencies"]) / len(self.current_stats["latencies"])

            del self.request_start_times[request_id]
            self._save_stats()

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_requests": self.current_stats["total_requests"],
            "total_responses": self.current_stats["total_responses"],
            "total_errors": self.current_stats["total_errors"],
            "average_latency": self.current_stats["average_latency"],
            "model_usage": dict(self.current_stats["model_usage"]),
            "response_codes": dict(self.current_stats["response_codes"]),
            "start_time": self.current_stats["start_time"],
            "last_request": self.current_stats["last_request"],
        }

    def reset_stats(self):
        self.current_stats = {
            "total_requests": 0,
            "total_responses": 0,
            "total_errors": 0,
            "average_latency": 0.0,
            "model_usage": defaultdict(int),
            "response_codes": defaultdict(int),
            "start_time": datetime.now().isoformat(),
            "last_request": None,
            "latencies": []
        }
        self.request_start_times = {}
        self._save_stats()

    def _save_stats(self):
        try:
            stats_to_save = {
                "total_requests": self.current_stats["total_requests"],
                "total_responses": self.current_stats["total_responses"],
                "total_errors": self.current_stats["total_errors"],
                "average_latency": self.current_stats["average_latency"],
                "model_usage": dict(self.current_stats["model_usage"]),
                "response_codes": dict(self.current_stats["response_codes"]),
                "start_time": self.current_stats["start_time"],
                "last_request": self.current_stats["last_request"],
            }

            with open(self.stats_file, 'w') as f:
                json.dump(stats_to_save, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save stats: {e}")

    def _load_stats(self):
        try:
            if self.stats_file.exists():
                with open(self.stats_file, 'r') as f:
                    loaded = json.load(f)

                self.current_stats["total_requests"] = loaded.get("total_requests", 0)
                self.current_stats["total_responses"] = loaded.get("total_responses", 0)
                self.current_stats["total_errors"] = loaded.get("total_errors", 0)
                self.current_stats["average_latency"] = loaded.get("average_latency", 0.0)
                self.current_stats["model_usage"] = defaultdict(int, loaded.get("model_usage", {}))
                self.current_stats["response_codes"] = defaultdict(int, loaded.get("response_codes", {}))
                self.current_stats["start_time"] = loaded.get("start_time", datetime.now().isoformat())
                self.current_stats["last_request"] = loaded.get("last_request")
        except Exception as e:
            logger.error(f"Failed to load stats: {e}")
