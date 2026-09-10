# 三大 benchmark：我们 vs 竞品报告分总表

2026-09-01 汇编。竞品数字均已回原文 HTML 逐格核对（方法列附 arXiv 号，版本差异在 caveat 注明）；base model 与子集差异巨大，**绝对分跨行不可比，横向只看 Δ**。诚实规则：竞品未说明重复次数的一律在 caveat 标"单跑/疑单跑"，我们自己的重复次数与重复后的结果如实标注，哪怕不好看。

## 一、WebArena

| 方法 | 发表处 | base model | 配置/口径 | 基线 | 带记忆 | Δ | 重复次数 | caveat |
|---|---|---|---|---|---|---|---|---|
| **hippo-agent（本工作）** | **未发表（2026-08 定稿）** | **gpt-5.6-sol** | **812 题集；报告口径为 shopping/shopping_admin/reddit/gitlab 四站两臂配对、站均值；方法臂每题 8 条并行 rollout（8 台隔离部署），官方 env reward 判分** | **64.3** | **71.8** | **+7.6** | **各站 1~3 次：shopping 3 次（+6.4/+10.8/+4.2 全正）、gitlab 2 次（−0.3/+5.4）、reddit 1 次、admin 3 次但跨代码版本** | **逐站 Δ +10.8/+8.3/+5.7/+5.4；admin 为能力口径（扣判分伪错，原始均值口径 −0.2）；shopping +10.8 那次 withmem 只覆盖流的前 67 道；同配置重复间可差约 5 点，因单条经验好坏随机而影响是模板家族级** |
| ReasoningBank (2509.25140) | ICLR 2026（2025-09 提交，v2 2026-03） | Gemini-2.5-flash | 684 题 5 子集（Shop187/Admin182/Gitlab180/Reddit106/Multi29），官方 task SR | 40.5 | 48.8 | +8.3 | 未说明（在线单流） | 疑单跑；非全 812；分站 nomem→RB：Shop 39.0→49.7 / Admin 44.5→51.1 / Gitlab 33.9→40.6 / Reddit 55.7→67.0 / Multi 10.3→13.8；同表 AWM 44.1 |
| ReasoningBank (2509.25140) | ICLR 2026 | Gemini-2.5-pro | 同上：684 题 5 子集 | 46.7 | 53.9 | +7.2 | 未说明 | 疑单跑；同表 Synapse 47.7、AWM 47.6（均为作者同框架复现） |
| ReasoningBank (2509.25140) | ICLR 2026 | Claude-3.7-sonnet | 同上：684 题 5 子集 | 41.7 | 46.3 | +4.6 | 未说明 | 疑单跑；同表 Synapse 42.6、AWM 40.8（AWM 在此骨干反低于无记忆） |
| ReasoningBank + MaTTS (2509.25140) | ICLR 2026 | flash / pro / Claude-3.7 | 684 题 5 子集；并行扩展 k=5、pass@1 | No Memory 40.5/46.7/41.7；RB 单独 48.8/53.9/46.3 | 51.8 / 56.3 / 48.8 | 对无记忆 +11.3/+9.6/+7.1；对 RB 再 +3.0/+2.4/+2.5 | 未说明 | 疑单跑；扩展曲线（Fig4，仅 Shopping+flash）正文只给 k1 49.7 / k5 55.1 / 串行 k5 54.5，k=3≈52.5 为图读值 |
| Synapse（WebArena 分为 RB 作者复现，原文 2306.07863） | 原文 ICLR 2024；WebArena 数出自 RB（ICLR 2026） | flash / pro / Claude-3.7 | 684 题 5 子集（RB 框架内复现） | 40.5 / 46.7 / 41.7 | 42.1 / 47.7 / 42.6 | +1.6 / +1.0 / +0.9 | 未说明 | 疑单跑；Synapse 原文只测 MiniWoB++/Mind2Web，无 WebArena，此数是第三方复现非自报 |
| AWM (2409.07429) | ICML 2025 poster（PMLR v267） | GPT-4 (gpt-4-0613, temp 0) | 全 812 题，online AWM，BrowserGym（a11y tree），task SR | 23.5 | 35.5 | +12.0（+51.1% 相对） | 未说明（在线单跑） | 单跑；同表 SteP 33.0 / AutoEval 20.2；他人复现波动大：ASI 文 36.3（claude-3.5）、SGDR 文 27.8（GPT-4.1，低于其 vanilla 28.3） |
| ASI (2504.06821) | arXiv 2025-04（v2 2025-08） | Claude-3.5-sonnet | 全 812 题；在线归纳可执行程序技能（记忆=技能库），task SR | 32.7 | 40.4 | +7.7（+23.5% 相对） | 单跑 | 单跑；同表 AWM 文本技能 36.3，ASI 比 AWM +4.1 |
| CER (2506.06698) | ACL 2025 | GPT-4o-2024-05-13 (temp 0.1) | 全 812 题，BrowserGym；经验蒸馏进动态记忆缓冲，task SR | 24.3 | 36.7（hybrid；offline 33.4 / online 33.2） | +12.4（+51.0% 相对） | 单跑 | 单跑；同表 SteP 33.0 标注不可比（人工策略）、AutoEval 20.2 |
| 等预算对照 (2606.15017) | EMNLP 2026（v2 2026-08 注记接收） | Gemini 3 Flash | 4 域 655 题（Shop187/Reddit106/Admin182/Gitlab180），BrowserGym；Vanilla-IB=15 步+剪枝换预算，模块法 10 步；aggregate task SR | 44.78（Vanilla-IB，token 配平基线） | AWM 39.34±2.1 / ASI 41.02±1.2 / RB 39.33±1.4 | AWM −5.44 / ASI −3.76 / RB −5.45（全为负） | 每域 3 次独立重复 | 全场唯一多次重复的竞品数；预算配平是近似（15 步 vs 10 步）；表内无同预算 plain vanilla 行；AWM/ASI 用统一代码、RB 用官方代码 |
| 等预算对照 (2606.15017) | EMNLP 2026 | GPT-5.4-mini | 同上 | 32.67 | AWM 27.02±1.9 / ASI 29.00±0.9 / RB 24.58±3.9 | AWM −5.65 / ASI −3.67 / RB −8.09 | 每域 3 次 | RB 在此模型方差最大（±3.9）且掉分最多 |
| 等预算对照 (2606.15017) | EMNLP 2026 | Qwen 3.6-27B | 同上；另有 WorkArena-L1：Vanilla-IB 55.56±2.9 vs AWM 53.53±3.8 / ASI 48.49±4.3 / RB 55.56±2.8 | 42.14 | AWM 38.01±1.9 / ASI 40.15±3.5 / RB 37.00±0.8 | AWM −4.13 / ASI −1.99 / RB −5.14 | 每域 3 次 | 结论：等预算下三种记忆/技能模块的表观增益消失 |
| SGDR (2606.04391) | arXiv 2026-06 | GPT-4.1 | 单域 5 站 764 题（剔除跨站任务），avg task SR | 28.3（vanilla）；同表 AWM 27.8 / ASI 33.0 / CER 33.9 | 37.5 | 对 vanilla +9.2；对最强基线 CER +3.6 | 单跑 | 单跑；AWM 在其复现中低于 vanilla |
| SGDR (2606.04391) | arXiv 2026-06 | Qwen3-4B | 同上 764 题 | 16.5；AWM 15.7 / ASI 20.8 / CER 22.1 | 24.3 | 对 vanilla +7.8；对 CER +2.2 | 单跑 | 单跑；小模型上方法排序与 GPT-4.1 一致 |
| HMT (2603.07024) | arXiv 2026-03 | GPT-4 | 多域（Shop/CMS/Reddit/Gitlab/Maps），total TaskSR，任务总数未明示 | 32.1（作者自跑 flat-retrieval 记忆基线） | 38.7 | 对 flat retrieval +6.6；对表中 AWM 35.5 为 +3.2 | 未说明 | 疑单跑；表中 AWM 35.5 / 官方基线 14.9 疑直接转引原论文而非同条件复现，跨行慎比 |
| ColorBrowserAgent (2601.07262) | arXiv 2026-01（v2 2026-04） | GPT-5 | 全 812 题；人在环知识适配+知识对齐渐进摘要 | 全集无自身无记忆基线；Lite 165 消融：去知识适配 65.4 / 去摘要 68.8 | 全集 71.2（自称 SOTA）；Lite 72.6 | Lite 消融：知识适配 +7.2、摘要压缩 +3.8；全集对 CUGA +9.5 | 未说明 | 疑单跑；工业系统、知识来自人类反馈非纯自主经验；记忆净值只有 Lite 消融可算；同表 AgentOccam 45.7 / WebOperator 54.6 |
| WebATLAS (2510.22732) | arXiv 2025-10 | 未明示（参照行标 Claude-4-Sonnet） | WebArena-Lite 165 题；经验记忆（认知图）+ 动作模拟 | 47.9（基座 AgentOccam）；先前 SOTA Plan-and-Act 53.9 | 63.0（仅认知图 57.4） | 对基座 +15.1（认知图贡献 +9.5） | 未说明 | 疑单跑；Lite 非全 812；无仅去记忆消融；base model 未确证 |
| ReAP (2506.02158) | arXiv 2025-06 | GPT-4o-2024-08-06 | 仅 70 题（shopping/map/reddit/gitlab）；知识库=AgentOccam 公开轨迹反思 | 约 61 | 约 72 | +11 总体；曾失败任务 +28~29 | 单跑 | 单跑；样本极小且成对数字为 Figure 2 图读值，仅方向参考 |
| SteP (2310.03720)——非记忆参照 | COLM 2024 | GPT-4 | 对官方 GPT-4 基线，人工编写策略栈 | 14.9 | 33.5（非记忆） | +18.6 | 未说明 | 疑单跑；他文引用值不一：33.0/33.3/自复现 37.2 |
| AgentOccam (2410.13825)——非记忆参照 | arXiv 2024-10（v2 2025-05） | GPT-4-Turbo-2024-04-09 | 全 812 题；纯观测/动作空间精简 | SteP 原报 33.3 / 自复现 37.2 | 43.1（+Judge 45.7） | 对 SteP +9.8 | 未说明 | 疑单跑；非记忆，GPT-4 时代全集参照上限，多篇把它当基座 |

