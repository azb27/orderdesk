import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

export const keys = {
  me: ["me"] as const,
  orders: (status: string) => ["orders", status] as const,
  order: (id: number) => ["order", id] as const,
  thread: (phone: string) => ["thread", phone] as const,
};

export function useMe() {
  return useQuery({ queryKey: keys.me, queryFn: api.me, retry: false, staleTime: 60_000 });
}

export function useOrders(status: string) {
  return useQuery({ queryKey: keys.orders(status), queryFn: () => api.orders(status), refetchInterval: 30_000 });
}

export function useOrder(id: number | null) {
  return useQuery({ queryKey: keys.order(id ?? 0), queryFn: () => api.order(id ?? 0), enabled: id !== null });
}

interface LiveEvent {
  type: "order" | "message" | "conversation";
  order_id?: number;
  phone?: string;
}

/** Server-sent events from Postgres NOTIFY. Each event invalidates exactly the queries it affects. */
export function useLiveUpdates(enabled: boolean): boolean {
  const qc = useQueryClient();
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (!enabled) return;
    let es: EventSource | null = null;

    function onMessage(e: MessageEvent<string>) {
      let ev: LiveEvent;
      try {
        ev = JSON.parse(e.data) as LiveEvent;
      } catch {
        return;
      }
      if (ev.type === "order") {
        void qc.invalidateQueries({ queryKey: ["orders"] });
        if (ev.order_id) void qc.invalidateQueries({ queryKey: keys.order(ev.order_id) });
      }
      if (ev.type === "message" && ev.phone) {
        void qc.invalidateQueries({ queryKey: keys.thread(ev.phone) });
        void qc.invalidateQueries({ queryKey: ["order"] });
      }
    }
    function open() {
      if (es) return;
      es = new EventSource("/api/events");
      es.onopen = () => setConnected(true);
      es.onerror = () => setConnected(false);
      es.onmessage = onMessage;
    }
    function close() {
      es?.close();
      es = null;
      setConnected(false);
    }
    // A hidden tab drops its stream, so a forgotten tab doesn't keep the server (and its database) awake.
    // Coming back reopens it and refetches whatever changed meanwhile.
    function onVisibility() {
      if (document.hidden) {
        close();
      } else {
        open();
        void qc.invalidateQueries();
      }
    }
    if (!document.hidden) open();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      close();
    };
  }, [enabled, qc]);
  return connected;
}

/** Re-render every `ms` (for clocks and ages). */
export function useNow(ms = 30_000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}
