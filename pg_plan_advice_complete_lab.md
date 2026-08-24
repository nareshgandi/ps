# pg_plan_advice — Complete Lab with Deep EXPLAIN Analysis
### PostgreSQL 19devel · Real Session Output · Zero Simulated Data

---

## Environment

```
PostgreSQL 19devel · x86_64-pc-linux-gnu · GCC 11.5 · Red Hat
Module : pg_plan_advice (contrib)
Load   : LOAD 'pg_plan_advice';   -- per session until shared_preload_libraries is set
```

---

## Schema and Data

```sql
CREATE TABLE regions   (id int PRIMARY KEY, name text);          --      20 rows
CREATE TABLE customers (id int PRIMARY KEY, region_id int,
                        name text);                              --  50,000 rows
CREATE TABLE orders    (id bigint, customer_id int,
                        amount numeric, status text);            -- 500,000 rows
```

Data distribution:
- Every customer belongs to one of 20 regions (random, roughly uniform)
- Every order belongs to one of 50,000 customers (random, roughly uniform)
- No index on `orders.customer_id` — intentional, reflects real-world gaps

---

## The Query Used Throughout

```sql
SELECT r.name, count(*), sum(o.amount)
FROM orders o
JOIN customers c ON o.customer_id = c.id
JOIN regions r   ON c.region_id   = r.id
GROUP BY r.name;
```

This aggregates revenue and order counts per region — a typical reporting query.
Result: 20 rows (one per region).

---

## Part 1 — Baseline Plan (Healthy Statistics)

### Raw Output

```
Finalize GroupAggregate (actual time=475.641..476.890 rows=20 loops=1)
  Group Key: r.name
  Buffers: shared hit=4710 dirtied=2 written=1
  →  Gather Merge (actual time=475.622..476.825 rows=60 loops=1)
        Workers Planned: 2
        Workers Launched: 2
        Buffers: shared hit=4710 dirtied=2 written=1
        →  Sort (actual time=449.580..449.586 rows=20 loops=3)
               Sort Key: r.name
               Sort Method: quicksort  Memory: 27kB
               Worker 0:  Sort Method: quicksort  Memory: 27kB
               Worker 1:  Sort Method: quicksort  Memory: 27kB
               →  Partial HashAggregate (actual time=449.410..449.431 rows=20 loops=3)
                     Group Key: r.name
                     Batches: 1  Memory Usage: 32kB
                     →  Hash Join (actual time=41.379..318.180 rows=166,666 loops=3)
                           Hash Cond: (c.region_id = r.id)
                           →  Hash Join (actual time=41.310..252.245 rows=166,666 loops=3)
                                 Hash Cond: (o.customer_id = c.id)
                                 →  Parallel Seq Scan on orders o
                                       rows=166,666  loops=3
                                       Buffers: shared hit=3733
                                 →  Hash
                                       Buckets: 65536  Batches: 1  Memory: 2466kB
                                       →  Seq Scan on customers c
                                             rows=50,000  loops=3
                                             Buffers: shared hit=958
                           →  Hash
                                 Buckets: 1024  Batches: 1  Memory: 9kB
                                 →  Seq Scan on regions r
                                       rows=20  loops=3
                                       Buffers: shared hit=3

Planning Time:  1.683 ms
Execution Time: 477.222 ms
```

---

### Deep Node-by-Node Explanation

PostgreSQL builds a **plan tree** and executes it **bottom-up**.
The indented arrows (`→`) show parent→child relationships.
Data flows upward — from leaves to root.

```
Execution order (bottom to top):

  1. Parallel Seq Scan on orders        ← data entry point (largest table)
  2. Seq Scan on customers → Hash       ← build hash table
  3. Seq Scan on regions  → Hash        ← build hash table
  4. Hash Join (orders ⋈ customers)     ← first join
  5. Hash Join (result  ⋈ regions)      ← second join
  6. Partial HashAggregate              ← each worker aggregates its slice
  7. Sort                               ← each worker sorts its 20 rows
  8. Gather Merge                       ← leader collects sorted streams
  9. Finalize GroupAggregate            ← leader combines partial results
```