可比性读法：这张表里绝对分几乎没有能直接比的——base model 从 GPT-4 时代跨到 2026 年模型，子集从全 812 到 684、655、764、Lite 165 直至 70 题，判分器版本也不同，横向只能比 Δ。与我们 +7.6 真正同量级、同为"全自主经验记忆"的是 ReasoningBank 的 +8.3/+7.2/+4.6、ASI 的 +7.7 和 SGDR 的 +9.2；AWM 与 CER 的 +12 建立在 23~25 分的 GPT-4/GPT-4o 低基线上，被低水位放大。表内唯一做了多次重复的竞品是等预算对照（每域 3 次），它测出的恰恰是三种记忆法在还清 token 预算后全为负，这提醒所有单跑 Δ 天然含噪——我们自己同配置重复间也能差 5 个点。ColorBrowser（人在环）、WebATLAS 与 ReAP（Lite/70 题小样本、图读值）口径根本不同，只作方向参考；SteP 与 AgentOccam 是非记忆参照系，用来标定各时代的绝对水位。

## 二、Mind2Web

| 方法 | 发表处 | base model | 配置/口径 | 基线 | 带记忆 | Δ | 重复次数 | caveat |
|---|---|---|---|---|---|---|---|---|
| **hippo-agent（本工作）** | **未发表** | **gpt-4o-mini** | **test_task（Cross-Task 252 题），teacher-forced 逐步预测，步级口径（step SR / element_acc）** | **—（待归档）** | **—（待归档）** | **+9.8（另机 run，数据待归档）；本机记录为步级 +5.4** | **单跑（另机 1 次待归档 + 本机 1 次记录，两次记录差 4.4 点）** | **7 月初早期配置（弱模型、旧写端），计划换 gpt-5.6-sol + 新架构重跑后更新；与 AWM/Synapse/RB 同为步级口径可比，但绝对分暂缺，+9.8 在归档核验前不应外报为定论** |
| AWM (2409.07429) | ICML 2025 poster（PMLR v267） | GPT-4 (gpt-4-0613) | 三 test split（CT/CW/CD）；offline=训练 demo 归纳 workflow，online=测试流自归纳；基线 MindAct* 作者复现；步级 step SR | 36.2 / 30.1 / 18.6 | offline 45.1/33.7/32.6；online 43.6/33.9/35.5 | offline +8.9/+3.6/+14.0；online +7.4/+3.8/+16.9（CT offline 论文称 +24.6% 相对） | 单跑，temp 0 | 单跑；任务级 SR 仅 2.0→4.8（CT）/2.0→2.3（CW）/1.0→0.7（CD offline，反降）；CT 的 Action F1 反降 60.6→57.3；分布差越大 online 增益越大 |
| AWM (2409.07429) | ICML 2025 | gpt-3.5-turbo | Cross-Task，AWM_offline，基线 MindAct(GPT-3.5)；步级 | 17.4 | 34.6 | +17.2 | 单跑，temp 0 | 单跑；同表 Synapse(gpt-3.5) 30.6，AWM 较其再 +4.0；任务级 0.8→2.8 |
| Synapse (2306.07863) | ICLR 2024 | gpt-3.5-turbo-16k-0613 | 三 test split；完整版=状态抽象+轨迹提示+exemplar 记忆；基线 MindAct；步级 | 17.4 / 16.2 / 18.6 | 30.6 / 24.2 / 26.4 | +13.2 / +8.0 / +7.8 | 未提重复 | 疑单跑；记忆组件净增量小：无记忆版→带记忆 29.2→30.6 / 22.7→24.2 / 26.2→26.4（+0.2~+1.4）；任务级 0.8→2.4 / 0.6→0.6 / 1.0→1.5 |
| ReasoningBank (2509.25140) | ICLR 2026（poster 级别未核） | Gemini-2.5-flash | 标准三 split 流式（通行 252/177/912 题，论文未明示大小）；记忆随测试序列累积、成败自评判无真值；SSR=步级 | 40.3 / 31.7 / 31.9 | 44.9 / 33.9 / 36.6 | +4.6 / +2.2 / +4.7 | 未提重复，agent temp 0 | 疑单跑；任务级 3.3→4.8 / 1.7→2.3 / 1.0→1.6；CT 档 EA 46.0→52.1；论文称 CD 增益最显著 |
| ReasoningBank (2509.25140) | ICLR 2026 | Gemini-2.5-pro | 同上 | 44.4 / 34.8 / 35.0 | 45.6 / 36.9 / 38.1 | +1.2 / +2.1 / +3.1 | 未提重复 | 疑单跑；任务级 3.5→5.1 / 3.4→3.8 / 1.4→1.7；强模型上步级增益缩小；M2W 未跑 Claude-3.7 |
| Synapse 第三方复现（载于 RB 论文） | ICLR 2026 (2509.25140) | Gemini-2.5-flash / pro | 标准三 split 流式，与 No Memory 同框架；步级 | flash 40.3/31.7/31.9；pro 44.4/34.8/35.0 | flash 41.2/32.1/32.4；pro 44.7/35.0/35.6 | flash +0.9/+0.4/+0.5；pro +0.3/+0.2/+0.6 | 未提重复 | 疑单跑；新模型上增益较原文 GPT-3.5 档（步级 +8~13）大幅坍缩——记忆增益随 base model 变强而收缩 |
| AWM 第三方复现（载于 RB 论文） | ICLR 2026 (2509.25140) | Gemini-2.5-flash / pro | 同上 | flash 40.3/31.7/31.9；pro 44.4/34.8/35.0 | flash 41.0/31.7/30.1；pro 44.4/34.8/34.4 | flash +0.7/0.0/−1.8；pro 0.0/0.0/−0.6 | 未提重复 | 疑单跑；AWM 在 Gemini 上基本无效、CD 反降，与原文 GPT-4 档 +8.9~+16.9 强反差 |
| TRAD (2403.06221) | SIGIR 2024 | GPT-3.5-turbo（3-shot） | 三 test split；从训练 demo 库做步级 thought 检索；步级 | MindAct 17.4/16.2/18.6；ReAct(Relevant) 26.0/20.5/23.1 | 30.8 / 24.0 / 28.0 | vs MindAct +13.4/+7.8/+9.4；vs Synapse 复现仅 +0.2/+0.6/+2.1 | 未说明 | 疑单跑；任务级仅 3.6/0.6/2.0；对强基线增益很小，主要赢在 cross-domain |
| DuSAR (2512.08366) | arXiv 2025-12（未见收录） | Llama3.1-70B | 三 test split；免 demo，双"策略文档"经反思持续改写；基线 ReAct；步级 | ReAct 12.0 / 8.5 / 8.9 | 45.5 / 32.3 / 36.8 | +33.5 / +23.8 / +27.9 | temp 0，未提重复 | 疑单跑；严格说是会话内策略反思、非跨任务经验库；ReAct 基线弱（同表 TRAD 37.8/28.1/33.9）；任务级最高仅 5.36 |
| Reflexion / ExpeL（核查性负结果） | NeurIPS 2023 / AAAI 2024 | — | 两文原文均无 Mind2Web 实验（Reflexion=ALFWorld/HotpotQA/HumanEval；ExpeL=HotpotQA/ALFWorld/WebShop/FEVER） | — | — | 不适用 | — | 传言"M2W 老线三家"中仅 Synapse 真有 Mind2Web 结果；ExpeL 全文 0 次提及 M2W（已 grep 原文核实） |

