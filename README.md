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
| **v1.1** | 2026-07-02 | 修复 12 个指标提取失败的 `re.sub` bug;加启动日志;清理 9 个死配置         |
| **v1.0** | 2026-07-02 | 初始版本:自适应并发搜索 + 临界确认测试,完整链路打通                      |

完整变更记录见 [CHANGELOG.md](./CHANGELOG.md)。

---

## 输出物

跑完一次,会在 `./slo_bench/perf_log/` 下生成:

```
slo_bench/perf_log/
└── <日期>_<时间>_<模型名>/
    ├── raw_<时间戳>.csv           # 每轮 benchmark 原始数据
    ├── max_results_<时间戳>.csv   # 每个 (input_len, output_len) 的最优并发
    └── perf_<时间戳>.log          # 完整运行日志(追加)
```

`max_results_*.csv` 的列:

```
input_len, output_len, concurrency, ttft, tpot, is_optimal
```

`is_optimal=1` 的行就是该测试用例下被识别的**临界最大并发数**。

---

## 常见问题

**Q: 跑起来只看到 WARNING,看不到进度?**
A: v1.0 入口没配 logging,v1.1 已修。`git checkout v1.1 && python run.py` 即可。

**Q: CSV 里某些指标值是 `inf`?**
A: v1.0 的 `_build_combined_metric_re` 有 bug,v1.1 已重构为逐指标独立正则。切到 v1.1 或更新版本即可。

**Q: 想加新的测试用例?**
A: 编辑 `slo_bench_core/config.py` 里的 `IO` 列表,加一行 `(input_len, output_len, low, high, ttft阈值, tpot阈值)`。

**Q: 想加新的指标提取?**
A: 在 `config.py` 的 `METRIC_PATTERNS` 字典里加一条 `<key>: <regex>` 即可,无需改 `metrics.py`。

**Q: GitHub 上怎么看历史版本对应的代码?**
A: 进入仓库页面 → 切换到对应 tag(右上角 branches/tags 下拉)→ 浏览文件,或者本地 `git checkout <tag>`。