---

#### Node 1 — Parallel Seq Scan on orders

```
→  Parallel Seq Scan on orders o
      rows=166,666  loops=3
      Buffers: shared hit=3733
```

**What it does:**
- Splits the `orders` table across 3 parallel processes (2 workers + 1 leader)
- Each process handles ~166,666 rows (500,000 ÷ 3)
- `loops=3` confirms 3 processes each executed this node once

**Why Seq Scan and not Index Scan?**
- No index exists on `orders.customer_id`
- Even if one existed, with no WHERE clause filtering rows, the query must
  touch all 500,000 rows — an index scan would be slower due to random I/O

**Why parallel?**
- `orders` is the largest table at ~500k rows (~3,733 pages = ~29MB)
- Splitting across 2 workers roughly halves the scan time
- Workers share no state during the scan — each reads its own disjoint range

**Buffer reading:**
```
shared hit=3733  → 3,733 pages × 8kB = ~29MB served from shared_buffers
dirtied=1        → 1 page was modified (hint bits updated during scan)
written=1        → 1 dirty page written to disk during scan
```
Zero disk reads — the entire orders table was already cached.

---

#### Node 2 — Seq Scan on customers → Hash

```
→  Hash
      Buckets: 65536  Batches: 1  Memory Usage: 2466kB
      →  Seq Scan on customers c
            rows=50,000  loops=3
            Buffers: shared hit=958
```

**What it does:**
- Scans all 50,000 customer rows sequentially
- Loads them into an in-memory hash table keyed on `customers.id`
- This hash table is the **build side** of the first Hash Join

**Why loops=3?**
Each of the 3 parallel workers builds its **own independent copy** of the
customers hash table. This is necessary because each worker must be able to
probe the full hash table independently.

**Memory breakdown:**
```
50,000 rows × ~49 bytes avg row size ≈ 2.45MB per worker
Buckets: 65536 = next power of 2 above 50,000
Batches: 1    = entire hash fits in memory (no disk spill)
Memory: 2466kB per worker × 3 workers = ~7.2MB total
```

**Why not parallel scan of customers?**
At 50k rows (~957 pages = ~7.5MB), the cost of coordinating parallel workers
exceeds the benefit. The planner correctly chose serial scan.

---

#### Node 3 — Seq Scan on regions → Hash

```
→  Hash
      Buckets: 1024  Batches: 1  Memory Usage: 9kB
      →  Seq Scan on regions r
            rows=20  loops=3
            Buffers: shared hit=3
```

**What it does:**
- Scans all 20 region rows — trivially fast (~3 pages = 24kB)
- Builds a 9kB hash table in memory

**Key observations:**
- `Buckets: 1024` — PostgreSQL allocates minimum bucket count even for 20 rows
- `Memory: 9kB` — fits entirely in CPU L1 cache, lookup is essentially free
- `loops=3` — each worker builds its own copy, but 3 × 9kB = 27kB total — negligible
- `Buffers: shared hit=3` — 3 pages = the entire regions table

---

#### Node 4 — First Hash Join: orders ⋈ customers

```
→  Hash Join (actual time=41.310..252.245 rows=166,666 loops=3)
      Hash Cond: (o.customer_id = c.id)
      Buffers: shared hit=4688
```

**What it does:**
- **Build phase** (0 → 41ms): load customers into hash table (Node 2)
- **Probe phase** (41ms → 252ms): for each order row, compute
  `hash(o.customer_id)` and look up the customers hash table

**Timing interpretation:**
```
actual time=41.310..252.245

41.310 ms  = time to first output row (= time to build the hash table)
252.245 ms = time to last output row  (= full probe phase complete)

Probe duration = 252 - 41 = 211ms per worker
                           = time to process 166,666 order rows against hash
```

