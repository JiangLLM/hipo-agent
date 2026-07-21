# hippo-agent 交接文档

最后更新：2026-07-18。写给下一个接手的人（或下一个会话）：读完这份应该能明白我们在做什么、已经知道了什么、卡在哪、下一步往哪走。密钥不在库里。**当前主战场是 WebArena，见下方"WebArena 现状"一节（最新）；SWE-bench 阶段的完整记录在后面。**

## WebArena 现状（2026-07-18，进行中）

**一句话**：WebArena 从零搭起来跑通了，agent scaffold 追平文献，一路修了 6 个 bug，现在第一次拿到 sol 的干净基线（shopping nomem 64%），withmem 自进化臂在跑，等它验证记忆有没有用。

**基础设施**（都在 AWS Sandbox 账号 717279734741, us-west-2）：
- EC2 `i-08d438a258bafaaeb`（m6i.xlarge, 1TB），内网 `10.44.12.29`，安全组只对 VPN 网段开放。私钥 `~/.ssh/hippo-webarena-sandbox.pem`。Team=agentic-ai-science 标签已打。
- 四个站点容器已 docker run + 配好 URL：shopping(7770)/shopping_admin(7780)/reddit(9999)/gitlab(8023)。Mac 经 VPN 直连。
- 站点 tar 在 EC2 `/data/tars`（195G，可重建容器）。

**LLM 通道**：走 **ZGAI 公司网关**（`LLM_API_BASE`/`LLM_API_KEY` 在 .env），OpenAI 兼容，有全部 gpt-5.x 含 gpt-5.6-sol/terra/luna。不烧个人 key。gpt-5 系必须 `drop_params=True`（temperature 只接受默认）。embed 用本地 bge-small（零成本）。

**代码**：`src/hippo/wa/`（data/rollout/brain/run，镜像 swe/ 结构）+ `.venv-wa`（独立环境，装 browsergym-webarena，**不碰主 .venv**）。一键换 model：`MODEL=gpt-5.6-sol SITE=shopping bash scripts/run_wa.sh`；分析 `scripts/analyze_wa.py <run目录>`（出 A/B + 自进化曲线 + judge 校准）。

**scaffold 升级（关键，追平文献）**：初版手写 agent 太简陋，reddit 48%/shopping 4%。查了 browsergym GenericAgent + RB legacy 的标准做法，改了四点 → reddit **68%**（=RB gemini-flash 68.9%）、shopping 脱离地板：
1. 观察不再字符硬截断（原 12k 盲砍把中后部目标元素切没了）→ 全量 axtree、40k 上限、filter_visible_only=False
2. 历史带 thought+action+error、窗口 15（原来只给动作字符串、6 步）
3. CoT 放开（原来限"一句话 Thought"）+ 穷举任务提示"读全整个列表再答"
4. max_steps 20→30

**修过的 6 个 bug**（WebArena 常驻浏览器+长轨迹+网关把脆弱点全逼出来了）：
1. data.py 路径：webarena 是 namespace package，`__file__` 是 None → 用 `importlib.resources.files`
2. 静默空转诊断：agent 全 0 步 → 是 Anthropic API 当时抖动（非我方），转 ZGAI
3. ZGAI + gpt-5 系全挂：网关分支漏 `drop_params` → 已加
4. LLM 调用永久 hang：加 120s timeout（`LLM_TIMEOUT`，超时→重试）
5. env.step 硬死（playwright 卡住，process idle on IO）：SIGALRM 90s 硬超时（`wa.step_timeout`），超时结束该局跳下一题
6. **【最关键，直接污染分数】WebArena fuzzy_match 评分器硬编码 `gpt-4-1106-preview` + 只认 OPENAI_API_KEY**：我们的真 OpenAI key 无该废弃模型权限 → 每个 fuzzy 任务评分 404 → 判 error 丢分。修法 `_fix_webarena_grader()`（run.py）：把评分器的 openai 调用重定向到 ZGAI 的 gpt-4o、走 max_completion_tokens。**这个 bug 之前把 shopping 分数严重压低（sol 真实 64% 被污染成 20%）。**
- 另加了 sol/terra/luna 跨变体 fallback（`LLM_FALLBACK_MODELS`），网关抖动时自动换实例。

