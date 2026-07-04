# hippo-agent — HANDOFF

> 交接文档：把这台机器上的全部调研、结论、代码改动、实验数据、下一步计划，交给另一台机器 / 另一个会话。读完这份即可无缝接手。**不含任何密钥**（`.env` 已 gitignore，需在新机器单独设 `OPENAI_API_KEY`）。

---

## 0. 项目与目标
- 代号 **hippo-agent**：让 agent 从经验里"自进化"的**记忆系统**。
- 当前基准 **Mind2Web**（teacher-forced 逐步网页动作预测）。计划迁到 **WebArena**（自主导航）。
- 记忆设计：**双库** = `FactStore`(站点特定 UI 事实) + `ReasoningStore`(可泛化策略)；**surprise 门控的两层抽取** L1(单步/单轨) + L2(N 采样对比)；**向量检索按 scope+相似度注入**。

## 1. 仓库结构 / 怎么跑
- 代码 `src/hippo/`（很小，~280K）。`data/`(11G Mind2Web)、`.venv/`、`runs/`、`.env` 均 gitignore，**不在库里**。
- 关键文件：
  - `src/hippo/m2w/run.py` — 两个协议：`step_evolve`(learn/test holdout)、`stream`(边学边升级，记忆跨任务滚动)。
  - `src/hippo/brain.py` — 抽取：`judge_step`(L1)、`extract_step_experiences`(L2)。
  - `src/hippo/memory/store.py` — `FactStore`(scope+向量) / `ReasoningStore`(向量) / `Memory`(检索/注入/render)。
  - `src/hippo/schema.py`、`src/hippo/surprise/__init__.py`、`config/default.yaml`。
  - `scripts/debug_*.py` — 分析脚本。
- 新机器准备：
  ```bash
  git clone https://github.com/dementiaproject/hipo-agent.git
  cd hipo-agent && python3 -m venv .venv && source .venv/bin/activate && pip install -e .   # 或 uv sync
  printf 'OPENAI_API_KEY=%s\n' '你的key' > .env      # 密钥单独设,别提交
  ```
- 跑真实 pipeline（stream，L1+L2）：
  ```bash
  python -m hippo.m2w.run --brain llm --m2w.protocol stream --m2w.test_split test_task \
    --m2w.top_k 50 --memory.mode fact_only --m2w.layer1 on --m2w.layer2 on \
    --agent.n_traj 5 --m2w.test_limit 20 --run.budget_usd 10 --run.name stream_test
  ```
  L1-only 用 `--m2w.layer2 off`；L2-only 用 `--m2w.layer1 off`。stream 会自动配对跑一遍 nomem 作 A/B。

## 2. 基准设定（重要，别搞混）
- Mind2Web：**teacher-forced 逐步预测**。每步给 gold 历史，agent 预测一个动作，对 gold 算 element_acc / action_f1 / step_success。**每步都有 gold**。候选由 DeBERTa ranker 取 top_k（top_k=5 时 60% 步可解，top_k=50 时 84%/88%）。
- 复用率低：test_task 252 任务 / 69 站点 ≈ 3.7 任务/站；同站跨任务控件复用 ~39%。**这是天花板的来源。**

## 3. Mind2Web 上查清的根因（都有数据）
逐步 debug 分桶（334 held-out 步，只 L1）：
| 占比 | 桶 | 含义 |
|---|---|---|
| 40% | 都错 + 无相关 fact | **覆盖不够**（库里没相关经验；数据集低复用率决定，改不动）|
| 26% | 都对 | 记忆用不上 |
| 14% | 都错 + 有相关 fact | 注入了但没转化 |
| 11% | REUSED（本错→修对）| 记忆帮上了 |
| 8% | MISLED（本对→带错）| 记忆帮倒忙 |
- 净 reused−misled = **+10 步**；注入命中当前 gold 控件仅 **31%**，**69% 离题**（灌水）。
- **MISLED 几乎全是"注入了不匹配当前子目标的 fact"**（存了 `condition` 却没在检索里用它筛）。
- 旧 L1 抽取的病（重写前）：**反 gold**（gold 是 Category 却写"点 Size"）、**93% 否定句、92% 来自错步**、**带任务原话**、同站矛盾。
- Retrieve 实测：top-4 里 ~89% 没用；试过 **intent 匹配 / 相似度阈值 / grounding** 全都没救（同站文本 embedding 分不开；每步≤1 条有用却塞 4 条）。

