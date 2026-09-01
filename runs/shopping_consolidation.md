# Consolidation of `runs/wa_shopping_20260724_105245_20260724_105247/memory.json`

input: 42 L2 items · merge>=0.88 (max cluster 5) · conflict>=0.8 · model=gpt-5.6-sol


## Stage 1+2 — merge & principle-ify (25 clusters)


- **MERGE** ['Exhaustive review scan with broad matching and canonical names', 'Scan all reviews by meaning, not exact phrase']
  -> «Identify reviewers by semantic meaning»
  - when: Use when a shopping task asks which reviewers mention a topic or combination of concepts. Do not use for product specifications or aggregate ratings.
  - rule: Determine matches from each full review’s meaning, including close paraphrases, concepts split across sentences, and ambiguous relevant references unless the task requires exact wording. Return every qualifying reviewer name exactly as displayed, counting duplicate renderings once while preserving genuinely distinct name variants.

- **REWRITE** ['Inspect all customer reviews and use the exact empty-result marker']
  -> «Identify reviewers by review-text criteria»
  - when: Use when the task asks for reviewers whose review text mentions a specified topic or sentiment.
  - rule: Evaluate every existing customer review by its full review body, excluding review-submission forms. Return each qualifying reviewer name verbatim; if none qualify, return exactly “N/A”.

- **MERGE** ['Use full order history and label every aggregate', 'Separate the order-count rule from completed-order spending', 'Verify complete order history before totaling', 'Audit full order history using paid totals']
  -> «Aggregate qualifying orders from complete history»
  - when: Use when the task asks for an order count or total spend from account order history, especially over a date range or with stated filters. Do not use for payment-transaction reports or merchandise-subtotal questions.
  - rule: Evaluate the complete order history, not a recent-orders preview, and include only rows matching every stated date, merchant, and status condition. Count qualifying orders and sum each full displayed Order Total or Grand Total once, never a subtotal. Label each reported aggregate clearly.

- **REWRITE** ['Use calendar-month scope and separate order count from fulfilled spend']
  -> «Use calendar months and distinguish order count from fulfilled spend»
  - when: Use when the task asks for order counts or fulfilled spending over a number of months as of a given date. Do not use calendar-month scope when the task explicitly requests a rolling interval.
  - rule: Interpret the period as the applicable calendar months. Count all orders in scope regardless of status, but sum full displayed order totals only for the specifically required completed or fulfilled status; similar statuses do not qualify. Verify that adjacent-month orders are excluded.

- **REWRITE** ['Qualify products before reading price extremes']
  -> «Qualify products before choosing price extremes»
  - when: Use when a shopping task asks for the price range, minimum price, or maximum price of a specific product type.
  - rule: Determine eligibility before selecting price endpoints: exclude accessories, related products, and near-identical types that do not match the request. Verify each endpoint’s full title, variant, and displayed price; do not assume the first or last sorted result qualifies when its identity is ambiguous.

- **MERGE** ['Build a complete product set before finding price extremes', 'Merge paginated category results before answering']
  -> «Establish the complete qualifying product set»
  - when: Use when the task asks for a complete product list or price range for a product type. Do not use for a single explicitly named item.
  - rule: Treat synonyms, reordered wording, and model variants as candidates, but exclude accessories and broader look-alikes. Before reporting names or price extremes, verify coverage across all result pages or partitions, check tied endpoints, and preserve complete visible titles and prices; consult product details when text is ambiguous or truncated.

- **MERGE** ['Audit complete order details and category-related costs', 'Audit full order history and verify shared-cost attribution', 'Audit full order details and preserve canonical output']
  -> «Calculate category spending from item-level order details»
  - when: Use when the task asks for spending on a category across past orders or a date range, especially if orders may contain both qualifying and nonqualifying items.
  - rule: Count only visibly qualifying item rows, verifying full names, variants, quantities, and subtotals so near-identical products are not conflated. For mixed orders, include shared charges only according to the task’s prescribed attribution method; never split them equally or infer missing proportions. Reconcile the result with displayed order totals and round only the final value.

