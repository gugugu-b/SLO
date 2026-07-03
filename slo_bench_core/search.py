"""自适应并发搜索 - 三阶段策略:大步长探索 → 小步长细化 → 二分定位。"""

import logging
import math
from typing import Tuple

from .benchmark import check_and_run_benchmark, run_benchmark_with_retry_and_metrics
from .config import (
    ENABLE_FINAL_CONFIRMATION,
    MAX_CONCURRENCY_LIMIT,
    SAFE_MARGIN,
    SEARCH_PARAMS,
    TTFT_LABEL,
    TPOT_LABEL,
)


def _is_within_safe_boundary(ttft: float, tpot: float, ttft_max: int, tpot_max: int) -> bool:
    """TTFT 和 TPOT 是否都在 (1+SAFE_MARGIN) 倍阈值内。"""
    return ttft <= ttft_max * (1 + SAFE_MARGIN) and tpot <= tpot_max * (1 + SAFE_MARGIN)


def _compute_margin(ttft: float, tpot: float, ttft_max: int, tpot_max: int) -> float:
    """性能余量 = min(ttft_max/ttft, tpot_max/tpot),失败时退到 10x。"""
    ttft_m = ttft_max / ttft if ttft > 0 else 10
    tpot_m = tpot_max / tpot if tpot > 0 else 10
    return min(ttft_m, tpot_m)


def _append_history(history_points: list, concurrency: int, ttft: float, tpot: float,
                    ttft_max: int, tpot_max: int, max_len: int = 10):
    """记录一次测试到历史点,超过 max_len 时弹出最老的点。"""
    margin = _compute_margin(ttft, tpot, ttft_max, tpot_max)
    history_points.append((concurrency, ttft, tpot, margin))
    if len(history_points) > max_len:
        history_points.pop(0)


def _lowest_valid_history_point(history_points: list, ttft_max: int, tpot_max: int) -> int:
    """从历史点中倒序找最近一个 TTFT/TPOT 都满足安全边界的并发值。"""
    for c, ttft, tpot, _ in reversed(history_points):
        if _is_within_safe_boundary(ttft, tpot, ttft_max, tpot_max):
            return c
    return 1


def predict_tpot_critical_point(history_points: list, tpot_max: int):
    """基于最近两个历史点的 TPOT 梯度,预测 TPOT 达到目标值时的临界并发数。"""
    if len(history_points) < 2:
        return None
    (c1, _, tpot1, _) = history_points[-2]
    (c2, _, tpot2, _) = history_points[-1]
    if c2 == c1:
        return None
    gradient = (tpot2 - tpot1) / (c2 - c1)
    target = tpot_max
    tolerance = tpot_max * SAFE_MARGIN
    if gradient > 0:
        critical = c2 + (target - tpot2) / gradient
    else:
        critical = float('inf')
    logging.info(
        f"TPOT梯度预测: 梯度={gradient:.2f}ms/并发, 当前TPOT={tpot2}ms, "
        f"目标TPOT={target}ms(±{tolerance:.1f}), 预测并发={critical:.0f}"
    )
    return critical


def _force_binary_on_cap(input_len, output_len, best_concurrency, history_points,
                         ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
                         cached_results, reason: str):
    """步长触达上限:在 [lowest_valid, best_concurrency] 内二分并返回。"""
    low = _lowest_valid_history_point(history_points, ttft_max, tpot_max)
    high = best_concurrency
    logging.warning(f"{reason}({best_concurrency})，在[{low}, {high}]内强制二分")
    return binary_search_concurrency(
        input_len, output_len, low, high,
        ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
        cached_results,
    )


def _binary_search_and_return(input_len, output_len, low, high,
                              ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
                              cached_results, reason: str):
    """在 [low, high] 内二分并返回,reason 仅作日志。"""
    logging.info(reason)
    return binary_search_concurrency(
        input_len, output_len, low, high,
        ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
        cached_results,
    )


