// Shapes returned by the Orderdesk API (api/src/orderdesk/web/app.py).

export type Role = "order_taker" | "supervisor";
export type Unit = "carton" | "pack" | "piece";
export type OrderStatus = "parsing" | "review" | "confirmed" | "posted" | "post_failed" | "rejected";

export interface Me {
  id: number;
  name: string;
  email: string;
  role: Role;
  supervisor_threshold_fils: number;
}

export interface Product {
  id: string;
  name_en: string;
  name_ar: string;
  size_label: string;
  pack_size: number;
  carton_size: number;
  stock_on_hand: number;
  family: string;
}

export interface OrderSummary {
  id: number;
  ref: string;
  status: OrderStatus;
  customer: { id: string; name: string; area: string } | null;
  lines: number;
  needs_attention: number;
  total_fils: number;
  holds: string[];
  parsed_by: string | null;
  created_at: string;
  age_minutes: number;
  erp_ref: string | null;
  required_role: Role;
}

export interface Line {
  position: number;
  sku: string | null;
  product: Product | null;
  qty: number;
  unit: Unit;
  qty_base: number;
  unit_price_fils: number;
  amount_fils: number;
  source_text: string;
  unit_from: "customer" | "history" | "default";
  confidence: number;
  flags: string[];
  edited: boolean;
  substitutes: Product[];
  why: string | null;
  candidates: Product[];
}

export interface ChatMessage {
  id: number;
  direction: "in" | "out";
  type: "text" | "image" | "audio" | "other";
  text: string | null;
  at: string;
  has_media?: boolean;
}

export interface OrderDetail extends Omit<OrderSummary, "lines"> {
  version: number;
  intent: string;
  notes: string[];
  lines: Line[];
  messages: ChatMessage[];
  customer_detail: {
    id: string;
    name: string;
    type: string;
    area: string;
    contact_name: string;
    credit_limit_fils: number;
    balance_fils: number;
    tier: string;
    language: string;
  } | null;
  recent_orders: { ref: string; date: string; lines: number; total_fils: number }[];
  confirmed_at: string | null;
  parse_cost_usd: number;
}

export interface LineChange {
  op: "update" | "add" | "delete";
  position?: number;
  sku?: string;
  qty?: number;
  unit?: Unit;
}

export interface DemoCustomer {
  id: string;
  name: string;
  phone: string;
  contact_name: string;
  type: string;
  language: string;
}

export interface AuditEntry {
  at: string;
  actor: string;
  action: string;
  before: unknown;
  after: unknown;
  note: string | null;
}

export interface DeadJob {
  id: number;
  kind: string;
  payload: Record<string, unknown>;
  attempts: number;
  last_error: string | null;
  updated_at: string;
}

export interface Stats {
  last_24h: Record<string, number>;
  dead_jobs: number;
  avg_seconds_to_confirm: number | null;
  llm_spend_today_usd: number;
  llm_budget_usd: number;
}
