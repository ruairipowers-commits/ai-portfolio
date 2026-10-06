-- Coverage of the S&P 500 reference universe for each ingested dataset (FR-4). Universe = dim_company.
with universe as (select count(*) as n from {{ ref('dim_company') }}),
options_cov as (
    select 'ds-options-iv' as dataset_id, count(distinct o.symbol) as symbols_covered,
           count(distinct case when c.symbol is not null then o.symbol end) as symbols_in_universe,
           min(o.obs_date) as first_date, max(o.obs_date) as last_date, count(*) as row_count,
           avg(case when o.atm_iv is null then 1.0 else 0.0 end) as null_rate_key_measure
    from {{ ref('stg_options') }} o left join {{ ref('dim_company') }} c using (symbol)
)
select dataset_id, symbols_covered, symbols_in_universe, universe.n as universe_size,
       symbols_in_universe * 1.0 / universe.n as coverage_pct, first_date, last_date,
       date_diff('day', first_date, last_date) as history_days, row_count, null_rate_key_measure
from options_cov, universe
