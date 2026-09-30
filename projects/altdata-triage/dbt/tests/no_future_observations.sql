-- Look-ahead guard: no vendor observation may be dated after the as-of date.
select * from {{ ref('stg_vendor_panels') }}
where obs_date > cast('{{ var("as_of_date") }}' as date)
