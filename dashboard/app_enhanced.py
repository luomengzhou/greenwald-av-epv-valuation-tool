"""
价值投资分析工具 - 增强版
包含详细的调整说明、手动输入和交互功能
"""
import streamlit as st
import sys
import json
from pathlib import Path
from datetime import datetime
import pandas as pd

# 工具函数
def _parse_optional_billion(text: str):
    if text is None:
        return None
    s = str(text).strip()
    if s == "":
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _get_report_year_label(processor, year_idx: int) -> str:
    def _pick_year(df):
        if df is None or df.empty or df.shape[1] <= year_idx:
            return None
        col = df.columns[year_idx]
        if hasattr(col, "year"):
            return str(col.year)
        s = str(col)
        import re
        m = re.search(r"(20\d{2})", s)
        return m.group(1) if m else None
    year = _pick_year(processor.balance_sheet) or _pick_year(processor.income_statement) or _pick_year(processor.cash_flow)
    label = ["最新财年 (T)", "上一财年 (T-1)", "前两财年 (T-2)"][year_idx]
    return f"{year} 财年 | {label}" if year else label


# 配置导入/导出使用的 session_state keys
CONFIG_KEYS = [
    # 侧边栏参数
    'brand_method', 'brand_royalty_rate', 'brand_role', 'use_industry_royalty',
    'sidebar_discount', 'sidebar_growth', 'market_risk_premium',
    'beta_method', 'workforce_cost_ratio', 'rd_growth_pct',
    # 数据缺失修正
    'override_depreciation_b_input', 'override_capex_b_input',
    'override_rou_b_input', 'override_rd_b_input',
    # Lecture 2 补充项
    'adj_receivables_default_b', 'adj_inventory_lifo_fifo_b',
    'adj_equity_method_b', 'adj_pension_b',
    # PPE / 商誉 / 员工等
    'ppe_override_b', 'ppe_land_area', 'ppe_land_price',
    'ppe_building_area', 'ppe_building_price',
    'gw_not_digested_b', 'gw_integration_year', 'gw_remove_pct',
    'num_regular', 'salary_regular', 'ratio_regular',
    'num_management', 'salary_management', 'ratio_management',
    # EPV
    'epv_p_catastrophic', 'epv_lambda',
    # FV
    'roic_lease_interest', 'strict_course_mode', 'gdp_lt', 'g_cap_ov',
    'super_years', 'super_g', 'term_g',
    # AI 配置
    'ai_provider', 'ai_model',  # API keys deliberately excluded from saved config
    # 手动覆盖
    'wacc_override_pct', 'roic_override_pct',
]


def _collect_config_snapshot() -> dict:
    return {k: st.session_state.get(k) for k in CONFIG_KEYS if k in st.session_state}


def _apply_config_snapshot(cfg: dict) -> int:
    count = 0
    for k, v in (cfg or {}).items():
        if k in CONFIG_KEYS:
            st.session_state[k] = v
            count += 1
    return count

# 添加项目根目录到路径
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from data.api_fetcher import DataFetcher
from data.data_processor import DataProcessor
import valuation.asset_value as asset_value_module
from valuation.adjustments import AdjustmentCalculator
from valuation.earning_power import EarningPowerCalculator
from valuation.beta_calculator import BetaCalculator, get_recommended_beta_method, INDUSTRY_PRACTICE
from valuation.franchise_value import FranchiseValueCalculator
from dashboard.components.visualizations import ValuationVisualizer
from dashboard.components.export import ReportExporter
from dashboard.components.tooltips import AV_ADJUSTMENTS_INFO, WACC_INFO
from config.settings import UI_CONFIG, MARKETS, BETA_METHODS
from utils.ai_financial_parser import parse_financial_text

# 页面配置
st.set_page_config(
    page_title=UI_CONFIG['page_title'],
    page_icon=UI_CONFIG['page_icon'],
    layout=UI_CONFIG['layout'],
    initial_sidebar_state=UI_CONFIG['sidebar_state']
)

# 标题
st.title('📊 价值投资分析工具 (增强版)')
st.markdown('*基于 Graham & Dodd 方法论 - 详细调整和交互式分析*')
st.divider()

# 初始化 session state
if 'analyzed' not in st.session_state:
    st.session_state.analyzed = False
if 'financial_data' not in st.session_state:
    st.session_state.financial_data = None
if 'show_mcap_chart' not in st.session_state:
    st.session_state.show_mcap_chart = False

# 侧边栏 - 输入参数
with st.sidebar:
    st.header('📝 基本信息')
    
    # 股票代码 / 公司名输入
    ticker = st.text_input(
        '股票代码 / 公司名 / 简称（含中文/首字母）',
        value='WMT',
        help='可填：代码（WMT、0700.HK、600519）、英文名（NVIDIA、starbuck）、中文名（贵州茅台）、简称/首字母（如 pingan / zgpa 等）。将自动解析为证券代码后再拉取数据。'
    )
    
    # 市场选择（简化）
    market = st.selectbox(
        '市场',
        options=list(MARKETS.keys()),
        format_func=lambda x: MARKETS[x]['name']
    )
    
    # 分析按钮
    analyze_button = st.button('🔍 开始分析', type='primary', use_container_width=True)

    # AI 财报解析助手
    st.subheader('🤖 AI 财报解析助手')
    ai_text = st.text_area(
        '📝 粘贴财报片段（AI 自动提取）',
        height=140,
        key='ai_financial_text',
        help='可粘贴 PPE、折旧、租赁等相关段落，AI 将提取关键数字并填入对应输入框'
    )
    ai_provider = st.selectbox(
        '模型提供方',
        options=['openai', 'anthropic'],
        index=0,
        key='ai_provider'
    )
    openai_api_key = st.text_input(
        'OpenAI API Key（可选）',
        type='password',
        key='openai_api_key'
    )
    anthropic_api_key = st.text_input(
        'Anthropic API Key（可选）',
        type='password',
        key='anthropic_api_key'
    )
    ai_model = st.text_input(
        '模型名称',
        value='gpt-4o',
        key='ai_model',
        help='OpenAI: gpt-4o / gpt-4o-mini；Anthropic: claude-3-5-sonnet-20240620 等'
    )
    if st.button('✨ 解析并填充', key='ai_parse_btn'):
        api_key_override = openai_api_key if ai_provider == 'openai' else anthropic_api_key
        parsed, raw, err = parse_financial_text(ai_text, ai_provider, ai_model, api_key_override=api_key_override)
        if err:
            st.error(f'AI 解析失败：{err}')
        elif not parsed:
            st.warning('AI 未解析出可用数值，请尝试更完整的片段。')
        else:
            # 映射到 session_state
            mapping = {
                'ppe_adjustment_b': 'ppe_override_b',
                'land_area_k_sqft': 'ppe_land_area',
                'land_price_per_sqft': 'ppe_land_price',
                'building_area_k_sqft': 'ppe_building_area',
                'building_price_per_sqft': 'ppe_building_price',
                'depreciation_b': 'override_depreciation_b_input',
                'capex_b': 'override_capex_b_input',
                'rou_b': 'override_rou_b_input',
            }
            for src, dst in mapping.items():
                if src in parsed and parsed[src] is not None:
                    val = parsed[src]
                    if isinstance(val, str):
                        try:
                            val = float(val.replace(",", ""))
                        except ValueError:
                            pass
                    st.session_state[dst] = val
            st.session_state['ai_last_parsed'] = parsed
            st.success('已填充可识别的数值（可在对应输入框查看/微调）')
            st.json(parsed)

    st.subheader('🛠️ 模型覆盖')
    wacc_override_pct = st.number_input(
        'WACC 覆盖 (%)（0=不覆盖）',
        min_value=0.0, max_value=50.0, value=0.0, step=0.1,
        key='wacc_override_pct'
    )
    roic_override_pct = st.number_input(
        'ROIC 覆盖 (%)（0=不覆盖）',
        min_value=0.0, max_value=100.0, value=0.0, step=0.1,
        key='roic_override_pct'
    )

    st.divider()

    # 配置保存/加载
    st.subheader('💾 配置管理')
    cfg_payload = json.dumps(_collect_config_snapshot(), ensure_ascii=False, indent=2)
    st.download_button(
        '💾 保存当前配置',
        data=cfg_payload,
        file_name=f'{ticker}_config.json',
        mime='application/json',
        use_container_width=True
    )
    uploaded_cfg = st.file_uploader('📂 加载配置', type=['json'])
    if st.button('应用配置', key='apply_config_btn'):
        if uploaded_cfg is None:
            st.warning('请先选择配置文件')
        else:
            try:
                cfg_data = json.load(uploaded_cfg)
                applied = _apply_config_snapshot(cfg_data)
                st.success(f'已载入配置（{applied} 项）')
                st.rerun()
            except Exception as e:
                st.error(f'配置加载失败：{e}')

    st.divider()
    
    # 高级参数设置（子项默认折叠，降低首屏密度）
    with st.expander('⚙️ 高级参数设置', expanded=False):
        with st.expander('🏷️ 品牌估值', expanded=False):
            st.subheader('品牌估值')
            brand_method = st.radio(
                '品牌估值方法',
                ['discounted_marketing', 'royalty', 'marketing'],
                index=2,
                format_func=lambda x: {'discounted_marketing': '营销费用折现 (~$73bn 量级)', 'royalty': '特许权费法', 'marketing': '营销公司法 EVA×RoB×PV (~$47bn 量级)'}[x],
                key='brand_method'
            )
            with st.expander('📖 方法说明'):
                st.markdown(AV_ADJUSTMENTS_INFO['brand_value']['theory'])
            use_industry_royalty = st.checkbox('使用行业特许费率 (建议)', value=True, key='use_industry_royalty')
            brand_royalty_rate = st.slider('特许费率 (%)', 0.5, 8.0, 1.0, 0.1, key='brand_royalty_rate') / 100
            if use_industry_royalty:
                comp_info = (st.session_state.get('financial_data') or {}).get('company_info', {})
                low, high = AdjustmentCalculator.get_industry_royalty_rate_range(
                    comp_info.get('sector', ''), comp_info.get('industry', '')
                )
                if low > 0 and high > 0:
                    st.caption(f'行业建议区间：{low*100:.1f}% - {high*100:.1f}%')
                else:
                    st.caption('行业区间未知，将使用默认费率或手动输入')
            brand_role = st.slider('品牌作用比 (%)', 5, 30, 15, 1, key='brand_role') / 100

        with st.expander('📐 折现参数', expanded=False):
            st.subheader('折现参数')
            discount_rate = st.slider('折现率 (%)', 5, 15, 7, 1, key='sidebar_discount') / 100
            growth_rate = st.slider('永续增长率 (%)', 0, 5, 2, 1, key='sidebar_growth') / 100

        with st.expander('📊 WACC参数', expanded=False):
            st.subheader('WACC参数')
            with st.expander('📖 WACC说明'):
                st.markdown(WACC_INFO)
            market_risk_premium = st.slider('市场风险溢价 (%)', 4, 10, 6, 1, key='market_risk_premium') / 100

        with st.expander('β Beta设置', expanded=False):
            st.subheader('Beta设置')
            beta_method = st.selectbox(
                'Beta计算方法',
                options=list(BETA_METHODS.keys()),
                format_func=lambda x: BETA_METHODS[x]['name'],
                help='选择资产定价模型',
                key='beta_method'
            )
            with st.expander(f'📖 {BETA_METHODS[beta_method]["name"]} 说明'):
                st.markdown(BETA_METHODS[beta_method]['description'])
                st.code(BETA_METHODS[beta_method]['formula'], language='python')
                st.info(f"**适用场景**: {BETA_METHODS[beta_method]['usage']}")
            with st.expander('🏢 业界实践参考'):
                st.markdown(INDUSTRY_PRACTICE)

        with st.expander('⚙️ 其他参数', expanded=False):
            st.subheader('其他参数')
            smoothing_options = [
                (3, '近3年平均（默认，推荐）'),
                (5, '近5年平均'),
                (7, '近7年平均（稳定型）'),
            ]
            smoothing_years = st.selectbox(
                '利润平滑周期',
                options=[o[0] for o in smoothing_options],
                format_func=lambda x: next(l for n, l in smoothing_options if n == x),
                index=0,
                help='默认3年与课件一致；成熟稳定型可用7年'
            )
            data_year_index = st.selectbox(
                'AV/EPV 使用报表年份',
                options=[0, 1, 2],
                format_func=lambda x: ['最新财年 (T)', '上一财年 (T-1)', '前两财年 (T-2)'][x],
                index=0,
                help='选择用于资产价值与盈利能力的原始报表年份'
            )
            smoothing_method = st.selectbox(
                '平滑方法',
                options=['simple', 'weighted', 'ttm'],
                format_func=lambda x: {'simple': '算术平均', 'weighted': '加权平均(近期权重大)', 'ttm': 'TTM(仅最近一年)'}[x],
                index=0,
                help='weighted 使用权重 [1,2,...,n]；TTM 不平滑，用最近一年'
            )
            workforce_cost_ratio = st.slider('员工培训成本比例 (%)', 5, 20, 10, 1, key='workforce_cost_ratio') / 100

        with st.expander('🔬 R&D 增长性支出', expanded=False):
            st.subheader('R&D 增长性支出（科技公司）')
            rd_growth_pct = st.slider(
                'R&D 视为增长性支出的比例 (%)',
                0, 100, 85,
                help='科技巨头通常 80–90% 的 R&D 视为增长投入可加回利润；其他行业可据实调低',
                key='rd_growth_pct'
            )
            rd_growth_ratio = rd_growth_pct / 100

