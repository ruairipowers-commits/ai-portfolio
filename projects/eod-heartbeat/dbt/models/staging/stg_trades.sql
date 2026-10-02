select t.*,
       row_number() over (partition by business_date, trade_id order by booked_time) as copy_n,
       booked_time > '{{ var("pb_cutoff_time") }}' as after_pb_cutoff
from {{ source('raw', 'trades') }} t
