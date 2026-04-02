"""
MCP Server — Microservice Health Monitor + Kaii Agent Bridge
Monitors 4 Spring Boot services, fetches logs from Neo4j,
triggers Kaii Agent on unhealthy services, and can restart services locally.
"""

import asyncio
import subprocess
import os
import json
import logging
from datetime import datetime
from typing import Any

import requests
from neo4j import GraphDatabase
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

# Base URLs per service
SERVICES = {
    "user":         "http://localhost:8080",
    "order":        "http://localhost:8082",
    "payment":      "http://localhost:8083",
    "notification": "http://localhost:8084",
}

# Each service exposes its own health path returning a plain string: "HEALTHY" | "UNHEALTHY"
HEALTH_PATHS = {
    "user":         "/user/health",
    "order":        "/order/health",
    "payment":      "/payment/health",
    "notification": "/notification/health",
}

NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

# Your organisation's Kaii Agent REST endpoint
KAII_AGENT_URL = os.getenv("KAII_AGENT_URL", "http://localhost:9000/kaii/analyze")

# Local restart scripts — one per service
RESTART_SCRIPTS = {
    "user":         "./scripts/restart_user.sh",
    "order":        "./scripts/restart_order.sh",
    "payment":      "./scripts/restart_payment.sh",
    "notification": "./scripts/restart_notification.sh",
}

HEALTH_TIMEOUT = 5   # seconds
LOG_FETCH_LIMIT = 50 # max log entries per service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-health-monitor")

# ─────────────────────────────────────────────
# NEO4J CLIENT
# ─────────────────────────────────────────────

class Neo4jLogClient:
    """
    Queries your existing @Node("Log") Spring Data Neo4j model:

        (:Log {
            id:          Long,
            message:     String,
            status:      "HEALTHY" | "UNHEALTHY" | "DEGRADED",
            error:       String,
            timestamp:   datetime,
            serviceName: String
        })
    """

    # Status values that indicate a problem — sent to Kaii Agent
    UNHEALTHY_STATUSES = {"UNHEALTHY", "DEGRADED"}

    def __init__(self):
        self._driver = None

    def _get_driver(self):
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                NEO4J_URI,
                auth=(NEO4J_USER, NEO4J_PASSWORD)
            )
        return self._driver

    def _record_to_dict(self, record) -> dict:
        """Convert a Neo4j record to a clean Python dict."""
        return {
            "id":          record["id"],
            "serviceName": record["serviceName"],
            "status":      record["status"],
            "message":     record["message"],
            "error":       record["error"],
            "timestamp":   str(record["timestamp"]),
        }

    def fetch_logs(self, service_name: str, limit: int = LOG_FETCH_LIMIT,
                   status_filter: str = None) -> list[dict]:
        """
        Fetch recent logs for a service from Neo4j.
        Optionally filter by status: HEALTHY | UNHEALTHY | DEGRADED
        """
        try:
            driver = self._get_driver()
            with driver.session() as session:
                if status_filter:
                    query = """
                        MATCH (l:Log {serviceName: $serviceName, status: $status})
                        RETURN l.id          AS id,
                               l.serviceName AS serviceName,
                               l.status      AS status,
                               l.message     AS message,
                               l.error       AS error,
                               l.timestamp   AS timestamp
                        ORDER BY l.timestamp DESC
                        LIMIT $limit
                    """
                    result = session.run(
                        query,
                        serviceName=service_name,
                        status=status_filter.upper(),
                        limit=limit
                    )
                else:
                    query = """
                        MATCH (l:Log {serviceName: $serviceName})
                        RETURN l.id          AS id,
                               l.serviceName AS serviceName,
                               l.status      AS status,
                               l.message     AS message,
                               l.error       AS error,
                               l.timestamp   AS timestamp
                        ORDER BY l.timestamp DESC
                        LIMIT $limit
                    """
                    result = session.run(
                        query,
                        serviceName=service_name,
                        limit=limit
                    )

                return [self._record_to_dict(r) for r in result]

        except Exception as e:
            logger.error(f"Neo4j fetch_logs failed for {service_name}: {e}")
            return [{"error": str(e), "serviceName": service_name}]

    def fetch_unhealthy_logs(self, service_name: str, limit: int = 20) -> list[dict]:
        """
        Fetch only UNHEALTHY and DEGRADED log entries for a service.
        These are the entries sent to Kaii Agent when a service is down.
        """
        try:
            driver = self._get_driver()
            with driver.session() as session:
                query = """
                    MATCH (l:Log {serviceName: $serviceName})
                    WHERE l.status IN ['UNHEALTHY', 'DEGRADED']
                    RETURN l.id          AS id,
                           l.serviceName AS serviceName,
                           l.status      AS status,
                           l.message     AS message,
                           l.error       AS error,
                           l.timestamp   AS timestamp
                    ORDER BY l.timestamp DESC
                    LIMIT $limit
                """
                result = session.run(query, serviceName=service_name, limit=limit)
                return [self._record_to_dict(r) for r in result]

        except Exception as e:
            logger.error(f"Neo4j fetch_unhealthy_logs failed for {service_name}: {e}")
            return [{"error": str(e)}]

    def fetch_log_summary(self, service_name: str) -> dict:
        """
        Returns a count breakdown of log statuses for a service.
        Useful for giving Kaii Agent a quick picture before deep analysis.
        """
        try:
            driver = self._get_driver()
            with driver.session() as session:
                query = """
                    MATCH (l:Log {serviceName: $serviceName})
                    RETURN l.status AS status, count(*) AS count
                    ORDER BY count DESC
                """
                result = session.run(query, serviceName=service_name)
                summary = {row["status"]: row["count"] for row in result}
                total = sum(summary.values())
                return {
                    "serviceName": service_name,
                    "total":       total,
                    "breakdown":   summary,
                }
        except Exception as e:
            logger.error(f"Neo4j fetch_log_summary failed for {service_name}: {e}")
            return {"error": str(e)}

    def close(self):
        if self._driver:
            self._driver.close()


