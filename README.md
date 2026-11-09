# Greenwald Valuation Tool — Asset Value · Earnings Power · Franchise Value

A Streamlit app and a reusable Python package for valuing a company the way Bruce Greenwald teaches it at Columbia. You build value in three layers and compare each one against the market price:

1. **Asset Value (AV):** reproduction cost of the balance sheet. Book values are adjusted for intangibles the accounts leave out: brand (royalty and marketing-capitalisation methods), workforce, R&D product portfolio, PP&E and goodwill.
2. **Earnings Power Value (EPV):** normalised, no-growth earnings ÷ cost of capital. Depreciation is split into maintenance and growth capex, and growth-related marketing and R&D spend is added back.
3. **Franchise / Growth Value (FV):** what growth is worth. Growth creates value only when ROIC exceeds WACC, and the reinvestment rate *k* is solved from growth capex.

When AV ≈ EPV, there is no moat. When EPV > AV, the gap is the franchise. When the market price exceeds EPV, the price is paying for growth, and that growth needs to be justified.

## What's in the code

| Module | Contents |
|---|---|
| `valuation/asset_value.py` | AV calculator with line-by-line reproduction-cost adjustments |
| `valuation/adjustments.py` | Brand, workforce, R&D, PP&E, goodwill, and growth-capex adjustment methods |
| `valuation/earning_power.py` | EPV from adjusted NOPAT and WACC |
| `valuation/franchise_value.py` | Growth value with ROIC-vs-WACC check |
| `valuation/beta_calculator.py` | CAPM beta, Blume-adjusted beta, fundamental (levered) beta, Fama-French 3-factor regression → cost of equity |
| `data/` | yfinance fetcher and financial-statement normaliser |
| `utils/ai_financial_parser.py` | Optional: paste a 10-K excerpt and have an LLM extract the line items (bring your own API key; keys are never written into exported configs) |
| `dashboard/app_enhanced.py` | Streamlit front end: AV → EPV → FV → summary → report export |

## Run

```bash
pip install -r requirements.txt
./run.sh            # opens http://localhost:8501
```

Note: the dashboard labels are currently in Chinese. The `valuation/` package can be used on its own from Python.

## Limitations

- Statement data comes from yfinance, which has gaps and occasional mislabelled lines. Check key inputs against the 10-K.
- The intangible adjustments (royalty rate, marketing-capitalisation life, and so on) are judgement calls exposed as parameters, not estimated.

See [`CHANGELOG.md`](CHANGELOG.md) for version history.

## License

MIT
