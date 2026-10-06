select id as dataset_id, title, vendor_id, category, licence, price_model, coalesce(list_price_usd, 0) as list_price_usd
from {{ source('landing', 'catalog_datasets') }}
