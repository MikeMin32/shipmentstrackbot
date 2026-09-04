import { Link } from "react-router-dom";

import type { Shipment } from "../types";
import { StatusPill } from "./StatusPill";

export function ShipmentCard({ shipment }: { shipment: Shipment }) {
  return (
    <Link className="shipment-card" to={`/shipments/${shipment.id}`}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="title">{shipment.title}</div>
        <StatusPill status={shipment.status} label={shipment.status_label} />
      </div>
      <div className="meta">
        <span>#{shipment.id}</span>
        <span>{shipment.account?.name ?? "No account"}</span>
        {shipment.expected_delivery_date ? <span>EDD {shipment.expected_delivery_date}</span> : null}
        {shipment.client_team ? <span>{shipment.client_team.name}</span> : null}
      </div>
    </Link>
  );
}
