"""指标提取 - 从 vllm bench serve 输出中逐项正则提取所有指标;
并从被测服务 /metrics 抓取 Prometheus 快照,计算 prefix cache 命中率与投机采样接受率。"""

import logging
import re
import urllib.request

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


# vLLM prefix cache 计数器候选名(新版为 gpu/cpu 前缀,旧版无前缀),按序取第一对齐全的
_PREFIX_CACHE_PAIRS = [
    ("vllm:gpu_prefix_cache_hits", "vllm:gpu_prefix_cache_queries"),
    ("vllm:prefix_cache_hits", "vllm:prefix_cache_queries"),
    ("vllm:cpu_prefix_cache_hits", "vllm:cpu_prefix_cache_queries"),
]
_SPEC_DECODE_ACCEPTED_KEY = "vllm:spec_decode_num_accepted_tokens"
_SPEC_DECODE_DRAFT_KEY = "vllm:spec_decode_num_draft_tokens"

# SGLang: 投机采样为 per-dp_rank Gauge(prefix cache 计数器见下方退回口径)
_SGLANG_CACHED_TOKENS_KEY = "sglang:cached_tokens_total"
_SGLANG_PROMPT_TOKENS_KEY = "sglang:prompt_tokens_total"
_SGLANG_PROMPT_HIST_SUM_KEY = "sglang:prompt_tokens_histogram_sum"
_SGLANG_UNCACHED_SUM_KEY = "sglang:uncached_prompt_tokens_histogram_sum"
_SGLANG_SPEC_ACCEPT_RATE_KEY = "sglang:spec_accept_rate"
_SGLANG_SPEC_ACCEPT_LENGTH_KEY = "sglang:spec_accept_length"


def scrape_prometheus_metrics(host: str, port: int, path: str = "/metrics",
                              timeout: float = 5.0) -> dict:
    """GET http://host:port/path 并解析 Prometheus 文本格式,返回 {指标名: [(labels, 数值)...]}。

    同名多条序列(不同 label,如多 dp_rank)保留全部样本与 label,由调用方按指标语义
    聚合(计数器求和 / 按 dp_rank 配对);注释行跳过;
    网络错误原样抛出,由调用方处理。
    """
    url = f"http://{host}:{port}{path}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        if len(tokens) < 2:
            continue
        name_and_labels = tokens[0]
        name = name_and_labels.split("{", 1)[0]
        labels = ""
        if "{" in name_and_labels:
            labels = name_and_labels[name_and_labels.index("{") + 1:name_and_labels.rfind("}")]
        try:
            values.setdefault(name, []).append((labels, float(tokens[1])))
        except ValueError:
            continue
    return values


def _resolve_counter_key(snapshot: dict, key: str):
    """计数器样本名解析。

    Prometheus 文本导出会给计数器样本追加 `_total` 后缀
    (如 vllm:prefix_cache_queries → vllm:prefix_cache_queries_total),
    精确名未命中时自动尝试 `<key>_total`;均未命中返回 None。
    """
    if not snapshot:
        return None
    if key in snapshot:
        return key
    total_key = f"{key}_total"
    if total_key in snapshot:
        return total_key
    return None


def _sum_series(snapshot: dict, key: str):
    """计数器语义聚合: 同名多序列(如多 dp_rank)求和;指标缺失返回 None。

    key 可传无后缀的计数器族名,内部自动解析 `_total` 样本名。
    """
    actual = _resolve_counter_key(snapshot, key)
    if actual is None:
        return None
    return sum(v for _, v in snapshot[actual])


_DP_RANK_RE = re.compile(r'\bdp_rank="([^"]+)"')


def _rank_values(snapshot: dict, key: str) -> dict:
    """{dp_rank: 数值};无 dp_rank label 的序列归入 None 键。"""
    out = {}
    for labels, value in (snapshot.get(key) or []):
        m = _DP_RANK_RE.search(labels)
        out[m.group(1) if m else None] = value
    return out


def _detect_backend(snapshot: dict) -> str:
    """按指标名前缀识别推理后端: 'vllm' / 'sglang' / ''(未知)。"""
    for key in snapshot:
        if key.startswith("vllm:"):
            return "vllm"
        if key.startswith("sglang:"):
            return "sglang"
    return ""


