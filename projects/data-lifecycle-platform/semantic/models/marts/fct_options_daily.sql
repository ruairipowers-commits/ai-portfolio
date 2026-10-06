select
    {{ dbt_utils_surrogate(['o.symbol', 'o.obs_date']) }} as option_day_id,
    o.symbol, o.obs_date, coalesce(c.gics_sector, 'Unmapped') as gics_sector,
    o.atm_iv, o.hv_20, o.atm_iv - o.hv_20 as iv_hv_spread, o.sotm_iv - o.sitm_iv as skew_25,
    o.calls_traded, o.puts_traded, o.calls_oi, o.puts_oi, o.vix
from {{ ref('stg_options') }} o
left join {{ ref('dim_company') }} c using (symbol)
