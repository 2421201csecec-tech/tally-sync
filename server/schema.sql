create extension if not exists pgcrypto;

create table merchants (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now()
);

create table users (
  id uuid primary key default gen_random_uuid(),
  merchant_id uuid not null references merchants(id),
  email text not null unique,
  password_hash text not null,
  created_at timestamptz not null default now()
);

create table agents (
  id uuid primary key default gen_random_uuid(),
  merchant_id uuid not null references merchants(id),
  token_hash text not null unique,        -- sha256 of token; token itself is never stored
  label text,
  hostname text,
  version text,
  last_seen timestamptz,
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);

-- Which Tally companies the merchant allowed this agent to sync (consent, enforced server-side)
create table agent_companies (
  agent_id uuid not null references agents(id) on delete cascade,
  name text not null,
  enabled boolean not null default false,
  primary key (agent_id, name)
);

-- Device pairing ("Allow this agent?") requests
create table pairing_requests (
  id uuid primary key default gen_random_uuid(),
  device_code_hash text not null unique,
  user_code text not null unique,
  hostname text,
  status text not null default 'pending',   -- pending | approved | denied | consumed
  merchant_id uuid references merchants(id),
  agent_id uuid references agents(id),
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);

create table companies (
  id uuid primary key default gen_random_uuid(),
  merchant_id uuid not null references merchants(id),
  name text not null,
  unique (merchant_id, name)
);

create table ledgers (
  company_id uuid not null references companies(id),
  guid text not null,
  name text not null,
  parent text,
  opening_balance numeric,
  closing_balance numeric,
  alter_id bigint,
  updated_at timestamptz not null default now(),
  primary key (company_id, guid)
);

create table stock_items (
  company_id uuid not null references companies(id),
  guid text not null,
  name text not null,
  parent text,
  unit text,
  closing_qty numeric,
  closing_value numeric,
  alter_id bigint,
  updated_at timestamptz not null default now(),
  primary key (company_id, guid)
);

create table vouchers (
  company_id uuid not null references companies(id),
  guid text not null,
  alter_id bigint not null,
  date date,
  voucher_type text,
  voucher_number text,
  party text,
  narration text,
  amount numeric,
  ledger_entries jsonb,
  inventory_entries jsonb,
  raw text,
  is_deleted boolean not null default false,
  updated_at timestamptz not null default now(),
  primary key (company_id, guid)
);
create index on vouchers (company_id, date);
create index on vouchers (company_id, voucher_type, date);
create index on vouchers (company_id, party);
