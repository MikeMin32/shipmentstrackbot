import { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "../api/client";
import { Banner, EmptyState } from "../components/EmptyState";
import { ShipmentCard } from "../components/ShipmentCard";
import type { NamedEntity, Shipment, StatusOption } from "../types";

const PAGE_SIZE = 50;

export function ShipmentsPage({ archived = false }: { archived?: boolean }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [accountId, setAccountId] = useState("");
  const [items, setItems] = useState<Shipment[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [statuses, setStatuses] = useState<StatusOption[]>([]);
  const [accounts, setAccounts] = useState<NamedEntity[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void Promise.all([api.statuses(), api.accounts()])
      .then(([statusPayload, accountPayload]) => {
        setStatuses(statusPayload.items);
        setAccounts(accountPayload);
      })
      .catch(() => undefined);
  }, []);

  const filters = useMemo(
    () => ({
      q: query.trim() || undefined,
      status: status || undefined,
      account_id: accountId && accountId !== "none" ? Number(accountId) : undefined,
      unassigned: accountId === "none" ? true : undefined,
      archived,
    }),
    [query, status, accountId, archived],
  );

  useEffect(() => {
    setOffset(0);
    setItems([]);
  }, [filters]);

  useEffect(() => {
    let cancelled = false;
    const handle = window.setTimeout(() => {
      setLoading(true);
      api
        .shipments({ ...filters, limit: PAGE_SIZE, offset })
        .then((payload) => {
          if (cancelled) {
            return;
          }
          setItems((current) => (offset === 0 ? payload.items : [...current, ...payload.items]));
          setTotal(payload.total);
          setError("");
        })
        .catch((err: unknown) => {
          if (cancelled) {
            return;
          }
          setError(err instanceof ApiError ? err.detail : "Could not load shipments");
        })
        .finally(() => {
          if (!cancelled) {
            setLoading(false);
          }
        });
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [filters, offset]);

  return (
    <div className="page">
      <h1 className="page-title">{archived ? "Archive" : "Shipments"}</h1>
      <div className="filters">
        <input
          className="search"
          placeholder="Search ID, country, clone, account, team"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <div className="grid-2">
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">All statuses</option>
            {statuses.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
          <select value={accountId} onChange={(event) => setAccountId(event.target.value)}>
            <option value="">All accounts</option>
            <option value="none">No account</option>
            {accounts.map((account) => (
              <option key={account.id ?? "x"} value={account.id ?? ""}>
                {account.name}
              </option>
            ))}
          </select>
        </div>
      </div>
      {error ? <Banner>{error}</Banner> : null}
      {loading && items.length === 0 ? <div className="muted">Loading…</div> : null}
      {!loading && items.length === 0 ? (
        <EmptyState>{archived ? "No archived shipments." : "No shipments match these filters."}</EmptyState>
      ) : (
        items.map((item) => <ShipmentCard key={item.id} shipment={item} />)
      )}
      {items.length < total ? (
        <button className="btn secondary block" type="button" disabled={loading} onClick={() => setOffset(items.length)}>
          {loading ? "Loading…" : `Load more (${items.length} of ${total})`}
        </button>
      ) : null}
    </div>
  );
}
