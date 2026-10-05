# ADR 0005: Public demo on Render + Neon free tiers, with a budget-capped model

**Status:** accepted · **Phase:** P6

## Context
The demo must stay up for months at no cost, survive restarts, and not let a stranger run up the Anthropic bill. It has one web process with an in-process worker, needs Postgres with `LISTEN`, and stores photos.

## Decision
- **Render free web service** builds the repo's `Dockerfile` from `render.yaml`. It sleeps after 15 idle minutes, wakes in about a minute, and has 750 instance hours a month.
- **Neon free Postgres** in Frankfurt, next to the Render service. Use the **direct** connection string, because `LISTEN` doesn't work through the pooler. Neon scales to zero when Render does, because the worker's polling is the only traffic.
- **Throwaway container disk:** nothing is written to it except the LLM response cache. Photos are in Postgres ([ADR 0002](0002-postgres-is-the-only-state.md)).
- The entrypoint runs migrations, seeds only an empty database, then serves.
- **Guards:**
  - a daily model budget (`LLM_DAILY_BUDGET_USD`, $0.50), summed from the parse cost stored on each order;
  - a per-IP rate limit on the simulator, keyed on the address Render's proxy appended;
  - a spend-limited Anthropic workspace as the backstop.
- When the budget is spent, parsing falls back to fuzzy matching and the draft says so. This replaces the "replay mode" in the original SPEC: a fallback shows how the product degrades, a replay would only show a recording.
- Visitor data older than three days is deleted at start-up, and the seeded history stays.
- CI runs the Playwright tests against this image, and checks that the image contains no eval data or ground truth.

## Consequences
- Cold starts are visible: the README says so.
- The demo password is public, on purpose: the login page has one-click demo buttons. Everything a visitor can do is bounded by the guards above, and the mock ERP answers only loopback.
- Moving to paid hosting changes `DATABASE_URL` and the plan line, nothing else.

## Alternatives considered
- **Hugging Face Spaces** (used for Stockroom): no managed Postgres, and the Space's disk resets, so the queue and orders would need an external database anyway.
- **Fly.io:** new accounts no longer get a free allowance.
- **Supabase free Postgres:** pauses after a week of inactivity and needs a manual restore. Neon resumes on the next connection.
