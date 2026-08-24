# PostgreSQL 19 — Logical Replication of Sequences

## Problem → Simulation → PostgreSQL 19 Solution

### Small definition

In PostgreSQL, a table can use a sequence to generate primary-key values:

```text
orders table
     |
     +-- order_id
           |
           +-- orders_order_id_seq
```

Before PostgreSQL 19, **logical replication replicated table rows, but sequence state was not automatically synchronized**.

That could create a problem:

```text
Publisher                         Subscriber

orders                            orders
1 Alice                           1 Alice
2 Bob                             2 Bob
3 Carol                           3 Carol
     |                                  |
     v                                  v
sequence = 3                     sequence may be behind
```

The table data can look synchronized while the sequence on the subscriber is at a different value.

PostgreSQL 19 adds logical replication support for sequence values.

---

# 1. Create the Table and Sequence

We will use an `orders` table whose `order_id` is generated from a sequence.

## On the Publisher

Create the table:

```sql
CREATE TABLE orders (
    order_id bigint PRIMARY KEY,
    customer_name text,
    amount numeric(10,2)
);
```

Create the sequence:

```sql
CREATE SEQUENCE orders_order_id_seq
START WITH 1
INCREMENT BY 1;
```

Make the sequence the default for `order_id`:

```sql
ALTER TABLE orders
ALTER COLUMN order_id
SET DEFAULT nextval('orders_order_id_seq');
```

Insert some orders:

```sql
INSERT INTO orders (customer_name, amount)
VALUES
('Alice', 500),
('Bob', 750),
('Carol', 1200);
```

Check the table:

```sql
SELECT *
FROM orders
ORDER BY order_id;
```

Expected:

```text
 order_id | customer_name | amount
----------+---------------+--------
        1 | Alice         | 500.00
        2 | Bob           | 750.00
        3 | Carol         | 1200.00
```

Check the sequence:

```sql
SELECT last_value, is_called
FROM orders_order_id_seq;
```

Expected:

```text
 last_value | is_called
------------+-----------
          3 | t
```

Our publisher now looks like:

```text
PUBLISHER

orders
+----+---------------+--------+
| id | customer      | amount |
+----+---------------+--------+
|  1 | Alice         | 500    |
|  2 | Bob           | 750    |
|  3 | Carol         | 1200   |
+----+---------------+--------+

orders_order_id_seq
        |
        v
   last_value = 3
```

---

# 2. Replicate the Table

Create a publication on the publisher:

```sql
CREATE PUBLICATION orders_pub
FOR TABLE orders;
```

On the subscriber, create the same table:

```sql
CREATE TABLE orders (
    order_id bigint PRIMARY KEY,
    customer_name text,
    amount numeric(10,2)
);
```

Create the sequence:

```sql
CREATE SEQUENCE orders_order_id_seq
START WITH 1
INCREMENT BY 1;
```

Attach it to the column:

```sql
ALTER TABLE orders
ALTER COLUMN order_id
SET DEFAULT nextval('orders_order_id_seq');
```

Create the subscription:

```sql
CREATE SUBSCRIPTION orders_sub
CONNECTION 'host=PUBLISHER_HOST dbname=postgres user=repuser password=PASSWORD'
PUBLICATION orders_pub;
```

The table rows are now replicated.

On the subscriber:

```sql
SELECT *
FROM orders
ORDER BY order_id;
```

You should see:

```text
 order_id | customer_name | amount
----------+---------------+--------
        1 | Alice         | 500.00
        2 | Bob           | 750.00
        3 | Carol         | 1200.00
```

But the important point is:

> **Table-row replication does not by itself mean that the subscriber's sequence state is synchronized.**

---

# 3. Demonstrate the Old Problem

Insert another order on the publisher:

```sql
INSERT INTO orders (customer_name, amount)
VALUES ('David', 900);
```

The publisher generates:

```text
order_id = 4
```

The row is replicated:

```text
PUBLISHER                         SUBSCRIBER

orders                            orders
1 Alice                           1 Alice
2 Bob                             2 Bob
3 Carol                           3 Carol
4 David  --------------------->  4 David
```

The table looks correct on both sides.

Now imagine that the subscriber becomes the database where new writes are generated.

Check the subscriber sequence:

```sql
SELECT last_value, is_called
FROM orders_order_id_seq;
```

The sequence state may not reflect the highest ID currently present in the table.

For example:

```text
SUBSCRIBER

orders table
highest order_id = 4

orders_order_id_seq
last_value = 3
```

Now insert a new order on the subscriber:

```sql
INSERT INTO orders (customer_name, amount)
VALUES ('Emma', 1000);
```

If the subscriber sequence generates `4`, PostgreSQL will attempt to insert an ID that already exists.

The result can be:

```text
ERROR: duplicate key value violates unique constraint
```

Conceptually:

```text
              orders table
                   |
                   v
            highest ID = 4
                   ^
                   |
          sequence generates 4
                   |
                   X
             duplicate key
```

## The actual problem

Before PostgreSQL 19, a logical replication design could therefore have:

```text
Table data       → synchronized
Sequence state   → not automatically synchronized
```

This was particularly important during:

- logical replication migrations
- database cutovers
- upgrades
- publisher/subscriber failover designs

---

# 4. PostgreSQL 19 — Replicate the Sequence Too

PostgreSQL 19 adds logical replication support for sequence values.

Instead of publishing only the table:

```sql
CREATE PUBLICATION orders_pub
FOR TABLE orders;
```

we can publish the sequence too:

```sql
CREATE PUBLICATION orders_pub
FOR TABLE orders, SEQUENCE orders_order_id_seq;
```

Or publish all sequences:

```sql
CREATE PUBLICATION orders_pub
FOR ALL SEQUENCES;
```

