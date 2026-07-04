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

## TODO

> 以下观察都是在 **Mind2Web**(teacher-forced 逐步预测、每步有 gold)上得到的。WebArena 是 per-task、无逐步 gold,记忆单元和这个问题的形态都会变。

- **L1 记忆太多(灌水)【Mind2Web 上】**:一个 stream 下来 L1 会写出上百条单步记忆,检索 top-k 里大部分和当前这步不相关;实测 L1+L2 合起来反而比单用任一个更差(灌水)。正在思考怎么收敛:
  - **少读 L1**:检索时按 `condition`(当前子目标)匹配、只注入命中的、注入条数动态(而不是每步硬塞 top-k)。
  - **少写 L1**:更严的 surprise 门控 / 按 key 去重合并 / 每站点封顶。
  - **甚至只写 L2**:L2(对比抽取)单条更准、更省(实测 40 条 L2 ≈ 104 条 L1 的效果);考虑让 L1 退居补充,或干脆只保留 L2。