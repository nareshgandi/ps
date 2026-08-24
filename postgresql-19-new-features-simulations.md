# PostgreSQL 19 — New Features: Small Definitions + Hands-On Simulations

> **Purpose:** A beginner-friendly blog companion for exploring the major PostgreSQL 19 features listed below.  
> The simulations are intentionally small so they can be run on a PostgreSQL 19 test instance.

> **Version note:** These examples target PostgreSQL 19. Some features are new in 19 and will not work on PostgreSQL 18 or earlier.

---

## 1. Property Graph Queries — SQL/PGQ

### Small definition

A **property graph** represents entities as **vertices**, relationships between entities as **edges**, and attributes of those entities or relationships as **properties**.

In PostgreSQL 19, SQL/PGQ lets us expose existing relational tables as a logical property graph and query relationships using graph-pattern syntax instead of writing traditional joins.

The important point is:

> PostgreSQL does **not** require you to move your data into a separate graph database. The graph is defined on top of relational tables.

### Simulation

We will use customers, orders, and the relationship between them.

```sql
DROP TABLE IF EXISTS customer_orders;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    customer_id integer PRIMARY KEY,
    name        text,
    city        text
);

CREATE TABLE orders (
    order_id     integer PRIMARY KEY,
    ordered_when date,
    amount       numeric(10,2)
);

CREATE TABLE customer_orders (
    customer_orders_id integer PRIMARY KEY,
    customer_id        integer REFERENCES customers(customer_id),
    order_id           integer REFERENCES orders(order_id)
);

INSERT INTO customers VALUES
(1, 'Alice', 'Hyderabad'),
(2, 'Bob',   'Bengaluru'),
(3, 'Carol', 'Chennai');

INSERT INTO orders VALUES
(101, CURRENT_DATE, 500),
(102, CURRENT_DATE, 1200),
(103, CURRENT_DATE - 1, 800);

INSERT INTO customer_orders VALUES
(1, 1, 101),
(2, 2, 102),
(3, 3, 103);
```

Create a property graph:

```sql
CREATE PROPERTY GRAPH shop_graph
    VERTEX TABLES (
        customers,
        orders
    )
    EDGE TABLES (
        customer_orders
        SOURCE customers
        DESTINATION orders
    );
```

Now ask a graph-style question:

```sql
SELECT *
FROM GRAPH_TABLE (
    shop_graph
    MATCH (c IS customers)-[co IS customer_orders]->(o IS orders)
    COLUMNS (
        c.name  AS customer_name,
        o.order_id,
        o.amount
    )
);
```

Conceptually:

```text
Alice  ----customer_orders----> Order 101
Bob    ----customer_orders----> Order 102
Carol  ----customer_orders----> Order 103
```

### What changed?

Before SQL/PGQ:

```sql
SELECT c.name, o.order_id, o.amount
FROM customers c
JOIN customer_orders co
  ON co.customer_id = c.customer_id
JOIN orders o
  ON o.order_id = co.order_id;
```

With SQL/PGQ:

```sql
MATCH (customer)-[relationship]->(order)
```

The relationship becomes explicit in the query.

**Takeaway:** SQL/PGQ gives PostgreSQL users a graph-querying model while keeping the underlying data relational.

---

## 2. REPACK — Reclaim Space and Reorganize Tables

### Small definition

`REPACK` rewrites a table to remove dead space and can optionally physically order the table using an index.

It brings together the main use cases of:

- `VACUUM FULL` — reclaim disk space by rewriting the table
- `CLUSTER` — rewrite a table according to an index

PostgreSQL 19 also adds:

```sql
REPACK (CONCURRENTLY)
```

which allows normal reads and writes to continue for most of the operation, with the stronger lock needed only briefly during the final file swap.

### Simulation

Create a table and generate dead tuples:

```sql
DROP TABLE IF EXISTS sales;

CREATE TABLE sales (
    sale_id     bigserial PRIMARY KEY,
    customer_id integer,
    amount      numeric(10,2),
    sale_date   date
);

INSERT INTO sales (customer_id, amount, sale_date)
SELECT
    (random() * 1000)::int,
    random() * 10000,
    CURRENT_DATE
FROM generate_series(1, 500000);
```

Check the table size:

```sql
SELECT pg_size_pretty(pg_total_relation_size('sales'));
```

Create dead tuples:

```sql
UPDATE sales
SET amount = amount * 1.10
WHERE sale_id <= 400000;

DELETE FROM sales
WHERE sale_id > 450000;
```

Compare normal vacuum with repacking:

```sql
VACUUM sales;
```

A normal `VACUUM` makes reusable space available inside the table.

