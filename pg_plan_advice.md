pg_plan_advice is a PostgreSQL module that lets you guide or constrain the query planner’s major plan decisions, such as join order, join method, scan method, and parallel execution.

JOIN_ORDER(o c r) tells PostgreSQL the preferred order in which to build the joins: orders → customers → regions.

```

postgres=# EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, PLAN_ADVICE)
SELECT r.name, count(*), sum(o.amount)
FROM orders o
JOIN customers c ON o.customer_id = c.id
JOIN regions r   ON c.region_id = r.id
GROUP BY r.name;
                                                      QUERY PLAN
----------------------------------------------------------------------------------------------------------------------
 Finalize GroupAggregate (actual time=216.565..216.652 rows=20.00 loops=1)
   Group Key: r.name
   Buffers: shared hit=4653
   ->  Gather Merge (actual time=216.552..216.619 rows=60.00 loops=1)
         Workers Planned: 2
         Workers Launched: 2
         Buffers: shared hit=4653
         ->  Sort (actual time=207.256..207.258 rows=20.00 loops=3)
               Sort Key: r.name
               Sort Method: quicksort  Memory: 27kB
               Buffers: shared hit=4653
               Worker 0:  Sort Method: quicksort  Memory: 27kB
               Worker 1:  Sort Method: quicksort  Memory: 27kB
               ->  Partial HashAggregate (actual time=207.208..207.214 rows=20.00 loops=3)
                     Group Key: r.name
                     Batches: 1  Memory Usage: 32kB
                     Buffers: shared hit=4637
                     Worker 0:  Batches: 1  Memory Usage: 32kB
                     Worker 1:  Batches: 1  Memory Usage: 32kB
                     ->  Hash Join (actual time=26.542..147.971 rows=166666.67 loops=3)
                           Hash Cond: (c.region_id = r.id)
                           Buffers: shared hit=4637
                           ->  Hash Join (actual time=26.509..118.287 rows=166666.67 loops=3)
                                 Hash Cond: (o.customer_id = c.id)
                                 Buffers: shared hit=4634
                                 ->  Parallel Seq Scan on orders o (actual time=0.004..13.363 rows=166666.67 loops=3)
                                       Buffers: shared hit=3677
                                 ->  Hash (actual time=26.326..26.327 rows=50000.00 loops=3)
                                       Buckets: 65536  Batches: 1  Memory Usage: 2466kB
                                       Buffers: shared hit=957
                                       ->  Seq Scan on customers c (actual time=0.009..9.326 rows=50000.00 loops=3)
                                             Buffers: shared hit=957
                           ->  Hash (actual time=0.024..0.025 rows=20.00 loops=3)
                                 Buckets: 1024  Batches: 1  Memory Usage: 9kB
                                 Buffers: shared hit=3
                                 ->  Seq Scan on regions r (actual time=0.015..0.017 rows=20.00 loops=3)
                                       Buffers: shared hit=3
 Planning:
   Buffers: shared hit=10
 Planning Time: 0.586 ms
 Generated Plan Advice:
   JOIN_ORDER(o c r)
   HASH_JOIN(c r)
   SEQ_SCAN(o c r)
   GATHER_MERGE((o c r))
 Execution Time: 216.752 ms
(46 rows)

postgres=#

```

