# 2026 自进化 benchmark 调研终版（2026-08-16）

三轮共 49 个 agent：一梯队 24（六路侦察+12 深读+5 对抗核实+裁决）、补深读 7（EvoClaw/CL-Bench 克隆仓库逐行读判分代码、MemoryArena 判分定案）、零约束重搜 9（八路、58 个已知之外新报 93 个、8 个多源共识）。

## 终版结论

主战场三张牌不变，自进化门票位定 CL-Bench：

1. **WebArena-Verified**（必做）：812 题审计修复版、确定性判分、env-ctrl 重置。治我们验尸钉死的三个坏通道，决定已有全部数字的公信力。首数 2-3 天，全量配对 1.5 周。
2. **WebChoreArena**（COLM26）：同四站 532 道加难题、117 模板成串、判分 95.5% 非 LLM。先打 admin 132 道纯 string_match，3-5 天。
3. **CL-Bench**（自进化门票，经克隆仓库级核实）：301 题六域、gain 指标原生同构我们的冻结配对、判分全本地零 LLM、Docker Hub 预构建镜像、官榜自带 ICL/Mem0/ACE 当对手。先打 poker+database 160 题，约一周首数。
   - 挑战者（核实后可换）：FinEvo-Bench（四路共识、协议同构，但代码未释出+Claude-judge 判分）；EnterpriseOps-Gym（四条全绿、ServiceNow、SQL verifier 0/1、34% 天花板，但非自进化原生、迁移密度待查）。SkillEvolBench 退居引用位。
   - SWE-Milestone/EvoClaw（ICML26 已接收、纯自进化榜第一）不当战场：98 题+10% resolve 地板，统计功效不够；当开场引文（"独立 >80% 塌到连续 38%"）和 future work。

零约束重搜的一句话答案：前两名反而更稳——全场仍无"任务成串+确定性判分+确认可得"三全且能替代它们的新环境。

写论文的负结论（related work 直接可用）：自训练谱系（AgentEvolver/AgentGym-RL/WebRL/AZR）没有为评测自进化造过任何新 bench；技能自创谱系全部在旧 bench 上评；lab 官方渠道 2026 零发布；2025-11 至 2026-08 涌现的十几个自进化 bench 全部是作者自报分、无一有外部提交榜。竞品事实标准 = WebArena + Mind2Web + SWE-bench-Verified，与我们三件套逐字重合。

必引清单速记：RoMeRL（memory-reward trap）、Experience-Sensitive Game Learning（"现有自进化增益噪且短暂"，与我们净值≈0 诊断同频）、SWE Context Bench（"精准经验↑/不过滤上下文↓"对位写端四病）、SkillEvolBench（"原始轨迹常胜蒸馏技能"对位 consolidation）、EvoAgentBench 负迁移句、2606.15017 等预算对比、COLM26 LLA workshop（9 月放榜回查）、AML coding track（上线即投）。

---
## 附录A：一梯队裁决全文
# 最终裁决:不开新环境战场,打三张牌——两张加固 WebArena 主战场,一张买自进化谱系门票

这是把 5 个侦察方向 90+ 个候选过完、12 个深读打分、5 个对抗核实之后的结论。先把裁决说死:**没有任何候选值得为它新写一套环境挂载**。所有真正的新环境(StuLife、MemoryArena、Evo-Memory、SEAGym、LifelongAgentBench、TimeWarp)都在代码成熟度、状态隔离或迁移密度上至少断一条腿。但"WebArena+SWE 已经足够"也不成立——我们现有结果有两个审稿人一眼能看到的伤口:判分器公信力(N/A 抽奖、exact_match 整句丢分是我们自己验尸钉死的)和 2026 新鲜度(WA 任务集是 2023 年的)。治这两个伤口的最优解恰好都不是新环境,而是 WebArena 自己的两个 2026 衍生品,外加一个便宜的原生自进化 bench。

## 一、值得打的前三