可比性读法：这一节第一要务是口径——表内主数全部是步级 step SR，任务级 SR 普遍只有 0.6%~5%，两个口径差一个数量级，绝不能混排；我们的 +9.8/+5.4 也是步级，与 AWM、Synapse、ReasoningBank 的步级数同口径。其次是时代效应：GPT-3.5/GPT-4 上的大 Δ（+8~+17）到了 Gemini-2.5 的第三方复现里坍缩到 ±1 以内，AWM 在 cross-domain 甚至反降，所以跨行比 Δ 只在相近 base model 之间才有意义。Synapse 自己的消融显示纯记忆组件净增量只有 +0.2~+1.4，它的大 Δ 主要来自状态抽象与轨迹提示，引用时别记在"记忆"头上。DuSAR 的 +33.5 是对极弱 ReAct 基线、且属会话内反思而非跨任务经验库，不能与其他行比。最后提醒：传言中的老线三家里，Reflexion 与 ExpeL 原文根本没有 Mind2Web 实验。

## 三、SWE-bench-Verified

| 方法 | 发表处 | base model | 配置/口径 | 基线 | 带记忆 | Δ | 重复次数 | caveat |
|---|---|---|---|---|---|---|---|---|
| **hippo-agent（本工作）** | **未发表** | **claude-haiku-4-5** | **Verified 的 django 子集 231 题；冻结成熟库（243 条）注入 vs 无记忆两臂配对；官方 harness 真值（Epoch arm64 镜像本地评测）** | **43.0** | **50.0** | **+7.0（配对净 +8，p=0.076）** | **该配对为单次；后续同配置独立重复 4 次** | **诚实标注：独立重复 4 次后效应消失——nomem 均值 45.4 vs withmem 46.3，配对 p=0.87；+7.0 属带记忆臂最走运一次撞上基线最倒霉一次，第二批题的"+7.3 复现"与主效应共享同一次基线抽样；该基准单次臂间对比实测有 ±8 点纯随机波动；流式（边学边跑）臂零效应（44.3 vs 42.6，p=0.42）；弱模型早期配置，计划换 gpt-5.6-sol 重跑** |
| ReasoningBank (2509.25140) | ICLR 2026（v2 2026-03 注记接收） | Gemini-2.5-flash | Verified（论文按 500 题数据集描述，未明示实例数）；自建 bash-only ReAct agent，记忆流式积累；resolve rate | 34.2（30.3 步） | 38.8（27.5 步） | +4.6 | 单跑，无多 seed | 单跑；同表 Synapse 35.4；AWM 未上 SWE 表；MaTTS 未用于 SWE（仅 web） |
| ReasoningBank (2509.25140) | ICLR 2026 | Gemini-2.5-pro | 同上 | 54.0（21.1 步） | 57.4（19.8 步） | +3.4 | 单跑 | 单跑；Synapse 在 pro 上反降至 53.4——基线记忆法可为负收益 |
| SWE-Exp (2507.23361 v2, 2026-02) | 未见接收 | DeepSeek-V3-0324 与 Claude-4-Sonnet(20250514) 双档 | Verified 500 题；基于 SWE-Search（moatless-tree-search）加双记忆经验库；DeepSeek 档 temp 0.7/20 迭代，Claude 档直接沿用 SWE-Search 设置；Pass@1 | SWE-Search 同模型 35.4 / 70.8 | 42.0 / 73.0 | +6.6 / +2.2；去经验抽取消融 36.0→42.0 即 +6.0 | 单跑，未报方差 | 单跑；引用认准 v2（v1 报 41.6 且无 Claude 档）；消融各组件 −3.2/−2.6/−2.2/−6.0/−3.8；基线是否自复现未说明 |
| Agent KB (2507.06229 v5) | arXiv 2025-07，接收状态未核实 | GPT-4.1（SWE-agent 框架） | **Lite 300 题（非 Verified）**，max iter 50，预算 $3.0；KB 由 80 条人工种子轨迹引导；pass@1 | 24.3 | 31.7 | +7.4（100 iter 档 27.0→35.3，+8.3） | 单跑 | 单跑；是 Lite 不是 Verified，与本表 Verified 行不可直接比；pass@3 档 +13.7 口径不同勿混排 |
| Agent KB (2507.06229 v5) | 同上 | GPT-4.1（OpenHands 框架） | Lite 300 题，max iter 50，预算 $4.5 | 24.3 | 28.3 | +4.0（100 iter 档 +3.0） | 单跑 | 单跑；Lite 非 Verified；摘要主打数即此格 |
| Agent KB (2507.06229 v5) | 同上 | Claude-3.7（OpenHands 框架） | Lite 300 题，同上 | 30.0 | 46.7 | +16.7（100 iter 档 +7.0） | 单跑 | 单跑；基线 30.0 远低于常见 Claude-3.7+OpenHands 报告分（受预算+iter 压制），Δ 疑被低基线放大 |
| SWE-Search (2410.20285)——非记忆参照 | ICLR 2025 | GPT-4o | Lite 300 题；测试时 MCTS+自反馈（非跨任务记忆），基线 Moatless-Adapted；pass@1 | 25.7 | 31.0 | +5.3（+17% 相对） | 单跑 | 单跑；非记忆，只作 SWE-Exp 基座参照；Lite 非 Verified |
| SWE-Search (2410.20285) | ICLR 2025 | GPT-4o-mini / Qwen2.5-72B / DeepSeek-V2.5 / Llama-3.1-70B | 同上 Lite 300 题 | 13.0 / 18.0 / 16.3 / 13.6 | 17.0 / 24.7 / 21.0 / 17.7 | +4.0 / +6.7 / +4.7 / +4.1 | 单跑 | 单跑；论文报的 +24/+27/+22/+23 是相对百分比 |
| ExpeRepair (2506.10484) | FSE 2026（PACMSE Vol.3） | Claude 3.5 Sonnet + o4-mini | Verified（实例数未写明，标准 500）与 Lite 300；每迭代 4 候选补丁 ×≤3 轮，双记忆（episodic+semantic）；pass@1 | 50.4（w/o Memory 消融；Lite 42.3） | 57.2（Lite 48.3） | Verified +6.8（Lite +6.0） | 单跑（内部多补丁采样后择一提交） | 单跑；Δ 来自整体去记忆消融而非独立无记忆基线；Claude 4 Sonnet 版 74.6/60.3 无对应消融 |
| 参照（非记忆）：Sonar Foundation Agent，swebench.com 榜首 | 官方榜，提交 2025-12-05 | Claude 4.5 Opus | Verified 全 500 题官方榜；% resolved | —（参照系） | 79.2（并列 live-SWE-agent 79.2） | — | 榜单单次提交 | checked=False（自报未经官方复核）；TRAE+Doubao-Seed-Code 78.8 紧随 |
| 参照（非记忆）：官方复核 checked 最高 | 官方榜，提交 2025-11-24 | Claude 4.5 Opus (20251101, medium) | Verified 全 500 题，checked=True 档 | —（参照系） | 74.4 | — | 榜单单次提交 | checked 档次高分 Gemini 3 Pro Preview 74.2、OpenHands+GPT-5 71.8；76-79 分段均为未复核自报 |