```

postgres=# SELECT r.name, count(*), sum(o.amount)
FROM orders o
JOIN customers c ON o.customer_id = c.id
JOIN regions r   ON c.region_id = r.id
GROUP BY r.name;
   name    | count |     sum
-----------+-------+-------------
 region_1  | 24801 | 12402325.92
 region_10 | 25368 | 12664350.81
 region_11 | 24870 | 12457240.64
 region_12 | 24891 | 12391240.12
 region_13 | 24862 | 12403646.41
 region_14 | 24712 | 12474742.64
 region_15 | 24773 | 12393793.76
 region_16 | 25053 | 12478635.56
 region_17 | 24945 | 12494437.62
 region_18 | 25135 | 12543202.01
 region_19 | 25123 | 12571811.69
 region_2  | 25173 | 12651688.95
 region_20 | 25186 | 12543224.57
 region_3  | 24804 | 12352951.86
 region_4  | 25004 | 12512238.21
 region_5  | 25212 | 12640436.31
 region_6  | 24767 | 12346059.09
 region_7  | 25056 | 12515905.86
 region_8  | 25121 | 12636730.16
 region_9  | 25144 | 12558248.54
(20 rows)

postgres=# EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, PLAN_ADVICE)
SELECT r.name, count(*), sum(o.amount)
FROM orders o
JOIN customers c ON o.customer_id = c.id
JOIN regions r   ON c.region_id = r.id
GROUP BY r.name;
                                                      QUERY PLAN

---------------------------------------------------------------------------------------------
-------------------------
 Finalize GroupAggregate (actual time=224.039..226.053 rows=20.00 loops=1)
   Group Key: r.name
   Buffers: shared hit=4653
   ->  Gather Merge (actual time=224.026..226.006 rows=60.00 loops=1)
         Workers Planned: 2
         Workers Launched: 2
         Buffers: shared hit=4653
         ->  Sort (actual time=216.879..216.883 rows=20.00 loops=3)
               Sort Key: r.name
               Sort Method: quicksort  Memory: 27kB
               Buffers: shared hit=4653
               Worker 0:  Sort Method: quicksort  Memory: 27kB
               Worker 1:  Sort Method: quicksort  Memory: 27kB
               ->  Partial HashAggregate (actual time=216.803..216.814 rows=20.00 loops=3)
                     Group Key: r.name
                     Batches: 1  Memory Usage: 32kB
                     Buffers: shared hit=4637
                     Worker 0:  Batches: 1  Memory Usage: 32kB
                     Worker 1:  Batches: 1  Memory Usage: 32kB
                     ->  Hash Join (actual time=32.490..148.169 rows=166666.67 loops=3)
                           Hash Cond: (c.region_id = r.id)
                           Buffers: shared hit=4637
                           ->  Hash Join (actual time=32.451..124.637 rows=166666.67 loops=3)
                                 Hash Cond: (o.customer_id = c.id)
                                 Buffers: shared hit=4634
                                 ->  Parallel Seq Scan on orders o (actual time=0.004..12.020
 rows=166666.67 loops=3)
                                       Buffers: shared hit=3677
                                 ->  Hash (actual time=32.284..32.284 rows=50000.00 loops=3)
                                       Buckets: 65536  Batches: 1  Memory Usage: 2466kB
                                       Buffers: shared hit=957
                                       ->  Seq Scan on customers c (actual time=0.009..9.475
rows=50000.00 loops=3)
                                             Buffers: shared hit=957
                           ->  Hash (actual time=0.027..0.027 rows=20.00 loops=3)
                                 Buckets: 1024  Batches: 1  Memory Usage: 9kB
                                 Buffers: shared hit=3
                                 ->  Seq Scan on regions r (actual time=0.018..0.019 rows=20.
00 loops=3)
                                       Buffers: shared hit=3
 Planning:
   Buffers: shared hit=10
 Planning Time: 0.694 ms
 Generated Plan Advice:
   JOIN_ORDER(o c r)
   HASH_JOIN(c r)
   SEQ_SCAN(o c r)
   GATHER_MERGE((o c r))
 Execution Time: 226.183 ms
(46 rows)

postgres=#
postgres=#
postgres=#
postgres=# EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, PLAN_ADVICE)
SELECT r.name, count(*), sum(o.amount)
FROM orders o
JOIN customers c ON o.customer_id = c.id
JOIN regions r   ON c.region_id = r.id
GROUP BY r.name;
                                                      QUERY PLAN
----------------------------------------------------------------------------------------------------------------------
 Finalize GroupAggregate (actual time=216.565..216.652 rows=20.00 loops=1)
   Group Key: r.name
   Buffers: shared hit=4653
   ->  Gather Merge (actual time=216.552..216.619 rows=60.00 loops=1)
         Workers Planned: 2
         Workers Launched: 2
         Buffers: shared hit=4653
         ->  Sort (actual time=207.256..207.258 rows=20.00 loops=3)
               Sort Key: r.name
               Sort Method: quicksort  Memory: 27kB
               Buffers: shared hit=4653
               Worker 0:  Sort Method: quicksort  Memory: 27kB
               Worker 1:  Sort Method: quicksort  Memory: 27kB
               ->  Partial HashAggregate (actual time=207.208..207.214 rows=20.00 loops=3)
                     Group Key: r.name
                     Batches: 1  Memory Usage: 32kB
                     Buffers: shared hit=4637
                     Worker 0:  Batches: 1  Memory Usage: 32kB
                     Worker 1:  Batches: 1  Memory Usage: 32kB
                     ->  Hash Join (actual time=26.542..147.971 rows=166666.67 loops=3)
                           Hash Cond: (c.region_id = r.id)
                           Buffers: shared hit=4637
                           ->  Hash Join (actual time=26.509..118.287 rows=166666.67 loops=3)
                                 Hash Cond: (o.customer_id = c.id)
                                 Buffers: shared hit=4634
                                 ->  Parallel Seq Scan on orders o (actual time=0.004..13.363 rows=166666.67 loops=3)
                                       Buffers: shared hit=3677
                                 ->  Hash (actual time=26.326..26.327 rows=50000.00 loops=3)
                                       Buckets: 65536  Batches: 1  Memory Usage: 2466kB
                                       Buffers: shared hit=957
                                       ->  Seq Scan on customers c (actual time=0.009..9.326 rows=50000.00 loops=3)
                                             Buffers: shared hit=957
                           ->  Hash (actual time=0.024..0.025 rows=20.00 loops=3)
                                 Buckets: 1024  Batches: 1  Memory Usage: 9kB
                                 Buffers: shared hit=3
                                 ->  Seq Scan on regions r (actual time=0.015..0.017 rows=20.00 loops=3)
                                       Buffers: shared hit=3
 Planning:
   Buffers: shared hit=10
 Planning Time: 0.586 ms
 Generated Plan Advice:
   JOIN_ORDER(o c r)
   HASH_JOIN(c r)
   SEQ_SCAN(o c r)
   GATHER_MERGE((o c r))
 Execution Time: 216.752 ms
(46 rows)

postgres=# SET pg_plan_advice.advice =
'JOIN_ORDER(o c r)
 HASH_JOIN(c r)
 SEQ_SCAN(o c r)
 GATHER_MERGE((o c r))';
SET
postgres=# EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, PLAN_ADVICE)
SELECT r.name, count(*), sum(o.amount)
FROM orders o
JOIN customers c ON o.customer_id = c.id
JOIN regions r   ON c.region_id = r.id
GROUP BY r.name;
                                                      QUERY PLAN
----------------------------------------------------------------------------------------------------------------------
 Finalize GroupAggregate (actual time=205.059..207.919 rows=20.00 loops=1)
   Group Key: r.name
   Buffers: shared hit=4653
   ->  Gather Merge (actual time=205.043..207.869 rows=60.00 loops=1)
         Workers Planned: 2
         Workers Launched: 2
         Buffers: shared hit=4653
         ->  Sort (actual time=194.579..194.583 rows=20.00 loops=3)
               Sort Key: r.name
               Sort Method: quicksort  Memory: 27kB
               Buffers: shared hit=4653
               Worker 0:  Sort Method: quicksort  Memory: 27kB
               Worker 1:  Sort Method: quicksort  Memory: 27kB
               ->  Partial HashAggregate (actual time=194.520..194.527 rows=20.00 loops=3)
                     Group Key: r.name
                     Batches: 1  Memory Usage: 32kB
                     Buffers: shared hit=4637
                     Worker 0:  Batches: 1  Memory Usage: 32kB
                     Worker 1:  Batches: 1  Memory Usage: 32kB
                     ->  Hash Join (actual time=21.967..136.117 rows=166666.67 loops=3)
                           Hash Cond: (c.region_id = r.id)
                           Buffers: shared hit=4637
                           ->  Hash Join (actual time=21.923..107.177 rows=166666.67 loops=3)
                                 Hash Cond: (o.customer_id = c.id)
                                 Buffers: shared hit=4634
                                 ->  Parallel Seq Scan on orders o (actual time=0.005..10.800 rows=166666.67 loops=3)
                                       Buffers: shared hit=3677
                                 ->  Hash (actual time=21.658..21.658 rows=50000.00 loops=3)
                                       Buckets: 65536  Batches: 1  Memory Usage: 2466kB
                                       Buffers: shared hit=957
                                       ->  Seq Scan on customers c (actual time=0.017..7.734 rows=50000.00 loops=3)
                                             Buffers: shared hit=957
                           ->  Hash (actual time=0.032..0.032 rows=20.00 loops=3)
                                 Buckets: 1024  Batches: 1  Memory Usage: 9kB
                                 Buffers: shared hit=3
                                 ->  Seq Scan on regions r (actual time=0.021..0.023 rows=20.00 loops=3)
                                       Buffers: shared hit=3
 Planning Time: 0.390 ms
 Supplied Plan Advice:
   SEQ_SCAN(o) /* matched */
   SEQ_SCAN(c) /* matched */
   SEQ_SCAN(r) /* matched */
   JOIN_ORDER(o c r) /* matched */
   HASH_JOIN(c) /* matched */
   HASH_JOIN(r) /* matched */
   GATHER_MERGE((o c r)) /* matched */
 Generated Plan Advice:
   JOIN_ORDER(o c r)
   HASH_JOIN(c r)
   SEQ_SCAN(o c r)
   GATHER_MERGE((o c r))
 Execution Time: 208.080 ms
(52 rows)

postgres=# RESET pg_plan_advice.advice;
RESET
postgres=# SET pg_plan_advice.advice = 'NO_GATHER(o c r)';
SET
postgres=# EXPLAIN (ANALYZE, COSTS OFF, PLAN_ADVICE)
SELECT r.name, count(*), sum(o.amount)
FROM orders o
JOIN customers c ON o.customer_id = c.id
JOIN regions r   ON c.region_id = r.id
GROUP BY r.name;
                                            QUERY PLAN
--------------------------------------------------------------------------------------------------
 HashAggregate (actual time=318.296..318.305 rows=20.00 loops=1)
   Group Key: r.name
   Batches: 1  Memory Usage: 32kB
   Buffers: shared hit=3997
   ->  Hash Join (actual time=7.422..212.838 rows=500000.00 loops=1)
         Hash Cond: (c.region_id = r.id)
         Buffers: shared hit=3997
         ->  Hash Join (actual time=7.399..153.469 rows=500000.00 loops=1)
               Hash Cond: (o.customer_id = c.id)
               Buffers: shared hit=3996
               ->  Seq Scan on orders o (actual time=0.004..18.996 rows=500000.00 loops=1)
                     Buffers: shared hit=3677
               ->  Hash (actual time=7.280..7.281 rows=50000.00 loops=1)
                     Buckets: 65536  Batches: 1  Memory Usage: 2466kB
                     Buffers: shared hit=319
                     ->  Seq Scan on customers c (actual time=0.009..3.433 rows=50000.00 loops=1)
                           Buffers: shared hit=319
         ->  Hash (actual time=0.017..0.018 rows=20.00 loops=1)
               Buckets: 1024  Batches: 1  Memory Usage: 9kB
               Buffers: shared hit=1
               ->  Seq Scan on regions r (actual time=0.011..0.013 rows=20.00 loops=1)
                     Buffers: shared hit=1
 Planning:
   Buffers: shared hit=10
 Planning Time: 0.307 ms
 Supplied Plan Advice:
   NO_GATHER(o) /* matched */
   NO_GATHER(c) /* matched */
   NO_GATHER(r) /* matched */
 Generated Plan Advice:
   JOIN_ORDER(o c r)
   HASH_JOIN(c r)
   SEQ_SCAN(o c r)
   NO_GATHER(o c r)
 Execution Time: 318.382 ms
(35 rows)

postgres=# RESET pg_plan_advice.advice;
RESET
postgres=# SET pg_plan_advice.advice =
'JOIN_ORDER(r c o)';
SET
postgres=# EXPLAIN (ANALYZE, COSTS OFF, PLAN_ADVICE)
SELECT r.name, count(*), sum(o.amount)
FROM orders o
JOIN customers c ON o.customer_id = c.id
JOIN regions r   ON c.region_id = r.id
GROUP BY r.name;
                                            QUERY PLAN
--------------------------------------------------------------------------------------------------
 HashAggregate (actual time=408.896..408.904 rows=20.00 loops=1)
   Group Key: r.name
   Batches: 1  Memory Usage: 32kB
   Buffers: shared hit=3997, temp read=1622 written=1622
   ->  Hash Join (actual time=149.780..299.806 rows=500000.00 loops=1)
         Hash Cond: (c.id = o.customer_id)
         Buffers: shared hit=3997, temp read=1622 written=1622
         ->  Hash Join (actual time=13.880..20.077 rows=50000.00 loops=1)
               Hash Cond: (r.id = c.region_id)
               Buffers: shared hit=320
               ->  Seq Scan on regions r (actual time=0.013..0.043 rows=20.00 loops=1)
                     Buffers: shared hit=1
               ->  Hash (actual time=13.745..13.746 rows=50000.00 loops=1)
                     Buckets: 65536  Batches: 1  Memory Usage: 2466kB
                     Buffers: shared hit=319
                     ->  Seq Scan on customers c (actual time=0.013..5.339 rows=50000.00 loops=1)
                           Buffers: shared hit=319
         ->  Hash (actual time=135.026..135.026 rows=500000.00 loops=1)
               Buckets: 262144  Batches: 4  Memory Usage: 7409kB
               Buffers: shared hit=3677, temp written=1464
               ->  Seq Scan on orders o (actual time=0.015..43.829 rows=500000.00 loops=1)
                     Buffers: shared hit=3677
 Planning:
   Buffers: shared hit=10
 Planning Time: 0.632 ms
 Supplied Plan Advice:
   JOIN_ORDER(r c o) /* matched */
 Generated Plan Advice:
   JOIN_ORDER(r c o)
   HASH_JOIN(c o)
   SEQ_SCAN(r c o)
   NO_GATHER(o c r)
 Execution Time: 409.557 ms
(33 rows)

postgres=#
```


