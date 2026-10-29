#!/usr/bin/env bash
set -Eeuo pipefail

project_dir=/opt/fuel-monitor-emergency/current
config_dir=/etc/fuel-monitor-emergency
data_dir=/var/lib/fuel-monitor-emergency
runtime_env="$config_dir/runtime.env"
image_env="$config_dir/image.env"
previous_image_file="$data_dir/previous-image"
unit_source="$project_dir/deploy/emergency/fuel-monitor-emergency.service"
unit_target=/etc/systemd/system/fuel-monitor-emergency.service

fail() {
  echo "$*" >&2
  exit 1
}

require_root() {
  (( EUID == 0 )) || fail "run this command as root"
}

setting() {
  local key="$1"
  awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "$runtime_env"
}

assert_private_file() {
  local path="$1"
  [[ -f "$path" && ! -L "$path" ]] || fail "required private file is missing: $path"
  [[ "$(stat -c '%a' "$path")" == "600" ]] || fail "private file must have mode 0600: $path"
}

validate_layout() {
  [[ -d "$project_dir/.git" ]] || fail "repository is not installed at $project_dir"
  assert_private_file "$runtime_env"
  for key in EMERGENCY_ENABLED EMERGENCY_MAX_PERMISSION_CONFIRMED EMERGENCY_SOURCE_VERIFIED EMERGENCY_MAX_CHANNEL_ID EMERGENCY_STATE_DIR EMERGENCY_SESSION_DIR EMERGENCY_SQLITE_PATH MAX_SESSION_PATH BOT_TOKEN; do
    grep -q "^${key}=." "$runtime_env" || fail "runtime.env is missing $key"
  done
  [[ "$(setting EMERGENCY_ENABLED)" == "true" ]] || fail "EMERGENCY_ENABLED must be true"
  [[ "$(setting EMERGENCY_MAX_PERMISSION_CONFIRMED)" == "true" ]] || fail "MAX permission gate must be true"
  [[ "$(setting EMERGENCY_SOURCE_VERIFIED)" == "true" ]] || fail "source verification gate must be true"
  [[ "$(setting EMERGENCY_MAX_CHANNEL_ID)" == "-69537682153611" ]] || fail "unexpected emergency source ID"
  [[ "$(setting BOT_TOKEN)" != "replace-through-secure-transfer-only" ]] || fail "BOT_TOKEN placeholder must be replaced securely"
  [[ "$(setting EMERGENCY_STATE_DIR)" == "$data_dir/state" ]] || fail "state directory must be $data_dir/state"
  [[ "$(setting EMERGENCY_SESSION_DIR)" == "$data_dir/session" ]] || fail "session directory must be $data_dir/session"
  assert_private_file "$data_dir/session/max.db"
  assert_private_file "$data_dir/state/alerts.sqlite3"
}

write_image_env() {
  local image="$1"
  local temporary
  temporary="$(mktemp "$config_dir/image.env.XXXXXX")"
  printf 'EMERGENCY_IMAGE=%s\n' "$image" >"$temporary"
  chmod 0644 "$temporary"
  mv -f "$temporary" "$image_env"
}

compose() {
  EMERGENCY_ENV_FILE="$runtime_env" docker compose \
    --project-name fuel-monitor-emergency \
    --env-file "$image_env" \
    --env-file "$runtime_env" \
    -f "$project_dir/compose.emergency.yml" "$@"
}

prepare_ownership() {
  local image="$1"
  local app_uid app_gid
  app_uid="$(docker run --rm --network none --entrypoint id "$image" -u app)"
  app_gid="$(docker run --rm --network none --entrypoint id "$image" -g app)"
  chown -R "$app_uid:$app_gid" "$data_dir/state" "$data_dir/session"
  chmod 0700 "$data_dir" "$data_dir/state" "$data_dir/session"
  chmod 0600 "$data_dir/state/alerts.sqlite3" "$data_dir/session/max.db"
}

install_unit() {
  install -m 0644 "$unit_source" "$unit_target"
  systemctl daemon-reload
  systemctl enable fuel-monitor-emergency.service >/dev/null
}

