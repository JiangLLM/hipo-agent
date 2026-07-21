# hippo-agent

海马体的启发:

- 海马体不是一直平均地保存所有东西。它更像一个**被显著刺激触发的临时情景编码器**。
- 当出现新奇、冲突、奖励、错误、危险、预测失败这类信号时,海马体更容易把当前经历快速绑成一段 episode:当时在哪里、看到了什么、想做什么、做了什么、结果如何。
- 这段 episode 不是马上变成长期知识。它先是短期、具体、带上下文的痕迹。
- 休息或睡眠时,尤其是安静清醒和睡眠,海马体会做离线整理:刚经历过的神经放电序列会被快速、压缩地来回 replay,有时按原顺序重放,有时倒着重放,常常比真实经历快很多。每次 replay 都是在重新激活那些刚形成的情景痕迹,让有用的连接被强化,无用的细节逐渐淡出。这个过程还会和皮层的慢振荡、睡眠纺锤协同,帮助皮层慢慢吸收其中稳定的结构。也就是说,白天先形成临时 episode,休息/睡眠时反复 replay 和筛选,最后才更像长期知识。
- 所以这里借用的不是“无限记忆”,而是:刺激触发编码 → 区分相似经验 → 比较新旧经验 → 回放巩固有用部分。

对应到 agent memory:

- 电脑存储很便宜,网页轨迹、页面结构、思考过程、失败日志都能无限保存。
- 但全存会让检索变脏。长期记忆不应该保存原始录像。
- hippo-agent 只想留下能感觉到surprise 和 指引下一次行动的经验。
- 做法是:把“做错了”“虽然选对但依据不成立”“多次尝试之间发生分歧”当成 agent 的 surprise,触发一次短期经验编码,再压缩成可复用的站点规律。

## Workflow

1. **先带着旧记忆进入当前步骤**  
   对每个网页步骤,系统先用「任务目标 + 当前页面候选」检索已有记忆。检索到的站点规律和策略会放进提示词,让 agent 在旧经验的帮助下做这一步。

2. **在同一状态下尝试 N 次**  
   对同一个目标、同一个页面、同一份检索记忆,系统生成 N 次尝试。默认是任务之间并发、任务内 N 次顺序;如果打开 `m2w.parallelism=step`,则任务顺序执行,但同一步的 N 次尝试会并发执行。每次尝试都会给出自己的想法和动作。

3. **先判断每次尝试是否真的掌握了这一步**  
   每次尝试先看动作有没有选中正确元素,再看它给出的理由是否可靠。动作错了,当然是 surprise;动作虽然选对,但依据空泛、逻辑不成立、没有真正说明为什么该选这个元素,也按 surprise 处理。标准答案只用于裁判,不会原样写进记忆。

4. **把单次 surprise 写成教训**  
   N 次尝试返回后,主线程统一处理写入。只要某次尝试被判定为 surprise,并且裁判提炼出了教训,就写成该网站下的一条记忆。这里不在并发线程里写库,避免并发修改记忆。

5. **再看 N 次尝试之间是否出现分歧**  
   单次教训处理完后,系统再统计 N 次尝试的对错分布。如果同一个状态下有的对、有的错,说明这里存在不稳定边界,需要做对比总结:多数错、少数对,就提炼正确做法;多数对、少数错,就提炼容易踩的坑。全对说明这一步已经稳定;全错则已经由上一步逐条提炼。

6. **用正确历史进入下一步**  
   学习时,当前步处理完后,代码把正确动作加入历史,再进入下一步。这是离线网页任务的设定:前面的历史保持正确,这样每一步都能单独学习“这一刻该怎么选”。

7. **测试时冻结记忆复用**  
   测试阶段不再写新记忆。每一步只检索、注入、行动,再和无记忆版本对比,看这些被筛出来的经验是否真的改善后续决策。

## Examples

真实 run 里抽出的记忆（Mind2Web）。

L1（`judge_step`，格式 `When {子目标}: use '{正确控件}' ({role}), not '{陷阱}'. {线索}`）:

