# hippo-agent — HANDOFF (project state & next steps)

> 目的：把这台机器上的调研 + 决策 + 现状交接给另一台机器上的新会话。读完这份即可接着干。

## 0. 一句话
让 agent 从经验里"自进化"的记忆系统。在 **Mind2Web**（teacher-forced 逐步预测）上，旧记忆**帮倒忙**；查清根因、重写了抽取后，变成**小幅正向**，但被数据集天花板压住。下一步计划迁到 **WebArena**（自主导航，记忆真有用武之地）。

## 1. 仓库
- 代码在 `src/hippo/`（很小，~280K）；`data/`(11G, Mind2Web) 和 `.venv/`、`runs/` 都 gitignore，**不随包走**。
- 关键文件：`src/hippo/m2w/run.py`(协议 step_evolve/stream)、`src/hippo/brain.py`(抽取)、`src/hippo/memory/store.py`(双库)、`config/default.yaml`。
- 跑真实 pipeline（需 OPENAI_API_KEY 在 .env）：
  `python -m hippo.m2w.run --brain llm --m2w.protocol stream --m2w.test_split test_task --m2w.top_k 50 --memory.mode fact_only --m2w.layer1 on --m2w.layer2 on --agent.n_traj 5 --m2w.test_limit 20`

## 2. Mind2Web 上查清的根因（有数据支撑）
- 旧结果：记忆净负（nomem step_success≈0.35 → withmem≈0.32）。
- 逐步对齐：misled(带偏) > reused(复用)。
- 三个原因（debug 分桶，334 步）：**40% 覆盖不够**（库里没相关经验，数据集低复用率决定，改不动）；**~69% 注入离题**（检索灌水）；旧 L1 抽取**反 gold、带任务原话、矛盾**。
- Retrieve 实测：top-4 里 ~89% 没用；试过 intent 匹配/阈值/grounding 都没救；根因是"每步≤1条有用却塞4条" + 覆盖。
- **教训**：单步 fact 会灌水；L1+L2 合并比单用更差（灌水）；embedding 检索在同站点文本上分不开。

## 3. 已做的代码改动（只改抽取，未碰 stream）
- `src/hippo/schema.py`：`FactItem` 加 `condition: str=""`（存 intent，供未来按子目标检索）。
- `src/hippo/brain.py`：
  - 新 helper：`_parse_control`(从 gold 解析 role/label)、`_dangerous_literals` + `_delist`(去任务字面值)。
  - **重写 `judge_step`(L1)**：正确控件用 gold 钉死（不再反 gold）；产出 intent/cue/trap + 模板拼接；去重 key=role:label:intent；drop 退化 trap。
  - L2(`extract_step_experiences`)**未改**；`extract_fact` 是旧的、且 body 截断（step 协议不用它）。

## 4. 实测结果（新抽取后，干净 held-out，0 泄漏）
- 静态 A/B（49 held-out 任务，共同 nomem 基线）：nomem elem=0.353；**L1 +0.021 / L2 +0.024**（打平，step_success L1 +0.054 略高）；**L1+L2 合并 −0.009（灌水，比单用差）**。L2 用 40 条 ≈ L1 用 104 条（L2 单条效率高）。
- Stream 自进化（从零、跨任务、新 L1）：整体 +0.009；**gap 前半程 −0.013 → 后半程 +0.028**（越学越好的形状，但小）。
- 正向对照（test-on-learn，有泄漏）：+15，仅证明机制通。
- 结论：**抽取修复把记忆从"负"推到"暖机后正向"，但 Mind2Web 量级小（覆盖+低复用率天花板）。**

## 5. WebArena 迁移计划（下一步主战场）
- 为什么：自主导航、per-task 功能判分、无逐步 gold、同站点任务多 → 记忆真有头部空间（RB +8.3%、AWM +51% 相对）。
- **数据集**：5 个 Docker 自建站(shopping/shopping_admin/reddit/gitlab/map)，~812 任务；评分 **per-task 程序化**(string/url/program_html，任务末尾查最终状态，0/1)，**无逐步分**。
- **自评**：RB 用 **per-task LLM-judge**(判整条轨迹成/败，label-free)驱动记忆；仓库 `google-research/reasoning-bank` 提供 agent(`WebArena/agents/basic`)+judge(`autoeval`)+harness。
- **我们的 per-task 设计（已和作者对齐）**：每任务 → 检索注入 → N 条并行 rollout → 每条 LLM 判成败(L1) → 对比 N 条(L2，按"多数对/错"分流) → 合并写库 → 下个任务用。**单元=任务级可泛化策略（不是单步 fact），从源头避免灌水。**
- **待定决策（差异化）**：(a) fact/reasoning 分离**当消融验证、别默认有用**（RB 单库就行）；(b) L2 的"多数方向"门控 ≠ MaTTS，是我们的小差异点；(c) 最有价值的可能是**"抗灌水/抗假成功/取得准"这套记忆质量机制**（RB 只一句 prompt 带过、我们真数据反复踩到）。
- **机器**：本机 M4 Max/64G/Docker(33G,10cpu)/~308G 空盘，够跑；注意磁盘(镜像大，先起 1–2 站)、别塞满、重批次夜里跑。

## 6. 关键教训 / 别再踩
1. **先测再写**：任何抽取/检索改动，先在真实数据离线验证，再落代码。
2. **判定要严**：假成功会被记忆放大成毒（RB 明确警告）。
3. **别合并灌水**：池子一大、top-k 检索就烂；单元要少而准。
4. **区分 test-on-learn（泄漏）vs held-out（真迁移）**：报告只信 held-out。
5. 沙箱/网络：litellm 走代理可能被挡；裸 urllib 有时能通。真跑用本机终端。

## 7. 后台还在跑的
`stream_L1 / stream_L2 / stream_L1L2`（各 40 任务，n_traj=5，真 pipeline）——`runs/stream_*/summary.json`。慢(~147s/withmem-task)，跑完看 3 者 A/B + 逐步 reused/misled + L1+L2 是否也灌水。
