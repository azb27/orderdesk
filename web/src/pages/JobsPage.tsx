import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import type { Me } from "../lib/types";
import { api } from "../lib/api";
import Topbar from "../components/Topbar";
import { useLiveUpdates } from "../lib/hooks";
import "./JobsPage.css";

const KIND: Record<string, string> = { parse: "Reading a conversation", post_erp: "Posting an order to the ERP", send_reply: "Sending a WhatsApp reply" };

export default function JobsPage({ me }: { me: Me }) {
  const qc = useQueryClient();
  const live = useLiveUpdates(true);
  const dead = useQuery({ queryKey: ["dead-jobs"], queryFn: api.deadJobs, refetchInterval: 10_000 });
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats, refetchInterval: 15_000 });
  async function retry(id: number) {
    await api.retryJob(id);
    void qc.invalidateQueries({ queryKey: ["dead-jobs"] });
  }
  const s = stats.data;
  return (
    <div className="jobs-page">
      <Topbar me={me} live={live} phoneOpen={false} onTogglePhone={() => undefined} />
      <main className="jobs">
        <Link to="/" className="btn btn-quiet">Back to the order desk</Link>
        <section aria-labelledby="today">
          <h1 id="today">Last 24 hours</h1>
          {s && (
            <dl className="jobs-stats">
              <div><dt>Waiting for a check</dt><dd>{s.last_24h.review ?? 0}</dd></div>
              <div><dt>In the ERP</dt><dd>{s.last_24h.posted ?? 0}</dd></div>
              <div><dt>ERP failures</dt><dd>{s.last_24h.post_failed ?? 0}</dd></div>
              <div><dt>Average time to confirm</dt><dd>{s.avg_seconds_to_confirm ? `${Math.round(s.avg_seconds_to_confirm)} s` : "–"}</dd></div>
              <div><dt>Model spend today</dt><dd>${s.llm_spend_today_usd.toFixed(2)} of ${s.llm_budget_usd.toFixed(2)}</dd></div>
            </dl>
          )}
        </section>
        <section aria-labelledby="dead">
          <h2 id="dead">Jobs that gave up</h2>
          <p className="muted">A job lands here after five failed attempts, or at once if the ERP refuses the order. A supervisor can send it again once the cause is fixed.</p>
          {dead.data?.length === 0 && <p className="jobs-none">Nothing stuck. Every job has finished.</p>}
          <ul className="jobs-list">
            {dead.data?.map((j) => (
              <li key={j.id}>
                <div>
                  <p className="jobs-kind">{KIND[j.kind] ?? j.kind}</p>
                  <p className="muted">{j.attempts} attempts. Last error: {j.last_error}</p>
                </div>
                {me.role === "supervisor" ? (
                  <button className="btn" onClick={() => void retry(j.id)}>Retry</button>
                ) : (
                  <span className="muted">A supervisor can retry</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      </main>
    </div>
  );
}
