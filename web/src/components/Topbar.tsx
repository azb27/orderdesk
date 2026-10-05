import { Link, useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import type { Me } from "../lib/types";
import { api } from "../lib/api";
import { keys, useNow } from "../lib/hooks";
import { minutesToCutoff } from "../lib/format";
import "./Topbar.css";

function Cutoff() {
  const now = useNow(30_000);
  const left = minutesToCutoff(now);
  const text =
    left > 0 ? `${Math.floor(left / 60)} h ${left % 60} min to the 16:00 cut-off` : "Past today's 16:00 cut-off: new orders go to the day after tomorrow";
  return (
    <p className={`cutoff ${left > 0 && left <= 60 ? "cutoff--soon" : ""}`} aria-live="polite">
      {text}
    </p>
  );
}

export default function Topbar({ me, live, phoneOpen, onTogglePhone }: { me: Me; live: boolean; phoneOpen: boolean; onTogglePhone: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  async function signOut() {
    await api.logout();
    qc.removeQueries();
    await qc.invalidateQueries({ queryKey: keys.me });
    navigate("/login");
  }
  return (
    <header className="topbar">
      <Link to="/" className="topbar-brand">
        Orderdesk
        <span className="topbar-company">Saffron Lane</span>
      </Link>
      <Cutoff />
      <span className={`live ${live ? "live--on" : ""}`} title={live ? "Live: new orders appear on their own" : "Reconnecting to live updates"}>
        <span className="live-dot" aria-hidden="true" />
        {live ? "Live" : "Reconnecting"}
      </span>
      <div className="topbar-right">
        <button className={`btn ${phoneOpen ? "btn-primary" : ""}`} aria-pressed={phoneOpen} onClick={onTogglePhone}>
          Retailer phone (demo)
        </button>
        <Link className="btn btn-quiet" to="/jobs">
          ERP & jobs
        </Link>
        <span className="topbar-user">
          {me.name}
          <span className="muted">{me.role === "supervisor" ? "Supervisor" : "Order desk"}</span>
        </span>
        <button className="btn btn-quiet" onClick={() => void signOut()}>
          Sign out
        </button>
      </div>
    </header>
  );
}
