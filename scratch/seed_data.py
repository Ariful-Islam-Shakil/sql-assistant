import os
import random
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

def seed_data():
    with engine.begin() as conn:
        # 1. Insert Brands
        brands = ["Nike", "Adidas", "Puma", "Reebok", "Vans", "Converse", "Under Armour", "New Balance"]
        brand_ids = []
        for brand in brands:
            # Check if exists
            result = conn.execute(text("SELECT id FROM brands WHERE name = :name"), {"name": brand}).fetchone()
            if result:
                brand_ids.append(result[0])
            else:
                result = conn.execute(text("INSERT INTO brands (name, created_at) VALUES (:name, NOW()) RETURNING id"), {"name": brand})
                brand_ids.append(result.fetchone()[0])
        print(f"Handled {len(brands)} brands.")

        # 2. Insert Categories
        categories = ["Running", "Basketball", "Casual", "Skateboarding", "Training", "Lifestyle", "Outdoor"]
        category_ids = []
        for cat in categories:
            result = conn.execute(text("SELECT id FROM categories WHERE name = :name"), {"name": cat}).fetchone()
            if result:
                category_ids.append(result[0])
            else:
                result = conn.execute(text("INSERT INTO categories (name, created_at) VALUES (:name, NOW()) RETURNING id"), {"name": cat})
                category_ids.append(result.fetchone()[0])
        print(f"Handled {len(categories)} categories.")

        # 3. Insert Products
        genders = ["men", "women", "unisex"]
        product_ids = []
        for i in range(25):
            brand_id = random.choice(brand_ids)
            category_id = random.choice(category_ids)
            gender = random.choice(genders)
            brand_name = brands[brand_ids.index(brand_id)] if brand_id in brand_ids else "Generic"
            
            # Find brand name for id
            brand_name = conn.execute(text("SELECT name FROM brands WHERE id = :id"), {"id": brand_id}).fetchone()[0]
            cat_name = conn.execute(text("SELECT name FROM categories WHERE id = :id"), {"id": category_id}).fetchone()[0]
            
            name = f"{brand_name} {cat_name} {random.choice(['Pro', 'Max', 'Ultra', 'Elite'])} {random.randint(1, 99)}"
            price = round(random.uniform(50, 250), 2)
            description = f"Experience premium comfort with the new {name}. Perfect for {cat_name} activities."
            
            result = conn.execute(text("""
                INSERT INTO products (brand_id, category_id, gender, price, is_deleted, name, description, created_at, updated_at)
                VALUES (:b_id, :c_id, :gender, :price, false, :name, :desc, NOW(), NOW())
                RETURNING id
            """), {
                "b_id": brand_id,
                "c_id": category_id,
                "gender": gender,
                "price": price,
                "name": name,
                "desc": description
            })
            product_id = result.fetchone()[0]
            product_ids.append(product_id)

        print(f"Inserted 25 new products.")

        # 4. Insert Product Images
        for p_id in product_ids:
            conn.execute(text("""
                INSERT INTO product_images (product_id, is_primary, image_path)
                VALUES (:p_id, true, :path)
            """), {"p_id": p_id, "path": f"images/product_{p_id}_primary.jpg"})
        print(f"Inserted images for all products.")

        # 5. Insert Product Variants
        colors = ["Black", "White", "Red", "Blue", "Grey", "Green", "Navy"]
        sizes = ["7", "8", "9", "10", "11", "12", "S", "M", "L", "XL"]
        for p_id in product_ids:
            # Add 2-3 variants per product
            for v_idx in range(random.randint(2, 4)):
                color = random.choice(colors)
                size = random.choice(sizes)
                stock = random.randint(5, 100)
                sku = f"SKU-{p_id}-{color[:2].upper()}-{size}-{v_idx}-{random.randint(1000, 9999)}"
                
                conn.execute(text("""
                    INSERT INTO product_variants (product_id, stock, size, color, sku)
                    VALUES (:p_id, :stock, :size, :color, :sku)
                """), {
                    "p_id": p_id,
                    "stock": stock,
                    "size": size,
                    "color": color,
                    "sku": sku
                })
        print(f"Inserted variants for all products.")

if __name__ == "__main__":
    try:
        seed_data()
        print("Data seeding completed successfully!")
    except Exception as e:
        print(f"Error during seeding: {e}")
