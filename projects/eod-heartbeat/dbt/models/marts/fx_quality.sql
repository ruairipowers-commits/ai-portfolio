-- FX moves beyond the threshold. A rate is only flagged if it is also far from the rate two days back, so the
-- day after a bad print (when the rate returns to normal) is not flagged as a second outlier.
select business_date, ccy, usd_rate, prev_rate, round(usd_rate / nullif(prev_rate, 0) - 1, 4) as move,
       abs(usd_rate / nullif(prev_rate, 0) - 1) > {{ var("fx_move_pct") }}
         and (prev2_rate is null or abs(usd_rate / nullif(prev2_rate, 0) - 1) > {{ var("fx_move_pct") }}) as is_outlier
from (select business_date, ccy, usd_rate,
             lag(usd_rate) over w as prev_rate, lag(usd_rate, 2) over w as prev2_rate
      from {{ ref('stg_fx') }} window w as (partition by ccy order by business_date)) x
where prev_rate is not null and ccy <> 'USD'
