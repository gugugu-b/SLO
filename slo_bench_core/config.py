"""配置常量 - 测试参数、模型配置、搜索策略、CSV 表头、正则模式。"""

import time

# ============================================================
# 版本号
# ============================================================
VERSION = "v1.3"

# 测试用例:(input_len, output_len, 初始并发low, 初始并发high, TTFT阈值, TPOT阈值)
IO = [
    (8192, 1024, 2, 128, 3000, 100),
    (16384, 1024, 2, 128, 3000, 100),
    (32768, 1024, 2, 128, 3000, 100),
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
SERVED_MODEL_NAME = "DeepSeek-V4-Flash-Channel-FP8-w8a8"
MODEL = "/data/model/DeepSeek-V4-Flash-Channel-FP8-w8a8"
DATASET_NAME = "random"
IGNORE_EOS = "--ignore-eos"
# 传给 --num-prompts 的请求数 = 并发数 × 这个倍数(默认 4,即每个并发跑 4 个请求再汇总体)
NUM_PROMPTS_PER_CONCURRENCY = 4

# ============================================================
# 前缀重复测试开关(默认关闭,启用后 _build_bench_cmd 切换到 prefix_repetition 命令)
# ============================================================
ENABLE_PREFIX_REPETITION = False
PREFIX_REPETITION_DATASET_NAME = "prefix_repetition"
PREFIX_REPETITION_PC_RATIO = 0.9
PREFIX_REPETITION_NUM_PREFIXES = 1

# 优化参数
MAX_RETRIES = 2               # 失败重试次数
BENCH_MAX_ERRORS = MAX_RETRIES + 1  # 子进程连续失败上限,超出则抛 BenchmarkError
MAX_CONCURRENCY_LIMIT = 128    # 并发搜索上限
ENABLE_FINAL_CONFIRMATION = True  # 最优并发做最终确认测试
ENABLE_DOUBLE_RUN = True      # 第一次预热,第二次作为正式结果

# 搜索策略参数
SEARCH_PARAMS = {
    # === 阈值(策略切换) ===
    "TPOT_GAP_LARGE": 30,        # 小步长切换线: tpot_gap ≤ 此值走"小步长精细搜索"
    "MARGIN_LOW": 1.5,           # TTFT 瓶颈判定: margin < 此值视为 TTFT 已接近阈值
    "TPOT_REMAINING_HIGH": 50,   # TPOT 剩余空间高阈值: tpot_remaining > 此值用翻倍
    "TPOT_REMAINING_LOW": 20,    # TPOT 剩余空间低阈值: 高/低之间减半,更低用 STEP_FALLBACK

    # === 步长边界 ===
    "STEP_UPPER_BOUND": 200,     # 步长硬上限(全局)
    "STEP_LOWER_BOUND": 5,       # 步长硬下限(全局)
    "STEP_FALLBACK": 100,        # 兜底固定步长(预测/TPOT 剩余空间不可用时)

    # === 步长比例 ===
    "GOLDEN_RATIO": 0.382,       # 黄金分割(动态步长探索,余量低时)
    "SMALL_STEP_RATIO": 0.3,     # 小步长比例(预测步长 / TTFT 瓶颈分支)

    # === 大步长偏移 ===
    "LARGE_STEP_OFFSET": 50,     # 预测临界点 + 此偏移(大步长分支)

    # === 防卡死 ===
    "STUCK_THRESHOLD": 3,        # 连续相同并发次数,达到后强制二分
}

# 运行时参数
SUBPROCESS_TIMEOUT = 3600       # vllm bench serve 子进程超时(秒)
POST_TEST_SLEEP = 2             # 单次测试后等待(秒)
RETRY_SLEEP = 2                 # 失败重试间隔(秒)

# perf_log 相关
PERF_LOG_DIR = "./slo_bench/perf_log"
PERF_MODEL_NAME = "DeepSeek-V4-Flash-Channel-FP8-w8a8"  # 与 SERVED_MODEL_NAME 一致

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
