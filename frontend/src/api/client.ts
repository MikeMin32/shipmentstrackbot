import type {
  DashboardData,
  MeResponse,
  NamedEntity,
  Reminder,
  Shipment,
  ShipmentListResponse,
  ShipmentPayload,
  StatusHistoryItem,
  StatusOption,
} from "../types";
import { getTelegram } from "../lib/telegram";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

function authHeaders(): HeadersInit {
  const initData = getTelegram()?.initData ?? "";
  const headers: Record<string, string> = {
    Accept: "application/json",
  };
  if (initData) {
    headers.Authorization = `tma ${initData}`;
  }
  return headers;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const auth = authHeaders();
  Object.entries(auth).forEach(([key, value]) => {
    if (!headers.has(key)) {
      headers.set(key, value);
    }
  });
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "API unavailable. Check that the backend is running.");
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const data = (await response.json().catch(() => ({}))) as { detail?: unknown };
  if (!response.ok) {
    const detail =
      typeof data.detail === "string"
        ? data.detail
        : Array.isArray(data.detail)
          ? "Request failed"
          : response.status === 401
            ? "Open this app from Telegram"
            : response.status === 403
              ? "Access denied"
              : "Request failed";
    throw new ApiError(response.status, detail);
  }
  return data as T;
}

export const api = {
  me: () => request<MeResponse>("/api/me"),
  dashboard: () => request<DashboardData>("/api/dashboard"),
  statuses: () =>
    request<{ items: StatusOption[] }>("/api/statuses"),
  countries: () => request<string[]>("/api/countries"),
  clones: () => request<string[]>("/api/clones"),
  accounts: () => request<NamedEntity[]>("/api/accounts"),
  accountSummary: () => request<NamedEntity[]>("/api/accounts/summary"),
  createAccount: (name: string) =>
    request<NamedEntity>("/api/accounts", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  teams: () => request<NamedEntity[]>("/api/client-teams"),
  createTeam: (name: string) =>
    request<NamedEntity>("/api/client-teams", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  shipments: (params: Record<string, string | number | boolean | undefined>) => {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === "") {
        return;
      }
      search.set(key, String(value));
    });
    const qs = search.toString();
    return request<ShipmentListResponse>(`/api/shipments${qs ? `?${qs}` : ""}`);
  },
  shipment: (id: number) => request<Shipment>(`/api/shipments/${id}`),
  createShipment: (payload: ShipmentPayload) =>
    request<Shipment>("/api/shipments", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateShipment: (id: number, payload: Record<string, unknown>) =>
    request<Shipment>(`/api/shipments/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  changeStatus: (id: number, status: string) =>
    request<Shipment>(`/api/shipments/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
  complete: (id: number) =>
    request<Shipment>(`/api/shipments/${id}/complete`, { method: "POST" }),
  archive: (id: number) =>
    request<Shipment>(`/api/shipments/${id}/archive`, { method: "POST" }),
  restore: (id: number) =>
    request<Shipment>(`/api/shipments/${id}/restore`, { method: "POST" }),
  history: (id: number) =>
    request<StatusHistoryItem[]>(`/api/shipments/${id}/history`),
  reminder: (id: number) =>
    request<{ reminder: Reminder | null }>(`/api/shipments/${id}/reminder`),
  setReminder: (id: number, remindAt: string) =>
    request<Reminder>(`/api/shipments/${id}/reminder`, {
      method: "PUT",
      body: JSON.stringify({ remind_at: remindAt }),
    }),
  deleteReminder: (id: number) =>
    request<{ ok: boolean }>(`/api/shipments/${id}/reminder`, {
      method: "DELETE",
    }),
};
