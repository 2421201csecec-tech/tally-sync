export type CompanyPermission = { name: string; enabled: boolean };

export type Agent = {
  id: string;
  hostname: string | null;
  version: string | null;
  last_seen: string | null;
  online: boolean;
  companies: CompanyPermission[];
};

export type Dashboard = {
  merchant_name: string;
  installer_ready: boolean;
  agents: Agent[];
  companies: {
    name: string;
    vouchers: number;
    ledgers: number;
    stock_items: number;
  }[];
  csrf: string;
};
