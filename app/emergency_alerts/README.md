# Emergency alerts (disabled by default)

## Prepared service, 2026-10-28

`python -m app.emergency_alerts run` now wires the independent reader, original-text
rewriter, Telegram sender and durable SQLite worker. Before any network or storage
operation it requires all three flags to equal `true`: `EMERGENCY_ENABLED`,
`EMERGENCY_MAX_PERMISSION_CONFIRMED`, and `EMERGENCY_SOURCE_VERIFIED`.
The last flag attests that an authorized live dry run has verified the channel ID,
metadata, actual timestamp and canonical public post URL. It is not evidence of
platform permission by itself. None of these prerequisites has been established
by offline tests. Do not set the flags merely on account-owner consent.

The deployed service uses the complete original text instead of an external AI
rewrite; this preserves qualifications and negation without sending content to
another service. Gemini remains available only to explicit library callers.
The supported API was inspected locally in `maxapi-python==2.4.1`:
`WebClient.fetch_history(chat_id, backward, from_time, get_chat, interactive)`.
Its history parser leaves optional `Message.chat_id` unset. Only responses to the
explicit verified-channel request inherit that ID; an explicitly different ID
is rejected. Pages overlap by timestamp and are deduplicated. A stalled cursor or
ten-page limit fails closed rather than claiming complete coverage. Metadata
`Chat.link` is described by pymax as an invite link, so its equivalence to the
required public channel URL still needs live verification. No ID is inferred
from the public handle, and no account-wide discovery request is performed.

`compose.emergency.yml` is a separate opt-in deployment manifest. Its three gates
are hard-coded false, including when an environment file contains true values.
It does not start with the fuel compose file and has no restart loop while gated.
The target host must provision private durable state and session directories,
writable by the image's `app` user, and a mode-0600 `.env.emergency` containing
the existing `BOT_TOKEN` and verified `EMERGENCY_MAX_CHANNEL_ID`. The session
directory must contain the existing `max.db`; pymax needs filesystem write access
for local session bookkeeping, which does not authorize MAX account mutations.
Avoid simultaneous processes using the same session file. Never put credentials
in command arguments or commit the environment/session files.

After permission and live verification, a reviewed deployment override may enable
the three flags and a restart policy. Default polling is 30 seconds, with a
10..300-second configuration range subject to the actual permitted rate. Reads
and processing have 30-second timeouts; repeated errors back off up to five
minutes. Real detection latency is not measured yet. SIGTERM stops polling and
closes resources. SQLite WAL, delivery claims and freshness checks survive
restarts; uncertain sends remain claimed for manual reconciliation.

`python -m app.emergency_alerts health` reads the persistent database without
creating one and fails for a missing/error heartbeat, heartbeat older than 120
seconds (or twice the configured polling interval plus 60 seconds, if larger),
pending/uncertain deliveries or edit/removal review items.
Docker health status is local monitoring, not an external notification system.
An operator must monitor it and take consistent SQLite backups. Missing posts
in a bounded history page are not treated as deletions; `record_removal` requires
an explicit verified deletion event. Historical edits outside the fresh window
are not guaranteed to be observed by polling.

MAX terms checked on 2026-10-28: https://legal.max.ru/ps sections 4.3.7
(special permission for automated collection), 4.3.10 (provided interface),
and 4.4 (software integration restrictions). There is no confirmed permission
for this personal-session integration. Deployment of disabled code does not
establish permission, live channel identity, or operational monitoring.

The manual `Emergency offline verification` workflow runs the full tests, builds
the image, and verifies the disabled gate with container networking disabled.
It receives no secrets. This is a build/preflight deployment check, not an
always-on production deployment. The separate Telegram preflight uses the
existing bot secret only for identity and posting-rights verification.

This package is isolated from the fuel summary runner and workflow. It makes no MAX or Telegram requests unless a caller explicitly constructs a reader, rewriter, sender and worker. The only accepted source is `https://max.ru/id5610084427_gos`; the only destination is `@benzinoren`. It can use the existing fuel-summary bot token from `BOT_TOKEN`. No MAX send, reaction, join or subscription operation is present.

