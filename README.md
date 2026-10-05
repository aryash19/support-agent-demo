# Support agent demo

A local customer-support agent using LangGraph and Ollama. This repository is
built in reviewable steps. Step 1 provides the database, policies, and seed tests.
Agent execution, support tools, and tracing are implemented in later steps.

## Setup

Install uv and run these commands from this repository:

```powershell
uv sync
uv run python -m support_agent.seed
uv run pytest
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
