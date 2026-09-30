-- One row per vendor: deterministic quality/coverage metrics + a transparent rule score.
-- The LLM explains and recommends; it never computes these numbers.
with panel as (
    select
        vendor_id,
        min(obs_date)                                         as first_date,
        max(obs_date)                                         as last_date,
        count(*)                                              as n_rows,
        count(distinct vendor_ticker)                         as n_tickers,
        count(distinct case when is_mapped then vendor_ticker end)           as n_tickers_mapped,
        count(distinct case when in_core_universe then vendor_ticker end)    as n_core_covered,
        avg(case when metric_value is null then 1.0 else 0.0 end)            as null_rate
    from {{ ref('int_panel_mapped') }}
    group by 1
),
core as (
    select count(*) as n_core from {{ ref('security_master') }} where in_core_universe
),
metrics as (
    select
        p.vendor_id,
        p.first_date,
        p.last_date,
        p.n_rows,
        p.n_tickers,
        round(date_diff('day', p.first_date, p.last_date) / 365.25, 2)                     as history_years,
        round(p.n_tickers_mapped * 1.0 / p.n_tickers, 3)                                    as pct_tickers_mapped,
        round(p.n_core_covered * 1.0 / c.n_core, 3)                                         as core_universe_coverage,
        round(p.null_rate, 3)                                                               as null_rate,
        round(1 - p.n_rows * 1.0 /
              (p.n_tickers * (date_diff('week', p.first_date, p.last_date) + 1)), 3)        as gap_rate,
        date_diff('day', p.last_date, cast('{{ var("as_of_date") }}' as date))              as days_stale
    from panel p cross join core c
)
select
    m.*,
    q.vendor_name,
    q.category,
    q.pii_present,
    q.point_in_time,
    q.license_derived_use,
    q.delivery,
    q.annual_price_usd,
    round(
          least(m.history_years / 5.0, 1.0) * 25
        + m.pct_tickers_mapped * 25
        + greatest(1 - m.null_rate - m.gap_rate, 0) * 20
        + least(m.core_universe_coverage * 2, 1.0) * 20
        + case when m.days_stale <= 14 then 10 else 0 end
    , 1)                                                                                    as rule_score
from metrics m
join {{ ref('stg_vendor_questionnaires') }} q using (vendor_id)