**已知会污染结论、必须先修好再信数字的坑**（血泪纪律，SWE 阶段立的）：
- 单次采样有 ±8pt 噪声——±5pt 内的 A/B 差异没有多 seed 不算数（SWE 的 +7 就是这么被证伪的）。
- LLM judge 会偏爱带记忆的轨迹（假阳）——judge 只用于学习环，A/B 计分一律用官方 reward。
- 带 bug 跑出的数据一律作废，绝不"带 bug 出零分然后甩锅数据集"。

**当前实验状态**：run `runs/wa_shopping_gpt5_6sol_20260718_110832`，gpt-5.6-sol 全程，shopping 25 题，nomem+withmem(N=5)。nomem 前 11 题 **64%**（干净基线，err0）。**开放问题**：sol 太强，shopping 64% 基线头部空间只剩 36pt，记忆提升空间可能被压缩（SWE 上 frontier 模型的老问题）；若 withmem 证明 shopping 对 sol 太易，下一步换更难的站（gitlab/shopping_admin）或加难任务。等 withmem 自进化曲线出来定。

**旧 WebArena A/B（作废存档）**：`runs/wa_reddit_ab_*`（旧简陋 scaffold + 单次采样，nomem 48 vs withmem 44），只留档不进结论。

---

（以下为 SWE-bench 阶段记录，2026-07 上半月）

## 这个项目在做什么

hippo-agent 是一个让 agent 从自己的经验里学习的记忆系统。灵感来自海马体：大脑不是把所有经历都存下来，而是在出现意外——错误、冲突、预期落空——的时候才把当下的情景编码成记忆，之后在休息时回放、筛选、合并，有用的部分才沉淀为长期知识。

对应到 agent 上，我们的做法是两层抽取，都由"意外"触发：

- L1：单次尝试结束后，如果失败了，或者成功了但过程站不住脚（没验证就提交），就让模型反思一次，写下一条教训。
- L2：同一个任务并行跑 N 次，如果有的成功有的失败，说明这里存在一个不稳定的决策边界，值得做一次对比总结——多数失败时提炼成功者做对了什么，多数成功时提炼失败者踩了什么坑。

写进库里的是带适用条件的短条目（标题、什么时候适用、一两句洞见），按仓库/站点分域，用向量检索取 top-k 注入到后续任务的提示里。全程不碰任务的标准答案：成败由一个带证据要求的 LLM judge 判定，它必须在轨迹里看到"修复被观察到生效"才算数。这个 label-free 的设定是刻意的——部署环境里没有人给你判卷子。

## 怎么走到 SWE-bench 的

项目先在 Mind2Web（网页操作，teacher-forced 逐步预测）上做了一轮。那一轮最重要的产出是教训：抽取质量决定一切（旧抽取会写出和正确答案相反的教训）；记忆单元要少而准，库一大 top-k 检索就被灌水淹死；注入不匹配当前情境的记忆比不注入更糟。修完抽取后记忆从负效应变成小幅正效应，但 Mind2Web 本身天花板太低——每个网站平均只有 3.7 个任务，经验没有多少复用的机会。

原计划迁到 WebArena，调研后放弃了：官方 Docker 镜像全是 amd64 而且动辄几十上百 GB，这台 M4 Max 跑不了，云上又要额外花钱。转而选了 SWE-bench-Verified，理由有四个：Epoch AI 发布了 arm64 的逐题镜像（Verified 覆盖 420/500），本地就能跑；每次尝试一个独立容器，N 次并行尝试天然互不干扰；django 一个仓库占了 500 题里的 231 题，经验复用密度极高；而竞品（ReasoningBank、SWE-Exp）在这个域的判定和门控都很粗糙，我们的差异化空间大。

## 系统现状

代码在 `src/hippo/`，SWE 部分是 `src/hippo/swe/` 四个文件：

