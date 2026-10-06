{{ config(materialized='table') }}
select cast(range as date) as date_day
from range(date '2010-01-01', date '2030-12-31', interval 1 day)