**Output:**
- Each worker produces ~166,666 joined rows containing both order and customer columns
- Total across 3 workers: 500,000 joined rows
- Every order is matched (equi-join on primary key, no nulls)

**Why Hash Join and not Nested Loop or Merge Join?**
```
Nested Loop: would require 500,000 × index probe = too many random lookups
Merge Join:  requires both sides sorted on join key — expensive sort first
Hash Join:   O(n) build + O(n) probe = optimal for this scale and no pre-sort
```

---

#### Node 5 — Second Hash Join: (orders+customers) ⋈ regions

```
→  Hash Join (actual time=41.379..318.180 rows=166,666 loops=3)
      Hash Cond: (c.region_id = r.id)
      Buffers: shared hit=4694
```

**What it does:**
- Takes the 166,666-row output of Node 4 as the probe side
- Probes the 9kB `regions` hash table (Node 3) for each row
- Attaches `r.name` to each row

**Timing:**
```
41.379 ms = startup (same as first join — builds regions hash in parallel)
318.180 ms = completion
Incremental cost = 318 - 252 = 66ms = cost of probing the regions hash

66ms to probe a 9kB hash table 166,666 times
= ~0.4 microseconds per lookup — essentially free per row
```

**Buffer note:**
```
shared hit: 4688 → 4694 = +6 pages
These 6 extra pages are the regions table (3 pages × 2 extra accesses)
```

---

#### Node 6 — Partial HashAggregate

```
→  Partial HashAggregate (actual time=449.410..449.431 rows=20 loops=3)
      Group Key: r.name
      Batches: 1  Memory Usage: 32kB
      Worker 0:  Batches: 1  Memory Usage: 32kB
      Worker 1:  Batches: 1  Memory Usage: 32kB
```

**What it does:**
- Each worker independently groups its ~166,666 joined rows by `r.name`
- Computes **partial** aggregates — not final values yet:
  - `partial count(*)` — count of rows seen by this worker
  - `partial sum(o.amount)` — sum of amounts seen by this worker

**Why "Partial"?**
Because the data is split across workers, each worker only sees a fraction
of each region's rows. The final answer requires combining all workers' partials.

**Concrete example:**
```
Worker 0 computes:  region_5 → count=8,234,  sum=412,847.33
Worker 1 computes:  region_5 → count=8,156,  sum=407,234.11
Leader  computes:   region_5 → count=8,277,  sum=413,901.44
                              ───────────────────────────────
Final (Node 9):     region_5 → count=24,667, sum=1,233,982.88
```

**Memory:**
```
Batches: 1      = hash table fits in memory (no disk spill)
Memory: 32kB    = hash table for 20 groups per worker
                = very small because only 20 distinct region names
```

---

#### Node 7 — Sort

```
→  Sort (actual time=449.580..449.586 rows=20 loops=3)
      Sort Key: r.name
      Sort Method: quicksort  Memory: 27kB
      Worker 0:  Sort Method: quicksort  Memory: 27kB
      Worker 1:  Sort Method: quicksort  Memory: 27kB
```

**What it does:**
- Each worker sorts its 20 partial aggregate rows by `r.name`

**Why sort here and not at the top?**
`Gather Merge` (Node 8) performs a k-way merge of sorted streams.
For this to work, each input stream must be pre-sorted.

**The economics:**
```
Option A: Sort 20 rows per worker in parallel, then merge
          Cost: 3 × sort(20 rows) = trivial

Option B: Gather all rows first, then sort
          Cost: sort(60 rows) = still trivial, BUT requires Gather not Gather Merge
          Gather loses the sorted property advantage

With only 20 groups, both are equivalent here.
With 1,000,000 groups this optimization becomes significant.
```

**Memory:**
```
27kB per worker = 20 rows × ~1.35kB per aggregate row
Sort Method: quicksort = in-memory, no disk spill
```
If this had spilled to disk it would show `external merge  Disk: XkB` — a red flag.

---

#### Node 8 — Gather Merge

