drop table if exists public.users cascade;

create table if not exists public.orders (
  id bigserial primary key,
  product_name text not null,
  quantity integer not null check (quantity > 0),
  currency_used text not null check (currency_used in ('HKD', 'CNY')),
  unit_price_original numeric(14, 2) not null,
  exchange_rate_to_inr numeric(14, 4) not null,
  unit_price_inr numeric(14, 2) not null,
  final_price_inr numeric(14, 2) not null,
  created_at timestamptz not null default now()
);

alter table public.orders drop column if exists created_by;

create index if not exists orders_created_at_idx on public.orders(created_at desc);
