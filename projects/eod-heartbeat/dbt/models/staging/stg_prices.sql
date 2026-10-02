select as_of as business_date, ticker, close from {{ source('raw', 'opening_prices') }}
union all
select business_date, ticker, close from {{ source('raw', 'prices') }}
