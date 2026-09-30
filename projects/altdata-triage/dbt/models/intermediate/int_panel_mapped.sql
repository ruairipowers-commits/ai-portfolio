-- Map vendor ticker codes to the firm's security master.
select
    p.*,
    sm.ticker is not null            as is_mapped,
    coalesce(sm.in_core_universe, false) as in_core_universe
from {{ ref('stg_vendor_panels') }} p
left join {{ ref('security_master') }} sm
    on p.vendor_ticker = sm.ticker