Now:

```sql
REPACK sales;
```

The table is rewritten, allowing unused space to be returned to the operating system.

### Reorganize according to an index

```sql
CREATE INDEX sales_customer_id_idx
ON sales(customer_id);

REPACK sales USING INDEX sales_customer_id_idx;
```

### Concurrent version

```sql
REPACK (CONCURRENTLY) sales;
```

This is especially interesting for production systems because normal reads and writes can continue during most of the operation.

### Observe progress

While another session runs `REPACK`:

```sql
SELECT
    pid,
    relid::regclass,
    command,
    phase,
    heap_blks_total,
    heap_blks_scanned,
    index_rebuild_count
FROM pg_stat_progress_repack;
```

**Takeaway:** `REPACK` provides one clearer command for table rewriting, space reclamation, and optional physical reorganization.

---

## 3. Logical Replication of Sequence Values

### Small definition

PostgreSQL 19 can logically replicate sequence values.

Previously, logical replication primarily focused on table-row changes. PostgreSQL 19 adds support for keeping sequences synchronized as well.

Sequences can be published using:

```sql
CREATE PUBLICATION pub1
FOR ALL SEQUENCES;
```

PostgreSQL 19 also allows logical decoding to become active when `wal_level = replica` once a valid logical replication slot exists, avoiding the old requirement to restart the server just to change `wal_level` to `logical`.

### Simulation

On the publisher:

```sql
CREATE SEQUENCE order_id_seq
START WITH 1000
INCREMENT BY 1;
```

Create a publication:

```sql
CREATE PUBLICATION pub1
FOR ALL SEQUENCES;
```

On the subscriber, create the matching sequence:

```sql
CREATE SEQUENCE order_id_seq
START WITH 1000
INCREMENT BY 1;
```

Create the subscription using the appropriate publisher connection information:

```sql
CREATE SUBSCRIPTION sub1
CONNECTION 'host=PRIMARY_HOST dbname=postgres user=repuser password=PASSWORD'
PUBLICATION pub1;
```

Advance the sequence on the publisher:

```sql
SELECT nextval('order_id_seq');
SELECT nextval('order_id_seq');
SELECT nextval('order_id_seq');
```

On the subscriber:

```sql
SELECT last_value, is_called
FROM order_id_seq;
```

If the sequence becomes out of sync, PostgreSQL 19 provides:

```sql
ALTER SUBSCRIPTION sub1 REFRESH SEQUENCES;
```

### What to observe

```text
Publisher sequence
       |
       | sequence WAL changes
       v
Logical replication
       |
       v
Subscriber sequence
```

**Takeaway:** Logical replication becomes more complete for applications that depend on sequences for generated identifiers.

> **Lab note:** This simulation requires two PostgreSQL 19 instances. Do not run `CREATE SUBSCRIPTION` against your only local server.

---

## 4. Smarter Autovacuum + Parallel Index Vacuuming

### Small definition

PostgreSQL 19 improves autovacuum in two important ways:

1. A single autovacuum worker can use parallel workers to vacuum/clean indexes.
2. Autovacuum uses a scoring system to prioritize tables that need vacuuming or analyzing more urgently.

The new settings include:

```sql
autovacuum_max_parallel_workers
```

and scoring-related parameters such as:

```sql
autovacuum_vacuum_insert_scale_factor
autovacuum_vacuum_scale_factor
autovacuum_analyze_scale_factor
```

with corresponding scoring weights available in PostgreSQL 19.

### Simulation — parallel vacuum

Create a table with several indexes:

```sql
DROP TABLE IF EXISTS orders_big;

CREATE TABLE orders_big (
    order_id    bigserial PRIMARY KEY,
    customer_id integer,
    status      text,
    amount      numeric
);

CREATE INDEX orders_big_customer_idx
ON orders_big(customer_id);

CREATE INDEX orders_big_status_idx
ON orders_big(status);

CREATE INDEX orders_big_amount_idx
ON orders_big(amount);
```

Load data:

```sql
INSERT INTO orders_big (customer_id, status, amount)
SELECT
    (random() * 100000)::int,
    CASE
        WHEN random() < 0.5 THEN 'NEW'
        ELSE 'COMPLETED'
    END,
    random() * 10000
FROM generate_series(1, 1000000);
```

For a manual demonstration:

```sql
VACUUM (PARALLEL 3, VERBOSE) orders_big;
```

Check the maximum parallelism allowed for autovacuum:

```sql
SHOW autovacuum_max_parallel_workers;
```

For a lab environment, you can experiment with:

```sql
ALTER SYSTEM SET autovacuum_max_parallel_workers = 3;
SELECT pg_reload_conf();
```

