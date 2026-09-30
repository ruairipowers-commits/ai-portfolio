select
    vendor_id,
    vendor_name,
    category,
    cast(pii_present as boolean)          as pii_present,
    cast(point_in_time as boolean)        as point_in_time,
    cast(license_derived_use as boolean)  as license_derived_use,
    delivery,
    cast(annual_price_usd as integer)     as annual_price_usd,
    notes                                 -- untrusted free text; sanitized in Python before any LLM call
from {{ source('raw', 'vendor_questionnaires') }}