- `data.py`：加载 Verified、按仓库过滤、解析 Epoch 镜像名并预拉取（没有 arm64 镜像的题自动跳过）。
- `rollout.py`：一次尝试 = 一个新容器 + mini-swe-agent（用的是 pip 上游 2.4.5，只当环境层，prompt 和提交协议原封不动）。记忆通过模板变量注入，空记忆时和原版逐字节一致。`compact_trace` 把完整轨迹压成 judge 能读的摘要，测试类命令的输出保留得比普通命令长四倍——验证证据就藏在那里。
- `brain.py`：三个 LLM 环节。`judge_attempt` 判成败，空 patch 直接判负不花钱，其余交给带严格性规则的 judge，输出 success 和 verified 两个独立的位；`reflect_attempt` 是 L1；`contrast_attempts` 是 L2，方向由多数派决定。另有 `select_relevant`，一个可选的注入侧闸门，让 LLM 从检索候选里只留条件匹配的（可以一条不留）。
- `run.py`：流式 runner。三种臂由 retrieve/write 两个开关组合出来：nomem（都关，冷基线）、withmem（都开，边跑边学，任务间严格串行）、frozenmem（只读不写，用固定的库做注入实验，任务可并行）。支持断点续跑（`--swe.memory_in` 加载旧库、`--swe.skip_done` 跳过跑过的题）、预算护栏（触顶自动停机，记忆和已完成结果都保得住）。

配套脚本：`scripts/eval_local.py` 是本地真值评测——把 Epoch 镜像 retag 成官方 harness 期望的名字，再用原版 `run_instance` 跑评测。注意 sb-cli 云端评测是坏的（全部报 failed run），别用。`scripts/run_swe_calib.sh` 和 `run_swe_stream.sh` 是两个常用入口。

模型选型：agent、judge、抽取三个角色统一用 claude-haiku-4-5。选它是因为校准显示它在这个基准上基线约 45%，正好处在"有成有败"的区间——分歧信号最丰富，记忆也有上升空间。frontier 模型九成都对，既没有分歧可学也没有头部可涨。embedding 用本地的 bge-small（fastembed），不花钱不走网。

跑一个小实验的样子：

```bash
.venv/bin/python -m hippo.swe.run \
  --llm.model anthropic/claude-haiku-4-5 \
  --llm.embed_model local/BAAI/bge-small-en-v1.5 \
  --swe.agent_model anthropic/claude-haiku-4-5 \
  --swe.repos django --swe.limit 25 --swe.arms nomem,withmem \
  --agent.n_traj 5 --run.budget_usd 40 --run.name my_run
```

## 实验走到哪了

以下全部是真值（本地官方 harness），不是 judge 的自评分。

先校准了裁判：拿 24 题的真值对照 judge 的判定，准确率 87.5%，precision 0.833。两个漏网的假成功、一个错杀的真成功——错杀那个正是证据门控在保守方向的代价，符合"假成功比假失败更毒"的设计取向。这个噪声水位也正是 L2 要求票差至少 4:1 的原因：单票 17% 的假阳率，四票同错才会把提炼方向带偏。

然后是主实验，django 全部 229 题。冷基线（无记忆）42.6%。流式自进化——从空库开始边做边学——跑到 116 题时撞了预算停机，此时库里 243 条经验。在配对比较里这个流式臂和基线打平（44.3% 对 42.6%，配对净 +2，p=0.42），当时的解读是：库还太年轻，大部分任务面对的是几十条的小库。

停机反而促成了整个项目最重要的发现。我们把那 243 条冻结，在剩下 114 个库从没见过的题上重新跑：50.0% 对基线 43.0%，配对净 +8，p=0.076。七个绝对点，比 ReasoningBank 在同一个基准上报的 +4.6 还高。同一个库换三种注入方式（原样注入、LLM 相关性闸门、闸门加强制注意）都是正的（+4.4 到 +7.0），互相之间打平——注入方式不重要，闸门把注入量砍掉七成效果也不掉，说明它是个减负的安全阀而非放大器。

接着追问效果来自哪类条目，把库按来源拆开单独测：只用 L1 的 185 条，零效应；只用 L2 的 58 条，零效应（甚至略负）；只用成功来源的 26 条，零效应。三个成分单独都不行，合在一起才行。解释是检索的 k=4 是硬性的：小库被迫把弱匹配塞满四个坑，大库的 top-4 才有真正的选择余地。效果属于"池子够密、检索有得挑"这个条件，不属于任何一类条目。

