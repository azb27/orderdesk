// A small fetch wrapper: cookies for the session, the CSRF header on every request, readable errors.
import type { AuditEntry, ChatMessage, DeadJob, DemoCustomer, LineChange, Me, OrderDetail, OrderSummary, Product, Stats } from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-Orderdesk", "1");
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(path, { ...init, headers, credentials: "same-origin" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body: unknown = await res.json();
      if (body && typeof body === "object" && "detail" in body) {
        const d = (body as { detail: unknown }).detail;
        detail = typeof d === "string" ? d : JSON.stringify(d);
      }
    } catch {
      /* not JSON: keep the status text */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const api = {
  me: () => request<Me>("/api/me"),
  login: (email: string, password: string) => request<Me>("/api/auth/login", json({ email, password })),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  orders: (status: string) => request<OrderSummary[]>(`/api/orders?status=${encodeURIComponent(status)}`),
  order: (id: number) => request<OrderDetail>(`/api/orders/${id}`),
  edit: (id: number, version: number, changes: LineChange[]) =>
    request<OrderDetail>(`/api/orders/${id}`, { method: "PATCH", body: JSON.stringify({ version, changes }) }),
  confirm: (id: number, version: number) => request<{ ok: boolean; status: string }>(`/api/orders/${id}/confirm`, json({ version })),
  reject: (id: number, reason: string) => request<{ ok: boolean }>(`/api/orders/${id}/reject`, json({ reason })),
  teach: (term: string, sku: string, customer_id: string | null) =>
    request<Record<string, string>>("/api/aliases", json({ term, sku, customer_id })),
  products: (q: string) => request<Product[]>(`/api/products?q=${encodeURIComponent(q)}`),
  audit: (ref: string) => request<AuditEntry[]>(`/api/audit?entity=order&entity_id=${encodeURIComponent(ref)}`),
  deadJobs: () => request<DeadJob[]>("/api/jobs?status=dead"),
  retryJob: (id: number) => request<{ ok: boolean }>(`/api/jobs/${id}/retry`, { method: "POST" }),
  stats: () => request<Stats>("/api/stats"),
  demoCustomers: () => request<DemoCustomer[]>("/api/simulator/customers"),
  thread: (phone: string) => request<ChatMessage[]>(`/api/simulator/thread?phone=${encodeURIComponent(phone)}`),
  sendAsRetailer: (phone: string, text: string, image?: File) => {
    const fd = new FormData();
    fd.set("phone", phone);
    fd.set("text", text);
    if (image) fd.set("image", image);
    return request<{ ok: boolean }>("/api/simulator/send", { method: "POST", body: fd });
  },
};