- **REWRITE** ['Use full order details and allocate shipping equally']
  -> «Allocate order shipping equally by item unit»
  - when: Use when the task asks for category spending over a specified date or range and requires shipping to be included without specifying another allocation method. Do not use when it requests merchandise subtotal only or defines a different allocation.
  - rule: Verify all matching orders using full item details, including variants, quantities, subtotals, and each order’s shipping charge. For each order, divide shipping equally among all item units, then add the shipping shares and merchandise subtotals only for qualifying units.

- **MERGE** ['Use full order history and extract only the exact requested attribute', 'Preserve and exhaust full order history', 'Match the item row before copying its price', 'Verify the latest matching order']
  -> «Verify the exact purchased item before extracting its attribute»
  - when: Use when the task asks for the date, price, variant, or configuration of a previously purchased item.
  - rule: Consider the complete order history, not only a recent-orders summary. Verify the exact product and variant in item-level details before extracting the requested field; do not substitute an order total, status, nearby row, or unrelated option. For “last ordered,” select the newest verified match, and report all matches if the task permits ties.

- **REWRITE** ['Single-pass review ledger and completeness check']
  -> «Complete, verbatim extraction of review criticisms»
  - when: Use when the task asks for criticisms or exact excerpts from product reviews. Do not use when the answer is available from the product summary alone.
  - rule: Treat each distinct complaint in the reviews as a candidate, including standalone media or error lines that express criticism. Preserve qualifying wording verbatim and contiguous, without added context or paraphrase; deduplicate repeated content and, when the task asks for every criticism, verify coverage of the full review set.

- **MERGE** ['Read the complete Reviews text', 'Open Reviews and Transcribe Criticism Exactly']
  -> «Extract Customer-Review Criticism Verbatim»
  - when: Use when the task asks to extract criticisms or passages from a product’s customer feedback. Do not use when it asks for a summary or paraphrase.
  - rule: Treat only existing customer-review text as evidence, not product descriptions, rating summaries, or review-submission prompts. Include every passage matching the requested scope, excluding unrelated shipping or delivery complaints when the question is specifically about the product. Preserve visible wording and boundaries verbatim—including capitalization, contractions, punctuation, and quotation marks—and verify any truncated text from its full version rather than inferring.

- **REWRITE** ['Audit every review sentence, including qualifiers']
  -> «Preserve every review criticism and qualifier»
  - when: Use when the task asks to extract criticisms from a shopping product’s customer reviews. Do not use when it asks only for ratings, specifications, or an overall summary.
  - rule: Treat every review-body statement that independently expresses criticism as relevant, including comparisons, qualifiers, later sentences, and suggestions for improvement. Preserve supported wording verbatim; exclude praise, review titles, and generic summaries that do not themselves state the requested criticism. Verify that abbreviated text is not mistaken for the complete review.

- **MERGE** ['Require an exact status match in complete order history', 'Treat the complete order-status grid as authoritative']
  -> «Match requested order statuses exactly»
  - when: Use when the task asks for orders with a specified status, especially the newest qualifying order. Do not use for product-search tasks.
  - rule: Treat the complete order history, not a recent-orders subset, as authoritative and require the visible status to match the requested wording exactly. Select all rows tied for the newest qualifying date and preserve the full requested value. If no exact match exists, return “N/A” rather than substituting a similar status.

- **REWRITE** ['Validate brand before using sorted price endpoints']
  -> «Validate brand membership at price endpoints»
  - when: Use when the task asks for a brand’s lowest and highest product prices.
  - rule: Treat the range as the minimum and maximum prices among genuinely brand-led products, not every search result containing the brand phrase. Verify endpoint candidates from the full product identity and exclude unrelated items or bundles where the brand appears only as an accessory.

- **MERGE** ['Preserve the exact search-result set', 'Preserve exact unit-price results']
  -> «Preserve the exact product set and derived prices»
  - when: Use when a shopping task asks for all products matching a stated search phrase and a price or per-item-price range. Do not use when the task explicitly specifies narrower category or exclusion criteria.
  - rule: Base the answer only on the complete result set for the exact phrase; do not add broadened-search variants or discard returned items merely because they resemble accessories. Preserve full product titles and verify every price used, including tied range endpoints. For per-item prices, divide the visible pack price by the verified count and do not round unless requested.

