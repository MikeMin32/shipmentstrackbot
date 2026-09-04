import { FormEvent, useEffect, useState } from "react";

import { api, ApiError } from "../api/client";
import { Banner, EmptyState } from "../components/EmptyState";
import type { NamedEntity } from "../types";

export function AccountsPage() {
  const [items, setItems] = useState<NamedEntity[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const rows = await api.accountSummary();
    setItems(rows);
  }

  useEffect(() => {
    load().catch((err: unknown) => {
      setError(err instanceof ApiError ? err.detail : "Could not load accounts");
    });
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || busy) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.createAccount(name.trim());
      setName("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not create account");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h1 className="page-title">Accounts</h1>
      <p className="muted">Totals include completed and archived shipments. Active counts exclude delivered and archived.</p>
      {error ? <Banner>{error}</Banner> : null}
      <form className="card" onSubmit={(event) => void onSubmit(event)} style={{ marginBottom: 12 }}>
        <div className="inline-add" style={{ marginTop: 0 }}>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="New account name"
          />
          <button className="btn" type="submit" disabled={busy}>
            Add
          </button>
        </div>
      </form>
      <div className="card">
        {items.length === 0 ? (
          <EmptyState>No accounts yet.</EmptyState>
        ) : (
          items.map((item) => (
            <div className="account-row" key={`${item.id ?? "none"}-${item.name}`}>
              <strong>{item.name}</strong>
              <div className="muted">
                {item.total ?? 0} total · {item.active ?? 0} active
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