然后是一盆冷水。我们把流式跑续上（从 243 条继续边做边学到 469 条），在同一批题上和冻结库对比：冻结库 49.1%，继续学习的库 40.9%，直接配对净负九。继续学习不但没有更好，反而把冻结库的优势学没了。

第一反应是"库涨太大、灌水回归"，但取证不支持这个故事：逐题对比两个臂实际注入的内容，平均每题四条里只有一条不同，新条目平均每题只挤进 0.9 条，而且注入了更多新条目的题反而赢得更多——内容侧的解释全部被排除。剩下两个嫌疑：一是协议混淆，学习臂是五个容器并行跑五次尝试（取第一次计分），冻结臂是单次尝试四任务并行，资源争抢的模式不一样；二是纯粹的采样方差，两个臂的计分尝试本来就是同分布的独立采样，17 比 8 的胜负分裂 p=0.054，本身就在显著边缘。

"记忆有工作窗口、涨过头会掉出去"这个解读一度很有说服力：协议钉死的切片实验里 367 条的臂确实比 243 条低，去掉新 L1 也没恢复，巩固合并还救回了一半。但最后一步取证把它翻案了（2026-07-16）。把每道题两臂实际注入的内容逐字 diff，发现所有"大库更差"的胜负差几乎全部集中在**注入完全相同**的题上（A vs B 在注入相同的 14 题上 4:0，注入真的不同的 32 题上 2:2 平；A vs C、P2 的 frozen vs growing 同一个模式）。输入一样输出不一样，说明差距来自别处——回查执行环境：切片三臂是顺序跑的，后跑的臂机器上并行挂着前一臂的真值评测容器；P2 的 growing 是 5 容器并发、frozen 是干净单尝试。**"降"是机器负载不对称加上单次采样方差，不是记忆中毒。** 所以最终结论：升（成熟库 +7）是真的、多测试集复现；降是假的，予以撤回；巩固的"半程恢复"同一混淆结构，一并降级为未证。教训写给后来人：单次温度采样的臂间对比，±5 个点以内的差异没有多 seed 就不要当效应；跑对照臂时别让机器上有别的重活。

## 官方步数设置下的攻坚（2026-07-14 起）

放开步数（250 步/$3，对齐社区默认）之后基线自己涨到 71.9%，任务开头注入的旧记忆只剩 +0.9。逐题排查发现定位不是瓶颈（两臂都在第 2 步就摸到 gold 文件），失败题缺的是子系统机制知识，而库里其实存着不少这类条目，只是按任务相似度检索送不到现场。于是做了 v2：知识按文件组织（96 个文件 286 条笔记，离线从已有轨迹重抽）、agent 打开文件的瞬间注入。触发率很好（失败题 90% 都收到了笔记），但真值只到 73.7%（+1.8），还是噪声带。

关键的裁决实验是 oracle：给 29 道怎么都做不出的题各配一条从官方答案蒸馏的机制提示（不含补丁本身），注入机制与 v2 完全相同。结果翻出 11 道（38%）。含义：模型没有被能力锁死，完美内容的上限约 +9.6 个点（71.9→81 左右），我们自动抽取只兑现了 +1.8——**瓶颈在抽取深度，不在投递机制，也不在模型**。相关文件：`runs/v2_notes_*/`（v2 臂与笔记库）、`runs/v2_notes_*/oracle/`（oracle 提示与真值）、`runs/orc_*/`（逐题 oracle 跑）。

"现实上限"分析（2026-07-16）给了最终答案：11 道 oracle 可翻的题里，10 道需要的知识训练题从没碰过、1 道擦边、0 道明确可学。oracle 的 +9.6 里几乎全部知识不存在于任何可学的经验中——django 各题命中代码库的不同角落，深层机制粒度上的跨任务重叠接近零。**跨任务记忆在官方设置下的现实上限约 +1~2 点，恰好等于 v2 实测的 +1.8。抽取没有失职，是矿里没有矿。**