- **REWRITE** ['Build and reconcile one complete scoped product ledger']
  -> «Reconcile a complete scoped product set»
  - when: Use when the task asks for every available product matching a specified brand/type and an aggregate such as a price range.
  - rule: Include only visibly available products that satisfy the exact requested attributes; exclude merely related or look-alike keyword matches. Preserve distinct variants, deduplicate identical listings, and use full product names and displayed prices. Compute the aggregate from the same final reconciled set so every listed product contributes exactly once.

- **MERGE** ['Verify cancellation evidence before calculating refunds', 'Audit full order history and return a parser-safe total']
  -> «Distinguish refunds from original order totals»
  - when: Use when the task asks for refunds tied to cancellations within a date range. Do not use when it asks only for original order totals.
  - rule: Qualify orders using visible cancellation or refund evidence and the relevant date, not merely the order date or a completed status. Sum displayed refunded amounts, including shipping only when explicitly refunded; an order’s Grand Total does not prove the refund amount. Verify all plausible orders before deciding the qualifying total.

- **MERGE** ['Use order-detail subtotals for shopping spend', 'Calculate spend from completed orders’ Grand Totals']
  -> «Choose the requested order-spend measure»
  - when: Use when the task asks how much was spent on orders during a date range. Do not use when it asks for a different quantity unrelated to order spending.
  - rule: For generic total-spent questions, sum completed orders’ Grand Totals, including shipping and fees; exclude canceled orders unless requested. If the task explicitly asks for merchandise spending or subtotals, sum order-detail Subtotals instead. Verify each qualifying order’s date, status, and displayed amount rather than relying on abbreviated entries.

- **MERGE** ['Complete newest-to-oldest order-detail scan', 'Preserve the order list and verify efficiently', 'Preserve order-history progress and finish within budget']
  -> «Verify the latest exact-item order»
  - when: Use when the task asks when a specific item was last ordered. Do not use when it asks about storefront availability or recent browsing.
  - rule: Determine recency from account purchase history, but verify the exact product and variant in order contents rather than inferring from summaries, status, or near-identical names. Check all orders newer than the candidate and all same-date orders, then report the complete displayed order date and every qualifying tie.

- **REWRITE** ['Open the exact order and transcribe every item verbatim']
  -> «Transcribe items from the exact past order»
  - when: Use when the task asks for product names from a specified past order.
  - rule: Verify the order number, then use that order’s itemized details rather than an order summary or reorder list. Include every product row and preserve each displayed name verbatim, including punctuation and measurement marks; do not guess or normalize abbreviated text.

- **REWRITE** ['Map orders explicitly and normalize status labels']
  -> «Map exact order numbers to verified statuses»
  - when: Use when the task asks for the status of one or more specified order numbers.
  - rule: Match each requested order number exactly to its displayed status; do not infer from another order or omit requested orders. Return an explicit order-number-to-status mapping, using any required lowercase canonical labels and verifying spelling-sensitive variants against visible order evidence.

- **REWRITE** ['Open the exact order and transcribe the full labeled address']
  -> «Transcribe the labeled address for a specific order»
  - when: Use when the task asks for the billing or shipping address of a specific order.
  - rule: Match the exact order number, then use the address block explicitly labeled “Billing Address” or “Shipping Address” as requested. Preserve every visible postal field verbatim; do not substitute the other address type or include an adjacent telephone number as part of the address.

- **REWRITE** ['Verify explicit discounts across the full catalog']
  -> «Identify explicit discounts across the full catalog»
  - when: Use when the task asks to find discounted or sale items in a shopping catalog.
  - rule: Include only items with an explicit sale marker or both original and reduced prices; ratings, missing ratings, or a single price do not prove a discount. Verify the full catalog is covered, preserve each qualifying variant’s complete name, and return “N/A” if none qualify.