```
[kohls]    When filter for women's dresses: use 'Category' (div), not 'Featured'. a section labeled with 'Category'
[kohls]    When find clothing options: use 'Shop by Category' (span), not 'check out'. visible text indicating category navigation
[kohls]    When browse toys for kids: use 'Age Range' (div), not 'Menu Expandable'. look for a section indicating age suitability
[budget]   When find a car rental location: use 'Enter your pick-up location or zip code' (textbox). textbox prompting for pick-up location or zip code
[budget]   When choose a car for a day: use 'Select My Car' (button). button labeled 'Select My Car'
[budget]   When filter vehicle types for rental: use 'Vehicle Type *' (generic), not 'SUVs & Wagons'. a control prompting vehicle type selection
[seatgeek] When find events in a city: use 'Change Location' (button). button to modify the selected location
[seatgeek] When find events in a city: use 'Search by city...' (searchbox), not 'Sports by City'. search box with prompt for city input
```

L2（`extract_step_experiences`，N 次尝试对比，多步 / 带条件 / 带"避免"）:

```
[budget]       To select the vehicle type, click the 'Vehicle Type *' element, then choose 'SUVs & Wagons' from the dropdown. This applies when you need to filter for specific vehicle types.
[budget]       Avoid clicking on the 'return time' dropdown when trying to select the vehicle type, as it does not pertain to filtering vehicle types.
[delta]        to enter the last name, click in the input field labeled 'Last Name (Required)' after entering the confirmation number. Avoid trying to enter the last name before selecting the confirmation number.
[viator]       to find the highest rated activity, ensure you click 'Traveler Rating' and not 'Price (Low to High)' or 'Price (High to Low)' as these do not sort by rating.
[sixflags]     To proceed with the purchase after selecting the diamond pass, click the 'Next' button. Avoid clicking the 'Purchase Pass' link as it does not lead to the next step.
[newegg]       To apply the selected component, click the button labeled 'Apply'. This is necessary after making a selection to proceed with the build.
[ticketcenter] To browse the venues playing the show, click the option labeled with the show name in the list. This applies when you want to see specific venue listings.
```

一个任务的 gold 轨迹（teacher-forced，每步给 gold 历史）:

```
Task: Add an e-gift card to bag of $100 for recipient John ... (site: underarmour)
  step0: [link]   Gift Cards        -> CLICK
  step1: [div]    SHOP NOW          -> CLICK      (gold 不在候选 top-k 内 → 该步判 0)
  step2: [input]  (recipient name)  -> TYPE: John
  step3: [input]  (email)           -> TYPE: abc@test.com
  step4: [input]  (from)            -> TYPE: buckeye.foobar@gmail.com
  step5: [input]  (amount)          -> TYPE: 100
  step6: [input]                    -> CLICK
  step7: [input]  (message)         -> TYPE: gift card
  step8: [button] Add to Bag        -> CLICK
```

## Prompts

L1 抽取 `judge_step` —— system:

```
You label ONE web-navigation step into a reusable DECISION RULE. The CORRECT control is ALREADY GIVEN (parsed from gold). Do NOT decide correctness; only describe how to recognize it and the trap.
Given: sub-goal, page candidates, agent REASONING and chosen ACTION, verdict, and CORRECT_CONTROL={role,label}.
Return JSON {"genuine":bool,"reason":str,"intent":str,"cue":str,"trap":str}.
- genuine: WRONG -> false. CORRECT -> true only if the reasoning names the real discriminative cue for CORRECT_CONTROL (else false = lucky guess).
- reason: one short clause on why the step failed or was lucky.
- intent: the GENERIC user sub-goal this control serves, 3-6 word verb phrase. If the sub-goal names a specific place/product/show/date/number, GENERALIZE it: say 'find events in a city' NOT 'in New York City'; 'search for a vehicle' NOT 'for Honda'. BAD (never output): a control name; the words button/filter/link/element; 'page-state'/'sub-goal'.
- cue: how to recognize CORRECT_CONTROL by its visible text/role/position, <=15 words; same generalization rule.
- trap: ONLY the visible label of the WRONG control the agent picked, <=5 words, and it MUST differ from CORRECT_CONTROL.label; if the pick equals the correct control or no distinct wrong control is identifiable, set trap to "".
- HARD: CORRECT_CONTROL.label is ground truth; NEVER name a different control as correct. intent and cue MUST be non-empty. NEVER copy any product name, place, date, number, color, or size into intent or cue.
```

