"""
Franchise Value计算模块
基于Columbia Business School Lecture 4: Growth and Value
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional


class FranchiseValueCalculator:
    """
    Franchise Value (特许权价值/增长价值) 计算器
    
    核心公式：
    V = EPV + FV
    V = NOPAT/r + (R-r)/r × Growth Investment
    
    其中：
    - FV > 0 当且仅当 ROIC > WACC
    """
    
    def __init__(self, data: Dict, adjustments: Dict = None):
        """
        初始化Franchise Value计算器
        
        Args:
            data: 财务数据字典
            adjustments: 用户调整参数
        """
        self.data = data
        self.adjustments = adjustments or {}
        
    def calculate_roic(self, use_marginal: bool = False, method: str = 'lecture') -> Dict:
        """
        计算ROIC (Return on Invested Capital)。
        
        Args:
            use_marginal: 是否计算边际ROIC
            method: 'lecture' (课件口径，WMT约12.5%) | 'net' | 'gross'
                - lecture: 课件公式。分子=Op Income + D&A + Lease/Interest；分母=Total Assets + Acc Dep - Payables - Accrued；税后ROIC=(1-T)*分子/分母
                - net: IC = (TA - CL + STD) - Cash
                - gross: IC = TA + Acc Dep - Spontaneous Liabilities
        
        Returns:
            Dict: ROIC计算结果（含 roic_method）
        """
        bs = self.data.get('balance_sheet', {})
        income = self.data.get('income_statement', {})
        cf = self.data.get('cash_flow', {})
        
        operating_income = self._get_single_value(income.get('operating_income', 0))
        tax_rate = self.adjustments.get('tax_rate', 0.21)
        total_assets = self._get_single_value(bs.get('total_assets', 0))
        ap = abs(self._get_single_value(bs.get('accounts_payable', 0)))
        accrued = abs(self._get_single_value(bs.get('accrued_liabilities', 0)))
        acc_dep = abs(self._get_single_value(bs.get('accumulated_depreciation', 0)))
        if not acc_dep and total_assets:
            ppe_net = self._get_single_value(bs.get('ppe_net', 0))
            acc_dep = ppe_net * 0.75 if ppe_net else 0  # 估算
        
        if method == 'lecture':
            # 课件公式：分子 = Op Income + D&A + Lease payment and Interest income
            d_and_a = self._get_single_value(cf.get('depreciation', 0))
            if not d_and_a:
                d_and_a = self._get_single_value(income.get('depreciation', 0)) if isinstance(income, dict) else 0
            if isinstance(d_and_a, (list, tuple)) and d_and_a:
                d_and_a = d_and_a[0] if isinstance(d_and_a[0], (int, float)) else 0
            lease_interest = self.adjustments.get('lease_and_interest_income', 0)  # 可从附注7获取，单位与OI一致
            total_operating_profit = operating_income + float(d_and_a or 0) + float(lease_interest or 0)
            invested_capital = total_assets + float(acc_dep or 0) - float(ap or 0) - float(accrued or 0)
            if invested_capital <= 0:
                invested_capital = max(total_assets * 0.5, 1)
            nopat = total_operating_profit * (1 - tax_rate)
            average_roic = nopat / invested_capital if invested_capital > 0 else 0
            roic_method = 'lecture'
            accumulated_depreciation = float(acc_dep or 0)
            spontaneous_liabilities = float(ap or 0) + float(accrued or 0)
        else:
            nopat = operating_income * (1 - tax_rate)
            current_liabilities = self._get_single_value(bs.get('current_liabilities', 0))
            cash = self._get_single_value(bs.get('cash', 0))
            short_term_debt = self._get_single_value(bs.get('short_term_debt', 0))
            if method == 'gross':
                accumulated_depreciation = float(acc_dep or 0)
                spontaneous_liabilities = float(ap or 0) + float(accrued or 0)
                invested_capital = total_assets + accumulated_depreciation - spontaneous_liabilities
                roic_method = 'gross'
            else:
                excess_cash = cash
                invested_capital = (total_assets - current_liabilities + short_term_debt) - excess_cash
                accumulated_depreciation = 0
                spontaneous_liabilities = current_liabilities
                roic_method = 'net'
            if invested_capital <= 0:
                invested_capital = max(total_assets * 0.5, 1)
            average_roic = nopat / invested_capital if invested_capital > 0 else 0
        
        roic_override = self.adjustments.get('roic_override')
        if roic_override is not None and roic_override > 0:
            average_roic = float(roic_override)
            nopat = average_roic * invested_capital

        marginal_roic = self._calculate_marginal_roic() if use_marginal else None
        
        return {
            'nopat': nopat,
            'invested_capital': invested_capital,
            'average_roic': average_roic,
            'marginal_roic': marginal_roic,
            'operating_income': operating_income,
            'tax_rate': tax_rate,
            'accumulated_depreciation': accumulated_depreciation,
            'spontaneous_liabilities': spontaneous_liabilities,
            'roic_method': roic_method,
        }
    
    def _calculate_marginal_roic(self) -> Optional[float]:
        """
        计算边际ROIC
        
        边际ROIC = ∂Operating Income / ∂Net Assets
        使用历史数据计算增量
        """
        try:
            income_list = self.data.get('income_statement', {})
            
            if not isinstance(income_list, list) or len(income_list) < 2:
                return None
            
            # 获取最近两年的营业收入变化
            recent_oi = self._get_single_value(income_list[0].get('operating_income', 0))
            previous_oi = self._get_single_value(income_list[1].get('operating_income', 0))
            
            delta_oi = recent_oi - previous_oi
            
            # 估算资产变化（简化）
            bs = self.data.get('balance_sheet', {})
            current_assets = bs.get('total_assets', 0)
            
            # 假设资产增长与收入增长成比例
            if previous_oi > 0:
                asset_growth_rate = delta_oi / previous_oi
                delta_assets = current_assets * asset_growth_rate / (1 + asset_growth_rate)
            else:
                return None
            
            if delta_assets > 0:
                marginal_roic = delta_oi / delta_assets
                return marginal_roic
            
            return None
            
        except Exception as e:
            print(f"计算边际ROIC失败: {e}")
            return None
    
    def calculate_growth_rate(self) -> Dict:
        """
        计算盈利增长率 g
        
        g = k × ROIC + Organic growth
        
        其中:
        - k = Growth Capex / NOPAT (再投资率)
        - ROIC = Return on Invested Capital
        - Organic growth = 同店销售增长、生产率提升等
        """
        # 1. 计算ROIC（与 FV 一致使用 net 口径）
        roic_result = self.calculate_roic(method='net')
        roic = roic_result['average_roic']
        nopat = roic_result['nopat']
        
        # 2. 计算Growth Capex（折旧抓取 + Fallback + 兜底，避免 Maintenance=0 导致 g 虚高）
        cf = self.data.get('cash_flow', {})
        income = self.data.get('income_statement', {})
        
        capex = abs(self._get_single_value(cf.get('capex', 0)))
        depreciation = abs(self._get_single_value(cf.get('depreciation', 0)))
        if depreciation <= 0:
            depreciation = abs(self._get_single_value(income.get('depreciation', 0)))
        # 兜底：若数据源仍为 0，假设 Maintenance Capex = 0.8 * Total Capex（行业常见比例）
        if depreciation <= 0 and capex > 0:
            depreciation = 0.8 * capex
        # Growth Capex = Capex - Maintenance Capex，Maintenance ≈ Depreciation
        growth_capex = max(0, capex - depreciation)
        
        # 对于科技公司，还应该考虑R&D作为增长投资
        income = self.data.get('income_statement', {})
        sector = self.data.get('company_info', {}).get('sector', '')
        
        if sector == 'Technology':
            # 科技公司的R&D也是重要的增长投资
            # 从营业费用中估算R&D（如果有的话）
            # 注意：yfinance可能不直接提供R&D，这里做保守处理
            # 假设R&D约为营收的10-15%（科技公司典型水平）
            revenue = self._get_single_value(income.get('revenue', 0))
            estimated_rd = revenue * 0.12 if revenue > 0 else 0
            
            # 将部分R&D视为增长投资（如70%）
            growth_capex += estimated_rd * 0.7
        
        # 3. 计算k值（再投资率）
        k = growth_capex / nopat if nopat > 0 else 0
        
        # 限制k值在合理范围内
        # 对于科技公司，k可能超过100%（因为包含R&D）
        k = min(max(k, 0), 2.0)  # 0-200%（科技公司R&D密集可能超过100%）
        
        # 4. 计算投资驱动增长率
        investment_growth = k * roic
        
        # 5. 估算有机增长率
        organic_growth = self._estimate_organic_growth()
        
        # 6. 总增长率
        total_growth = investment_growth + organic_growth
        
        return {
            'total_growth': total_growth,
            'investment_growth': investment_growth,
            'organic_growth': organic_growth,
            'k': k,
            'roic': roic,
            'growth_capex': growth_capex,
            'capex': capex,
            'depreciation': depreciation,
            'nopat': nopat,
        }
    
    def _estimate_organic_growth(self) -> float:
        """
        估算有机增长率
        
        有机增长来源：
        1. 同店销售增长 (Same-store sales growth)
        2. 生产率提升
        3. 相对价格改善
        4. 经济增长
        """
        # 方法1：基于历史收入增长率
        income_list = self.data.get('income_statement', {})
        
        if isinstance(income_list, list) and len(income_list) >= 3:
            try:
                revenues = []
                for item in income_list[:5]:  # 最近5年
                    rev = self._get_single_value(item.get('revenue', 0))
                    if rev > 0:
                        revenues.append(rev)
                
                if len(revenues) >= 2:
                    # 计算平均增长率
                    growth_rates = []
                    for i in range(len(revenues) - 1):
                        if revenues[i+1] > 0:
                            gr = (revenues[i] - revenues[i+1]) / revenues[i+1]
                            growth_rates.append(gr)
                    
                    if growth_rates:
                        avg_growth = np.mean(growth_rates)
                        # 有机增长通常低于总增长，保守估计为总增长的50-70%
                        organic = avg_growth * 0.6
                        return max(0, min(organic, 0.10))  # 上限10%
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        
        # 方法2：使用默认值
        # 基于行业和经济环境的典型有机增长率
        sector = self.data.get('company_info', {}).get('sector', '')
        
        default_organic_growth = {
            'Technology': 0.05,
            'Consumer Cyclical': 0.03,
            'Consumer Defensive': 0.02,
            'Healthcare': 0.04,
            'Financial Services': 0.03,
            'Communication': 0.03,
            'Industrials': 0.03,
            'Energy': 0.02,
            'Utilities': 0.02,
            'Real Estate': 0.02,
            'Basic Materials': 0.03,
        }
        
        return default_organic_growth.get(sector, 0.03)  # 默认3%
    
    def calculate_franchise_value(self, wacc: float = None) -> Dict:
        """
        计算Franchise Value (特许权价值)
        
        FV只有在ROIC > WACC时才有价值
        
        Args:
            wacc: 加权平均资本成本，如不提供则自动计算
            
        Returns:
            Dict: Franchise Value计算结果
        """
        # 1. 获取ROIC。strict_course_mode 下默认使用 lecture 口径以贴合课件；否则沿用 net 口径。
        strict_course_mode = bool(self.adjustments.get('strict_course_mode', False))
        roic_method = 'lecture' if strict_course_mode else 'net'
        roic_result = self.calculate_roic(method=roic_method)
        roic = roic_result['average_roic']
        nopat = roic_result['nopat']
        
        # 2. 获取或计算WACC
        if wacc is None:
            # 从EPV计算器导入（如果已经计算）
            wacc = self.adjustments.get('wacc', 0.08)  # 默认8%
        
        # 3. 计算增长率并应用永续增长率上限（g 原则上不超过 WACC 的 80% 或长期 GDP 如 3%）
        growth_result = self.calculate_growth_rate()
        g = growth_result['total_growth']
        gdp_long_term = self.adjustments.get('gdp_long_term', 0.03)
        g_cap = max(0.8 * wacc, gdp_long_term)
        if self.adjustments.get('perpetual_growth_cap_override') is not None:
            g_cap = float(self.adjustments['perpetual_growth_cap_override'])
        g = min(g, g_cap)
        growth_result['total_growth'] = g
        growth_result['perpetual_growth_cap'] = g_cap
        
        # 4. 计算EPV (Earnings Power Value)
        epv = nopat / wacc if wacc > 0 else 0
        
        # 5. 计算Franchise Value
        # 课件主式：FV = Growth Investment × (ROIC-WACC)/WACC /(WACC-g)
        k = growth_result['k']
        growth_investment = k * nopat
        value_per_dollar = (roic - wacc) / wacc if wacc > 0 else 0

        if strict_course_mode:
            # 严格课件模式：允许 ROIC < WACC 时 FV 为负（增长摧毁价值）。
            # 为避免奇点，仅在 g 逼近 WACC 时做数值保护。
            g_safe = min(g, wacc - 0.005) if wacc > 0.005 else g
            denom = (wacc - g_safe)
            fv = growth_investment * value_per_dollar / denom if abs(denom) > 1e-9 else 0
        else:
            # 启发式模式（历史行为）
            if roic > wacc:
                # 有正的特许权价值（ROIC > WACC）
                super_years = self.adjustments.get('supernormal_growth_years', 0) or 0
                super_g = self.adjustments.get('supernormal_g', g)
                terminal_g = self.adjustments.get('terminal_g', gdp_long_term)
                if super_years > 0 and wacc > terminal_g and (wacc - terminal_g) > 0.01:
                    # 两阶段：前 super_years 年按 super_g，之后永续 terminal_g
                    fv = 0
                    for t in range(1, super_years + 1):
                        fv += growth_investment * (1 + super_g) ** t * value_per_dollar / (1 + wacc) ** t
                    tv = (growth_investment * (1 + super_g) ** super_years * (1 + terminal_g) * value_per_dollar /
                          (wacc - terminal_g) / (1 + wacc) ** super_years)
                    fv += tv
                    fv = min(fv, epv * 5)
                elif wacc > g and (wacc - g) > 0.01:
                    fv = growth_investment * value_per_dollar / (wacc - g)
                    fv = min(fv, epv * 5)
                elif g >= wacc or (wacc - g) <= 0.01:
                    high_growth_years = 10
                    discount_factor = sum([(1 / (1 + wacc)) ** year for year in range(1, high_growth_years + 1)])
                    annual_value_creation = growth_investment * value_per_dollar
                    fv = annual_value_creation * discount_factor
                    conservative_multiplier = 20
                    fv_alternative = growth_investment * value_per_dollar * conservative_multiplier
                    fv = min(fv, fv_alternative, epv * 3)
                else:
                    fv = 0
            else:
                # ROIC <= WACC，增长摧毁价值（启发式模式不展示负值）
                fv = 0
        
        # 6. 总价值
        total_value = epv + fv
        
        # 7. 与市值对比
        market_data = self.data.get('market_data', {})
        market_cap = market_data.get('market_cap', 0)
        enterprise_value = market_data.get('enterprise_value', 0)
        
        # 计算安全边际
        if enterprise_value > 0:
            margin_of_safety = (total_value - enterprise_value) / enterprise_value
        elif market_cap > 0:
            margin_of_safety = (total_value - market_cap) / market_cap
        else:
            margin_of_safety = 0
        
        return {
            'franchise_value': fv,
            'epv': epv,
            'total_value': total_value,
            'roic': roic,
            'wacc': wacc,
            'spread': roic - wacc,
            'growth_rate': g,
            'perpetual_growth_cap': g_cap,
            'nopat': nopat,
            'market_cap': market_cap,
            'enterprise_value': enterprise_value,
            'margin_of_safety': margin_of_safety,
            'fv_to_epv_ratio': fv / epv if epv > 0 else 0,
            'creates_value': roic > wacc,
            'strict_course_mode': strict_course_mode,
            'roic_method': roic_result.get('roic_method', 'net'),
        }
    
    def calculate_implied_growth_rate(self, wacc: float = None, target_value: float = None) -> Dict:
        """
        计算支撑当前股价所需的隐含永续增长率 g。
        即求 g 使得 EPV + FV(g) = target_value（默认市值）。
        """
        fv_analysis = self.calculate_franchise_value(wacc=wacc)
        epv = fv_analysis['epv']
        roic = fv_analysis['roic']
        market_data = self.data.get('market_data', {})
        mcap = target_value if target_value is not None else market_data.get('market_cap', 0)
        if mcap <= 0:
            return {'implied_g': None, 'message': '无市值数据'}
        if wacc is None:
            wacc = fv_analysis['wacc']
        if roic <= wacc:
            return {'implied_g': None, 'message': 'ROIC <= WACC 时 FV=0，无法反推 g'}
        excess = mcap - epv
        if excess <= 0:
            return {'implied_g': 0.0, 'message': '市值 <= EPV，隐含 g = 0'}
        growth_result = self.calculate_growth_rate()
        k = growth_result['k']
        nopat = growth_result['nopat']
        growth_investment = k * nopat
        value_per_dollar = (roic - wacc) / wacc
        if growth_investment * value_per_dollar <= 0:
            return {'implied_g': None, 'message': '增长投资或价值倍数为 0'}
        # FV = growth_investment * value_per_dollar / (wacc - g) = excess
        # wacc - g = growth_investment * value_per_dollar / excess
        denom = growth_investment * value_per_dollar / excess
        if denom >= wacc:
            return {'implied_g': None, 'message': '隐含 g 为负或超过 WACC'}
        implied_g = wacc - denom
        implied_g = max(0, min(implied_g, wacc - 0.01))
        return {
            'implied_g': implied_g,
            'epv': epv,
            'market_cap': mcap,
            'fv_implied': excess,
            'message': f'支撑当前市值所需永续增长率 g ≈ {implied_g:.1%}',
        }
    
    def calculate_expected_return(self, holding_period_years: int = 5) -> Dict:
        """
        计算预期收益率
        
        R = D/V + g + (1+g) × h
        
        Args:
            holding_period_years: 持有期（年）
            
        Returns:
            Dict: 预期收益率分析
        """
        # 1. 计算分配收益率 D/V
        market_data = self.data.get('market_data', {})
        market_cap = market_data.get('market_cap', 0)
        enterprise_value = market_data.get('enterprise_value', market_cap)
        
        # D/V = (Dividends + Net Share Buybacks) / Market Cap；Net Share Buybacks = Repurchase - Issuance
        cf = self.data.get('cash_flow', {})
        dividends = abs(self._get_single_value(cf.get('dividends_paid', 0)))
        stock_repurchase = abs(self._get_single_value(cf.get('stock_repurchase', 0)))
        stock_issuance = abs(self._get_single_value(cf.get('common_stock_issuance', 0)))
        net_buybacks = max(0, stock_repurchase - stock_issuance)
        total_distribution = dividends + net_buybacks
        distribution_yield = total_distribution / market_cap if market_cap > 0 else 0
        
        # 2. 计算增长率 g
        growth_result = self.calculate_growth_rate()
        g = growth_result['total_growth']
        
        # 3. 估算市盈率压缩/扩张率 h
        # h的计算需要预测未来市盈率
        # 这里提供几种情景
        
        scenarios = self._calculate_multiple_scenarios(enterprise_value, holding_period_years)
        
        # 4. 计算不同情景下的收益率
        returns = {}
        for scenario_name, h in scenarios.items():
            r = distribution_yield + g + (1 + g) * h
            returns[scenario_name] = {
                'return': r,
                'distribution_yield': distribution_yield,
                'growth': g,
                'multiple_change': h,
            }
        
        return {
            'returns_by_scenario': returns,
            'base_return': distribution_yield + g,  # 假设h=0
            'distribution_yield': distribution_yield,
            'growth_rate': g,
            'total_distribution': total_distribution,
            'enterprise_value': enterprise_value,
        }
    
    def _calculate_multiple_scenarios(self, current_ev: float, 
                                     holding_period: int) -> Dict[str, float]:
        """
        计算不同的市盈率情景
        
        Returns:
            Dict: 情景名称 -> h值 (年化市盈率变化率)
        """
        holding_period = max(1, int(holding_period))
        roic_result = self.calculate_roic()
        nopat = roic_result['nopat']
        
        if nopat <= 0:
            return {'no_change': 0}
        
        # 当前EV/NOPAT倍数
        current_multiple = current_ev / nopat if nopat > 0 else 20
        
        # 定义目标倍数情景
        scenarios = {
            '乐观': current_multiple * 1.2,      # 上涨20%
            '不变': current_multiple,             # 保持不变
            '回归均值': 15,                       # 回归到历史平均
            '悲观': current_multiple * 0.8,      # 下降20%
        }
        
        h_values = {}
        for name, target_multiple in scenarios.items():
            # 计算年化市盈率变化率
            # target = current × (1 + h)^n
            # h = (target/current)^(1/n) - 1
            if current_multiple > 0:
                h = (target_multiple / current_multiple) ** (1 / holding_period) - 1
            else:
                h = 0
            h_values[name] = h
        
        return h_values
    
    def _get_single_value(self, value):
        """获取单一数值（处理列表情况）"""
        if isinstance(value, (list, tuple)) and len(value) > 0:
            return float(value[0]) if value[0] else 0
        return float(value) if value else 0
    
    def generate_summary(self) -> Dict:
        """
        生成完整的Franchise Value分析摘要
        """
        # 1. ROIC分析
        roic_analysis = self.calculate_roic(use_marginal=True)
        
        # 2. 增长分析
        growth_analysis = self.calculate_growth_rate()
        
        # 3. Franchise Value
        fv_analysis = self.calculate_franchise_value()
        
        # 4. 预期收益率
        return_analysis = self.calculate_expected_return()
        
        # 5. 综合评估
        creates_value = fv_analysis['creates_value']
        roic = fv_analysis['roic']
        wacc = fv_analysis['wacc']
        margin_of_safety = fv_analysis['margin_of_safety']
        
        # 投资建议
        if creates_value and margin_of_safety > 0.3:
            recommendation = "强烈买入"
            reason = f"ROIC ({roic:.1%}) 显著高于WACC ({wacc:.1%})，且有30%+安全边际"
        elif creates_value and margin_of_safety > 0:
            recommendation = "买入"
            reason = f"ROIC ({roic:.1%}) 高于WACC ({wacc:.1%})，有正安全边际"
        elif creates_value:
            recommendation = "持有"
            reason = "创造价值但市场已充分定价"
        else:
            recommendation = "观望"
            reason = f"ROIC ({roic:.1%}) 低于WACC ({wacc:.1%})，增长摧毁价值"
        
        return {
            'roic_analysis': roic_analysis,
            'growth_analysis': growth_analysis,
            'franchise_value_analysis': fv_analysis,
            'return_analysis': return_analysis,
            'recommendation': recommendation,
            'reason': reason,
        }


def format_currency(value: float, currency: str = 'USD') -> str:
    """格式化货币显示"""
    if abs(value) >= 1e12:
        return f"${value/1e12:.2f}T"
    elif abs(value) >= 1e9:
        return f"${value/1e9:.2f}B"
    elif abs(value) >= 1e6:
        return f"${value/1e6:.2f}M"
    else:
        return f"${value:,.0f}"
