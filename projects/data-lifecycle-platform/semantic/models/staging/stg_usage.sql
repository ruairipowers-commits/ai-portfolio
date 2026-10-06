select cast(day as date) as usage_date, customer as customer_id, team as team_id, "user" as user_id,
       dataset as dataset_id, cast(queries as integer) as queries
from {{ source('landing', 'usage') }}