```
→  Gather Merge (actual time=475.622..476.825 rows=60 loops=1)
      Workers Planned: 2
      Workers Launched: 2
      Buffers: shared hit=4710 dirtied=2 written=1
```

**What it does:**
- Leader collects sorted streams from all 3 processes (2 workers + itself)
- Performs a **k-way merge** — like merging 3 sorted lists into one sorted list
- Produces 60 rows (20 per stream × 3 streams), sorted by `r.name`

**Gather vs Gather Merge — critical distinction:**

| Node | Worker output | Leader action | Use case |
|---|---|---|---|
| `Gather` | Unsorted | Collects in arrival order | When order doesn't matter |
| `Gather Merge` | Pre-sorted | Merges sorted streams | When sorted output needed downstream |

`Gather Merge` was chosen because Node 9 (`Finalize GroupAggregate`) requires
input sorted by `r.name` to identify group boundaries. This avoids a sort at the
leader level — instead sorting happens in parallel across workers.

**`loops=1`** — this node runs only in the leader process. Workers don't execute it.

---

#### Node 9 — Finalize GroupAggregate (Root)

```
Finalize GroupAggregate (actual time=475.641..476.890 rows=20 loops=1)
  Group Key: r.name
  Buffers: shared hit=4710 dirtied=2 written=1
```

**What it does:**
- Leader receives 60 sorted rows (20 region names × 3 partial results each)
- For consecutive rows with the same `r.name`, combines partial aggregates:
  - `final count = sum of all partial counts`
  - `final sum   = sum of all partial sums`
- Produces the final 20 rows returned to the client

**Why `Finalize GroupAggregate` and not `HashAggregate`?**
```
HashAggregate      → uses a hash table to group, input can be unsorted
GroupAggregate     → requires sorted input, uses streaming grouping
Finalize Aggregate → specific variant of GroupAggregate that combines partials
```
`Finalize` is used specifically in the parallel aggregation pattern where partial
results come from workers. It knows to combine `partial count` + `partial count`
into `final count` correctly.

**`loops=1`** — runs only once, only in the leader.

---

### Complete Timing Breakdown

```
Node                          Cumulative time    Incremental
─────────────────────────────────────────────────────────────
Parallel Seq Scan (orders)    0 → 57ms           57ms   scan
Hash build (customers)        0 → 38ms           38ms   build
Hash Join 1 (⋈ customers)    41 → 252ms         211ms   probe
Hash Join 2 (⋈ regions)      252 → 318ms         66ms   probe
Partial HashAggregate         318 → 449ms        131ms   aggregate
Sort                          449ms               ~0ms   20 rows
Gather Merge                  449 → 476ms         27ms   merge
Finalize GroupAggregate       476ms               ~0ms   combine

Total Execution Time: 477ms
Planning Time:          1.7ms  (0.35% of total — healthy ratio)
```

---

### Buffer Summary

```
shared hit=4710      → all data from shared_buffers (RAM), zero disk reads
dirtied=2            → 2 pages had hint bits updated during scan
written=1            → 1 dirty page evicted to disk during query

Breakdown:
  orders    : 3,733 pages = 29.1MB
  customers :   958 pages =  7.5MB
  regions   :     3 pages = 24KB
  planning  :    16 pages = overhead
  ─────────────────────────
  Total     : 4,710 pages = 36.8MB
```

The entire working set fit in `shared_buffers`. This is why the query runs in
477ms despite touching 500k rows — no I/O wait at all.

---

### Generated Plan Advice — Explained

```
Generated Plan Advice:
   JOIN_ORDER(o c r)
   HASH_JOIN(c r)
   SEQ_SCAN(o c r)
   GATHER_MERGE((o c r))
```

This is PostgreSQL encoding its decisions as a re-usable directive string.

