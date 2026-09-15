# Changelog

所有版本通过 git tag(`v1.0`、`v1.1` …)发布,`git checkout <tag>` 看历史版本代码。

---

## [v1.5.1] - 2026-09-15

相对 v1.5 的变更。

### 新功能
- **benchmark 命令显式下发 `--percentile-metrics ttft,tpot,itl,e2el`**(`config.py` + `benchmark.py`):
  此前未传该参数,用的 vllm 默认值(ttft,tpot,itl);新增 `PERCENTILE_METRICS` 配置项,e2el 为
  端到端时延(需要 bench serve 侧支持该取值)。配套提取 `Mean/Median/P99 E2EL (ms)` 到 metrics
  (`METRIC_PATTERNS` 新增 `mean_e2el` / `median_e2el` / `p99_e2el`),并落到
  `vllm_bench_result-*.csv` 新增的 `mean_e2el / median_e2el / p99_e2el` 三列
  (`VLLM_BENCH_HEADERS`)+ `perf_log` 的 Extracted Metrics 段。
  **注意**: 该 CSV 追加写,旧表头无这三列——升级后重跑前清掉当天旧的
  `vllm_bench_result-*.csv`,避免新旧行错位。
- **point_metrics-*.csv 即时落盘**(`benchmark.py` + `csv_io.py` + `runner.py`): 每个成功并发点
  在 `_formal_test_with_scrape` 测完**当场追加**一行(进程中断也不丢已测结果,此前要等用例搜索
  结束才一次性写出);用例结束后从 `cached_results` 整体重写为按并发数排序、去重的最终版本
  (重测同一并发只留最新)。行构造抽为 `csv_io.point_metrics_row()` 供即时追加与汇总共用;
  v1.5 已有的"收录全部成功并发点"语义不变。

### 修复
- **prefix_repetition 模式 NameError**(`benchmark.py`): `NUM_PROMPTS_PER_CONCURRENCY` 在
  `_build_bench_cmd` / `save_perf_log_entry` 中使用但漏 import,默认 random 模式因条件短路
  不触发,一开 `ENABLE_PREFIX_REPETITION` 即崩;补上 import。

### 文档
- README 补 v1.5.1 版本历史行。

---

## [v1.5] - 2026-09-15

相对 v1.4.1 的变更。

### 新功能
- **prefix cache 命中率与投机采样接受率统计**(`metrics.py` + `benchmark.py` + `config.py`):
  每次正式测试前后各抓一次被测服务 `/metrics`(Prometheus 文本格式,`urllib` 标准库实现),
  差值计算两个百分数并注入该次测试的 metrics:
  - vLLM: `prefix_cache_hit_rate` = Δhits ÷ Δqueries × 100(兼容 `vllm:gpu_prefix_cache_*` /
    `vllm:prefix_cache_*` / `vllm:cpu_prefix_cache_*` 三组候选名,计数器 `_total` 后缀自动解析);
    `spec_decode_accept_rate` = Δaccepted ÷ Δdraft × 100;
  - SGLang: token 级命中率 Δcached ÷ Δprompt(unified 等版本无 `cached_tokens_total` 样本时
    退回 `1 - Δuncached ÷ Δprompt`);接受率取测试后快照的 `sglang:spec_accept_rate` Gauge
    (多 dp_rank 部署按 `spec_accept_length` 配对,length=0 的空闲 rank 不参与平均);
  - `spec_decode_accept_rate` **优先取 fork 版 bench serve 输出直接打印的本次测试
    `Acceptance rate (%)`**(逐轮精确值,不受指标命名差异与其他流量污染),输出中没有该项时
    回退上述 `/metrics` 差值口径;
  - 抓取失败 / 服务无该指标 / 分母为 0 时对应值留空;新增 `ENABLE_METRICS_SCRAPE` /
    `METRICS_SCRAPE_PATH` / `METRICS_SCRAPE_TIMEOUT` 三个配置项,可整体关闭;
    抓取失败只告警一次,不中断测试。
- **逐点指标表 `point_metrics-*.csv`**(`runner.py`): 每个用例搜索结束后,把该用例本次实际测过的
  每个**成功**并发点(含大步长探索点 / 二分点 / 最终确认点 / 最优并发 ±1 参考点)的关键性能
  指标写到 `slo_bench/slo_log/<日期>/context_<il>x<ol>/point_metrics-<il>x<ol>-TTFT<t>-TPOT<t>.csv`
  (每次运行重写),按并发数排序。数据直接取自 `adaptive_concurrency_search` 返回的
  `cached_results`,不产生额外测试开销;失败点(`ttft/tpot` 为 `-1` 或 `inf`)与
  `retry_count` 计数键跳过。
