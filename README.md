# SLO Benchmark - vLLM 自动摸高测试工具

> 基于 `vllm bench serve`,给定 **TTFT / TPOT** 阈值,自适应并发搜索,自动找到**临界最大并发数**。

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](https://www.python.org/)
[![Status](https://img.shields.io/badge/Status-Active-success)](#版本历史)

---

## 这是什么

在大模型推理服务上线 / 性能调优时,经常要回答一个问题:**给定响应延迟 SLO(TP99 TTFT 不超 X ms,TPOT 不超 Y ms),这个 vLLM 服务最大能扛多少并发?**

手工一点点试,费时费力;一次性压满,要么没摸到上限、要么直接打挂服务。

本工具的做法:

1. 从一个保守并发数起步,在 `[low, high]` 区间内做**自适应二分/翻倍搜索**;
2. 每跑一轮 `vllm bench serve`,从日志里**实时提取 TTFT / TPOT / 吞吐**;
3. 一旦任一指标**超出阈值**,立刻回退一步,把步长减半/采用黄金分割,**精细逼近临界点**;
4. 找到临界并发后,做一次**最终确认测试**,落盘 CSV + perf_log。

适用场景:**线上服务的并发容量摸底**、**模型 / 量化方案变更后的回归对比**、**调参前后效果验证**。

---

## 快速开始

### 环境要求

- **Python 3.9+** (本项目仅用标准库,无需 `pip install`)
- 已安装 **vLLM** 且能正常调用 `vllm bench serve` 子命令(请参考 [vLLM 官方文档](https://docs.vllm.ai/en/latest/benchmarking/))

### 跑起来

**当前推荐版本:**

```bash
git clone <repo-url>
cd SLO
python run.py
```

**跑指定历史版本:**

```bash
# 切到 v1.0 (工作区自动变成 v1.0 的代码)
git checkout v1.0
python run.py

# 回到最新
git checkout main
```

历史版本不需要切换目录,`git checkout <tag>` 后根目录的 `run.py` 会自动变成那个版本的代码。

### 配置改哪里

主要改 `slo_bench_core/config.py`:

| 配置项                | 含义                                  | 默认值 |
|-----------------------|---------------------------------------|--------|
| `IO`                  | 测试用例列表(input_len, output_len, 初始 low, 初始 high, TTFT阈值, TPOT阈值) | 见文件 |
| `TTFT_LABEL`          | 判定用的 TTFT 标签(Mean/Median/P99)  | `Mean TTFT` |
| `TPOT_LABEL`          | 判定用的 TPOT 标签(Mean/Median/P99)  | `Mean TPOT` |
| `SERVED_MODEL_NAME`   | vLLM 已部署的模型名                   | `DeepSeek-V4-Flash-Channel-FP8-w8a8` |
| `HOST` / `PORT`       | vLLM 服务地址                          | `0.0.0.0:30000` |
| `MAX_CONCURRENCY_LIMIT` | 并发搜索硬上限                       | `128` |
| `ENABLE_METRICS_SCRAPE` | 是否抓取被测服务 `/metrics` 统计 prefix cache 命中率 / 投机采样接受率 | `True` |
| `SEARCH_PARAMS`       | 自适应搜索参数(步长/阈值/防卡死)     | 见文件 |

---

## 项目结构

```
SLO/
├── README.md              # 本文件
├── CHANGELOG.md           # 版本变更记录
├── requirements.txt       # 依赖(本项目为标准库,无外部依赖)
├── .gitignore
├── run.py                 # 入口(当前推荐版本)
└── slo_bench_core/        # 核心包
    ├── __init__.py
    ├── config.py          # 配置 / 常量 / 正则(VERSION = "v1.X")
    ├── benchmark.py       # 单轮 benchmark 包装 + 重试
    ├── search.py          # 自适应并发搜索主算法
    ├── runner.py          # 多用例调度 + 日志
    ├── metrics.py         # 指标提取
    └── csv_io.py          # CSV 落盘
```

### 核心模块速览

- **`config.py`** — 所有可调常量集中在这里(测试用例、模型信息、搜索策略、CSV 表头、指标正则)。
- **`benchmark.py`** — 封装 `vllm bench serve` 子进程调用、负责子进程超时处理、错误重试。
- **`search.py`** — 自适应并发搜索主算法(粗排 → 步长收敛 → 临界确认)。
- **`runner.py`** — 多测试用例调度,统一日志输出(带 `=====` 分隔条 + `┣━ ┗━` 树状 banner)。
- **`metrics.py`** — 从 benchmark 输出里**正则提取** TTFT/TPOT/Throughput 等指标。
- **`csv_io.py`** — 原始数据 / 最优结果 CSV 落盘到 `./slo_bench/perf_log/`。

---

## 版本管理

只靠 git tag 和 CHANGELOG 管理,代码放在根目录,**不**为每个版本建子目录。

- **Git Tag** — 每个发布版本打一个 tag(`v1.0`、`v1.1` …),`git checkout <tag>` 工作区自动变成该版本的代码。
- **`main` 分支** — 永远指向**最新已发布版本**,与 `v<latest>` tag 指向同一 commit。
- **`config.py` 里的 `VERSION` 常量** — 代码硬编码当前版本号,启动日志会自动带上。
- **CHANGELOG.md** — 每个版本的变更、原因、影响范围。

### 发布新版本的流程

```bash
# 1. 在 main 上改代码,完成后把 config.py 的 VERSION 改成新版本号

# 2. 在 CHANGELOG.md 顶部加新版本段

# 3. 提交并打 tag
git add .
git commit -m "release: v1.2 - <本次变更概述>"
git tag -a v1.2 -m "v1.2: <本次变更概述>"
git push origin main --tags
```

### 查看历史版本

```bash
git tag                # 列出所有版本
git checkout v1.0      # 工作区变成 v1.0 代码(无需切换目录)
git checkout main      # 回到最新
git diff v1.0 v1.1     # 对比两个版本
```

---

## 版本历史

| 版本     | 日期       | 主要变更                                                                |
|----------|------------|-------------------------------------------------------------------------|
| **v1.5** | 2026-09-15 | 新增逐点指标 `point_metrics-*.csv` 与全场景汇总 `import_all_perf.csv`;抓取 `/metrics` 统计 prefix cache 命中率与投机采样接受率 |
| **v1.4.1** | 2026-08-27 | 修复小步长分支漏 `math.isfinite` 守卫导致 `OverflowError`(TTFT 瓶颈 + TPOT 梯度 ≤0 场景) |
| **v1.4** | 2026-07-07 | prefix_repetition 模式 num_prompts = 并发 × 4(`NUM_PROMPTS_PER_CONCURRENCY`);文件名 np 段按模式分支 |
| **v1.3** | 2026-07-07 | 新增 `ENABLE_PREFIX_REPETITION` 前缀重复测试模式;修复 random/prefix_repetition 两种模式漏传 `--max-concurrency` 导致并发压不出 |
| **v1.2** | 2026-07-03 | perf_log 文件名格式 `il{il}_ol{ol}_c{c}` → `il{il}_ol{ol}_np{con}_mc{con}` |
| **v1.1** | 2026-07-02 | 修复 12 个指标提取失败的 `re.sub` bug;加启动日志;清理 9 个死配置         |
| **v1.0** | 2026-07-02 | 初始版本:自适应并发搜索 + 临界确认测试,完整链路打通                      |

---

## 输出物

跑完一次,会在 `./slo_bench/perf_log/<模型名>/` 下生成若干 perf_log 文件,命名格式:

```
il{input_len}_ol{output_len}_np{np}_mc{concurrency}.log
```

- `il` — input length (输入 token 数)
- `ol` — output length (输出 token 数)
- `np` — num prompts(请求数,传给 `vllm bench serve --num-prompts`)
- `mc` — max concurrency (并发数)

> `np` 按 dataset 模式区分:
> - `random` 模式: `np = mc`(1:1)
> - `prefix_repetition` 模式: `np = mc × NUM_PROMPTS_PER_CONCURRENCY`(默认 ×4,即每个并发跑 4 个请求再汇总体,用来给 prefix 缓存充分热身)
>
> 文件名按两个维度同时记录,方便将来调整比例。
>
> CSV 输出(原始数据 / 最优结果)在 `slo_bench/slo_log/<日期>/context_<il>x<ol>/` 下,文件名 `vllm_bench_result-<il>x<ol>-TTFT<ttft>-TPOT<tpot>.csv`、 `max_results-<...>.csv`、`point_metrics-<...>.csv`、`summary_<日期>.csv`;全场景汇总 `slo_bench/import_all_perf.csv` 见下节。

`max_results_*.csv` 的列:

```
input_len, output_len, concurrency, ttft, tpot, is_optimal
```

`is_optimal=1` 的行就是该测试用例下被识别的**临界最大并发数**。

### 逐点指标 point_metrics-*.csv 与全场景汇总 import_all_perf.csv

每个测试用例结束后,在 `slo_bench/slo_log/<日期>/context_<il>x<ol>/` 下写一份
`point_metrics-<il>x<ol>-TTFT<ttft>-TPOT<tpot>.csv`(每次运行重写),收录该用例本次
实际测过的每个**成功**并发点(含探索点 / 二分点 / 最终确认点 / 最优并发 ±1 参考点),
按并发数排序;运行结束再把所有用例的行汇总重写到 `slo_bench/import_all_perf.csv`
(每次运行重写、只留最新),两张表列完全相同:

```
input_len, output_len, concurrency,
mean_ttft, mean_tpot,
output_token_throughput, total_token_throughput, benchmark_duration,
output_throughput_per_concurrency, decode_throughput_per_concurrency,
prefix_cache_hit_rate, spec_decode_accept_rate
```

- `output_throughput_per_concurrency` — 单并发输出吞吐 = 生成输出吞吐 ÷ 并发数;
- `decode_throughput_per_concurrency` — 单并发 decode 吞吐 = 1000 ÷ 平均 TPOT(ms),即单条请求流在 decode 阶段的 token 速率;
- `prefix_cache_hit_rate`(prefix cache 命中率,百分数)— 来自被测服务 `/metrics`
  正式测试**前后快照**的差值,按指标前缀自动识别后端:
  - vLLM: Δhits ÷ Δqueries × 100(兼容 `vllm:gpu_prefix_cache_*` / `vllm:prefix_cache_*` /
    `vllm:cpu_prefix_cache_*` 三组候选名,计数器 `_total` 后缀自动解析;服务端需启用
    `--enable-prefix-caching`,否则该列留空);
  - SGLang: token 级命中率 Δcached ÷ Δprompt × 100(服务端需 `--enable-metrics` 暴露
    `/metrics`;unified 等版本无 `cached_tokens_total` 样本时自动退回
    `1 - Δuncached ÷ Δprompt`);
- `spec_decode_accept_rate`(投机采样接受率,百分数)— **优先取 bench serve 输出中直接
  打印的本次测试 `Acceptance rate (%)`**(部分厂商 fork 的 vLLM 会打印,为逐轮精确值),
  输出中没有该项时回退 `/metrics` 差值口径:
  - vLLM: Δaccepted ÷ Δdraft × 100;
  - SGLang: 取测试后快照的 `sglang:spec_accept_rate` Gauge(多 dp_rank 按
    `spec_accept_length` 配对,空闲 rank 不参与平均)。

抓取失败、服务无该指标或分母为 0 时对应列留空;`ENABLE_METRICS_SCRAPE=False` 可整体
关闭抓取。

---

## 常见问题

**Q: 跑起来只看到 WARNING,看不到进度?**
A: v1.0 入口没配 logging,v1.1 已修。`git checkout v1.1 && python run.py` 即可。

**Q: 测试时崩 `OverflowError: cannot convert float infinity to integer`?**
A: 出现在 v1.4 及之前的 `slo_bench_core/search.py:340`(小步长分支),`predict_tpot_critical_point` 在 TPOT 梯度 ≤ 0 时返回 `float('inf')`,小步长分支漏了 `math.isfinite` 守卫,`int(inf - x)` 直接挂。常见触发场景: **TTFT 已是瓶颈(压到 ttft_max 附近),TPOT 仍远低于 tpot_max**,历史两点 TPOT 随并发增加反而微降(vLLM batching 摊薄)。v1.4.1 已修: 补 `math.isfinite` 守卫,无法预测时回退到 `+20` 步长继续探索。

**Q: CSV 里某些指标值是 `inf`?**
A: v1.0 的 `_build_combined_metric_re` 有 bug,v1.1 已重构为逐指标独立正则。切到 v1.1 或更新版本即可。

**Q: 想加新的测试用例?**
A: 编辑 `slo_bench_core/config.py` 里的 `IO` 列表,加一行 `(input_len, output_len, low, high, ttft阈值, tpot阈值)`。

**Q: 想加新的指标提取?**
A: 在 `config.py` 的 `METRIC_PATTERNS` 字典里加一条 `<key>: <regex>` 即可,无需改 `metrics.py`。

**Q: GitHub 上怎么看历史版本对应的代码?**
A: 进入仓库页面 → 切换到对应 tag(右上角 branches/tags 下拉)→ 浏览文件,或者本地 `git checkout <tag>`。