**第一优先:WebArena-Verified(ServiceNow,总分 45,对抗核实全过、数字全部独立复现)。** 这是同一个 WebArena 的 812 题全量审计修复版:修错题歧义题、判分器改成确定性(去掉 LLM-judge 和子串匹配,换类型感知比对 + HAR 网络迹验证,带双 checksum,可离线重判),每个容器内置 env-ctrl 重置 API。五条硬性质:迁移性满分——实测数据集 190 个模板、其中 119 个模板恰好各 5 道姊妹题,与我们测出的"同模板 1-4 近邻复用"作用域完全同构;真值满分——两类 evaluator 全部 0/1 本地可执行;自托管 9——镜像瘦身后 shopping 落盘 13.3GB、gitlab 31.6GB(注意 5.42GB/22GB 是 Hub 压缩尺寸),48 道跨站题需要 wikipedia 容器别漏;新鲜度 6——2025-12 发布、2026-03 仍在 push、browsergym 官方 pip 包,无 leaderboard,SKILL.nb 报 53.7% 未饱和;接入满分——复用 hippo.wa 加八台舰队,换镜像后用 env-ctrl 的 POST `/init` 替代自制重置(**没有 `/reset` 端点**,核实过源码),终答改其 JSON schema(`task_type`/`status`/`retrieved_data`/`error_details`)。它直接连根治掉我们验尸出的三个坏通道,并且让 688→812 全量覆盖变成正当可行:改状态题靠 env-ctrl 重置 + 八台隔离,不再需要排除。首个数(单站检索题子集重跑)2-3 天;全量 812 配对约 1.5 周,唯一新增工作是给 Playwright 加 `record_har_path`(现有 harness 没收 HAR,查过了)。论文角色:这不是第三战场,是主战场的判分公信力升级——比任何新战场都优先。

**第二优先:WebChoreArena(总分修正后 42-43,对抗核实数字全部吻合)。** 同四个 WebArena 站上 532 道手工"苦役"任务,117 模板、每模板 1-7 实例中位 5,COLM 2026,v2 是 2026-08-08。判分实测 string_match 423 / url_match 42 / program_html 99,fuzzy_match 仅 24 道占 4.5% 且 admin 站 132 题全部纯 string_match——正合我们的 grader 纪律。GPT-5 仅 45.1-48.3%、GPT-4o 6.8%,远未饱和,在线 leaderboard 活着。接入成本全场最低:config 是 WA 格式超集、task_id 从 10000 起不撞、直接换任务文件复用现有舰队;65 道跨站题每道只涉 2 站(其中 18 道要第 5 站 kiwix wikipedia),可后置。首个数:shopping_admin 132 道纯 string_match 两臂配对,3-5 天。两个如实标注:任务集 2025-06 即公开,对 2025 年中后训练的模型有污染窗口;其难点设计偏长上下文/海量记忆而非经验复用,报数必须按模板近邻迁移口径拆,不能把整体分当记忆效应。论文角色:主结果的加难延伸——"同基建换更难任务流,机制还成立吗"。

**第三优先:SkillEvolBench(总分 42,对抗核实通过,带三处修正)。** 180 题 = 30 任务族 × 6 角色,每族 3 道习得任务顺序呈现(流内可更新库)+ 3 道冻结部署(context-shift/对抗/组合)——习得/部署切分与我们"流内学习 + 冻结库配对评测"协议同构,这是全部原生自进化候选里唯一结构、判分、代码三样都实的。判分本地规则式,但核实出关键细节:**Ba 要求 outcome 与 process 测试全部通过**(接判官时不能只跑 outcome,否则与论文不可比);113/180 任务无 hidden 拆分;环境是静态资产 + 容器内本地 mock 服务,无外部活依赖。no-skill 最佳 ESR 38.9%(Sonnet 4.6,修正过原稿的 35.6),远未饱和。接入复用 SWE 挂载的容器 + 本地测试执行模式,绕开 Harbor 调度但要满足 test.sh 的 env var 与 reward.txt 契约,先接 E1+E3 约一周出首数。风险照实写:7 星 1 fork,leaderboard 全是作者自报,买的不是榜位而是两句话——"在原生自进化 bench 上机制也成立",以及和它核心发现"raw-trajectory 复用常胜蒸馏技能"的直接对话(这正是我们 L2 写端质量诊断和 consolidation 修法的对位靶子)。

**明确落选与理由(敢下结论部分)。** EvoAgentBench 降为"必引 + 可选只打 SWE 域":对抗核实发现 GDPVal 是 pairwise LLM-judge(比 rubric 更依赖参考侧)、judge 模型未钉死、harness 代码只支持四域而 HF 数据已五域、leaderboard 绑死 OpenClaw/Nanobot,我们的数上去不可比;它那句"every automatic method still exhibits negative transfer in at least one setting"当靶子引用比参赛值钱。TimeWarp 否决:核实发现论文全部基线分是 GPT-5-judge 判的,repo 里的确定性 verifier 是发表后补建且自认更严——我们的数与其基线根本不可对表;且 goal 跨 6 个 UI 版本答案不变,记忆会退化成背答案;3 星、代码 repo 无 LICENSE 文件。StuLife 单条持久世界与 N=8 配对冲突(要 deepcopy 分叉),计分一半压在考试知识回忆;MemoryArena 是单 commit 无 license 的 preview;Evo-Memory 与 LifelongAgentBench 停更且后者大概率被 gpt-5-mini 打穿;SEAGym 任务源一半是 HLE 一次性考题、repo 官方性未坐实。SWE-Bench-CL 不当战场但白嫖协议:它把 Verified 重组成同仓时序串的划分和 CL 指标(遗忘/前后向迁移)可直接套在我们已有 SWE 数据上重述一组口径,零成本;项目本身 2025-05 停更、从未报过任何模型分,当战场等于替死人抬轿。

