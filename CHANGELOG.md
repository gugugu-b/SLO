# Changelog

所有版本通过 git tag(`v1.0`、`v1.1` …)发布,`git checkout <tag>` 看历史版本代码。

---

## [v1.0] - 2026-07-02

初始版本。

- 基础功能: 给定 TTFT/TPOT 阈值,通过自适应并发搜索自动找到临界最大并发数。
- 入口文件: `run.py`。
- 核心包: `slo_bench_core/`(`config` / `benchmark` / `search` / `runner` / `metrics` / `csv_io`)。
- 已知问题: 指标提取函数有 `_build_combined_metric_re` 的 `re.sub` bug,12 个指标提取失败(在 v1.1 修复)。
