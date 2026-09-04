import { FormEvent, useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import { EntityPicker } from "../components/EntityPicker";
import { Banner } from "../components/EmptyState";
import { haptic } from "../lib/telegram";
import type { NamedEntity, Shipment, StatusOption } from "../types";

const emptyForm = {
  account_id: "" as number | "",
  country: "",
  clone: "",
  client_team_id: "" as number | "",
  box_weight: "",
  status: "preparing",
  label_creation_date: "",
  scanned_in_date: "",
  expected_delivery_date: "",
  note: "",
};

export function ShipmentFormPage() {
  const { id } = useParams();
  const isEdit = Boolean(id);
  const navigate = useNavigate();
  const location = useLocation();
  const [form, setForm] = useState(emptyForm);
  const [accounts, setAccounts] = useState<NamedEntity[]>([]);
  const [teams, setTeams] = useState<NamedEntity[]>([]);
  const [statuses, setStatuses] = useState<StatusOption[]>([]);
  const [countries, setCountries] = useState<string[]>([]);
  const [clones, setClones] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(!isEdit);

  useEffect(() => {
    void Promise.all([api.accounts(), api.teams(), api.statuses(), api.countries(), api.clones()]).then(
      ([accountRows, teamRows, statusPayload, countryRows, cloneRows]) => {
        setAccounts(accountRows);
        setTeams(teamRows);
        setStatuses(statusPayload.items.filter((item) => item.id !== "delivered"));
        setCountries(countryRows);
        setClones(cloneRows);
      },
    );
  }, []);

  useEffect(() => {
    if (!id) {
      return;
    }
    api
      .shipment(Number(id))
      .then((shipment) => {
        applyShipment(shipment);
        setLoaded(true);
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.detail : "Could not load shipment");
        setLoaded(true);
      });
  }, [id]);

  function applyShipment(shipment: Shipment) {
    setForm({
      account_id: shipment.account?.id ?? "",
      country: shipment.country,
      clone: shipment.clone,
      client_team_id: shipment.client_team?.id ?? "",
      box_weight: shipment.box_weight != null ? String(shipment.box_weight) : "",
      status: shipment.status,
      label_creation_date: shipment.label_creation_date ?? "",
      scanned_in_date: shipment.scanned_in_date ?? "",
      expected_delivery_date: shipment.expected_delivery_date ?? "",
      note: shipment.note ?? "",
    });
  }

  function update<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (busy) {
      return;
    }
    if (form.account_id === "") {
      setError("Account is required");
      return;
    }
    if (!form.country.trim() || !form.clone.trim()) {
      setError("Country and clone are required");
      return;
    }
    let weight: number | null = null;
    if (form.box_weight.trim()) {
      weight = Number(form.box_weight);
      if (!Number.isFinite(weight) || weight <= 0) {
        setError("Box weight must be a positive number");
        return;
      }
    }

    setBusy(true);
    setError("");
    try {
      if (isEdit && id) {
        const payload: Record<string, unknown> = {
          account_id: Number(form.account_id),
          country: form.country.trim(),
          clone: form.clone.trim(),
          note: form.note.trim() || null,
          clear_note: !form.note.trim(),
          box_weight: weight,
          clear_box_weight: weight == null,
          label_creation_date: form.label_creation_date || null,
          scanned_in_date: form.scanned_in_date || null,
          expected_delivery_date: form.expected_delivery_date || null,
          clear_label_creation_date: !form.label_creation_date,
          clear_scanned_in_date: !form.scanned_in_date,
          clear_expected_delivery_date: !form.expected_delivery_date,
        };
        if (form.client_team_id === "") {
          payload.clear_client_team = true;
        } else {
          payload.client_team_id = Number(form.client_team_id);
        }
        const updated = await api.updateShipment(Number(id), payload);
        haptic("success");
        navigate(`/shipments/${updated.id}`, { replace: true, state: { notice: "Shipment updated" } });
      } else {
        const created = await api.createShipment({
          account_id: Number(form.account_id),
          country: form.country.trim(),
          clone: form.clone.trim(),
          client_team_id: form.client_team_id === "" ? null : Number(form.client_team_id),
          box_weight: weight,
          status: form.status,
          label_creation_date: form.label_creation_date || null,
          scanned_in_date: form.scanned_in_date || null,
          expected_delivery_date: form.expected_delivery_date || null,
          note: form.note.trim() || null,
        });
        haptic("success");
        navigate(`/shipments/${created.id}`, { replace: true, state: { notice: "Shipment created" } });
      }
    } catch (err) {
      haptic("error");
      setError(err instanceof ApiError ? err.detail : "Could not save shipment");
      setBusy(false);
    }
  }

  if (!loaded) {
    return (
      <div className="page">
        <h1 className="page-title">{isEdit ? "Edit shipment" : "New shipment"}</h1>
        <div className="muted">Loading…</div>
      </div>
    );
  }

  return (
    <div className="page">
      <h1 className="page-title">{isEdit ? "Edit shipment" : "New shipment"}</h1>
      {error ? <Banner>{error}</Banner> : null}
      <form className="card" onSubmit={(event) => void onSubmit(event)}>
        <EntityPicker
          label="Account"
          required
          value={form.account_id}
          items={accounts}
          onChange={(value) => update("account_id", value)}
          onCreate={async (name) => {
            const created = await api.createAccount(name);
            setAccounts((current) => [...current, created]);
            return created;
          }}
        />
        <div className="field">
          <label>Country</label>
          <input
            list="country-options"
            required
            value={form.country}
            onChange={(event) => update("country", event.target.value)}
            placeholder="DE, CA, ATL"
          />
          <datalist id="country-options">
            {countries.map((item) => (
              <option key={item} value={item} />
            ))}
          </datalist>
        </div>
        <div className="field">
          <label>Clone</label>
          <input
            list="clone-options"
            required
            value={form.clone}
            onChange={(event) => update("clone", event.target.value)}
          />
          <datalist id="clone-options">
            {clones.map((item) => (
              <option key={item} value={item} />
            ))}
          </datalist>
        </div>
        <EntityPicker
          label="Client team"
          allowEmpty
          emptyLabel="No team"
          value={form.client_team_id}
          items={teams}
          onChange={(value) => update("client_team_id", value)}
          onCreate={async (name) => {
            const created = await api.createTeam(name);
            setTeams((current) => [...current, created]);
            return created;
          }}
        />
        <div className="field">
          <label>Box weight (kg)</label>
          <input
            inputMode="decimal"
            type="number"
            min="0.001"
            step="0.001"
            value={form.box_weight}
            onChange={(event) => update("box_weight", event.target.value)}
          />
        </div>
        {!isEdit ? (
          <div className="field">
            <label>Status</label>
            <select value={form.status} onChange={(event) => update("status", event.target.value)}>
              {statuses.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <div className="field">
          <label>Label creation date</label>
          <input
            type="date"
            value={form.label_creation_date}
            onChange={(event) => update("label_creation_date", event.target.value)}
          />
        </div>
        <div className="field">
          <label>Scanned-in date</label>
          <input
            type="date"
            value={form.scanned_in_date}
            onChange={(event) => update("scanned_in_date", event.target.value)}
          />
        </div>
        <div className="field">
          <label>Expected delivery date</label>
          <input
            type="date"
            value={form.expected_delivery_date}
            onChange={(event) => update("expected_delivery_date", event.target.value)}
          />
        </div>
        <div className="field">
          <label>Note</label>
          <textarea
            value={form.note}
            maxLength={500}
            onChange={(event) => update("note", event.target.value)}
          />
        </div>
        <div className="actions">
          <button
            className="btn secondary"
            type="button"
            onClick={() => {
              if (location.key === "default") {
                navigate("/");
              } else {
                navigate(-1);
              }
            }}
          >
            Cancel
          </button>
          <button className="btn" type="submit" disabled={busy}>
            {busy ? "Saving…" : isEdit ? "Save changes" : "Create shipment"}
          </button>
        </div>
      </form>
    </div>
  );
}
