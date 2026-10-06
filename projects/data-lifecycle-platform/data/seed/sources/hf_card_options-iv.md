---
# Offline copy for the demo, RECONSTRUCTED from the Hugging Face listing of gauss314/options-IV-SP500 (licence tag,
# size, column list as shown in the Hub viewer on 4 Oct 2026). `dlp fetch` replaces it with the real card and the
# real `features` from the Hub API.
license: apache-2.0
task_categories: [tabular-classification, tabular-regression]
size_categories: [1M<n<10M]
dataset_info:
  features:
    - {name: symbol, dtype: string}
    - {name: date, dtype: string}
    - {name: strikes_spread, dtype: float64}
    - {name: calls_contracts_traded, dtype: int64}
    - {name: puts_contracts_traded, dtype: int64}
    - {name: calls_open_interest, dtype: int64}
    - {name: puts_open_interest, dtype: int64}
    - {name: DITM_IV, dtype: float64}
    - {name: ITM_IV, dtype: float64}
    - {name: sITM_IV, dtype: float64}
    - {name: ATM_IV, dtype: float64}
    - {name: sOTM_IV, dtype: float64}
    - {name: OTM_IV, dtype: float64}
    - {name: DOTM_IV, dtype: float64}
    - {name: hv_20, dtype: float64}
    - {name: hv_60, dtype: float64}
    - {name: hv_120, dtype: float64}
    - {name: hv_200, dtype: float64}
    - {name: VIX, dtype: float64}
---
# options-IV-SP500

Options data for S&P 500 stocks: implied volatility by moneyness (deep in the money to deep out of the money),
historical volatility over 20 to 200 days, contracts traded and open interest for calls and puts, and the VIX.
3.16 million rows.
