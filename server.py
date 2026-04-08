"""
FastMCP Server — Microservices Orchestration + Ticket Management
Exposes tools for: User, Order, Payment, Notification, and Ticket services.
Run: python server.py
"""

import asyncio
import httpx
import sqlite3
import json
from datetime import datetime
from typing import Optional
from fastmcp import FastMCP

# ─────────────────────────────────────────────
# Service Registry
# ─────────────────────────────────────────────
SERVICES = {
    "user":         "http://localhost:8080",
    "order":        "http://localhost:8082",
    "payment":      "http://localhost:8083",
    "notification": "http://localhost:8084",
    "ticket":       "http://localhost:8090",
}

# Dependency graph: each service calls the next downstream
DEPENDENCY_GRAPH = {
    "user":         ["order"],
    "order":        ["payment"],
    "payment":      ["notification"],
    "notification": [],
    "ticket":       ["user", "order", "payment", "notification"],  # ticket tracks all four
}

# ─────────────────────────────────────────────
# FastMCP App
# ─────────────────────────────────────────────
mcp = FastMCP(
    name="Microservices Orchestration Server",
    instructions=(
        "This MCP server exposes tools to interact with five microservices: "
        "user (8080), order (8082), payment (8083), notification (8084), and ticket (8090). "
        "Use health/toggle tools to monitor/control cascading health. "
        "Use process tools to trigger chain calls. "
        "Use ticket tools to manage issues in batch. "
        "Use dependency_graph to understand service relationships."
    ),
)

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
async def _get(url: str) -> str:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text

async def _post(url: str, json_body: Optional[dict] = None) -> str:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(url, json=json_body or {})
        r.raise_for_status()
        return r.text if r.text else "OK"

async def _put(url: str, json_body: Optional[dict] = None) -> str:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.put(url, json=json_body or {})
        r.raise_for_status()
        try:
            return json.dumps(r.json())
        except Exception:
            return r.text

# ─────────────────────────────────────────────
# ── CORE SERVICE TOOLS ────────────────────────
# ─────────────────────────────────────────────

# ── /process ──────────────────────────────────

@mcp.tool(description="Trigger the User service process (GET /user/process). It chains to Order → Payment → Notification.")
async def user_process() -> str:
    return await _get(f"{SERVICES['user']}/user/process")


@mcp.tool(description="Trigger the Order service process (GET /order/process). It chains to Payment → Notification.")
async def order_process() -> str:
    return await _get(f"{SERVICES['order']}/order/process")


@mcp.tool(description="Trigger the Payment service process (GET /payment/process). It chains to Notification.")
async def payment_process() -> str:
    return await _get(f"{SERVICES['payment']}/payment/process")


@mcp.tool(description="Trigger the Notification service process (GET /notification/process). Terminal service.")
async def notification_process() -> str:
    return await _get(f"{SERVICES['notification']}/notification/process")


# ── /health ───────────────────────────────────

@mcp.tool(description="Check health status of the User service (GET /user/health).")
async def user_health() -> str:
    return await _get(f"{SERVICES['user']}/user/health")


@mcp.tool(description="Check health status of the Order service (GET /order/health).")
async def order_health() -> str:
    return await _get(f"{SERVICES['order']}/order/health")


@mcp.tool(description="Check health status of the Payment service (GET /payment/health).")
async def payment_health() -> str:
    return await _get(f"{SERVICES['payment']}/payment/health")


@mcp.tool(description="Check health status of the Notification service (GET /notification/health).")
async def notification_health() -> str:
    return await _get(f"{SERVICES['notification']}/notification/health")


@mcp.tool(description="Check ALL four core services health at once and return a summary.")
async def all_health_check() -> str:
    results = {}
    for name in ["user", "order", "payment", "notification"]:
        try:
            results[name] = await _get(f"{SERVICES[name]}/{name}/health")
        except Exception as e:
            results[name] = f"ERROR: {e}"
    return json.dumps(results, indent=2)


# ── /toggle ───────────────────────────────────

@mcp.tool(description="Toggle the health status of the User service (POST /user/toggle). Cascading effect propagates to Order, Payment, Notification.")
async def user_toggle() -> str:
    return await _post(f"{SERVICES['user']}/user/toggle")


@mcp.tool(description="Toggle the health status of the Order service (POST /order/toggle). Cascading effect propagates to Payment, Notification.")
async def order_toggle() -> str:
    return await _post(f"{SERVICES['order']}/order/toggle")


@mcp.tool(description="Toggle the health status of the Payment service (POST /payment/toggle). Cascading effect propagates to Notification.")
async def payment_toggle() -> str:
    return await _post(f"{SERVICES['payment']}/payment/toggle")