- **REWRITE** ['Preserve and label the rating scale']
  -> «Preserve and label the rating scale»
  - when: Use when the task asks for a product rating or asks to round a rating.
  - rule: Report and round the rating on the scale shown by the source, preserving its unit. Convert to another scale only when the task explicitly requests it; otherwise, any optional conversion must be clearly labeled.

- **REWRITE** ['Prove a category-scoped unique winner before purchasing']
  -> «Verify a unique category-scoped winner before purchasing»
  - when: Use when the task asks to purchase the highest-rated item within a specified category and budget.
  - rule: Compare all products strictly within the requested category and budget, and verify that exactly one has the highest displayed rating. If the top rating is tied or full eligibility cannot be established, do not purchase and report N/A; otherwise purchase only the verified winner.

## Stage 3 — conflict sweep (25 items)


- **KEEP_B** (cos=0.924) «Complete, verbatim extraction of review criticisms» vs «Extract Customer-Review Criticism Verbatim» — dropped «Complete, verbatim extraction of review criticisms»
  - why: The lessons overlap, but A improperly allows standalone media or error lines as review criticism even when they are not customer-review text. B gives the safer general rule: use only actual customer feedback, preserve it verbatim, and apply scope-specific exclusions.

- **BRANCH** (cos=0.876) «Aggregate qualifying orders from complete history» + «Choose the requested order-spend measure»
  - why: The lessons conflict on whether to use full order totals or merchandise subtotals, and the task question explicitly determines which measure applies.
  -> «Aggregate orders using the requested spend measure»
  - when: Use for order counts or spending aggregates across account order history, including date ranges and filters. Choose full totals versus merchandise subtotals based on the quantity named in the question.
  - rule: If the question explicitly requests merchandise spending or subtotals, sum qualifying order-detail Subtotals; otherwise, sum each qualifying completed order’s displayed Grand Total once, including shipping and fees. Review the complete history, apply all stated date, merchant, and status filters, and exclude canceled orders unless requested. For counts, count only qualifying orders.

- **BRANCH** (cos=0.865) «Establish the complete qualifying product set» + «Preserve the exact product set and derived prices»
  - why: The lessons conflict over whether to use a semantic product-type set that excludes accessories or preserve every result returned for an exact search phrase. The task question determines the intended set.
  -> «Choose the product set requested»
  - when: Use the question’s wording to decide between semantic product matching and exact-phrase result preservation. In either case, verify complete coverage, full titles, prices, and tied endpoints.
  - rule: If the question asks for products of a type or gives category/exclusion criteria, include synonymous and model variants but exclude accessories and broader look-alikes. If it asks for all products matching an exact search phrase, preserve the complete returned set without adding variants or removing accessory-like results. For per-item ranges, verify pack counts and divide without rounding unless requested.

- **BRANCH** (cos=0.856) «Aggregate orders using the requested spend measure» + «Calculate category spending from item-level order details»
  - why: The rules conflict for category-filtered spending: A’s default would sum whole order Grand Totals, while B includes only qualifying items. The task question reveals whether spending is for a category/item subset or whole qualifying orders.
  -> «Choose item-level or order-level spending aggregation»
  - when: Use the spending scope named in the question to choose between item-level category subtotals and whole-order totals. Apply all stated date, merchant, and status filters.
  - rule: If the question asks for spending on a category or item subset, sum only visibly qualifying item subtotals; include shared charges only when an attribution method is specified. Otherwise, sum each qualifying completed order’s Grand Total once, unless the question explicitly requests merchandise spending or subtotals. Exclude canceled orders unless requested.

- **BRANCH** (cos=0.833) «Qualify products before choosing price extremes» + «Choose the product set requested»
  - why: The lessons conflict on whether accessory-like or semantically mismatched search results should be excluded, and the task question determines which rule applies.
  -> «Choose the requested product set before finding price endpoints»
  - when: Use the question’s wording to distinguish semantic product matching from preservation of exact-phrase search results, then verify coverage and price endpoints.
  - rule: If the question requests a product type or states category/exclusion criteria, include valid synonymous and model variants while excluding accessories and broader look-alikes. If it requests all results matching an exact search phrase, preserve the complete returned set without adding or removing variants. Verify full titles, variants, prices, ties, and pack-count calculations.