image_for_revision() {
  local revision
  revision="$(git -C "$project_dir" rev-parse --verify HEAD)"
  printf 'fuel-monitor-emergency:%s\n' "${revision:0:12}"
}

build() {
  require_root
  [[ -d "$project_dir/.git" ]] || fail "repository is not installed at $project_dir"
  [[ -z "$(git -C "$project_dir" status --porcelain)" ]] || fail "server checkout must be clean"
  local revision image
  revision="$(git -C "$project_dir" rev-parse --verify HEAD)"
  image="$(image_for_revision)"
  docker build --pull --label "org.opencontainers.image.revision=$revision" -t "$image" "$project_dir"
  docker image inspect --format 'built={{.RepoTags}} size={{.Size}}' "$image"
}

deploy() {
  require_root
  validate_layout
  [[ -z "$(git -C "$project_dir" status --porcelain)" ]] || fail "server checkout must be clean"
  local image previous
  image="$(image_for_revision)"
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    build
  fi
  prepare_ownership "$image"
  previous=""
  if [[ -f "$image_env" ]]; then
    previous="$(awk -F= '$1 == "EMERGENCY_IMAGE" {print $2}' "$image_env")"
  fi
  write_image_env "$image"
  compose config --quiet
  install_unit
  if ! systemctl restart fuel-monitor-emergency.service; then
    if [[ -n "$previous" && "$previous" != "$image" ]]; then
      write_image_env "$previous"
      systemctl restart fuel-monitor-emergency.service || true
    else
      systemctl stop fuel-monitor-emergency.service || true
    fi
    fail "deployment failed; previous image was restored when available"
  fi
  if [[ -n "$previous" && "$previous" != "$image" ]]; then
    printf '%s\n' "$previous" >"$previous_image_file"
    chmod 0600 "$previous_image_file"
  fi
  status
}

rollback() {
  require_root
  validate_layout
  [[ -f "$previous_image_file" ]] || fail "no previous image is recorded"
  local previous current
  previous="$(<"$previous_image_file")"
  docker image inspect "$previous" >/dev/null
  current="$(awk -F= '$1 == "EMERGENCY_IMAGE" {print $2}' "$image_env")"
  write_image_env "$previous"
  if ! systemctl restart fuel-monitor-emergency.service; then
    write_image_env "$current"
    systemctl restart fuel-monitor-emergency.service || true
    fail "rollback image did not become healthy; current image was restored"
  fi
  printf '%s\n' "$current" >"$previous_image_file"
  chmod 0600 "$previous_image_file"
  status
}

status() {
  require_root
  local container_id
  systemctl is-active --quiet fuel-monitor-emergency.service || fail "systemd service is not active"
  container_id="$(docker ps -q \
    --filter label=com.docker.compose.project=fuel-monitor-emergency \
    --filter label=com.docker.compose.service=emergency | head -n 1)"
  [[ -n "$container_id" ]] || fail "emergency container is not running"
  docker inspect --format 'container={{.Name}} state={{.State.Status}} health={{.State.Health.Status}} started={{.State.StartedAt}} restarts={{.RestartCount}} image={{.Config.Image}}' "$container_id"
  docker exec "$container_id" python -m app.emergency_alerts health
  docker exec "$container_id" python -c 'import os, sqlite3; db=sqlite3.connect(os.environ["EMERGENCY_SQLITE_PATH"]); values=dict(db.execute("SELECT key, value FROM service_state")); print("last_poll=" + values.get("last_poll_completed_at", "unknown"), "duration_ms=" + values.get("last_poll_duration_ms", "unknown"), "posts=" + values.get("last_poll_post_count", "unknown"), "failures=" + values.get("consecutive_poll_failures", "unknown")); print("stored_posts=" + str(db.execute("SELECT COUNT(*) FROM posts").fetchone()[0]), "deliveries=" + str(db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]))'
}

usage() {
  echo "usage: $0 build|deploy|rollback|status" >&2
  exit 2
}

case "${1:-}" in
  build) build ;;
  deploy) deploy ;;
  rollback) rollback ;;
  status) status ;;
  *) usage ;;
esac