def _run_and_check_cap(input_len, output_len, best_concurrency, test_concurrency,
                       ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
                       cached_results, history_points, reason_prefix: str):
    """执行一次测试,处理失败 / TPOT 超限 / TTFT 超限 / 通过四种分支。

    返回 (ttft, tpot, metrics, best_concurrency, best_ttft, best_tpot, done, result)
    - done=True 时 result 为最终返回元组 (ttft, tpot, best_concurrency, cached_results)
    - done=False 时需要调用方继续循环,result 为 None
    """
    ttft, tpot, metrics = check_and_run_benchmark(
        input_len, output_len, test_concurrency, ttft_max, tpot_max,
        vllm_bench_result_file_name, max_results_file_name, cached_results,
    )

    if ttft == -1 or tpot == -1:
        result = _binary_search_and_return(
            input_len, output_len, best_concurrency, test_concurrency,
            ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
            cached_results, f"{reason_prefix}服务不可用，在[{best_concurrency}, {test_concurrency}]内二分",
        )
        return ttft, tpot, metrics, best_concurrency, None, None, True, result

    tpot_upper = tpot_max * (1 + SAFE_MARGIN)
    if tpot > tpot_upper:
        low = _lowest_valid_history_point(history_points, ttft_max, tpot_max)
        result = _binary_search_and_return(
            input_len, output_len, low, test_concurrency,
            ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
            cached_results,
            f"{reason_prefix}TPOT超限({tpot}ms > {tpot_upper:.1f}ms)，在[{low}, {test_concurrency}]内二分",
        )
        return ttft, tpot, metrics, best_concurrency, None, None, True, result

    if ttft > ttft_max * (1 + SAFE_MARGIN):
        low = _lowest_valid_history_point(history_points, ttft_max, tpot_max)
        result = _binary_search_and_return(
            input_len, output_len, low, test_concurrency,
            ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
            cached_results,
            f"{reason_prefix}TPOT在范围内但TTFT超限，在[{low}, {test_concurrency}]内二分",
        )
        return ttft, tpot, metrics, best_concurrency, None, None, True, result

    # 通过:更新最优
    return ttft, tpot, metrics, test_concurrency, ttft, tpot, False, None