neo4j_client = Neo4jLogClient()

# ─────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────

def check_service_health(service_name: str) -> dict:
    """
    Calls each service's custom health endpoint which returns a plain
    string body: "HEALTHY" or "UNHEALTHY"

    e.g. GET http://localhost:8080/user/health  → "HEALTHY"
         GET http://localhost:8083/payment/health → "UNHEALTHY"
    """
    base_url     = SERVICES.get(service_name)
    health_path  = HEALTH_PATHS.get(service_name)

    if not base_url or not health_path:
        return {
            "serviceName": service_name,
            "status":      "UNKNOWN",
            "error":       f"Service '{service_name}' not configured.",
            "checked_at":  datetime.utcnow().isoformat() + "Z",
        }

    url = base_url + health_path
    try:
        resp   = requests.get(url, timeout=HEALTH_TIMEOUT)
        # Response is a plain string: "HEALTHY" or "UNHEALTHY"
        status = resp.text.strip().upper()

        # Normalise anything unexpected to UNKNOWN
        if status not in ("HEALTHY", "UNHEALTHY"):
            status = "UNKNOWN"

        return {
            "serviceName": service_name,
            "status":      status,          # HEALTHY | UNHEALTHY
            "url":         url,
            "http_code":   resp.status_code,
            "checked_at":  datetime.utcnow().isoformat() + "Z",
        }

    except requests.exceptions.ConnectionError:
        return {
            "serviceName": service_name,
            "status":      "UNHEALTHY",
            "url":         url,
            "error":       "Connection refused — service is not reachable.",
            "checked_at":  datetime.utcnow().isoformat() + "Z",
        }
    except requests.exceptions.Timeout:
        return {
            "serviceName": service_name,
            "status":      "UNHEALTHY",
            "url":         url,
            "error":       f"Timed out after {HEALTH_TIMEOUT}s.",
            "checked_at":  datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        return {
            "serviceName": service_name,
            "status":      "UNKNOWN",
            "url":         url,
            "error":       str(e),
            "checked_at":  datetime.utcnow().isoformat() + "Z",
        }


def check_all_services_health() -> list[dict]:
    return [check_service_health(name) for name in SERVICES]


# ─────────────────────────────────────────────
# KAII AGENT TRIGGER
# ─────────────────────────────────────────────

def trigger_kaii_agent(service_name: str, health_result: dict,
                        unhealthy_logs: list[dict], log_summary: dict) -> dict:
    """
    Sends unhealthy service context to Kaii Agent via REST POST.
    Kaii will analyse the logs + health data and suggest/apply a fix.

    Payload includes:
    - actuator health status (UP/DOWN) from Spring Boot
    - log_summary: count breakdown of HEALTHY/UNHEALTHY/DEGRADED from Neo4j
    - unhealthy_logs: last 20 UNHEALTHY/DEGRADED LogNode entries from Neo4j
      Each log matches your @Node("Log") model: { id, serviceName, status, message, error, timestamp }
    """
    payload = {
        "serviceName":      service_name,
        "healthStatus":     health_result.get("status"),    # HEALTHY | UNHEALTHY | UNKNOWN
        "healthUrl":        health_result.get("url"),
        "healthError":      health_result.get("error"),     # set when service is unreachable
        "log_summary":      log_summary,
        "unhealthy_logs":   unhealthy_logs,
        "requested_action": "diagnose_and_fix",
        "metadata": {
            "base_path":      os.getcwd(),
            "restart_script": RESTART_SCRIPTS.get(service_name, ""),
            "triggered_at":   datetime.utcnow().isoformat() + "Z",
        }
    }

    try:
        resp = requests.post(
            KAII_AGENT_URL,
            json=payload,
            timeout=30,
            headers={"Content-Type": "application/json"}
        )
        return {
            "kaii_status":   resp.status_code,
            "kaii_response": resp.json() if resp.headers.get(
                "content-type", "").startswith("application/json") else resp.text,
            "payload_sent":  payload,
        }
    except Exception as e:
        return {
            "kaii_status":   "ERROR",
            "error":         str(e),
            "payload_sent":  payload,
        }


# ─────────────────────────────────────────────
# RESTART SERVICE
# ─────────────────────────────────────────────

def restart_service(service_name: str) -> dict:
    """Runs the local shell restart script for the given service."""
    script = RESTART_SCRIPTS.get(service_name)
    if not script:
        return {
            "service": service_name,
            "success": False,
            "error":   f"No restart script configured for '{service_name}'."
        }

    if not os.path.isfile(script):
        return {
            "service": service_name,
            "success": False,
            "error":   f"Script not found: {script}"
        }

    try:
        result = subprocess.run(
            ["bash", script],
            capture_output=True,
            text=True,
            timeout=60
        )
        return {
            "service":     service_name,
            "success":     result.returncode == 0,
            "returncode":  result.returncode,
            "stdout":      result.stdout.strip(),
            "stderr":      result.stderr.strip(),
            "script_used": script,
        }
    except subprocess.TimeoutExpired:
        return {
            "service": service_name,
            "success": False,
            "error":   "Restart script timed out after 60 seconds."
        }
    except Exception as e:
        return {
            "service": service_name,
            "success": False,
            "error":   str(e)
        }


# ─────────────────────────────────────────────
# MCP SERVER
# ─────────────────────────────────────────────

app = Server("microservice-health-monitor")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="check_health",
            description=(
                "Check the health of one or all Spring Boot microservices. "
                "Each service exposes a custom health endpoint (e.g. /user/health) "
                "returning a plain string: HEALTHY or UNHEALTHY."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": (
                            "Name of the service to check: 'user', 'order', "
                            "'payment', 'notification'. Omit to check all."
                        ),
                        "enum": ["user", "order", "payment", "notification", "all"]
                    }
                },
                "required": []
            }
        ),

        types.Tool(
            name="fetch_logs",
            description=(
                "Fetch LogNode entries for a microservice from Neo4j. "
                "Matches your @Node(\'Log\') model: id (Long), message, status, error, timestamp, serviceName. "
                "Optionally filter by status: HEALTHY | UNHEALTHY | DEGRADED."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Service name (maps to serviceName field in LogNode).",
                        "enum": ["user", "order", "payment", "notification"]
                    },
                    "status": {
                        "type": "string",
                        "description": "Optional status filter matching LogNode.status values.",
                        "enum": ["HEALTHY", "UNHEALTHY", "DEGRADED"]
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of log entries to return (default 50).",
                        "default": 50
                    }
                },
                "required": ["service"]
            }
        ),

        types.Tool(
            name="trigger_fix",
            description=(
                "Send an unhealthy service report to the Kaii Agent via REST. "
                "Kaii will analyse health data + error logs and attempt to "
                "diagnose the issue and apply fixes to local files."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Service name to report to Kaii.",
                        "enum": ["user", "order", "payment", "notification"]
                    },
                    "auto_fetch_logs": {
                        "type": "boolean",
                        "description": (
                            "If true (default), automatically fetch error logs "
                            "from Neo4j and include them in the Kaii payload."
                        ),
                        "default": True
                    }
                },
                "required": ["service"]
            }
        ),

        types.Tool(
            name="restart_service",
            description=(
                "Run the local shell restart script for a Spring Boot microservice. "
                "Use after Kaii applies a fix, or for a quick manual restart."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Service to restart: user, order, payment, notification.",
                        "enum": ["user", "order", "payment", "notification"]
                    }
                },
                "required": ["service"]
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:

    # ── check_health ──────────────────────────────────────────────────────────
    if name == "check_health":
        service = arguments.get("service", "all")

        if service and service != "all":
            result = check_service_health(service)
        else:
            result = check_all_services_health()

        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    # ── fetch_logs ────────────────────────────────────────────────────────────
    elif name == "fetch_logs":
        service       = arguments.get("service")
        status_filter = arguments.get("status")       # HEALTHY | UNHEALTHY | DEGRADED
        limit         = arguments.get("limit", LOG_FETCH_LIMIT)

        if not service:
            return [types.TextContent(type="text",
                                      text=json.dumps({"error": "service is required"}))]

        logs    = neo4j_client.fetch_logs(service, limit=limit, status_filter=status_filter)
        summary = neo4j_client.fetch_log_summary(service)

        return [types.TextContent(type="text", text=json.dumps({
            "serviceName":   service,
            "status_filter": status_filter,
            "count":         len(logs),
            "summary":       summary,
            "logs":          logs,
        }, indent=2))]

    # ── trigger_fix ───────────────────────────────────────────────────────────
    elif name == "trigger_fix":
        service         = arguments.get("service")
        auto_fetch_logs = arguments.get("auto_fetch_logs", True)

        if not service:
            return [types.TextContent(type="text",
                                      text=json.dumps({"error": "service is required"}))]

        # 1. Get Spring Actuator health snapshot
        health = check_service_health(service)

        # 2. Fetch UNHEALTHY/DEGRADED LogNode entries + summary from Neo4j
        unhealthy_logs = []
        log_summary    = {}
        if auto_fetch_logs:
            unhealthy_logs = neo4j_client.fetch_unhealthy_logs(service, limit=20)
            log_summary    = neo4j_client.fetch_log_summary(service)

        # 3. Fire full context to Kaii Agent
        kaii_result = trigger_kaii_agent(service, health, unhealthy_logs, log_summary)

        return [types.TextContent(type="text", text=json.dumps({
            "serviceName":         service,
            "health":              health,
            "log_summary":         log_summary,
            "unhealthy_logs_sent": len(unhealthy_logs),
            "kaii_result":         kaii_result,
        }, indent=2))]

    # ── restart_service ───────────────────────────────────────────────────────
    elif name == "restart_service":
        service = arguments.get("service")

        if not service:
            return [types.TextContent(type="text",
                                      text=json.dumps({"error": "service is required"}))]

        result = restart_service(service)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    else:
        return [types.TextContent(type="text",
                                  text=json.dumps({"error": f"Unknown tool: {name}"}))]


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
