import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from support_agent.db import connect
from support_agent.seed import seed_database
from support_agent.tools import SupportTools


@pytest.fixture
def tools(tmp_path):
    path = tmp_path / "support.db"
    seed_database(path, as_of=date(2026, 10, 6))
    return SupportTools(path, 1, tmp_path / "outbox.jsonl",
                        Path(__file__).resolve().parents[1] / "policy", today=date(2026, 10, 6))


def test_lookups_and_ownership(tools):
    assert tools.lookup_order(1042)["order"]["amount"] == 4999
    assert tools.lookup_order(1002)["code"] == "not_found"
    assert tools.lookup_order(9999)["code"] == "not_found"
    assert tools.lookup_customer(email="customer01@example.com")["customer"]["id"] == 1
    assert tools.lookup_customer(customer_id=2)["code"] == "not_found"
    assert tools.lookup_customer(customer_id=1, email="customer02@example.com")["code"] == "not_found"
    assert tools.lookup_customer()["code"] == "invalid_input"
    assert all(row["customer_id"] == 1 for row in tools.list_orders()["orders"])
    assert tools.get_refund_status(1042)["refund"] is None
    assert tools.get_refund_status(1002)["code"] == "not_found"


def test_refund_persists_and_prevents_duplicates(tools):
    assert tools.process_refund(1042, 4999, "Wrong item")["ok"]
    assert tools.lookup_order(1042)["order"]["status"] == "refunded"
    assert tools.get_refund_status(1042)["refund"]["reason"] == "Wrong item"
    assert tools.process_refund(1042, 4999, "Retry")["code"] == "already_refunded"


@pytest.mark.parametrize("age,amount,status,code", [
    (31, 4999, "delivered", "ineligible"), (-1, 4999, "delivered", "ineligible"),
    (10, 10001, "delivered", "requires_review"), (10, 4999, "shipped", "ineligible"),
    (10, 4999, "cancelled", "ineligible"),
])
def test_refund_denials_leave_database_unchanged(tools, age, amount, status, code):
    from datetime import timedelta
    db = connect(tools.db_path)
    with db:
        db.execute("UPDATE orders SET date = ?, amount = ?, status = ? WHERE id = 1042",
                   ((tools.today - timedelta(days=age)).isoformat(), amount, status))
    db.close()
    assert tools.process_refund(1042, amount, "Requested")["code"] == code
    assert tools.get_refund_status(1042)["refund"] is None
    assert tools.lookup_order(1042)["order"]["status"] == status


def test_refund_limits_and_ownership(tools):
    assert tools.process_refund(1042, 1, "Partial")["code"] == "requires_review"
    assert tools.process_refund(1002, 3000, "Other customer")["code"] == "not_found"
    assert tools.process_refund(1042, 4999, " ")["code"] == "invalid_input"
    with pytest.raises(ValidationError):
        tools.process_refund(1042, 49.99, "Not cents")
    db = connect(tools.db_path)
    with db:
        db.execute("UPDATE orders SET date = '2026-09-06', amount = 10000 WHERE id = 1042")
    db.close()
    assert tools.process_refund(1042, 10000, "Boundary")["ok"]


def test_concurrent_refund_only_writes_once(tools):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: tools.process_refund(1042, 4999, "Retry"), range(2)))
    assert sum(result["ok"] for result in results) == 1


def test_refund_rolls_back_when_order_write_fails(tools):
    db = connect(tools.db_path)
    db.execute("CREATE TRIGGER fail_update BEFORE UPDATE ON orders BEGIN SELECT RAISE(ABORT, 'test'); END")
    db.commit()
    db.close()
    with pytest.raises(sqlite3.IntegrityError):
        tools.process_refund(1042, 4999, "Test rollback")
    assert tools.get_refund_status(1042)["refund"] is None


@pytest.mark.parametrize("field,value", [("address", "42 Example Avenue, Demo City"),
    ("email", "new@example.com"), ("phone", "+1-202-555-0199")])
def test_customer_updates(tools, field, value):
    assert tools.update_customer(1, field, value)["ok"]
    assert tools.lookup_customer(customer_id=1)["customer"][field] == value


def test_invalid_updates(tools):
    assert tools.update_customer(2, "address", "Test")["code"] == "not_found"
    assert tools.update_customer(1, "email", "real@other.com")["code"] == "invalid_input"
    assert tools.update_customer(1, "email", "customer02@example.com")["code"] == "conflict"
    assert tools.update_customer(1, "phone", "123")["code"] == "invalid_input"
    assert tools.update_customer(1, "address", " ")["code"] == "invalid_input"
    with pytest.raises(ValidationError):
        tools.update_customer(1, "name", "Changed")


def test_policy_and_outbox(tools):
    for topic in ("refunds", "data-handling", "escalation"):
        assert tools.read_policy(topic)["content"]
    with pytest.raises(ValidationError):
        tools.read_policy("../README")
    assert tools.respond_to_customer("Hello\nYour order is delivered.")["ok"]
    assert tools.respond_to_customer("Follow-up")["ok"]
    rows = [json.loads(line) for line in tools.outbox_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["customer_id"] == 1
    assert rows[0]["message"] == "Hello\nYour order is delivered."
    assert tools.respond_to_customer(" ")["code"] == "invalid_input"


def test_langchain_tool_contracts(tools):
    bound = {tool.name: tool for tool in tools.as_langchain_tools()}
    assert len(bound) == 8
    assert bound["lookup_order"].invoke({"order_id": 1042})["ok"]
    assert bound["list_orders"].invoke({})["ok"]
    with pytest.raises(ValidationError):
        bound["lookup_order"].invoke({"order_id": "1042"})
