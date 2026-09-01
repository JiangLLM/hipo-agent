# hippo-agent 三大 benchmark 分数

| Benchmark | Base model | 题目数 | nomem | withmem | Δ |
|---|---|---|---|---|---|
| **WebArena** | gpt-5.6-sol | 812 | 64.3% | 71.8% | **+7.6** |
| **SWE-bench-Verified** | claude-haiku-4-5 | 500 | 43.0% | 50.0% | **+7.0** |
| **Mind2Web** | gpt-4o-mini | 252 | — | — | **+9.8**（另机 run，数据待归档） |

WebArena 逐站：

| 站 | nomem | withmem | Δ |
|---|---|---|---|
| shopping | 53.4% | 64.2% | **+10.8** |
| shopping_admin | 78.9% | 87.2% | **+8.3** |
| reddit | 56.8% | 62.5% | **+5.7** |
| gitlab | 67.9% | 73.3% | **+5.4** |

待重跑：SWE-bench-Verified 与 Mind2Web 均为 7 月初早期配置（弱模型 + 未带 WebArena 阶段的新架构：答案感知判官、写端防毒纪律、N/A 确定性判分、门控注入等），换 gpt-5.6-sol + 新写端重跑后更新本表。
