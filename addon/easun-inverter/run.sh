#!/usr/bin/with-contenv bashio
set -euo pipefail

# Wait for MQTT service if available
if command -v bashio::services.wait &> /dev/null; then
  bashio::log.info "⏳ Waiting for MQTT service..."
  bashio::services.wait "mqtt" || true
fi

# Auto-discover MQTT credentials
if command -v bashio::services.available &> /dev/null && bashio::services.available "mqtt"; then
  MQTT_HOST_DISC=$(bashio::services "mqtt" "host" || echo "")
  MQTT_PORT_DISC=$(bashio::services "mqtt" "port" || echo "")
  MQTT_USER_DISC=$(bashio::services "mqtt" "username" || echo "")
  MQTT_PASS_DISC=$(bashio::services "mqtt" "password" || echo "")
  [ -n "${MQTT_HOST_DISC}" ] && export MQTT_HOST="${MQTT_HOST_DISC}"
  [ -n "${MQTT_PORT_DISC}" ] && export MQTT_PORT="${MQTT_PORT_DISC}"
  [ -n "${MQTT_USER_DISC}" ] && export MQTT_USERNAME="${MQTT_USER_DISC}"
  [ -n "${MQTT_PASS_DISC}" ] && export MQTT_PASSWORD="${MQTT_PASS_DISC}"
  bashio::log.info "📡 MQTT credentials obtained via Supervisor."
else
  bashio::log.info "ℹ️ No MQTT discovery; using manual options if provided."
fi

cd /app
exec python3 main.py
