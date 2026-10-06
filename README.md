# Support agent demo

A local customer-support agent using LangGraph and Ollama. This repository is
built in reviewable steps. Steps 1 and 2 provide the database, policies, support
tools, and tests. Agent execution and tracing are implemented in later steps.

## Setup

Install uv and run these commands from this repository:

```powershell
uv sync
uv run python -m support_agent.seed
uv run python -m pytest
```

Python 3.11 or newer is required. The seed command resets the customers, orders,
and refunds tables in `data/support.db`; use a demo database only. To choose a
different file and deterministic date:

```powershell
uv run python -m support_agent.seed --db data/demo.db --as-of 2026-10-05
```

There are 20 fake customers, 50 orders, and initially no refunds. Emails use
example.com, addresses are invented, and phone numbers use the fictional
202-555-01xx range. Money is stored as integer USD cents. Dates use ISO format.
Order 1042 belongs to customer 1, costs $49.99, and is dated ten days before
the seed anchor date, making it eligible for the documented refund policy.
Database files and local outbox messages are excluded from Git.

## Planned implementation

1. Repository, repeatable synthetic seed, policy documents, and seed tests.
2. Typed lookup_order, lookup_customer, process_refund, update_customer, and
   respond_to_customer tools; read_policy supplies company policy.
3. LangGraph agent and CLI backed by Ollama, with authenticated synthetic
   customer context and tool authorization enforced by code.
4. OpenTelemetry GenAI tracing with synthetic content and running instructions.

The expanded design will add a local MCP tool server, explicit stateful sessions
and stateless runs, and specialist agents coordinated by a support supervisor.
Additional tools may cover ticket creation, escalation, order history, and
refund status. Their contracts and permissions will be reviewed before step 2.
All actions remain local; customer replies are written to outbox.jsonl.

## Support tools (step 2)

`SupportTools` in `src/support_agent/tools.py` exposes eight typed LangChain tools:
the six core operations (including read_policy), plus list_orders and
get_refund_status. The application supplies a trusted customer ID when creating
the service; model-supplied IDs cannot change its account scope.

```python
from pathlib import Path
from support_agent.tools import SupportTools

service = SupportTools(Path("data/support.db"), customer_id=1,
                       outbox_path=Path("outbox.jsonl"), policy_dir=Path("policy"))
tools = service.as_langchain_tools()
print(service.lookup_order(1042))
```

Refund amounts use integer cents: 4999 means $49.99. Full refunds are authorized
only for owned, delivered orders aged 0–30 days with a total of at most 10000
cents. Duplicate requests do not create additional refunds. The refund insert
and status update use one transaction, serialized with BEGIN IMMEDIATE.
Policy Markdown explains these rules; executable enforcement lives in the
service and policy changes must update both together.

Expected business denials return `ok: false` with a code and explanation.
Invalid typed inputs raise Pydantic validation errors; database/filesystem
failures propagate so the future agent can handle them without claiming success.
Account changes validate fields and restrict emails and phones to synthetic
values. Addresses must be invented demo addresses; free text is not a personal
data detector. Only synthetic inputs should be used.

Outbox writes append one JSON record per reply. This demo outbox is intended for
a single local process and has no exactly-once delivery or cross-process locking.
MCP transport, durable sessions, specialist agents, and escalation tickets are
pending the agent design step; they are not implemented by this commit.
