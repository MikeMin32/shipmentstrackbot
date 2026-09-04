export type StatusId =
  | "standby"
  | "preparing"
  | "make_label"
  | "enroute"
  | "out_for_delivery"
  | "delivered";

export interface NamedEntity {
  id: number | null;
  name: string;
  archived?: boolean;
  total?: number;
  active?: number;
  unassigned?: boolean;
}

export interface Shipment {
  id: number;
  country: string;
  clone: string;
  title: string;
  status: StatusId;
  status_label: string;
  status_group: string;
  account: NamedEntity | null;
  client_team: NamedEntity | null;
  box_weight: number | null;
  label_creation_date: string | null;
  scanned_in_date: string | null;
  expected_delivery_date: string | null;
  delivered_date: string | null;
  note: string | null;
  archived: boolean;
  created_at: string | null;
  updated_at: string | null;
  created_by: number | null;
  reminder?: Reminder | null;
}

export interface Reminder {
  id: number;
  shipment_id: number;
  remind_at: string;
  created_by: number | null;
  created_at: string | null;
}

export interface StatusHistoryItem {
  id: number;
  old_status: string | null;
  old_status_label: string | null;
  new_status: string | null;
  new_status_label: string | null;
  changed_by: number | null;
  changed_at: string | null;
}

export interface DashboardData {
  counts: {
    active: number;
    in_transit: number;
    enroute: number;
    out_for_delivery: number;
    working: number;
    delivered: number;
    archived: number;
  };
  accounts: NamedEntity[];
  active: {
    in_transit: Shipment[];
    working: Shipment[];
  };
}

export interface ShipmentListResponse {
  items: Shipment[];
  total: number;
  limit: number;
  offset: number;
}

export interface MeResponse {
  user: {
    id: number;
    first_name: string;
    last_name: string | null;
    username: string | null;
  };
  timezone: string;
  dev_auth: boolean;
}

export interface StatusOption {
  id: string;
  label: string;
}

export interface ShipmentPayload {
  account_id: number;
  country: string;
  clone: string;
  client_team_id?: number | null;
  box_weight?: number | null;
  status?: string;
  label_creation_date?: string | null;
  scanned_in_date?: string | null;
  expected_delivery_date?: string | null;
  note?: string | null;
}
