-- FR-1: every feed for every business date against its SLA, as seen at the as-of time.
select c.business_date, f.feed, f.critical,
       (c.business_date + f.sla_time::time) as sla_at,
       a.arrived_at, a.rows,
       case when a.arrived_at is not null and a.arrived_at <= c.business_date + f.sla_time::time then 'on_time'
            when a.arrived_at is not null then 'late'
            when timestamp '{{ var("as_of") }}' > c.business_date + f.sla_time::time then 'missing'
            else 'pending' end as status,
       round(extract(epoch from (coalesce(a.arrived_at, timestamp '{{ var("as_of") }}')
                                 - (c.business_date + f.sla_time::time))) / 60) as minutes_late
from {{ ref('stg_calendar') }} c
cross join {{ source('raw', 'feeds') }} f
left join {{ ref('stg_arrivals') }} a on a.business_date = c.business_date and a.feed = f.feed
