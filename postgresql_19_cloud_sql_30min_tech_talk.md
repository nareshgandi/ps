# PostgreSQL 19 → Cloud SQL
## 30-Minute Tech Talk: From OSS Feature to Cloud SQL Product

**Audience:** Cloud SQL for PostgreSQL engineering team  
**Theme:** What PostgreSQL 19 gives us, what Cloud SQL needs to care about, and what Cloud SQL should test/productize.

> **Status note:** PostgreSQL 19 is still pre-GA as of August 25, 2026. The official PostgreSQL 19 release notes currently describe Beta 3, released August 13, 2026. Treat this deck as a PostgreSQL 19 readiness discussion, not a final-release contract.

---

# 1. Title

## PostgreSQL 19: From OSS to Cloud SQL

### What is new?
### What do we need to care about?
### What should we test before GA?

**Opening line**

> “Today I don't want to just walk through the PostgreSQL 19 release notes. I want to look at PostgreSQL 19 from a Cloud SQL product-engineering perspective.”

---

# 2. PostgreSQL 19 at a Glance

PostgreSQL 19 brings improvements across:

- Query optimization
- I/O and storage
- Autovacuum
- Logical replication
- High availability / recovery
- SQL/PGQ property graphs
- Temporal data
- Planner control
- Observability
- COPY / bulk loading
- JSON
- Security/authentication
- Upgrade tooling

The major areas especially relevant to Cloud SQL include:

- SQL/PGQ
- REPACK
- Sequence replication
- WAIT FOR
- Parallel autovacuum
- Async I/O
- Online checksum changes
- Temporal operations
- `pg_plan_advice`
- New monitoring/statistics information

**Speaker message**

> “There isn't one PostgreSQL 19 killer feature. The interesting thing is that several improvements directly touch managed-database concerns: replication, maintenance, I/O, observability and performance.”

---

# 3. PostgreSQL 19 Feature Map

| Area | PostgreSQL 19 highlights |
|---|---|
| 🚀 Performance | Optimizer improvements, async I/O, parallel autovacuum, SIMD COPY, radix sort |
| 🔄 Replication / HA | Sequence replication, `WAIT FOR`, logical replication improvements |
| 🧠 New SQL capabilities | SQL/PGQ, temporal `FOR PORTION OF`, `IGNORE NULLS` |
| 🛠 Operations | `REPACK`, online checksum changes, new statistics views, better EXPLAIN |

**Key transition**

> “For Cloud SQL, these four buckets don't have equal priority.”

---

# 4. Feature #1 — SQL/PGQ / Property Graphs

## What is a property graph?

A property graph represents:

- **Vertices** → entities
- **Edges** → relationships
- **Properties** → attributes

PostgreSQL 19 introduces SQL Property Graph Queries / SQL/PGQ.

## Simple example

```sql
CREATE TABLE customers (
    id bigint,
    name text
);

CREATE TABLE orders (
    id bigint,
    customer_id bigint
);
```

Conceptually:

```text
Customer
   |
   | PLACED
   ↓
 Order
```

## Why Cloud SQL cares

This is a **new SQL capability**, not just a performance improvement.

Cloud SQL needs to validate:

- Parser behavior
- Planner behavior
- Permissions
- Backup/restore
- Logical replication
- HA/failover
- Database migration
- Query Insights / observability
- Connection poolers/proxies

**Speaker point**

> “The interesting question isn't whether MATCH works. The question is whether the entire Cloud SQL lifecycle works around a property graph.”

---

# 5. Feature #2 — REPACK

PostgreSQL 19 introduces native REPACK functionality.

Example:

```sql
REPACK table_name;
```

and:

```sql
REPACK TABLE table_name CONCURRENTLY;
```

The `CONCURRENTLY` form is particularly interesting because it is designed to avoid blocking normal reads and writes.

## Why Cloud SQL cares

Cloud SQL customers already deal with:

