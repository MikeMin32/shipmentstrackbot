import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { api, ApiError } from "./api/client";
import { Layout } from "./components/Layout";
import { TelegramBackButton } from "./components/TelegramBackButton";
import { initTelegram } from "./lib/telegram";
import { AccessPage } from "./pages/AccessPage";
import { AccountsPage } from "./pages/AccountsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ShipmentDetailPage } from "./pages/ShipmentDetailPage";
import { ShipmentFormPage } from "./pages/ShipmentFormPage";
import { ShipmentsPage } from "./pages/ShipmentsPage";
import type { MeResponse } from "./types";

export function App() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    initTelegram();
    api
      .me()
      .then((payload) => {
        setMe(payload);
        setReady(true);
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err : new ApiError(0, "Could not reach API"));
        setReady(true);
      });
  }, []);

  if (!ready) {
    return (
      <div className="page">
        <h1 className="page-title">Shipment Tracker</h1>
        <div className="muted">Loading…</div>
      </div>
    );
  }

  if (error) {
    if (error.status === 401) {
      return (
        <AccessPage
          title="Open this app from Telegram"
          message="Valid Telegram Mini App authentication is required. Shipment data is not available from a direct browser visit."
        />
      );
    }
    if (error.status === 403) {
      return <AccessPage title="Access denied" message="Your Telegram account is not on the allowlist." />;
    }
    return <AccessPage title="Tracker unavailable" message={error.detail} />;
  }

  return (
    <>
      <TelegramBackButton />
      <Routes>
        <Route element={<Layout devAuth={Boolean(me?.dev_auth)} />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/shipments" element={<ShipmentsPage />} />
          <Route path="/shipments/new" element={<ShipmentFormPage />} />
          <Route path="/shipments/:id" element={<ShipmentDetailPage />} />
          <Route path="/shipments/:id/edit" element={<ShipmentFormPage />} />
          <Route path="/accounts" element={<AccountsPage />} />
          <Route path="/archive" element={<ShipmentsPage archived />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </>
  );
}