# 主内容区域
if analyze_button or st.session_state.analyzed:
    if analyze_button:  # 只在点击按钮时重新获取数据
        with st.spinner(f'正在获取 {ticker} 的财务数据...'):
            try:
                # 1. 获取数据
                fetcher = DataFetcher(ticker, market)
                financial_data = fetcher.get_all_financial_data()
                
                # 检查数据
                if not financial_data['company_info']:
                    st.error(
                        f'❌ 无法获取“{ticker}”的数据（可能解析失败或市场选择不匹配）。'
                        f'建议：1）换更完整的公司名/英文名；2）直接输入代码（如 NVDA、0700.HK、600519）；3）确认市场选择正确。'
                    )
                    st.stop()
                
                # 保存到 session state（若接口解析了公司名→代码，后续分析用解析后的代码）
                st.session_state.financial_data = financial_data
                st.session_state.analyzed = True
                st.session_state.fetcher = fetcher
                st.session_state.effective_ticker = financial_data.get('resolved_ticker', ticker)
            except Exception as e:
                st.error(f'❌ 数据获取失败: {str(e)}')
                st.stop()
    
    # 从 session state 读取数据（分析时用解析后的代码，如 NVDA）
    financial_data = st.session_state.financial_data
    fetcher = st.session_state.get('fetcher')
    ticker_for_analysis = st.session_state.get('effective_ticker', ticker)
    if financial_data.get('resolved_ticker'):
        st.info(f"已根据公司名解析为股票代码：**{ticker}** → **{financial_data['resolved_ticker']}**，以下分析使用 {financial_data['resolved_ticker']} 的数据。")
    
    # 2. 处理数据（使用侧边栏选择的报表年份）
    processor = DataProcessor(financial_data)
    try:
        processed_data = processor.get_latest_year_data(data_year_index)
    except TypeError:
        # 兼容：若 data_processor 未更新为带 year_idx 的版本，则用默认最新年
        processed_data = processor.get_latest_year_data()
    viz = ValuationVisualizer()
    
    # 添加历史数据，并将所选报表年份对齐到索引 0（避免计算器默认取 [0] 时与 UI 年份不一致）
    processed_data['income_statement'] = processor.extract_income_statement_items(7)
    processed_data['cash_flow'] = processor.extract_cash_flow_items(5)

    def _rotate_to_front(arr, idx):
        if not isinstance(arr, list) or not arr:
            return arr
        if idx <= 0 or idx >= len(arr):
            return arr
        return arr[idx:] + arr[:idx]

    for _k in ('revenue', 'cogs', 'operating_income', 'ebit', 'net_income', 'depreciation', 'rd_expense', 'sg_and_a'):
        if _k in processed_data.get('income_statement', {}):
            processed_data['income_statement'][_k] = _rotate_to_front(processed_data['income_statement'][_k], data_year_index)
    for _k in ('operating_cash_flow', 'capex', 'free_cash_flow', 'depreciation_cf', 'dividends_paid', 'stock_repurchase', 'common_stock_issuance'):
        if _k in processed_data.get('cash_flow', {}):
            processed_data['cash_flow'][_k] = _rotate_to_front(processed_data['cash_flow'][_k], data_year_index)
    
    # 数据完整性检查（关键字段 0/None 则视为缺失）
    _check_fn = getattr(DataProcessor, 'check_critical_data_completeness', None)
    if callable(_check_fn):
        data_completeness = _check_fn(processed_data, data_year_index)
    else:
        data_completeness = {
            k: {'value': 0, 'missing': False, 'label': k, 'hint': ''}
            for k in ('depreciation', 'capex', 'right_of_use_assets', 'rd_expense')
        }
    any_missing = any(v.get('missing') for v in data_completeness.values())
    if 'data_completeness' not in st.session_state or st.session_state.get('data_completeness_ticker') != ticker_for_analysis:
        st.session_state.data_completeness = data_completeness
        st.session_state.data_completeness_ticker = ticker_for_analysis
    else:
        st.session_state.data_completeness = data_completeness
    
    # Sidebar：关键数据缺失警告与手动修正（单位：十亿 $B）
    override_dep_b = None
    override_capex_b = None
    override_rou_b = None
    override_rd_b = None
    with st.sidebar:
        missing_items = []
        if any_missing:
            st.error('⚠️ 关键数据缺失警告')
            st.caption('yfinance 可能未抓取到以下项，会导致 ROIC/Growth/AV 失真。请查阅年报后手动填写（单位：十亿美元 $B）。')
            with st.expander('📝 手动修正缺失数据（$B）', expanded=True):
                comp = st.session_state.data_completeness
                if comp['depreciation']['missing']:
                    missing_items.append('折旧与摊销（Depreciation & Amortization）')
                    st.caption('**Depreciation & Amortization** — 年报 Cash Flow Statement')
                    override_dep = st.number_input(
                        '折旧与摊销 ($B)',
                        min_value=0.0, value=float(st.session_state.get('override_depreciation_b_input') or 0), step=0.5, format='%.2f',
                        key='override_depreciation_b_input',
                        help='当前 API 值为 0，请从年报现金流量表补充'
                    )
                    override_dep_b = override_dep if (override_dep is not None and override_dep > 0) else None
                else:
                    override_dep_b = None
                if comp['capex']['missing']:
                    missing_items.append('资本支出（Capex）')
                    st.caption('**Capital Expenditure** — 年报 Cash Flow Statement')
                    override_capex = st.number_input(
                        '资本支出 ($B)',
                        min_value=0.0, value=float(st.session_state.get('override_capex_b_input') or 0), step=0.5, format='%.2f',
                        key='override_capex_b_input',
                        help='当前 API 值为 0，请从年报现金流量表补充'
                    )
                    override_capex_b = override_capex if (override_capex is not None and override_capex > 0) else None
                else:
                    override_capex_b = None
                if comp['right_of_use_assets']['missing']:
                    missing_items.append('经营租赁使用权资产（ROU）')
                    st.caption('**Operating Lease Right-of-Use Assets** — 年报 Balance Sheet (ASC 842)')
                    override_rou = st.number_input(
                        '经营租赁使用权资产 ($B)',
                        min_value=0.0, value=float(st.session_state.get('override_rou_b_input') or 0), step=0.5, format='%.2f',
                        key='override_rou_b_input',
                        help='当前 API 值为 0，请从年报资产负债表补充'
                    )
                    override_rou_b = override_rou if (override_rou is not None and override_rou > 0) else None
                else:
                    override_rou_b = None
                if comp['rd_expense']['missing']:
                    missing_items.append('研发费用（R&D）')
                    st.caption('**R&D Expenses** — 年报 Income Statement（科技公司必填）')
                    override_rd = st.number_input(
                        '研发费用 ($B)',
                        min_value=0.0, value=float(st.session_state.get('override_rd_b_input') or 0), step=0.5, format='%.2f',
                        key='override_rd_b_input',
                        help='当前 API 值为 0，请从年报利润表补充'
                    )
                    override_rd_b = override_rd if (override_rd is not None and override_rd > 0) else None
                else:
                    override_rd_b = None
        
        # Lecture 2 资产价值补充项（手动输入）
        bs = processed_data.get('balance_sheet', {})
        receivables = float(bs.get('accounts_receivable', 0) or 0)
        inventory = float(bs.get('inventory', 0) or 0)
        suggested_receivables_default_b = (receivables * 0.01) / 1e9 if receivables > 0 else 0.0
        suggested_inventory_adj_b = 0.0
        suggested_equity_method_adj_b = 0.0
        suggested_pension_adj_b = 0.0
        
        with st.expander('🧾 资产价值补充项（手动填写）', expanded=False):
            st.caption('以下为**建议值**（仅供参考），请以年报附注为准；留空表示暂不调整。单位：$B。')
            
            st.caption(f'应收坏账调整（Receivables defaults）建议：{suggested_receivables_default_b:.2f} $B')
            receivables_default_input = st.text_input(
                '应收坏账调整 ($B，负数表示减值)',
                value='',
                key='adj_receivables_default_b'
            )
            
            st.caption(f'存货 LIFO/FIFO 调整建议：{suggested_inventory_adj_b:.2f} $B')
            inventory_lifo_fifo_input = st.text_input(
                '存货 LIFO/FIFO 调整 ($B)',
                value='',
                key='adj_inventory_lifo_fifo_b'
            )
            
            st.caption(f'权益法投资调整建议：{suggested_equity_method_adj_b:.2f} $B')
            equity_method_input = st.text_input(
                '权益法投资调整 ($B)',
                value='',
                key='adj_equity_method_b'
            )
            
            st.caption(f'养老金/表外负债调整建议：{suggested_pension_adj_b:.2f} $B')
            pension_input = st.text_input(
                '养老金/表外负债调整 ($B，负数表示负债增加)',
                value='',
                key='adj_pension_b'
            )
        
        # 汇总：仍为空缺的手动项
        if _parse_optional_billion(receivables_default_input) is None:
            missing_items.append('应收坏账调整')
        if _parse_optional_billion(inventory_lifo_fifo_input) is None:
            missing_items.append('存货 LIFO/FIFO 调整')
        if _parse_optional_billion(equity_method_input) is None:
            missing_items.append('权益法投资调整')
        if _parse_optional_billion(pension_input) is None:
            missing_items.append('养老金/表外负债调整')
        
        if missing_items:
            st.info('📌 仍需年报补充的项目：' + '、'.join(missing_items))
    
    # 将用户手动输入优先覆盖 API 的 0 值（单位 $B → 美元）
    B = 1e9
    if override_dep_b is None:
        override_dep_b = st.session_state.get('override_depreciation_b_input')
    if override_dep_b:
        val = override_dep_b * B
        if isinstance(processed_data['income_statement'].get('depreciation'), list):
            processed_data['income_statement']['depreciation'][0] = val
        else:
            processed_data['income_statement']['depreciation'] = val
        if 'depreciation_cf' in processed_data['cash_flow'] and isinstance(processed_data['cash_flow']['depreciation_cf'], list):
            processed_data['cash_flow']['depreciation_cf'][0] = val
        if 'depreciation' in processed_data['cash_flow']:
            processed_data['cash_flow']['depreciation'] = val
    if override_capex_b is None:
        override_capex_b = st.session_state.get('override_capex_b_input')
    if override_capex_b:
        val = override_capex_b * B
        if isinstance(processed_data['cash_flow'].get('capex'), list):
            processed_data['cash_flow']['capex'][0] = val
        else:
            processed_data['cash_flow']['capex'] = val
    if override_rou_b is None:
        override_rou_b = st.session_state.get('override_rou_b_input')
    if override_rou_b:
        val = override_rou_b * B
        processed_data['balance_sheet']['right_of_use_assets'] = val
    if override_rd_b is None:
        override_rd_b = st.session_state.get('override_rd_b_input')
    if override_rd_b:
        val = override_rd_b * B
        if isinstance(processed_data['income_statement'].get('rd_expense'), list):
            processed_data['income_statement']['rd_expense'][0] = val
        else:
            processed_data['income_statement']['rd_expense'] = val
    
    # 3. 公司信息展示（增强版）
    company_info = financial_data['company_info']
    market_data = financial_data['market_data']
    trading_currency = (company_info.get('currency') or MARKETS.get(market, {}).get('currency') or "USD").upper()
    financial_currency = (company_info.get('financial_currency') or trading_currency).upper()
    currency = financial_currency  # 统一估值/财报展示币种以财报币种为准
    if trading_currency != financial_currency:
        st.warning(
            f"⚠️ 币种口径提示：该标的交易币种为 {trading_currency}，财报币种为 {financial_currency}。"
            "本工具将以财报币种展示 AV/EPV/FV；市值等市场数据若与财报币种不同，需汇率换算后再严格比较。"
        )
    
    col1, col2, col3, col4 = st.columns(4)
    
    current_date = datetime.now().strftime('%Y-%m-%d')
    
    with col1:
        st.metric('公司名称', company_info.get('name', 'N/A'))
        
    with col2:
        market_cap = market_data.get('market_cap', 0)
        market_cap_label = f"市值 ({current_date}) {currency} {market_cap/1e9:.1f}B"
        if st.button(market_cap_label, key='toggle_mcap_chart'):
            st.session_state.show_mcap_chart = not st.session_state.show_mcap_chart
        st.caption('点击市值可展开/收回走势')
    
    # 市值图：居中全宽、可选时间范围、可再次点击收起
    if st.session_state.show_mcap_chart:
        with st.container():
            period_label = {'ytd': '年初至今', '3mo': '近3月', '1y': '近1年', '2y': '近2年', '5y': '近5年'}
            mcap_period = st.selectbox(
                '时间范围',
                options=['ytd', '3mo', '1y', '2y', '5y'],
                format_func=lambda x: period_label[x],
                key='mcap_period_select'
            )
            with st.spinner('加载市值历史...'):
                hist_data = fetcher.get_historical_market_data(mcap_period)
                if hist_data and hist_data.get('dates'):
                    fig = viz.create_market_cap_history(
                        hist_data['dates'],
                        hist_data['market_cap'],
                        current_date,
                        currency=currency,
                    )
                    fig.update_layout(height=400, margin=dict(l=60, r=60))
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info('暂无该时间段的市值历史数据')
    
    with col3:
        sector = company_info.get('sector', '') or 'N/A'
        industry = company_info.get('industry', '') or 'N/A'
        industry_display = f"{sector}" if sector != 'N/A' else industry
        if sector != 'N/A' and industry != 'N/A' and industry != sector:
            industry_display = f"{sector} — {industry}"
        st.metric('行业', industry_display)

    # 先计算 Beta（供 col4 与后续 EPV 使用）
    beta_calc = BetaCalculator(ticker_for_analysis, market)
    if beta_method == 'capm':
        beta_result = beta_calc.calculate_capm_beta('5y')
        beta_value = beta_result.get('beta', 1.0)
        beta_method_name = 'CAPM'
    elif beta_method == 'adjusted_blume':
        beta_result = beta_calc.calculate_blume_adjusted_beta()
        beta_value = beta_result.get('beta', 1.0)
        beta_method_name = 'Blume调整'
    elif beta_method == 'fundamental':
        bs = processed_data.get('balance_sheet', {})
        debt = bs.get('long_term_debt', 0) + bs.get('short_term_debt', 0)
        equity = bs.get('total_equity', 1) or 1
        de_ratio = debt / equity if equity > 0 else 0
        beta_result = beta_calc.calculate_fundamental_beta(de_ratio, 0.21)
        beta_value = beta_result.get('beta', 1.0)
        beta_method_name = '基本面'
    elif beta_method in ['ff3', 'ff5']:
        beta_result = beta_calc.estimate_ff3_beta()
        beta_value = beta_result.get('beta_market', 1.0)
        beta_method_name = 'FF3估算'
    else:
        beta_value = market_data.get('beta', 1.0)
        beta_method_name = 'Yahoo'
        beta_result = {'beta': beta_value, 'warning': ''}

    year_label = _get_report_year_label(processor, data_year_index)
    with col4:
        st.metric('报表基准年', year_label)
        st.metric(f'Beta ({beta_method_name})', f"{beta_value:.3f}")

    # 正文内关键参数（与侧边栏一致，便于快速确认）
    with st.expander('⚙️ 关键参数（AV/EPV 用）', expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"**利润平滑**：{smoothing_years} 年平均")
        with c2:
            st.markdown(f"**报表年份**：{year_label}")
        with c3:
            st.markdown(f"**折现率**：{discount_rate*100:.0f}% | **永续增长**：{growth_rate*100:.0f}%")

    if beta_result.get('warning'):
        st.warning(beta_result['warning'])

    with st.expander('📊 Beta详情', expanded=False):
            st.markdown('**计算结果**')
            if beta_result.get('formula'):
                st.code(beta_result.get('formula', ''), language='text')
            c1, c2 = st.columns(2)
            with c1:
                if 'r_squared' in beta_result:
                    st.metric('R²（解释力）', f"{beta_result['r_squared']:.3f}")
            with c2:
                if 'observations' in beta_result:
                    st.metric('数据点数', f"{beta_result['observations']}个月")
            hist_data_b = fetcher.get_historical_market_data('5y')
            if hist_data_b and hist_data_b.get('beta_dates'):
                fig_beta = viz.create_beta_history(
                    hist_data_b['beta_dates'], hist_data_b['beta_values'],
                    beta_value, beta_method_name
                )
                st.plotly_chart(fig_beta, use_container_width=True)
                st.caption(
                    "说明：图中**红线**为 60 日滚动 Beta（日频），每个时点是「过去 60 个交易日」的 Beta；"
                    "**绿星/水平线**为 5 年月度全样本 CAPM Beta，用于 WACC/估值。二者口径不同，故数值可差异较大。"
                )
    
    # Beta深度分析：与侧栏方法一致（5种），行业Beta仅占右栏
    with st.expander('📊 Beta深度分析', expanded=False):
        st.subheader('多模型Beta对比')
        beta_calc = BetaCalculator(ticker_for_analysis, market)
        col_left, col_right = st.columns([3, 2])
        
        with col_left:
            st.markdown('**不同模型的Beta值**')
            comparison_data = []
            capm_result = beta_calc.calculate_capm_beta()
            bs = processed_data.get('balance_sheet', {})
            debt = bs.get('long_term_debt', 0) + bs.get('short_term_debt', 0)
            equity = bs.get('total_equity', 1) or 1
            de_ratio = debt / equity if equity > 0 else 0
            
            for method_key, method_cfg in BETA_METHODS.items():
                if method_key == 'capm':
                    r = capm_result
                    comparison_data.append({
                        '模型': method_cfg['name'],
                        'Beta': f"{r.get('beta', 1.0):.3f}",
                        'R²': f"{r.get('r_squared', 0):.3f}",
                        '说明': method_cfg['usage']
                    })
                elif method_key == 'adjusted_blume':
                    r = beta_calc.calculate_blume_adjusted_beta(capm_result.get('beta', 1.0))
                    comparison_data.append({
                        '模型': method_cfg['name'],
                        'Beta': f"{r.get('beta', 1.0):.3f}",
                        'R²': '-',
                        '说明': method_cfg['usage']
                    })
                elif method_key == 'fundamental':
                    r = beta_calc.calculate_fundamental_beta(de_ratio, 0.21) if de_ratio >= 0 else {'beta': 1.0}
                    comparison_data.append({
                        '模型': method_cfg['name'],
                        'Beta': f"{r.get('beta', 1.0):.3f}",
                        'R²': '-',
                        '说明': f"D/E={de_ratio:.2f}; {method_cfg['usage']}"
                    })
                elif method_key in ['ff3', 'ff5']:
                    r = beta_calc.estimate_ff3_beta()
                    comparison_data.append({
                        '模型': method_cfg['name'],
                        'Beta': f"{r.get('beta_market', 1.0):.3f}",
                        'R²': '-',
                        '说明': method_cfg['usage']
                    })
            
            comparison_df = pd.DataFrame(comparison_data)
            st.dataframe(comparison_df, use_container_width=True, hide_index=True)
            st.success(f"**当前使用**: {beta_method_name} Beta = {beta_value:.3f}")
        
        with col_right:
            st.markdown('**行业Beta参考**')
            industry_refs = beta_calc.get_industry_beta_reference()
            current_industry = company_info.get('sector', 'Unknown')
            if current_industry in industry_refs:
                ref = industry_refs[current_industry]
                st.info(f"**{current_industry}**\n- 典型: {ref.get('beta', 1.0):.2f}\n- 范围: {ref.get('range', (0.5, 1.5))[0]:.2f}-{ref.get('range', (0.5, 1.5))[1]:.2f}\n- 当前公司: {beta_value:.3f}")
            with st.expander('查看所有行业Beta'):
                industry_data = [{'行业': ind, '典型Beta': f"{d.get('beta', 1.0):.2f}", '范围': f"{d.get('range', (0.5, 1.5))[0]:.1f}-{d.get('range', (0.5, 1.5))[1]:.1f}"} for ind, d in industry_refs.items()]
                st.dataframe(pd.DataFrame(industry_data), use_container_width=True, hide_index=True)
        
        recommended = get_recommended_beta_method(company_info)
        st.info(f'💡 **推荐方法**: {BETA_METHODS[recommended]["name"]} - {BETA_METHODS[recommended]["usage"]}')
    
    st.divider()
    
    # 4. Asset Value部分（增强版）
    st.header('📈 Asset Value (AV) 计算')
    
    # AV调整参数区（可手动输入）
    with st.expander('🔧 AV调整参数（点击展开手动调整）', expanded=False):
        
        # PPE调整
        st.subheader('1️⃣ PPE调整')
        col1, col2 = st.columns([2, 1])
        
        with col1:
            with st.expander('📖 理论依据'):
                st.markdown(AV_ADJUSTMENTS_INFO['ppe_adjustment']['theory'])
                st.markdown('**调整公式：**')
                st.markdown(AV_ADJUSTMENTS_INFO['ppe_adjustment']['formula'])
        
        with col2:
            use_manual_ppe = st.checkbox('手动输入PPE数据', key='use_manual_ppe')
        
        # 直接输入 PPE 调整额 ($B)，优先于自动计算（WMT 课件约 +46）
        ppe_override_b = st.number_input(
            'PPE 调整额 ($B)，留空用自动/下方手动',
            min_value=None, max_value=200.0, value=None, step=1.0, format='%.1f',
            key='ppe_override_b',
            help='直接填调整额十亿美元，如 WMT 填 46 表示 +46B；填 0 表示不调整'
        )
        manual_ppe_adj = None
        heuristic_components = None
        if ppe_override_b is not None:
            manual_ppe_adj = float(ppe_override_b) * 1e9  # 优先用直接输入（含 0）
            use_manual_ppe = True
        elif use_manual_ppe:
            st.info('💡 数据来源参考: ' + ', '.join(AV_ADJUSTMENTS_INFO['ppe_adjustment']['data_sources']))
            ppe_land_area = st.number_input('土地面积 (千平方英尺)', value=10000.0, step=100.0, key='ppe_land_area')
            ppe_land_price = st.number_input('当地地价 ($/平方英尺)', value=100.0, step=10.0, key='ppe_land_price')
            ppe_building_area = st.number_input('建筑面积 (千平方英尺)', value=50000.0, step=1000.0, key='ppe_building_area')
            ppe_building_price = st.number_input('当地房价 ($/平方英尺)', value=150.0, step=10.0, key='ppe_building_price')
            manual_ppe_adj = (ppe_land_area * ppe_land_price + ppe_building_area * ppe_building_price) * 1000
        else:
            comp_info = company_info or {}
            heuristic = asset_value_module.get_industry_heuristic(comp_info.get('sector', ''), comp_info.get('industry', ''))
            bs_ppe = processed_data.get('balance_sheet', {})
            total_assets = float(bs_ppe.get('total_assets', 0) or 0)
            if heuristic and total_assets > 0:
                heuristic_gross = total_assets * heuristic['ppe_ratio_of_assets']
                heuristic_components = {k: heuristic_gross * v for k, v in heuristic['components'].items()}
                st.caption('（基于行业基准估算，建议通过解析器校准）')
        
        st.divider()
        
        # 商誉调整
        st.subheader('2️⃣ 商誉调整')
        col1, col2 = st.columns([2, 1])
        
        with col1:
            with st.expander('📖 理论依据'):
                st.markdown(AV_ADJUSTMENTS_INFO['goodwill_adjustment']['theory'])
        
        with col2:
            use_manual_goodwill = st.checkbox('手动选择商誉', key='use_manual_goodwill')
        
        if use_manual_goodwill:
            manual_goodwill_not_digested = None
            bs_gw = processed_data.get('balance_sheet', {})
            current_goodwill = float(bs_gw.get('goodwill', 0) or 0)
            st.write(f'**当前商誉总额**: {currency} {current_goodwill/1e9:.2f}B')
            st.caption('课件：调整额 = -(当前商誉 - 未消化部分)；未消化 = 收购产生尚未完全整合的商誉')
            use_not_digested = st.checkbox('直接输入未消化商誉 ($B)', value=False, key='gw_use_not_digested')
            if use_not_digested:
                not_digested_b = st.number_input('未消化商誉 ($B)', min_value=0.0, value=current_goodwill/1e9*0.5, step=0.5, key='gw_not_digested_b')
                manual_goodwill_not_digested = not_digested_b * 1e9
                manual_goodwill_adj = -(current_goodwill - manual_goodwill_not_digested)
            else:
                integration_year = st.slider(
                    '整合截止年份（该年之前的收购视为已整合）',
                    2018, 2025, 2022, key='gw_integration_year'
                )
                st.markdown('**主要收购记录（可从财报附注获取）**')
                remove_goodwill_pct = st.slider(
                    '剔除比例 (%)',
                    0, 100, 50, 5, key='gw_remove_pct'
                ) / 100
                manual_goodwill_adj = -current_goodwill * remove_goodwill_pct
                manual_goodwill_not_digested = None
        
        st.divider()
        
        # 员工价值
        st.subheader('3️⃣ 员工队伍价值')
        col1, col2 = st.columns([2, 1])
        
        with col1:
            with st.expander('📖 理论依据'):
                st.markdown(AV_ADJUSTMENTS_INFO['workforce_value']['theory'])
        
        with col2:
            use_manual_workforce = st.checkbox('手动输入员工数据', key='use_manual_workforce')
        
        if use_manual_workforce:
            employee_info = fetcher.get_employee_info()
            total_employees = employee_info.get('total_employees', 0)
            
            st.write(f'**披露员工总数**: {total_employees:,}')
            
            num_regular = st.number_input('普通员工数', value=int(total_employees * 0.95), step=1000, key='num_regular')
            salary_regular = st.number_input('普通员工平均薪酬 ($)', value=30000, step=1000, key='salary_regular')
            ratio_regular = st.slider('普通员工培训成本比例 (%)', 5, 20, 10, key='ratio_regular') / 100
            
            num_management = st.number_input('管理层人数', value=int(total_employees * 0.05), step=100, key='num_management')
            salary_management = st.number_input('管理层平均薪酬 ($)', value=150000, step=10000, key='salary_management')
            ratio_management = st.slider('管理层培训成本比例 (%)', 20, 50, 30, key='ratio_management') / 100
            
            manual_workforce_value = (num_regular * salary_regular * ratio_regular +
                                    num_management * salary_management * ratio_management)
    
    # 执行AV计算
    user_adjustments_av = {
        'brand_method': brand_method,
        'brand_role': brand_role,
        'discount_rate': discount_rate,
        'growth_rate': growth_rate,
        'workforce_cost_ratio': workforce_cost_ratio,
    }
    if not use_industry_royalty:
        user_adjustments_av['brand_royalty_rate'] = brand_royalty_rate
    
    # 添加手动调整（直接 $B 或勾选「手动输入PPE」时 manual_ppe_adj 已在上方赋值）
    if 'manual_ppe_adj' in locals() and manual_ppe_adj is not None:
        user_adjustments_av['manual_ppe_adjustment'] = manual_ppe_adj
    if 'heuristic_components' in locals() and heuristic_components:
        user_adjustments_av['ppe_components'] = heuristic_components
    
    if 'use_manual_goodwill' in locals() and use_manual_goodwill:
        if manual_goodwill_not_digested is not None:
            user_adjustments_av['goodwill_not_digested'] = manual_goodwill_not_digested
        else:
            user_adjustments_av['remove_goodwill'] = abs(manual_goodwill_adj)
    
    if 'use_manual_workforce' in locals() and use_manual_workforce:
        user_adjustments_av['manual_workforce_value'] = manual_workforce_value
    
    # Lecture 2 补充项（$B → 美元）
    receivables_default_b = _parse_optional_billion(st.session_state.get('adj_receivables_default_b'))
    inventory_lifo_fifo_b = _parse_optional_billion(st.session_state.get('adj_inventory_lifo_fifo_b'))
    equity_method_b = _parse_optional_billion(st.session_state.get('adj_equity_method_b'))
    pension_b = _parse_optional_billion(st.session_state.get('adj_pension_b'))
    
    if receivables_default_b is not None:
        user_adjustments_av['receivables_default_adjustment'] = receivables_default_b * B
    if inventory_lifo_fifo_b is not None:
        user_adjustments_av['inventory_lifo_fifo_adjustment'] = inventory_lifo_fifo_b * B
    if equity_method_b is not None:
        user_adjustments_av['equity_method_adjustment'] = equity_method_b * B
    if pension_b is not None:
        user_adjustments_av['underfunded_pension'] = pension_b * B
    
    av_calculator = asset_value_module.AssetValueCalculator(processed_data, user_adjustments_av)
    av_results = av_calculator.calculate(user_adjustments_av)
    av_summary = av_calculator.get_av_summary()
    
    # AV 结果与图表（展示移至步骤 Tab）
    viz = ValuationVisualizer()
    fig_av_breakdown = viz.create_av_components_breakdown(av_results['components'], currency=currency)
    
    # EPV部分（完整公式、调整分项、WACC表、营业利润率图、第35页表）
    st.header('💰 Earning Power Value (EPV) 计算')
    
    from dashboard.components import epv_tables
    
    user_adjustments_epv = {
        'ticker': ticker_for_analysis,
        'smoothing_years': smoothing_years,
        'data_year_index': data_year_index,
        'smoothing_method': smoothing_method,
        'market_risk_premium': market_risk_premium,
        'brand_value': av_results['brand_value'],
        'beta': beta_value,
        'rd_growth_ratio': rd_growth_ratio,
    }
    
    epv_calculator = EarningPowerCalculator(processed_data, user_adjustments_epv)
    epv_results = epv_calculator.calculate(user_adjustments_epv)
    
    # 1) 公式 + 各调整分项（依据 + 可手动输入）
    breakdown = epv_calculator.get_epv_detailed_breakdown(user_adjustments_epv)
    with st.expander('📘 EPV 理论与核心公式', expanded=False):
        st.markdown("**EPV = 调整后 NOPAT / WACC**")
        st.caption("调整后 NOPAT = (1-税率) × [营业利润 + 折旧调整 + 增长性支出 + 非经常项]")

    # 调整额输入表（可编辑）
    adjustment_overrides = {}
    with st.expander('🧾 EPV 调整额输入（可编辑表）', expanded=False):
        adj_rows = []
        for item in breakdown.get('adjustments_detail', []):
            adj_rows.append({
                '项目': item['name'],
                '原始值($B)': (item.get('original_value', 0) or 0) / 1e9,
                '调整额($B)': (item.get('suggested_value', item['adjustment_value']) or 0) / 1e9,
                '说明': item.get('rationale', ''),
                '_key': item['key'],
            })
        if adj_rows:
            adj_df = pd.DataFrame(adj_rows)
            edited = st.data_editor(
                adj_df.drop(columns=['_key']),
                use_container_width=True,
                hide_index=True,
                disabled=['项目', '原始值($B)', '说明']
            )
            for idx, row in edited.iterrows():
                key = adj_rows[idx]['_key']
                val_b = row['调整额($B)']
                adjustment_overrides[key] = float(val_b) * 1e9
    
    # 2) Growth expense 两种方法（Lecture 3 第28页）
    income_st = processed_data.get('income_statement', {})
    rev = breakdown.get('revenue', 0)
    sg = income_st.get('sg_and_a', 0)
    if isinstance(sg, (list, tuple)) and len(sg) > 0:
        sg = sg[0]
    else:
        sg = float(sg or 0)
    marketing = sg * 0.35
    with st.expander('📌 增长性支出调整方法（小字说明）', expanded=False):
        growth_method = epv_tables.render_growth_expense_method_selector(
            'method1', rev, marketing, av_results.get('brand_value', 0)
        )
    user_adjustments_epv['growth_expense_method'] = growth_method
    
    # 3) WACC 计算过程表（Lecture 3 第13页）
    wacc_breakdown = epv_calculator.get_wacc_breakdown(user_adjustments_epv)
    with st.expander('📊 WACC 计算过程（可选）', expanded=False):
        wacc_result = epv_tables.render_wacc_table_lecture3_p13(wacc_breakdown, key_prefix="wacc_epv", currency=currency)
    user_adjustments_epv['wacc'] = wacc_result.get('wacc', epv_results['wacc'])
    wacc_override_pct = st.session_state.get('wacc_override_pct', 0) or 0
    if wacc_override_pct and wacc_override_pct > 0:
        user_adjustments_epv['wacc'] = wacc_override_pct / 100
    st.caption(f"WACC 采用值：{user_adjustments_epv['wacc']:.2%}")
    
    # 合并调整项覆盖并重新计算 EPV
    user_adjustments_epv.update(adjustment_overrides)
    epv_results = epv_calculator.calculate(user_adjustments_epv)
    epv_summary = epv_calculator.get_epv_summary()
    
    # 4) 营业利润率折线图（含平滑线与事件标注）
    st.subheader('营业利润率与平滑')
    col_chart, col_opt = st.columns([3, 1])
    with col_opt:
        smoothing_years_chart = st.selectbox(
            '平滑年数',
            options=[3, 5, 7],
            index=[3, 5, 7].index(smoothing_years),
            key='margin_years_chart'
        )
    try:
        year_labels, margins_list, smoothed_m = processor.get_operating_margin_history(smoothing_years_chart)
        if year_labels and margins_list:
            fig_margin = epv_tables.create_operating_margin_chart(
                year_labels, margins_list, smoothed_m, ticker_for_analysis, smoothing_years_chart
            )
            with col_chart:
                st.plotly_chart(fig_margin, use_container_width=True)
            with col_opt:
                latest_margin = margins_list[0] if margins_list else None
                if latest_margin is not None:
                    st.metric('最新年度利润率', f"{latest_margin:.2%}")
        else:
            st.info("暂无足够历史数据绘制营业利润率图")
    except Exception as e:
        st.warning(f"营业利润率图暂不可用: {e}")
    
    # 5) EPV vs EPVc（折叠附注）
    bs = processed_data.get('balance_sheet', {})
    cash = bs.get('cash', 0) or 0
    debt = (bs.get('long_term_debt', 0) or 0) + (bs.get('short_term_debt', 0) or 0)
    r = epv_results['wacc']
    r_pct = epv_results['wacc'] * 100
    r_star = r
    r_star_pct = r * 100
    epvc_operating = None
    epvc_equity = None
    with st.expander("📎 EPVc 附注（默认关闭）", expanded=False):
        st.caption("默认采用 EPV；如需考虑终止风险，可设置 p 和 λ。")
        p_catastrophic = st.number_input(
            "终止概率 p（r*≈r+p）",
            min_value=0.0, max_value=0.5, value=0.0, step=0.005, format="%.3f",
            key="epv_p_catastrophic",
        )
        lam_catastrophic = st.number_input(
            "λ（永久损伤比例，可选）",
            min_value=0.0, max_value=1.0, value=0.0, step=0.1, key="epv_lambda",
        )
        if p_catastrophic >= 0.05 and lam_catastrophic > 0:
            denom = p_catastrophic * lam_catastrophic * (1 + r) + (1 - p_catastrophic) * r
            r_star = (r * (r + p_catastrophic)) / denom if denom > 0 else r + p_catastrophic
        else:
            r_star = r + p_catastrophic
        r_star_pct = r_star * 100
        epvc_operating = epv_results['adjusted_nopat'] / r_star if r_star > 0 else 0
        epvc_equity = epvc_operating + cash - debt

    # 6) 完整计算过程表（Lecture 3 第35页）：原值 / 调整额 / 调整后；r* 与 EPVc
    comps = epv_results.get('components', {})
    with st.expander('🧾 EPV 完整计算过程（可折叠）', expanded=False):
        epv_tables.render_epv_final_table_lecture3_p35(
            revenue=epv_results['current_revenue'],
            operating_margin=epv_results['smoothed_margin'],
            op_income=epv_results['smoothed_operating_income'],
            adj_over_dep=epv_results['depreciation_adjustment'],
            adj_growth_marketing=comps.get('增长支出调整', 0),
            adj_growth_product=0,
            adj_growth_lease=0,
            adj_growth_workforce=0,
            extraordinary=epv_results['extraordinary_adjustment'],
            adjusted_op_income=epv_results['adjusted_operating_income'],
            tax_pct=epv_results['tax_rate'] * 100,
            adjusted_nopat=epv_results['adjusted_nopat'],
            wacc_pct=r_pct,
            epv_operating=epv_results['epv'],
            non_op_cash=cash,
            debt=debt,
            epv_equity=epv_results['epv'] + cash - debt,
            r_star_pct=r_star_pct,
            epvc_operating=epvc_operating,
            epvc_equity=epvc_equity,
            currency=currency,
        )
    
    # EPV 瀑布图（展示移至步骤 Tab）
    fig_epv_waterfall = viz.create_epv_components_waterfall(
        epv_results['components'],
        epv_results['epv'],
        currency=currency,
    )
    
    # 综合分析数据（展示移至步骤 Tab）
    fig_comparison = None
    summary_df = viz.create_valuation_summary_table(av_summary, epv_summary, currency=currency)

    net_income = processed_data.get('income_statement', {}).get('net_income') or 0
    if isinstance(net_income, (list, tuple)):
        net_income = net_income[0] if net_income else 0
    net_income = float(net_income or 0)
    total_equity = bs.get('total_equity') or 0
    total_equity = float(total_equity or 0)
    operating_income = processed_data.get('income_statement', {}).get('operating_income') or 0
    if isinstance(operating_income, (list, tuple)):
        operating_income = operating_income[0] if operating_income else 0
    operating_income = float(operating_income or 0)
    ev = market_cap + debt - cash
    pe = (market_cap / net_income) if net_income and net_income > 0 else None
    pb = (market_cap / total_equity) if total_equity and total_equity > 0 else None
    ev_ebit = (ev / operating_income) if operating_income and operating_income > 0 else None
    epv_to_mcap = (epv_results['epv'] / market_cap) if market_cap and market_cap > 0 else None
    av_to_mcap = (av_results['total_av'] / market_cap) if market_cap and market_cap > 0 else None
    # 避免显示 Inf/NaN 或极端倍数
    def _finite(x):
        return x is not None and x == x and abs(x) != float('inf')
    def _safe_ratio(x, low=0.01, high=1000):
        if x is None or not _finite(x): return None
        return x if low <= x <= high else None
    epv_to_mcap_s = _safe_ratio(epv_to_mcap)
    av_to_mcap_s = _safe_ratio(av_to_mcap)
    pe_s = _safe_ratio(pe, high=500) if pe is not None else None
    pb_s = _safe_ratio(pb, high=50) if pb is not None else None
    mult_df = pd.DataFrame({
        '指标': ['P/E (市值/净利润)', 'P/B (市值/净资产)', 'EV/EBIT (经营利润)', 'EPV/市值', 'AV/市值'],
        '数值': [
            f"{pe_s:.1f}x" if pe_s is not None else ("N/A (亏损)" if net_income is not None and net_income < 0 else "N/A"),
            f"{pb_s:.1f}x" if pb_s is not None else ("N/A (净资产为负)" if total_equity is not None and total_equity < 0 else "N/A"),
            f"{ev_ebit:.1f}x" if ev_ebit is not None and _finite(ev_ebit) and 0 < ev_ebit < 500 else "N/A",
            f"{epv_to_mcap_s:.2f}" if epv_to_mcap_s is not None else ("极端值(请核参)" if epv_to_mcap is not None else "N/A"),
            f"{av_to_mcap_s:.2f}" if av_to_mcap_s is not None else ("极端值(请核参)" if av_to_mcap is not None else "N/A"),
        ],
        '说明': [
            '市盈率，亏损时无意义',
            '市净率，净资产为负时无意义',
            '企业价值/经营利润',
            'EPV 与市值比，>1 可能低估',
            '资产价值与市值比',
        ],
    })

    epv_to_market = epv_summary.get('epv_to_market_cap', 0) or 0
    epv_ratio_ok = (epv_to_market == epv_to_market and epv_to_market != float('inf') and epv_to_market >= 0 and market_cap > 0)

    # Franchise Value 部分（展示移至步骤 Tab）
    st.header('🚀 Franchise Value (FV)')
    st.caption('基于 Columbia Business School Growth & Value 方法论')
    
    with st.expander('📖 什么是Franchise Value？', expanded=False):
        st.markdown('''
### Franchise Value概念

**公式**：
```
V = EPV + FV
V = NOPAT/r + (R-r)/r × Growth Investment
```

**核心原理**：
- **EPV** = 当前盈利能力的价值（假设零增长）
- **FV** = 增长投资创造的额外价值
- **FV > 0** 当且仅当 **ROIC > WACC**

**关键指标**：
- **ROIC** (Return on Invested Capital): 投资资本回报率
- **g** (Growth rate): 盈利增长率 = k × ROIC + 有机增长
- **k**: 再投资率 = Growth Capex / NOPAT

**投资含义**：
- ROIC > WACC：增长创造价值，应该追求增长
- ROIC < WACC：增长摧毁价值，应该分配利润
- ROIC = WACC：增长不创造价值，保持现状
        ''')
    
    # 计算Franchise Value
    from valuation import FranchiseValueCalculator
    
    with st.expander('📐 ROIC 与增长率 (g) 参数', expanded=False):
        st.caption('永续增长率 g 上限：原则上不超过 WACC 的 80% 或长期 GDP；成熟型如 WMT 推荐 g≈3%，高增长型可设超常期。')
        roic_lease_interest = st.number_input(
            'Lecture ROIC 的 Lease/Interest 项 ($B)',
            min_value=-50.0,
            max_value=50.0,
            value=float(st.session_state.get('roic_lease_interest') or 0.0),
            step=0.1,
            key='roic_lease_interest',
            help='用于课件 ROIC 分子：OI + D&A + Lease/Interest；默认 0 表示未手动补充。'
        )
        strict_course_mode = st.checkbox(
            '严格课件模式（FV 允许为负，不使用启发式上限）',
            value=True,
            key='strict_course_mode',
            help='开启后按课件主式计算 FV；当 ROIC < WACC 时，FV 为负值（增长摧毁价值）。'
        )
        gdp_long_term = st.number_input('长期 GDP 预期 (%)', min_value=1, max_value=6, value=3, step=1, key='gdp_lt') / 100
        perpetual_cap_override = st.number_input('永续增长率上限覆盖 (%)，留空则用 max(80%×WACC, GDP)', min_value=0, max_value=15, value=0, step=1, key='g_cap_ov') / 100
        if perpetual_cap_override <= 0:
            perpetual_cap_override = None
        st.caption('高增长型（如 NVDA）：可设超常增长年数，之后回归终期 g。')
        supernormal_years = st.number_input('超常增长年数（0=关闭）', min_value=0, max_value=10, value=0, step=1, key='super_years')
        supernormal_g_pct = st.number_input('超常期增长率 g (%)', min_value=0, max_value=30, value=15, step=1, key='super_g') / 100 if supernormal_years else 0
        terminal_g_pct = st.number_input('终期永续 g (%)', min_value=1, max_value=6, value=3, step=1, key='term_g') / 100 if supernormal_years else gdp_long_term
    fv_adjustments = {
        'wacc': epv_results['wacc'],
        'tax_rate': user_adjustments_epv.get('tax_rate', 0.21),
        'lease_and_interest_income': (roic_lease_interest or 0) * B,
        'strict_course_mode': bool(st.session_state.get('strict_course_mode', True)),
        'gdp_long_term': gdp_long_term,
        'perpetual_growth_cap_override': perpetual_cap_override,
        'supernormal_growth_years': supernormal_years if supernormal_years else 0,
        'supernormal_g': supernormal_g_pct if supernormal_years else None,
        'terminal_g': terminal_g_pct if supernormal_years else None,
        'roic_override': (st.session_state.get('roic_override_pct', 0) or 0) / 100 if (st.session_state.get('roic_override_pct', 0) or 0) > 0 else None,
    }
    
    fv_calculator = FranchiseValueCalculator(processed_data, fv_adjustments)
    
    # 计算ROIC（展示默认用 net 口径，更符合市场常用“投入资本”定义；lecture 口径保留作对照）
    roic_analysis = fv_calculator.calculate_roic(use_marginal=True, method='net')
    roic_analysis_lecture = fv_calculator.calculate_roic(use_marginal=False, method='lecture')
    
    # 计算增长率（内部 FV 会用 net ROIC 并应用 g 上限）
    growth_analysis = fv_calculator.calculate_growth_rate()
    
    # 计算Franchise Value（内部强制 method='net'，并应用永续 g 上限）
    wacc_for_fv = epv_results['wacc']
    if wacc_override_pct and wacc_override_pct > 0:
        wacc_for_fv = wacc_override_pct / 100
    fv_analysis = fv_calculator.calculate_franchise_value(wacc=wacc_for_fv)
    
    # 隐含增长率：支撑当前股价所需的 g
    implied = fv_calculator.calculate_implied_growth_rate(wacc=wacc_for_fv)

    fig_comparison = viz.create_av_epv_comparison(
        av_results['total_av'],
        epv_results['epv'],
        market_cap,
        fv_analysis.get('franchise_value'),
        company_info.get('name', ticker_for_analysis),
        currency=currency,
    )

    # 导出用明细表（原始值/调整值/调整后）
    bs_export = processed_data.get("balance_sheet", {})
    av_export_df = pd.DataFrame([
        {"分项": "账面权益", "原始值": bs_export.get("total_equity", 0) or 0, "调整值": 0, "调整后": bs_export.get("total_equity", 0) or 0},
        {"分项": "PPE调整", "原始值": bs_export.get("ppe_net", 0) or 0, "调整值": av_results.get("ppe_adjustment", 0), "调整后": (bs_export.get("ppe_net", 0) or 0) + av_results.get("ppe_adjustment", 0)},
        {"分项": "商誉调整", "原始值": bs_export.get("goodwill", 0) or 0, "调整值": av_results.get("goodwill_adjustment", 0), "调整后": (bs_export.get("goodwill", 0) or 0) + av_results.get("goodwill_adjustment", 0)},
        {"分项": "经营租赁(ROU)", "原始值": bs_export.get("right_of_use_assets", 0) or 0, "调整值": av_results.get("operating_lease_adjustment", 0), "调整后": (bs_export.get("right_of_use_assets", 0) or 0) + av_results.get("operating_lease_adjustment", 0)},
        {"分项": "流动资产调整", "原始值": 0, "调整值": av_results.get("current_assets_adjustment", 0), "调整后": av_results.get("current_assets_adjustment", 0)},
        {"分项": "权益法投资调整", "原始值": 0, "调整值": av_results.get("equity_method_adjustment", 0), "调整后": av_results.get("equity_method_adjustment", 0)},
        {"分项": "养老金/表外负债调整", "原始值": 0, "调整值": av_results.get("pension_adjustment", 0), "调整后": av_results.get("pension_adjustment", 0)},
        {"分项": "品牌价值", "原始值": 0, "调整值": av_results.get("brand_value", 0), "调整后": av_results.get("brand_value", 0)},
        {"分项": "员工价值", "原始值": 0, "调整值": av_results.get("workforce_value", 0), "调整后": av_results.get("workforce_value", 0)},
        {"分项": "产品组合", "原始值": 0, "调整值": av_results.get("product_portfolio_value", 0), "调整后": av_results.get("product_portfolio_value", 0)},
    ])
    epv_export_df = pd.DataFrame([
        {"项目": "营业收入", "原始值": epv_results.get("current_revenue", 0), "调整值": 0, "调整后": epv_results.get("current_revenue", 0)},
        {"项目": "平滑利润率", "原始值": epv_results.get("smoothed_margin", 0), "调整值": 0, "调整后": epv_results.get("smoothed_margin", 0)},
        {"项目": "平滑营业利润", "原始值": epv_results.get("smoothed_operating_income", 0), "调整值": 0, "调整后": epv_results.get("smoothed_operating_income", 0)},
        {"项目": "折旧调整", "原始值": 0, "调整值": epv_results.get("depreciation_adjustment", 0), "调整后": epv_results.get("depreciation_adjustment", 0)},
        {"项目": "增长性支出", "原始值": 0, "调整值": epv_results.get("growth_expense_adjustment", 0), "调整后": epv_results.get("growth_expense_adjustment", 0)},
        {"项目": "非经常项", "原始值": 0, "调整值": epv_results.get("extraordinary_adjustment", 0), "调整后": epv_results.get("extraordinary_adjustment", 0)},
        {"项目": "调整后营业利润", "原始值": 0, "调整值": 0, "调整后": epv_results.get("adjusted_operating_income", 0)},
        {"项目": "税率", "原始值": epv_results.get("tax_rate", 0), "调整值": 0, "调整后": epv_results.get("tax_rate", 0)},
        {"项目": "调整后 NOPAT", "原始值": 0, "调整值": 0, "调整后": epv_results.get("adjusted_nopat", 0)},
        {"项目": "WACC", "原始值": epv_results.get("wacc", 0), "调整值": 0, "调整后": epv_results.get("wacc", 0)},
    ])
    roic_export_df = pd.DataFrame([
        {"项目": "Operating Income", "数值": roic_analysis['operating_income'] / 1e9, "单位": "$B", "说明": "Income Statement"},
        {"项目": "Tax Rate", "数值": roic_analysis['tax_rate'], "单位": "%", "说明": "有效税率"},
        {"项目": "NOPAT", "数值": roic_analysis['nopat'] / 1e9, "单位": "$B", "说明": "(1-T)×利润口径"},
        {"项目": "Invested Capital", "数值": roic_analysis['invested_capital'] / 1e9, "单位": "$B", "说明": "投入资本口径随 method"},
        {"项目": "Acc. Depreciation", "数值": roic_analysis.get('accumulated_depreciation', 0) / 1e9, "单位": "$B", "说明": "lecture 口径用"},
        {"项目": "Spontaneous Liabilities", "数值": roic_analysis.get('spontaneous_liabilities', 0) / 1e9, "单位": "$B", "说明": "AP+Accrued 等"},
        {"项目": "ROIC", "数值": roic_analysis['average_roic'], "单位": "%", "说明": "NOPAT / Invested Capital"},
        {"项目": "ROIC Method", "数值": roic_analysis.get('roic_method', ''), "单位": "-", "说明": "lecture/net/gross"},
        {"项目": "Growth Rate (g)", "数值": growth_analysis['total_growth'], "单位": "%", "说明": "k×ROIC + organic"},
        {"项目": "Growth Capex", "数值": growth_analysis['growth_capex'] / 1e9, "单位": "$B", "说明": "Capex−Maintenance"},
        {"项目": "k (reinvest rate)", "数值": growth_analysis['k'], "单位": "%", "说明": "Growth Capex / NOPAT"},
        {"项目": "WACC", "数值": fv_analysis.get('wacc', 0), "单位": "%", "说明": "资本成本"},
        {"项目": "EPV", "数值": fv_analysis.get('epv', 0) / 1e9, "单位": "$B", "说明": "NOPAT/r"},
        {"项目": "FV", "数值": fv_analysis['franchise_value'] / 1e9, "单位": "$B", "说明": "特许权价值"},
        {"项目": "Total Value", "数值": fv_analysis['total_value'] / 1e9, "单位": "$B", "说明": "EPV+FV"},
    ])
    export_tables = {
        "AV 原始与调整": av_export_df,
        "EPV 原始与调整": epv_export_df,
        "ROIC与FV计算": roic_export_df,
    }
    
    # 调试信息（展开查看）
    with st.expander('🔍 计算详情（调试）', expanded=False):
        debug_data = {
            'ROIC': f"{roic_analysis['average_roic']:.2%}",
            'WACC': f"{fv_analysis['wacc']:.2%}",
            'ROIC > WACC': roic_analysis['average_roic'] > fv_analysis['wacc'],
            'Growth Rate (g)': f"{growth_analysis['total_growth']:.2%}",
            'Capex': f"${abs(growth_analysis['capex'])/1e9:.2f}B",
            'Depreciation': f"${abs(growth_analysis['depreciation'])/1e9:.2f}B",
            'Growth Capex': f"${growth_analysis['growth_capex']/1e9:.2f}B",
            'k (reinvestment rate)': f"{growth_analysis['k']:.2%}",
            'NOPAT': f"${roic_analysis['nopat']/1e9:.2f}B",
            'EPV': f"${fv_analysis['epv']/1e9:.2f}B",
            'FV': f"${fv_analysis['franchise_value']/1e9:.2f}B",
        }
        st.json(debug_data)
    
    # 计算预期收益率
    return_analysis = fv_calculator.calculate_expected_return(holding_period_years=5)

    # 步骤 Tabs：按流程分步展示，降低首屏密度
    tab_overview, tab_av, tab_epv, tab_fv, tab_export = st.tabs([
        "📋 概览", "🏠 AV", "💰 EPV", "📊 综合与FV", "📥 导出"
    ])

    with tab_overview:
        st.header("📊 估值综合分析")
        missing_labels = [v.get('label', k) for k, v in (data_completeness or {}).items() if v.get('missing')]
        if missing_labels:
            st.warning("数据缺失：请查看年报补充 " + "、".join(missing_labels))
        st.plotly_chart(fig_comparison, use_container_width=True)
        st.subheader("估值摘要")
        st.dataframe(summary_df, use_container_width=True, hide_index=True)
        st.subheader("💡 分析结论")
        with st.expander("📖 EPV/市值 与 EPV vs AV 的理论解读", expanded=False):
            st.markdown("""
**EPV/市值 (Earning Power Value to Market Cap)**  
- **Graham & Dodd / 价值投资**：EPV 代表“现有资产可持续盈利”的价值；若 EPV > 市值，可能存在安全边际。  
- **Damodaran**：EPV 相当于“无增长时的企业价值”；EPV/市值 > 1 可视为“当前盈利被低估”。  

**EPV 与 AV 的大小关系**  
- **EPV > AV**：通常说明存在**无形资产**（品牌、客户关系、壁垒）。  
- **EPV ≤ AV**：可能资产冗余、效率不足（见 Columbia Lecture）。
            """)
        if not epv_ratio_ok or market_cap <= 0:
            st.caption("EPV/市值 需在有效市值下才有参考意义；请确认已选择正确股票并已获取市值。")
        elif epv_to_market > 1.0:
            st.success(f"✅ EPV ({epv_to_market:.0%}) 高于市值，可能存在低估")
        elif epv_to_market > 0.7:
            st.info(f"ℹ️ EPV ({epv_to_market:.0%}) 接近市值，估值合理")
        else:
            st.warning(f"⚠️ EPV ({epv_to_market:.0%}) 显著低于市值，包含大量增长预期")
        if epv_results["epv"] > av_results["total_av"]:
            st.info("🔹 EPV 高于 AV，表明业务存在壁垒和竞争优势")
        else:
            st.warning("🔹 EPV 低于或等于 AV，可能存在资产效率问题")

    with tab_av:
        # ── AV 理论公式（折叠）──
        with st.expander("📘 AV 理论与核心公式", expanded=False):
            st.latex(r"AV = \text{Book Equity} + \sum \Delta_i")
            st.markdown(r"""
其中 $\Delta_i$ 为各分项调整额：

| 分项 | 调整逻辑 |
|------|----------|
| **PPE** | 按分项系数重估：$\Delta_{PPE} = \sum_j (\text{Gross}_j \times f_j) - \text{PPE}_{net}^{报表}$ |
| **商誉** | 扣除已整合部分：$\Delta_{GW} = -(\text{GW} - \text{未消化})$ |
| **经营租赁(ROU)** | BS 已有 ROU 则 $\Delta=0$；否则手动输入 |
| **流动资产** | 应收坏账 + 存货 LIFO/FIFO 调整（需年报） |
| **权益法/养老金** | 需年报附注手动输入 |
| **品牌/员工/产品** | 按特许费率法/培训成本法/DCF 估算 |

**PPE 分项系数表（默认/行业基准）**：  
- Land ×1.5~2.0、Building ×1.2~1.5、Fixtures ×0.8~1.0、Equipment ×0.6~0.8、CIP ×1.0  
- 若 API 能读到 PPE Gross 和分项则展示实际分项；否则按行业比例预估并提示需年报截图校准。
            """)

        # ── AV 分项明细表（报表值 / 调整额 / 调整后）──
        bs_av = processed_data.get("balance_sheet", {})
        _raw = {
            "账面权益":         float(bs_av.get("total_equity", 0) or 0),
            "PPE调整":          float(bs_av.get("ppe_net", 0) or 0),
            "商誉调整":         float(bs_av.get("goodwill", 0) or 0),
            "经营租赁(ROU)":    float(bs_av.get("right_of_use_assets", 0) or 0),
            "流动资产调整":     0.0,
            "权益法投资调整":   0.0,
            "养老金/表外负债调整": 0.0,
            "品牌价值":         0.0,
            "员工价值":         0.0,
            "产品组合":         0.0,
        }
        av_rows = []
        for comp, adj_val in av_results["components"].items():
            raw_val = _raw.get(comp, 0.0)
            missing = (comp == "PPE调整" and raw_val == 0)
            av_rows.append({
                "分项": comp,
                "报表原值($B)": f"{raw_val/1e9:.2f}",
                "调整额($B)": f"{adj_val/1e9:.2f}",
                "调整后($B)": f"{(raw_val + adj_val)/1e9:.2f}" if comp != "账面权益" else f"{raw_val/1e9:.2f}",
                "数据来源": "⚠️ 缺失" if missing else ("API" if raw_val != 0 else "模型估算"),
            })
        av_rows.append({
            "分项": "**合计 AV**",
            "报表原值($B)": "",
            "调整额($B)": "",
            "调整后($B)": f"**{av_results['total_av']/1e9:.2f}**",
            "数据来源": "",
        })
        st.dataframe(pd.DataFrame(av_rows), use_container_width=True, hide_index=True)

        # ── PPE 分项明细（折叠）──
        ppe_details = av_results.get("ppe_details") or {}
        is_heuristic = ppe_details.get("heuristic", False)
        ppe_detail_rows = [(k, v) for k, v in ppe_details.items() if isinstance(v, dict)]
        if ppe_detail_rows:
            with st.expander("📄 PPE 分项明细（系数 × 原值 → 调整后）", expanded=False):
                rows = []
                for comp, detail in ppe_detail_rows:
                    rows.append({
                        "分项": comp,
                        "Gross 原值($B)": f"{(detail.get('original', 0) or 0)/1e9:.2f}",
                        "系数": f"{detail.get('factor', 1.0):.2f}",
                        "调整后($B)": f"{(detail.get('adjusted', 0) or 0)/1e9:.2f}",
                        "调整额($B)": f"{(detail.get('adjustment', 0) or 0)/1e9:.2f}",
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if is_heuristic:
            st.warning("PPE 使用行业基准比例估算，建议通过年报截图或 AI 解析校准。")
        if float(bs_av.get("ppe_net", 0) or 0) == 0:
            st.warning("⚠️ PPE 净值缺失或为 0——请从年报 Balance Sheet 截图补充。")

        # ── AV 组成图 ──
        col1, col2 = st.columns([1, 2])
        with col1:
            st.metric("**总 Asset Value**", f"**{currency} {av_results['total_av']/1e9:.2f}B**")
        with col2:
            st.plotly_chart(fig_av_breakdown, use_container_width=True)

    with tab_epv:
        with st.expander("📘 EPV 理论与核心公式", expanded=False):
            st.latex(r"EPV = \frac{\text{Adjusted NOPAT}}{\text{WACC}}")
            st.markdown(r"""
**调整后 NOPAT 推导过程**：

$$\text{Adj.NOPAT} = (1 - T) \times \big[\text{Smoothed OI} + \Delta_{dep} + \Delta_{growth} + \Delta_{extra}\big]$$

| 符号 | 含义 | 来源 |
|------|------|------|
| Smoothed OI | 平滑后的营业利润 = 当期收入 × 平滑利润率 | 取 N 年平均利润率 |
| $\Delta_{dep}$ | 折旧调整 = Capex − D&A（正=折旧不足） | Cash Flow Statement |
| $\Delta_{growth}$ | 增长性支出调整（研发/SGA 超维护部分） | 人工判断 |
| $\Delta_{extra}$ | 非经常性项目调整 | Income Statement 附注 |
| T | 有效税率 | Income Statement |
| WACC | 加权平均资本成本 | Beta/CAPM + 债务成本 |

**EPV 权益** = EPV + 现金 − 有息债务
            """)
        epv_comps = epv_results.get("components", {})
        epv_rows = [
            {"项目": "营业收入", "原始值": f"{epv_results['current_revenue']/1e9:.2f}B", "调整值": "-", "调整后": f"{epv_results['current_revenue']/1e9:.2f}B", "需调整": "否"},
            {"项目": "平滑利润率", "原始值": f"{epv_results['smoothed_margin']:.2%}", "调整值": "-", "调整后": f"{epv_results['smoothed_margin']:.2%}", "需调整": "否"},
            {"项目": "平滑营业利润", "原始值": f"{epv_results['smoothed_operating_income']/1e9:.2f}B", "调整值": "-", "调整后": f"{epv_results['smoothed_operating_income']/1e9:.2f}B", "需调整": "否"},
            {"项目": "折旧调整", "原始值": "-", "调整值": f"{epv_results['depreciation_adjustment']/1e9:.2f}B", "调整后": f"{epv_results['depreciation_adjustment']/1e9:.2f}B", "需调整": "是"},
            {"项目": "增长性支出", "原始值": "-", "调整值": f"{epv_comps.get('增长支出调整', 0)/1e9:.2f}B", "调整后": f"{epv_comps.get('增长支出调整', 0)/1e9:.2f}B", "需调整": "是"},
            {"项目": "非经常项", "原始值": "-", "调整值": f"{epv_results['extraordinary_adjustment']/1e9:.2f}B", "调整后": f"{epv_results['extraordinary_adjustment']/1e9:.2f}B", "需调整": "是"},
            {"项目": "调整后营业利润", "原始值": "-", "调整值": "-", "调整后": f"{epv_results['adjusted_operating_income']/1e9:.2f}B", "需调整": "否"},
            {"项目": "税率", "原始值": f"{epv_results['tax_rate']:.2%}", "调整值": "-", "调整后": f"{epv_results['tax_rate']:.2%}", "需调整": "否"},
            {"项目": "调整后 NOPAT", "原始值": "-", "调整值": "-", "调整后": f"{epv_results['adjusted_nopat']/1e9:.2f}B", "需调整": "否"},
            {"项目": "WACC", "原始值": f"{epv_results['wacc']:.2%}", "调整值": "-", "调整后": f"{epv_results['wacc']:.2%}", "需调整": "否"},
        ]
        st.dataframe(pd.DataFrame(epv_rows), use_container_width=True, hide_index=True)
        st.subheader("EPV 结果")
        col1, col2 = st.columns([1, 2])
        with col1:
            st.metric("营业收入", f"{currency} {epv_results['current_revenue']/1e9:.2f}B")
            st.metric("平滑利润率", f"{epv_results['smoothed_margin']:.2%}")
            st.metric("调整后NOPAT", f"{currency} {epv_results['adjusted_nopat']/1e9:.2f}B")
            st.metric("WACC", f"{epv_results['wacc']:.2%}")
            st.metric("**总 EPV (经营)**", f"**{currency} {epv_results['epv']/1e9:.2f}B**")
            st.metric("EPV 权益 (EPV+现金-债务)", f"{currency} {(epv_results['epv']+cash-debt)/1e9:.2f}B")
        with col2:
            st.plotly_chart(fig_epv_waterfall, use_container_width=True)

    with tab_fv:
        with st.expander("📘 FV 理论与名词解释", expanded=False):
            st.latex(r"V = EPV + FV = \frac{\text{NOPAT}}{r} + \frac{R - r}{r} \times I_g")
            st.markdown(r"""
| 符号 | 名称 | 说明 |
|------|------|------|
| **R** | ROIC | 投入资本回报率 = NOPAT / Invested Capital |
| **r** | WACC | 加权平均资本成本（CAPM + 债务成本） |
| **$I_g$** | Growth Investment | 用于产生增长的资本投入 |
| **k** | 再投资率 | = Growth Capex / NOPAT |
| **g** | 增长率 | = k × R + 有机增长 |

**Growth Capex 来源**：
$$\text{Growth Capex} = \text{Total Capex} - \text{Maintenance Capex}$$
其中 Maintenance Capex ≈ Depreciation（维持现有产能所需资本支出）。

**FV 判断逻辑**：
- R > r → FV > 0 → 增长**创造**价值  
- R < r → FV < 0 → 增长**摧毁**价值  
- R = r → FV = 0 → 增长无价值意义
            """)
        st.subheader("其他估值方法对比（P/E、P/B、EV/EBITDA）")
        st.dataframe(mult_df, use_container_width=True, hide_index=True)
        if (epv_to_mcap is not None and (epv_to_mcap > 10 or epv_to_mcap < 0.05)) or (av_to_mcap is not None and (av_to_mcap > 10 or av_to_mcap < 0.05)):
            st.caption("⚠️ EPV/市值 或 AV/市值 偏离常见区间，建议核对折现率、利润平滑与报表年份。")
        with st.expander("📋 理论符合性审查与附注", expanded=False):
            st.markdown("""
本工具按 **Graham & Dodd / Columbia 估值课件** 思路实现 AV、EPV、EPVc。
1. **数据与基准年**：可统一选择报表年份（T / T-1 / T-2），平滑周期默认 3 年。  
2. **EPV vs EPVc**：无显著终止风险时以 EPV 为主，否则可参考 EPVc。  
3. **倍数法对比**：P/E、P/B、EV/EBIT 与 EPV/市值、AV/市值并列，便于交叉验证。
            """)
        def _pct(x, default='N/A'):
            if x is None or x != x or abs(x) == float('inf') or abs(x) > 10:
                return default
            return f"{x:.1%}"
        st.subheader("1️⃣ ROIC 分析")
        # ── 手动覆盖状态提示 ──
        wacc_override_pct = st.session_state.get('wacc_override_pct', 0) or 0
        roic_override_pct = st.session_state.get('roic_override_pct', 0) or 0
        _roic_src = f"手动覆盖 ({roic_override_pct:.2f}%)" if roic_override_pct > 0 else "模型计算"
        _wacc_src = f"手动覆盖 ({wacc_override_pct:.2f}%)" if wacc_override_pct > 0 else "模型计算"
        _roic_method_label = {
            'lecture': '课件口径（Gross）',
            'net': 'Net IC 口径',
            'gross': 'Gross IC 口径',
        }.get(roic_analysis.get('roic_method', ''), roic_analysis.get('roic_method', ''))

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("平均 ROIC", _pct(roic_analysis['average_roic']))
        with c2:
            st.metric("WACC", _pct(fv_analysis['wacc']))
        with c3:
            spread = roic_analysis['average_roic'] - fv_analysis['wacc']
            st.metric("ROIC − WACC", _pct(spread), delta_color="normal" if spread > 0 else "inverse")
        with c4:
            st.metric("NOPAT", f"{currency} {roic_analysis['nopat']/1e9:.2f}B")
        fig_roic_wacc = viz.create_roic_vs_wacc_scatter(roic_analysis['average_roic'], fv_analysis['wacc'], company_info.get('name', ticker_for_analysis))
        st.plotly_chart(fig_roic_wacc, use_container_width=True)
        with st.expander("📎 ROIC 口径对照（net vs lecture）", expanded=False):
            st.caption("net 口径更接近市场常用 ROIC 定义；lecture 口径用于课件对照，遇到 contra-sign/缺失项时可能偏离较大。")
            st.dataframe(pd.DataFrame([
                {"口径": "net（默认）", "ROIC": _pct(roic_analysis.get('average_roic')), "投入资本($B)": f"{roic_analysis.get('invested_capital',0)/1e9:.2f}", "NOPAT($B)": f"{roic_analysis.get('nopat',0)/1e9:.2f}"},
                {"口径": "lecture（对照）", "ROIC": _pct(roic_analysis_lecture.get('average_roic')), "投入资本($B)": f"{roic_analysis_lecture.get('invested_capital',0)/1e9:.2f}", "NOPAT($B)": f"{roic_analysis_lecture.get('nopat',0)/1e9:.2f}"},
            ]), use_container_width=True, hide_index=True)

        # ── ROIC 完整计算过程（折叠）──
        with st.expander('🔍 ROIC 完整计算过程', expanded=False):
            st.markdown(f"**计算方法**：{_roic_method_label}")
            _acc_dep = roic_analysis.get('accumulated_depreciation', 0)
            _spont = roic_analysis.get('spontaneous_liabilities', 0)
            _oi = roic_analysis['operating_income']
            _tr = roic_analysis['tax_rate']
            _nopat = roic_analysis['nopat']
            _ic = roic_analysis['invested_capital']
            _roic_val = roic_analysis['average_roic']
            _bs_fv = processed_data.get("balance_sheet", {})
            _cf_fv = processed_data.get("cash_flow", {})
            _income_fv = processed_data.get("income_statement", {})
            _ta = float(_bs_fv.get("total_assets", 0) or 0)
            _dep_raw = _cf_fv.get("depreciation", 0)
            if isinstance(_dep_raw, (list, tuple)):
                _dep = float(_dep_raw[0]) if _dep_raw and _dep_raw[0] else 0
            else:
                _dep = float(_dep_raw) if _dep_raw else 0
            if not _dep:
                _dep_raw2 = _income_fv.get("depreciation", 0) if isinstance(_income_fv, dict) else 0
                if isinstance(_dep_raw2, (list, tuple)):
                    _dep = float(_dep_raw2[0]) if _dep_raw2 and _dep_raw2[0] else 0
                else:
                    _dep = float(_dep_raw2) if _dep_raw2 else 0
            _method = roic_analysis.get('roic_method', '')

            _lease_int = float(fv_adjustments.get('lease_and_interest_income', 0) or 0)
            _pre_tax_total = _oi + _dep + _lease_int
            if _method == 'lecture':
                st.latex(r"\text{ROIC}_{lecture} = \frac{(1 - T) \times [\text{OI} + \text{D\&A} + \text{Lease/Interest}]}{\text{Total Assets} + \text{Acc.Dep} - \text{AP} - \text{Accrued}}")
                roic_rows = [
                    {"步骤": "① Operating Income (OI)", "公式/来源": "Income Statement", "数值": f"{currency} {_oi/1e9:.2f}B"},
                    {"步骤": "② D&A (折旧与摊销)", "公式/来源": "Cash Flow / IS", "数值": f"{currency} {_dep/1e9:.2f}B"},
                    {"步骤": "③ Lease & Interest Income", "公式/来源": "年报附注 (手动输入)", "数值": f"{currency} {_lease_int/1e9:.2f}B"},
                    {"步骤": "④ 分子合计 (税前)", "公式/来源": "① + ② + ③", "数值": f"{currency} {_pre_tax_total/1e9:.2f}B"},
                    {"步骤": "⑤ 有效税率 (T)", "公式/来源": "IS / 手动", "数值": f"{_tr:.1%}"},
                    {"步骤": "⑥ NOPAT (税后)", "公式/来源": "(1−T) × ④", "数值": f"{currency} {_pre_tax_total*(1-_tr)/1e9:.2f}B"},
                    {"步骤": "⑦ Total Assets", "公式/来源": "Balance Sheet", "数值": f"{currency} {_ta/1e9:.2f}B"},
                    {"步骤": "⑧ Accumulated Depreciation", "公式/来源": "BS（可能估算）", "数值": f"{currency} {_acc_dep/1e9:.2f}B"},
                    {"步骤": "⑨ AP + Accrued (自发负债)", "公式/来源": "Balance Sheet", "数值": f"{currency} {_spont/1e9:.2f}B"},
                    {"步骤": "⑩ Invested Capital", "公式/来源": "⑦ + ⑧ − ⑨", "数值": f"{currency} {_ic/1e9:.2f}B"},
                    {"步骤": "⑪ ROIC", "公式/来源": "⑥ / ⑩", "数值": _pct(_roic_val)},
                ]
            else:
                st.latex(r"\text{ROIC} = \frac{\text{NOPAT}}{\text{Invested Capital}}")
                roic_rows = [
                    {"步骤": "① Operating Income", "公式/来源": "Income Statement", "数值": f"{currency} {_oi/1e9:.2f}B"},
                    {"步骤": "② 有效税率 (T)", "公式/来源": "IS / 手动", "数值": f"{_tr:.1%}"},
                    {"步骤": "③ NOPAT", "公式/来源": "(1−T) × ①", "数值": f"{currency} {_nopat/1e9:.2f}B"},
                    {"步骤": "④ Invested Capital", "公式/来源": f"{'TA−CL+STD−Cash' if _method=='net' else 'TA+AccDep−SL'}", "数值": f"{currency} {_ic/1e9:.2f}B"},
                    {"步骤": "⑤ ROIC", "公式/来源": "③ / ④", "数值": _pct(_roic_val)},
                ]
            st.dataframe(pd.DataFrame(roic_rows), use_container_width=True, hide_index=True)
            if roic_override_pct > 0:
                st.info(f"注意：ROIC 已被手动覆盖为 {roic_override_pct:.2f}%，上表显示的是覆盖后数值。")
            if _acc_dep == 0 and _method == 'lecture':
                st.warning("⚠️ Accumulated Depreciation 数据缺失，已用 PPE_net × 75% 估算。建议从年报核实。")
            _mroic = roic_analysis.get('marginal_roic')
            if _mroic is not None:
                st.caption(f"边际 ROIC (Marginal ROIC) = {_pct(_mroic)}，反映最近一年增量资本效率。")
        st.subheader("2️⃣ 盈利增长分析")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("总增长率 (g)", _pct(growth_analysis.get('total_growth')))
        with c2:
            st.metric("投资驱动", _pct(growth_analysis.get('investment_growth')))
        with c3:
            st.metric("有机增长", _pct(growth_analysis.get('organic_growth')))
        with c4:
            st.metric("再投资率 (k)", _pct(growth_analysis.get('k')))
        if fv_analysis.get('perpetual_growth_cap') is not None:
            st.caption(f"永续增长率已应用上限：{fv_analysis['perpetual_growth_cap']:.1%}")
        if implied.get('implied_g') is not None:
            st.info(f"**隐含增长率**：{implied['message']}")
        fig_growth = viz.create_growth_decomposition(growth_analysis)
        st.plotly_chart(fig_growth, use_container_width=True)
        with st.expander('🔍 增长率计算详情', expanded=False):
            st.markdown(f"""
**Growth Capex** = Capex − Maintenance Capex（Maintenance≈Depreciation）= {currency} {growth_analysis['growth_capex']/1e9:.2f}B  
**NOPAT** = {currency} {growth_analysis['nopat']/1e9:.2f}B  
**k** = Growth Capex / NOPAT = {_pct(growth_analysis.get('k'))}  
**投资驱动增长** = k × ROIC = {_pct(growth_analysis.get('investment_growth'))}  
**有机增长（估算）** = {_pct(growth_analysis.get('organic_growth'))}  
**总增长率 g** = {_pct(growth_analysis.get('total_growth'))}
            """)
        st.subheader("3️⃣ Franchise Value计算")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("EPV", f"{currency} {fv_analysis['epv']/1e9:.2f}B")
        with c2:
            st.metric("Franchise Value", f"{currency} {fv_analysis['franchise_value']/1e9:.2f}B")
        with c3:
            st.metric("总价值", f"{currency} {fv_analysis['total_value']/1e9:.2f}B")
        fig_fv_waterfall = viz.create_franchise_value_waterfall(fv_analysis, currency=currency)
        st.plotly_chart(fig_fv_waterfall, use_container_width=True)
        fig_value_bridge = viz.create_value_bridge(av_results['total_av'], fv_analysis['epv'], fv_analysis['franchise_value'], market_cap, currency=currency)
        st.plotly_chart(fig_value_bridge, use_container_width=True)
        col1, col2 = st.columns(2)
        with col1:
            if fv_analysis['creates_value']:
                st.success(f"✅ ROIC ({fv_analysis['roic']:.1%}) > WACC，增长创造价值 | FV/EPV = {fv_analysis['fv_to_epv_ratio']:.1%}")
            else:
                st.error(f"❌ ROIC ({fv_analysis['roic']:.1%}) < WACC，增长摧毁价值")
        with col2:
            mos = fv_analysis.get('margin_of_safety', 0)
            if mos is None or (mos != mos) or abs(mos) == float('inf'):
                st.caption("安全边际: N/A")
            elif mos > 0.3:
                st.success(f"🎯 安全边际: {mos:.0%} (充足)")
            elif mos > 0:
                st.info(f"🎯 安全边际: {mos:.0%} (适中)")
            else:
                st.warning(f"⚠️ 安全边际: {mos:.0%} (高估)")
        st.subheader("4️⃣ 预期收益率分析")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("分配收益率", f"{return_analysis['distribution_yield']*100:.2f}%")
        with c2:
            st.metric("增长率", f"{return_analysis['growth_rate']:.1%}")
        with c3:
            st.metric("基准收益率 (h=0)", f"{return_analysis['base_return']:.1%}")
        scenarios = return_analysis['returns_by_scenario']
        scenario_data = [{'情景': k, '市盈率变化率 (h)': f"{v['multiple_change']:.1%}", '预期收益率': f"{v['return']:.1%}"} for k, v in scenarios.items()]
        st.dataframe(pd.DataFrame(scenario_data), use_container_width=True, hide_index=True)
        fig_return_heatmap = viz.create_return_scenarios_heatmap(return_analysis)
        st.plotly_chart(fig_return_heatmap, use_container_width=True)
        st.subheader("💡 Franchise Value投资建议")
        summary = fv_calculator.generate_summary()
        rec, reason = summary['recommendation'], summary['reason']
        if '强烈买入' in rec:
            st.success(f"## {rec}")
        elif '买入' in rec:
            st.info(f"## {rec}")
        elif '持有' in rec:
            st.warning(f"## {rec}")
        else:
            st.error(f"## {rec}")
        st.markdown(f"**理由**: {reason}")
        summary_metrics = pd.DataFrame([
            {'指标': 'ROIC', '数值': f"{fv_analysis['roic']:.1%}"}, {'指标': 'WACC', '数值': f"{fv_analysis['wacc']:.1%}"},
            {'指标': 'Spread', '数值': f"{fv_analysis['spread']:.1%}"}, {'指标': '盈利增长率', '数值': f"{fv_analysis['growth_rate']:.1%}"},
            {'指标': 'EPV', '数值': f"{currency} {fv_analysis['epv']/1e9:.2f}B"}, {'指标': 'FV', '数值': f"{currency} {fv_analysis['franchise_value']/1e9:.2f}B"},
            {'指标': '总内在价值', '数值': f"{currency} {fv_analysis['total_value']/1e9:.2f}B"}, {'指标': '当前市值', '数值': f"{currency} {market_cap/1e9:.2f}B"},
            {'指标': '安全边际', '数值': f"{fv_analysis['margin_of_safety']:.1%}"},
        ])
        st.dataframe(summary_metrics, use_container_width=True, hide_index=True)

    with tab_export:
        st.header("📥 导出报告")
        exporter = ReportExporter()
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            excel_data = exporter.export_to_excel(
                company_info, av_results, epv_results, av_summary, epv_summary,
                fv_analysis=fv_analysis, extra_tables=export_tables
            )
            st.download_button(
                label="📊 下载Excel报告（含原始/调整/过程）",
                data=excel_data,
                file_name=exporter.get_filename(ticker_for_analysis, 'excel'),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="dl_excel"
            )
        with col_b:
            summary_text = exporter.create_summary_text(company_info, av_summary, epv_summary)
            st.download_button(
                label="📝 下载文本摘要",
                data=summary_text,
                file_name=exporter.get_filename(ticker_for_analysis, 'txt'),
                mime="text/plain",
                use_container_width=True,
                key="dl_txt"
            )
        with col_c:
            try:
                pdf_data = exporter.export_to_pdf(company_info, av_summary, epv_summary, fv_analysis=fv_analysis)
                st.download_button(
                    label="📄 下载PDF简报",
                    data=pdf_data,
                    file_name=exporter.get_filename(ticker_for_analysis, 'pdf'),
                    mime="application/pdf",
                    use_container_width=True,
                    key="dl_pdf"
                )
            except Exception as e:
                st.warning(f"PDF 导出不可用：{e}")
        st.success("✅ 分析完成！")

else:
    # 默认界面
    st.info('👈 请在左侧输入股票代码并点击"开始分析"按钮')
    
    st.markdown('''
## 🆕 增强版功能一览

### 1. 分步估值流程
- 概览 → AV → EPV → 综合与FV → 导出，按 Tab 依次展开
- 每步均包含核心公式（LaTeX）、分项明细表和可折叠理论说明

### 2. AV / EPV / FV 完整链路
- **AV**：PPE 分项系数重估、商誉/租赁/品牌/员工逐项调整
- **EPV**：NOPAT 调整明细 + WACC 计算过程
- **FV**：ROIC 完整推导、增长率分解、Franchise Value 瀑布图

### 3. AI 财报解析 + 行业常识库
- 侧边栏支持粘贴年报片段，AI 自动提取 PPE/折旧/租赁数字
- 行业 PPE 占比基准自动预填（可手动校准）

### 4. 会话配置持久化
- 所有手动参数通过 Session State 保持
- 支持一键保存/加载 JSON 配置文件

### 5. 多格式导出
- Excel（含原始/调整/ROIC/FV 明细多 Sheet）
- PDF 简报 + TXT 文本摘要

---
**开始使用**：在左侧输入股票代码，选择市场，点击"开始分析"！
    ''')

# 页脚
st.divider()
st.markdown('''
<div style="text-align: center; color: #666; font-size: 0.9em;">
    <p>增强版 v2.0 | 基于 Columbia Business School 课程</p>
    <p>本工具仅供学习和研究使用 | © 2026</p>
</div>
''', unsafe_allow_html=True)
