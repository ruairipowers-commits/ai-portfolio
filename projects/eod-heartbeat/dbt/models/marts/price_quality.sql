-- Stale prices (unchanged for stale_days business days running) and outsized moves without a corporate action.
with p as (
  select business_date, ticker, close,
         lag(close) over (partition by ticker order by business_date) as prev_close,
         min(close) over w as lo, max(close) over w as hi, count(*) over w as n
  from {{ ref('stg_prices') }}
  window w as (partition by ticker order by business_date rows between {{ var("stale_days") - 1 }} preceding and current row)
)
select p.business_date, p.ticker, p.close, p.prev_close,
       (p.lo = p.hi and p.n = {{ var("stale_days") }}) as is_stale,
       abs(p.close / nullif(p.prev_close, 0) - 1) > {{ var("price_move_pct") }} and ca.ticker is null as is_outlier,
       round(p.close / nullif(p.prev_close, 0) - 1, 4) as move
from p
left join {{ source('raw', 'corp_actions') }} ca on ca.business_date = p.business_date and ca.ticker = p.ticker
where p.prev_close is not null