### What is happening?

```text
Autovacuum worker
      |
      +---- index 1 ----> parallel worker
      |
      +---- index 2 ----> parallel worker
      |
      +---- index 3 ----> parallel worker
```

Only indexes that qualify for parallel vacuum participate, and the number of workers is still subject to global limits.

### Observe activity

```sql
SELECT
    pid,
    datname,
    relid::regclass,
    phase,
    heap_blks_scanned,
    indexes_total,
    indexes_processed
FROM pg_stat_progress_vacuum;
```

**Takeaway:** PostgreSQL 19 makes autovacuum more CPU-parallel for index work and more selective about which tables deserve attention first.

---

## 5. Enable or Disable Data Checksums While the Server Is Running

### Small definition

PostgreSQL data checksums protect data pages against certain forms of corruption.

PostgreSQL 19 allows checksums to be enabled or disabled **online**, without shutting down the database server.

Check the current state:

```sql
SHOW data_checksums;
```

### Simulation

First verify:

```sql
SHOW data_checksums;
```

On a PostgreSQL 19 test system, enable checksums online:

```sql
SELECT pg_enable_data_checksums();
```

Monitor progress:

```sql
SELECT
    pid,
    datname,
    phase,
    databases_total,
    databases_processed
FROM pg_stat_progress_data_checksums;
```

Check again:

```sql
SHOW data_checksums;
```

To disable them:

```sql
SELECT pg_disable_data_checksums();
```

### Important operational point

Enabling checksums is not free.

PostgreSQL needs to process existing data pages, which can generate substantial:

- I/O
- WAL
- replication traffic

So although the server remains available, this should still be treated as a significant maintenance operation.

**Takeaway:** "Online" does not mean "zero impact." The important change is that checksum state can now be changed without taking the database offline.

---

## 6. WAIT FOR LSN — Read Your Writes on a Standby

### Small definition

`WAIT FOR LSN` lets a PostgreSQL session wait until a standby has reached a particular WAL position.

This is useful for the classic problem:

```text
Application writes to PRIMARY
          |
          v
Application immediately reads from STANDBY
          |
          v
Data is not there yet
```

PostgreSQL 19 provides a direct way to wait for the standby to replay the relevant WAL.

### Simulation

On the primary:

```sql
UPDATE customers
SET city = 'Hyderabad'
WHERE customer_id = 1;
```

Capture the WAL position:

```sql
SELECT pg_current_wal_insert_lsn();
```

Suppose it returns:

```text
0/306EE20
```

On the standby:

```sql
WAIT FOR LSN '0/306EE20';
```

Once it returns:

```text
 status
---------
 success
```

the standby has replayed that WAL position.

Now the read can safely happen:

```sql
SELECT *
FROM customers
WHERE customer_id = 1;
```

### With a timeout

```sql
WAIT FOR LSN '0/306EE20'
WITH (
    MODE 'standby_replay',
    TIMEOUT '5s',
    NO_THROW
);
```

### Why this matters

This pattern provides an application-level consistency guarantee:

```text
WRITE
  |
  | obtain LSN
  v
PRIMARY
  |
  | WAL
  v
STANDBY
  |
  | WAIT FOR LSN
  v
READ
```

**Takeaway:** Instead of guessing whether replication has caught up, the application can wait for a precise WAL position.

---

## 7. Temporal UPDATE and DELETE — `FOR PORTION OF`

### Small definition

Temporal tables store information together with the period during which that information is valid.

PostgreSQL 18 introduced important application-time temporal table capabilities. PostgreSQL 19 extends this with:

```sql
FOR PORTION OF
```

for `UPDATE` and `DELETE`.

The key idea is:

> Change only a selected portion of a row's validity period instead of changing or deleting its entire history.

### Simulation

Create a temporal-style table:

```sql
DROP TABLE IF EXISTS product_prices;

CREATE TABLE product_prices (
    product_id integer,
    price      numeric(10,2),
    valid_at   daterange,
    PRIMARY KEY (product_id, valid_at WITHOUT OVERLAPS)
);
```

Insert history:

```sql
INSERT INTO product_prices VALUES
(
    101,
    100.00,
    daterange('2026-01-01', '2026-12-31', '[)')
);
```

View it:

```sql
SELECT *
FROM product_prices;
```

Imagine that the price should change only during April:

```text
Jan ----------------------------- Dec
          |------|
          April
```

Run:

```sql
UPDATE product_prices
SET price = 120.00
FOR PORTION OF valid_at
FROM DATE '2026-04-01'
TO DATE '2026-05-01'
WHERE product_id = 101;
```

