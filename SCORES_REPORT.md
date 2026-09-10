# hippo-agent 三大 benchmark 分数

| Benchmark | Base model | 题目数 | nomem | withmem | Δ |
|---|---|---|---|---|---|
| **WebArena** | gpt-5.6-sol | 812 | 64.3% | 71.8% | **+7.6** |
| **SWE-bench-Verified** | claude-haiku-4-5 | 500 | 43.0% | 50.0% | **+7.0** |
| **Mind2Web** | gpt-4o-mini | 252 | 65.4% | 74.6% | **+9.2** |

WebArena 逐站：



| 站 | nomem | withmem | Δ |
|---|---|---|---|
| shopping | 53.4% | 64.2% | **+10.8** |
| shopping_admin | 78.9% | 87.2% | **+8.3** |
| reddit | 56.8% | 62.5% | **+5.7** |
| gitlab | 67.9% | 73.3% | **+5.4** |




| 站 |  nomem | withmem | Δ |
|---|---|---|---|
| shopping |  0.559 | 0.701 | **+14.1** |
| shopping_admin | 0.673 | 0.807 | **+13.4** |
| gitlab |  0.679 | 0.821 | **+14.2** |
| reddit | 0.568 | 0.636 | +6.8 |
| map |  0.592 | 0.794 | **+20.2** |
| **全部合计** | **0.609** | **0.761** | **+15.2** |

待重跑：SWE-bench-Verified 与 Mind2Web 均为 7 月初早期配置（弱模型 + 未带 WebArena 阶段的最新新架构），换 gpt-5.6-sol 或者fable/opus5 重新跑一遍实验。