@mcp.tool(description="Toggle the health status of the Notification service (POST /notification/toggle).")
async def notification_toggle() -> str:
    return await _post(f"{SERVICES['notification']}/notification/toggle")


# ── /logs ─────────────────────────────────────

@mcp.tool(description="Fetch logs from the User service (GET /user/logs). Logs are stored in SQLite.")
async def user_logs() -> str:
    return await _get(f"{SERVICES['user']}/user/logs")


@mcp.tool(description="Fetch logs from the Order service (GET /order/logs).")
async def order_logs() -> str:
    return await _get(f"{SERVICES['order']}/order/logs")


@mcp.tool(description="Fetch logs from the Payment service (GET /payment/logs).")
async def payment_logs() -> str:
    return await _get(f"{SERVICES['payment']}/payment/logs")


@mcp.tool(description="Fetch logs from the Notification service (GET /notification/logs).")
async def notification_logs() -> str:
    return await _get(f"{SERVICES['notification']}/notification/logs")


@mcp.tool(description="Fetch logs from ALL four core services at once and return a combined summary.")
async def all_logs() -> str:
    combined = {}
    for name in ["user", "order", "payment", "notification"]:
        try:
            combined[name] = await _get(f"{SERVICES[name]}/{name}/logs")
        except Exception as e:
            combined[name] = f"ERROR: {e}"
    return json.dumps(combined, indent=2)


# ─────────────────────────────────────────────
# ── TICKET SERVICE TOOLS ─────────────────────
# ─────────────────────────────────────────────

@mcp.tool(description=(
    "Create a new ticket in the Ticket service (POST /tickets). "
    "Parameters: ticketId (str), service (str — must be user/order/payment/notification), "
    "severity (str), error (str)."
))
async def create_ticket(ticketId: str, service: str, severity: str, error: str) -> str:
    payload = {
        "ticketId": ticketId,
        "service": service,
        "severity": severity,
        "error": error,
    }
    return await _post(f"{SERVICES['ticket']}/tickets", json_body=payload)


@mcp.tool(description="Get a ticket by ID from the Ticket service (GET /tickets/{id}).")
async def get_ticket(ticket_id: str) -> str:
    return await _get(f"{SERVICES['ticket']}/tickets/{ticket_id}")


@mcp.tool(description=(
    "Update an existing ticket (PUT /tickets/{id}). "
    "Parameters: ticket_id (str), severity (str), error (str)."
))
async def update_ticket(ticket_id: str, severity: str, error: str) -> str:
    payload = {"severity": severity, "error": error}
    return await _put(f"{SERVICES['ticket']}/tickets/{ticket_id}", json_body=payload)


@mcp.tool(description="Resolve a ticket by ID (POST /tickets/{id}/resolve). Marks it as resolved in Neo4j.")
async def resolve_ticket(ticket_id: str) -> str:
    return await _post(f"{SERVICES['ticket']}/tickets/{ticket_id}/resolve")


@mcp.tool(description="Mark a ticket as in-progress by ID (POST /tickets/{id}/progress).")
async def progress_ticket(ticket_id: str) -> str:
    return await _post(f"{SERVICES['ticket']}/tickets/{ticket_id}/progress")


@mcp.tool(description="Get all OPEN tickets from the Ticket service (GET /tickets/open).")
async def get_open_tickets() -> str:
    return await _get(f"{SERVICES['ticket']}/tickets/open")


@mcp.tool(description="Get all RESOLVED tickets from the Ticket service (GET /tickets/resolved).")
async def get_resolved_tickets() -> str:
    return await _get(f"{SERVICES['ticket']}/tickets/resolved")


# ─────────────────────────────────────────────
# ── BATCH TICKET PROCESSING ──────────────────
# ─────────────────────────────────────────────

@mcp.tool(description=(
    "Batch-resolve ALL open tickets automatically. "
    "Fetches all open tickets from the Ticket service and resolves each one. "
    "Returns a summary of how many were resolved and any failures. "
    "Use this for automated periodic resolution instead of resolving one by one."
))
async def batch_resolve_open_tickets() -> str:
    """
    Periodically callable batch tool: fetches all open tickets and resolves them.
    Ideal for scheduled runs (e.g., every N minutes via a cron or agent loop).
    """
    resolved_ids = []
    failed = []

    try:
        raw = await _get(f"{SERVICES['ticket']}/tickets/open")
        tickets = json.loads(raw)
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch open tickets: {e}"})

    if not tickets:
        return json.dumps({"message": "No open tickets found.", "resolved": [], "failed": []})

    for ticket in tickets:
        tid = ticket.get("ticketId") or ticket.get("id")
        if not tid:
            continue
        try:
            await _post(f"{SERVICES['ticket']}/tickets/{tid}/resolve")
            resolved_ids.append(tid)
        except Exception as e:
            failed.append({"ticketId": tid, "error": str(e)})

    return json.dumps({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "total_open": len(tickets),
        "resolved_count": len(resolved_ids),
        "resolved_ids": resolved_ids,
        "failed_count": len(failed),
        "failures": failed,
    }, indent=2)


