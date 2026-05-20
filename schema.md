# Database Schema: shoe_store_db

## Tables

### brands
- `id` (integer): Primary Key
- `created_at` (timestamp with time zone)
- `name` (character varying): Unique brand name (e.g., Nike, Adidas)

### categories
- `id` (integer): Primary Key
- `created_at` (timestamp with time zone)
- `name` (character varying): Category name (e.g., Running, Basketball)

### products
- `id` (integer): Primary Key
- `brand_id` (integer): Foreign Key to `brands.id`
- `category_id` (integer): Foreign Key to `categories.id`
- `gender` (genderenum): 'men', 'women', 'unisex'
- `price` (numeric): Product price
- `is_deleted` (boolean): Soft delete flag
- `name` (character varying): Product name
- `description` (text): Detailed description
- `created_at` (timestamp with time zone)
- `updated_at` (timestamp with time zone)

### product_images
- `id` (integer): Primary Key
- `product_id` (integer): Foreign Key to `products.id`
- `is_primary` (boolean): Whether this is the main image
- `image_path` (character varying): Path to image file

### product_variants
- `id` (integer): Primary Key
- `product_id` (integer): Foreign Key to `products.id`
- `stock` (integer): Number of items in stock
- `size` (character varying): Size (e.g., 9, 10, L, XL)
- `color` (character varying): Color (e.g., Blue, Black)
- `sku` (character varying): Unique Stock Keeping Unit

## Relations
- `products.brand_id` -> `brands.id`
- `products.category_id` -> `categories.id`
- `product_images.product_id` -> `products.id`
- `product_variants.product_id` -> `products.id`