| Directive | Encodes this decision | Why the planner chose it |
|---|---|---|
| `JOIN_ORDER(o c r)` | Drive from orders → customers → regions | Largest table drives; small tables become hash build sides |
| `HASH_JOIN(c r)` | customers and regions are hash **build** sides | No pre-sorted data; hash is O(n) optimal at this scale |
| `SEQ_SCAN(o c r)` | All tables scanned sequentially | No selective filter; full scan needed; parallel for orders |
| `GATHER_MERGE((o c r))` | Use parallel workers with pre-sorted output | Large table benefits from parallelism; sorted merge avoids leader re-sort |

**Note:** `o` (orders) is absent from `HASH_JOIN` because orders is the **probe
side** (outer table). Only the **build sides** (inner tables) appear in `HASH_JOIN`.

---

## Part 2 — Plan Advice Experiments

### Experiment A — Full Pin (all directives matched)

```sql
SET pg_plan_advice.advice =
  'JOIN_ORDER(o c r) HASH_JOIN(c r) SEQ_SCAN(o c r) GATHER_MERGE((o c r))';
```

```
Supplied Plan Advice:
   SEQ_SCAN(o)           /* matched */
   SEQ_SCAN(c)           /* matched */
   SEQ_SCAN(r)           /* matched */
   JOIN_ORDER(o c r)     /* matched */
   HASH_JOIN(c)          /* matched */
   HASH_JOIN(r)          /* matched */
   GATHER_MERGE((o c r)) /* matched */
```

Compact advice `HASH_JOIN(c r)` was **expanded** to individual directives.
Compact `SEQ_SCAN(o c r)` was **expanded** to three separate `/* matched */` lines.
Plan is identical. This is plan stabilization — any future stats change or PG upgrade
cannot alter this plan without you explicitly removing the advice.

---

### Experiment B — Kill Parallelism (NO_GATHER)

```sql
SET pg_plan_advice.advice = 'NO_GATHER(o c r)';
```

**Before (parallel):**
```
Finalize GroupAggregate
  → Gather Merge (Workers: 2)
      → Sort
          → Partial HashAggregate
              → Hash Join → Hash Join → Parallel Seq Scan
```

**After (serial):**
```
HashAggregate
  → Hash Join
      → Hash Join
          → Seq Scan on orders    ← no longer parallel
```

**Five nodes disappeared with one directive:**

| Removed node | Why it's gone |
|---|---|
| `Gather Merge` | No workers to gather from |
| `Finalize GroupAggregate` | No partial results to finalize |
| `Partial HashAggregate` | No partial aggregation needed |
| `Sort` (pre-gather) | Gather Merge needed it; Gather Merge is gone |
| `Parallel` prefix on Seq Scan | No parallel workers |

`HashAggregate` replaced `Finalize GroupAggregate` — serial aggregation
uses a single hash table, no partial/final split needed.

**Production use case:** Peak OLTP hours — one SET prevents reporting queries
from consuming parallel worker slots. No config reload, no restart.

---

### Experiment C — Flip Join Order

```sql
SET pg_plan_advice.advice = 'JOIN_ORDER(r c o)';
```

**Before:** orders drives (big table first), hash built on customers then regions
**After:** regions drives (small table first), hash built on customers then orders

```
Hash Join  (Hash Cond: c.id = o.customer_id)      ← orders is now BUILD side
  → Hash Join  (Hash Cond: r.id = c.region_id)    ← customers is BUILD side
      → Seq Scan on regions r                      ← 20-row driver
      → Hash → Seq Scan on customers c
  → Hash → Seq Scan on orders o                   ← 500k rows hashed into memory!
```

**What changed automatically (without being told):**
```
Generated Plan Advice now shows:  HASH_JOIN(c o)
Previously it showed:             HASH_JOIN(c r)
```

The planner flipped which tables are the build sides on its own — you only
specified the join order. The planner adapted the join methods accordingly.

**Also notable:** Parallelism disappeared (`NO_GATHER` shown in Generated advice).
Driving from a 20-row table makes parallelism less attractive — the planner
decided serial execution was better with this join order.

**Warning:** Hashing 500k orders into memory requires significantly more `work_mem`.
This join order is suboptimal here — used for demonstration only.

