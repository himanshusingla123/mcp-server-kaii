#!/bin/bash
# Restart script for USER service (port 8080)
# Adjust JAR path and JVM options to match your project layout

SERVICE_NAME="user-service"
JAR_PATH="./user-service/target/user-service.jar"
LOG_FILE="./logs/user-service.log"
PID_FILE="./pids/user-service.pid"
JVM_OPTS="-Xms256m -Xmx512m"
SPRING_PROFILE="default"

mkdir -p ./logs ./pids

echo "[$(date)] Restarting $SERVICE_NAME..."

# Kill existing process if running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping PID $OLD_PID..."
        kill "$OLD_PID"
        sleep 3
    fi
fi

# Start service
nohup java $JVM_OPTS \
    -Dspring.profiles.active=$SPRING_PROFILE \
    -jar "$JAR_PATH" \
    >> "$LOG_FILE" 2>&1 &

NEW_PID=$!
echo $NEW_PID > "$PID_FILE"
echo "[$SERVICE_NAME] Started with PID $NEW_PID"
exit 0
