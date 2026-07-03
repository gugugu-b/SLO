"""配置常量 - 测试参数、模型配置、搜索策略、CSV 表头、正则模式。"""

import time

# 测试用例:(input_len, output_len, 初始并发low, 初始并发high, TTFT阈值, TPOT阈值)
IO = [
    (1024, 1024, 2, 256, 3000, 100),
    (2048, 1024, 2, 256, 3000, 100),
    (4096, 1024, 2, 256, 3000, 100),
    (8192, 1024, 2, 256, 3000, 100),
]


# 脚本启动时间戳(模块加载时计算一次,全包共享)
SCRIPT_START_TIME = time.strftime("%H%M%S")
SCRIPT_START_DATE = time.strftime("%Y%m%d")

# TTFT/TPOT 标签:可选 "Mean TTFT" / "Median TTFT" / "P99 TTFT" 等
TTFT_LABEL = "Mean TTFT"
TPOT_LABEL = "Mean TPOT"
SAFE_MARGIN = 0.03  # 安全余量

# vllm bench serve 固定参数
HOST = "0.0.0.0"
PORT = "30000"
BACKEND = "vllm"
SERVED_MODEL_NAME = "Qwen3.6-35B-A3B"
MODEL = "/data/model/Qwen3.6-35B-A3B"
DATASET_NAME = "random"
IGNORE_EOS = "--ignore-eos"

# 优化参数
MAX_RETRIES = 2               # 失败重试次数
BENCH_MAX_ERRORS = MAX_RETRIES + 1  # 子进程连续失败上限,超出则抛 BenchmarkError
MAX_CONCURRENCY_LIMIT = 256    # 并发搜索上限
ENABLE_FINAL_CONFIRMATION = True  # 最优并发做最终确认测试
ENABLE_DOUBLE_RUN = True      # 第一次预热,第二次作为正式结果

# 搜索策略参数
SEARCH_PARAMS = {
    "TPOT_GAP_LARGE": 30,        # 大步长: TPOT 差距 > 此值
    "TPOT_GAP_MEDIUM": 10,       # 小步长: TPOT 差距 > 此值
    "STEP_DBL": "double",        # tpot_gap > 50 时翻倍
    "STEP_HALF": "half",         # tpot_gap > 20 时减半
    "STEP_FALLBACK": 100,        # 其它情况固定步长
    "STEP_MIN": 5,
    "STEP_MAX": 200,
    "MARGIN_VERY_HIGH": 10,
    "MARGIN_HIGH": 5,
    "MARGIN_MEDIUM": 2,
    "MARGIN_LOW": 1.5,           # TTFT 成瓶颈的阈值
    "GOLDEN_RATIO": 0.382,
    "SMALL_STEP_RATIO": 0.3,
    "LARGE_STEP_OFFSET": 50,
    "STUCK_THRESHOLD": 3,
    "STEP_HALVE_MIN": 10,
}

# 运行时参数
SUBPROCESS_TIMEOUT = 3600       # vllm bench serve 子进程超时(秒)
POST_TEST_SLEEP = 2             # 单次测试后等待(秒)
RETRY_SLEEP = 2                 # 失败重试间隔(秒)

# perf_log 相关
PERF_LOG_DIR = "./slo_bench/perf_log"
PERF_MODEL_NAME = "Qwen3.6-35B-A3B"  # 与 SERVED_MODEL_NAME 一致

# CSV 表头
VLLM_BENCH_HEADERS = [
    "input_len", "output_len", "concurrency", "successful_requests", "benchmark_duration",
    "total_input_tokens", "total_generated_tokens", "req_throughput", "output_token_throughput", "total_token_throughput",
    "mean_ttft", "median_ttft", "p99_ttft",
    "mean_tpot", "median_tpot", "p99_tpot",
    "mean_itl", "median_itl", "p99_itl",
]

MAX_RESULTS_HEADERS = [
    "input_len", "output_len", "concurrency", "ttft", "tpot", "is_optimal",
]

# 指标正则:每个指标一个独立命名组,内层再命名一个数值捕获组
METRIC_PATTERNS = {
    'successful_requests': r"[Ss]uccessful\s+[Rr]equests?:\s*(\d+)",
    'benchmark_duration': r"[Bb]enchmark\s+[Dd]uration\s*\(?s\)?:\s*(\d+(?:\.\d+)?)",
    'total_input_tokens': r"[Tt]otal\s+[Ii]nput\s+[Tt]okens?:\s*(\d+)",
    'total_generated_tokens': r"[Tt]otal\s+[Gg]enerated\s+[Tt]okens?:\s*(\d+)",
    'req_throughput': r"[Rr]equest\s+[Tt]hroughput\s*\(req/s\)?:\s*(\d+(?:\.\d+)?)",
    'output_token_throughput': r"[Oo]utput\s+[Tt]oken\s+[Tt]hroughput\s*\(tok/s\)?:\s*(\d+(?:\.\d+)?)",
    'total_token_throughput': r"[Tt]otal\s+[Tt]oken\s+[Tt]hroughput\s*\(tok/s\)?:\s*(\d+(?:\.\d+)?)",
    'mean_ttft': r"[Mm]ean\s+TTFT\s*\(ms\)?:\s*(\d+(?:\.\d+)?)",
    'median_ttft': r"[Mm]edian\s+TTFT\s*\(ms\)?:\s*(\d+(?:\.\d+)?)",
    'p99_ttft': r"P99\s+TTFT\s*\(ms\)?:\s*(\d+(?:\.\d+)?)",
    'mean_tpot': r"[Mm]ean\s+TPOT\s*\(ms\)?:\s*(\d+(?:\.\d+)?)",
    'median_tpot': r"[Mm]edian\s+TPOT\s*\(ms\)?:\s*(\d+(?:\.\d+)?)",
    'p99_tpot': r"P99\s+TPOT\s*\(ms\)?:\s*(\d+(?:\.\d+)?)",
    'mean_itl': r"[Mm]ean\s+ITL\s*\(ms\)?:\s*(\d+(?:\.\d+)?)",
    'median_itl': r"[Mm]edian\s+ITL\s*\(ms\)?:\s*(\d+(?:\.\d+)?)",
    'p99_itl': r"P99\s+ITL\s*\(ms\)?:\s*(\d+(?:\.\d+)?)",
}

INT_METRIC_KEYS = frozenset({'successful_requests', 'total_input_tokens', 'total_generated_tokens'})

# TTFT/TPOT 标签 -> metrics 字典 key
TTFT_KEY_MAP = {
    "Mean TTFT": "mean_ttft",
    "Median TTFT": "median_ttft",
    "P99 TTFT": "p99_ttft",
}
TPOT_KEY_MAP = {
    "Mean TPOT": "mean_tpot",
    "Median TPOT": "median_tpot",
    "P99 TPOT": "p99_tpot",
}