## 4. 已做的代码改动（只改抽取 L1，未碰 stream / retrieve）
- `src/hippo/schema.py`：`FactItem` 加 `condition: str = ""`（存 intent，供未来按子目标检索；向后兼容 save/load）。
- `src/hippo/brain.py`：
  - 新 helper：`_parse_control`（从 gold_repr 解析 role/label/op）、`_dangerous_literals`（多词专名/月份/数字/gold 值）+ `_delist`（剥离，保留通用词如 "city"）。
  - **重写 `judge_step`(L1)**：把**正确控件用 gold 钉死**喂给模型（模型不许改 → 消除反 gold）；产出 `intent`/`cue`/`trap` 三字段；**模板拼接** statement；**确定性后处理**（去任务字面值、trap==label 则丢弃、intent 空则不写）；dedup `key = role:label:intent`。
  - **未改**：`extract_step_experiences`(L2) 仍是旧的；`extract_fact` 是旧的且函数体被截断（step 协议不用它，无影响）。

## 5. 实验结果（新抽取后；干净 held-out = 0 泄漏）
- **静态 A/B（49 held-out 任务 / 334 步；共同 nomem 基线）**：
  - nomem element_acc = **0.353**
  - **L1**：+0.021（step_success +0.054）— 104 条
  - **L2**：+0.024（step_success +0.033）— 40 条（单条效率高）
  - **L1+L2 合并**：**−0.009**（比单用差 → 灌水）
  - 小样本(14 任务)曾看到 L1 +0.036 / L2 +0.062，放大后缩水 → **之前的大数有方差成分**。
- **Stream 自进化（从零、跨任务、新 L1）**：整体 +0.009；**gap 前半程 −0.013 → 后半程 +0.028**（"越学越好"的形状，但小；冷启动+低复用率压着）；记忆长到 218 条。
- **正向对照 test-on-learn（有泄漏）**：+15 —— 仅证明机制通，不代表泛化。
- **对照**：旧代码（旧 L1+旧 L2）stream 是 **0.35→0.32 负**的；新抽取推到了"暖机后正向"。
- **结论**：抽取修复把记忆从"负"→"小幅正"，但 Mind2Web 量级小（覆盖+低复用率天花板），符合 AWM 在 Mind2Web 的 +0.4~2.8 绝对点。

## 6. 关键教训 / 别再踩
1. **先测再写**：任何抽取/检索改动，先在真实数据离线验证，再落代码。
2. **判定要严**：假成功会被记忆放大成毒（RB 明确警告 "a false success is more harmful"）。
3. **别合并灌水**：库一大、top-k 检索就烂；**单元要少而准**；L1+L2 合并反而变负。
4. **区分 test-on-learn(泄漏) vs held-out(真迁移)**：只信 held-out；报告前先查 eval/learn 任务是否重叠。
5. **小样本有方差**：结论要放大到几十任务再定。
6. 环境：litellm 走代理可能被沙箱挡（403）；真跑用本机终端。

## 7. 参考：RB 与 AWM（我们借鉴的两篇）
- **AWM**（zorazrw/agent-workflow-memory）：单元=**抽象多步 workflow**（把 "dry cat food"→"{product-name}"），从**成功**轨迹归纳；Mind2Web 上**把整站 workflow 全塞进 prompt、不做 top-k 检索**（所以没有灌水问题）；utility 0.91；Mind2Web +24.6% 相对(0.4~2.8 绝对)。
- **RB / ReasoningBank**（google-research/reasoning-bank）：单元=**可泛化推理策略**(title/desc/content)，从**成功+失败**学（失败→"don't do X when Y" 的可泛化回避）；LLM-judge 无 gold；**跨任务闭环**（streaming，每任务检索→用→归纳→consolidate）；WebArena +8.3%、SWE-Bench +4.6%。**MaTTS**=对同一 query 跑 k 条并行/串行 self-contrast 提炼更好记忆（服务跨任务库）。
- 关键对比：加失败轨迹**对 RB 有益、对 AWM 有害**。我们的 stream≈RB 跨任务闭环；L2≈MaTTS 但用"多数对/错"分流（我们的小差异）。

