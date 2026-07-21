# 下一场硬仗：前沿模型 × 新基准

## 我们现在站在哪

先说清一件事：我们最初在这份文档里报过 +7（43.0% → 50.0%，两个测试集"复现"），后来把同一配置独立重复四次，效应归零了（45.4% vs 46.3%，p=0.87）——当初的 +7 是幸运抽样叠加共享基线造成的伪复现，已撤回。这个撤回本身比 +7 值钱，因为它连带查清了三件事：这类基准上单次跑动有 ±8 个点的纯随机波动；LLM 裁判会偏爱带记忆的轨迹（假阳率高约 3 个点）；Verified 的题目之间深层知识几乎不重叠，结构上不适合考记忆。

同一个基准上其他记忆方法报的增益，现在要用新的眼光看：

| 方法 | 报告的增益 | 测量方式 |
|---|---|---|
| ReasoningBank（Google） | +4.6 | 单次跑动，无重复 |
| SWE-Exp | +6.6 / +2.2 | 单次跑动，无重复，且依赖标准答案标注轨迹 |
| 子任务级记忆（arXiv 2602.21611） | 平均 +4.7 | **3 次重复报均值±方差**（同行里唯一做了的） |

我们实测的单次波动是 ±8 个点——前两行的数字完全落在这个噪声带内。带着这套防弹的测量纪律去新基准，就是我们的底气：如果效应在那里存在，我们测出来的是真的。

## 为什么必须走

我们的方法有个结构性的依赖：它靠"同一道题有的尝试成、有的尝试败"这个分歧信号来学习。这决定了模型和基准必须匹配——模型在这个基准上得处在能力边界附近，太强或太弱信号都没有。

老的 SWE-bench-Verified 已经满足不了这个条件了。前沿模型在上面九成都对，一道题跑五次五次全成，没有分歧可学，也没有几个点可涨；OpenAI 自己都宣布不再用它衡量前沿模型。但这不是方法的死路，是基准的死路：换到更难更新的题上，前沿模型自己就会回到"有成有败"的区间。

## 候选基准

| 基准 | 是什么 | 为什么适合我们 |
|---|---|---|
| SWE-bench-Live | 持续滚动收录新 GitHub issue | 模型背不到题，污染质疑从根上免疫，是记忆方法最干净的考场 |
| SWE-rebench（Nebius） | 同样滚动更新，带自动化收题管线 | 同上，且题量供给稳定，适合长 stream 实验 |
| SWE-bench Pro（Scale） | 商业级仓库、题目明显更难 | 把前沿模型压回 20-40% 区间，分歧信号最足 |
| Multi-SWE-bench | 多语言仓库（Java/TS/Go/Rust…） | 检验经验机制出不出得了 Python 生态 |
| SWE-smith | 在任意仓库无限合成任务 | 任务密度可控，正好把我们发现的"库密度—效果"曲线画完整 |
| EvoMemBench / SEA-Eval / EvoAgentBench | 2026 年新出的自我进化专用基准 | 评测协议本身为跨任务积累设计，不用自己搭对照；社区正在向它们汇聚 |

选基准还有一条后来才想明白的硬标准：**任务流要反复踩同一批机制**。我们在 django 上把失败题逐个查过，官方步数下做不出的题，需要的深层知识几乎都没在其他任务里出现过——同一个仓库不等于同一批知识。记忆的价值取决于"知识回访率"，这是 SWE-smith（同仓库密集造题）排进优先序、以及 WebArena（同站任务天然回访）是主目标的根本原因。

选择的优先序：先上一个滚动型（Live 或 rebench）把主结果立住，再用 SWE-smith 补机制研究，多语言和自进化专用基准作为推广性证据。

## 抽出来的经验长什么样

条目原文是英文（抽取模型的输出），下面原样照录。好的坏的都摆出来。

L1 是单次尝试失败（或成功但没验证）之后的反思，一条一题。写得好的时候，一条就把一个 django 内部的坑讲透。比如这条，说的是 union 出来的查询集为什么 `.none()` 会失灵——问题的根子在 SQL 生成走了另一条不编译 WHERE 子句的路：