PostgreSQL handles the temporal boundaries and creates the required remaining history.

Conceptually, the result becomes similar to:

```text
101 | 100.00 | [2026-01-01,2026-04-01)
101 | 120.00 | [2026-04-01,2026-05-01)
101 | 100.00 | [2026-05-01,2026-12-31)
```

### Temporal delete

Suppose we want to remove the product's validity only for June:

```sql
DELETE FROM product_prices
FOR PORTION OF valid_at
FROM DATE '2026-06-01'
TO DATE '2026-07-01'
WHERE product_id = 101;
```

Conceptually:

```text
Before:
Jan -------- Jun -------- Jul -------- Dec
             [ delete ]

After:
Jan -------- Jun          Jul -------- Dec
```

The history outside the targeted period remains.

**Takeaway:** `FOR PORTION OF` makes historical corrections much easier because you can modify or remove a specific time slice rather than manually splitting ranges yourself.

---

## 8. `pg_plan_advice` — Control the Query Planner

### Small definition

`pg_plan_advice` is a PostgreSQL 19 extension that lets you describe, reproduce, and alter important planner decisions using a plan-advice language.

It is useful when:

- a known-good plan needs to be stabilized
- you want to experiment with planner decisions
- the optimizer repeatedly chooses a plan you believe is unsuitable

### Simulation

Check whether the extension is available:

```sql
SELECT name, default_version
FROM pg_available_extensions
WHERE name = 'pg_plan_advice';
```

Install it:

```sql
CREATE EXTENSION pg_plan_advice;
```

Start with the extension documentation:

```sql
\dx pg_plan_advice
```

The general workflow is:

```text
Normal query
     |
     v
Planner chooses plan
     |
     | observe / generate advice
     v
Plan advice
     |
     v
Planner decision is guided
```

A practical lab should begin by comparing:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT *
FROM orders_big
WHERE customer_id = 5000;
```

Then investigate the plan-advice facilities exposed by the extension.

### Important warning

Do not treat planner advice as "force this plan forever."

The PostgreSQL planner normally adapts when:

- data distribution changes
- table size changes
- indexes change
- statistics change
- PostgreSQL itself improves

**Takeaway:** `pg_plan_advice` is best viewed as a controlled mechanism for planner experimentation and stabilization, not a replacement for good statistics and indexing.

---

## 9. `pg_stash_advice` — Automatically Apply Plan Advice

### Small definition

`pg_stash_advice` complements `pg_plan_advice`.

Instead of manually applying advice every time, it can store advice associated with a query identifier and automatically apply it when that query is planned.

Think of it as:

```text
Query
  |
  v
Query ID
  |
  v
Advice stash
  |
  v
Stored plan advice
  |
  v
Planner
```

### Simulation

Check availability:

```sql
SELECT name, default_version
FROM pg_available_extensions
WHERE name = 'pg_stash_advice';
```

Install:

```sql
CREATE EXTENSION pg_stash_advice;
```

The extension can maintain an advice stash in dynamic shared memory.

Check the relevant configuration:

```sql
SHOW pg_stash_advice.stash_name;
```

The general lab workflow is:

1. Identify a query with an undesirable plan.
2. Generate or construct appropriate `pg_plan_advice`.
3. Store the advice in a `pg_stash_advice` stash.
4. Run the query again.
5. Confirm that the advice is automatically applied.

### Operational caution

Advice is stored in dynamic shared memory, so storing large numbers of advice entries can consume memory.

**Takeaway:** `pg_stash_advice` turns planner advice from a one-off experiment into an automatically applied policy based on query identity.

---

## 10. Performance Improvements

### Small definition

PostgreSQL 19 contains many smaller performance improvements rather than one single "performance feature."

Important areas include:

- automatic scaling of I/O worker processes
- faster foreign-key checks
- query-planning improvements
- executor optimizations
- better parallel query behavior
- improvements to incremental sorting and joins
- more efficient processing of some expressions

### Simulation 1 — Foreign-key workload

Create parent and child tables:

```sql
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;

CREATE TABLE orders (
    order_id bigint PRIMARY KEY
);

CREATE TABLE order_items (
    item_id  bigint PRIMARY KEY,
    order_id bigint REFERENCES orders(order_id),
    amount   numeric
);

INSERT INTO orders
SELECT generate_series(1, 100000);

INSERT INTO order_items
SELECT
    generate_series(1, 1000000),
    ((random() * 99999)::bigint + 1),
    random() * 1000;