## 二、2026 自进化 bench 生态一页综述

**存在什么:品类已经成潮,标尺还没诞生。** 从 2025-11 到 2026-08 不到十个月里,明确面向自进化/经验积累/持续学习的 bench 密集出场:Evo-Memory(2025-11,GDM,流式任务流)、SWE-Bench-CL(2025-06,CL 协议)、MemoryArena(2026-02,跨 session 互依)、SkillFlow 与 SkillLearnBench 与 SEA-Eval(2026-04)、EvoMemBench 与 SkillEvolBench 与 MemGym 与 BenchTrace(2026-05)、SEAGym(2026-06)、EvoAgentBench(2026-07),加上 lifelong 谱系 LifelongAgentBench(2025-05)→StuLife(2025-08),和 2026-07-29 上线的 Agent Memory Leaderboard(20+ 机构联合,文本 track 已上线、coding track 未放出)。COLM 2026 连办第二届 Lifelong Agents workshop,方向已建制化。

**不存在什么:这一批全部是自报分。** 星数从 2 到 96,没有一个有外部提交的 leaderboard,没有一个被任何竞品方法当主战场。基础设施还在真空期:PapersWithCode 2025-07 关停,普林斯顿 HAL 2026-08 停收提交,AML coding track(12 仓库 150 任务、与我们 SWE 线同构,最值得盯)尚未公开。同时满足"模板成串 + 确定性判分 + 活跃社区 + 未饱和"四条的新环境一个都没有——最接近的就是 WebArena 的两个 2026 衍生品,这正是前三名有两个是 WA 衍生的原因。

