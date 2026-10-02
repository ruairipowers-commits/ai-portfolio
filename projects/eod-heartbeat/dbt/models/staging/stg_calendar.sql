-- Business dates delivered so far (one landing folder each), with the previous business date.
with d as (
  select distinct business_date from {{ source('raw', 'file_arrivals') }}
  union select distinct business_date from {{ source('raw', 'prices') }}
)
select business_date,
       coalesce(lag(business_date) over (order by business_date),
                (select max(as_of) from {{ source('raw', 'opening_prices') }})) as prev_date
from d