L1 —— user:

```
SUB-GOAL: {task}
PAGE candidates: {obs[:600]}
AGENT reasoning: {thought}
AGENT chose: {action}
CORRECT_CONTROL: role={role} label={label}
Verdict: {CORRECT|WRONG}
```

抽出的 JSON 经确定性后处理拼成 statement：`When {intent}: use '{label}' ({role})[, not '{trap}'][. {cue}]`（并剥离任务字面值、丢弃 trap==label）。

L2 抽取 `extract_step_experiences` —— system:

```
You are an expert in web navigation. For ONE step of a task, an agent made N parallel attempts. You are given the goal, the page candidates, the GOLD correct action, and for each attempt: its REASONING, chosen ACTION, whether it was CORRECT, and a short per-attempt reflection on why it went wrong.

## Think first (self-contrast)
Reflect on WHY some attempts succeeded and others failed - what distinguishes the correct control from the look-alike(s) the wrong attempts picked. Use the GOLD action as ground truth and the per-attempt reflections.

## Then summarize
  - {direction}      # 多数错 -> 提炼正确做法; 多数对 -> 提炼要避免的陷阱

## Item format (each): title / description / content
      title:       short name for the control / decision.
      description: WHEN to use and WHEN NOT to use this item (the condition).
      content:     1-3 sentences of insight to AVOID such failures and pick the right control.

## Hard rules
  - Describe controls by GENERAL FUNCTION + visible text/role, NEVER by numeric id.
  - State what the control DOES, NOT how it serves THIS task.
  - NEVER include any value taken from the goal (product names, places, dates, numbers).
  - Do NOT output overlapping or duplicate items. At most 3 items.

Respond JSON: {"facts":[{"title":str,"description":str,"content":str,"key":str}]}
```

L2 —— user:

```
GOAL: {task}
PAGE candidates: {obs[:600]}
GOLD correct action (abstract it, do NOT copy literal values): {gold_repr}
{n} attempts, {nc} correct:
  attempt1 [ok|wrong]: reasoning: {thought} -> chose {action}
      why-wrong (layer1): {reason}
  attempt2 [ok|wrong]: ...
```

## SWE-Bench-Verified（当前主战场，2026-07）

同一套两层 surprise 机制的任务级形态：N 条并行修复尝试（每条独立容器，状态天然隔离）→ 证据门控的 LLM judge（success 与 verified 分离，trace 里看不到修复生效就不算成）→ L1 对失败/假成功逐条反思（每题封顶）→ L2 在分歧且票差足够时做方向分流对比 → repo-scoped 策略库。全程 label-free，真值只在事后评测。

django 231 题、claude-haiku-4-5、真值（本地官方 harness + Epoch arm64 镜像）：

- judge 标定：acc 87.5%（24 题真值对照），假成功率与票差门控的容错设计匹配
- 流式自进化 A/B：配对 115 题 **零效应**（44.3% vs 42.6%，p=0.42）
- **冻结成熟库（243 条）注入：50.0% vs 43.0%，+7.0 绝对点**（配对净 +8，p=0.076；RB 同域 +4.6）
- 结论：**库要密到 top-k 成为真选择，记忆才开始起效**；流式跑的稚嫩库稀释了效应
- 泄漏审计：judge/抽取结构上接触不到 gold；2.9% 字面重叠均为 agent 自行写出等价修复
- 注入消融（同 114 题）：plain 50.0% / LLM 相关性闸门 48.2% / 闸门+强制注意 47.4%，统计打平——**闸门砍掉 70% 注入量效果不丢**（安全阀而非放大器）；胜负题的注入主题相关度无差 → 效果瓶颈在**库的密度与成分**，不在注入方式

