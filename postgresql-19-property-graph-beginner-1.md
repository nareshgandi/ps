# PostgreSQL 19 Property Graph — Beginner-Friendly Guide

## 1. What is a Property Graph?

Let's start with a simple real-world example.

Imagine an e-commerce application:

- Customer **Naresh** places an order.
- The order contains a **Laptop**.
- The order also contains a **Mouse**.
- The Laptop is supplied by **Dell**.

We can represent this as:

```text
Naresh
  |
  | PLACED
  ↓
Order 101
  |
  | CONTAINS
  ├──────────→ Laptop
  |
  └──────────→ Mouse
```

This is a **graph**.

A graph has two fundamental concepts:

### Vertex / Node

A vertex represents a thing or entity.

Examples:

```text
Customer
Order
Product
Company
```

### Edge

An edge represents a relationship between two things.

Examples:

```text
Customer ──PLACED──> Order
Order ──CONTAINS──> Product
Product ──SUPPLIED_BY──> Company
```

So:

> **Graph = Vertices + Relationships**

---

# 2. What makes it a Property Graph?

Now attach information to the vertices and relationships.

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

These are **properties**.

A relationship can also have properties:

```text
Naresh ── PLACED ──> Order 101

Relationship properties:
    placed_at = 2026-08-20
    channel = WEB
```

Therefore:

> **Property Graph = Vertices + Edges + Properties**

---

# 3. PostgreSQL 19 and Property Graphs

This is the most important part.

You might initially think PostgreSQL 19 creates a completely separate graph database:

```text
        Graph Database
             |
      ┌──────┴──────┐
      ↓             ↓
   Vertices        Edges
```

That's not the best way to think about PostgreSQL's implementation.

PostgreSQL continues storing the underlying data in normal relational tables.

The graph is a **logical representation of that relational data**.

Conceptually:

```text
                 PostgreSQL 19
                      |
          ┌───────────┴───────────┐
          ↓                       ↓
   Relational SQL             SQL/PGQ
          ↓                       ↓
   Tables + JOINs          Graph patterns
          |                       |
          └───────────┬───────────┘
                      ↓
                 SAME DATA
```

This means you can use:

- Normal SQL
- JOINs
- Aggregations
- Indexes
- Constraints
- Transactions
- Graph pattern matching

over the same PostgreSQL database.

### Important statement

Don't say:

> "PostgreSQL 19 has become a graph database."

A better statement is:

> **PostgreSQL 19 supports SQL/PGQ, allowing relational data to be represented and queried as a property graph.**

---

# 4. Let's build a simple e-commerce schema

For learning purposes, we will deliberately create **explicit edge tables**.

This makes the property-graph concept easier to understand.

Our model will be:

```text
customers
     |
     | customer_orders
     ↓
orders
     |
     | order_items
     ↓
products
```

And the graph will look like:

```text
(Customer)
     |
   PLACED
     ↓
 (Order)
     |
  CONTAINS
     ↓
 (Product)
```

---

# 5. Create the Vertex Tables

## Customer table

```sql
CREATE TABLE customers (
    customer_id integer PRIMARY KEY,
    name text,
    city text
);
```

Example data:

```sql
INSERT INTO customers VALUES
(1, 'Naresh', 'Hyderabad'),
(2, 'Ravi', 'Bangalore');
```

---

## Order table

```sql
CREATE TABLE orders (
    order_id integer PRIMARY KEY,
    order_date date,
    amount numeric
);
```

Example data:

```sql
INSERT INTO orders VALUES
(101, '2026-08-20', 76500),
(102, '2026-08-21', 75000);
```

---

## Product table

```sql
CREATE TABLE products (
    product_id integer PRIMARY KEY,
    name text,
    price numeric
);
```

Example data:

```sql
INSERT INTO products VALUES
(10, 'Laptop', 75000),
(20, 'Mouse', 1500);
```

These three tables represent **vertices** in our graph.

```text
customers  → Vertex
orders     → Vertex
products   → Vertex
```

---

# 6. Create the Edge Tables

Now we explicitly model the relationships.