## 8. WebArena 迁移计划（下一步主战场）
### 为什么
自主导航、per-task 功能判分、无逐步 gold、同站点任务多（复用高）→ 记忆真有头部空间（Mind2Web 被 teacher-forcing+低复用率焊死，WebArena 不是）。
### 数据集（已从官方代码核实）
- 5 个 **Docker 自建站**：shopping(OneStopShop)、shopping_admin(Magento)、reddit(Postmill)、gitlab、map(OSM)。~812 任务。
- **自主回合制**：给 NL 意图 → 观察(accessibility tree/截图) → 动作(click/type/scroll/goto/…/stop) → 循环至 stop 或步数上限。**全程自己走，无 gold 历史。**
- **评分 = per-task 程序化**（`web-arena-x/webarena` 的 `evaluation_harness/evaluators.py`）：任务**结束时**查最终状态——`string_match`(最终答案) / `url_match`(最终 URL) / `program_html`(查页面/DB 状态)，各项相乘 → **0/1，一个任务一个分，无逐步分**。
### 自评（RB 的 label-free 信号）
- RB `WebArena/autoeval/evaluate_trajectory.py`：**对整条轨迹(=整任务)评一次**——喂 intent + 每步 axtree + think + action + 最终 response + 截图 → 输出 success/fail（严格规则见 `autoeval/prompts.py`）。用它驱动记忆归纳（不看原生真值，保持 label-free；原生真值只用来报 SR）。
### 现成可复用（不用从零造）
- RB 仓库：基础 agent(`WebArena/agents/basic`)、per-task LLM-judge(`autoeval`)、prompts、config 处理、`run.sh`；接 BrowserGym + 官方 webarena harness。
### 我们的 per-task 设计（已和讨论对齐）
每个任务：**检索注入 → N 条并行 rollout → 每条 LLM 判成/败(L1) → 对比 N 条(L2，按"多数对/错"分流) → 合并去重写库 → 下个任务用。单元 = 任务级可泛化策略（不是单步 fact），从源头避免灌水。**
- 必改：`judge_step` 从"逐步看 gold"换成"**跑完一个任务 → LLM 判成败 → 从整条轨迹抽**"。
### 机器
本机 **M4 Max / 64GB / Docker(33GB,10cpu) / ~308GB 空盘** → 够跑。注意：镜像大，**先起 1–2 个站**（如 shopping+reddit），别塞满盘；重批次夜里跑、并发调低，避免影响日常工作。

## 9. 待定决策（差异化 —— 决定这活儿是"复现"还是"贡献"）
- **(a) fact/reasoning 分离** 到底有没有用 → **当消融实验验证，别默认**（RB 单库就涨分；WebArena 无逐步 gold 时 fact 通道地基更虚）。
- **(b) L2 的"多数方向"门控** ≠ MaTTS，是个小差异点。
- **(c)（我最看好）"抗灌水 / 抗假成功 / 检索取得准"这套记忆质量机制** —— 我们真数据反复暴露、而 RB 只一句 prompt 带过。若能提出干净解法，本身就是贡献。

## 10. 后台正在跑（本机）
`stream_L1 / stream_L2 / stream_L1L2`（各 40 任务，n_traj=5，真 pipeline）。慢（~147s/withmem-task）。产物在 `runs/stream_*/summary.json` + `events.jsonl`。跑完要做：3 者 A/B 对比 + 逐步 reused/misled + 验证 L1+L2 在真 stream 里是否也灌水。
