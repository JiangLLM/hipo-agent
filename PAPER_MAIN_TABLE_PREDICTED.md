# 主表预测值（预测，非实测）— 2026-09-01

与 `PAPER_MAIN_TABLE.md` 三张表格子一一对应。我们的行 = SCORES_REPORT.md / WA_SCORES.md 正典分；竞品行 = 该方法在最新最强 base model 上的已发表 Δ（原文或第三方复现），按 sol 基线的剩余空间折算后叠到我们的 No-Memory 上；Overall 为四站均值；置信度低的格子留空。

## Table 1 · WebArena（812 题，任务成功率 %）

| Method | Shopping<br>(187) | Shopping Admin<br>(182) | GitLab<br>(180) | Reddit<br>(106) | Map<br>(109) | Multi-site<br>(48) | **Overall** | **Δ** |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|
| No-Memory | 53.4 | 78.9 | 67.9 | 56.8 | [ ] | [ ] | 64.3 | — |
| No-Memory (token-matched) | 54.4 | 79.9 | 68.9 | 57.8 | [ ] | [ ] | 65.3 | +1.0 |
| AWM | 54.6 | 80.1 | 69.1 | 58.0 | [ ] | [ ] | 65.5 | +1.2 |
| ASI | 55.9 | 81.4 | 70.4 | 59.3 | [ ] | [ ] | 66.8 | +2.5 |
| ReasoningBank | 57.7 | 81.5 | 70.6 | 61.3 | [ ] | [ ] | 67.8 | +3.5 |
| **Hippo (ours)** | **64.2** | **87.2** | **73.3** | **62.5** | [ ] | [ ] | **71.8** | **+7.6** |

## Table 2 · Mind2Web（Step Success Rate %）

| Method | Cross-Task<br>(252) | Cross-Website<br>(177) | Cross-Domain<br>(912) | **Avg** | **Δ** |
|:---|---:|---:|---:|---:|---:|
| No-Memory | [ ] | [ ] | [ ] | [ ] | — |
| No-Memory (token-matched) | [ ] | [ ] | [ ] | [ ] | [ ] |
| Synapse ◇ | [ ] | [ ] | [ ] | [ ] | +0.5 |
| AWM | [ ] | [ ] | [ ] | [ ] | −0.2 |
| ASI | — | — | — | — | — |
| ReasoningBank | [ ] | [ ] | [ ] | [ ] | +2.1 |
| **Hippo (ours)** | [ ] | [ ] | [ ] | [ ] | **+9.8** |

## Table 3 · SWE-bench Verified（500 题，解决率 %，按数据集 `difficulty` 字段分档）

| Method | &lt;15 min fix<br>(194) | 15 min–1 hour<br>(261) | 1–4 hours<br>(42) | &gt;4 hours<br>(3) | **Overall**<br>(500) | **Δ** |
|:---|---:|---:|---:|---:|---:|---:|
| No-Memory | [ ] | [ ] | [ ] | [ ] | 43.0 | — |
| No-Memory (token-matched) | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| AWM | — | — | — | — | — | — |
| ASI | — | — | — | — | — | — |
| SWE-Exp ◇ | — | — | — | — | 45.2 | +2.2 |
| ReasoningBank | [ ] | [ ] | [ ] | [ ] | 46.4 | +3.4 |
| **Hippo (ours)** | [ ] | [ ] | [ ] | [ ] | **50.0** | **+7.0** |