- Table bloat
- Index bloat
- Maintenance windows
- Long-running VACUUM
- `pg_repack`
- Locking concerns

Cloud SQL also supports the `pg_repack` extension.

## Product question

Current model:

```text
Customer
   ↓
pg_repack
   ↓
External utility
   ↓
connections / locks / permissions
```

Potential native model:

```text
Customer
   ↓
Native PostgreSQL REPACK
   ↓
PostgreSQL engine
```

## Benchmark

Measure:

- Table size
- Index size
- Bloat before/after
- WAL generated
- CPU
- I/O
- Lock duration
- Replica lag
- Failover behavior
- Impact on foreground workload

---

# 6. Feature #3 — Logical Replication of Sequences

PostgreSQL 19 adds sequence synchronization to logical replication.

Example publication:

```sql
CREATE PUBLICATION pub
FOR ALL TABLES, ALL SEQUENCES;
```

Subscription support includes:

```sql
ALTER SUBSCRIPTION sub
REFRESH SEQUENCES;
```

## Before

```text
Table rows ───────────────→ Subscriber

Sequence state
     X
     |
     └── not automatically synchronized
```

## PostgreSQL 19

```text
Table rows ───────────────→ Subscriber
                             +
Sequence state ───────────→ Subscriber
```

## Why Cloud SQL cares

This directly affects:

- Database Migration Service
- CDC
- Logical replicas
- Cross-region architectures
- Migration cutovers
- Failover designs
- DR
- Applications using sequences/identity columns

## Demo candidate

```sql
CREATE SEQUENCE order_id_seq;

CREATE TABLE orders (
    id bigint DEFAULT nextval('order_id_seq'),
    description text
);
```

Generate writes on publisher and compare sequence state:

```sql
SELECT * FROM pg_sequences;
```

on publisher and subscriber.

**Priority: P0**

---

# 7. Feature #4 — Logical Replication and Effective WAL Level

PostgreSQL 19 adds behavior that can automatically enable the required WAL level for logical replication in appropriate circumstances.

A new:

```sql
effective_wal_level
```

reports the effective WAL level.

## Why this matters for Cloud SQL

Cloud SQL intentionally abstracts many PostgreSQL configuration details.

Cloud SQL uses product-specific configuration mechanisms such as:

```text
cloudsql.logical_decoding
```

rather than asking users to manage every low-level PostgreSQL setting.

## Cloud SQL question

Can PostgreSQL 19 simplify product configuration?

Potential model:

```text
Customer request
      ↓
Logical replication
      ↓
Cloud SQL determines required WAL behavior
      ↓
PostgreSQL 19
```

instead of requiring users to understand every low-level WAL setting.

---

# 8. Feature #5 — WAIT FOR

PostgreSQL 19 introduces:

```sql
WAIT FOR
```

which can wait for an LSN to be written, flushed, or replayed on a standby.

## Why it matters

This enables stronger read-your-writes semantics.

```text
WRITE
  |
  ↓
Primary
  |
  | WAL
  ↓
Replica
  |
  ↓
WAIT FOR replay
  |
  ↓
READ
```

## Cloud SQL opportunity

Relevant to:

- Read replicas
- Application consistency
- HA
- Cross-region replicas
- DR
- Migration workflows

## Performance test

Compare:

```text
write
  ↓
WAIT FOR
  ↓
read
```

against:

```text
write
  ↓
poll replica replay LSN
  ↓
read
```

Measure:

- Latency
- CPU
- Network
- Replica lag
- Behavior during replica stress

**Priority: P0**

---

# 9. Feature #6 — Parallel Autovacuum

PostgreSQL 19 allows autovacuum to use parallel workers for index vacuuming.

New settings include:

```text
autovacuum_max_parallel_workers
autovacuum_parallel_workers
```

PostgreSQL 19 also introduces scoring to prioritize tables that most need vacuum/analyze.

## Why Cloud SQL cares

This directly affects managed database resource consumption:

```text
Customer workload
       ↓
Autovacuum
       ↓
CPU + Memory + I/O
       ↓
Cloud SQL infrastructure
```

## Questions

Does parallel autovacuum:

- Reduce bloat faster?
- Increase CPU spikes?
- Increase disk I/O?
- Impact foreground queries?
- Impact replicas?
- Affect noisy-neighbor isolation?
- Change storage throughput requirements?

**This should definitely be benchmarked.**

---

# 10. Feature #7 — Async I/O

PostgreSQL 19 improves asynchronous I/O and introduces automatic control of I/O workers.

Relevant parameters include:

```text
io_min_workers
io_max_workers
io_worker_idle_timeout
io_worker_launch_interval
```

## Cloud SQL relevance

This is one of the **highest-priority performance areas**.

Cloud SQL sits between:

```text
PostgreSQL
     ↓
Cloud SQL storage architecture
     ↓
GCP storage
```

## Questions

How does PostgreSQL 19 I/O behavior interact with:

- Cloud SQL storage
- Enterprise vs Enterprise Plus
- Different machine families
- Read replicas
- High-IOPS workloads
- Storage latency
- Data cache

**Priority: P0 benchmark**

---

# 11. Feature #8 — TOAST Default Changes to LZ4

PostgreSQL 19 changes:

```text
default_toast_compression
```

from:

```text
pglz
```

to:

```text
lz4
```

## Cloud SQL implications

This changes default compression behavior and deserves benchmarking.

Test:

```text
pglz vs LZ4
```

Measure:

- INSERT throughput
- UPDATE throughput
- SELECT throughput
- Storage size
- CPU
- WAL
- Replication traffic

## Particularly important workloads

- JSONB
- Large TEXT
- Documents
- BYTEA
- Vector-related data
- Large TOASTed rows

---

# 12. Feature #9 — COPY Improvements

PostgreSQL 19 adds several COPY improvements.

## COPY FROM

Invalid input can be converted to NULL:

```sql
COPY t
FROM 'file.csv'
WITH (ON_ERROR SET_NULL);
```

## COPY TO

JSON output is supported:

```sql
COPY t TO STDOUT WITH (FORMAT JSON);
```

Additional options include:

```text
FORCE_ARRAY
```

PostgreSQL 19 also improves COPY performance using SIMD CPU instructions.

## Cloud SQL tests

Benchmark:

```text
COPY 1M rows
COPY 10M rows
COPY partitioned table
COPY JSON
COPY with malformed data
```

Measure:

- Throughput
- CPU
- WAL
- Storage
- Replica impact

---

# 13. Feature #10 — Query Planner Improvements

PostgreSQL 19 includes many optimizer improvements.

Examples include:

- Better treatment of some `NOT IN` queries
- More `LEFT JOIN` → `ANTI JOIN` transformations
- Better semijoin planning
- Memoize improvements
- Better hash join NULL handling
- Earlier aggregation in some join plans
- Other planner cost/plan improvements

## Why Cloud SQL cares

Customers can potentially get performance improvements **without changing application code**.

But:

> **Plan changes can also create regressions.**

Therefore:

```text
PG18 plan
     ↓
PG19 plan
     ↓
Same query?
     ↓
Different performance?
```

**Priority: P0 benchmark**

---

# 14. `pg_plan_advice`

PostgreSQL 19 introduces:

```text
pg_plan_advice
```

for controlling/stabilizing planner decisions.

There is also:

```text
pg_stash_advice
```

for automatically applying advice based on queries.

## Problem

```text
Customer query
      ↓
Planner
      ↓
Plan A
```

After statistics/data distribution changes:

```text
Same query
      ↓
Planner
      ↓
Plan B
      ↓
Performance regression
```

Planner advice can influence the planner's decision.

## Cloud SQL product questions

- Do we expose the extension?
- Do we integrate it with Query Insights?
- Can it help diagnose plan regressions?
- Should Cloud SQL provide recommendations?
- How do we prevent bad advice from becoming a persistent production problem?