已完成的嵌套设计（全部同批 held-out 题真值可比）：成分消融显示 **L1-only / L2-only / success-only 单独全部无效**，只有完整密库正向——效果属于"池子密、top-k 有得挑"；三层嵌套显示 **frozen@116 +7.3 而 growing(243→469) 归零**。归因取证排除了内容侧解释（注入 diff 仅 1/4 条且与胜负反相关、冗余未爆炸），剩余嫌疑是协议混淆（N=5 vs n=1）与采样方差——**"密度过冲/倒U"暂列待裁决**，协议钉死只变库的三臂切片实验（bank@116 / @180 / @180-去新L1）正在跑，同时回答"是不是 L1 的问题"。之后：sympy 全弧复制去 django 特例化 → 按裁决结果决定收紧 L1 / 巩固合并（CLS"睡眠"）/ 补统计功效 → 论文（SWE-Exp 差异矩阵已备）。

## 主结果与路线图

先交代结论的演变，因为它本身就是这个项目最重要的产出。我们在 SWE-bench-Verified 的 django 题上跑通了整套记忆自进化，最初的测量显示：攒出来的经验库能把解题率从 43% 提到 50%，还在第二批题上"复现"了 +7.3。但当我们把同一个配置**独立重复四次**之后，这个效应消失了——无记忆四次平均 45.4%，带记忆四次平均 46.3%，配对检验 p=0.87。当初的 +7 是带记忆臂最走运的一次抽样撞上无记忆臂最倒霉的一次，而所谓的"多臂互相印证"共享了同一次基线抽样，是同一个错误的几张复印件。

这次翻案挖出三个对整个方向都适用的发现：单次采样的臂间对比在这类基准上有 ±8 个点的纯随机波动，任何单跑报数的记忆论文（包括 ReasoningBank +4.6、SWE-Exp +6.6）都值得用同样的标准重新审视；LLM 裁判会系统性偏爱带记忆的轨迹（假阳率高约 3 个点）——"引用了经验"的解题过程在裁判眼里显得更可信，但真值并没有更好，这动摇了 label-free 评估这条路的地基；以及 Verified 的题目之间深层知识几乎不重叠（拿官方答案蒸馏的完美提示能救活 38% 的失败题，但那些知识在其他题的做题记录里 10/11 从未出现过），这个基准在结构上就不适合考察跨任务记忆。细节都在 HANDOFF.md。

下一步想做的： decay 或者说睡眠 - 另外库不是越大越好——太小挑不出东西，太大又开始互相干扰，中间有个甜区。这两件事与其说是缺陷，不如说就是这个方向真正要研究的问题：什么时候值得记, L2的时候看看抽取多少、怎么维护。（可以做 可以不做）

下一阶段的主攻方向——上更新更难的基准、配前沿模型——单独写在 [NEXT_BENCH.md](NEXT_BENCH.md)。

再往后是 WebArena。自主网页导航、同一个网站上任务反复出现，本来就是记忆最该发光的地方，我们的机制代码也早就和具体领域解耦了，迁过去只用换环境层。卡住的只有机器：官方镜像全是 x86 的，加起来三百多个 G，这台 Apple Silicon 跑不动。需要一台 x86 的 Linux 机器，4 核 16G 内存、1T 左右的盘、装好 Docker 就行——要么直接用官方的 AWS 镜像（us-east-2 区，t3a.xlarge 配 1T 盘，开箱即用），要么随便租台 x86 大盘机自己搭（有现成脚本，四十欧一个月的档位就够），公司沙箱里开台 EC2 也可以。

## TODO

> 以下观察都是在 **Mind2Web**(teacher-forced 逐步预测、每步有 gold)上得到的。WebArena 是 per-task、无逐步 gold,记忆单元和这个问题的形态都会变。

- **L1 记忆太多(灌水)【Mind2Web 上】**:一个 stream 下来 L1 会写出上百条单步记忆,检索 top-k 里大部分和当前这步不相关;实测 L1+L2 合起来反而比单用任一个更差(灌水)。正在思考怎么收敛:
  - **少读 L1**:检索时按 `condition`(当前子目标)匹配、只注入命中的、注入条数动态(而不是每步硬塞 top-k)。
  - **少写 L1**:更严的 surprise 门控 / 按 key 去重合并 / 每站点封顶。
  - **甚至只写 L2**:L2(对比抽取)单条更准、更省(实测 40 条 L2 ≈ 104 条 L1 的效果);考虑让 L1 退居补充,或干脆只保留 L2。