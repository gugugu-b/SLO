# Changelog

所有版本通过 git tag(`v1.0`、`v1.1` …)发布,`git checkout <tag>` 看历史版本代码。

---

## [v1.2] - 2026-07-03

相对 v1.1 的变更。

### 改进
- **perf_log 文件命名格式升级**(`benchmark.py`): 从 `il{il}_ol{ol}_c{c}.log` 改为 `il{il}_ol{ol}_np{con}_mc{con}.log`,把"请求数 `np`"和"并发数 `mc`"作为文件名的两个维度(当前 1:1 都取 `concurrency`,将来可拆开使用)。

### 文档
- README"输出物"节补充文件名格式说明及 `np` / `mc` 两个维度的含义。

---

## [v1.1] - 2026-07-02

相对 v1.0 的变更。

### Bug 修复
- **指标提取 bug**(`config.py` + `metrics.py`): `_build_combined_metric_re` 函数用 `re.sub(r'\((?!\?)', ...)` 把正则里"第一个左括号"改成命名组,但区分不了"转义的字面括号 `\(`"和"真正的捕获组 `(`",导致 12 个指标(`req_throughput`、`mean_ttft` 等)提取失败,值恒为 `inf`。重写为**逐个指标跑独立正则**。
- **入口日志缺失**(`run.py`): 没配 `logging.basicConfig`,默认只能看到 WARNING 以上,跑起来像卡住了。加 `level=INFO` 后所有现有 INFO 日志生效。

### 重构
- **指标提取重构**(`metrics.py`): 不再用合并正则,改用预编译的 `_COMPILED_METRIC_PATTERNS` 字典逐项 `re.search`,取 `group(1)`。代码更清晰,bug 也消除了。
- **日志 banner**(`runner.py` + `benchmark.py`): 用例开始打印 `=====` 分隔条 + `[用例 N/M]` 进度;每次实际跑测试打印 `┣━ ... ┗━` 树状 banner,显示预热/正式阶段、并发数、TTFT/TPOT 结果。
- **SEARCH_PARAMS 清理**(`config.py`): 删除 9 个历史遗留死配置(`TPOT_GAP_MEDIUM` / `STEP_DBL` / `STEP_HALF` / `STEP_MAX` / `MARGIN_VERY_HIGH` / `MARGIN_HIGH` / `MARGIN_MEDIUM` / `STEP_HALVE_MIN` + 原 `STEP_MIN` 合并到 `STEP_LOWER_BOUND`),新增 4 个真正生效的参数(`STEP_UPPER_BOUND` / `STEP_LOWER_BOUND` / `TPOT_REMAINING_HIGH` / `TPOT_REMAINING_LOW`,原 `STEP_FALLBACK` 保留并赋予实际语义),从 18 项精简到 11 项。
- **search.py 硬编码抽取**: 把 `200` / `50` / `100` 等关键硬编码(步长上限、兜底步长、TPOT 剩余空间阈值、偏移量)统一从 `SEARCH_PARAMS` 读取;分级阶梯的内部参数(4/3/1.5/0.5 等倍数)保留硬编码,避免过度抽象。

### 清理
- 删除 `config.py` 里的死代码 `_build_combined_metric_re` 以及不再使用的 `COMBINED_METRIC_RE` / `METRIC_VALUE_GROUP`,以及 `import re`(没用了)。
- 入口文件 `slo_bench_cache.py` 改名为 `run.py`。

### 版本管理
- 在 `config.py` 顶部新增 `VERSION = "v1.1"` 常量。
- `runner.py` 启动日志自动带版本号:`[v1.1] 开始vllm_benchmark并发自动摸高测试`。

---

## [v1.0] - 2026-07-02

初始版本。

- 基础功能: 给定 TTFT/TPOT 阈值,通过自适应并发搜索自动找到临界最大并发数。
- 入口文件: `run.py`。
- 核心包: `slo_bench_core/`(`config` / `benchmark` / `search` / `runner` / `metrics` / `csv_io`)。
- 已知问题: 指标提取函数有 `_build_combined_metric_re` 的 `re.sub` bug,12 个指标提取失败(在 v1.1 修复)。
