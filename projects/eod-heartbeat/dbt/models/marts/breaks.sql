-- One row per break. Detection is deterministic SQL (NFR-4); the model only explains rows from this table.
with b as (
  select business_date, case status when 'late' then 'late_file' else 'missing_file' end as break_type,
         case when status = 'missing' and critical then 'critical' when critical then 'high' else 'medium' end as severity,
         feed as entity, null::text as book, 'minutes_late' as metric, null::numeric as expected,
         minutes_late::numeric as actual, minutes_late::numeric as diff,
         case status when 'late' then 'late' else 'missing' end || case when feed = 'fx' then ',fx' else '' end as hints,
         format('%s file %s: SLA %s, %s', feed, status, to_char(sla_at, 'HH24:MI'),
                coalesce('arrived ' || to_char(arrived_at, 'HH24:MI'), 'not arrived')) as detail
  from {{ ref('file_sla') }} where status in ('late', 'missing')
  union all
  select business_date, 'duplicate_trade', 'high', trade_id, book, 'copies', 1, max(copy_n), max(copy_n) - 1,
         'duplicate', format('trade %s (%s %s) appears %s times in the OMS extract', trade_id, ticker, max(qty), max(copy_n))
  from {{ ref('stg_trades') }} group by business_date, trade_id, book, ticker having max(copy_n) > 1
  union all
  select r.business_date, 'position_break', 'high', r.ticker, r.book, 'qty', r.pb_qty, r.internal_qty, r.diff,
         concat_ws(',',
                   case when ca.ticker is not null then 'corporate_action,split' end,
                   case when d.ticker is not null then 'duplicate' end,
                   case when lt.ticker is not null then 'late_trade,timing' end),
         format('%s %s: internal %s vs prime broker %s (diff %s)%s%s%s', r.book, r.ticker, r.internal_qty, r.pb_qty, r.diff,
                case when ca.ticker is not null then format('; corporate action %s %s:1 today', ca.action, ca.ratio) end,
                case when d.ticker is not null then '; duplicated OMS trade today' end,
                case when lt.ticker is not null then format('; trade of %s booked %s after the %s PB cutoff',
                                                             lt.qty, lt.booked_time, '{{ var("pb_cutoff_time") }}') end)
  from {{ ref('recon_positions') }} r
  left join {{ source('raw', 'corp_actions') }} ca on ca.business_date = r.business_date and ca.ticker = r.ticker
  left join (select distinct business_date, ticker from {{ ref('stg_trades') }} where copy_n > 1) d
    on d.business_date = r.business_date and d.ticker = r.ticker
  left join {{ ref('stg_trades') }} lt on lt.business_date = r.business_date and lt.ticker = r.ticker
    and lt.after_pb_cutoff and lt.qty = r.diff
  where r.diff <> 0
  union all
  select p.business_date, case when p.computed_pnl is null then 'pnl_unavailable' else 'pnl_break' end,
         case when p.computed_pnl is null or abs(p.diff) > 1000000 then 'critical' else 'high' end,
         p.book, p.book, 'pnl_usd', p.reported_pnl, p.computed_pnl, p.diff,
         concat_ws(',', case when p.computed_pnl is null then 'missing,fx' end,
                   case when exists (select 1 from {{ ref('fx_quality') }} f join {{ source('raw', 'securities') }} s
                                     on s.ccy = f.ccy where f.business_date = p.business_date and f.is_outlier
                                     and s.book = p.book) then 'fx' end,
                   case when exists (select 1 from {{ source('raw', 'corp_actions') }} c join {{ source('raw', 'securities') }} s
                                     on s.ticker = c.ticker where c.business_date = p.business_date and s.book = p.book)
                        then 'corporate_action,split' end),
         case when p.computed_pnl is null then format('%s P&L cannot be computed: an input (FX or price) is missing', p.book)
              else format('%s computed P&L %s vs risk system %s (diff %s)', p.book, p.computed_pnl, p.reported_pnl, p.diff) end
  from {{ ref('pnl_explain') }} p
  where p.computed_pnl is null or abs(p.diff) > {{ var("pnl_abs_threshold_usd") }}
  union all
  select business_date, 'stale_price', 'medium', ticker, null, 'close', prev_close, close, 0, 'stale',
         format('%s close %s unchanged for %s business days', ticker, close, {{ var("stale_days") }})
  from {{ ref('price_quality') }} where is_stale
    and business_date in (select business_date from {{ ref('stg_arrivals') }} where feed = 'prices')
  union all
  select business_date, 'price_outlier', 'medium', ticker, null, 'move', prev_close, close, move, 'price',
         format('%s moved %s%% with no corporate action', ticker, round(move * 100, 1))
  from {{ ref('price_quality') }} where is_outlier
    and business_date in (select business_date from {{ ref('stg_arrivals') }} where feed = 'prices')
  union all
  select business_date, 'fx_outlier', 'high', ccy, null, 'usd_rate', prev_rate, usd_rate, move, 'fx',
         format('%s rate %s vs %s yesterday (%s%%)', ccy, usd_rate, prev_rate, round(move * 100, 1))
  from {{ ref('fx_quality') }} where is_outlier
    and business_date in (select business_date from {{ ref('stg_arrivals') }} where feed = 'fx')
)
select md5(business_date::text || break_type || entity || coalesce(book, '')) as break_id, *
from b
