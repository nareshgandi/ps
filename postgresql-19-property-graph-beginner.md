# PostgreSQL 19 Property Graph — Beginner-Friendly Explanation

## 1. Start with a real-world example

Imagine an e-commerce application:

- Customer **Naresh** places an order.
- That order contains a **Laptop**.
- The Laptop is supplied by **Dell**.
- Naresh also bought a **Mouse**.
- The Mouse is supplied by **Logitech**.

You can visualize this as:

```text
Naresh
  |
  | PLACED
  ↓
Order 101
  |
  | CONTAINS
  ↓
Laptop
  |
  | SUPPLIED_BY
  ↓
Dell
```

Here we have two fundamental things:

### Nodes / Vertices

Things:

```text
Customer
Order
Product
Company
```

### Edges

Relationships between things:

```text
Customer ──PLACED──> Order
Order ──CONTAINS──> Product
Product ──SUPPLIED_BY──> Company
```

That's the basic idea of a **graph**.

---

# 2. What makes it a "Property" Graph?

Now add information to those things.

For example:

```text
Customer
----------------
name = Naresh
city = Hyderabad

Product
----------------
name = Laptop
price = 75000

Order
----------------
order_id = 101
order_date = 2026-08-20
```

Relationships can have information too.

So:

**Graph = Nodes + Relationships**

**Property Graph = Nodes + Relationships + Properties**

PostgreSQL 19 introduces SQL/PGQ (SQL Property Graph Queries), which lets relational data be represented and queried using the property-graph model.

---

# 3. The important PostgreSQL part

You might imagine PostgreSQL creates a completely new physical graph storage system:

```text
      Graph Database
          |
   ┌──────┴──────┐
 Nodes          Edges
```

That's not the right mental model.

PostgreSQL continues storing the actual data in normal relational tables.

For example:

```text
customers
--------------------------------
customer_id | name
------------+--------
1           | Naresh
2           | Ravi


orders
--------------------------------
order_id | customer_id | amount
---------+-------------+--------
101      | 1           | 75000


products
--------------------------------
product_id | name
-----------+---------
10         | Laptop


order_items
--------------------------------
order_id | product_id
---------+-----------
101      | 10
```

PostgreSQL 19 can expose these existing relational tables as a **property graph**.

Conceptually:

```text
              PostgreSQL
                   |
        ┌──────────┴──────────┐
        |                     |
   Relational SQL        Property Graph
        |                     |
    tables/joins          nodes/edges
        |                     |
        └──────────┬──────────┘
                   |
              SAME DATA
```

The property graph is essentially a logical/read-only graph definition over your relational data, rather than a separate physical graph database.

**Important DBA takeaway:**

> PostgreSQL 19 does not mean "PostgreSQL has become a graph database."

A better statement is:

> **PostgreSQL 19 allows relational data to be exposed and queried as a property graph using SQL/PGQ.**

---

# 4. Let's build an example in PostgreSQL 19

Suppose we create three tables.

## Customers

```sql
CREATE TABLE customers (
    customer_id integer PRIMARY KEY,
    name text,
    city text
);
```

## Orders

```sql
CREATE TABLE orders (
    order_id integer PRIMARY KEY,
    customer_id integer REFERENCES customers(customer_id),
    order_date date
);
```

## Products

```sql
CREATE TABLE products (
    product_id integer PRIMARY KEY,
    name text,
    price numeric
);
```

And an order-items table:

```sql
CREATE TABLE order_items (
    order_item_id integer PRIMARY KEY,
    order_id integer REFERENCES orders(order_id),
    product_id integer REFERENCES products(product_id)
);
```

Populate some data:

```sql
INSERT INTO customers VALUES
(1, 'Naresh', 'Hyderabad'),
(2, 'Ravi', 'Bangalore');

INSERT INTO orders VALUES
(101, 1, '2026-08-20'),
(102, 2, '2026-08-21');

INSERT INTO products VALUES
(10, 'Laptop', 75000),
(20, 'Mouse', 1500);

INSERT INTO order_items VALUES
(1001, 101, 10),
(1002, 101, 20),
(1003, 102, 10);
```

---

# 5. First look at the data using normal SQL

