"""vllm_benchmark 并发自动摸高测试 - 入口

基于设定 TTFT、TPOT 上限值,求临界最大并发数。
实际逻辑在 slo_bench_core 包内,本文件仅作为薄入口。
"""

import logging

from slo_bench_core import run_test_cases

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
    )
    run_test_cases()