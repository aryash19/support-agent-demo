from datetime import date

import pytest

from support_agent.db import connect
from support_agent.seed import seed_database


def test_seed_is_repeatable_and_synthetic(tmp_path):
    path = tmp_path / "nested" / "support.db"
    seed_database(path, as_of=date(2026, 10, 5))
    db = connect(path)
    try:
        assert db.execute("SELECT count(*) FROM customers").fetchone()[0] == 20
        assert db.execute("SELECT count(*) FROM orders").fetchone()[0] == 50
        assert db.execute("SELECT count(*) FROM refunds").fetchone()[0] == 0
        assert all(row[0].endswith("@example.com") for row in db.execute("SELECT email FROM customers"))
        order = dict(db.execute("SELECT * FROM orders WHERE id = 1042").fetchone())
        assert order == dict(id=1042, customer_id=1, item="Notebook set", amount=4999,
                            date="2026-09-25", status="delivered")
        db.execute("UPDATE customers SET name = 'Modified' WHERE id = 1")
        db.commit()
    finally:
        db.close()
    seed_database(path, as_of=date(2026, 10, 5))
    db = connect(path)
    try:
        assert db.execute("SELECT name FROM customers WHERE id = 1").fetchone()[0] == "Demo Customer 01"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        db.close()


def test_schema_rejects_orphan_order(tmp_path):
    path = tmp_path / "support.db"
    seed_database(path)
    db = connect(path)
    try:
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO orders VALUES (9999, 999, 'Lamp', 100, '2026-10-05', 'delivered')")
    finally:
        db.close()
