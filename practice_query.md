Here are some complex natural language queries you can use to test your **SQL Intelligence Agent**. These queries will challenge the **Planner** to find multiple tables and the **SQL Generator** to handle joins, aggregations, and subqueries.

### 1. Multi-Table Joins & Filtering
> *"Show me all 'men' products from 'Nike' that are in the 'Running' category, including their price and primary image path."*
*   **Goal**: Joins `products`, `brands`, `categories`, and `product_images`.

### 2. Aggregations & Grouping
> *"What is the total stock count for each brand? Show the brand name and the total stock across all their product variants."*
*   **Goal**: Joins `brands`, `products`, and `product_variants` with a `SUM()` and `GROUP BY`.

### 3. Ranking & Subqueries
> *"Find the top 3 most expensive shoes in the 'Basketball' category, including their brand name and the total number of color variants available for each."*
*   **Goal**: Sorting, limits, and grouping across multiple tables.

### 4. Availability & Stock Checks
> *"List all 'unisex' shoes that have 'Blue' color variants with more than 50 items in stock."*
*   **Goal**: Deep filtering in the `product_variants` table linked back to `products`.

### 5. Complex Statistics
> *"Which category has the highest average price for 'women' shoes, and what is that average price?"*
*   **Goal**: `AVG()` aggregation with `ORDER BY` and `LIMIT 1`.

### 6. Search & Pattern Matching
> *"Find all products that have 'Pro' or 'Ultra' in their name, and show me the distinct colors they are available in."*
*   **Goal**: `LIKE` or `ILIKE` pattern matching with `DISTINCT` across joins.

### How to test:
Copy and paste these into your web interface at [http://localhost:8000](http://localhost:8000). You can check the **Generated SQL** section in the UI to see how `qwen2.5-coder:7b` handles these complex requirements!