def binary_search_concurrency(input_len: int, output_len: int, low: int, high: int,
                              ttft_max: int, tpot_max: int,
                              vllm_bench_result_file_name: str, max_results_file_name: str,
                              cached_results: dict = None) -> Tuple[float, float, int, dict]:
    """二分查找,寻找同时满足 TTFT 和 TPOT 阈值的最大并发数。"""
    if cached_results is None:
        cached_results = {}

    best_concurrency, best_ttft, best_tpot = -1, float('inf'), float('inf')
    best_metrics = {}

    while low <= high:
        mid = (low + high) // 2
        ttft, tpot, metrics = check_and_run_benchmark(
            input_len, output_len, mid, ttft_max, tpot_max,
            vllm_bench_result_file_name, max_results_file_name, cached_results,
        )

        margin = _compute_margin(ttft, tpot, ttft_max, tpot_max)
        logging.info(f"精确搜索 - 并发: {mid}, TTFT: {ttft}ms, TPOT: {tpot}ms, 性能余量: {margin:.2f}x")

        if ttft == -1 or tpot == -1:
            logging.warning(f"输入长度: {input_len}, 输出长度: {output_len}, 并发数 {mid} 导致服务不可用")
            high = mid - 1
            continue

        ttft_tolerance = ttft_max * SAFE_MARGIN
        tpot_tolerance = tpot_max * SAFE_MARGIN
        in_tight = ttft <= ttft_max * (1 - SAFE_MARGIN) and tpot <= tpot_max * (1 - SAFE_MARGIN)
        in_safe = _is_within_safe_boundary(ttft, tpot, ttft_max, tpot_max)
        if in_tight or in_safe:
            best_concurrency, best_ttft, best_tpot = mid, ttft, tpot
            best_metrics = metrics
            if abs(ttft - ttft_max) <= ttft_tolerance and abs(tpot - tpot_max) <= tpot_tolerance:
                logging.info(
                    f"二分搜索找到: 并发={mid}, TTFT={ttft}ms (在{ttft_max}±{ttft_tolerance:.1f}内), "
                    f"TPOT={tpot}ms (在{tpot_max}±{tpot_tolerance:.1f}内)，接受结果并停止"
                )
                break
            low = mid + 1
        else:
            high = mid - 1

    if best_concurrency == -1:
        logging.error("未找到有效并发配置")
        return float('inf'), float('inf'), 0, {}

    if ENABLE_FINAL_CONFIRMATION:
        logging.info(f"对最优并发数 {best_concurrency} 进行最终确认测试")
        final_ttft, final_tpot, final_metrics = run_benchmark_with_retry_and_metrics(
            input_len, output_len, best_concurrency, ttft_max, tpot_max,
            vllm_bench_result_file_name, max_results_file_name,
        )
        cache_key = (input_len, output_len, best_concurrency)
        cached_results[cache_key] = (final_ttft, final_tpot, final_metrics)

        if final_ttft != -1 and final_tpot != -1 and _is_within_safe_boundary(final_ttft, final_tpot, ttft_max, tpot_max):
            current_margin = _compute_margin(best_ttft, best_tpot, ttft_max, tpot_max)
            final_margin = _compute_margin(final_ttft, final_tpot, ttft_max, tpot_max)
            if abs(final_margin - 1) < abs(current_margin - 1):
                best_ttft, best_tpot, best_metrics = final_ttft, final_tpot, final_metrics
                logging.info(
                    f"最终确认测试通过，且结果更接近阈值: {TTFT_LABEL}={best_ttft}ms, "
                    f"{TPOT_LABEL}={best_tpot}ms, 性能余量: {final_margin:.2f}x"
                )
            else:
                logging.info(
                    f"最终确认测试通过，但当前结果更接近阈值: {TTFT_LABEL}={best_ttft}ms, "
                    f"{TPOT_LABEL}={best_tpot}ms, 性能余量: {current_margin:.2f}x"
                )
        else:
            logging.warning("最终确认测试失败，使用之前的结果")
    else:
        logging.info("跳过最终确认测试，使用当前最优结果")

    # 额外测试 best-1 和 best+1 作为参考数据点
    for delta in [-1, 1]:
        neighbor_c = best_concurrency + delta
        if neighbor_c < 1:
            continue
        logging.info(f"最终确认测试 - 额外测试相邻并发: {neighbor_c}")
        neighbor_ttft, neighbor_tpot, neighbor_metrics = run_benchmark_with_retry_and_metrics(
            input_len, output_len, neighbor_c, ttft_max, tpot_max,
            vllm_bench_result_file_name, max_results_file_name,
        )
        cache_key = (input_len, output_len, neighbor_c)
        cached_results[cache_key] = (neighbor_ttft, neighbor_tpot, neighbor_metrics)

    req_throughput = best_metrics.get('req_throughput', 0)
    total_token_throughput = best_metrics.get('total_token_throughput', 0)
    logging.info(
        f"输入长度: {input_len}, 输出长度: {output_len}, 最优并发数: {best_concurrency}, "
        f"{TTFT_LABEL}: {best_ttft}ms, {TPOT_LABEL}: {best_tpot}ms, "
        f"请求吞吐量: {req_throughput} req/s, 总token吞吐量: {total_token_throughput} token/s"
    )
    return best_ttft, best_tpot, best_concurrency, cached_results