def _compute_vllm_rates(before: dict, after: dict):
    """vLLM: prefix cache 命中率与投机采样接受率,均为计数器差值(多序列求和)。

    计数器样本名可能带 `_total` 后缀(取决于 vLLM 版本/注册方式),自动解析。
    """
    if not before or not after:
        return "", ""
    cache_rate = ""
    for hits_key, queries_key in _PREFIX_CACHE_PAIRS:
        queries_actual = _resolve_counter_key(after, queries_key)
        hits_actual = _resolve_counter_key(after, hits_key)
        if queries_actual is None or hits_actual is None:
            continue
        delta_queries = (_sum_series(after, queries_actual)
                         - (_sum_series(before, queries_actual) or 0.0))
        if delta_queries > 0:
            delta_hits = (_sum_series(after, hits_actual)
                          - (_sum_series(before, hits_actual) or 0.0))
            cache_rate = round(delta_hits / delta_queries * 100, 2)
        break
    spec_rate = ""
    accepted_actual = _resolve_counter_key(after, _SPEC_DECODE_ACCEPTED_KEY)
    draft_actual = _resolve_counter_key(after, _SPEC_DECODE_DRAFT_KEY)
    if accepted_actual is not None and draft_actual is not None:
        delta_draft = (_sum_series(after, draft_actual)
                       - (_sum_series(before, draft_actual) or 0.0))
        if delta_draft > 0:
            delta_accepted = (_sum_series(after, accepted_actual)
                              - (_sum_series(before, accepted_actual) or 0.0))
            spec_rate = round(delta_accepted / delta_draft * 100, 2)
    return cache_rate, spec_rate


def _sglang_cache_hit_rate(before: dict, after: dict):
    """SGLang token 级 prefix cache 命中率(百分数)。

    首选 Δcached_tokens_total ÷ Δprompt_tokens_total 计数器差值;
    unified 等版本不导出 cached_tokens_total 样本时,退回
    1 - Δuncached_prompt_tokens_histogram_sum ÷ Δprompt(SGLang 语义: uncached = prompt - cached)。
    不使用 sglang:cache_hit_rate: 该 Gauge 按 prefill 批次覆盖,混合流量下不可靠。
    """
    if not before or not after:
        return ""
    # 分母: prompt token 总量,优先计数器,缺失时用直方图 _sum
    prompt_key = None
    for key in (_SGLANG_PROMPT_TOKENS_KEY, _SGLANG_PROMPT_HIST_SUM_KEY):
        if key in after and key in before:
            prompt_key = key
            break
    if prompt_key is None:
        return ""
    delta_prompt = _sum_series(after, prompt_key) - _sum_series(before, prompt_key)
    if delta_prompt <= 0:
        return ""

    cached_a = _sum_series(after, _SGLANG_CACHED_TOKENS_KEY)
    cached_b = _sum_series(before, _SGLANG_CACHED_TOKENS_KEY)
    if cached_a is not None and cached_b is not None:
        hit = (cached_a - cached_b) / delta_prompt
    else:
        unc_a = _sum_series(after, _SGLANG_UNCACHED_SUM_KEY)
        unc_b = _sum_series(before, _SGLANG_UNCACHED_SUM_KEY)
        if unc_a is None or unc_b is None:
            return ""
        hit = 1 - (unc_a - unc_b) / delta_prompt
    return round(max(0.0, min(hit, 1.0)) * 100, 2)


def _sglang_spec_accept_rate(after: dict):
    """SGLang 投机采样接受率(百分数),取测试后快照的服务端 Gauge。

    多 dp_rank 部署按 dp_rank 配对 spec_accept_length:
    accept_length 经过任何投机批次必然 ≥ 1,length=0 的 rank 视为空闲,
    其 0 值 rate 不参与平均;无法配对时退回全部序列算术平均。
    值 ≤ 1 视为 0-1 比率换算百分数,> 1 视为已是百分数。
    """
    if not after or _SGLANG_SPEC_ACCEPT_RATE_KEY not in after:
        return ""
    rates = _rank_values(after, _SGLANG_SPEC_ACCEPT_RATE_KEY)
    lengths = _rank_values(after, _SGLANG_SPEC_ACCEPT_LENGTH_KEY)
    active = {r: v for r, v in rates.items() if lengths.get(r, 1) > 0}
    values = list((active or rates).values())
    mean = sum(values) / len(values)
    if 0 < mean <= 1:
        mean *= 100
    return round(mean, 2)


def _compute_sglang_rates(before: dict, after: dict):
    return _sglang_cache_hit_rate(before, after), _sglang_spec_accept_rate(after)


def compute_metrics_rates(before: dict, after: dict):
    """用两次 /metrics 快照计算 prefix cache 命中率与投机采样接受率(百分数)。

    按指标前缀自动识别后端:
    - vLLM: hits/queries 与 spec accepted/draft 计数器差值
    - SGLang: cached_tokens_total/prompt_tokens_total 计数器差值(token 级命中率);
      spec_accept_rate 取测试后 Gauge 快照值
    快照缺失、指标不存在或分母为 0 时对应值为空串(表示不可用)。
    """
    if not after:
        return "", ""
    if _detect_backend(after) == "sglang":
        return _compute_sglang_rates(before, after)
    return _compute_vllm_rates(before, after)