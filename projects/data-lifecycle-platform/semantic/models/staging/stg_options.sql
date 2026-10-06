-- One row per symbol per trading day. Column names follow the Hub dataset; renamed to snake_case here only.
select
    upper(trim(symbol))                    as symbol,
    cast("date" as date)                   as obs_date,
    cast(strikes_spread as double)         as strikes_spread,
    cast(calls_contracts_traded as bigint) as calls_traded,
    cast(puts_contracts_traded as bigint)  as puts_traded,
    cast(calls_open_interest as bigint)    as calls_oi,
    cast(puts_open_interest as bigint)     as puts_oi,
    cast(ATM_IV as double)                 as atm_iv,
    cast(sOTM_IV as double)                as sotm_iv,
    cast(sITM_IV as double)                as sitm_iv,
    cast(hv_20 as double)                  as hv_20,
    cast(hv_60 as double)                  as hv_60,
    cast(VIX as double)                    as vix
from {{ source('landing', 'options_iv') }}
