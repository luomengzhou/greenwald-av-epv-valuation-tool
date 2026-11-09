"""
调整计算模块 - 各种财务调整的计算逻辑
"""
import numpy as np
from typing import Dict, List, Tuple


class AdjustmentCalculator:
    """财务调整计算类"""

    @staticmethod
    def get_industry_royalty_rate_range(sector: str = "", industry: str = "") -> Tuple[float, float]:
        """
        获取行业特许权费率范围（用于品牌价值估算）。
        
        Returns:
            (low, high) 费率区间；若无法识别则返回空区间 (0, 0)
        """
        s = (sector or "").strip().lower()
        i = (industry or "").strip().lower()
        text = f"{s} {i}"
        
        if "luxury" in text or "luxuries" in text or "apparel" in text or "jewelry" in text or "cosmetic" in text:
            return (0.05, 0.08)
        if "tech" in text or "software" in text or "semiconductor" in text or "internet" in text:
            return (0.02, 0.04)
        if "retail" in text or "consumer" in text or "supermarket" in text or "discount" in text:
            return (0.005, 0.01)
        
        return (0.0, 0.0)
    
    @staticmethod
    def calculate_brand_value_royalty(revenue: float, royalty_rate: float = 0.05,
                                     discount_rate: float = 0.07, growth_rate: float = 0.02) -> float:
        """
        使用特许权费法计算品牌价值
        
        Args:
            revenue: 营业收入
            royalty_rate: 特许费率
            discount_rate: 折现率
            growth_rate: 永续增长率
            
        Returns:
            float: 品牌价值
        """
        # 确保所有输入都是数字
        revenue = float(revenue) if revenue else 0
        royalty_rate = float(royalty_rate) if royalty_rate else 0.05
        discount_rate = float(discount_rate) if discount_rate else 0.07
        growth_rate = float(growth_rate) if growth_rate else 0.02
        
        if revenue == 0:
            return 0
        
        if discount_rate <= growth_rate:
            growth_rate = discount_rate - 0.02  # 调整增长率
        
        if discount_rate - growth_rate <= 0:
            return 0
        
        pv_factor = 1 / (discount_rate - growth_rate)
        brand_value = royalty_rate * revenue * pv_factor
        
        return brand_value
    
    @staticmethod
    def calculate_brand_value_marketing(marketing_expense: float, eva: float,
                                       brand_role: float = 0.15,
                                       discount_rate: float = 0.07,
                                       growth_rate: float = 0.02) -> float:
        """
        使用营销公司法计算品牌价值
        
        Args:
            marketing_expense: 营销费用
            eva: 经济增加值 (ROIC - WACC) * IC
            brand_role: 品牌作用比
            discount_rate: 折现率
            growth_rate: 永续增长率
            
        Returns:
            float: 品牌价值
        """
        if discount_rate <= growth_rate:
            growth_rate = discount_rate - 0.02
        
        pv_factor = 1 / (discount_rate - growth_rate)
        brand_value = eva * brand_role * pv_factor
        
        return brand_value
    
    @staticmethod
    def calculate_workforce_value(total_compensation: float, 
                                  training_cost_ratio: float = 0.10) -> float:
        """
        计算员工队伍价值
        
        Args:
            total_compensation: 员工总薪酬
            training_cost_ratio: 招聘培训成本比例
            
        Returns:
            float: 员工队伍价值
        """
        return total_compensation * training_cost_ratio
    
    @staticmethod
    def calculate_product_portfolio_value(rd_expenses: List[float],
                                         depreciation_rate: float = 0.20) -> float:
        """
        计算产品组合价值
        
        Args:
            rd_expenses: 历年R&D支出列表（从最新到最早）
            depreciation_rate: R&D折旧率
            
        Returns:
            float: 产品组合价值
        """
        portfolio_value = 0
        for i, rd in enumerate(rd_expenses):
            # 每年折旧rate的i次方
            depreciation_factor = (1 - depreciation_rate) ** i
            portfolio_value += rd * depreciation_factor
        
        return portfolio_value
    
    @staticmethod
    def calculate_ppe_adjustment(ppe_components: Dict, adjustment_factors: Dict,
                                 reported_ppe_net: float = 0) -> Tuple[float, Dict]:
        """
        计算PPE调整（Lecture 2 口径：调整额 = 调整后净值 - 报表净值，可为正如 WMT +46b）
        
        Args:
            ppe_components: PPE 各分项 Gross {'land': x, 'building': y, 'fixtures', 'equipment', 'cip'}
            adjustment_factors: 分项系数 {'land_factor': 0.5, 'building_factor': 0.864, ...}
            reported_ppe_net: 报表 PPE 净值
            
        Returns:
            Tuple[float, Dict]: (调整额, 详细)
        """
        details = {}
        component_map = {
            'land': 'land_factor',
            'building': 'building_factor',
            'fixtures': 'fixture_factor',
            'equipment': 'equipment_factor',
            'cip': 'cip_factor',
        }
        adjusted_net = 0
        for component, factor_key in component_map.items():
            original_value = ppe_components.get(component, 0)
            factor = adjustment_factors.get(factor_key, 1.0)
            adjusted_value = original_value * factor
            adjusted_net += adjusted_value
            details[component] = {
                'original': original_value,
                'factor': factor,
                'adjusted': adjusted_value,
            }
        total_adjustment = adjusted_net - reported_ppe_net if reported_ppe_net else (adjusted_net - sum(ppe_components.get(k, 0) for k in component_map))
        return total_adjustment, details
    
    @staticmethod
    def calculate_goodwill_adjustment(goodwill_history: List[Dict],
                                     acquisition_goodwill: float = 0) -> Tuple[float, str]:
        """
        计算商誉调整
        
        Args:
            goodwill_history: 商誉历史 [{'year': 2025, 'amount': x}, ...]
            acquisition_goodwill: 需要剔除的收购商誉
            
        Returns:
            Tuple[float, str]: (调整额, 说明)
        """
        if not goodwill_history:
            return 0, "无商誉数据"
        
        current_goodwill = goodwill_history[0].get('amount', 0)
        
        if acquisition_goodwill > 0:
            adjustment = -acquisition_goodwill
            explanation = f"剔除收购商誉 ${acquisition_goodwill/1e9:.1f}B"
        else:
            adjustment = -current_goodwill
            explanation = f"剔除全部商誉 ${current_goodwill/1e9:.1f}B"
        
        return adjustment, explanation
    
    @staticmethod
    def calculate_depreciation_adjustment(depreciation: float, capex: float,
                                         revenue_growth: float = 0,
                                         ppe_value: float = 0) -> float:
        """
        计算折旧调整（过度折旧）
        
        方法：维护性资本支出 vs 折旧费用
        
        Args:
            depreciation: 折旧费用
            capex: 资本支出
            revenue_growth: 营收增长率
            ppe_value: PPE账面价值
            
        Returns:
            float: 过度折旧额（正数表示过度折旧）
        """
        # yfinance 的 Capital Expenditure 为负数（现金流出），统一取绝对值，
        # 否则 maintenance_capex 会被截为 0，导致整笔折旧被当作“过度折旧”加回
        capex = abs(float(capex or 0))
        depreciation = abs(float(depreciation or 0))

        # 估算增长性资本支出
        growth_capex = ppe_value * max(revenue_growth, 0) if ppe_value > 0 else 0
        
        # 维护性资本支出
        maintenance_capex = max(0, capex - growth_capex)
        
        # 过度折旧 = 折旧 - 维护性资本支出
        over_depreciation = depreciation - maintenance_capex
        
        return max(0, over_depreciation)  # 只返回过度折旧（正值）
    
    @staticmethod
    def calculate_marketing_growth_expense(current_marketing: float,
                                          brand_value: float,
                                          amortization_years: float = 15) -> float:
        """
        计算营销增长支出
        
        Args:
            current_marketing: 当期营销费用
            brand_value: 品牌价值
            amortization_years: 摊销年限
            
        Returns:
            float: 营销增长支出
        """
        brand_amortization = brand_value / amortization_years
        growth_expense = current_marketing - brand_amortization
        
        return max(0, growth_expense)  # 只返回正值
    
    @staticmethod
    def calculate_rd_growth_expense(current_rd: float,
                                   historical_rd: List[float],
                                   product_cycle_years: float = 5) -> float:
        """
        计算R&D增长支出
        
        Args:
            current_rd: 当期R&D支出
            historical_rd: 历史R&D支出列表
            product_cycle_years: 产品周期年数
            
        Returns:
            float: R&D增长支出
        """
        if not historical_rd:
            return 0
        
        avg_rd = np.mean(historical_rd)
        maintenance_rd = avg_rd / product_cycle_years if product_cycle_years > 0 else avg_rd
        growth_expense = current_rd - maintenance_rd
        
        return max(0, growth_expense)
