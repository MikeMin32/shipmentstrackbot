import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { DashboardData } from "../types";
import { Banner, EmptyState } from "../components/EmptyState";
import { ShipmentCard } from "../components/ShipmentCard";

export function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .dashboard()
      .then((payload) => {
        if (!cancelled) {
          setData(payload);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.detail : "Could not load dashboard");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="page">
        <h1 className="page-title">Shipment Tracker</h1>
        <Banner>{error}</Banner>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="page">
        <h1 className="page-title">Shipment Tracker</h1>
        <div className="muted">Loading…</div>
      </div>
    );
  }

  return (
    <div className="page">
      <h1 className="page-title">Shipment Tracker</h1>
      <div className="cards">
        <div className="summary-card">
          <div className="label">Active</div>
          <div className="value">{data.counts.active}</div>
        </div>
        <div className="summary-card">
          <div className="label">En Route</div>
          <div className="value">{data.counts.enroute}</div>
        </div>
        <div className="summary-card">
          <div className="label">Out For Delivery</div>
          <div className="value">{data.counts.out_for_delivery}</div>
        </div>
        <div className="summary-card">
          <div className="label">Delivered</div>
          <div className="value">{data.counts.delivered}</div>
        </div>
      </div>

      <div className="section-title">Accounts · all shipments</div>
      <div className="card">
        {data.accounts.length === 0 ? (
          <EmptyState>No accounts yet.</EmptyState>
        ) : (
          data.accounts.map((account) => (
            <div className="account-row" key={`${account.id ?? "none"}-${account.name}`}>
              <div>
                <strong>{account.name}</strong>
                <div className="muted">
                  {account.total ?? 0} total · {account.active ?? 0} active
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      <div className="section-title">In Transit</div>
      {data.active.in_transit.length === 0 ? (
        <EmptyState>Nothing in transit.</EmptyState>
      ) : (
        data.active.in_transit.map((item) => <ShipmentCard key={item.id} shipment={item} />)
      )}

      <div className="section-title">Working On</div>
      {data.active.working.length === 0 ? (
        <EmptyState>Nothing in progress.</EmptyState>
      ) : (
        data.active.working.map((item) => <ShipmentCard key={item.id} shipment={item} />)
      )}

      <div style={{ marginTop: 16 }}>
        <Link className="btn block" to="/shipments/new">
          Add shipment
        </Link>
      </div>
    </div>
  );
}
