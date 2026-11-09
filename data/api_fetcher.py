"""
数据获取模块 - 从各种API获取财务数据
"""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import urllib.parse
import urllib.request
import warnings
warnings.filterwarnings('ignore')


class DataFetcher:
    """财务数据获取类"""
    
    def __init__(self, ticker: str, market: str = 'US'):
        """
        初始化数据获取器
        
        Args:
            ticker: 股票代码
            market: 市场代码 (US, HK, CN, SZ)
        """
        self.ticker = ticker
        self.market = market
        self.full_ticker = self._format_ticker(ticker, market)
        self.stock = None
        self._fetch_stock_object()
    
    def _format_ticker(self, ticker: str, market: str) -> str:
        """格式化股票代码

        - US: 原样（无后缀）
        - HK: 自动补 .HK
        - CN: 自动判断 .SS / .SZ / .BJ（当输入为 6 位数字时）
        """
        market_suffixes = {
            'US': '',
            'HK': '.HK',
            # CN 需按代码判断（上交所/深交所/北交所），默认不强行补后缀
            'CN': '',
            'SZ': '.SZ'
        }
        
        # 如果已经有后缀，直接返回
        if '.' in ticker:
            return ticker

        t = (ticker or '').strip()
        # A 股常见：6 位数字。按首位规则粗略判断交易所后缀
        if market == 'CN' and t.isdigit() and len(t) == 6:
            if t.startswith(('6', '9')):
                return t + '.SS'
            if t.startswith(('0', '2', '3')):
                return t + '.SZ'
            # 北交所常见：8/4 开头（如 83xxxx / 43xxxx）
            if t.startswith(('8', '4')):
                return t + '.BJ'
            # 兜底：仍按 CN 默认（不补后缀）
            return t
        
        return t + market_suffixes.get(market, '')
    
    def _resolve_company_name_to_ticker(self, query: str, market: str) -> Optional[str]:
        """
        用 yfinance Search API 将公司名/部分名解析为股票代码（如 starbuck→SBUX, NVIDIA→NVDA）。
        不区分大小写；支持部分匹配（如 Starbucks 输成 starbuck）。
        """
        if not query or not query.strip():
            return None
        q = query.strip()
        # 尝试多种查询以提高匹配率：
        # - 英文名：原样 / Title / 加 Inc/Corp
        # - 中文名：只用原样（避免噪声）
        # - 首字母/简称：同时尝试大小写
        def _contains_cjk(s: str) -> bool:
            return any('\u4e00' <= ch <= '\u9fff' for ch in (s or ''))

        # A 股中文名/简称：优先走国内行情 suggest（yfinance.Search 对中文经常命中不稳）
        if market == 'CN':
            resolved_cn = self._resolve_cn_name_to_ticker(q)
            if resolved_cn:
                return resolved_cn

        if _contains_cjk(q):
            search_queries = [q]
        elif q.isalpha() and 2 <= len(q) <= 8:
            search_queries = [q, q.upper(), q.lower(), q.title()]
        else:
            search_queries = [q, q.title(), q + " Inc", q + " Corp"]
        for search_query in search_queries:
            try:
                search = yf.Search(search_query, max_results=15)
                quotes = getattr(search, 'quotes', None)
                if not quotes:
                    continue
                resolved = self._pick_best_equity_ticker(quotes, market)
                if resolved:
                    return resolved
            except Exception:
                continue
        return None

    def _resolve_cn_name_to_ticker(self, query: str) -> Optional[str]:
        """
        A股/北交所：用腾讯 smartbox 将中文名/拼音/首字母解析为代码。

        返回格式：600519.SS / 000001.SZ / 830799.BJ
        """
        if not query or not query.strip():
            return None
        q = query.strip()
        try:
            # 返回示例：
            # v_hint="sz~002130~沃尔核材~wehc~GP-A^sh~600323~瀚蓝环境~hlhj~GP-A"
            url = "https://smartbox.gtimg.cn/s3/?q=" + urllib.parse.quote(q) + "&t=all"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                text = resp.read().decode("utf-8", errors="ignore")
            if not text or "v_hint" not in text:
                return None
            # 取引号内主体
            i1 = text.find("\"")
            i2 = text.rfind("\"")
            body = text[i1 + 1 : i2] if (i1 != -1 and i2 != -1 and i2 > i1) else text
            if not body:
                return None
            for item in body.split("^"):
                parts = item.split("~")
                if len(parts) < 2:
                    continue
                mkt = parts[0].strip().lower()
                code = parts[1].strip()
                if not code or not code.isdigit() or len(code) != 6:
                    continue
                if mkt == "sh":
                    return code + ".SS"
                if mkt == "sz":
                    return code + ".SZ"
                if mkt == "bj":
                    return code + ".BJ"
            return None
        except Exception:
            return None

    def _pick_best_equity_ticker(self, quotes, market: str) -> Optional[str]:
        """从 Search 返回的 quotes 中选出最合适的美股/指定市场股票代码。"""
        if not quotes:
            return None
        # CN: 同时接受 .SS/.SZ/.BJ；HK: .HK；US: 无后缀
        suffix = {'US': '', 'HK': '.HK', 'CN': '', 'SZ': '.SZ'}.get(market, '')
        cn_suffixes = ('.SS', '.SZ', '.BJ')
        for q in quotes:
            sym = (q.get('symbol') if isinstance(q, dict) else getattr(q, 'symbol', None)) or ''
            qtype = (q.get('quoteType') if isinstance(q, dict) else getattr(q, 'quoteType', '')) or ''
            if qtype != 'EQUITY':
                continue
            if market == 'US' and '.' not in sym:
                return sym
            if market == 'CN' and any(sym.endswith(s) for s in cn_suffixes):
                return sym
            if suffix and sym.endswith(suffix):
                return sym
            if not suffix and '.' not in sym:
                return sym
        for q in quotes:
            sym = (q.get('symbol') if isinstance(q, dict) else getattr(q, 'symbol', None)) or ''
            if sym and (q.get('quoteType') if isinstance(q, dict) else getattr(q, 'quoteType', '')) == 'EQUITY':
                return sym.split('.')[0] if market == 'US' else sym
        return None
    
    def _fetch_stock_object(self):
        """获取股票对象"""
        try:
            self.stock = yf.Ticker(self.full_ticker)
        except Exception as e:
            print(f"获取股票对象失败: {e}")
            self.stock = None
    
    def get_company_info(self) -> Dict:
        """获取公司基本信息"""
        if not self.stock:
            return {}
        
        try:
            info = self.stock.info
            return {
                'name': info.get('longName', 'N/A'),
                'sector': info.get('sector', 'N/A'),
                'industry': info.get('industry', 'N/A'),
                'country': info.get('country', 'N/A'),
                # currency: 交易币种（如 ADR 可能为 USD）
                'currency': info.get('currency', 'USD'),
                # financial_currency: 财报币种（如 TSM 的财报可能为 TWD）
                'financial_currency': info.get('financialCurrency') or info.get('financial_currency') or info.get('currency', 'USD'),
                'market_cap': info.get('marketCap', 0),
                'beta': info.get('beta', 1.0),
                'employees': info.get('fullTimeEmployees', 0),
            }
        except Exception as e:
            print(f"获取公司信息失败: {e}")
            return {}
    
    def get_balance_sheet(self, years: int = 5) -> pd.DataFrame:
        """
        获取资产负债表
        
        Args:
            years: 获取年数
            
        Returns:
            DataFrame: 资产负债表数据
        """
        if not self.stock:
            return pd.DataFrame()
        
        try:
            # 获取年度资产负债表
            balance_sheet = self.stock.balance_sheet
            if balance_sheet is None or balance_sheet.empty:
                return pd.DataFrame()
            
            # 只保留最近N年
            if balance_sheet.shape[1] > years:
                balance_sheet = balance_sheet.iloc[:, :years]
            
            return balance_sheet
        except Exception as e:
            print(f"获取资产负债表失败: {e}")
            return pd.DataFrame()
    
    def get_income_statement(self, years: int = 7) -> pd.DataFrame:
        """
        获取利润表
        
        Args:
            years: 获取年数（EPV需要7年数据用于平滑）
            
        Returns:
            DataFrame: 利润表数据
        """
        if not self.stock:
            return pd.DataFrame()
        
        try:
            # 获取年度利润表
            income_stmt = self.stock.income_stmt
            if income_stmt is None or income_stmt.empty:
                return pd.DataFrame()
            
            # 只保留最近N年
            if income_stmt.shape[1] > years:
                income_stmt = income_stmt.iloc[:, :years]
            
            return income_stmt
        except Exception as e:
            print(f"获取利润表失败: {e}")
            return pd.DataFrame()
    
    def get_cash_flow(self, years: int = 5) -> pd.DataFrame:
        """
        获取现金流量表
        
        Args:
            years: 获取年数
            
        Returns:
            DataFrame: 现金流量表数据
        """
        if not self.stock:
            return pd.DataFrame()
        
        try:
            # 获取年度现金流量表
            cash_flow = self.stock.cashflow
            if cash_flow is None or cash_flow.empty:
                return pd.DataFrame()
            
            # 只保留最近N年
            if cash_flow.shape[1] > years:
                cash_flow = cash_flow.iloc[:, :years]
            
            return cash_flow
        except Exception as e:
            print(f"获取现金流量表失败: {e}")
            return pd.DataFrame()
    
    def get_market_data(self) -> Dict:
        """
        获取市场数据
        
        Returns:
            Dict: 市场数据（市值、Beta、股价等）
        """
        if not self.stock:
            return {}
        
        try:
            info = self.stock.info
            return {
                'market_cap': info.get('marketCap', 0),
                'enterprise_value': info.get('enterpriseValue', 0),
                'beta': info.get('beta', 1.0),
                'current_price': info.get('currentPrice', 0),
                'shares_outstanding': info.get('sharesOutstanding', 0),
                'forward_pe': info.get('forwardPE', 0),
                'trailing_pe': info.get('trailingPE', 0),
            }
        except Exception as e:
            print(f"获取市场数据失败: {e}")
            return {}
    
    def get_all_financial_data(self) -> Dict:
        """
        一次性获取所有财务数据。
        若输入为公司名（如 NVIDIA）导致接口无数据，会尝试用 Search API 解析为股票代码（如 NVDA）再拉取。
        """
        company_info = self.get_company_info()
        market_cap = (company_info.get('market_cap') or 0) if company_info else 0
        resolved_ticker = None
        
        # Yahoo 只认股票代码：无数据时或输入像公司名/中文/首字母时尝试解析为代码
        def _contains_cjk(s: str) -> bool:
            return any('\u4e00' <= ch <= '\u9fff' for ch in (s or ''))

        t = (self.ticker or '').strip()
        looks_like_name = (
            t and '.' not in t and (
                _contains_cjk(t) or
                (not t.isalnum()) or
                (len(t) > 5) or
                (t != t.upper())
            )
        )
        # 当输入为“首字母/简称”（通常 2-8 位字母）但直接拉不到数据时，也尝试解析
        looks_like_initials = t.isalpha() and 2 <= len(t) <= 8 and '.' not in t
        no_financials = False
        try:
            no_financials = (self.get_balance_sheet().empty and self.get_income_statement().empty)
        except Exception:
            no_financials = False

        if (not company_info or not market_cap or no_financials or looks_like_name) and t and '.' not in t:
            original_input = self.ticker
            resolved = self._resolve_company_name_to_ticker(original_input, self.market)
            if resolved and resolved.upper() != original_input.upper():
                self.ticker = resolved
                self.full_ticker = self._format_ticker(resolved, self.market)
                self._fetch_stock_object()
                company_info = self.get_company_info()
                market_cap = (company_info.get('market_cap') or 0) if company_info else 0
                if company_info and market_cap:
                    resolved_ticker = resolved
                    print(f"已根据公司名解析为股票代码: {original_input} → {resolved}")
        # 二次兜底：首字母/简称但第一次没触发 looks_like_name 的情况（例如全大写且较短）
        if (not resolved_ticker) and (looks_like_initials and (not company_info or not market_cap or no_financials)):
            original_input = self.ticker
            resolved = self._resolve_company_name_to_ticker(original_input, self.market)
            if resolved and resolved.upper() != original_input.upper():
                self.ticker = resolved
                self.full_ticker = self._format_ticker(resolved, self.market)
                self._fetch_stock_object()
                company_info = self.get_company_info()
                market_cap = (company_info.get('market_cap') or 0) if company_info else 0
                if company_info and market_cap:
                    resolved_ticker = resolved
                    print(f"已根据简称/首字母解析为股票代码: {original_input} → {resolved}")
        
        result = {
            'company_info': company_info or {},
            'balance_sheet': self.get_balance_sheet(),
            'income_statement': self.get_income_statement(),
            'cash_flow': self.get_cash_flow(),
            'market_data': self.get_market_data(),
        }
        if resolved_ticker:
            result['resolved_ticker'] = resolved_ticker
        return result
    
    def get_risk_free_rate(self) -> float:
        """
        获取无风险利率（10年期国债收益率）
        
        Returns:
            float: 无风险利率
        """
        try:
            # 获取10年期美国国债收益率
            treasury = yf.Ticker("^TNX")
            hist = treasury.history(period="5d")
            if not hist.empty:
                rate = hist['Close'].iloc[-1] / 100  # 转换为小数
                return rate
            return 0.043  # 默认4.3%
        except Exception:
            return 0.043
    
    def get_historical_market_data(self, period: str = "5y") -> dict:
        """
        获取历史市值和Beta数据
        
        Args:
            period: 时间周期
            
        Returns:
            dict: 包含历史数据的字典
        """
        try:
            # 获取历史价格
            hist = self.stock.history(period=period)
            
            if hist.empty:
                return {}
            
            # 计算市值历史（价格 × 流通股数）
            info = self.stock.info
            shares = info.get('sharesOutstanding', 0)
            
            hist['MarketCap'] = hist['Close'] * shares if shares > 0 else 0
            
            # 获取市场指数数据计算Beta
            market_ticker = "^GSPC"  # S&P 500
            market_hist = yf.Ticker(market_ticker).history(period=period)
            
            # 计算滚动Beta（60天窗口）
            if not market_hist.empty:
                stock_returns = hist['Close'].pct_change()
                market_returns = market_hist['Close'].pct_change()
                
                # 对齐数据
                combined = pd.DataFrame({
                    'stock': stock_returns,
                    'market': market_returns
                }).dropna()
                
                # 计算60天滚动Beta
                rolling_window = 60
                betas = []
                dates = []
                
                for i in range(rolling_window, len(combined)):
                    window_data = combined.iloc[i-rolling_window:i]
                    cov = window_data['stock'].cov(window_data['market'])
                    var = window_data['market'].var()
                    beta = cov / var if var != 0 else 1.0
                    betas.append(beta)
                    dates.append(combined.index[i])
                
                beta_series = pd.Series(betas, index=dates)
            else:
                beta_series = pd.Series()
            
            return {
                'dates': hist.index.tolist(),
                'prices': hist['Close'].tolist(),
                'market_cap': hist['MarketCap'].tolist() if 'MarketCap' in hist else [],
                'beta_dates': beta_series.index.tolist() if not beta_series.empty else [],
                'beta_values': beta_series.tolist() if not beta_series.empty else [],
            }
            
        except Exception as e:
            print(f"获取历史数据失败: {e}")
            return {}
    
    def calculate_beta(self, period: str = "5y", method: str = "historical") -> float:
        """
        计算Beta值
        
        Args:
            period: 计算周期 (1y, 2y, 5y)
            method: 计算方法 (historical, blume, vasicek)
            
        Returns:
            float: Beta值
        """
        try:
            # 从info获取beta
            info = self.stock.info
            raw_beta = info.get('beta', None)
            
            # 如果没有beta，手动计算
            stock_hist = self.stock.history(period=period)
            market_hist = yf.Ticker("^GSPC").history(period=period)  # S&P 500
            
            if stock_hist.empty or market_hist.empty:
                return 1.0
            
            # 计算收益率
            stock_returns = stock_hist['Close'].pct_change().dropna()
            market_returns = market_hist['Close'].pct_change().dropna()
            
            # 对齐日期
            combined = pd.DataFrame({
                'stock': stock_returns,
                'market': market_returns
            }).dropna()
            
            if len(combined) < 20:
                return 1.0
            
            # 计算协方差和方差
            covariance = combined['stock'].cov(combined['market'])
            market_variance = combined['market'].var()
            
            raw_beta = covariance / market_variance if market_variance != 0 else 1.0
            
            # 根据方法调整Beta
            if method == "blume":
                # Blume调整: 向1.0回归
                beta = 0.67 * raw_beta + 0.33 * 1.0
            elif method == "vasicek":
                # Vasicek调整: 向行业平均回归（这里简化为1.0）
                industry_beta = 1.0  # 可以扩展为实际行业Beta
                weight = 0.7  # 权重
                beta = weight * raw_beta + (1 - weight) * industry_beta
            else:
                beta = raw_beta
            
            return max(0.1, min(beta, 3.0))  # 限制在0.1-3.0之间
            
        except Exception as e:
            print(f"计算Beta失败: {e}")
            return 1.0
    
    def get_employee_info(self) -> dict:
        """
        获取员工信息
        
        Returns:
            dict: 员工相关信息
        """
        try:
            info = self.stock.info
            return {
                'total_employees': info.get('fullTimeEmployees', 0),
                'description': info.get('longBusinessSummary', ''),
            }
        except Exception:
            return {'total_employees': 0, 'description': ''}


if __name__ == "__main__":
    # 测试代码
    fetcher = DataFetcher("WMT", "US")
    
    print("=== 公司信息 ===")
    info = fetcher.get_company_info()
    for key, value in info.items():
        print(f"{key}: {value}")
    
    print("\n=== 资产负债表 ===")
    bs = fetcher.get_balance_sheet()
    print(bs.head())
    
    print("\n=== 利润表 ===")
    income = fetcher.get_income_statement()
    print(income.head())