`AuthorizedMaxSession` reuses the saved personal `pymax.WebClient` session with the same noninteractive login policy as fuel collection. It requires an explicit permission gate, a supplied channel ID, and a MAX channel object whose type and public link match the official MChS URL. `PreparedMaxReader` then requests history only for that ID. Normal `connect()` may incidentally synchronize available chats, messages, and contacts; this module does not enumerate, inspect, or store them. The channel ID, post link format, channel metadata behavior, and MAX permission have not been verified in a live session. The connector is wired only to the separately gated emergency service.

`EmergencyPipeline` filters eligible posts, asks Gemini for a short rewrite, validates numbers, named places, status words and source vocabulary, and includes the complete original text and public source link in the Telegram message. Rejected or unavailable Gemini output falls back to the unmodified original, so a rewrite failure does not suppress a fresh official alert. The SQLite store persists message IDs, revisions, detection and send timestamps, and a single destination. Repeated polls after a pre-send error can retry. A send that might have succeeded remains `claimed` and requires manual reconciliation before retry; automatic resend could duplicate an alert. Edited or removed posts also require review. Posts older than 15 minutes are not sent, including after restarts. Before the first send, the Telegram adapter verifies the chat username and the existing bot's posting rights. Emergency alerts retain their own state and do not call the fuel-summary runner.

To activate after authorization, provide a verified channel ID and post link mapping, the existing `BOT_TOKEN`, and a durable SQLite path. Run the worker as its own service, with independent monitoring and state backups. Keep the fuel summary workflow unchanged. Verify the sole destination with a safe bot identity and chat check before enabling real sends. No real MAX read or Telegram publication has been performed for this package.

## Safe preparation

Use the existing fuel-summary `BOT_TOKEN` secret. Do not put the token in source control, command arguments, or chat. The separate manual `Emergency Telegram preflight` workflow uses this existing GitHub Actions secret and has read-only repository permissions. It never calls `send_message`. The fuel-summary schedule and workflow remain unchanged. A future always-on host must receive the same token through its secret manager or a private environment file; an Actions secret is available only inside Actions jobs.

Run `python -m app.emergency_alerts telegram-preflight` in an environment with `BOT_TOKEN`, or dispatch the manual `Emergency Telegram preflight` workflow. This makes only Telegram identity, chat, and administrator-rights requests; it does not call `send_message`. It verifies that the destination is a channel named `@benzinoren` and pins its numeric chat ID for subsequent sends.

Set `EMERGENCY_SQLITE_PATH` to an absolute path on a persistent, backed-up disk (for example `/var/lib/fuel-monitor-emergency/alerts.sqlite3`). Run `python -m app.emergency_alerts store-check` on the intended host. The store rejects relative paths, in-memory databases, symlinks, and database files readable by other users. It uses SQLite WAL and full synchronous durability. Back up the database and its WAL state consistently; do not place it in an ephemeral Actions workspace. Preserve the same path across service restarts. The polling worker accepts a stop event and propagates cancellation, so a dedicated service can stop it cleanly.

MAX's current user agreement section 4.3.7 requires special permission for automated collection. The user's acceptance of incidental login synchronization does not grant that permission. After written permission is confirmed and the exact channel ID is established through an authorized method, set `EMERGENCY_MAX_PERMISSION_CONFIRMED=true`, `EMERGENCY_MAX_CHANNEL_ID` to that ID, and `MAX_SESSION_PATH` to the existing saved session. Run `python -m app.emergency_alerts max-dry-run` first. It checks the channel identity, reads history in pages of 20 up to the freshness boundary, and runs the full pipeline against a no-network preview sender and temporary SQLite database. It prints only counts, never sends to Telegram, and never changes production delivery state. If metadata or history coverage cannot be verified, it fails closed. Independently confirm a real post's timestamp and canonical public URL before any live publication. No RSS, other account, or alternative feed is an acceptable substitute.