## Customer → Order

Create a `customer_orders` table:

```sql
CREATE TABLE customer_orders (
    customer_id integer REFERENCES customers(customer_id),
    order_id integer REFERENCES orders(order_id),
    placed_at timestamp,
    channel text,
    PRIMARY KEY (customer_id, order_id)
);
```

Insert data:

```sql
INSERT INTO customer_orders VALUES
(1, 101, '2026-08-20 10:30:00', 'WEB'),
(2, 102, '2026-08-21 14:20:00', 'MOBILE');
```

Now we have:

```text
Naresh
   |
   | PLACED
   | channel = WEB
   | placed_at = 2026-08-20 10:30
   ↓
Order 101
```

Notice something important:

The **relationship itself has properties**.

```text
channel
placed_at
```

This is one of the reasons property graphs are powerful.

---

# 7. Create the Order → Product Edge

Now create:

```sql
CREATE TABLE order_items (
    order_id integer REFERENCES orders(order_id),
    product_id integer REFERENCES products(product_id),
    quantity integer,
    PRIMARY KEY (order_id, product_id)
);
```

Insert data:

```sql
INSERT INTO order_items VALUES
(101, 10, 1),
(101, 20, 1),
(102, 10, 1);
```

Now the graph becomes:

```text
Naresh
   |
   | PLACED
   ↓
Order 101
   |
   | CONTAINS
   ├──────────────→ Laptop
   |                quantity = 1
   |
   └──────────────→ Mouse
                    quantity = 1
```

---

# 8. Why create `customer_orders`?

A natural question is:

> "Why didn't we simply put `customer_id` inside the `orders` table?"

That is absolutely valid relational modeling.

For example:

```text
orders
-----------------------------
order_id
customer_id
order_date
amount
```

would be perfectly reasonable if every order belongs to exactly one customer.

However, for teaching **property graphs**, an explicit relationship table makes the concept much clearer:

```text
customers
    |
    | customer_orders
    ↓
orders
```

Now we can clearly distinguish:

```text
VERTEX TABLES
----------------
customers
orders
products


EDGE TABLES
----------------
customer_orders
order_items
```

The mental model becomes:

> **Vertex table = What is the thing?**

> **Edge table = How are two things connected?**

This is especially useful when the relationship itself has properties.

For example:

```text
customer_orders
-----------------------------------
customer_id
order_id
placed_at
channel
```

The edge can carry:

```text
placed_at
channel
```

---

# 9. Relational Model vs Graph Model

The relational model looks like:

```text
customers
    |
    | FK
    ↓
customer_orders
    |
    | FK
    ↓
orders
    |
    | FK
    ↓
order_items
    |
    | FK
    ↓
products
```

The graph model looks like:

```text
(Customer)
     |
   PLACED
     ↓
 (Order)
     |
  CONTAINS
     ↓
(Product)
```

Same underlying information.

Different way of thinking.

---

# 10. Querying the data using normal SQL

Before using graph queries, let's query the same data using traditional SQL.

```sql
SELECT
    c.name AS customer_name,
    o.order_id,
    p.name AS product_name,
    oi.quantity
FROM customers c
JOIN customer_orders co
    ON co.customer_id = c.customer_id
JOIN orders o
    ON o.order_id = co.order_id
JOIN order_items oi
    ON oi.order_id = o.order_id
JOIN products p
    ON p.product_id = oi.product_id;
```

The database has to follow this relationship:

```text
customers
    ↓
JOIN customer_orders
    ↓
JOIN orders
    ↓
JOIN order_items
    ↓
JOIN products
```

---

# 11. Now think like a graph

Instead of thinking:

> Which tables do I join?

Think:

> How are these things connected?

The relationship pattern becomes:

```text
(Customer)
    |
  PLACED
    ↓
(Order)
    |
 CONTAINS
    ↓
(Product)
```

Or more compactly:

```text
(customer)-[placed]->(order)-[contains]->(product)
```

This is the core idea behind graph pattern matching.

---

# 12. PostgreSQL 19 SQL/PGQ

