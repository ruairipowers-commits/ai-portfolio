select id as contract_id, customer_id, dataset_id, cast(start_date as date) as start_date,
       cast(end_date as date) as end_date, cast(price_usd as double) as price_usd, n_datasets, status
from {{ source('landing', 'catalog_contracts') }}
