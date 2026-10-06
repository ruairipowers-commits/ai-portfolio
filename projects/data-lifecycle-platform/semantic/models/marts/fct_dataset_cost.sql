-- Contract cost spread evenly over each day of the term, split across the contract's datasets.
select
    {{ dbt_utils_surrogate(['c.contract_id', 'c.dataset_id', 's.date_day']) }} as cost_id,
    s.date_day as cost_date, c.contract_id, c.customer_id, c.dataset_id,
    c.price_usd / c.n_datasets / (date_diff('day', c.start_date, c.end_date) + 1) as cost_usd
from {{ ref('stg_contracts') }} c
join {{ ref('metricflow_time_spine') }} s on s.date_day between c.start_date and c.end_date