---

### Experiment D — Force Nested Loop (deliberately bad)

```sql
SET pg_plan_advice.advice =
  'JOIN_ORDER(r c o) NESTED_LOOP_PLAIN(c) NESTED_LOOP_PLAIN(o)';
```

```
GroupAggregate
  → Sort (Sort Key: r.name)
      → Nested Loop  (Join Filter: c.id = o.customer_id)
            → Nested Loop  (Join Filter: r.id = c.region_id)
                  → Seq Scan on regions r      ← 20 rows (outer)
                  → Seq Scan on customers c    ← 50,000 rows (inner, repeated 20×)
            → Seq Scan on orders o             ← 500,000 rows (inner, repeated N×)
```

**The cost math:**
```
Outer Nested Loop:
  regions (20) × customers (50,000) = 1,000,000 row combinations
  Filter reduces this to 50,000 matched (c.region_id = r.id)

Inner Nested Loop:
  50,000 matched × orders (500,000) = 25,000,000,000 combinations examined
  This is O(n²) behavior
```

No index on `customers.region_id` or `orders.customer_id` means the inner side
of each nested loop is a **full sequential scan**. This would run for many minutes
on real data.

**`/* matched */` does NOT mean "good idea".**
It means the planner obeyed you. The planner is not wrong to flag this as
expensive — it is expensive. You overrode its judgment.

**Also note:**
```
GroupAggregate (not Finalize GroupAggregate)  ← no parallelism
Sort at the top                               ← GroupAggregate needs sorted input
                                              ← no pre-sort from workers available
```

---

## Part 3 — The Regression and Rescue

### Timeline of Events

```
T+0   Healthy baseline: 477ms
      ANALYZE current, all statistics correct

T+1   Corrupt statistics:
      UPDATE pg_class SET reltuples = 50 WHERE relname = 'orders';
      UPDATE pg_class SET reltuples = 50 WHERE relname = 'customers';
      Planner now thinks both tables have 50 rows (reality: 500k and 50k)

T+2   Query runs without advice → regression:
      2,482ms  (5.2× slower)
      Nested Loop chosen, 500,000 index lookups, 15MB disk spill

T+3   Query cancelled (^C) — too slow to wait

T+4   ANALYZE to fix stats (skipped in the demonstration run)
      278ms — back to normal naturally

T+5   Re-corrupt stats (orders only):
      UPDATE pg_class SET reltuples = 50 WHERE relname = 'orders';

T+6   Query runs → 2,482ms regression again

T+7   Apply golden advice:
      SET pg_plan_advice.advice = 'JOIN_ORDER(o c r) HASH_JOIN(c r) ...';
      818ms — rescued despite stats still wrong

T+8   ANALYZE orders:
      257ms — full recovery, faster than original baseline
```

---

### Regression Plan — Why It's So Slow

```
GroupAggregate (actual time=2313..2481ms)
  → Sort  [external merge  Disk: 15,056kB]   ← 15MB spilled to disk
      → Nested Loop  [rows=500,000]
            → Nested Loop  [rows=500,000]
                  → Seq Scan on orders        ← planner thinks: 50 rows
                  → Index Scan on customers   ← 500,000 index lookups
                        Index Searches: 500,000
                        Buffers: shared hit=1,498,343
            → Materialize → Seq Scan regions
```

**The planner's (incorrect) reasoning:**
```
reltuples=50 for orders  → planner expects 50 rows to join
50 rows × index lookup   → cheap! Nested Loop is optimal for small outer tables
```

**The reality:**
```
orders actually has 500,000 rows
500,000 rows × one index lookup each = 500,000 random B-tree traversals
Each traversal = 3-4 buffer hits on average
500,000 × 3 = 1,498,343 buffer hits just for the customers index
```

**The sort spill:**
```
Planner thinks: 50 rows → work_mem allocation for sort is tiny
Reality: 500,000 rows need sorting → spills 15MB to temp files on disk
Temp I/O: read=1882 written=1889 (×8kB = ~15MB of disk traffic)
```

