select {{ dbt_utils_surrogate(['usage_date', 'team_id', 'dataset_id']) }} as usage_id, *
from {{ ref('stg_usage') }}
