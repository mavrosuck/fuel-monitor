# Always-on Linux deployment

This deployment moves only the Orenburg MChS emergency worker. The scheduled
fuel-summary workflow and its secrets are not installed on the server.

## Server prerequisite

Use one always-on Linux VPS with a public outbound connection, one vCPU, at
least 512 MiB RAM and 2 GiB free disk. Install Docker Engine with the Compose
plugin and enable `docker.service`. Access must use an SSH key and a sudo-capable
operator; do not send passwords, bot tokens or MAX session data in chat.

The repository must be a clean checkout at:

```text
/opt/fuel-monitor-emergency/current
```

Create these root-owned private staging directories before cutover:

```text
/etc/fuel-monitor-emergency
/var/lib/fuel-monitor-emergency/state
/var/lib/fuel-monitor-emergency/session
```

Use `runtime.env.example` as the server file layout. Transfer the active local
`.local/emergency.env` over SSH so the existing `BOT_TOKEN` is never pasted or
printed, then add the four fixed server path settings from the example and set
mode `0600`. Do not start the service until the current SQLite state and MAX
session have been transferred.

The existing session has already completed an authenticated read on an Ubuntu
GitHub Actions runner, so it is not tied to Docker Desktop or macOS. It can
still expire or be revoked; the service treats that as a health failure and
does not attempt an interactive login.

## One-time cutover from the Mac

Prepare the server checkout and run `sudo deploy/emergency/manage.sh build`
first. This downloads dependencies and builds the exact commit without reading
the session or starting a monitor. The final state transfer is done only after
the local container stops, so two MAX readers never run at once.

1. Confirm the local container is healthy and record the safe counts. The
   expected starting point for this migration is four `baseline` posts and zero
   deliveries.
2. Stop `fuel-monitor-emergency` gracefully. Do not remove the container,
   volumes or local files.
3. Create a consistent SQLite copy while the container is stopped:

   ```text
   sqlite3 .local/emergency-state/alerts.sqlite3 ".backup '/private/staging/alerts.sqlite3'"
   ```

4. Transfer exactly three private files over SSH: the new SQLite copy as
   `/var/lib/fuel-monitor-emergency/state/alerts.sqlite3`, the existing
   `.local/emergency-session/max.db` as
   `/var/lib/fuel-monitor-emergency/session/max.db`, and the active
   `.local/emergency.env` as `/etc/fuel-monitor-emergency/runtime.env`. Rename
   it only at the protected server destination, then add the non-secret state,
   session and in-container path lines from `runtime.env.example`. Use a private
   staging directory and `sudo install -m 0600`; never paste or print secret
   values.
5. From the server checkout run:

   ```text
   sudo deploy/emergency/manage.sh deploy
   sudo deploy/emergency/manage.sh status
   ```

6. Leave the Mac container stopped and run `status` again after at least 90
   seconds. A later `last_poll`, healthy state, zero failures and unchanged
   baseline/delivery counts prove polling continued independently on Linux.
7. Keep all local files and the stopped local container as the rollback copy.

If server activation fails, stop the server unit and immediately restart the
unchanged Mac container. The deployment command automatically restores the
previous server image when an upgrade fails its health check.

## Upgrade and rollback

Fetch and check out the approved commit in the clean server checkout. Then run
`sudo deploy/emergency/manage.sh deploy`. The image is tagged with the exact Git
commit, the prior tag is retained, and systemd waits up to three minutes for a
healthy heartbeat. Run `sudo deploy/emergency/manage.sh rollback` to exchange
the current and previous images. Neither operation rewrites SQLite or the MAX
session.

The unit starts after Docker and network readiness, restarts the container
unless explicitly stopped, and survives host reboot. The container has no
published ports, runs as the image's unprivileged `app` user, drops all Linux
capabilities, uses a read-only root filesystem, limits CPU, memory, processes
and log growth, and stores only the session and SQLite state on private mounts.

## Recovery evidence

For each check, retain only safe output from `manage.sh status`: image revision,
container health, restart count, last-poll timestamp and duration, number of
source posts seen, consecutive failures, stored-post count and delivery count.
Never collect `docker inspect` environment output or copy the runtime/session
files into logs.
