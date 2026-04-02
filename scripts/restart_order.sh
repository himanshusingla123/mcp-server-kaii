#!/bin/bash
SERVICE_NAME="order-service"
JAR_PATH="./order-service/target/order-service.jar"
LOG_FILE="./logs/order-service.log"
PID_FILE="./pids/order-service.pid"
JVM_OPTS="-Xms256m -Xmx512m"
SPRING_PROFILE="default"

mkdir -p ./logs ./pids
echo "[$(date)] Restarting $SERVICE_NAME..."

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping PID $OLD_PID..."
        kill "$OLD_PID"
        sleep 3
    fi
fi

nohup java $JVM_OPTS \
    -Dspring.profiles.active=$SPRING_PROFILE \
    -jar "$JAR_PATH" \
    >> "$LOG_FILE" 2>&1 &

NEW_PID=$!
echo $NEW_PID > "$PID_FILE"
echo "[$SERVICE_NAME] Started with PID $NEW_PID"
exit 0
