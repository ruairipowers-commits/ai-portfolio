-- P&L explain per book: prior-day internal position x local price change x today's FX, vs the risk system.
with px as (
  select c.business_date, s.ticker, s.ccy, s.book, p.close, pp.close as prev_close, fx.usd_rate
  from {{ ref('stg_calendar') }} c
  cross join {{ source('raw', 'securities') }} s
  left join {{ ref('stg_prices') }} p on p.business_date = c.business_date and p.ticker = s.ticker
  left join {{ ref('stg_prices') }} pp on pp.business_date = c.prev_date and pp.ticker = s.ticker
  left join {{ ref('stg_fx') }} fx on fx.business_date = c.business_date and fx.ccy = s.ccy
),
pos as (
  select c.business_date, i.book, i.ticker, i.qty as prev_qty
  from {{ ref('stg_calendar') }} c
  join {{ ref('stg_internal_positions') }} i on i.business_date = c.prev_date
  union all
  select c.business_date, o.book, o.ticker, o.qty
  from {{ ref('stg_calendar') }} c
  join {{ source('raw', 'opening_positions') }} o on o.as_of = c.prev_date
),
by_name as (
  select px.business_date, px.book, px.ticker, pos.prev_qty * (px.close - px.prev_close) * px.usd_rate as pnl_usd
  from px join pos on pos.business_date = px.business_date and pos.ticker = px.ticker and pos.book = px.book
),
computed as (
  select business_date, book,
         case when bool_or(pnl_usd is null) then null else round(sum(pnl_usd), 2) end as computed_pnl
  from by_name group by 1, 2
)
select c.business_date, c.book, c.computed_pnl, r.pnl_usd as reported_pnl,
       round(c.computed_pnl - r.pnl_usd, 2) as diff
from computed c
join {{ ref('stg_arrivals') }} a on a.business_date = c.business_date and a.feed = 'reported_pnl'
left join {{ source('raw', 'reported_pnl') }} r on r.business_date = c.business_date and r.book = c.book