This is a **product decision**, not merely an upstream compatibility test.

---

# 15. Observability Improvements

PostgreSQL 19 adds useful statistics and monitoring information.

Examples include new or enhanced views such as:

```text
pg_stat_lock
pg_stat_recovery
pg_stat_autovacuum_scores
pg_dsm_registry_allocations
```

and improvements to:

```text
pg_stat_progress_vacuum
pg_stat_progress_analyze
pg_stat_replication_slots
pg_stat_subscription_stats
```

## Cloud SQL opportunity

Connect:

```text
PostgreSQL system views
        +
Cloud Monitoring
        +
Query Insights
        +
Cloud SQL metrics
```

## Product questions

Which PG19 signals should become:

- Cloud Monitoring metrics?
- Query Insights signals?
- Alerts?
- Dashboards?
- Troubleshooting recommendations?

---

# 16. Not Every PostgreSQL Feature Is Equal for Cloud SQL

Classify every PostgreSQL 19 change into four buckets.

| Bucket | Meaning |
|---|---|
| 🟢 **Inherit** | PostgreSQL feature works automatically |
| 🔵 **Adapt** | Cloud SQL needs product/configuration work |
| 🟠 **Benchmark** | Feature changes performance/resource behavior |
| 🔴 **Product decision** | Decide whether/how to expose it |

## Examples

### Inherit

- `IGNORE NULLS`
- New SQL functions
- Many planner improvements
- Smaller syntax changes

### Adapt

- Logical replication
- REPACK
- Online checksums
- Authentication
- New configuration parameters

### Benchmark

- Async I/O
- Parallel autovacuum
- TOAST LZ4
- Planner changes
- COPY SIMD

### Product decision

- `pg_plan_advice`
- SQL/PGQ
- New observability metrics
- Native maintenance workflows

---

# 17. Cloud SQL Compatibility Matrix

| PostgreSQL 19 feature | Cloud SQL concern | Action |
|---|---|---|
| SQL/PGQ | SQL, backup, HA, replication | Compatibility |
| REPACK | Locks, storage, replicas | Performance + reliability |
| Sequence replication | Logical replication / DMS | **P0 validation** |
| WAIT FOR | Read replicas | **P0 validation** |
| Parallel autovacuum | CPU/I/O | **P0 benchmark** |
| Async I/O | Storage architecture | **P0 benchmark** |
| LZ4 TOAST default | Storage/CPU | Benchmark |
| Planner changes | Query regressions | Benchmark |
| `pg_plan_advice` | Extension exposure | Product decision |
| New system views | Monitoring | Product integration |
| COPY improvements | Data import/export | Benchmark |
| Temporal SQL | Compatibility | Functional testing |
| `IGNORE NULLS` | Compatibility | Functional testing |
| Online checksums | Managed storage model | Architecture review |

---

# 18. PostgreSQL 19 Cloud SQL Readiness Framework

```text
                 PostgreSQL 19
                       |
        +--------------+--------------+
        |              |              |
    Functional      Operational     Performance
       Tests           Tests            Tests
        |              |              |
        ↓              ↓              ↓
      SQL/API        HA/DR          CPU
      extensions     backup         I/O
      permissions    replicas       latency
      upgrades      failover       throughput
        |              |              |
        +--------------+--------------+
                       |
                       ↓
                Cloud SQL Product
                       |
        +--------------+--------------+
        |              |              |
      Expose        Integrate       Document
```

---

# 19. P0 Performance Test Suite

## 1. Async I/O

Compare:

```text
PG18 vs PG19
```

Workloads:

- Sequential scan
- Random read
- Large table scan
- Index scan

Metrics:

- QPS
- Latency
- IOPS
- CPU
- Storage latency

---

## 2. Parallel Autovacuum

Test:

```text
1 worker
2 workers
4 workers
8 workers
```

Measure:

- VACUUM duration
- Foreground latency
- CPU
- I/O
- Replica lag

