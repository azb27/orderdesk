# ADR 0002: Postgres is the only state: queue, events and media included

**Status:** accepted · **Phase:** P4 (media moved in P6)

## Context
The desk needs background work: parsing after a burst of messages lands, posting to the ERP with retries, sending replies. It needs live updates to every open console, and it needs somewhere to keep photos. The usual answers are Redis for the queue and pub/sub, plus S3 for files. That is three systems to run, back up and keep consistent, for a distributor that will see a few hundred orders a day.

## Decision
- **Job queue** in a `jobs` table. Workers claim with `FOR UPDATE SKIP LOCKED`. Failures back off exponentially (`min(300, 2^attempts)` seconds); after `max_attempts` a job is parked as `dead`. `enqueue` also sends `pg_notify` so a worker could wake early. The in-process worker polls every 0.5 s.
- **Live updates** with `LISTEN/NOTIFY`. Handlers `publish` inside their transaction, so a notification goes out only on commit. One listener per process fans out to the SSE clients, and it reconnects after a database restart.
- **Photos** in a `media` table (bytes plus content type), referenced by `messages.media_id`.
- **The mock ERP** keeps its own table in a separate `erp` schema. A unique idempotency key there makes a retried post a no-op.

## Consequences
- A restart loses nothing: queued work, dead letters and media survive it, and the job page shows the dead letters with a retry button.
- One backup covers everything, and the tests run against the same Postgres CI uses.
- `LISTEN` needs a direct connection, not PgBouncer in transaction mode. On Neon that means the non-pooled URL ([ADR 0005](0005-free-tier-deploy.md)).
- Photos in Postgres are fine at demo scale (a few hundred KB each, cleaned up after three days). At real volume they move to object storage and the table keeps the key.
- The queue is good to roughly hundreds of jobs a second, far beyond this desk. If that ever binds, it's a sign the system has a different shape.

## Alternatives considered
- **Redis + RQ/Celery:** a second stateful service and a second failure mode ("Redis lost the job"). It buys throughput this workload doesn't need.
- **WebSockets instead of SSE:** updates only flow server to client here, and SSE reconnects by itself through proxies.