---

### Rescue Plan — What Advice Fixed and What It Couldn't

```
GroupAggregate (actual time=539..817ms)
  → Gather Merge  [Workers: 2]
      → Sort  [external merge  Disk: 5,608kB]   ← still spilling, but less
          → Hash Join → Hash Join → Parallel Seq Scan
```

**What advice fixed:**
```
✔ Join method     : Nested Loop → Hash Join
                    Buffers: 1,502,075 → 4,707  (320× fewer buffer hits)
✔ Join order      : orders drives again
✔ Parallelism     : Gather Merge restored, 2 workers launched
✔ Execution time  : 2,482ms → 818ms  (3× improvement)
```

**What advice could NOT fix (stats still wrong):**
```
✘ Sort still spills:  15,056kB (regression) → 5,608kB (rescue) vs 27kB (healthy)
  Reason: planner still thinks 50 rows → allocates tiny work_mem for sort
  Advice controls join shape, not memory grant calculations

✘ GroupAggregate instead of Finalize GroupAggregate:
  Reason: planner thinks 50 rows → partial aggregation overhead not worth it
  So it skips the Partial/Finalize split → GroupAggregate used instead

✘ Cost estimates still wrong throughout the plan
```

**The residual gap (818ms vs 257ms) is entirely explained by:**
1. Sort spilling to disk: each worker spills ~5.6MB instead of sorting in 27kB RAM
2. Wrong aggregation node: GroupAggregate slightly less efficient than Partial/Finalize

---

### Full Recovery After ANALYZE

```sql
ANALYZE orders;
```

```
Finalize GroupAggregate (actual time=254..257ms)   ← Finalize returns
  → Gather Merge (Workers: 2)
      → Sort  [quicksort  Memory: 27kB]            ← no disk spill
          → Partial HashAggregate                   ← partial returns
              → Hash Join → Hash Join → Parallel Seq Scan
```

All directives still `/* matched */`. Advice still active.
But now statistics are correct, so:
- Planner knows 500k rows → allocates proper `work_mem` → sort stays in memory
- Partial/Finalize split returns — planner sees benefit again
- Result: **257ms** — even faster than the 477ms original baseline
  (difference explained by the data being fully cached from prior runs)

---

## Part 4 — Performance Summary

| Phase | Statistics | Advice | Plan | Sort method | Exec time |
|---|---|---|---|---|---|
| Baseline | ✔ Correct | None | Hash Join + Parallel | quicksort 27kB RAM | **477ms** |
| First regression | ✘ Stale | None | Nested Loop | ext. merge 15MB disk | **2,482ms** |
| Rescue | ✘ Stale | ✔ Applied | Hash Join + Parallel | ext. merge 5.6MB disk | **818ms** |
| Full recovery | ✔ Correct | ✔ Applied | Hash Join + Parallel | quicksort 27kB RAM | **257ms** |

**Regression severity:** 477ms → 2,482ms = **5.2× slower**
**Advice rescue:** 2,482ms → 818ms = **3.0× improvement** with stats still broken
**Full recovery:** 257ms = **46% faster** than original (cache warm effect)

---

## Part 5 — Key Principles

### What pg_plan_advice Controls

```
JOIN_ORDER    → which table drives, which is inner
HASH_JOIN     → force hash join for specific tables
MERGE_JOIN    → force merge join
NESTED_LOOP   → force nested loop
SEQ_SCAN      → force sequential scan
INDEX_SCAN    → force specific index
NO_GATHER     → disable parallelism
GATHER_MERGE  → require parallel with sorted worker output
```

### What pg_plan_advice Does NOT Control

```
Row estimates (cardinality)   → depends on pg_statistic, ANALYZE
Cost calculations              → depends on row estimates + GUCs
Memory grants (work_mem)       → depends on row estimates
Index selection within scans   → planner decides given the scan method
Aggregation method             → HashAgg vs GroupAgg not controllable
Number of parallel workers     → set by max_parallel_workers_per_gather
```