```

Now benchmark operations that exercise foreign-key checks:

```sql
EXPLAIN (ANALYZE, BUFFERS)
UPDATE order_items
SET amount = amount + 1
WHERE item_id <= 10000;
```

For meaningful comparisons, run the same workload on PostgreSQL 18 and PostgreSQL 19 with:

- the same hardware
- the same dataset
- the same configuration
- warmed/cold cache conditions documented
- multiple runs

### Simulation 2 — Observe I/O workers

Check relevant configuration:

```sql
SHOW io_method;
SHOW io_workers;
SHOW effective_io_concurrency;
```

Then use a large table:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM orders_big;
```

The purpose of this experiment is not to expect one fixed number of milliseconds.

Instead, observe:

```text
PostgreSQL 18
    |
    | workload
    v
I/O behavior
    |
    v
execution time

PostgreSQL 19
    |
    | same workload
    v
I/O behavior
    |
    v
execution time
```

**Takeaway:** PostgreSQL 19's performance work is spread across many parts of the database engine. Benchmarking the workload that matters to you is more meaningful than relying on a single headline number.

---

# Suggested Blog Structure

If this is being published as a PostgreSQL 19 learning blog, a simple structure is:

```text
PostgreSQL 19 New Features
|
+-- 1. Property Graphs
|
+-- 2. REPACK
|
+-- 3. Logical Replication of Sequences
|
+-- 4. Smarter Autovacuum
|
+-- 5. Online Data Checksums
|
+-- 6. WAIT FOR LSN
|
+-- 7. Temporal UPDATE/DELETE
|
+-- 8. pg_plan_advice
|
+-- 9. pg_stash_advice
|
+-- 10. Performance Improvements
```

For each feature, keep the same learning pattern:

```text
What is it?
     |
     v
Why was it needed?
     |
     v
Small example
     |
     v
Run the simulation
     |
     v
Observe the result
     |
     v
Production use case
```

---

# Quick Comparison

| PostgreSQL 19 feature | Simple meaning | Main DBA/Developer value |
|---|---|---|
| SQL/PGQ | Query relational data as a property graph | Relationship-heavy queries |
| `REPACK` | Rewrite/reorganize a table | Space reclamation + physical organization |
| Sequence replication | Replicate sequence state | Better logical-replication completeness |
| Smarter autovacuum | Better prioritization + parallel index vacuum | Better maintenance scalability |
| Online checksums | Change checksum state while running | Easier operational adoption |
| `WAIT FOR LSN` | Wait for a standby to reach an LSN | Read-your-writes consistency |
| `FOR PORTION OF` | Update/delete part of a temporal range | Easier historical corrections |
| `pg_plan_advice` | Guide planner decisions | Plan experimentation/stabilization |
| `pg_stash_advice` | Automatically apply stored advice | Repeatable query-plan guidance |
| Performance improvements | Many engine-level optimizations | Better throughput and latency |

---

# Final Takeaway

PostgreSQL 19 is not just about adding more SQL syntax.

The features can be grouped into four larger themes:

### 1. New ways to query data

SQL/PGQ introduces a graph-oriented way to query relationships while keeping the underlying data relational.

### 2. Better database maintenance

`REPACK`, smarter autovacuum, and online checksum operations make routine DBA work more flexible.

### 3. Better application consistency and history management

`WAIT FOR LSN` helps applications implement read-your-writes behavior with asynchronous replicas, while `FOR PORTION OF` makes temporal data modifications much easier.

### 4. More control and better performance

`pg_plan_advice`, `pg_stash_advice`, and numerous planner, executor, foreign-key, and I/O improvements give PostgreSQL 19 more tools for controlling and optimizing production workloads.

---

# Official PostgreSQL Documentation

- PostgreSQL 19 Release Notes: https://www.postgresql.org/docs/19/release.html
- Property Graphs: https://www.postgresql.org/docs/19/ddl-property-graphs.html
- REPACK: https://www.postgresql.org/docs/19/sql-repack.html
- Logical Replication of Sequences: https://www.postgresql.org/docs/19/logical-replication-sequences.html
- Routine Vacuuming / Parallel Vacuum: https://www.postgresql.org/docs/19/routine-vacuuming.html
- Data Checksums: https://www.postgresql.org/docs/19/checksums.html
- WAIT FOR: https://www.postgresql.org/docs/19/sql-wait-for.html
- Temporal Tables: https://www.postgresql.org/docs/19/ddl-temporal-tables.html
- Temporal UPDATE/DELETE: https://www.postgresql.org/docs/19/dml-application-time-update-delete.html
- pg_plan_advice: https://www.postgresql.org/docs/19/pgplanadvice.html
- pg_stash_advice: https://www.postgresql.org/docs/19/pgstashadvice.html