Now logical replication knows that the sequence is part of the replication configuration.

---

# 5. Create the Subscription

On the subscriber:

```sql
CREATE SUBSCRIPTION orders_sub
CONNECTION 'host=PUBLISHER_HOST dbname=postgres user=repuser password=PASSWORD'
PUBLICATION orders_pub;
```

During subscription initialization, PostgreSQL can synchronize the initial sequence state.

Check the subscriber:

```sql
SELECT last_value, is_called
FROM orders_order_id_seq;
```

The sequence can now be synchronized with the publisher.

---

# 6. Move the Sequence Forward

Let's generate more orders on the publisher:

```sql
INSERT INTO orders (customer_name, amount)
VALUES ('Frank', 1500);

INSERT INTO orders (customer_name, amount)
VALUES ('Grace', 1800);

INSERT INTO orders (customer_name, amount)
VALUES ('Helen', 2200);
```

The publisher now has:

```text
orders

1 Alice
2 Bob
3 Carol
4 David
5 Frank
6 Grace
7 Helen
```

And the sequence has advanced accordingly:

```sql
SELECT last_value, is_called
FROM orders_order_id_seq;
```

Conceptually:

```text
Publisher sequence
        |
        v
last_value = 7
```

PostgreSQL 19 can synchronize the sequence state to the subscriber.

---

# 7. Refresh Sequence Synchronization

If required, the subscriber can refresh sequence synchronization:

```sql
ALTER SUBSCRIPTION orders_sub
REFRESH SEQUENCES;
```

Then check:

```sql
SELECT last_value, is_called
FROM orders_order_id_seq;
```

The subscriber can now be brought back into synchronization with the publisher's sequence state.

---

# 8. Before PostgreSQL 19 vs PostgreSQL 19

## Before PostgreSQL 19

```text
             LOGICAL REPLICATION
                    |
          +---------+---------+
          |                   |
          v                   v
      TABLE ROWS          SEQUENCE
          |                   |
          v                   X
     replicated          not automatically
                         synchronized
```

Example:

```text
Publisher                         Subscriber

orders                            orders
1 Alice                           1 Alice
2 Bob                             2 Bob
3 Carol                           3 Carol
4 David                           4 David

sequence = 4                     sequence = 3
                                      |
                                      v
                              Potential duplicate ID
```

---

## PostgreSQL 19

```text
             LOGICAL REPLICATION
                    |
          +---------+---------+
          |                   |
          v                   v
      TABLE ROWS          SEQUENCE STATE
          |                   |
          +---------+---------+
                    |
                    v
               SUBSCRIBER
                 stays
              synchronized
```

The important change is:

```text
Before PostgreSQL 19

Table rows       → replicated
Sequence state   → manual synchronization


PostgreSQL 19

Table rows       → replicated
Sequence state   → sequence synchronization supported
```

---

# 9. Why This Matters During a Migration

Consider an online migration:

```text
OLD DATABASE
     |
     | logical replication
     v
NEW DATABASE
```

The application continues writing to the old database while the new database catches up.

Before PostgreSQL 19:

```text
OLD DATABASE                     NEW DATABASE

orders rows  ----------------->  orders rows
sequence     ----------------->  ?
                                      |
                                      v
                              Manual sequence
                              synchronization
```

PostgreSQL 19 improves this:

```text
OLD DATABASE                     NEW DATABASE

orders rows  ----------------->  orders rows
sequence     ----------------->  sequence state
```

This reduces an important piece of manual work during logical replication migrations and cutovers.

---

# 10. One Important Detail — Sequence Caching

Do **not** describe the feature as:

> "Every `nextval()` is replicated immediately."

That is not accurate.

PostgreSQL sequences can cache values. Therefore, sequence WAL state does not necessarily advance on every individual `nextval()`.

For example:

```text
Sequence cache

1  2  3  4  5  6  7  8 ...
|----------------|
      cached
```

The important PostgreSQL 19 improvement is:

> **PostgreSQL 19 adds logical replication support for synchronizing sequence values between publisher and subscriber.**

It does not mean every individual sequence call becomes an independently replicated event.

---

# 11. Simple Mental Model

Remember the difference this way:

```text
                BEFORE PostgreSQL 19

       LOGICAL REPLICATION
              |
       +------+------+
       |             |
       v             v
     TABLE        SEQUENCE
       |             |
       v             X
   replicated     manual
                  handling


                PostgreSQL 19

       LOGICAL REPLICATION
              |
       +------+------+
       |             |
       v             v
     TABLE        SEQUENCE
       |             |
       +------+------+
              |
              v
        synchronized
```

## One-line definition

> **PostgreSQL 19 extends logical replication to include sequence state, solving an important synchronization gap between replicated tables and the sequences that generate their IDs.**

---

# Production Use Cases

This feature is particularly useful for:

1. **Logical replication migrations**

   ```text
   PostgreSQL A → PostgreSQL B
   ```

2. **Major-version upgrades**

   ```text
   PostgreSQL 18 → PostgreSQL 19
   ```

3. **Database cutovers**

   ```text
   Old primary → New primary
   ```

4. **Disaster-recovery/failover designs**

   ```text
   Primary → Subscriber
                |
                v
             Failover
   ```

5. **Applications using sequence-generated primary keys**

   ```text
   orders.order_id
          |
          v
   orders_order_id_seq
   ```

---

# Final Takeaway

The easiest way to remember the PostgreSQL 19 improvement is:

> **Logical replication used to replicate the rows, but the sequence that generates the IDs was a separate problem. PostgreSQL 19 brings sequence synchronization into logical replication.**

That makes logical replication more complete for real-world applications that use sequences for primary-key generation.