PostgreSQL 19 introduces support for SQL/PGQ (SQL Property Graph Queries).

Two important concepts to learn are:

```text
CREATE PROPERTY GRAPH
```

and:

```text
GRAPH_TABLE
```

### `CREATE PROPERTY GRAPH`

This defines how your relational tables should be interpreted as a property graph.

Conceptually:

```text
Relational tables
       ↓
Property graph definition
       ↓
Vertices + Edges + Properties
```

### `GRAPH_TABLE`

This allows you to query graph patterns.

Conceptually:

```text
(Customer)-[PLACED]->(Order)-[CONTAINS]->(Product)
```

---

# 13. Property Graph Definition

Our intended mapping is:

```text
Vertex tables:

customers
orders
products


Edge tables:

customer_orders
order_items
```

And their relationships are:

```text
customer_orders

SOURCE:
customers.customer_id

DESTINATION:
orders.order_id
```

and:

```text
order_items

SOURCE:
orders.order_id

DESTINATION:
products.product_id
```

The resulting graph is:

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

# 14. Why this is different from simply using foreign keys

The foreign keys are still there.

For example:

```sql
customer_orders.customer_id
    REFERENCES customers.customer_id
```

and:

```sql
customer_orders.order_id
    REFERENCES orders.order_id
```

Those are normal relational database constraints.

The property graph definition adds another logical interpretation:

```text
customer_orders
        ↓
    graph edge
        ↓
Customer ──PLACED──> Order
```

So:

```text
Foreign Key
     ↓
Relational relationship

Property Graph
     ↓
Graph relationship
```

The same underlying relationship can therefore be understood in two ways.

---

# 15. Graph Query Pattern

Suppose we want:

> Find every customer, their orders, and the products in those orders.

The graph pattern is:

```text
(Customer)
    |
  PLACED
    ↓
(Order)
    |
 CONTAINS
    ↓
(Product)
```

In PostgreSQL's SQL/PGQ syntax, `GRAPH_TABLE` is used to express this pattern.

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

The important thing for a beginner is not memorizing the syntax.

Understand this first:

```text
(c)-[placed]->(o)-[contains]->(p)
```

Read it as:

> Find a customer who placed an order that contains a product.

---

# 16. Why graph queries become useful

Imagine the application becomes more complicated:

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

Traditional SQL might require many joins:

```text
customers
    ↓
orders
    ↓
order_items
    ↓
products
    ↓
categories
    ↓
suppliers
    ↓
countries
```

Graph thinking focuses on the path:

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

This becomes especially useful when the question is about **relationships and paths** rather than simply retrieving rows.

---

# 17. Another Example — Social Network

Consider LinkedIn-style data:

```text
Naresh
   |
  KNOWS
   ↓
Ravi
   |
  KNOWS
   ↓
Anil
```

Suppose the question is:

> Who is connected to Naresh through two levels?

Graph thinking:

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

Traditional relational SQL can also answer this using self-joins.

But the graph pattern describes the relationship more naturally.

---

# 18. Property Graph vs Relational Database

| Relational | Property Graph |
|---|---|
| Table | Vertex/Edge table represented in a graph |
| Row | Vertex or edge record |
| Column | Property |
| Primary/Foreign Key | Relationship/key used to connect graph elements |
| JOIN | Graph pattern/traversal |
| WHERE | Filtering graph elements |
| SQL | SQL + graph pattern syntax |
| Tables | Vertices + edges |

Remember:

> Property graphs don't replace relational databases.

They provide another way to work with relational data.

---

# 19. The most important misconception

Do **not** think:

> "PostgreSQL 19 is now a graph database."

Instead think:

> **"PostgreSQL 19 supports SQL/PGQ, which lets me define and query a property graph over relational data."**

That distinction is important.

You still have:

```text
PostgreSQL
    |
    ├── Tables
    ├── Indexes
    ├── Constraints
    ├── Transactions
    ├── SQL
    └── SQL/PGQ
```

---

# 20. Why this matters to a PostgreSQL DBA

This feature is interesting because you don't necessarily need another database just to perform relationship-oriented queries.