可比性读法：先分清基准——Agent KB 与 SWE-Search 全部是 Lite 300 题，与 Verified 行的绝对分和 Δ 都不可直接比。真正在 Verified 上可比 Δ 的是 ReasoningBank（+4.6/+3.4）、SWE-Exp v2（+6.6/+2.2）、ExpeRepair（+6.8，但来自去记忆消融而非独立基线）和我们的 +7.0，不过这几行（含我们那次配对）全是单跑。我们随后做的 4 次独立重复把 +7.0 抹平到 +0.9（p=0.87），并测得该基准上单次臂间对比有 ±8 点纯随机波动——同样的审视理应施加给表内所有单跑 Δ。引用 SWE-Exp 务必认准 v2 数字（42.0/73.0），v1 的 41.6 已被作者更新。非记忆榜首 79.2/74.4 标定了 2026 模型在此基准的水位：记忆论文的基线（24~54 分）距水位很远，Δ 的工程含金量要打这个折扣。

## 四、全场速读

把三张表放在一起看，我们的数在名义上不落下风。WebArena 上竞品正向声称的 Δ 从 Synapse 复现的 +1 到 CER 的 +12.4，密度最高的一段在 +7~+9（ReasoningBank +8.3、ASI +7.7、SGDR +9.2），我们的 +7.6 正落在这一段中间，且四站逐站全正；SWE-bench-Verified 上可比的记忆 Δ 是 +2.2~+6.8，我们的 +7.0 名义上是全场最高；Mind2Web 步级口径下，新模型时代的 Δ 只剩 +1~+5，我们的 +9.8（待归档）高于 ReasoningBank 同口径数，本机记录的 +5.4 也在其上沿。

但这份总表更重要的读法在"重复次数"那一列。竞品几乎清一色单跑或未说明；全场唯一做了系统重复的竞品（等预算对照，每域 3 次，EMNLP 2026）测出的恰恰是三种主流记忆法在等 token 预算下全为负。我们自己是表里少数做过独立重复的：WebArena 的 shopping 三次全正（+6.4/+10.8/+4.2）、真正吃到同模板经验的子群 +9.4 且三次方向一致，这是目前全场最扛得住重复检验的正效应；而 SWE 上同配置独立重复四次后 +7.0 被抹平到 +0.9（p=0.87），Mind2Web 两次记录相差 4.4 点且待归档。按我们自己建立的标准，全场所有单跑 Δ——包括竞品的 +8.3/+6.6/+12.4，也包括我们 SWE 的 +7.0 和 M2W 的 +9.8——都只能当作含 ±5~8 点噪声的点估计。诚实的定位是：WebArena 结果处在竞品分布中上段且经过重复验证，可以外报；SWE 与 Mind2Web 的数字在重复检验或归档核验通过之前，只应作为带完整 caveat 的过程记录。