@mcp.tool(description=(
    "Batch-process open tickets for a specific service (user/order/payment/notification). "
    "Fetches all open tickets, filters by service name, and resolves matching ones. "
    "Useful for targeted batch resolution of a single degraded service."
))
async def batch_resolve_tickets_by_service(service: str) -> str:
    resolved_ids = []
    failed = []

    try:
        raw = await _get(f"{SERVICES['ticket']}/tickets/open")
        tickets = json.loads(raw)
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch open tickets: {e}"})

    matching = [t for t in tickets if t.get("service", "").lower() == service.lower()]

    if not matching:
        return json.dumps({"message": f"No open tickets for service '{service}'.", "resolved": []})

    for ticket in matching:
        tid = ticket.get("ticketId") or ticket.get("id")
        if not tid:
            continue
        try:
            await _post(f"{SERVICES['ticket']}/tickets/{tid}/resolve")
            resolved_ids.append(tid)
        except Exception as e:
            failed.append({"ticketId": tid, "error": str(e)})

    return json.dumps({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "service": service,
        "matched": len(matching),
        "resolved_count": len(resolved_ids),
        "resolved_ids": resolved_ids,
        "failed_count": len(failed),
        "failures": failed,
    }, indent=2)


# ─────────────────────────────────────────────
# ── DEPENDENCY GRAPH ─────────────────────────
# ─────────────────────────────────────────────

@mcp.tool(description=(
    "Return the full dependency graph of all microservices. "
    "Shows which services depend on which, including the Ticket service "
    "which tracks issues for all four core services stored in Neo4j."
))
async def get_dependency_graph() -> str:
    graph = {
        "description": (
            "Directed dependency graph. "
            "An entry A -> [B] means service A calls service B downstream."
        ),
        "nodes": list(SERVICES.keys()),
        "edges": DEPENDENCY_GRAPH,
        "ports": {name: url.replace("http://localhost:", "") for name, url in SERVICES.items()},
        "cascade_chain": "user → order → payment → notification",
        "ticket_service": {
            "port": 8090,
            "storage": "Neo4j (graph DB)",
            "tracks": ["user", "order", "payment", "notification"],
            "note": (
                "Tickets are created from Excel files uploaded by users. "
                "The Ticket service stores and manages them as graph nodes in Neo4j, "
                "linked to the affected service nodes."
            ),
        },
        "log_storage": "SQLite (per-service)",
    }
    return json.dumps(graph, indent=2)


# ─────────────────────────────────────────────
# ── SYSTEM OVERVIEW ──────────────────────────
# ─────────────────────────────────────────────

@mcp.tool(description=(
    "Full system snapshot: health of all 4 core services + open ticket count. "
    "Use this as a quick dashboard call at the start of any monitoring session."
))
async def system_snapshot() -> str:
    health = {}
    for name in ["user", "order", "payment", "notification"]:
        try:
            health[name] = await _get(f"{SERVICES[name]}/{name}/health")
        except Exception as e:
            health[name] = f"UNREACHABLE: {e}"

    try:
        open_raw = await _get(f"{SERVICES['ticket']}/tickets/open")
        open_tickets = json.loads(open_raw)
        open_count = len(open_tickets)
    except Exception as e:
        open_tickets = []
        open_count = f"ERROR: {e}"

    return json.dumps({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "service_health": health,
        "open_tickets": open_count,
        "cascade_chain": "user(8080) → order(8082) → payment(8083) → notification(8084)",
        "ticket_service": f"{SERVICES['ticket']} [Neo4j]",
    }, indent=2)


# ─────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────
if __name__ == "__main__":
    # SSE transport exposes the MCP server on HTTP so Kaii agent can discover it.
    # After running, use a cloud tunnel (e.g. ngrok / cloudflared) to get a public URL:
    #   ngrok http 8000
    #   cloudflared tunnel --url http://localhost:8000
    # Then register that public URL in Kaii as an MCP server endpoint.
    mcp.run(transport="sse", host="0.0.0.0", port=8000)