You could have:

```text
                  PostgreSQL 19
                       |
        ┌──────────────┼──────────────┐
        ↓              ↓              ↓
    OLTP SQL       Analytics       Graph
        ↓              ↓              ↓
     Tables        Aggregates    Relationships
        └──────────────┬──────────────┘
                       ↓
                  SAME DATABASE
                  SAME DATA
```

For example:

### Normal OLTP query

```sql
SELECT *
FROM orders
WHERE order_id = 101;
```

### Analytical query

```sql
SELECT customer_id, count(*)
FROM customer_orders
GROUP BY customer_id;
```

### Relationship-oriented query

```text
(Customer)-[PLACED]->(Order)-[CONTAINS]->(Product)
```

All of these can work with the same PostgreSQL database.

---

# 21. The key mental model for a fresher

Remember this:

```text
                 RELATIONAL TABLES
                         |
             ┌───────────┴───────────┐
             ↓                       ↓
       What is the thing?      How are things connected?
             ↓                       ↓
        VERTEX TABLES            EDGE TABLES
             ↓                       ↓
       customers                 customer_orders
       orders                    order_items
       products
             \                       /
              \                     /
               └──── PROPERTY ─────┘
                      GRAPH
```

Or even simpler:

> **Relational thinking asks: "Which tables do I JOIN?"**

> **Graph thinking asks: "How are these things connected?"**

---

# 22. Quick Terminology Cheat Sheet

| Term | Simple meaning |
|---|---|
| Graph | Things + relationships |
| Vertex | A node/thing |
| Edge | A relationship between things |
| Property | Attribute/value attached to a vertex or edge |
| Property Graph | Vertices + edges + properties |
| Vertex table | Relational table used to represent graph nodes |
| Edge table | Relational table used to represent graph relationships |
| SQL/PGQ | SQL functionality for property graph queries |
| `CREATE PROPERTY GRAPH` | Defines a property graph over relational tables |
| `GRAPH_TABLE` | Queries graph patterns |
| Graph pattern | Describes how vertices and edges connect |

---

# 23. Complete Example — One Picture

Our relational database:

```text
┌─────────────────┐
│    customers    │
├─────────────────┤
│ customer_id     │
│ name            │
│ city            │
└────────┬────────┘
         │
         │ customer_orders
         ↓
┌─────────────────┐
│     orders      │
├─────────────────┤
│ order_id        │
│ order_date      │
│ amount          │
└────────┬────────┘
         │
         │ order_items
         ↓
┌─────────────────┐
│    products     │
├─────────────────┤
│ product_id      │
│ name            │
│ price           │
└─────────────────┘
```

The graph view:

```text
┌───────────┐
│  Naresh   │
│ Customer  │
└─────┬─────┘
      │
      │ PLACED
      │
      ▼
┌───────────┐
│ Order 101 │
└─────┬─────┘
      │
      │ CONTAINS
      │
      ├───────────────┐
      ▼               ▼
┌───────────┐   ┌───────────┐
│  Laptop   │   │   Mouse   │
│  Product  │   │  Product  │
└───────────┘   └───────────┘
```

The important point:

```text
                SAME DATA
                   |
       ┌───────────┴───────────┐
       ↓                       ↓
 Relational model        Property graph
       ↓                       ↓
 Tables + FKs           Vertices + Edges
       ↓                       ↓
       └──────── PostgreSQL ───┘
```

---

# 24. Final Takeaway

If you remember only five things, remember these:

1. **A graph represents things and their relationships.**
2. **A property graph adds properties to things and relationships.**
3. **PostgreSQL 19 can define a property graph over relational tables.**
4. **Vertex tables represent things; edge tables represent relationships.**
5. **Graph queries let you express relationship patterns such as:**

```text
(Customer)-[PLACED]->(Order)-[CONTAINS]->(Product)
```

The big idea is:

> **Relational thinking = data is organized into tables.**

> **Graph thinking = data is connected through relationships.**

> **PostgreSQL 19 lets you use both perspectives over the same underlying data.**
