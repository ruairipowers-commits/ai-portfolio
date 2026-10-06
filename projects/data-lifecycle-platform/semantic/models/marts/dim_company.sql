select symbol, company_name, gics_sector, gics_sub_industry, headquarters_location, cik
from {{ ref('stg_constituents') }}
