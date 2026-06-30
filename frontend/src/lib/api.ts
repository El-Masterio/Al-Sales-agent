/**
 * src/lib/api.ts
 * ==============
 * Typed API client. Wraps fetch with auth-token injection, JSON handling,
 * and a 401 -> refresh-token retry. Exposes an SWR-compatible fetcher.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

const ACCESS_KEY = "sa_access_token";
const REFRESH_KEY = "sa_refresh_token";

export const tokenStore = {
  getAccess: () => (typeof window === "undefined" ? null : localStorage.getItem(ACCESS_KEY)),
  getRefresh: () => (typeof window === "undefined" ? null : localStorage.getItem(REFRESH_KEY)),
  set: (access: string, refresh: string) => {
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear: () => {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function refreshAccessToken(): Promise<boolean> {
  const refresh = tokenStore.getRefresh();
  if (!refresh) return false;
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    tokenStore.set(data.access_token, data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  retry = true,
): Promise<T> {
  const access = tokenStore.getAccess();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (access) headers["Authorization"] = `Bearer ${access}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401 && retry) {
    const refreshed = await refreshAccessToken();
    if (refreshed) return apiFetch<T>(path, options, false);
    tokenStore.clear();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new ApiError("Session expired", 401);
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(detail, res.status);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// SWR fetcher
export const fetcher = <T>(path: string) => apiFetch<T>(path);

// Typed endpoint helpers
export const api = {
  login: (email: string, password: string) =>
    apiFetch<{ access_token: string; refresh_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => apiFetch<User>("/auth/me"),
  triggerResearch: (companyId: string) =>
    apiFetch<{ message: string }>(`/companies/${companyId}/research`, { method: "POST" }),
  generateLeads: (criteria: Record<string, unknown>, maxCompanies = 50) =>
    apiFetch<{ message: string }>(`/companies/generate-leads?max_companies=${maxCompanies}`, {
      method: "POST",
      body: JSON.stringify(criteria),
    }),
  activateCampaign: (id: string) =>
    apiFetch<Campaign>(`/campaigns/${id}/activate`, { method: "POST" }),
  pauseCampaign: (id: string) =>
    apiFetch<Campaign>(`/campaigns/${id}/pause`, { method: "POST" }),
  reviewReply: (id: string, override?: string) =>
    apiFetch(`/replies/${id}/review`, {
      method: "POST",
      body: JSON.stringify({ override_classification: override ?? null }),
    }),
};

// ── Shared types (mirror backend Pydantic schemas) ───────────────────────────

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  has_calendar_connected: boolean;
}

export interface DashboardOverview {
  total_leads: number;
  new_leads_today: number;
  emails_sent_today: number;
  emails_sent_total: number;
  open_rate_pct: number;
  reply_rate_pct: number;
  meetings_booked_today: number;
  meetings_booked_total: number;
  revenue_pipeline_usd: number;
  active_campaigns: number;
}

export interface TimeSeriesPoint {
  date: string;
  leads_added: number;
  emails_sent: number;
  emails_opened: number;
  replies_received: number;
  meetings_booked: number;
  revenue_usd: number;
}

export interface Company {
  id: string;
  name: string;
  website: string | null;
  industry: string | null;
  icp_score: number | null;
  lead_status: string;
  employee_count: number | null;
  last_researched_at: string | null;
}

export interface Campaign {
  id: string;
  name: string;
  status: string;
  stat_leads_added: number;
  stat_emails_sent: number;
  stat_emails_opened: number;
  stat_replies: number;
  stat_meetings: number;
}

export interface Reply {
  id: string;
  company_id: string;
  from_email: string;
  from_name: string | null;
  subject: string | null;
  body_text: string;
  classification: string;
  classification_confidence: number | null;
  sentiment_score: number | null;
  ai_summary: string | null;
  received_at: string;
  reviewed: boolean;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}