这把结论从"抽取要更深"改写成了"任务分布要有知识回访"：记忆的价值取决于任务流是否反复踩同一批机制。紧预算下的 +7（流程纪律在步数稀缺时值钱）和官方设置下的 ~0（深层知识不重叠）是同一个理论的两面。对下一步的含义：选基准要选有回访结构的——SWE-smith（同仓库密集造题）、真实持续开发场景、WebArena（同站任务反复）——而不是只看"同仓库"标签。v3（Fable 5 当抽取器）已在跑，按此分析预测它只会到 +1~2；如果真是，就是这个"知识不相交"论证的证伪测试通过，一起写进论文。

## 定位与竞品

最直接的对标是 SWE-Exp（arXiv 2507.23361，已精读）。它证明了"经验值得存"，但它依赖标准答案来标注轨迹成败、每条轨迹无条件入库、没有并行尝试之间的对比、检索 rerank 不能弃权——这四点恰好是我们的四个机制主张：label-free 的证据门控判定、surprise 触发的选择性写入、跨 rollout 的分歧对比、可弃权的注入闸门。它的 Limitations 自己承认"缺乏评估经验适用性的机制"，可以直接引来做动机。写作时注意：成败双源学习、经验分层结构、检索加 rerank 这些它已经占位，不要抢首创；它的分层是按抽象粒度（理解层/修改层），我们的分层是按信息来源（单轨反思/跨轨对比），要显式区分。ReasoningBank 是另一个必引对象，我们的流式协议和它同构，判定和门控比它严格得多。

泄漏问题可以硬气地回应：judge 和抽取在结构上接触不到标准答案，库里 2.9% 的条目和官方修复有字面重叠，逐条查过，全是 agent 自己写出了等价修复。

## 接下来做什么

1. 等裁决实验落地（应该就在几小时内），按判读表进入对应分支：收紧 L1、或做巩固原型、或补统计功效。
2. sympy 75 题全弧复制（约 85 美元），把结论从"django 研究"升级成"跨仓库成立"。
3. 统计功效是投稿前必须补的课：主效应的 p 值在 0.076 到 0.192 之间，现在靠多臂同向撑定性结论，需要 django 加 sympy 的合并配对、或者多 seed 重复。
4. 远期：agent 主动召回（给 agent 一个 recall 命令，卡住的时候自己查库——线索触发式回忆，和立项叙事同构，也是竞品没有的形态）；WebArena 回归（等算力：Zillow sandbox 的 x86 EC2 自建，或租一台 Hetzner）。

## 实用杂项

账本：截至目前总花费约 500 美元（Anthropic key）。单价参考：学习臂 N=5 全流程约 0.9 美元一题，冻结/基线臂约 0.2 美元一题。

产物位置（`runs/` 不进 git）：大跑 `runs/swe_big_django_*/`（nomem 真值、243 条库、成分过滤库）；尾跑 `runs/swe_tail_*/`（469 条库、切片实验的三个库和 skip 文件）；各消融臂 `runs/abl_*/` 和 `runs/slice_*/`，每个目录里 `gt_*.json` 是真值、`preds_*.json` 是提交格式、`trajs/` 是完整轨迹、`events.jsonl` 是结构化日志（每题的判定、检索命中、写入条目都在里面）。

踩过的坑，别再踩：judge 的回复里会出现 `\A`、`\d` 这类非法 JSON 转义，解析要做清洗重试（SweBrain._json 已处理）；YAML 会把裸的 on/off 解析成布尔值，开关判断要兼容（_on() 已处理）；str.format 的模板里 JSON 示例的花括号要双写；dotenv 在 stdin 里跑的脚本要传显式路径；`grep -c` 没匹配时输出 0 且退出码是 1，拼 `|| echo 0` 会出双行；sb-cli 云端评测坏的，本地评测时 harness 会在检查实例镜像之前先检查 env 镜像是否存在，把同一个镜像多 tag 一个 env 名字就能绕过；跑长实验用 caffeinate 防休眠，断网前 SIGSTOP 整棵进程树、恢复后 SIGCONT，比让 API 调用失败重试干净得多。

Mind2Web 时期的完整记录保留在下面的附录里。

---

# 附录：Mind2Web 时期记录（2026-07 之前，原文保留）

> 以下是切换到 SWE-Bench 之前的原始交接内容。结论仍然有效（尤其第 3、6 节的教训直接塑造了现在的设计），但环境、命令、"下一步计划"以当时为准，不再维护。

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
