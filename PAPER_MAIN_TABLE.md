# 论文主表 — 三个 bench 一人一张（Markdown 版）

图例：`[ ]` 待跑填入 · `—` 该方法原文未覆盖此 bench · ◇ 引用原文数（非同 base model，灰色参考行） · **粗体** 列最优 · 最右 Δ = Overall 相对 No-Memory 的提升（百分点）

所有格子同一 base model、N=8 并行 rollout、同一判分器、两臂配对协议。子结构（题数）全部从官方数据集直接数出：WebArena `test.raw.json` 812 题；Mind2Web 官方 README；SWE-bench Verified HF 数据集 500 题。

---

## Table 1 · WebArena（812 题，任务成功率 %）

| Method | Shopping<br>(187) | Shopping Admin†<br>(182) | GitLab<br>(180) | Reddit<br>(106) | Map<br>(109) | Multi-site<br>(48) | **Overall**<br>(812) | **Δ** |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|
| No-Memory | 53.4 | 78.9 | 67.9 | 56.8 | [ ] | [ ] | 64.3‡ | — |
| No-Memory (token-matched) | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| AWM | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| ASI | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| ReasoningBank | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| **Hippo (ours)** | **64.2** | **87.2** | **73.3** | **62.5** | [ ] | [ ] | **71.8**‡ | **▲7.6** |

† Shopping Admin 为能力口径。
‡ Overall 暂为已填四站均值；Map 待新写端重跑（旧写端 59.2→59.5 备用），Multi-site 待跨站支持。
Multi-site 48 题构成：GitLab+Reddit 18、Map+Wikipedia 17、GitLab+Wikipedia 6、Reddit+Shopping 5、Map+Shopping Admin 2。Wikipedia 只出现在跨站题里，故不单列。

---

## Table 2 · Mind2Web（1,341 测试题；Step Success Rate %）

| Method | Cross-Task<br>(252) | Cross-Website<br>(177) | Cross-Domain<br>(912) | **Avg** | **Δ** |
|:---|---:|---:|---:|---:|---:|
| No-Memory | [ ] | [ ] | [ ] | [ ] | — |
| No-Memory (token-matched) | [ ] | [ ] | [ ] | [ ] | [ ] |
| Synapse ◇ | [ ] | [ ] | [ ] | [ ] | ◇ |
| AWM | [ ] | [ ] | [ ] | [ ] | [ ] |
| ASI | — | — | — | — | — |
| ReasoningBank | [ ] | [ ] | [ ] | [ ] | [ ] |
| **Hippo (ours)** | [ ]¶ | [ ] | [ ] | [ ] | **▲[ ]** |

Cross-Task = 训练见过的网站上的新任务；Cross-Website = 已见领域里的未见网站；Cross-Domain = 整个领域未见。Element Accuracy / Operation F1 与 Step SR 同一次跑出，放附表。
¶ 现有 Cross-Task Step SR：旧配置 Δ+5.4（本机）/ +9.8（另机，数据待归档）；主格等 sol 重跑。

---

## Table 3 · SWE-bench Verified（500 题，解决率 %，按数据集 `difficulty` 字段分档；± 为 4 次独立重复的极差）

| Method | &lt;15 min fix<br>(194) | 15 min–1 hour<br>(261) | 1–4 hours<br>(42) | &gt;4 hours<br>(3) | **Overall**<br>(500) | **Δ** |
|:---|---:|---:|---:|---:|---:|---:|
| No-Memory | [ ] | [ ] | [ ] | [ ] | [ ] ± [ ] | — |
| No-Memory (token-matched) | [ ] | [ ] | [ ] | [ ] | [ ] ± [ ] | [ ] |
| AWM | — | — | — | — | — | — |
| ASI | — | — | — | — | — | — |
| SWE-Exp ◇ | — | — | — | — | [ ] | ◇ |
| ReasoningBank | [ ] | [ ] | [ ] | [ ] | [ ] ± [ ] | [ ] |
| **Hippo (ours)** | [ ] | [ ] | [ ] | [ ] | [ ] ± [ ]§ | **▲[ ]** |

分档是 SWE-bench Verified 数据集自带的 `difficulty` 字段（标注者估计的人工修复时长），四档题数 194 / 261 / 42 / 3 直接从数据集数出；Django 231 题分别为 92 / 117 / 22 / 0。按仓库的切法放附表。
§ 现有 Django 229 题旧配置 43.0→50.0（+7.0），经 4 次重复归零，改报 ± 极差；主格等 sol 重跑 ×4。

---

## 待填实验（最小集，约 8–14 天机时）

| # | 实验 | 填哪些格 |
|:-:|:---|:---|
| 1 | ReasoningBank 复现 @ sol @ WebArena 五站 | Table 1 RB 行 |
| 2 | token-matched 基线 @ sol @ WebArena | Table 1 第 2 行 |
| 3 | Mind2Web 三 split @ sol（No-Memory / Ours / AWM / RB） | Table 2 四行 |
| 4 | SWE Django 子集 @ sol × 4 重复（No-Memory / Ours / RB） | Table 3 Overall 与四档（Django 子集先填） |
| 5 | Map 新写端重跑 + Multi-site 跨站支持 | Table 1 Map / Multi-site 列 |
| 6 | AWM / ASI 复现 @ sol @ WebArena（可砍，砍则改 ◇ 引用原文数） | Table 1 AWM / ASI 行 |
| 7 | SWE 其余 269 题 @ sol（补 Overall 与四档全量） | Table 3 全部列 |
