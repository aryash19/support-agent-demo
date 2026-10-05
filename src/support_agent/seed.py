"""Recreate a deterministic synthetic fixture database."""

import argparse
from datetime import date, timedelta
from pathlib import Path

from support_agent.db import DEFAULT_DB, SCHEMA, connect

ITEMS = ("Desk lamp", "Notebook set", "Travel mug", "USB cable", "Keyboard")


def seed_database(path: Path = DEFAULT_DB, *, as_of: date | None = None) -> None:
    """Replace this demo database's tables atomically; amounts are USD cents."""
    anchor = as_of or date.today()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(path)
    try:
        # executescript commits a pending transaction, so BEGIN belongs inside it.
        connection.executescript(
            "BEGIN IMMEDIATE; DROP TABLE IF EXISTS refunds; "
            "DROP TABLE IF EXISTS orders; DROP TABLE IF EXISTS customers;" + SCHEMA
        )
        connection.executemany(
            "INSERT INTO customers VALUES (?, ?, ?, ?, ?)",
            [
                (i, f"Demo Customer {i:02}", f"customer{i:02}@example.com",
                 f"{i} Example Street, Demo City", f"+1-202-555-{100 + i:04}")
                for i in range(1, 21)
            ],
        )
        rows = []
        for offset in range(50):
            order_id = 1001 + offset
            age = 10 if order_id == 1042 else (offset * 7) % 65
            amount = 4999 if order_id == 1042 else (offset % 8 + 1) * 1500
            customer_id = 1 if order_id == 1042 else offset % 20 + 1
            status = "delivered" if order_id == 1042 or offset % 5 else "shipped"
            rows.append((order_id, customer_id, ITEMS[offset % len(ITEMS)], amount,
                         (anchor - timedelta(days=age)).isoformat(), status))
        connection.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)", rows)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset a local synthetic support database.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--as-of", type=date.fromisoformat, help="Anchor date, YYYY-MM-DD")
    args = parser.parse_args()
    seed_database(args.db, as_of=args.as_of)
    print(f"Seeded {args.db}: 20 synthetic customers, 50 orders, 0 refunds.")


if __name__ == "__main__":
    main()
