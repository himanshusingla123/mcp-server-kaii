# MCP Microservice Health Monitor

Monitors 4 Spring Boot microservices, fetches logs from Neo4j,
and bridges unhealthy services to your **Kaii Agent** for auto-fix.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     MCP Server (Python)                  │
│                                                          │
│  check_health   ──► /actuator/health  (each service)    │
│  fetch_logs     ──► Neo4j bolt://localhost:7687          │
│  trigger_fix    ──► Kaii Agent REST API                  │
│  restart_service──► ./scripts/restart_<service>.sh       │
└─────────────────────────────────────────────────────────┘
         ▲
   Kaii Agent calls these tools
```

---

## Services Monitored

| Service      | Port | Health URL                              |
|--------------|------|-----------------------------------------|
| user         | 8080 | http://localhost:8080/actuator/health   |
| order        | 8082 | http://localhost:8082/actuator/health   |
| payment      | 8083 | http://localhost:8083/actuator/health   |
| notification | 8084 | http://localhost:8084/actuator/health   |

---

## Setup

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 2. Set environment variables
```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=your_password

# Your Kaii Agent REST endpoint
export KAII_AGENT_URL=http://localhost:9000/kaii/analyze
```

### 3. Make restart scripts executable
```bash
chmod +x scripts/restart_*.sh
```

### 4. Run the MCP server
```bash
python server.py
```

---

## Connecting to Kaii Agent

Add this to your Kaii Agent's MCP client config (claude_desktop_config.json or equivalent):

```json
{
  "mcpServers": {
    "microservice-monitor": {
      "command": "python",
      "args": ["/path/to/mcp_server/server.py"],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "your_password",
        "KAII_AGENT_URL": "http://localhost:9000/kaii/analyze"
      }
    }
  }
}
```

---

## Spring Boot Integration

### Step 1: Add Neo4j Logback Appender to each service

Copy `config/Neo4jLogAppender.java` into:
```
src/main/java/com/yourorg/logging/Neo4jLogAppender.java
```

Copy `config/logback-spring.xml` into:
```
src/main/resources/logback-spring.xml
```

### Step 2: Add to pom.xml
```xml
<dependency>
    <groupId>org.neo4j.driver</groupId>
    <artifactId>neo4j-java-driver</artifactId>
    <version>5.18.0</version>
</dependency>
```

### Step 3: Enable Spring Actuator in application.properties
```properties
management.endpoints.web.exposure.include=health,info
management.endpoint.health.show-details=always
```

---

## MCP Tools Reference

### `check_health`
```json
{ "service": "payment" }          // single service
{ "service": "all" }              // all 4 services
```

### `fetch_logs`
```json
{ "service": "order", "level": "ERROR", "limit": 20 }
```

### `trigger_fix`
```json
{ "service": "payment", "auto_fetch_logs": true }
```
Sends to Kaii: service name, health snapshot, last 20 ERROR/FATAL logs.

### `restart_service`
```json
{ "service": "user" }
```
Runs `./scripts/restart_user.sh`.

---

## Kaii Agent Payload Shape

```json
{
  "service": "payment",
  "status": "DOWN",
  "health_details": { ... },
  "error": "Connection refused",
  "error_logs": [
    {
      "level": "ERROR",
      "message": "...",
      "timestamp": "2025-01-01T10:00:00",
      "exception": "java.lang.NullPointerException: ..."
    }
  ],
  "requested_action": "diagnose_and_fix",
  "metadata": {
    "base_path": "/home/user/project",
    "restart_script": "./scripts/restart_payment.sh",
    "triggered_at": "2025-01-01T10:00:05Z"
  }
}
```

Adjust field names in `trigger_kaii_agent()` in `server.py` to match
your Kaii Agent's actual API contract.

---

## Neo4j Log Node Schema

```cypher
(:Log {
    service:   "payment",
    level:     "ERROR",
    message:   "Database connection pool exhausted",
    timestamp: datetime("2025-01-01T10:00:00"),
    thread:    "http-nio-8083-exec-3",
    logger:    "com.yourorg.PaymentService",
    exception: "java.sql.SQLException: No available connections"
})
```

Useful Cypher queries:
```cypher
-- Recent errors for payment service
MATCH (l:Log {service: "payment", level: "ERROR"})
RETURN l ORDER BY l.timestamp DESC LIMIT 20;

-- All services error count today
MATCH (l:Log) WHERE l.level IN ['ERROR','FATAL']
RETURN l.service, count(*) AS errors ORDER BY errors DESC;
```
