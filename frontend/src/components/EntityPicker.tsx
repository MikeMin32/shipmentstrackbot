import { useState } from "react";

import type { NamedEntity } from "../types";

export function EntityPicker({
  label,
  value,
  items,
  required = false,
  allowEmpty = false,
  emptyLabel = "None",
  onChange,
  onCreate,
}: {
  label: string;
  value: number | "";
  items: NamedEntity[];
  required?: boolean;
  allowEmpty?: boolean;
  emptyLabel?: string;
  onChange: (id: number | "") => void;
  onCreate: (name: string) => Promise<NamedEntity>;
}) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleCreate() {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Name is required");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const created = await onCreate(trimmed);
      onChange(created.id ?? "");
      setName("");
      setAdding(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="field">
      <label>{label}</label>
      <select
        required={required}
        value={value}
        onChange={(event) => {
          const next = event.target.value;
          onChange(next === "" ? "" : Number(next));
        }}
      >
        <option value="">{allowEmpty ? emptyLabel : `Select ${label.toLowerCase()}`}</option>
        {items
          .filter((item) => item.id != null)
          .map((item) => (
            <option key={item.id ?? item.name} value={item.id ?? ""}>
              {item.name}
            </option>
          ))}
      </select>
      {adding ? (
        <div className="inline-add">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={`New ${label.toLowerCase()}`}
          />
          <button className="btn" type="button" disabled={busy} onClick={() => void handleCreate()}>
            Save
          </button>
          <button className="btn secondary" type="button" onClick={() => setAdding(false)}>
            Cancel
          </button>
        </div>
      ) : (
        <button className="btn secondary" type="button" style={{ marginTop: 8 }} onClick={() => setAdding(true)}>
          + Add {label.toLowerCase()}
        </button>
      )}
      {error ? <div className="muted" style={{ color: "var(--tg-theme-destructive-text-color)" }}>{error}</div> : null}
    </div>
  );
}
