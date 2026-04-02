package com.yourorg.logging;

import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.classic.spi.IThrowableProxy;
import ch.qos.logback.core.AppenderBase;
import org.neo4j.driver.*;

import java.time.LocalDateTime;

/**
 * Neo4jLogAppender.java
 *
 * Custom Logback appender that writes each log event as a (:Log) node in Neo4j.
 * Place this class in: src/main/java/com/yourorg/logging/
 *
 * Neo4j node structure:
 *   (:Log {
 *       service:   "user",
 *       level:     "ERROR",
 *       message:   "...",
 *       timestamp: datetime(...),
 *       thread:    "http-nio-8080-exec-1",
 *       logger:    "com.yourorg.UserService",
 *       exception: "java.lang.NullPointerException: ..."   // optional
 *   })
 *
 * Add neo4j-java-driver dependency to pom.xml:
 *   <dependency>
 *       <groupId>org.neo4j.driver</groupId>
 *       <artifactId>neo4j-java-driver</artifactId>
 *       <version>5.18.0</version>
 *   </dependency>
 */
public class Neo4jLogAppender extends AppenderBase<ILoggingEvent> {

    // Configured via logback-spring.xml
    private String neo4jUri      = "bolt://localhost:7687";
    private String neo4jUser     = "neo4j";
    private String neo4jPassword = "password";
    private String serviceName   = "unknown-service";

    private Driver driver;

    @Override
    public void start() {
        try {
            driver = GraphDatabase.driver(
                neo4jUri,
                AuthTokens.basic(neo4jUser, neo4jPassword)
            );
            super.start();
        } catch (Exception e) {
            addError("Failed to connect Neo4jLogAppender to " + neo4jUri, e);
        }
    }

    @Override
    protected void append(ILoggingEvent event) {
        if (driver == null) return;

        try (Session session = driver.session()) {
            String exceptionText = null;
            IThrowableProxy throwable = event.getThrowableProxy();
            if (throwable != null) {
                exceptionText = throwable.getClassName() + ": " + throwable.getMessage();
            }

            session.run(
                "CREATE (:Log { " +
                "  service:   $service, " +
                "  level:     $level, " +
                "  message:   $message, " +
                "  timestamp: datetime($timestamp), " +
                "  thread:    $thread, " +
                "  logger:    $logger, " +
                "  exception: $exception " +
                "})",
                Values.parameters(
                    "service",   serviceName,
                    "level",     event.getLevel().toString(),
                    "message",   event.getFormattedMessage(),
                    "timestamp", LocalDateTime.now().toString(),
                    "thread",    event.getThreadName(),
                    "logger",    event.getLoggerName(),
                    "exception", exceptionText
                )
            );
        } catch (Exception e) {
            // Avoid recursive logging — just print to stderr
            System.err.println("[Neo4jLogAppender] Failed to write log: " + e.getMessage());
        }
    }

    @Override
    public void stop() {
        if (driver != null) {
            driver.close();
        }
        super.stop();
    }

    // ── Setters (called by Logback XML config) ────────────────────────────
    public void setNeo4jUri(String neo4jUri)           { this.neo4jUri = neo4jUri; }
    public void setNeo4jUser(String neo4jUser)         { this.neo4jUser = neo4jUser; }
    public void setNeo4jPassword(String neo4jPassword) { this.neo4jPassword = neo4jPassword; }
    public void setServiceName(String serviceName)     { this.serviceName = serviceName; }
}