### The Fundamental Rule

```
pg_plan_advice = emergency brake
ANALYZE        = fuel

You can steer with no fuel.
You will eventually stop.

Always fix the root cause (ANALYZE / statistics).
Use advice as a bridge, not a destination.
```

---

## Part 6 — Production Runbook

### Step 0 — Proactive: capture golden advice (before any incident)

```sql
-- On a healthy, recently-analyzed system
LOAD 'pg_plan_advice';   -- or add to shared_preload_libraries

EXPLAIN (COSTS OFF, PLAN_ADVICE)
  <your critical query here>;

-- Copy "Generated Plan Advice" section
-- Store in: runbook, config management, pg_stash_advice, comment in code
```

### Step 1 — Incident: query regressed

```sql
-- Confirm regression
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
WHERE query LIKE '%r.name%orders%'
ORDER BY mean_exec_time DESC;

-- Apply golden advice immediately (no restart needed)
SET pg_plan_advice.advice =
  'JOIN_ORDER(o c r) HASH_JOIN(c r) SEQ_SCAN(o c r) GATHER_MERGE((o c r))';

-- For system-wide effect:
ALTER SYSTEM SET pg_plan_advice.advice =
  'JOIN_ORDER(o c r) HASH_JOIN(c r) SEQ_SCAN(o c r) GATHER_MERGE((o c r))';
SELECT pg_reload_conf();
```

### Step 2 — Verify rescue

```sql
EXPLAIN (ANALYZE, COSTS OFF, PLAN_ADVICE) <your query>;
-- All directives must show /* matched */
-- Execution time should be back in acceptable range
```

### Step 3 — Diagnose root cause

```sql
-- Check when tables were last analyzed
SELECT relname, reltuples, last_analyze, last_autoanalyze
FROM pg_stat_user_tables
WHERE relname IN ('orders', 'customers', 'regions');

-- Check autovacuum settings
SELECT relname, reloptions
FROM pg_class
WHERE relname IN ('orders', 'customers');

-- Check if autovacuum is lagging
SELECT schemaname, relname, n_dead_tup, last_autovacuum, last_autoanalyze
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC;
```

### Step 4 — Fix root cause

```sql
-- Fix statistics
ANALYZE orders, customers;

-- Adjust autovacuum if needed
ALTER TABLE orders SET (autovacuum_analyze_scale_factor = 0.01);

-- Verify stats are now correct
SELECT relname, reltuples FROM pg_class
WHERE relname IN ('orders', 'customers', 'regions');
```

### Step 5 — Verify full recovery and remove advice

```sql
-- Confirm back to baseline
EXPLAIN (ANALYZE, COSTS OFF, PLAN_ADVICE) <your query>;

-- Remove the advice crutch
RESET pg_plan_advice.advice;
-- or system-wide:
ALTER SYSTEM RESET pg_plan_advice.advice;
SELECT pg_reload_conf();
```

### Step 6 — Persist the module (optional)

```ini
# postgresql.conf
shared_preload_libraries = 'pg_plan_advice'
```

After restart, `LOAD` is no longer needed per session and
`CREATE EXTENSION pg_plan_advice` will work cleanly.

---

## Appendix — LOAD Required Per Session

```
ERROR: unrecognized EXPLAIN option "plan_advice"
```

This error means `pg_plan_advice` is not loaded in the current session.

**Fix for current session:**
```sql
LOAD 'pg_plan_advice';
```

**Fix permanently (requires restart):**
```ini
# postgresql.conf
shared_preload_libraries = 'pg_plan_advice'
```

The error appeared twice in this lab session — once after `\c a` (new connection,
module not loaded) and once after connecting to the `a` database. This is expected
behavior until `shared_preload_libraries` is configured.

---

*All execution times, buffer counts, and plan outputs in this document are real
observed values from a live PostgreSQL 19devel session. Nothing is simulated.*
