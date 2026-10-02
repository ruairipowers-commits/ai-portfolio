-- Internal book of record: opening + every OMS row (duplicates included — that's the bug we want to catch)
-- + ops adjustments, cumulative by business date.
with s as (select ticker, book from {{ source('raw', 'securities') }}),
grid as (select c.business_date, s.book, s.ticker from {{ ref('stg_calendar') }} c cross join s),
moves as (
  select business_date, book, ticker, qty from {{ source('raw', 'trades') }}
  union all
  select business_date, book, ticker, qty from {{ source('raw', 'adjustments') }}
)
select g.business_date, g.book, g.ticker,
       coalesce(o.qty, 0) + coalesce((select sum(m.qty) from moves m
                                      where m.book = g.book and m.ticker = g.ticker
                                        and m.business_date <= g.business_date), 0) as qty
from grid g
left join {{ source('raw', 'opening_positions') }} o on o.book = g.book and o.ticker = g.ticker
