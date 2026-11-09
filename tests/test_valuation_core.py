"""
Smoke tests for the pure-Python valuation logic (no Streamlit / yfinance needed).

Run with:  pytest -q
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from valuation.adjustments import AdjustmentCalculator  # noqa: E402
from valuation.asset_value import AssetValueCalculator  # noqa: E402
from valuation.earning_power import EarningPowerCalculator  # noqa: E402
from valuation.franchise_value import FranchiseValueCalculator  # noqa: E402
from valuation.beta_calculator import BetaCalculator, FFFactorCalculator  # noqa: E402


@pytest.fixture
def wmt_like_data():
    """Rough Walmart-scale inputs (USD), newest year first in every list."""
    return {
        'income_statement': {
            'revenue': [681e9, 648e9, 611e9],
            'operating_income': [29.3e9, 27.0e9, 20.4e9],
            'cogs': [511e9, 490e9, 463e9],
            'sg_and_a': [140e9, 130e9, 127e9],
            'depreciation': [12.9e9, 11.9e9, 11.0e9],
            'rd_expense': [0, 0, 0],
        },
        'balance_sheet': {
            'total_equity': 91e9, 'total_assets': 260e9,
            'ppe_net': 126e9, 'ppe_gross': 231e9, 'goodwill': 28e9, 'cash': 9e9,
            'long_term_debt': 33e9, 'short_term_debt': 6e9,
            'accounts_payable': 58e9, 'accrued_liabilities': 29e9,
            'accumulated_depreciation': 105e9, 'current_liabilities': 96e9,
            'right_of_use_assets': 13e9,
        },
        'cash_flow': {'capex': [23.8e9, 20.6e9, 16.9e9], 'depreciation': [12.9e9, 11.9e9, 11.0e9]},
        'market_data': {'market_cap': 780e9, 'shares_outstanding': 8.0e9, 'beta': 0.7, 'enterprise_value': 810e9},
        'company_info': {'sector': 'Consumer Defensive', 'industry': 'Discount Stores',
                         'country': 'United States', 'name': 'WMT'},
    }


# ---------------------------------------------------------------- beta / cost of equity

def test_blume_adjustment():
    r = BetaCalculator('TEST').calculate_blume_adjusted_beta(1.3)
    assert r['beta'] == pytest.approx(0.67 * 1.3 + 0.33)
    # Blume pulls betas toward 1.0 from both sides
    assert BetaCalculator('TEST').calculate_blume_adjusted_beta(0.5)['beta'] > 0.5
    assert BetaCalculator('TEST').calculate_blume_adjusted_beta(1.5)['beta'] < 1.5


def test_hamada_levered_beta():
    r = BetaCalculator('TEST').calculate_fundamental_beta(debt_to_equity=0.5, tax_rate=0.21, unlevered_beta=0.8)
    assert r['beta'] == pytest.approx(0.8 * (1 + 0.79 * 0.5))


def test_ff3_regression_recovers_known_loadings():
    rng = np.random.default_rng(0)
    n = 120
    idx = pd.period_range('2015-01', periods=n, freq='M')
    mkt = pd.Series(rng.normal(0.006, 0.04, n), index=idx)
    smb = pd.Series(rng.normal(0.001, 0.025, n), index=idx)
    hml = pd.Series(rng.normal(0.002, 0.03, n), index=idx)
    y = 0.001 + 1.2 * mkt - 0.4 * smb + 0.3 * hml + rng.normal(0, 0.005, n)

    reg = FFFactorCalculator.calculate_ff3_regression(y, mkt, smb, hml)
    assert reg['observations'] == n
    assert reg['beta_mkt'] == pytest.approx(1.2, abs=0.05)
    assert reg['beta_smb'] == pytest.approx(-0.4, abs=0.08)
    assert reg['beta_hml'] == pytest.approx(0.3, abs=0.08)
    assert 0.95 < reg['r_squared'] <= 1.0
    assert abs(reg['t_stats']['beta_mkt']) > 10


def test_ff3_cost_of_equity_formula():
    coe = FFFactorCalculator.ff3_cost_of_equity(0.04, 1.0, 0.5, -0.2, 0.06, 0.02, 0.03)
    assert coe == pytest.approx(0.04 + 0.06 + 0.01 - 0.006)


def test_parse_ff_csv_month_block_only():
    text = (
        "This file was created by CMPT_ME_BEME_RETS\n\n"
        ",Mkt-RF,SMB,HML,RF\n"
        "202401,1.50,-0.20,0.30,0.45\n"
        "202402,-2.00,0.10,0.00,0.42\n"
        "\nAnnual Factors: January-December\n"
        ",Mkt-RF,SMB,HML,RF\n"
        "2024,10.0,1.0,2.0,5.0\n"
    )
    df = FFFactorCalculator.parse_ff_csv(text)
    assert list(df.columns) == ['Mkt-RF', 'SMB', 'HML', 'RF']
    assert len(df) == 2  # annual rows are excluded
    assert df.loc[pd.Period('2024-01', 'M'), 'Mkt-RF'] == pytest.approx(0.015)


# ---------------------------------------------------------------- adjustments

def test_royalty_brand_value_is_growing_perpetuity():
    v = AdjustmentCalculator.calculate_brand_value_royalty(100.0, royalty_rate=0.05, discount_rate=0.07, growth_rate=0.02)
    assert v == pytest.approx(0.05 * 100 / (0.07 - 0.02))


def test_depreciation_adjustment_handles_negative_capex_sign():
    # yfinance reports capex as a negative cash flow; the sign must not create a fake add-back
    pos = AdjustmentCalculator.calculate_depreciation_adjustment(12.9e9, 23.8e9, 0.05, 126e9)
    neg = AdjustmentCalculator.calculate_depreciation_adjustment(12.9e9, -23.8e9, 0.05, 126e9)
    assert pos == neg
    assert pos == 0  # maintenance capex (17.5B) exceeds depreciation -> no over-depreciation


def test_ppe_reproduction_cost_adjustment():
    comps = {'land': 100, 'building': 100, 'fixtures': 100, 'equipment': 100, 'cip': 100}
    factors = {'land_factor': 0.5, 'building_factor': 0.864, 'fixture_factor': 0.5, 'equipment_factor': 0.5, 'cip_factor': 1.0}
    adj, details = AdjustmentCalculator.calculate_ppe_adjustment(comps, factors, reported_ppe_net=300)
    assert adj == pytest.approx(336.4 - 300)
    assert details['building']['adjusted'] == pytest.approx(86.4)


# ---------------------------------------------------------------- AV / EPV / FV end to end

def test_asset_value_components_sum(wmt_like_data):
    res = AssetValueCalculator(wmt_like_data).calculate({'brand_method': 'royalty'})
    assert res['total_av'] == pytest.approx(sum(res['components'].values()))
    assert res['book_equity'] == 91e9
    assert res['ppe_adjustment'] > 0  # reproduction cost above book, as in the Greenwald WMT case


def test_epv_equals_nopat_over_wacc(wmt_like_data):
    calc = EarningPowerCalculator(wmt_like_data)
    res = calc.calculate({'risk_free_rate': 0.043, 'beta': 0.7, 'market_risk_premium': 0.06})
    assert res['epv'] == pytest.approx(res['adjusted_nopat'] / res['wacc'])
    assert res['adjusted_nopat'] == pytest.approx(res['adjusted_operating_income'] * (1 - 0.21))
    # WACC bracketed by after-tax cost of debt and cost of equity
    coe = 0.043 + 0.7 * 0.06
    assert (0.043 + 0.02) * 0.79 < res['wacc'] < coe


def test_epv_wacc_override_accepts_percent_or_decimal(wmt_like_data):
    a = EarningPowerCalculator(wmt_like_data).calculate({'wacc': 8})
    b = EarningPowerCalculator(wmt_like_data).calculate({'wacc': 0.08})
    assert a['wacc'] == pytest.approx(0.08) == b['wacc']


def test_franchise_value_sign_follows_roic_spread(wmt_like_data):
    fv_pos = FranchiseValueCalculator(wmt_like_data).calculate_franchise_value(wacc=0.08)
    assert fv_pos['creates_value'] and fv_pos['franchise_value'] > 0
    assert fv_pos['total_value'] == pytest.approx(fv_pos['epv'] + fv_pos['franchise_value'])
    assert fv_pos['growth_rate'] <= fv_pos['perpetual_growth_cap'] < 0.08

    # ROIC below WACC -> growth destroys value -> FV = 0 in heuristic mode, < 0 in strict mode
    fv_zero = FranchiseValueCalculator(wmt_like_data).calculate_franchise_value(wacc=0.30)
    assert fv_zero['franchise_value'] == 0
    fv_strict = FranchiseValueCalculator(wmt_like_data, {'strict_course_mode': True}).calculate_franchise_value(wacc=0.30)
    assert fv_strict['franchise_value'] < 0
