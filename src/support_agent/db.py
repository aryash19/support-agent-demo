"""SQLite connection and schema shared by seeding and future tools."""

import sqlite3
from pathlib import Path

DEFAULT_DB = Path("data/support.db")

SCHEMA = """
CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    address TEXT NOT NULL,
    phone TEXT NOT NULL
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    item TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK (amount > 0),
    date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('delivered', 'shipped', 'cancelled', 'refunded'))
);
CREATE TABLE refunds (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id),
    amount INTEGER NOT NULL CHECK (amount > 0),
    reason TEXT NOT NULL,
    date TEXT NOT NULL
);
CREATE INDEX orders_customer_idx ON orders(customer_id);
"""


def connect(path: Path = DEFAULT_DB) -> sqlite3.Connection:
    """Open a connection with foreign keys enabled; callers close it."""
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
