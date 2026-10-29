#!/usr/bin/env bash
set -Eeuo pipefail

timeout_seconds="${1:-180}"
if [[ ! "$timeout_seconds" =~ ^[0-9]+$ ]] || (( timeout_seconds < 1 || timeout_seconds > 600 )); then
  echo "health timeout must be 1..600 seconds" >&2
  exit 2
fi

deadline=$((SECONDS + timeout_seconds))
while (( SECONDS < deadline )); do
  container_id="$(docker ps -aq \
    --filter label=com.docker.compose.project=fuel-monitor-emergency \
    --filter label=com.docker.compose.service=emergency | head -n 1)"
  if [[ -n "$container_id" ]]; then
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container_id")"
    if [[ "$health" == "healthy" ]]; then
      exit 0
    fi
    if [[ "$health" == "unhealthy" ]]; then
      echo "emergency container became unhealthy" >&2
      exit 1
    fi
  fi
  sleep 5
done

echo "emergency container did not become healthy within ${timeout_seconds}s" >&2
exit 1