## Result

42 -> 20 items (0 dropped as untriggerable, 4 branched, 1 contradictions collapsed) · LLM cost $0.41


## Final bank


### «Identify reviewers by semantic meaning»
- when: Use when a shopping task asks which reviewers mention a topic or combination of concepts. Do not use for product specifications or aggregate ratings.
- rule: Determine matches from each full review’s meaning, including close paraphrases, concepts split across sentences, and ambiguous relevant references unless the task requires exact wording. Return every qualifying reviewer name exactly as displayed, counting duplicate renderings once while preserving genuinely distinct name variants.

### «Identify reviewers by review-text criteria»
- when: Use when the task asks for reviewers whose review text mentions a specified topic or sentiment.
- rule: Evaluate every existing customer review by its full review body, excluding review-submission forms. Return each qualifying reviewer name verbatim; if none qualify, return exactly “N/A”.

### «Choose item-level or order-level spending aggregation»
- when: Use the spending scope named in the question to choose between item-level category subtotals and whole-order totals. Apply all stated date, merchant, and status filters.
- rule: If the question asks for spending on a category or item subset, sum only visibly qualifying item subtotals; include shared charges only when an attribution method is specified. Otherwise, sum each qualifying completed order’s Grand Total once, unless the question explicitly requests merchandise spending or subtotals. Exclude canceled orders unless requested.

### «Use calendar months and distinguish order count from fulfilled spend»
- when: Use when the task asks for order counts or fulfilled spending over a number of months as of a given date. Do not use calendar-month scope when the task explicitly requests a rolling interval.
- rule: Interpret the period as the applicable calendar months. Count all orders in scope regardless of status, but sum full displayed order totals only for the specifically required completed or fulfilled status; similar statuses do not qualify. Verify that adjacent-month orders are excluded.

### «Choose the requested product set before finding price endpoints»
- when: Use the question’s wording to distinguish semantic product matching from preservation of exact-phrase search results, then verify coverage and price endpoints.
- rule: If the question requests a product type or states category/exclusion criteria, include valid synonymous and model variants while excluding accessories and broader look-alikes. If it requests all results matching an exact search phrase, preserve the complete returned set without adding or removing variants. Verify full titles, variants, prices, ties, and pack-count calculations.

### «Allocate order shipping equally by item unit»
- when: Use when the task asks for category spending over a specified date or range and requires shipping to be included without specifying another allocation method. Do not use when it requests merchandise subtotal only or defines a different allocation.
- rule: Verify all matching orders using full item details, including variants, quantities, subtotals, and each order’s shipping charge. For each order, divide shipping equally among all item units, then add the shipping shares and merchandise subtotals only for qualifying units.

### «Verify the exact purchased item before extracting its attribute»
- when: Use when the task asks for the date, price, variant, or configuration of a previously purchased item.
- rule: Consider the complete order history, not only a recent-orders summary. Verify the exact product and variant in item-level details before extracting the requested field; do not substitute an order total, status, nearby row, or unrelated option. For “last ordered,” select the newest verified match, and report all matches if the task permits ties.

### «Extract Customer-Review Criticism Verbatim»
- when: Use when the task asks to extract criticisms or passages from a product’s customer feedback. Do not use when it asks for a summary or paraphrase.
- rule: Treat only existing customer-review text as evidence, not product descriptions, rating summaries, or review-submission prompts. Include every passage matching the requested scope, excluding unrelated shipping or delivery complaints when the question is specifically about the product. Preserve visible wording and boundaries verbatim—including capitalization, contractions, punctuation, and quotation marks—and verify any truncated text from its full version rather than inferring.

### «Preserve every review criticism and qualifier»
- when: Use when the task asks to extract criticisms from a shopping product’s customer reviews. Do not use when it asks only for ratings, specifications, or an overall summary.
- rule: Treat every review-body statement that independently expresses criticism as relevant, including comparisons, qualifiers, later sentences, and suggestions for improvement. Preserve supported wording verbatim; exclude praise, review titles, and generic summaries that do not themselves state the requested criticism. Verify that abbreviated text is not mistaken for the complete review.