> **Combined queries (.union(), .intersection(), .difference()) don't respect .none() marker**
> Combined queries store their constituent queries in `query.combined_queries` and generate SQL via a different code path in `SQLCompiler.as_sql()`. The `.none()` method adds a `NothingNode` to the WHERE clause, but combined query SQL generation bypasses the WHERE clause compilation for the combinator.

这条指出了 `split_exclude()` 新建 Query 对象时会丢注解，连该在哪一行怎么补都写清了：

> **Annotations must be propagated when creating subqueries in split_exclude()**
> In split_exclude() (around line 1668 of django/db/models/sql/query.py), when creating a new Query object with `query = Query(self.model)`, copy annotations from the original query to the new one using `query.annotations = self.annotations.copy()` before calling add_filter().

这条发现了一个只有踩过才知道的陷阱——`getattr` 会先拿到实例属性，模型恰好有个字段叫 filterable 时正常过滤会被误杀：

> **Distinguish class-level filterable attribute from instance attributes**
> The check_filterable() method in django/db/models/sql/query.py uses getattr(expression, 'filterable', True) which finds instance attributes before class attributes. For model instances with a field named 'filterable', this incorrectly blocks filtering.

写得差的时候就是放之四海而皆准的流程话。事后核查证明这类条目基本没被 agent 用上：

> **Identify the minimal change set before exploration**
> **Use test failures to guide implementation, not exploration**

L2 是同一道题五次尝试出现分歧后的对比总结。质量普遍比 L1 高，因为有正反两面可对照。下面这条来自一道 1 成 4 败的题，从唯一成功的那次尝试里提炼出正确路径，位置和值都点到了：

> **Default FILE_UPLOAD_PERMISSIONS setting location and value**
> The default FILE_UPLOAD_PERMISSIONS is defined in django/conf/global_settings.py (line ~307). Change it from `None` to `0o644` to ensure consistent, readable file permissions regardless of whether TemporaryUploadedFile or MemoryUploadedFile was used.

这条相反，来自 4 成 1 败，把唯一失败那次踩的坑记了下来：

> **Test mocking strategy must match subprocess API changes**
> When changing from subprocess.check_call to subprocess.run, tests that mock subprocess.call must be updated to mock subprocess.run instead.

v2 的文件笔记是最新的改进：知识按文件组织、带类/方法锚点，agent 打开这个文件的瞬间才注入。`deletion.py` 的笔记本里已经攒出了性能直觉——删除逻辑只需要主键，真值判断却会把整行都查出来：

> (Collector.collect) The collect method evaluates QuerySets via truthiness checks (e.g., `elif sub_objs:`) which triggers database queries; only the primary key field is required for deletion logic, so `.only('pk')` avoids loading unnecessary fields.

对失败的分析也指向同一个方向：官方步数设置下没做出来的题，需要的都是这个深度的机制事实。但任务级检索送不到——243 条里光 query.py 的知识就有 16 条，按整题相似度取 4 条时几乎从来轮不到它们。所以组织方式（按文件）和注入时机（打开文件时）比再多攒一倍条目更重要，这也是 v2 改这两处的原因。

## 配最新的 API

- 手上可用的模型档位：Fable 5（Anthropic）、GPT-5.6 系（OpenAI，账号恢复后）。
- 打法不变：agent、judge、抽取同一个模型，label-free，配对真值检验——只是模型和基准一起升级，让能力边界重新落在题目难度上。
- 预算感受：前沿模型单价约是 haiku 档的 20-40 倍，一轮完整的 stream + 消融估计在两三千美元量级，需要按此规划。
- 成功标准提前定好：**如果这套方法配最新模型、在最新基准上还能拿出 5 到 10 个点的提升，那就不是"在小模型旧基准上调出来的数字"，而是一个真正漂亮的 work**——它说明记忆自进化的价值不随模型变强而消失，只是跟着能力边界往前移。
- 反过来如果拿不出来，也有明确的退路叙事：记忆的价值集中在预算受限、模型处在能力边界的部署场景（我们已有 +7 的证据），这本身就是一篇诚实的 scope 论文。
