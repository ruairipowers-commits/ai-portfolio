-- Feed arrivals as seen at the as-of time: anything that lands later hasn't arrived yet.
select business_date, feed, arrived_at, rows
from {{ source('raw', 'file_arrivals') }}
where arrived_at <= timestamp '{{ var("as_of") }}'
