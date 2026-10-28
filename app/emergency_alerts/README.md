# Emergency alerts (gated independent service)

## Verified boundary, 2026-10-28

The emergency worker is independent from the two-hour fuel-summary runner. It
reads only the official public MAX channel `https://max.ru/id5610084427_gos`
through an existing personal `pymax.WebClient` session and can deliver only to
Telegram `@benzinoren`. It contains no MAX send, reaction, comment, join,
subscription or settings operation.

The user reports that MAX has consented to this automated personal-session read.
That consent remains an operator-controlled prerequisite. Before network or
storage access, production requires all three flags to equal `true`:
`EMERGENCY_ENABLED`, `EMERGENCY_MAX_PERMISSION_CONFIRMED`, and
`EMERGENCY_SOURCE_VERIFIED`.

An authorized live check confirmed one matching chat:

- channel ID: `-69537682153611`;
- type: `CHANNEL`;
- title: `МЧС Оренбургской области`;
- public link: `https://max.ru/id5610084427_gos`.

The pinned ID, type and exact public link are rechecked whenever the service
connects. The personal WebClient message model does not expose the bot API's
optional public post URL. Guessed `/<message_id>` links return HTTP 404, so the
service never constructs them. Telegram alerts preserve the original MAX
message ID, timestamp, full text and the verified channel URL.

## Read-only MAX access

`AuthorizedMaxSession` accepts only the pinned channel ID and a private regular
session file that is not a symlink and has no group or other permissions. Login
is noninteractive and fails closed if the saved session expires. Normal
`connect()` synchronization may include chats, contacts and messages as accepted
by the user, but this package requests, processes and persists history only for
the verified MChS channel.

`PreparedMaxReader` reads bounded pages, deduplicates overlapping IDs and moves
the next cursor one millisecond before the oldest item. A stalled cursor or the
ten-page safety limit fails closed. Give the emergency service its own private
copy of the session file; never point two local processes at the same database.
The manual `Emergency MAX read-only dry run` workflow uses a separate restored
copy and serializes with the fuel workflow.

Run the isolated source check with:

```text
python -m app.emergency_alerts max-dry-run
```

It prints only MAX post IDs, timestamps, short safe excerpts and aggregate
counts. It uses temporary SQLite state and a no-network preview sender, never
constructs Telegram and never changes production delivery state. A live run read
20 official posts, matched two old real closure/cancellation notices, produced
zero fresh previews and sent nothing.

## Filtering and delivery safety

Eligible notices are limited to Orenburg road closures, restrictions and
reopenings; UAV, air and missile threats and cancellations; Kover introduction
or removal; and directly related civilian safety instructions. Weather alone,
general news, exercises, speculation and operational military details are
rejected. The production service uses the complete original text without an
external AI rewrite.

Posts older than 15 minutes are never sent, including reopenings and all-clear
messages. Freshness is checked again immediately before delivery. On the first
successful source read, the worker transactionally records matching existing
posts as a baseline without creating deliveries. Only later observations can be
sent, preventing an initial backfill burst.

SQLite WAL and `FULL` synchronous mode preserve post revisions, detection times,
delivery claims, Telegram message IDs and heartbeat state. Duplicate claims are
transactionally blocked. A send with an uncertain result remains `claimed` for
manual reconciliation and is not retried blindly. Edits and verified removals
enter review states.

Before any send, the Telegram adapter confirms that the existing bot is an
administrator of exactly `@benzinoren` and has posting rights. The manual
`Emergency Telegram preflight` workflow performs only identity, chat and rights
requests; it never calls `send_message`.

## Deployment

`compose.emergency.yml` is a separate opt-in service and does not start with the
fuel compose file. Its private mode-0600 `.env.emergency` must provide:

```text
EMERGENCY_ENABLED=true
EMERGENCY_MAX_PERMISSION_CONFIRMED=true
EMERGENCY_SOURCE_VERIFIED=true
EMERGENCY_MAX_CHANNEL_ID=-69537682153611
BOT_TOKEN=<secret from the existing secret manager>
EMERGENCY_STATE_DIR=<private durable directory>
EMERGENCY_SESSION_DIR=<private directory containing max.db>
```

Validate it with `docker compose --env-file .env.emergency -f compose.emergency.yml config --quiet`, then use the corresponding `up -d` command.

Never place the token or session in source control, command arguments or logs.
The state and session directories must be private and writable by the container's
`app` user. The service polls every 30 seconds by default, accepts only 10..300
seconds, backs off up to five minutes after repeated failures, restarts unless
stopped and exposes a local health check. Monitor that health status and back up
SQLite consistently with its WAL.

Run `python -m app.emergency_alerts telegram-preflight`, `max-dry-run`, and
`store-check` on the target environment before setting all activation gates.
The first production start intentionally establishes a no-send baseline. Keep
the existing fuel workflow and its two-hour publication behavior unchanged.