### «Match requested order statuses exactly»
- when: Use when the task asks for orders with a specified status, especially the newest qualifying order. Do not use for product-search tasks.
- rule: Treat the complete order history, not a recent-orders subset, as authoritative and require the visible status to match the requested wording exactly. Select all rows tied for the newest qualifying date and preserve the full requested value. If no exact match exists, return “N/A” rather than substituting a similar status.

### «Validate brand membership at price endpoints»
- when: Use when the task asks for a brand’s lowest and highest product prices.
- rule: Treat the range as the minimum and maximum prices among genuinely brand-led products, not every search result containing the brand phrase. Verify endpoint candidates from the full product identity and exclude unrelated items or bundles where the brand appears only as an accessory.

### «Reconcile a complete scoped product set»
- when: Use when the task asks for every available product matching a specified brand/type and an aggregate such as a price range.
- rule: Include only visibly available products that satisfy the exact requested attributes; exclude merely related or look-alike keyword matches. Preserve distinct variants, deduplicate identical listings, and use full product names and displayed prices. Compute the aggregate from the same final reconciled set so every listed product contributes exactly once.

### «Distinguish refunds from original order totals»
- when: Use when the task asks for refunds tied to cancellations within a date range. Do not use when it asks only for original order totals.
- rule: Qualify orders using visible cancellation or refund evidence and the relevant date, not merely the order date or a completed status. Sum displayed refunded amounts, including shipping only when explicitly refunded; an order’s Grand Total does not prove the refund amount. Verify all plausible orders before deciding the qualifying total.

### «Verify the latest exact-item order»
- when: Use when the task asks when a specific item was last ordered. Do not use when it asks about storefront availability or recent browsing.
- rule: Determine recency from account purchase history, but verify the exact product and variant in order contents rather than inferring from summaries, status, or near-identical names. Check all orders newer than the candidate and all same-date orders, then report the complete displayed order date and every qualifying tie.

### «Transcribe items from the exact past order»
- when: Use when the task asks for product names from a specified past order.
- rule: Verify the order number, then use that order’s itemized details rather than an order summary or reorder list. Include every product row and preserve each displayed name verbatim, including punctuation and measurement marks; do not guess or normalize abbreviated text.

### «Map exact order numbers to verified statuses»
- when: Use when the task asks for the status of one or more specified order numbers.
- rule: Match each requested order number exactly to its displayed status; do not infer from another order or omit requested orders. Return an explicit order-number-to-status mapping, using any required lowercase canonical labels and verifying spelling-sensitive variants against visible order evidence.

### «Transcribe the labeled address for a specific order»
- when: Use when the task asks for the billing or shipping address of a specific order.
- rule: Match the exact order number, then use the address block explicitly labeled “Billing Address” or “Shipping Address” as requested. Preserve every visible postal field verbatim; do not substitute the other address type or include an adjacent telephone number as part of the address.

### «Identify explicit discounts across the full catalog»
- when: Use when the task asks to find discounted or sale items in a shopping catalog.
- rule: Include only items with an explicit sale marker or both original and reduced prices; ratings, missing ratings, or a single price do not prove a discount. Verify the full catalog is covered, preserve each qualifying variant’s complete name, and return “N/A” if none qualify.

### «Preserve and label the rating scale»
- when: Use when the task asks for a product rating or asks to round a rating.
- rule: Report and round the rating on the scale shown by the source, preserving its unit. Convert to another scale only when the task explicitly requests it; otherwise, any optional conversion must be clearly labeled.

### «Verify a unique category-scoped winner before purchasing»
- when: Use when the task asks to purchase the highest-rated item within a specified category and budget.
- rule: Compare all products strictly within the requested category and budget, and verify that exactly one has the highest displayed rating. If the top rating is tied or full eligibility cannot be established, do not purchase and report N/A; otherwise purchase only the verified winner.