"""指标提取 - 从 vllm bench serve 输出中逐项正则提取所有指标。"""

import logging
import re

from .config import (
    INT_METRIC_KEYS,
    METRIC_PATTERNS,
    TPOT_KEY_MAP,
    TTFT_KEY_MAP,
)

# 已警告过的指标名,避免同一指标在多次提取中重复告警
_warned_metrics = set()


def reset_warnings():
    """每个测试用例开始时调用,清空警告缓存。"""
    _warned_metrics.clear()


# 预编译每个 metric 的独立正则,避免每次提取都重新编译
_COMPILED_METRIC_PATTERNS = {
    key: re.compile(pat) for key, pat in METRIC_PATTERNS.items()
}


def _extract_all_metrics(output_str: str) -> dict:
    """逐项正则提取所有指标。

    未命中的指标:整数用 0、浮点用 inf 兜底。
    """
    metrics = {key: 0 for key in INT_METRIC_KEYS}
    metrics.update({key: float('inf') for key in METRIC_PATTERNS if key not in INT_METRIC_KEYS})

    for key, cre in _COMPILED_METRIC_PATTERNS.items():
        match = cre.search(output_str)
        if match is None:
            continue
        raw = match.group(1)
        try:
            metrics[key] = int(float(raw)) if key in INT_METRIC_KEYS else float(raw)
        except (ValueError, TypeError) as e:
            display = key.replace('_', ' ').title()
            if display not in _warned_metrics:
                logging.warning(f"提取 {display} 失败: {e}")
                _warned_metrics.add(display)
    return metrics


def select_metric(metrics: dict, label: str, label_map: dict):
    """根据标签从 metrics 字典取值。未知标签返回 inf 并告警。"""
    key = label_map.get(label)
    if key is None:
        logging.error(f"未知标签: {label}")
        return float('inf')
    return metrics[key]


def select_ttft(metrics: dict, label: str) -> float:
    return select_metric(metrics, label, TTFT_KEY_MAP)


def select_tpot(metrics: dict, label: str) -> float:
    return select_metric(metrics, label, TPOT_KEY_MAP)