Normally, you'd query this with joins:

```sql
SELECT
    c.name,
    o.order_id,
    p.name AS product
FROM customers c
JOIN orders o
    ON o.customer_id = c.customer_id
JOIN order_items oi
    ON oi.order_id = o.order_id
JOIN products p
    ON p.product_id = oi.product_id;
```

You are basically saying:

```text
Customer
   ↓
JOIN
   ↓
Order
   ↓
JOIN
   ↓
Order Item
   ↓
JOIN
   ↓
Product
```

---

# 6. Now think about the same data as a graph

The same data can be viewed as:

```text
               PLACED
       Naresh ────────> Order 101
                           |
                           | CONTAINS
                           ↓
                        Laptop
                           |
                           | SUPPLIED_BY
                           ↓
                          Dell
```

The important change is not necessarily the data.

The change is **how we describe and query the relationships**.

---

# 7. Creating a Property Graph

PostgreSQL 19 provides `CREATE PROPERTY GRAPH`.

Conceptually, you can define:

```sql
CREATE PROPERTY GRAPH ecommerce
    VERTEX TABLES (
        customers LABEL customer,
        orders LABEL "order",
        products LABEL product
    )
    EDGE TABLES (
        customer_orders
            SOURCE customers
            DESTINATION orders
            LABEL placed,

        order_items
            SOURCE orders
            DESTINATION products
            LABEL contains
    );
```

The exact source/destination key mapping needs to reflect the columns in your real tables.

For example:

```text
customer_orders

SOURCE:
customers.customer_id

DESTINATION:
orders.order_id
```

And:

```text
order_items

SOURCE:
orders.order_id

DESTINATION:
products.product_id
```

The important idea is:

```text
Relational table
      ↓
Define it as a vertex or edge
      ↓
Property graph
```

---

# 8. Nodes and edges in our example

We can now think of our relational tables as:

```text
customers
    ↓
VERTEX TABLE


orders
    ↓
VERTEX TABLE


products
    ↓
VERTEX TABLE


order_items
    ↓
EDGE TABLE
```

So:

```text
Customer
   |
 placed
   ↓
Order
   |
 contains
   ↓
Product
```

---

# 9. Querying the graph

This is where the feature becomes interesting.

Traditional SQL thinks in terms of joins:

```text
customer
   ↓
JOIN
   ↓
order
   ↓
JOIN
   ↓
order_item
   ↓
JOIN
   ↓
product
```

Graph thinking describes the relationship as a pattern:

```text
(customer)-[placed]->(order)-[contains]->(product)
```

PostgreSQL 19 provides `GRAPH_TABLE` for graph pattern matching.

Conceptually:

```sql
SELECT *
FROM GRAPH_TABLE (
    ecommerce
    MATCH
        (c IS customer)
        -[IS placed]->
        (o IS "order")
        -[IS contains]->
        (p IS product)
    COLUMNS (
        c.name AS customer_name,
        o.order_id,
        p.name AS product_name
    )
);
```

The most important part is:

```text
(c)-[placed]->(o)-[contains]->(p)
```

Read it like English:

> Find a customer who placed an order that contains a product.

---

# 10. Why graph queries can be useful

Consider a complicated relationship:

```text
Customer
   ↓
Order
   ↓
Product
   ↓
Category
   ↓
Supplier
   ↓
Country
```

In relational SQL, this can become many joins:

```sql
SELECT ...
FROM customers c
JOIN orders o ...
JOIN order_items oi ...
JOIN products p ...
JOIN categories cat ...
JOIN suppliers s ...
JOIN countries co ...
WHERE ...;
```

Graph thinking becomes:

```text
(Customer)
    |
  placed
    ↓
 (Order)
    |
 contains
    ↓
(Product)
    |
 belongs_to
    ↓
(Category)
    |
 supplied_by
    ↓
(Supplier)
    |
 located_in
    ↓
(Country)
```

Graph pattern matching lets you describe the relationship path directly.

---

# 11. Another simple example: LinkedIn

Imagine:

```text
Naresh ──WORKS_AT──> Company A
  |
  | KNOWS
  ↓
Ravi ──WORKS_AT──> Company B
  |
  | KNOWS
  ↓
Anil
```