---

## 3. Planner Regression

Use representative Cloud SQL workloads.

Compare:

```text
PG18 plan
vs
PG19 plan
```

Track:

- Plan changes
- Latency changes
- CPU changes
- Rows processed
- Buffers

---

## 4. TOAST LZ4

Compare:

```text
PG18 pglz
vs
PG19 lz4
```

Use:

- JSONB
- BYTEA
- Large TEXT

---

## 5. Logical Replication

Test:

- INSERT
- UPDATE
- DELETE
- Sequence changes
- Replica lag
- Slot behavior
- Failover
- Recovery

---

## 6. REPACK

Run:

```text
REPACK
REPACK CONCURRENTLY
```

while simultaneously running:

```text
OLTP workload
read replica
backup
monitoring
```

---

# 20. Cloud SQL-Specific Failure Matrix

For every major feature, ask:

> **What happens during...?**

## HA failover

```text
Feature
  ↓
Primary failure
  ↓
Standby promotion
  ↓
Does state survive?
```

## Read replica

```text
Feature
  ↓
Replication
  ↓
Does replica remain consistent?
```

## Backup/PITR

```text
Feature
  ↓
Backup
  ↓
Restore
  ↓
Is feature state preserved?
```

## Major upgrade

```text
PG18
 ↓
PG19
 ↓
Does metadata/config/state migrate?
```

## Clone

```text
Instance
 ↓
Clone
 ↓
Does feature continue to work?
```

---

# 21. Extensions — The Hidden Compatibility Surface

Cloud SQL has a curated list of supported PostgreSQL extensions.

For PG19, create an extension matrix.

```text
Extension
    |
    +-- Builds?
    |
    +-- Installs?
    |
    +-- Upgrade?
    |
    +-- Backup/restore?
    |
    +-- Replica?
    |
    +-- HA?
    |
    +-- DMS?
    |
    +-- Major upgrade?
```

Pay special attention to extensions that interact with:

- Planner
- WAL
- Shared memory
- Background workers
- Hooks
- Replication
- Storage

Examples of important Cloud SQL extensions to validate include:

- `pgvector`
- `pg_stat_statements`
- `pg_repack`
- `pg_hint_plan`
- `pglogical`
- `pg_partman`
- `pg_squeeze`
- `pg_wait_sampling`

---

# 22. PostgreSQL 19 Compatibility Changes

Not every important change is a new feature.

Important compatibility changes include:

- Warnings around successful MD5 authentication
- Removal of RADIUS support
- `standard_conforming_strings = on`
- Restrictions on CR/LF in database/role/tablespace names
- Changes to `inet`/`cidr` default index opclasses
- `max_locks_per_transaction` default changing from 64 → 128
- JIT disabled by default
- Renaming of a `pg_stat_subscription_stats` column
- Wait event type `BUFFERPIN` → `BUFFER`

## Cloud SQL implication

Compatibility testing is not:

> “Does PostgreSQL 19 start?”

It is:

> **“Which existing Cloud SQL customers change behavior when moved from 18 → 19?”**

---

# 23. Upgrade Testing

## PG18 → PG19

Test all Cloud SQL upgrade paths.

### Application compatibility

```text
JDBC
ODBC
libpq
Python
Go
Node.js
ORMs
```

### Database compatibility

```text
extensions
roles
permissions
functions
indexes
generated columns
partitioning
logical replication
```

### Operational compatibility

```text
backup
restore
PITR
clone
HA
failover
read replicas
monitoring
Query Insights
```

### Important

PostgreSQL major-version upgrades require an appropriate upgrade mechanism such as `pg_upgrade`, logical replication, or dump/restore.

Cloud SQL must turn the PostgreSQL upgrade model into a **managed, reliable customer experience**.

---

# 24. What Should Cloud SQL Productize?

## Candidate #1 — Native REPACK

Could Cloud SQL expose:

```text
Reclaim table space
```

as a managed operation?

Instead of requiring:

