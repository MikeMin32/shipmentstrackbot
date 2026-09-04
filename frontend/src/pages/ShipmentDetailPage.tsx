import { FormEvent, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import { Banner } from "../components/EmptyState";
import { StatusPill } from "../components/StatusPill";
import { confirmAction, haptic } from "../lib/telegram";
import type { Reminder, Shipment, StatusHistoryItem, StatusOption } from "../types";

function Field({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

function toLocalInput(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function fromLocalInput(value: string): string {
  const date = new Date(value);
  return date.toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function ShipmentDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const shipmentId = Number(id);
  const [shipment, setShipment] = useState<Shipment | null>(null);
  const [history, setHistory] = useState<StatusHistoryItem[]>([]);
  const [statuses, setStatuses] = useState<StatusOption[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(
    (location.state as { notice?: string } | null)?.notice ?? "",
  );
  const [busy, setBusy] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [reminderOpen, setReminderOpen] = useState(false);
  const [reminderAt, setReminderAt] = useState("");

  async function load() {
    const [item, historyRows, statusPayload] = await Promise.all([
      api.shipment(shipmentId),
      api.history(shipmentId),
      api.statuses(),
    ]);
    setShipment(item);
    setHistory(historyRows);
    setStatuses(statusPayload.items);
    if (item.reminder?.remind_at) {
      setReminderAt(toLocalInput(item.reminder.remind_at));
    }
  }

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(err instanceof ApiError ? err.detail : "Could not load shipment");
    });
  }, [shipmentId]);

  async function run(action: () => Promise<Shipment>, success: string) {
    if (busy) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const updated = await action();
      setShipment(updated);
      setNotice(success);
      haptic("success");
      const historyRows = await api.history(shipmentId);
      setHistory(historyRows);
    } catch (err) {
      haptic("error");
      setError(err instanceof ApiError ? err.detail : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  async function onComplete() {
    const ok = await confirmAction("Mark this shipment as delivered? Delivered date will be set automatically.");
    if (ok) {
      await run(() => api.complete(shipmentId), "Marked as delivered");
    }
  }

  async function onArchive() {
    const ok = await confirmAction("Archive this shipment? It will be hidden from operational views.");
    if (ok) {
      await run(() => api.archive(shipmentId), "Archived");
    }
  }

  async function onRestore() {
    await run(() => api.restore(shipmentId), "Restored");
  }

  async function onStatus(status: string) {
    setStatusOpen(false);
    await run(() => api.changeStatus(shipmentId, status), "Status updated");
  }

  async function onReminder(event: FormEvent) {
    event.preventDefault();
    if (!reminderAt) {
      setError("Choose a reminder date and time");
      return;
    }
    const iso = fromLocalInput(reminderAt);
    if (new Date(iso).getTime() <= Date.now()) {
      setError("Reminder must be in the future");
      return;
    }
    setBusy(true);
    try {
      const reminder = await api.setReminder(shipmentId, iso);
      setShipment((current) => (current ? { ...current, reminder } : current));
      setReminderOpen(false);
      setNotice("Reminder saved");
      haptic("success");
    } catch (err) {
      haptic("error");
      setError(err instanceof ApiError ? err.detail : "Could not save reminder");
    } finally {
      setBusy(false);
    }
  }

  async function onRemoveReminder() {
    setBusy(true);
    try {
      await api.deleteReminder(shipmentId);
      setShipment((current) => (current ? { ...current, reminder: null } : current));
      setNotice("Reminder removed");
      haptic("success");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not remove reminder");
    } finally {
      setBusy(false);
    }
  }

  if (error && !shipment) {
    return (
      <div className="page">
        <h1 className="page-title">Shipment</h1>
        <Banner>{error}</Banner>
      </div>
    );
  }

  if (!shipment) {
    return (
      <div className="page">
        <h1 className="page-title">Shipment</h1>
        <div className="muted">Loading…</div>
      </div>
    );
  }

  const reminder: Reminder | null | undefined = shipment.reminder;

  return (
    <div className="page">
      <h1 className="page-title">{shipment.title}</h1>
      {notice ? <Banner kind="info">{notice}</Banner> : null}
      {error ? <Banner>{error}</Banner> : null}

      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <StatusPill status={shipment.status} label={shipment.status_label} />
          <span className="muted">#{shipment.id}</span>
        </div>
        <dl className="details">
          <Field label="Country" value={shipment.country || "—"} />
          <Field label="Clone" value={shipment.clone || "—"} />
          <Field label="Account" value={shipment.account?.name ?? "No account"} />
          <Field label="Client team" value={shipment.client_team?.name ?? "—"} />
          <Field
            label="Box weight"
            value={shipment.box_weight != null ? `${shipment.box_weight} kg` : "—"}
          />
          <Field label="Label creation date" value={shipment.label_creation_date ?? "—"} />
          <Field label="Scanned-in date" value={shipment.scanned_in_date ?? "—"} />
          <Field label="Expected delivery date" value={shipment.expected_delivery_date ?? "—"} />
          <Field label="Delivered date" value={shipment.delivered_date ?? "—"} />
          <Field
            label="Reminder"
            value={reminder?.remind_at ? new Date(reminder.remind_at).toLocaleString() : "—"}
          />
          <Field label="Note" value={shipment.note || "—"} />
          <Field label="Updated" value={shipment.updated_at || "—"} />
        </dl>
      </div>

      {!shipment.archived ? (
        <div className="actions">
          <Link className="btn secondary" to={`/shipments/${shipment.id}/edit`}>
            Edit
          </Link>
          <button className="btn secondary" type="button" onClick={() => setStatusOpen(true)}>
            Change status
          </button>
          <button className="btn secondary" type="button" onClick={() => setReminderOpen(true)}>
            Reminder
          </button>
          {shipment.status !== "delivered" ? (
            <button className="btn" type="button" disabled={busy} onClick={() => void onComplete()}>
              Mark delivered
            </button>
          ) : (
            <span />
          )}
          <button className="btn danger" type="button" disabled={busy} onClick={() => void onArchive()}>
            Archive
          </button>
        </div>
      ) : (
        <div className="actions">
          <button className="btn" type="button" disabled={busy} onClick={() => void onRestore()}>
            Restore
          </button>
          <button className="btn secondary" type="button" onClick={() => navigate("/archive")}>
            Back to archive
          </button>
        </div>
      )}

      <div className="section-title">Status history</div>
      <div className="card">
        {history.length === 0 ? (
          <div className="muted">No history yet.</div>
        ) : (
          <ul className="timeline">
            {history.map((item) => (
              <li key={item.id}>
                <div>
                  {item.old_status_label
                    ? `${item.old_status_label} → ${item.new_status_label}`
                    : item.new_status_label}
                </div>
                <div className="muted">
                  {item.changed_at}
                  {item.changed_by ? ` · user ${item.changed_by}` : ""}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {statusOpen ? (
        <div className="sheet" onClick={() => setStatusOpen(false)}>
          <div className="sheet-card" onClick={(event) => event.stopPropagation()}>
            <h2 className="page-title">Change status</h2>
            <div className="status-grid">
              {statuses.map((item) => (
                <button
                  key={item.id}
                  className="btn secondary"
                  type="button"
                  disabled={busy || item.id === shipment.status}
                  onClick={() => void onStatus(item.id)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}

      {reminderOpen ? (
        <div className="sheet" onClick={() => setReminderOpen(false)}>
          <div className="sheet-card" onClick={(event) => event.stopPropagation()}>
            <h2 className="page-title">Reminder</h2>
            <p className="muted">Reminders still use a specific time. Notifications are sent in Telegram.</p>
            <form onSubmit={(event) => void onReminder(event)}>
              <div className="field">
                <label>Date and time</label>
                <input
                  type="datetime-local"
                  value={reminderAt}
                  onChange={(event) => setReminderAt(event.target.value)}
                  required
                />
              </div>
              <div className="actions">
                <button className="btn" type="submit" disabled={busy}>
                  Save reminder
                </button>
                {reminder ? (
                  <button className="btn danger" type="button" disabled={busy} onClick={() => void onRemoveReminder()}>
                    Remove
                  </button>
                ) : (
                  <button className="btn secondary" type="button" onClick={() => setReminderOpen(false)}>
                    Cancel
                  </button>
                )}
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}