Now ask:

> Find people who are connected to Naresh through two levels.

In relational SQL, this often involves self-joins.

Graph thinking becomes:

```text
(Naresh)
   |
  knows
   ↓
(Person)
   |
  knows
   ↓
(Person)
```

This is where graph pattern matching becomes very natural.

---

# 12. Property Graph vs Relational Database

| Relational | Property Graph |
|---|---|
| Table | Vertex/Edge table exposed as graph |
| Row | Vertex/Edge |
| Column | Property |
| PK/FK | Relationship between vertices/edges |
| JOIN | Graph traversal/pattern |
| WHERE | Filtering graph elements |
| SQL | SQL + graph pattern syntax |

But PostgreSQL 19 is **not replacing relational SQL with graphs**.

Instead:

```text
             PostgreSQL 19
                   |
       ┌───────────┴───────────┐
       ↓                       ↓
 Relational SQL           SQL/PGQ
       ↓                       ↓
 Tables + JOINs          Graph patterns
       └───────────┬───────────┘
                   ↓
              Same database
              Same data
```

Relational SQL and graph queries can work over the same underlying PostgreSQL data.

---

# 13. The most important misconception to avoid

Do not say:

> "PostgreSQL 19 has become a graph database."

Say:

> **"PostgreSQL 19 supports SQL/PGQ, allowing relational data to be represented and queried as a property graph."**

That is the better mental model.

The graph definition does not require creating a separate physical graph database. It describes how existing relational tables should be interpreted as vertices and edges.

---

# 14. Why this is interesting for a PostgreSQL DBA

This feature is particularly interesting because you don't necessarily need to introduce a separate graph database just to answer relationship-oriented questions.

You could have:

```text
                PostgreSQL 19
                     |
       ┌─────────────┼─────────────┐
       ↓             ↓             ↓
   OLTP tables   SQL queries   Graph queries
       |                           |
       └────────── same data ──────┘
```

For example:

### Normal DBA query

```sql
SELECT *
FROM orders
WHERE customer_id = 100;
```

### Analytical SQL

```sql
SELECT customer_id, count(*)
FROM orders
GROUP BY customer_id;
```

### Relationship-oriented query

```text
(Customer)-[placed]->(Order)-[contains]->(Product)
```

All can operate against the same PostgreSQL database.

---

# 15. The one mental model to remember

If you are a fresher, remember this:

```text
TABLES
  ↓
Rows become things
Columns become properties
Foreign-key relationships become connections
  ↓
PROPERTY GRAPH
  ↓
Query relationships as patterns
```

Or even simpler:

> **Relational thinking asks: "Which tables do I JOIN?"**

> **Graph thinking asks: "How are these things connected?"**

PostgreSQL 19 lets you use both ways of thinking over the same underlying relational data through SQL/PGQ.

---

# 16. Quick terminology cheat sheet

| Term | Simple meaning |
|---|---|
| Graph | Things + relationships |
| Vertex | A node/thing |
| Edge | A relationship between things |
| Property | Attribute/value attached to a vertex or edge |
| Property Graph | Vertices + edges + properties |
| Vertex table | Relational table used to represent graph nodes |
| Edge table | Relational table used to represent graph relationships |
| SQL/PGQ | SQL standard functionality for property graph queries |
| `CREATE PROPERTY GRAPH` | Defines a property graph over relational tables |
| `GRAPH_TABLE` | Queries graph patterns |
| Graph pattern | Describes how nodes and relationships should connect |

---

# 17. Final mental picture

```text
                    POSTGRESQL 19
                         |
              ┌──────────┴──────────┐
              |                     |
         RELATIONAL VIEW       GRAPH VIEW
              |                     |
        ┌─────┴─────┐         ┌─────┴─────┐
        |           |         |           |
      Tables       JOINs    Vertices     Edges
        |                       |           |
        └─────────── SAME UNDERLYING DATA ─┘
```

The key idea:

> **Property graphs do not necessarily mean a different database. They are a different way of representing and querying relationships in your existing data.**

For a PostgreSQL DBA, this makes SQL/PGQ especially interesting because you can combine traditional relational SQL with graph pattern queries without moving the data into a separate graph database.
