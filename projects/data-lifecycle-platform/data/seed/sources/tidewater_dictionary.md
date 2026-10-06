# Tidewater port congestion index — data dictionary (SYNTHETIC; Tidewater Freight Signals is fictional)

Delivered as one CSV per day. Version 3.2.

| Field | Type | Description |
|---|---|---|
| obs_date | date | Observation date (UTC) |
| port_code | string | UN/LOCODE of the port |
| vessels_waiting | integer | Container vessels at anchor waiting for a berth |
| median_dwell_hours | float | Median container dwell time at the terminal, hours |
| congestion_index | float | 0–100 composite congestion score |
| exposed_ticker | string | Ticker of a listed company with material exposure to the port |
| exposure_weight | float | Share of that company's estimated container volume through the port |