def _find_valid_starting_point(input_len, output_len, concurrences_low,
                               ttft_max, tpot_max,
                               vllm_bench_result_file_name, max_results_file_name, cached_results):
    """探测初始并发;若越界则向下折半,直到找到满足安全边界的起点。

    返回 (best_concurrency, best_ttft, best_tpot, history_points, found)
    """
    concurrency = concurrences_low
    best_concurrency = concurrency

    cache_key = (input_len, output_len, concurrency)
    if cache_key in cached_results:
        ttft, tpot, metrics = cached_results[cache_key]
        if ttft == -1 or tpot == -1 or not _is_within_safe_boundary(ttft, tpot, ttft_max, tpot_max):
            ttft, tpot, metrics = run_benchmark_with_retry_and_metrics(
                input_len, output_len, concurrency, ttft_max, tpot_max,
                vllm_bench_result_file_name, max_results_file_name,
            )
            cached_results[cache_key] = (ttft, tpot, metrics)
    else:
        ttft, tpot, metrics = run_benchmark_with_retry_and_metrics(
            input_len, output_len, concurrency, ttft_max, tpot_max,
            vllm_bench_result_file_name, max_results_file_name,
        )
        cached_results[cache_key] = (ttft, tpot, metrics)

    best_ttft, best_tpot = ttft, tpot
    margin = _compute_margin(best_ttft, best_tpot, ttft_max, tpot_max)
    history_points = [(best_concurrency, best_ttft, best_tpot, margin)]

    if _is_within_safe_boundary(best_ttft, best_tpot, ttft_max, tpot_max):
        return best_concurrency, best_ttft, best_tpot, history_points, True

    logging.warning(f"初始并发 {concurrency} 超出阈值，向下浮动查找合适的起始点")
    while concurrency > 1:
        concurrency = max(1, concurrency // 2)
        ttft, tpot, _ = check_and_run_benchmark(
            input_len, output_len, concurrency, ttft_max, tpot_max,
            vllm_bench_result_file_name, max_results_file_name, cached_results,
        )
        if _is_within_safe_boundary(ttft, tpot, ttft_max, tpot_max):
            best_concurrency, best_ttft, best_tpot = concurrency, ttft, tpot
            margin = _compute_margin(ttft, tpot, ttft_max, tpot_max)
            history_points.append((best_concurrency, best_ttft, best_tpot, margin))
            logging.info(f"向下浮动找到合适起始点: {concurrency}")
            return best_concurrency, best_ttft, best_tpot, history_points, True
    logging.error("无法找到合适的起始并发数")
    return 0, float('inf'), float('inf'), history_points, False


def adaptive_concurrency_search(input_len: int, output_len: int,
                                concurrences_low: int, concurrences_high: int,
                                ttft_max: int, tpot_max: int,
                                vllm_bench_result_file_name: str, max_results_file_name: str) -> Tuple[float, float, int, dict]:
    """自适应并发搜索 - 三阶段:大步长探索 → 小步长细化 → 二分定位。"""
    cached_results = {}

    best_concurrency, best_ttft, best_tpot, history_points, found = _find_valid_starting_point(
        input_len, output_len, concurrences_low, ttft_max, tpot_max,
        vllm_bench_result_file_name, max_results_file_name, cached_results,
    )
    if not found:
        return float('inf'), float('inf'), 0, cached_results

    high_limit_checked = False
    stuck_count = 0
    last_test_concurrency = -1

    tpot_target = tpot_max
    tpot_upper = tpot_target * (1 + SAFE_MARGIN)
    ttft_target = ttft_max

    while True:
        margin = _compute_margin(best_ttft, best_tpot, ttft_max, tpot_max)
        logging.info(f"当前并发: {best_concurrency}, TTFT: {best_ttft}ms, TPOT: {best_tpot}ms, 性能余量: {margin:.2f}x")

        # 防重复检测:连续两次相同并发则跳出
        if len(history_points) >= 2 and history_points[-1][0] == best_concurrency == history_points[-2][0]:
            logging.warning(
                f"检测到重复测试: 并发={best_concurrency}，TTFT={best_ttft}ms，TPOT={best_tpot}ms，使用当前结果"
            )
            return best_ttft, best_tpot, best_concurrency, cached_results

        tpot_gap = abs(best_tpot - tpot_target)
        ttft_gap = abs(best_ttft - ttft_target)
        ttft_tolerance = ttft_max * SAFE_MARGIN
        tpot_tolerance = tpot_max * SAFE_MARGIN

        # 策略1:两者都在容差范围内,直接接受
        if ttft_gap <= ttft_tolerance and tpot_gap <= tpot_tolerance:
            logging.info(
                f"TTFT={best_ttft}ms (在[{ttft_target - ttft_tolerance:.1f}, {ttft_target + ttft_tolerance:.1f}]内), "
                f"TPOT={best_tpot}ms (在[{tpot_target - tpot_tolerance:.1f}, {tpot_target + tpot_tolerance:.1f}]内)，接受为最优"
            )
            return best_ttft, best_tpot, best_concurrency, cached_results

        # 策略2/3:TPOT差距不大时用小步长精细搜索
        if tpot_gap <= SEARCH_PARAMS["TPOT_GAP_LARGE"]:
            if len(history_points) >= 2:
                predicted = predict_tpot_critical_point(history_points, tpot_max)
                if predicted and predicted > best_concurrency:
                    gap = predicted - best_concurrency
                    step = max(int(gap * SEARCH_PARAMS["SMALL_STEP_RATIO"]), 10)
                    test_concurrency = min(best_concurrency + step, int(predicted), MAX_CONCURRENCY_LIMIT)
                else:
                    predicted = None
                    test_concurrency = min(best_concurrency + 20, MAX_CONCURRENCY_LIMIT)

                if test_concurrency == best_concurrency:
                    return _force_binary_on_cap(
                        input_len, output_len, best_concurrency, history_points,
                        ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
                        cached_results, "小步长搜索触达上限",
                    )

                label = f"TPOT差距中等({tpot_gap:.1f}ms)，小步长精细搜索" if predicted else "无法预测，小步长搜索"
                logging.info(f"{label}: {best_concurrency} -> {test_concurrency}")

                ttft, tpot, metrics, new_best_c, new_best_ttft, new_best_tpot, done, result = _run_and_check_cap(
                    input_len, output_len, best_concurrency, test_concurrency,
                    ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
                    cached_results, history_points, "",
                )
                if done:
                    return result
                best_concurrency, best_ttft, best_tpot = new_best_c, new_best_ttft, new_best_tpot
                _append_history(history_points, best_concurrency, best_ttft, best_tpot, ttft_max, tpot_max)
                continue

            # 历史点不足,落到下方大步长逻辑
        else:
            # 大步长探索:TPOT差距大
            if len(history_points) >= 2:
                predicted = predict_tpot_critical_point(history_points, tpot_max)
                if predicted and predicted > best_concurrency:
                    if margin < SEARCH_PARAMS["MARGIN_LOW"]:
                        # TTFT 已是瓶颈,小步长
                        step = max(int(best_concurrency * SEARCH_PARAMS["SMALL_STEP_RATIO"]), 10)
                        test_concurrency = min(best_concurrency + step, MAX_CONCURRENCY_LIMIT)
                        logging.info(
                            f"TPOT差距大({tpot_gap:.1f}ms)但TTFT margin只有{margin:.2f}x，TTFT是瓶颈，用小步长: "
                            f"{best_concurrency} -> {test_concurrency}"
                        )
                    else:
                        if not isinstance(predicted, (int, float)) or not math.isfinite(predicted):
                            step = SEARCH_PARAMS["STEP_FALLBACK"]
                        else:
                            step = max(int(predicted - best_concurrency) + SEARCH_PARAMS["LARGE_STEP_OFFSET"], SEARCH_PARAMS["LARGE_STEP_OFFSET"])
                        test_concurrency = min(best_concurrency + step, MAX_CONCURRENCY_LIMIT)
                        logging.info(
                            f"TPOT差距大({tpot_gap:.1f}ms)，大步长跳到 {test_concurrency} (预测临界={predicted:.0f})"
                        )

                    if test_concurrency == best_concurrency:
                        return _force_binary_on_cap(
                            input_len, output_len, best_concurrency, history_points,
                            ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
                            cached_results, "TPOT差距大步长触达上限",
                        )

                    ttft, tpot, metrics = check_and_run_benchmark(
                        input_len, output_len, test_concurrency, ttft_max, tpot_max,
                        vllm_bench_result_file_name, max_results_file_name, cached_results,
                    )
                    if ttft == -1 or tpot == -1:
                        # 服务不可用,缩小步长重试
                        fallback_c = best_concurrency + 20
                        if isinstance(predicted, (int, float)) and math.isfinite(predicted):
                            test_concurrency = max(fallback_c, int(predicted))
                        else:
                            test_concurrency = fallback_c
                        ttft, tpot, metrics = check_and_run_benchmark(
                            input_len, output_len, test_concurrency, ttft_max, tpot_max,
                            vllm_bench_result_file_name, max_results_file_name, cached_results,
                        )
                    if ttft == -1 or tpot == -1:
                        return _binary_search_and_return(
                            input_len, output_len, best_concurrency, test_concurrency,
                            ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
                            cached_results,
                            f"大步长测试失败，在[{best_concurrency}, {test_concurrency}]内二分",
                        )

                    _append_history(history_points, test_concurrency, ttft, tpot, ttft_max, tpot_max)

                    if tpot > tpot_upper:
                        low = _lowest_valid_history_point(history_points, ttft_max, tpot_max)
                        return _binary_search_and_return(
                            input_len, output_len, low, test_concurrency,
                            ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
                            cached_results,
                            f"找到上界: 并发={test_concurrency}, TPOT={tpot}ms > {tpot_upper:.1f}ms，在[{low}, {test_concurrency}]内二分",
                        )
                    if ttft > ttft_max * (1 + SAFE_MARGIN):
                        low = _lowest_valid_history_point(history_points, ttft_max, tpot_max)
                        return _binary_search_and_return(
                            input_len, output_len, low, test_concurrency,
                            ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
                            cached_results,
                            f"TPOT在范围内但TTFT超限，在[{low}, {test_concurrency}]内二分",
                        )

                    best_concurrency, best_ttft, best_tpot = test_concurrency, ttft, tpot
                    logging.info(f"TPOT={tpot}ms 仍在范围内，继续大步跳")
                    continue
                else:
                    # 无法预测,基于 TPOT 剩余空间算步长
                    tpot_remaining = tpot_target - best_tpot
                    if margin < SEARCH_PARAMS["MARGIN_LOW"]:
                        step = max(int(best_concurrency * SEARCH_PARAMS["SMALL_STEP_RATIO"]), 10)
                        logging.info(
                            f"无法预测且TTFT margin只有{margin:.2f}x，TTFT是瓶颈，用小步长: "
                            f"{best_concurrency} -> {best_concurrency + step}"
                        )
                    else:
                        if tpot_remaining > SEARCH_PARAMS["TPOT_REMAINING_HIGH"]:
                            step = best_concurrency
                        elif tpot_remaining > SEARCH_PARAMS["TPOT_REMAINING_LOW"]:
                            step = best_concurrency // 2
                        else:
                            step = SEARCH_PARAMS["STEP_FALLBACK"]
                    test_concurrency = min(best_concurrency + step, MAX_CONCURRENCY_LIMIT)
                    if test_concurrency == best_concurrency:
                        return _force_binary_on_cap(
                            input_len, output_len, best_concurrency, history_points,
                            ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
                            cached_results, "大步长探索触达上限",
                        )
                    logging.info(f"无法预测，基于TPOT差距={tpot_remaining:.1f}ms，步长={step}，跳到 {test_concurrency}")

                    ttft, tpot, metrics, new_best_c, new_best_ttft, new_best_tpot, done, result = _run_and_check_cap(
                        input_len, output_len, best_concurrency, test_concurrency,
                        ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
                        cached_results, history_points, "",
                    )
                    if done:
                        return result
                    best_concurrency, best_ttft, best_tpot = new_best_c, new_best_ttft, new_best_tpot
                    _append_history(history_points, best_concurrency, best_ttft, best_tpot, ttft_max, tpot_max)
                    continue
            # 历史点不足或落到此处:用动态步长继续探索

        # 动态步长探索(历史点不足或大步长分支未 continue)
        if len(history_points) >= 2:
            predicted = predict_tpot_critical_point(history_points, tpot_max)
            if predicted and predicted > best_concurrency and isinstance(predicted, (int, float)) and math.isfinite(predicted):
                gap = predicted - best_concurrency
                ratio = 0.5 if margin > 3 else SEARCH_PARAMS["GOLDEN_RATIO"]
                step = int(gap * ratio)
                step = max(10, min(step, SEARCH_PARAMS["STEP_UPPER_BOUND"]))
            else:
                # 分级阶梯(内部参数保留硬编码:每级 margin → 倍数 / 基数 / 上限)
                # margin 越大越激进;边界由 STEP_UPPER_BOUND 控制全局上限
                if margin > 10:
                    step = max(50, min(int(best_concurrency * 4), SEARCH_PARAMS["STEP_UPPER_BOUND"]))
                elif margin > 5:
                    step = max(30, min(int(best_concurrency * 3), 150))
                elif margin > 2:
                    step = max(10, min(int(best_concurrency * 1.5), 100))
                else:
                    step = max(SEARCH_PARAMS["STEP_LOWER_BOUND"], min(int(best_concurrency * 0.5), 50))
        else:
            if margin > 5:
                step = int(best_concurrency * 3)
            else:
                step = int(best_concurrency * 1.5)
            step = max(20, min(step, SEARCH_PARAMS["STEP_UPPER_BOUND"]))

        new_concurrency = best_concurrency + step

        if new_concurrency > concurrences_high and not high_limit_checked:
            logging.info(f"超过初始区间上限 {concurrences_high}，验证上限")
            high_limit_checked = True
            ttft, tpot, metrics = check_and_run_benchmark(
                input_len, output_len, concurrences_high, ttft_max, tpot_max,
                vllm_bench_result_file_name, max_results_file_name, cached_results,
            )
            if _is_within_safe_boundary(ttft, tpot, ttft_max, tpot_max):
                best_concurrency, best_ttft, best_tpot = concurrences_high, ttft, tpot
                new_concurrency = min(best_concurrency + max(1, int(best_concurrency * 0.2)), MAX_CONCURRENCY_LIMIT)
                logging.info(f"初始区间上限可用，继续向上探索到 {new_concurrency}")
            else:
                return _binary_search_and_return(
                    input_len, output_len, concurrences_low, concurrences_high,
                    ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
                    cached_results, "初始区间上限不可用，在初始区间内精确搜索",
                )

        if new_concurrency > MAX_CONCURRENCY_LIMIT:
            logging.warning(f"已达到最大并发上限 {MAX_CONCURRENCY_LIMIT}")
            return best_ttft, best_tpot, best_concurrency, cached_results

        logging.info(f"大步长探索: 从 {best_concurrency} 增加到 {new_concurrency}")
        ttft, tpot, metrics = check_and_run_benchmark(
            input_len, output_len, new_concurrency, ttft_max, tpot_max,
            vllm_bench_result_file_name, max_results_file_name, cached_results,
        )

        if new_concurrency == last_test_concurrency:
            stuck_count += 1
            logging.warning(f"检测到重复测试: 并发={new_concurrency}，stuck_count={stuck_count}")
            if stuck_count >= SEARCH_PARAMS["STUCK_THRESHOLD"]:
                logging.warning(f"连续{stuck_count}次test_concurrency无变化，强制二分搜索")
                return _binary_search_and_return(
                    input_len, output_len, max(1, best_concurrency - step), best_concurrency + step,
                    ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
                    cached_results, f"连续{stuck_count}次重复，强制二分",
                )
        else:
            stuck_count = 0
        last_test_concurrency = new_concurrency

        if ttft == -1 or tpot == -1:
            step = int(step * 0.5)
            if step < SEARCH_PARAMS["STEP_LOWER_BOUND"]:
                logging.warning(f"步长已减小到{step}，无法继续探索")
                return best_ttft, best_tpot, best_concurrency, cached_results
            new_concurrency = best_concurrency + step
            logging.info(f"服务不可用，减小步长到 {step}，尝试 {new_concurrency}")
            ttft, tpot, metrics = check_and_run_benchmark(
                input_len, output_len, new_concurrency, ttft_max, tpot_max,
                vllm_bench_result_file_name, max_results_file_name, cached_results,
            )

        if ttft == -1 or tpot == -1:
            continue

        _append_history(history_points, new_concurrency, ttft, tpot, ttft_max, tpot_max)

        if _is_within_safe_boundary(ttft, tpot, ttft_max, tpot_max):
            best_concurrency, best_ttft, best_tpot = new_concurrency, ttft, tpot
        elif ttft <= ttft_max * (1 + SAFE_MARGIN) or tpot <= tpot_max * (1 + SAFE_MARGIN):
            # 只有一项超边界,在 [best_concurrency, new_concurrency] 内二分
            return _binary_search_and_return(
                input_len, output_len, best_concurrency, new_concurrency,
                ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
                cached_results, f"超过安全边界，在[{best_concurrency}, {new_concurrency}]内精确搜索",
            )
        else:
            # 两者都超阈值,找上一个有效点做二分
            if len(history_points) >= 2:
                valid_concurrency = None
                for i in range(len(history_points) - 1, -1, -1):
                    if history_points[i][3] >= 1:
                        valid_concurrency = history_points[i][0]
                        break
                if valid_concurrency is not None:
                    return _binary_search_and_return(
                        input_len, output_len, valid_concurrency, new_concurrency,
                        ttft_max, tpot_max, vllm_bench_result_file_name, max_results_file_name,
                        cached_results,
                        f"超过阈值(margin={margin:.2f}x)，在上个有效点{valid_concurrency}和{new_concurrency}间二分",
                    )
            # 没有有效历史点,降低并发重试
            step = max(10, step // 2)
            new_concurrency = max(1, new_concurrency - step)
            logging.info(f"无有效历史点，降低并发重试: {new_concurrency}")
            ttft, tpot, metrics = check_and_run_benchmark(
                input_len, output_len, new_concurrency, ttft_max, tpot_max,
                vllm_bench_result_file_name, max_results_file_name, cached_results,
            )
            if ttft == -1 or tpot == -1:
                continue
            continue
