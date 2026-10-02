-- Vendor FX rates plus USD = 1 for every date (USD is the base currency, not a vendor-supplied rate).
select as_of as business_date, ccy, usd_rate from {{ source('raw', 'opening_fx') }} where ccy <> 'USD'
union all
select business_date, ccy, usd_rate from {{ source('raw', 'fx') }} where ccy <> 'USD'
union all
select business_date, 'USD', 1.0 from {{ ref('stg_calendar') }}
union all
select max(as_of), 'USD', 1.0 from {{ source('raw', 'opening_fx') }}