```text
pg_repack
```

---

## Candidate #2 — Read-Your-Writes API

Could Cloud SQL expose a convenient way to wait until a replica has replayed a particular write using PostgreSQL 19 `WAIT FOR`?

---

## Candidate #3 — Query Plan Stabilization

Potential workflow:

```text
Plan regression
       ↓
Query Insights
       ↓
pg_plan_advice
       ↓
Recommended remediation
```

---

## Candidate #4 — Autovacuum Intelligence

PostgreSQL 19 has new autovacuum scoring.

Cloud SQL could expose:

```text
Top tables needing vacuum
Top tables needing analyze
Why?
How urgent?
```

---

# 25. The Cloud SQL Performance Question

> ## “PostgreSQL 19 may be faster — but is it faster on Cloud SQL?”

Upstream benchmarks don't answer the Cloud SQL question.

PostgreSQL's I/O model interacts with:

```text
PostgreSQL
      ↓
Linux
      ↓
VM
      ↓
Cloud SQL architecture
      ↓
GCP storage
```

Similarly, parallel autovacuum interacts with:

```text
PostgreSQL workers
      ↓
CPU allocation
      ↓
Storage I/O
      ↓
Customer workload
```

Therefore:

> **Upstream benchmark ≠ Cloud SQL benchmark**

---

# 26. Proposed PG19 Benchmark Matrix

| Test | PG18 | PG19 | Cloud SQL editions | Metrics |
|---|---:|---:|---|---|
| OLTP | ✓ | ✓ | Enterprise / Enterprise Plus | p95/p99 |
| Sequential scan | ✓ | ✓ | Both | Latency |
| Async I/O | ✓ | ✓ | Both | IOPS/CPU |
| Autovacuum | ✓ | ✓ | Both | Duration/I/O |
| COPY | ✓ | ✓ | Both | Rows/sec |
| TOAST | ✓ | ✓ | Both | Size/CPU |
| Logical replication | ✓ | ✓ | Both | Lag |
| Sequence replication | — | ✓ | Both | Correctness |
| REPACK | — | ✓ | Both | Locks/WAL |
| Planner | ✓ | ✓ | Both | Regressions |
| HA failover | ✓ | ✓ | Both | RTO |
| Read replica | ✓ | ✓ | Both | Lag |

---

# 27. Proposed Priority Ranking

## P0 — Must Validate

1. **Async I/O**
2. **Logical replication / sequence replication**
3. **Parallel autovacuum**
4. **Major upgrade**
5. **HA / replica behavior**
6. **Planner regressions**

## P1 — Important

7. **REPACK**
8. **TOAST LZ4**
9. **COPY improvements**
10. **New observability**

## P2 — Product Exploration

11. **SQL/PGQ**
12. **`pg_plan_advice`**
13. **Temporal SQL**
14. **New authentication/configuration capabilities**

---

# 28. One End-to-End Experiment

Instead of ten tiny demos, use one integrated Cloud SQL experiment.

## Scenario

```text
Cloud SQL PostgreSQL
        |
        | OLTP workload
        ↓
      Orders
        |
        +---- sequence
        |
        +---- large JSONB
        |
        +---- index bloat
        |
        +---- read replica
```

## Phase 1

Run workload.

## Phase 2

Create bloat.

## Phase 3

Run:

```sql
REPACK TABLE orders CONCURRENTLY;
```

## Phase 4

Generate writes and sequence changes.

## Phase 5

Replicate.

## Phase 6

Use:

```text
WAIT FOR
```

to guarantee replay.

## Phase 7

Observe:

```text
CPU
I/O
replica lag
locks
WAL
query latency
```

## Phase 8

Fail over.

### Final question

> “Did PostgreSQL 19 work?”

versus:

> **“Did PostgreSQL 19 work as a Cloud SQL feature?”**

That is the central message of the talk.

---

# 29. PostgreSQL 19 → Cloud SQL Checklist

## OSS Compatibility

