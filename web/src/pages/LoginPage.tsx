import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { keys } from "../lib/hooks";
import "./LoginPage.css";

const DEMO = [
  { email: "maria@saffronlane.example", who: "Maria", role: "Order desk: confirms everyday orders" },
  { email: "omar@saffronlane.example", who: "Omar", role: "Supervisor: releases credit holds and large orders" },
];
const DEMO_PASSWORD = import.meta.env.VITE_DEMO_PASSWORD ?? "orderdesk-demo";

export default function LoginPage() {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function signIn(e: string, p: string) {
    setBusy(true);
    setError(null);
    try {
      const me = await api.login(e, p);
      qc.setQueryData(keys.me, { ...me, supervisor_threshold_fils: 0 });
      await qc.invalidateQueries({ queryKey: keys.me });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void signIn(email, password);
  }

  return (
    <main className="login">
      <section className="login-sheet" aria-labelledby="login-title">
        <p className="login-brand">Saffron Lane Foodstuff Trading</p>
        <h1 id="login-title">Orderdesk</h1>
        <p className="muted">WhatsApp orders, read and drafted, waiting for your check.</p>
        <div className="login-demo" role="group" aria-label="Demo accounts">
          {DEMO.map((d) => (
            <button key={d.email} className="login-person" disabled={busy} onClick={() => void signIn(d.email, DEMO_PASSWORD)}>
              <span className="login-person-name">Sign in as {d.who}</span>
              <span className="muted">{d.role}</span>
            </button>
          ))}
        </div>
        <details className="login-manual">
          <summary>Sign in with email</summary>
          <form onSubmit={onSubmit} className="login-form">
            <div className="field">
              <label htmlFor="email">Email</label>
              <input id="email" className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="password">Password</label>
              <input id="password" className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
            <button className="btn btn-primary" disabled={busy}>Sign in</button>
          </form>
        </details>
        {error && <p className="error-text" role="alert">{error}</p>}
        <p className="login-foot muted">A demo with a fictional distributor. No real customers, products or orders.</p>
      </section>
    </main>
  );
}