**竞品在哪评:WebArena+SWE-Verified 就是 2026 记忆线的事实标准。** ReasoningBank(Google,ICLR'26 线,最强竞品)= WebArena + Mind2Web + SWE-bench-Verified,与我们的三件套逐字重合;AWM 在 WebArena/Mind2Web;ACE/Metis/MemSkill 一族聚在 AppWorld;Memento 一族在 GAIA/HLE(开放工具任务,与我们作用域不同);对抗性论文《Are Online Skill and Memory Modules Always Worth Their Tokens?》(2606.15017)在 WebArena 三域 + WorkArena-L1 做等 token 预算对比。没有任何竞品把主结果押在上面那批原生自进化 bench 上。

**领域的举证标准已经换了。** 四条已发表的元结论合起来定义了 2026 年这个方向的审稿共识:EvoAgentBench 说没有自动方法在所有设置保持净正收益;SkillEvolBench 说原始轨迹复用常胜过蒸馏技能;2606.15017 说等预算下裸基线追平 AWM/ASI/ReasoningBank 全部三种;LifelongAgentBench 说朴素 replay 低效。问题已经从"记忆有没有用"变成"你的测量能不能排除预算、方差和判官假象"——而这恰好是我们配对协议、多次重复、判分通道拆解正在做的事。

## 三、论文定位:评测选择怎么讲最强

**场地正当性不需要道歉,需要三层讲法。** 第一层,同场可比:我们的 WebArena + SWE-Verified(+ Mind2Web 挂载)与 ReasoningBank 的配置完全重合、与 2606.15017 的场地重合,审稿人无法说我们挑了软柿子;2026 原生自进化 bench 全部尚无第三方公信力,把主结果押在那里反而不可审。第二层,覆盖与测量纪律是差异化:全场没有竞品做过 812 全量两臂配对(都在跑子集),我们用八台部署解决了改状态题的隔离;逐题配对自带剂量对照(未注入经验的 34 道差值恰好 0.000);同配置三次重复方向一致;判分通道拆开报(N/A 抽奖与 url_match 自制假阳是我们自己揭的)——这四条正是 2606.15017 向全领域提出而竞品普遍缺的,建议再主动补报等 token 预算口径,正面回应该文。第三层,作用域诚实当卖点:实测记忆作用域是同模板 1-4 道近邻(+9.4 点/相对 +23%),跨模板 +0.6 测不出——这是本领域第一个把作用域直接测出来的工作,EvoAgentBench 的 Ability Graph 和 SkillEvolBench 的族结构都在假设这个作用域存在,我们给了测量。SWE 线则把 Verified 上"+7 经四次重复归零、单跑 ±8 点噪声"的撤回当测量纪律贡献报,不当失败藏。

**缺什么补什么,按优先级。** 缺判分公信力——上 WebArena-Verified,重跑加重判,三个坏通道连根去掉,这是唯一"必须做"。缺 2026 新鲜度和未饱和难度——上 WebChoreArena 的 shopping_admin 132 道,同基建数天出数。缺自进化谱系归属——上 SkillEvolBench 一套数(退而求其次打 EvoAgentBench 的 SWE 域),换来"原生自进化 bench 上也成立"一句话。引用层白嫖不跑:SWE-Bench-CL 的 CL 指标重述我们 SWE 数据、BenchTrace 呼应写端四病诊断、EvoMemBench 与 Evo-Memory 作 related work 的方法对比口径、WebCoach 作最近邻方法对比、COLM Lifelong Agents workshop 证方向建制化、AML coding track 标记为"上线即投"。三件全做约 2.5-3 周可并行完成;若只能做一件,做 WebArena-Verified——判分器的公信力决定我们已有全部数字的生死,新战场只决定论文的宽度。
---
## 附录B：纯自进化榜（无基建偏置，补深读后）
核实材料读毕(简报、上轮裁决 /tmp/bench_verdict.md、三份对抗核实、/tmp/clbench 与 /tmp/swem-site 原始数据复核)。以下为纯自进化榜最终版。

# 纯自进化榜·最终版(四维:迁移性/真值/自托管/新鲜度,不含接入成本)

## 一、全部原生自进化候选四维重排

去掉基建偏置后榜首换人:本轮两个新核实对象顶掉了上轮的门票持有者 SkillEvolBench,而 MemoryArena 的 ICML 徽章救不了它的尺子。分数为折入对抗核实修正后的重打,不是旧总分减接入项。

1. **SWE-Milestone/EvoClaw,38(迁9/真10/托9/鲜10)**。98 个 graded 里程碑在 7 仓内成依赖 DAG(graded 集 77 边、39 Strong,go-zero/nushell 深到第 8 层),同仓经验天然向后传;判分纯测试执行、零 LLM、fail-closed、digest 钉死可离线;ICML 2026 已接收(venue "ICML 2026 regular")、repo 2026-08-01 还在 push、28 模型活榜、Opus 4.6 resolve 仅 11.2-11.6% 远未饱和。扣分:浅仓(dubbo)迁移信号弱,8 臂分叉要靠 snapshot 自建协议。
2. **CL-Bench,36(迁10/真9/托9/鲜8)**。全榜唯一"隐结构就是为经验积累设计"的 bench:301 题六域(poker 120 五阶段、BSM 90 三阶段、database 40 前后漂移、cohort 20、codebase 19、sales 12),gain 指标原生就是我们的冻结配对协议;判分全本地零 LLM,六域皆有官方 success 阈值;Apache-2.0、Docker Hub 预构建镜像、逐题独立容器,8 臂隔离零成本。扣分:纯 arXiv preprint、repo 自 7-18 零 push、榜 12 条全作者自报。
3. **SkillEvolBench,33(迁10/真8/托9/鲜6)**。30 族×(3 习得+3 部署)与我们协议同构、本地规则判分,但 113/180 无 hidden 拆分,7 星 1 fork、榜纯自报,社区热度趋零。
4. **EvoAgentBench,31(迁9/真6/托7/鲜9)**。Ability Graph 设计好、2026-07 最新,但 GDPVal 域是未钉死 judge 的 pairwise LLM 判分,harness 只支持四域而数据五域,榜绑 OpenClaw/Nanobot 不可比。SWE 域单打可救,整体不行。
5. **SWE-Bench-CL,29(迁8/真10/托9/鲜2)**。协议是好协议,项目是死项目(2025-05 停更、从未报过模型分)。当指标语言白嫖,不当战场。
6. **EvoMemBench,约27**(本轮未复核,按深读折算,不进前列)。
7. **MemoryArena,26(迁7/真5/托6/鲜8)**。ICML 已接收是真的(decision note 实证),但五域里只有 shopping 是纯程序判分;search 绑 gpt-4.1 judge 无回退、formal 判官=解题者同后端、travel 相似度截断可构造满分且全员 SR≈0;代码单次 dump、无 license。对我们这种把 grader 纪律当卖点的论文,真值 5 分即事实否决。
8. **StuLife,25(迁9/真6/托4/鲜6)**。终身流是真流,但单条持久世界与 N=8 配对结构性冲突(deepcopy 黑改),计分一半压在考试回忆。
9. **SEAGym,约22**。任务源一半 HLE 一次性考题,迁移性先天不足,官方性未坐实。
尾注:Evo-Memory 与 LifelongAgentBench 停更淘汰,TimeWarp 因"基线全靠 GPT-5-judge、答案跨版本不变会退化成背答案"维持否决。

## 二、只加一个原生自进化战场:打 CL-Bench,首数约一周

榜首是 SWE-Milestone,但"最好的 bench"不等于"我们这一个名额该给谁",三条硬理由让位:第一,统计功效。SWE-Milestone 全库只有 98 个串行里程碑且 resolve 地板极低——官榜 flash/小杯档在 navidrome 0/9、element-web 1/18、dubbo 1/12(site CSV 实算),我们在 SWE-Verified 上"+7 分经四次重复归零、单跑 ±8 点"的教训直接适用:在 ~10% 基率、n=98 的配对二值上测 +3-5 点差值,重复一次要多日和整轮 frontier 成本;CL-Bench 是 301 题、官方 runs=5、题小可廉价堆重复。第二,对表面。SWE-Milestone 榜上零记忆方法,当第一固然新,但 silent mode 信息边界决定我们的判官式学习本就无法与官榜同协议,数字孤悬;CL-Bench 官榜就有 ICL·Sonnet 4.6(reward 0.196/gain 0.241)、Mem0(gain 0.224 按 gain 第 3)、ACE(双口径垫底),这正是论文需要的那场架——赢的标准要按核实口径写死:reward 和 gain 双指标同时压过 ICL 与 Mem0,点名 ACE,不混用论文口径(ACE 8.6%)与 7-18 重归一化后的现榜口径(7.65%)。第三,机制咬合。database 域漂移拆分(20 pre/20 post 换 products_drifted.db)加"答错才喂真值"的边界,恰好是我们 WA 上 t168 参考答案反噬和写端四病的天然考场——bench 按设计惩罚背答案式记忆,等于替我们验证 consolidation 修法;cohort 域"分数永不示 agent"与我们判官知真值/agent 答案盲的分工完全同构。

打法与工期:挂载新写但薄——复用其逐题独立容器与 baseline 配对协议,判官按官方 InstanceOutcome 阈值二值化,gain 就用它原生定义;约 3-4 天挂载,先跑 poker+database 两域 160 题两臂配对(覆盖阶段课程与分布漂移两种流形态),**开工第 7 天前后出首个配对数**;全六域 301 题、Sonnet 4.6 主报对官榜、gpt-5-mini 附报证跨模型,约 2.5 周收全。落地细节三条防雷:sales 域 mode=replicate 别照抄 permute;codebase 奖励是成功时 1−(solved_step−1)/max_steps;逐域披露判官的真值访问与官方基线的信息差。SWE-Milestone 不弃——转为引言动机(独立任务 >80% 塌到连续 38.03% 是全文最好的开场引文)与 future work 前瞻位,若后期富余,可在 go-zero 单仓按官方单臂协议跑一个带记忆 demo 进附录,不进主表。

## 三、与 WebArena-Verified / WebChoreArena 的组合

三场一个协议一张表:统一用 CL-Bench 的 gain 语言报逐题配对差,故事线是"同一机制,三种考卷"——WA-Verified 是修好的尺子(主战场,812 全量配对、判分通道拆解、作用域测量:同模板近邻 +9.4 点/跨模板 +0.6),WebChoreArena 是更难的流(同基建 2026 难度,532 题里先打 admin 132 道纯 string_match,按模板近邻口径拆报,污染窗口如实标注),CL-Bench 是专为记忆设计的考场(自进化谱系门票 + 与 ICL/Mem0/ACE 同场对表 + web/SWE 之外的域宽度)。三者互为免疫:审稿人质疑尺子,答 WA-V 确定性重判;质疑饱和与新鲜度,答 WCA(GPT-5 仅 45-48%);质疑"换个为记忆而设的场子还成立吗",答 CL-Bench。资源上互不相抢:八台舰队跑 WA-V(首数 2-3 天、全量 1.5 周)并行 WCA admin(3-5 天),CL-Bench 走本地 Docker,三线并行 2.5-3 周全落地。基模配对明写:WA 线沿用 gpt-5-mini 与既有 688 题配对保持连续,CL-Bench 主报 Sonnet 4.6 以对齐官榜。若被迫砍到两场,砍 WCA 留 WA-V+CL-Bench——尺子公信力加谱系归属是最小完备集;CL-Bench 内部若砍,先 poker+database+codebase 三域 179 题再补全。引用带不跑:SWE-Milestone 作动机与前瞻、SkillEvolBench 的"原始轨迹常胜蒸馏技能"对话我们的 L2 consolidation、EvoAgentBench 的负迁移句、SWE-Bench-CL 的 CL 指标重述既有 SWE 数据、AML coding track 上线即投。

证据文件:/tmp/bench_verdict.md(上轮裁决)、/tmp/pure_evo_brief.md(本轮规矩)、/tmp/clbench(HEAD 5f8c50e,六域 schedule 复核)、/tmp/swem-site-1786948627/data/trial_results.csv(小杯档 resolve 地板实算)、/tmp/swemv-1786948439、/tmp/memoryarena;三份对抗核实结论已全部折入分数与口径。
---
## 附录C：零约束重搜汇拢（93 个新候选与负结果）
Both flags resolved as far as titles go. Now the consolidation.

# 八路重搜汇拢(2026-08-16)

## 1) 黑名单外新候选清单(去重后约 93 条,其中至少一路看好 42 条)

**多源共识(≥2 路独立命中,本轮最硬信号,共 8 条):**

- **FinEvo-Bench** (arXiv 2608.06144, 2026-08-06) — **4 路命中、4 路全看好,全场唯一共识**。北航×阿里 Qwen DianJin,120 个真实金融任务/20 业务场景排成打乱交错的纵向流,原生做"进化 vs 非进化"配对对照(报告 +9.33~19.37 分)。判分=机构 rubric+Claude(Opus 4.6) judge,可复核非本地 0/1;四路都没找到代码/数据,可得性未坐实。
- **EnterpriseOps-Gym** (2603.13594, 2026-03) — 3 路。ServiceNow,1150 专家任务×8 域、512 工具+164 表容器沙箱,SQL verifier 只核对终态数据库(均 5.3 条件)=本地 0/1;Apache-2 开源确认(GitHub 119 星活跃+HF dataset);最好模型 34.1%,余量大。非为自进化设计,流要自组。
- **PACE-Bench** (2608.14441, 2026-08-14) — 3 路。THUNLP 物理域代码进化,144 源→目标适应对,沙盒诊断反馈迭代改造,0/1 可判,开源确认(thunlp,CC-BY)。流性中等:对内迭代、对间较独立。
- **TimeSage-EV** (2608.14270, 2026-08-14) — 3 路但 2 看好 1 降级。活基准 1485 场景-期次 QA,扣留未来真实发布为真值,承诺月更+代码+榜。争议:标题的 evolving 主要指数据流而非 agent;月更对论文可复现是双刃。
- **Social Gym + SPaRTan** (2608.09128, 2026-08-10) — 2 路全看好。CMU 系,21 个多人社交游戏+Elo,规则判胜负=本地 0/1;SPaRTan 免训练自博弈:复盘→可迁移 playbook→下局注入,对 GPT-5-mini 有效、Qwen3-32B 无效。代码未确认。
- **PATH-Bench** (2608.01149, 2026-08-02) — 2 路。已核实全名 "PATH-Bench: Path-Dependent Evaluation of Lifelong Agents":受控"有益/干扰历史"序列专测经验路径依赖,报前后向迁移+遗忘,附 Selective Experience Use 基线。代码未确认。**消歧警示:与黑名单"PAST-Bench"一字之差,若黑名单那条是此篇的笔误应剔除,请对一下你的黑名单出处。**
- **AgentCL** (2606.02461, 2026-06-01) — 2 路。受控组合式任务流(前序子解/证据/工作流对后续可复用)+naive 流对照,附 MemProbe 入库过滤探针(与我们 consolidation 修法同构)。代码未确认。
- OpenSciToolBench (2607.28692) — 2 路命中但两路皆不看好:在审、判分与释出均未确认。

**消歧后剔除:** 路 4 报的 Continual Learning Bench (Asawa, 2606.05661) 已核实官方题名就是 "Continual Learning Bench",即 CL-Bench——大概率就是黑名单里无描述的那条,默认剔除(除非你黑名单里的 CL-Bench 指 Dou 2602.03587 的 context-learning bench,那就恢复此条)。

**单源、标看好(34 条,按类分组):**

*环境/任务流型(15):* VibeLifeBench(2608.10875,200 任务×20-30 阶段,1247 条原子检查直读后端状态,20 题子集开放、全集邮件申请)、EnterpriseMem-Bench(2605.26394,JPMC 多轮 Text2SQL,execution accuracy 0/1,自带 Memory Benefit Score=现成"记忆净值"度量,repo 未找到)、SWE Context Bench(2602.08316,1100+376 同仓相关 issue 按真实依赖分组专测经验复用,自证"精准经验↑/不过滤上下文↓",释出未确认)、Endless Terminals(2601.16443,3255 容器终端任务 completion test 0/1,为自进化 RL 造的无限流原料,释出未确认)、CEO-Bench(2606.18543,500 模拟天经营,期末现金完全客观,代码未确认)、Business Arena(2608.08621,30 天电商,期末净资产账本全透明,代码未确认)、EvoEnv(2601.08173,ACL26 Findings,职场流式任务且"从经验持续学习"是显式评测维度,开源 KnowledgeXLab)、MyPCBench(2606.16748,共享 persona 桌面 184 任务、类 WA 用法,rubric+LLM judge,已发布)、FutureSim(2605.15188,真实事件时序回放,0/1+Brier 全客观,repo 未放)、CRMArena-Pro(2505.18878,旁证 CRMWeaver 共享记忆在其上有效,repo 活跃但要 Salesforce org,2025-05 偏老)、MemGUI-Bench(2602.06075,64 镜像对+pass@k 设计漂亮,但 LLM judge 管线+移动基建重)、ScenDroid / DomusMind / ShopGym(三个 ICLR26-LLA/ICML26 workshop 货,设计对口但全没找到代码)、FinPerMA(2608.04095,Post-Shock 检查点个性化,客观 accuracy,未释出)。

*技能/工具/自改进型(6):* SkillsBench(2602.12670,技能库谱系事实评测标准,确定性 verifier、开源,但任务独立单题、流需自构)、SWE-Skills-Bench(2603.15401,565 任务 0/1、开源,技能边际效用)、Tool-Genesis(2603.05578,2150 任务工具自创诊断,L1-L3 客观,GitHub 直链未见)、MMG2Skill(2606.01993,教程→技能→rollout 闭环自进化,自带 130 任务 bench 跨 OSWorld/Minecraft/RLCard,承诺公开)、AutoWorldModel-Bench(2608.11216,EA,固定预算闭环自改进 world-model,客观指标)、Evo-Bench RUC-AIBOX(2608.09096,harness 自进化专用,GitHub 未见)。

*游戏/episode 型(5):* PTCG-Bench(2605.29653,原生"多局经验自进化"双层设计,胜负 0/1,开源 zjunet)、SciCrafter(2604.24697,红石"发现→沉淀→应用"课程流,程序化 0/1,开源但 2 星单 commit)、Experience-Sensitive Game Learning(2608.07490,专测经验驱动行为变化,结论"现有自进化 agent 增益噪且短暂"与我们同频,代码未确认)、J-TTL/EvoTest(2510.13220,Jericho 跨 episode TTL,客观得分、成本极低,代码未确认)、EmbodiedBench(2502.09560,本体老,价值=ELITE/BrainMem/RoboMemory 等 5 个 2026 记忆自进化方法的现成比武场)。

*环境合成/平台型(4):* CUA-Gym(2605.25624,RLVR 确定性 reward,开源待查)、Gym-Anything/CUA-World(2604.06126,CMU 全开源 CC-BY,1 万+长程任务)、D3-Gym(2604.27977,239 科研仓库 565 任务,自动评测与人工 87.5% 一致,开源)、Prime Intellect Environments Hub(在线环境集市,verifiers 标准)。

*记忆读端/个性化型(4):* PerMem-Bench(2605.25535,开源,MRR 对照真值记忆,写端质量对口)、LongMINT(2605.18565,开源,EM,干扰专项)、MobileMem(2608.13606,开源 zjunlp,年尺度个人经验流、偏召回)、SE-Bench(2602.04811,开源 thunlp,0/1,知识内化诊断盘)。

**单源、报了但不看好(约 50 条,留作 related work 索引):** 方法非 bench 类(SkillRise、RoMeRL[点名 memory-reward trap,竞品必读]、SEAL、NanoResearch、FlashEvolve、Ouroboros、KnowAct-GUIClaw、Experience Makes Skillful、Rethinking How to Remember、ToolMaker/TM-Bench);安全与诊断类(AuthMem-Bench 权限坍塌、SkillMisevo-Bench 技能误进化、Trust-Memevo 记忆误进化、MemSyco-Bench 谄媚污染、ScrambleToolBench 不用自家知识、Set-shifting 流内改道、ShiftBench、Streaming Memory Benchmark);记忆 QA/具身类(AMA-Bench、WorldMemArena[已核与黑名单 MemoryArena 非同物]、RoboMemArena、LMEE-Bench、StreamMemBench、MemoryCD、SWITCH、LifeSide、LongAct、MineNPC-Task);判分或流性不达标类(RealPref 纯 LLM 判、FinEvolveBench[2606.06960,注意与 FinEvo-Bench 是不同论文]市场收益高噪+低重复、MirrorCraft 单集适应、Alem、RTSGameBench 出题侧自进化、PokeGym 商业游戏、SAGE、CirrusBench、OlaBench、IBA-Bench、EnterpriseClawBench 数据不放、EnterpriseLab、DSGym、Agents' Last Exam、skyrl-gym/GEM/InternBootcamp 训练向、SkillCorpus 资源库、OpenEarth-Bench、OmegaUse-OfficeVal/SaaSBench/DocOps 标题级未核)。

## 2) 按四条软要求粗评:值得深读的前几名

四条(流性/客观信号/可得性/新鲜度)全绿的只有一个,从它排起。

**第一:EnterpriseOps-Gym。** 唯一全绿:持久状态沙箱上的同环境任务流、SQL verifier 本地 0/1、开源确认且活跃、2026-03,外加 34% 的巨大余量和三路独立命中。深读只需回答一个问题:1150 个任务在域内是否成串(有没有 WA 那种模板姊妹结构)——迁移密度正是上一轮枪毙一票候选的刀,也是它能否推翻"没有值得新写挂载的环境"这句裁决的唯一变数。它与 WebArena-Verified 同为 ServiceNow 出品,谱系叙事顺。

**第二:FinEvo-Bench。** 四路全命中全看好,且它就是"我们协议的 bench 化"(纵向流、边学边用、进化 vs 非进化配对)。流性新鲜度满分;判分 Claude-judge 打八折(可复核但非 0/1,与我们 grader 纪律相性差);命门是四路都没找到代码。行动:深读+立刻查释出/邮件作者;坐实可得就顶上"谱系门票"位,坐不实降为 related work 头号锚点(其 +19.37 分是"经验保留有增益"主张的外部印证)。

**第三:Social Gym + SPaRTan。** 全场客观信号最干净的原生自进化候选(规则胜负+Elo),playbook 机制与我们两层提炼最像,且自带"提炼质量敏感"(GPT-5-mini 行/Qwen3-32B 不行)这个可对话结论,8 月 10 日极新。命门同样是代码未确认。

**第四:SWE Context Bench。** 单源但性价比突出:同仓 issue 依赖分组专测经验复用,SWE 式判分,与我们现有 SWE 挂载几乎零成本对接;其"精准经验显著提升、不过滤上下文负收益"与我们写端四病诊断互证。释出未确认,查实即接。

**第五(打包):PATH-Bench + AgentCL。** 当协议镜子而非战场:正/负历史路径依赖与 MemProbe 入库过滤,分别对位我们的净值≈0 诊断与 consolidation 修法。代码都没出,先进必引清单,释出后再议(PATH-Bench 先做黑名单消歧)。

第二梯队留档:PTCG-Bench(开源+0/1+原生多局进化,小而干净的补充战场)、VibeLifeBench(原子检查信号硬、20 题子集当天可跑,但阶段流是任务内不是跨任务)、PACE-Bench(开源+0/1 但流性中等)、MMG2Skill、EvoEnv、CEO-Bench/Business Arena(信号最硬的经营双子,可得性未确认且与 N 次并行协议要大改)。

## 3) searched_but_empty 汇总(负结果,related work 可直接用)

自训练谱系没有为评测自进化造过新 bench:AgentEvolver 只评 AppWorld+BFCL v3,AgentGym-RL 全用旧环境,WebRL=WebArena-Lite,DigiRL 后继全在 AndroidWorld 系,AZR/R-Zero/rStar 系只评静态 math/code 题集——这条线的新东西全部长在环境合成/gym 侧(CUA-Gym、Gym-Anything、D3-Gym、Endless Terminals)。技能自创方法 2026 全在既有 bench 上评(MUSE-Autoskill/CoEvoSkills/SkillRL/Skill Self-Play 等→SkillsBench),无一自带新环境,"流内技能积累"的原生 bench 在该谱系仍是空位。客服/企业线:τ-bench 系无带持续改进协议的后继,CRMArena 无官方新版,WorkBench/OfficeBench 无后继,PrefEval 无官方 V2,流式 Text2SQL 仅 EnterpriseMem-Bench 一家有经验流设计。游戏线:NetHack/Kinetix/Habitat 3 均无 lifelong 任务流新评测,MineStudio 无后继、MCU 止于 2025-10,Odyssey 无明确后继。会议线:COLM26 LLA 第二届接收列表未公开(官网未挂+OpenReview 反爬),**9 月放榜必须回查**;ICML26 AI-for-Math 的 13 个新 bench 全是一次性数学题;ICLR26 RSI workshop 127 篇几乎全方法文。lab 官方渠道:Anthropic/GDM/Meta/Qwen/Moonshot/智谱 2026 均无 agent 持续学习评测发布,HN 零命中。

系统性盲区如实记:八路 WebSearch 配额全部耗尽(200/200),全程改走 arXiv API/WebFetch/GitHub API;X、新闻稿、Google Scholar 未覆盖,HF daily 仅抽样 22 天。但多路在 arXiv 侧大量重复命中黑名单项,说明主渠道覆盖已饱和,残留漏网概率集中在社交媒体首发、未挂 arXiv 的项目。

## 4) 一句话回答

前两名不动、第三名松动:WebArena-Verified 与 WebChoreArena 在零约束重搜后反而更稳(全场仍无"任务成串+确定性判分+确认可得"三全且能替代它们的新环境),但 SkillEvolBench 的"谱系门票"位出现两个真挑战者——四路共识、协议同构但可得性未坐实的 FinEvo-Bench,和四条软要求全绿、唯一值得考虑新写挂载的 EnterpriseOps-Gym——建议改为"SkillEvolBench 守擂,这两家分别核实代码可得性与迁移密度后竞争上岗"。