- **全场景汇总表 `import_all_perf.csv`**(`runner.py`): 上述 point_metrics 的全场景汇总表
  (列完全相同),运行结束整体重写到 `slo_bench/import_all_perf.csv`(每次运行重写、只留最新,
  语义参考 bench 项目的同名产物),按 `(input_len, output_len, concurrency)` 排序,便于导入
  表格工具横向对比。
- 两表列结构(`POINT_METRICS_HEADERS`): `input_len / output_len / concurrency / mean_ttft /
  mean_tpot / output_token_throughput / total_token_throughput / benchmark_duration` 加两个
  单并发归一化指标 `output_throughput_per_concurrency`(生成输出吞吐 ÷ 并发数)、
  `decode_throughput_per_concurrency`(1000 ÷ 平均 TPOT,单条请求流的 decode 速率)与
  `prefix_cache_hit_rate` / `spec_decode_accept_rate` 两个命中率列。
- `METRIC_PATTERNS` 新增 `spec_accept_rate`(bench serve 输出的 `Acceptance rate (%)`)。

### 文档
- README「输出物」新增「逐点指标 point_metrics-*.csv 与全场景汇总 import_all_perf.csv」小节;
  配置表补 `ENABLE_METRICS_SCRAPE`;版本历史表补 v1.5 行。

---

## [v1.4.1] - 2026-08-27

相对 v1.4 的变更。

### Bug 修复
- **小步长分支 `OverflowError`**(`search.py`): `predict_tpot_critical_point` 在 TPOT 梯度 ≤ 0 时返回 `float('inf')` 表达"无法预测临界并发",而小步长分支(`tpot_gap <= TPOT_GAP_LARGE`)调用前漏了 `math.isfinite` 守卫,导致 `int(inf - x)` 抛 `OverflowError: cannot convert float infinity to integer`。与另两处调用(大步长分支 / 动态步长分支)处理对齐,补 `math.isfinite(predicted)` 守卫;无法预测时回退到 `+20` 步长继续探索,后续若触到 TTFT 上限会自然走到 `_force_binary_on_cap` 做二分。**触发场景**: TTFT 已是瓶颈(压到 ttft_max 附近),TPOT 还远低于 tpot_max 阈值,历史两点 TPOT 随并发不升反降(vLLM batching 摊薄 decode 时间但排队拉长 TTFT),梯度出现 -0.x ms/并发 的情况。

---

## [v1.4] - 2026-07-07

相对 v1.3 的变更。

### 新功能
- **prefix_repetition 模式 num_prompts 加倍率**(`config.py` + `benchmark.py`): 新增 `NUM_PROMPTS_PER_CONCURRENCY = 4` 常量,启用 `ENABLE_PREFIX_REPETITION` 时 `--num-prompts = 并发 × 4`,即每个并发跑 4 个请求汇总体,给 prefix 缓存充分热身。`random` 模式保持原样(`--num-prompts = 并发`,1:1)。
- **perf_log 文件名 np 段按模式分支**(`benchmark.py`): `save_perf_log_entry` 根据 `ENABLE_PREFIX_REPETITION` 决定 np 值(random 模式 `np = mc`,prefix_repetition 模式 `np = mc × 4`),文件名跟实际命令保持一致。

### 重构
- **配置归位**(`config.py`): `NUM_PROMPTS_PER_CONCURRENCY` 从 `vllm bench serve 固定参数` 块挪到 `前缀重复测试开关` 块下,跟 `ENABLE_PREFIX_REPETITION` 等常量聚拢,功能不变。

### 文档
- README np/mc 描述分模式说明(random / prefix_repetition 各自规则)。

---

## [v1.3] - 2026-07-07

相对 v1.2 的变更。

### 新功能
- **前缀重复测试模式**(`config.py` + `benchmark.py`): 新增 `ENABLE_PREFIX_REPETITION` 开关(默认关闭),启用后 `_build_bench_cmd` 切到 `prefix_repetition` dataset,通过 `PREFIX_REPETITION_PC_RATIO` 控制 prefix 在输入中的占比(prefix + suffix 都向上取整,可能比 `input_len` 多 1 token)。用于压测前缀缓存命中场景下的吞吐上界。

### Bug 修复
- **vllm bench serve 缺 `--max-concurrency`**(`benchmark.py`): random 和 prefix_repetition 两种模式在 `--num-prompts` 之后都漏传 `--max-concurrency`,导致 vLLM 走默认串行执行,压不出真实并发吞吐。两个分支 `--num-prompts` 之后均补齐。

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
