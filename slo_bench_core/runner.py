"""测试入口 - 遍历 IO 用例,调度自适应搜索,写汇总 CSV。"""

import csv
import glob
import logging
import os
import time

from .benchmark import reset_bench_error_counter
from .config import IO, PERF_LOG_DIR, PERF_MODEL_NAME, SCRIPT_START_DATE, SCRIPT_START_TIME, TTFT_LABEL, TPOT_LABEL, VERSION
from .csv_io import get_base_filename, write_to_csv
from .metrics import reset_warnings
from .search import adaptive_concurrency_search


_SUMMARY_HEADERS = ["input_len", "output_len", "ttft_threshold", "tpot_threshold", "best_concurrency", "ttft", "tpot"]
_BEST_METRICS_HEADERS = [
    "input_len", "output_len", "concurrency",
    "successful_requests", "benchmark_duration",
    "total_input_tokens", "total_generated_tokens",
    "req_throughput", "output_token_throughput", "total_token_throughput",
    "mean_ttft", "median_ttft", "p99_ttft",
    "mean_tpot", "median_tpot", "p99_tpot",
    "mean_itl", "median_itl", "p99_itl",
]


def _move_perf_logs_to_model_dir():
    """把 perf_log/il*.log 移动到 perf_log/<PERF_MODEL_NAME>/ 下。"""
    perf_model_dir = os.path.join(PERF_LOG_DIR, PERF_MODEL_NAME)
    os.makedirs(perf_model_dir, exist_ok=True)
    for file in glob.glob(f"{PERF_LOG_DIR}/il*.log"):
        dest = os.path.join(perf_model_dir, os.path.basename(file))
        os.rename(file, dest)
        logging.info(f"已将perf_log文件移动到: {dest}")


def _write_summary_csv(summary_results):
    summary_dir = os.path.join(os.getcwd(), "slo_bench", "slo_log", SCRIPT_START_DATE)
    os.makedirs(summary_dir, exist_ok=True)
    summary_file = os.path.join(summary_dir, f"summary_{SCRIPT_START_DATE}.csv")
    with open(summary_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(_SUMMARY_HEADERS)
        for row in summary_results:
            writer.writerow([row[h] for h in _SUMMARY_HEADERS])
    logging.info(f"汇总CSV已写入: {summary_file}")


def _write_best_metrics_csv(summary_results):
    best_metrics_dir = os.path.join(os.getcwd(), "slo_bench")
    os.makedirs(best_metrics_dir, exist_ok=True)
    best_metrics_file = os.path.join(
        best_metrics_dir, f"best_metrics_{SCRIPT_START_DATE}_{SCRIPT_START_TIME}.csv"
    )
    with open(best_metrics_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(_BEST_METRICS_HEADERS)
        for row in summary_results:
            metrics = row.get("metrics", {})
            writer.writerow([
                row["input_len"], row["output_len"], row["best_concurrency"],
                metrics.get('successful_requests', 0),
                metrics.get('benchmark_duration', 0),
                metrics.get('total_input_tokens', 0),
                metrics.get('total_generated_tokens', 0),
                metrics.get('req_throughput', 0),
                metrics.get('output_token_throughput', 0),
                metrics.get('total_token_throughput', 0),
                metrics.get('mean_ttft', 0),
                metrics.get('median_ttft', 0),
                metrics.get('p99_ttft', 0),
                metrics.get('mean_tpot', 0),
                metrics.get('median_tpot', 0),
                metrics.get('p99_tpot', 0),
                metrics.get('mean_itl', 0),
                metrics.get('median_itl', 0),
                metrics.get('p99_itl', 0),
            ])
    logging.info(f"最优指标CSV已写入: {best_metrics_file}")


def run_test_cases():
    """遍历 IO 测试用例,执行自适应搜索,写汇总 CSV。"""
    logging.info(f"[{VERSION}] 开始vllm_benchmark并发自动摸高测试")
    start_time = time.time()
    summary_results = []

    total = len(IO)
    for idx, (input_len, output_len, concurrences_low, concurrences_high, ttft_max, tpot_max) in enumerate(IO, 1):
        logging.info("=" * 60)
        logging.info(
            f"[用例 {idx}/{total}] il={input_len} ol={output_len}  "
            f"TTFT≤{ttft_max}ms TPOT≤{tpot_max}ms  "
            f"并发区间 {concurrences_low}-{concurrences_high}"
        )
        logging.info("=" * 60)
        test_start_time = time.time()

        # 每个用例重置错误计数与警告缓存
        reset_bench_error_counter()
        reset_warnings()

        vllm_bench_result_file_name = get_base_filename("vllm_bench_result", input_len, output_len, ttft_max, tpot_max)
        max_results_file_name = get_base_filename("max_results", input_len, output_len, ttft_max, tpot_max)

        ttft, tpot, best_concurrency, cached_results = adaptive_concurrency_search(
            input_len, output_len, concurrences_low, concurrences_high, ttft_max, tpot_max,
            vllm_bench_result_file_name, max_results_file_name,
        )

        best_cache_key = (input_len, output_len, best_concurrency)
        best_metrics = cached_results.get(best_cache_key, (None, None, {}))[2] if best_cache_key in cached_results else {}

        write_to_csv(
            [input_len, output_len, best_concurrency, ttft, tpot, 1],
            max_results_file_name,
            headers=["input_len", "output_len", "concurrency", "ttft", "tpot", "is_optimal"],
            input_len=input_len,
            output_len=output_len,
        )

        test_time = int(time.time() - test_start_time)
        logging.info(
            f"[用例 {idx}/{total}] 完成: 最优并发={best_concurrency}, "
            f"{TTFT_LABEL}={ttft}ms, {TPOT_LABEL}={tpot}ms, 耗时={test_time}秒"
        )

        summary_results.append({
            "input_len": input_len,
            "output_len": output_len,
            "ttft_threshold": ttft_max,
            "tpot_threshold": tpot_max,
            "best_concurrency": best_concurrency,
            "ttft": ttft,
            "tpot": tpot,
            "metrics": best_metrics,
        })

    total_time = int(time.time() - start_time)
    logging.info(f"测试结束，总用时: {total_time}秒")

    _move_perf_logs_to_model_dir()
    _write_summary_csv(summary_results)
    _write_best_metrics_csv(summary_results)
