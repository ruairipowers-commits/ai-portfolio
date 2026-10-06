select
    upper(trim(symbol))           as symbol,
    security                      as company_name,
    gics_sector,
    gics_sub_industry,
    headquarters_location,
    try_cast(date_added as date)  as date_added,
    nullif(trim(cast(cik as varchar)), '') as cik,
    founded
from {{ source('landing', 'constituents') }}
