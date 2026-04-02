#!/bin/bash
SERVICE_NAME="notification-service"
JAR_PATH="./notification-service/target/notification-service.jar"
LOG_FILE="./logs/notification-service.log"
PID_FILE="./pids/notification-service.pid"
JVM_OPTS="-Xms256m -Xmx512m"
SPRING_PROFILE="default"

mkdir -p ./logs ./pids
echo "[$(date)] Restarting $SERVICE_NAME..."

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID"; sleep 3
    fi
fi

nohup java $JVM_OPTS -Dspring.profiles.active=$SPRING_PROFILE \
    -jar "$JAR_PATH" >> "$LOG_FILE" 2>&1 &

echo $! > "$PID_FILE"
echo "[$SERVICE_NAME] Started with PID $(cat $PID_FILE)"
exit 0
