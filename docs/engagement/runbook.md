# Runbook: running the order desk

*For Saffron Lane's IT admin and the desk lead (fictional). It covers the deployed service as built. Hosting setup is in [`docs/deploy.md`](../deploy.md).*

## What's running

There is one container: the web console, the API, the job worker, and live updates, plus a Postgres database. Postgres holds everything: orders, messages, photos, the job queue and the audit log. Restarting the container loses nothing.

| Piece | Where to look |
|---|---|
| Is it up? | `GET /healthz` returns `{"ok": true, "queued_jobs": n, "model": ..., "llm": true}` |
| Today's numbers | The **Jobs** page in the console (from `GET /api/stats`): orders by status over 24 h, dead jobs, average seconds from opening an order to confirming it, model spend today against the budget |
| Stuck work | The **Jobs** page lists dead jobs with their last error. A supervisor can retry one |
| Who did what | Each order's history panel (from `GET /api/audit`): every edit (with before and after), confirmation, rejection and ERP post. Taught names are logged separately, under `entity=alias` |
| Logs | The host's log stream (Render: the service's Logs tab) |

## Daily

- **08:30:** open the Jobs page. Dead jobs should be 0, and model spend should be near zero at the start of the day.
- **15:30:** check the **To check** queue. Anything still there at 15:45 is at risk for the 16:00 cut-off. Tell the desk lead.
- **After 16:00:** the **ERP failed** tab should be empty. Any order there didn't reach the warehouse.

## When something goes wrong

### Orders aren't appearing

1. Check `/healthz`. No answer means the service is down. Restart it from the host's dashboard; migrations and start-up take about a minute.
2. Check `queued_jobs` on `/healthz`.
   - Rising: the worker is stuck. Restart the service. Queued jobs are in Postgres and resume.
   - Zero, but no new orders: the webhook isn't receiving.
3. If the webhook isn't receiving, look for `401` responses on `POST /webhooks/whatsapp` in the logs. That means the signature check is failing: `WHATSAPP_APP_SECRET` doesn't match the Meta app secret. Fix the variable and restart. **Never disable the check.** Unsigned requests are rejected by design.

### Drafts say "Read by the fallback parser"

The model wasn't used. There are two reasons:

1. **The daily budget is spent:** the Jobs page shows spend ≥ budget. Drafts carry on with fuzzy matching, which is less accurate (see the eval). Raise `LLM_DAILY_BUDGET_USD` if the volume is real, and check the order count first. An unexpected jump in volume can mean a loop or abuse.
2. **The API is failing:** the logs show Anthropic errors. Fuzzy matching covers it automatically. Check the provider's status page. Nothing to do at the desk except read drafts more carefully: every line is tinted for checking.

### An order shows "ERP failed"

- **The ERP refused it** (a 4xx; the reason is in the order's history): retrying won't help, so the job goes straight to the Jobs page. Fix the cause in the ERP, usually a SKU or customer that isn't set up or is blocked. Then a supervisor retries the job.
- **The ERP was down** (5xx or timeouts): the post retried with backoff, five attempts in all, and then went to the Jobs page. When the ERP is back, a supervisor retries the job. The idempotency key `orderdesk:<order ref>` means a retry never books the order twice. That holds even if the first attempt reached the ERP and only the response was lost.

### A retailer says their order was wrong

1. Find the order by customer in **In ERP**. Open its history: the message, the draft, every edit, who confirmed it.
2. Classify the error with the same words the eval uses: wrong product, size, unit or number, a missed line, or an extra line.
3. If it was a name the system didn't know, teach it (the "teach this name" link on the line). If it was a pattern, log it for the weekly eval re-run.

### Something looks like a security problem

- **Repeated `401`s on the webhook from unknown addresses:** that is someone probing. The signature check rejects them, and nothing else is needed.
- **A leaked secret:**
  - `SECRET_KEY`: rotating it signs everyone out.
  - `WHATSAPP_APP_SECRET`: rotate it in Meta and here together.
  - Anthropic key: revoke it in the console, then set the new one.

  Record what happened and when.

## Changes

- **Catalogue, prices, customers:** come from the ERP sync. After a large change (new pack sizes, a new brand), re-run the eval before trusting the confidence tints.
- **Model or prompt changes:** only with an eval run on the current week's traffic, compared in the results file. Never change the model ID in production without one.
- **Database restore:** use the provider's point-in-time restore. Orders are financial records, so production needs a plan with point-in-time recovery (the free tier used for the demo is not one).

## Who to call

| Problem | Owner |
|---|---|
| The console, drafts, the job queue | Orderdesk support (the engagement team, then the client's IT after handover) |
| ERP rejects or is down | ERP vendor / IT admin |
| WhatsApp numbers, Meta app | IT admin |
| Credit holds and limits | Credit controller |
