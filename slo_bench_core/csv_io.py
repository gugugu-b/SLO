"""CSV 输出 - 写入 vllm_bench_result / max_results / summary / best_metrics。"""

import csv
import logging
import os
from typing import List

from .config import SCRIPT_START_DATE


def get_base_filename(prefix: str, input_len: int, output_len: int, ttft_max: int, tpot_max: int) -> str:
    """生成包含测试参数的文件名(无时间戳,数据追加到同一文件)。"""
    return f"{prefix}-{input_len}x{output_len}-TTFT{ttft_max}-TPOT{tpot_max}.csv"


def write_to_csv(data: List, filename: str = "results.csv", headers: List = None,
                 input_len: int = None, output_len: int = None):
    """将一行 data 追加到 CSV。目录按日期 + 上下文组合自动生成。"""
    context_str = f"{input_len}x{output_len}" if input_len and output_len else "unknown"
    log_dir = os.path.join(
        os.getcwd(),
        "slo_bench",
        "slo_log",
        SCRIPT_START_DATE,
        f"context_{context_str}",
    )
    os.makedirs(log_dir, exist_ok=True)

    file_path = os.path.join(log_dir, filename)
    file_exists = os.path.isfile(file_path)
    try:
        with open(file_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists and headers:
                writer.writerow(headers)
            writer.writerow(data)
    except IOError as e:
        logging.error(f"写入文件失败: {e}")
