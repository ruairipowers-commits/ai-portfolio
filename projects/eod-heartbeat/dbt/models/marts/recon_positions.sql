-- Internal positions vs the prime broker, for dates whose PB file has arrived.
select i.business_date, i.book, i.ticker, i.qty as internal_qty, p.qty as pb_qty,
       i.qty - coalesce(p.qty, 0) as diff
from {{ ref('stg_internal_positions') }} i
join {{ ref('stg_arrivals') }} a on a.business_date = i.business_date and a.feed = 'pb_positions'
left join {{ source('raw', 'pb_positions') }} p
  on p.business_date = i.business_date and p.book = i.book and p.ticker = i.ticker
