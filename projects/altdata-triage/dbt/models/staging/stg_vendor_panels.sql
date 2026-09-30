select
    vendor_id,
    cast(obs_date as date)              as obs_date,
    upper(trim(ticker))                 as vendor_ticker,
    try_cast(metric_value as double)    as metric_value
from {{ source('raw', 'vendor_panels') }}