- [ ] PostgreSQL binaries
- [ ] Extensions
- [ ] SQL syntax
- [ ] System catalogs
- [ ] Configuration parameters
- [ ] Client drivers

## Cloud SQL Platform

- [ ] HA
- [ ] Read replicas
- [ ] Logical replication
- [ ] Backups
- [ ] PITR
- [ ] Clone
- [ ] Maintenance
- [ ] Major upgrade
- [ ] Monitoring
- [ ] Query Insights

## Performance

- [ ] CPU
- [ ] Memory
- [ ] I/O
- [ ] Storage
- [ ] WAL
- [ ] Replication lag
- [ ] Latency
- [ ] Throughput

## Product

- [ ] Expose feature?
- [ ] Hide feature?
- [ ] Cloud SQL flag?
- [ ] API?
- [ ] UI?
- [ ] Monitoring metric?
- [ ] Documentation?
- [ ] Support playbook?

---

# 30. Final Takeaway

## 1. What is cool in PostgreSQL 19?

> **SQL/PGQ, native REPACK, sequence replication, WAIT FOR, async I/O, parallel autovacuum, planner improvements and better observability.**

## 2. What does Cloud SQL need to care about?

> **Anything that touches storage, WAL, replication, HA, upgrades, extensions, resource management or customer-visible behavior.**

## 3. What should Cloud SQL build/test?

> **Don't just test whether the feature works. Test whether it works under Cloud SQL's managed lifecycle: workload + storage + HA + replica + backup + upgrade + observability.**

---

# The One Slide to Emphasize

## PostgreSQL Feature → Cloud SQL Feature

```text
             PostgreSQL 19
                   │
                   ▼
          ┌──────────────────┐
          │ Does SQL work?   │
          └────────┬─────────┘
                   │
                   ▼
          ┌──────────────────┐
          │ Does PG work?    │
          └────────┬─────────┘
                   │
                   ▼
          ┌──────────────────┐
          │ Does Cloud SQL   │
          │ architecture     │
          │ support it?      │
          └────────┬─────────┘
                   │
          ┌────────┼────────┐
          ▼        ▼        ▼
        HA/DR   Storage   Replication
          │        │        │
          └────────┼────────┘
                   ▼
          ┌──────────────────┐
          │ Does customer   │
          │ workload improve│
          │ or regress?     │
          └────────┬─────────┘
                   ▼
          ┌──────────────────┐
          │ Should Cloud SQL │
          │ PRODUCTIZE it?  │
          └──────────────────┘
```

> **This is the difference between “we support PostgreSQL 19” and “we have successfully productized PostgreSQL 19.”**

---

# Suggested 30-Minute Timing

| Time | Slides | Topic |
|---:|---|---|
| 0–2 min | 1–3 | Why PG19 matters |
| 2–10 min | 4–15 | Cool PostgreSQL 19 features |
| 10–18 min | 16–22 | **What Cloud SQL needs to care about** |
| 18–26 min | 23–27 | **Testing / benchmarking strategy** |
| 26–29 min | 28–29 | End-to-end experiment + checklist |
| 29–30 min | 30 | Takeaways |

## Presentation recommendation

Spend less time explaining every SQL feature and more time on **slides 16–27**.

That is where the talk becomes a **Cloud SQL engineering talk**, rather than a generic PostgreSQL 19 feature presentation.

---

# Official References

- PostgreSQL 19 Release Notes: https://www.postgresql.org/docs/19/release-19.html
- Cloud SQL for PostgreSQL Release Notes: https://docs.cloud.google.com/sql/docs/postgres/release-notes
- Cloud SQL PostgreSQL Database Versions: https://docs.cloud.google.com/sql/docs/postgres/db-versions
- Cloud SQL PostgreSQL Extensions: https://docs.cloud.google.com/sql/docs/postgres/extensions
- Cloud SQL Logical Replication: https://docs.cloud.google.com/sql/docs/postgres/replication/configure-logical-replication
