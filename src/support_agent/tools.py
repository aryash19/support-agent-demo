"""Local support operations bound to a trusted application customer identity.

Amounts passed to refund tools are integer USD cents, matching SQLite storage.
Business failures are structured results; infrastructure failures propagate.
"""

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from support_agent.db import connect


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OrderInput(Input):
    order_id: int = Field(gt=0)


class CustomerInput(Input):
    customer_id: int | None = Field(default=None, gt=0)
    email: str | None = Field(default=None, max_length=254)


class RefundInput(OrderInput):
    amount: int = Field(gt=0, description="Full refund amount in integer USD cents")
    reason: str = Field(min_length=1, max_length=1000)


class UpdateInput(Input):
    customer_id: int = Field(gt=0)
    field: Literal["address", "email", "phone"]
    value: str = Field(min_length=1, max_length=500)


class PolicyInput(Input):
    topic: Literal["refunds", "data-handling", "escalation"]


class ReplyInput(Input):
    message: str = Field(min_length=1, max_length=10000)


class EmptyInput(Input):
    pass


def failure(code: str, message: str) -> dict:
    return {"ok": False, "code": code, "message": message}


class SupportTools:
    """One request/session's tools; customer identity never comes from model input."""

    def __init__(self, db_path: Path, customer_id: int, outbox_path: Path,
                 policy_dir: Path, *, today: date | None = None):
        if customer_id <= 0:
            raise ValueError("A trusted customer identity is required")
        self.db_path = db_path
        self.customer_id = customer_id
        self.outbox_path = outbox_path
        self.policy_dir = policy_dir
        self.today = today

    def current_date(self) -> date:
        return self.today or date.today()

    @contextmanager
    def database(self, *, write: bool = False):
        db = connect(self.db_path)
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def lookup_order(self, order_id: int) -> dict:
        with self.database() as db:
            row = db.execute("SELECT * FROM orders WHERE id = ? AND customer_id = ?",
                             (order_id, self.customer_id)).fetchone()
        return {"ok": True, "order": dict(row)} if row else failure("not_found", "Order not found")

    def lookup_customer(self, customer_id: int | None = None, email: str | None = None) -> dict:
        if customer_id is None and email is None:
            return failure("invalid_input", "Supply a customer ID or email")
        if customer_id is not None and customer_id != self.customer_id:
            return failure("not_found", "Customer not found")
        with self.database() as db:
            row = db.execute("SELECT * FROM customers WHERE id = ?", (self.customer_id,)).fetchone()
        if not row or (email is not None and row["email"].casefold() != email.strip().casefold()):
            return failure("not_found", "Customer not found")
        return {"ok": True, "customer": dict(row)}

    def list_orders(self) -> dict:
        with self.database() as db:
            rows = db.execute("SELECT * FROM orders WHERE customer_id = ? ORDER BY date DESC, id DESC",
                              (self.customer_id,)).fetchall()
        return {"ok": True, "orders": [dict(row) for row in rows]}

    def get_refund_status(self, order_id: int) -> dict:
        with self.database() as db:
            order = db.execute("SELECT id FROM orders WHERE id = ? AND customer_id = ?",
                               (order_id, self.customer_id)).fetchone()
            if not order:
                return failure("not_found", "Order not found")
            row = db.execute("SELECT * FROM refunds WHERE order_id = ?", (order_id,)).fetchone()
        return {"ok": True, "refund": dict(row) if row else None}

    def process_refund(self, order_id: int, amount: int, reason: str) -> dict:
        # Validate also for callers using the Python service directly.
        args = RefundInput(order_id=order_id, amount=amount, reason=reason)
        if not args.reason.strip():
            return failure("invalid_input", "A refund reason is required")
        with self.database(write=True) as db:
            order = db.execute("SELECT * FROM orders WHERE id = ? AND customer_id = ?",
                               (order_id, self.customer_id)).fetchone()
            if not order:
                return failure("not_found", "Order not found")
            if order["status"] == "refunded" or db.execute(
                    "SELECT id FROM refunds WHERE order_id = ?", (order_id,)).fetchone():
                return failure("already_refunded", "This order already has a refund")
            age = (self.current_date() - date.fromisoformat(order["date"])).days
            if order["status"] != "delivered" or not 0 <= age <= 30:
                return failure("ineligible", "Only delivered orders within 30 days are eligible")
            if amount != order["amount"]:
                return failure("requires_review", "Only full refunds are supported automatically")
            if amount > 10000:
                return failure("requires_review", "Refunds above $100 require human approval")
            cursor = db.execute("INSERT INTO refunds (order_id, amount, reason, date) VALUES (?, ?, ?, ?)",
                                (order_id, amount, reason.strip(), self.current_date().isoformat()))
            db.execute("UPDATE orders SET status = 'refunded' WHERE id = ?", (order_id,))
            result = {"ok": True, "refund_id": cursor.lastrowid, "order_id": order_id,
                      "amount": amount, "status": "refunded"}
        return result

    def update_customer(self, customer_id: int, field: str, value: str) -> dict:
        args = UpdateInput(customer_id=customer_id, field=field, value=value)
        if customer_id != self.customer_id:
            return failure("not_found", "Customer not found")
        value = args.value.strip()
        if not value or any(ord(c) < 32 for c in value):
            return failure("invalid_input", "Provide a nonempty value without control characters")
        if field == "email":
            value = value.lower()
            if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@example\.com", value):
                return failure("invalid_input", "Use a valid example.com email")
        if field == "phone" and not re.fullmatch(r"\+1-202-555-01\d{2}", value):
            return failure("invalid_input", "Use a synthetic +1-202-555-01xx phone number")
        try:
            with self.database(write=True) as db:
                # field is restricted by UpdateInput's Literal, never arbitrary SQL.
                cursor = db.execute(f"UPDATE customers SET {args.field} = ? WHERE id = ?",
                                    (value, self.customer_id))
                if not cursor.rowcount:
                    return failure("not_found", "Customer not found")
        except sqlite3.IntegrityError:
            return failure("conflict", "That email cannot be used")
        return {"ok": True, "customer_id": customer_id, "field": field, "value": value}

    def read_policy(self, topic: str) -> dict:
        args = PolicyInput(topic=topic)
        return {"ok": True, "topic": topic,
                "content": (self.policy_dir / f"{args.topic}.md").read_text(encoding="utf-8")}

    def respond_to_customer(self, message: str) -> dict:
        args = ReplyInput(message=message)
        if not args.message.strip():
            return failure("invalid_input", "Reply must not be blank")
        # Ensure the application identity exists before recording a reply.
        with self.database() as db:
            if not db.execute("SELECT id FROM customers WHERE id = ?", (self.customer_id,)).fetchone():
                return failure("not_found", "Customer not found")
        self.outbox_path.parent.mkdir(parents=True, exist_ok=True)
        record = {"customer_id": self.customer_id, "message": message,
                  "date": self.current_date().isoformat()}
        with self.outbox_path.open("a", encoding="utf-8") as outbox:
            outbox.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"ok": True, "delivery": "local_outbox", "customer_id": self.customer_id}

    def as_langchain_tools(self) -> list[StructuredTool]:
        specs = [
            ("lookup_order", OrderInput, "Look up an order belonging to the current customer."),
            ("lookup_customer", CustomerInput, "Look up the current customer by ID or email."),
            ("process_refund", RefundInput, "Issue a full eligible refund in USD cents; enforce policy."),
            ("update_customer", UpdateInput, "Update the current customer's address, example.com email, or synthetic phone."),
            ("read_policy", PolicyInput, "Read company refund, data-handling, or escalation policy."),
            ("respond_to_customer", ReplyInput, "Record the customer reply in the local outbox."),
            ("list_orders", EmptyInput, "List the current customer's orders."),
            ("get_refund_status", OrderInput, "Read refund status for the current customer's order."),
        ]
        return [StructuredTool.from_function(getattr(self, name), name=name,
                description=description, args_schema=schema) for name, schema, description in specs]
