"""Create data/sample.db - a small, realistic retail database.

Usage:  python scripts/create_sample_db.py [--force]
"""

from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sample.db"

SCHEMA = """
CREATE TABLE categories (
    category_id   INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    description   TEXT
);
CREATE TABLE products (
    product_id    INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    category_id   INTEGER NOT NULL REFERENCES categories(category_id),
    unit_price    REAL NOT NULL,
    units_in_stock INTEGER NOT NULL DEFAULT 0,
    discontinued  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE customers (
    customer_id   INTEGER PRIMARY KEY,
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    email         TEXT UNIQUE,
    city          TEXT,
    country       TEXT,
    signup_date   DATE
);
CREATE TABLE employees (
    employee_id   INTEGER PRIMARY KEY,
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    title         TEXT,
    hire_date     DATE,
    manager_id    INTEGER REFERENCES employees(employee_id)
);
CREATE TABLE orders (
    order_id      INTEGER PRIMARY KEY,
    customer_id   INTEGER NOT NULL REFERENCES customers(customer_id),
    employee_id   INTEGER REFERENCES employees(employee_id),
    order_date    DATE NOT NULL,
    status        TEXT NOT NULL,
    ship_city     TEXT,
    ship_country  TEXT
);
CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(order_id),
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL,
    unit_price    REAL NOT NULL,
    discount      REAL NOT NULL DEFAULT 0
);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_items_product ON order_items(product_id);
CREATE VIEW order_totals AS
SELECT o.order_id, o.customer_id, o.order_date, o.status,
       ROUND(SUM(i.quantity * i.unit_price * (1 - i.discount)), 2) AS total
FROM orders o JOIN order_items i ON i.order_id = o.order_id
GROUP BY o.order_id;
"""

CATEGORIES = {
    "Electronics": ["Wireless Mouse", "Mechanical Keyboard", "USB-C Hub",
                    "27-inch Monitor", "Noise-Cancelling Headphones", "Webcam HD"],
    "Books": ["Learning SQL", "Python Crash Course", "Clean Code",
              "The Pragmatic Programmer", "Data Science Handbook"],
    "Home & Kitchen": ["Coffee Maker", "Chef Knife", "Blender",
                       "Cast Iron Pan", "Electric Kettle"],
    "Sports": ["Yoga Mat", "Running Shoes", "Dumbbell Set", "Water Bottle",
               "Cycling Helmet"],
    "Office": ["Standing Desk", "Ergonomic Chair", "Desk Lamp",
               "Notebook Pack", "Gel Pens"],
}
PRICE_RANGE = {"Electronics": (19, 349), "Books": (12, 55),
               "Home & Kitchen": (15, 180), "Sports": (9, 140),
               "Office": (4, 499)}

LOCATIONS = {
    "Germany": ["Berlin", "Munich", "Hamburg", "Frankfurt"],
    "France": ["Paris", "Lyon", "Marseille"],
    "USA": ["New York", "Chicago", "San Francisco", "Austin"],
    "UK": ["London", "Manchester", "Edinburgh"],
    "India": ["Mumbai", "Bengaluru", "Delhi", "Chennai"],
    "Brazil": ["São Paulo", "Rio de Janeiro"],
    "Japan": ["Tokyo", "Osaka"],
    "Canada": ["Toronto", "Vancouver"],
    "Spain": ["Madrid", "Barcelona"],
    "Australia": ["Sydney", "Melbourne"],
}
FIRST = ["Anna", "Ben", "Carla", "David", "Elena", "Felix", "Grace", "Hugo",
         "Isha", "Jonas", "Kenji", "Lena", "Marco", "Nina", "Omar", "Priya",
         "Quinn", "Rosa", "Sam", "Tara", "Umar", "Vera", "Wei", "Yuki", "Zoe"]
LAST = ["Müller", "Schmidt", "Dubois", "Smith", "Johnson", "Brown", "Patel",
        "Sharma", "Silva", "Tanaka", "García", "Martin", "Wilson", "Lee",
        "Kumar", "Rossi", "Nguyen", "Fischer", "Taylor", "Moreau"]
STATUSES = ["delivered"] * 7 + ["shipped", "processing", "cancelled"]


def rand_date(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def build(path: Path, seed: int = 42) -> None:
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(SCHEMA)

        # Categories & products
        product_rows = []
        pid = 1
        for cid, (cat, items) in enumerate(CATEGORIES.items(), start=1):
            con.execute("INSERT INTO categories VALUES (?, ?, ?)",
                        (cid, cat, f"All things {cat.lower()}"))
            lo, hi = PRICE_RANGE[cat]
            for item in items:
                price = round(rng.uniform(lo, hi), 2)
                product_rows.append((pid, item, cid, price, rng.randint(0, 250),
                                     int(rng.random() < 0.08)))
                pid += 1
        con.executemany("INSERT INTO products VALUES (?,?,?,?,?,?)", product_rows)
        prices = {r[0]: r[3] for r in product_rows}

        # Employees (1 manager + reports)
        employees = [
            (1, "Sophie", "Wagner", "Sales Manager", "2019-03-01", None),
            (2, "Luca", "Bianchi", "Sales Representative", "2020-06-15", 1),
            (3, "Aisha", "Khan", "Sales Representative", "2021-01-10", 1),
            (4, "Tom", "Becker", "Sales Representative", "2022-09-05", 1),
            (5, "Mei", "Chen", "Inside Sales Coordinator", "2023-02-20", 1),
        ]
        con.executemany("INSERT INTO employees VALUES (?,?,?,?,?,?)", employees)

        # Customers
        customers = []
        for cid in range(1, 121):
            fn, ln = rng.choice(FIRST), rng.choice(LAST)
            country = rng.choice(list(LOCATIONS))
            city = rng.choice(LOCATIONS[country])
            email = f"{fn}.{ln}{cid}@example.com".lower()
            signup = rand_date(rng, date(2022, 1, 1), date(2024, 6, 30))
            customers.append((cid, fn, ln, email, city, country, signup.isoformat()))
        con.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?,?)", customers)

        # Orders & items (~15% of customers never order)
        buyers = [c for c in customers if rng.random() > 0.15]
        oid, iid = 1, 1
        order_rows, item_rows = [], []
        for _ in range(600):
            c = rng.choice(buyers)
            signup = date.fromisoformat(c[6])
            odate = rand_date(rng, max(signup, date(2023, 1, 1)), date(2025, 6, 30))
            order_rows.append((oid, c[0], rng.randint(1, 5), odate.isoformat(),
                               rng.choice(STATUSES), c[4], c[5]))
            for product_id in rng.sample(list(prices), rng.randint(1, 4)):
                discount = rng.choice([0, 0, 0, 0.05, 0.1, 0.15])
                item_rows.append((iid, oid, product_id, rng.randint(1, 5),
                                  prices[product_id], discount))
                iid += 1
            oid += 1
        con.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?)", order_rows)
        con.executemany("INSERT INTO order_items VALUES (?,?,?,?,?,?)", item_rows)
        con.commit()
    finally:
        con.close()
    print(f"Created {path} "
          f"({len(customers)} customers, {len(order_rows)} orders, "
          f"{len(item_rows)} order items, {len(product_rows)} products)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="Overwrite an existing database")
    parser.add_argument("--path", type=Path, default=DB_PATH)
    args = parser.parse_args()
    if args.path.exists():
        if not args.force:
            print(f"{args.path} already exists (use --force to rebuild).")
            return
        args.path.unlink()
    build(args.path)


if __name__ == "__main__":
    main()
