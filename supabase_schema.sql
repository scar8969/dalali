create table if not exists public.orders (
  id bigserial primary key,
  reference text not null,
  notes text,
  currency text not null check (currency in ('HKD', 'CNY')),
  unit_price numeric(14, 2) not null,
  exchange_rate numeric(14, 4) not null,
  unit_price_inr numeric(14, 2) not null,
  subtotal_inr numeric(14, 2) not null,
  final_inr numeric(14, 2) not null,
  status text not null default 'draft' check (status in ('draft', 'sent', 'cancelled')),
  created_at timestamptz not null default now()
);

create table if not exists public.order_items (
  id bigserial primary key,
  order_id bigint not null references public.orders(id) on delete cascade,
  product_name text not null,
  quantity integer not null check (quantity > 0),
  unit_price_original numeric(14, 2) not null
);

create index if not exists idx_orders_created on public.orders(created_at desc);
create index if not exists idx_items_order on public.order_items(order_id);
