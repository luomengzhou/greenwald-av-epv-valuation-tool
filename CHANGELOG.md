# 更新日志

## v2.3 FF3 回归与测试 (2026-11-09)

- `beta_calculator`: Fama-French 三因子由“分桶估算”改为真实 OLS 回归（numpy），自动下载 Kenneth French 月度因子；下载失败时回退估算并明确标注。CAPM Beta 标准误改为斜率标准误。yfinance 改为延迟导入，纯数学部分无需安装即可使用。
- `adjustments.calculate_depreciation_adjustment`: capex 取绝对值，避免负号导致整笔折旧被当作过度折旧加回。
- 新增 `tests/`（12 个 pytest 用例：Blume、Hamada、FF3 回归、EPV=NOPAT/WACC、FV 符号等）。
- 修复 `docs/site` 仓库链接（旧用户名）；README 补充 AV（权益口径）vs EPV（企业口径）等限制说明。

## v2.2 Franchise Value增长分析 (2026-02-07)

### 🌟 重大新增：Franchise Value模块

**基于Columbia Business School Lecture 4: Growth and Value**

#### 完整的增长价值分析框架

1. **ROIC (投资资本回报率) 分析** ✅
   - 平均ROIC vs WACC对比
   - Invested Capital精确计算
   - 边际ROIC分析（增长投资的真实回报）
   - ROIC vs WACC可视化散点图

2. **盈利增长率 (g) 分解** ✅
   - 投资驱动增长 = k × ROIC
   - 有机增长（同店销售/生产率提升）
   - k值（再投资率）= Growth Capex / NOPAT
   - 增长分解柱状图

3. **Franchise Value计算** ✅
   - **核心公式**：V = EPV + FV
   - **FV公式**：(ROIC - WACC) / (WACC - g) × Growth Investment
   - **关键判断**：只有ROIC > WACC时增长才创造价值
   - FV瀑布图：从EPV到Total Value
   - 完整价值桥：AV → EPV → FV → 市值

4. **预期收益率分析** ✅
   - **收益率公式**：R = D/V + g + (1+g) × h
   - 分配收益率（D/V）计算
   - 多情景预期收益率（乐观/不变/悲观）
   - **收益率热力图**：g vs h 敏感性分析
   - 风险警示：g下降+h为负的"双重打击"

5. **价值创造判断** ✅
   - ROIC > WACC：增长创造价值 ✓
   - ROIC < WACC：增长摧毁价值 ✗
   - 安全边际计算
   - FV/EPV比率
   - 综合投资建议

#### 新增可视化组件

- `create_franchise_value_waterfall()` - FV瀑布图
- `create_roic_vs_wacc_scatter()` - ROIC vs WACC散点图
- `create_growth_decomposition()` - 增长分解图
- `create_return_scenarios_heatmap()` - 收益率情景热力图
- `create_value_bridge()` - 完整价值链

#### 核心计算模块

**文件**: `valuation/franchise_value.py`

- `FranchiseValueCalculator` 类
- `calculate_roic()` - ROIC计算（平均+边际）
- `calculate_growth_rate()` - 增长率分解
- `calculate_franchise_value()` - FV计算
- `calculate_expected_return()` - 预期收益率
- `generate_summary()` - 综合分析

#### 理论基础

完整实现Tano Santos教授的Growth and Value框架：
- ROIC vs WACC的经济利润概念
- k × ROIC的增长动力学
- 有机增长 vs 投资驱动增长
- 市盈率压缩/扩张的收益影响
- Walmart案例完整复现

---

## v2.1 Beta模型重大升级 (2026-02-07)

### 🌟 重大改进：Beta计算完全重构

#### 真正的金融模型（不再是简单的历史周期）

**新增5种Beta计算方法：**

1. **CAPM Beta** ⭐ - 业界标准
   - Goldman Sachs、Morgan Stanley使用
   - 公式：β = Cov(Ri, Rm) / Var(Rm)
   
2. **Fama-French 3因子Beta** 📚 - 学术专业
   - AQR、Two Sigma等对冲基金使用
   - 考虑市场、规模、价值三因子
   
3. **Fama-French 5因子Beta** 📈 - 最新模型
   - 增加盈利能力和投资模式因子
   
4. **Blume调整Beta** 🔄 - Bloomberg方法
   - β_adj = 0.67×β_historical + 0.33×1.0
   - 金融终端默认方法
   
5. **基本面Beta** 💼 - 财务杠杆法
   - 适合新公司和重组后
   - β_L = β_U × [1 + (1-T)×(D/E)]

#### Beta合理性检查

- ⚠️ 自动识别负Beta（对冲资产）
- ⚠️ 警告极端值（<0.1 或 >3.0）
- ℹ️ 显示Beta合理范围
- 📊 对比行业典型Beta

#### 多模型Beta对比

- 一键查看所有方法的计算结果
- 显示R²（解释力）指标
- 推荐最适合当前公司的方法

#### 行业Beta参考

- 11个主要行业的典型Beta值
- Beta合理范围
- 与你分析的公司对比

#### 业界实践指南

- 投资银行：CAPM + Blume
- 对冲基金：Fama-French多因子
- 学术研究：FF3/FF5因子
- 评级机构：标准CAPM

### 📚 新增文档

- **BETA使用指南.md**：80页完整Beta教程
  - 5种方法详细说明
  - 业界实践案例
  - 行业Beta参考表
  - 常见问题解答

### 🔧 技术改进

- ✅ 新增 `valuation/beta_calculator.py` 模块
- ✅ 集成scipy用于统计计算
- ✅ 更新 `app_enhanced.py` 集成新Beta计算器
- ✅ Beta值自动传递到WACC计算
- ✅ 更新 `config/settings.py` 的BETA_METHODS

### 🐛 Bug修复

- 修正Beta概念混淆（历史周期 → 金融模型）
- 添加负Beta识别和警告
- 改进Beta极端值处理

---

## v2.0 增强版 (2026-02-07)

### 🆕 新增功能

#### 1. 简化市场选择
- ✅ 从4个选项简化为3个：美股/港股/A股
- ✅ A股自动识别沪深交易所（600开头→上海，000/300开头→深圳）
- ✅ 统一界面体验

#### 2. 市值和Beta历史展示
- 📈 **市值历史走势**: 点击"查看市值走势"按钮，显示过去5年市值变化
- 📉 **Beta历史走势**: 点击"查看Beta走势"按钮，显示Beta动态变化
- 📅 **数据日期显示**: 所有指标显示数据截止日期
- 🔄 **多种Beta计算方法**:
  - 5年历史Beta
  - 3年历史Beta  
  - 2年历史Beta
  - Blume调整Beta (0.67×历史Beta + 0.33)
  - Vasicek调整Beta (行业加权)

#### 3. AV调整详细说明

每个调整项现在都包含：

##### a. PPE调整
- 📖 **理论依据**: 历史成本 vs 现实成本的详细说明
- 📝 **调整公式**: 完整的计算公式展示
- 🔗 **数据来源**: 房地产数据库参考(Zillow, CoStar等)
- ✏️ **手动输入**:
  - 土地面积和单价
  - 建筑面积和房价
  - 设备价格指数

##### b. 商誉调整
- 📖 **理论依据**: 收购溢价处理原则
- 📅 **整合年份选择**: 滑动条选择整合截止年份
- 📜 **收购历史**: 显示主要收购记录
- ✏️ **手动调整**: 可选择剔除比例

##### c. 员工价值
- 📖 **理论依据**: 人力资本投资说明
- 👥 **员工数据**: 显示公司披露的员工总数
- 💰 **薪酬分类**:
  - 普通员工数量和平均薪酬
  - 管理层人数和平均薪酬
- 🎚️ **成本比例**: 可调整不同级别的培训成本比例

##### d. 品牌价值
- 📖 **两种方法说明**:
  - 特许权费法（公式和参数）
  - 营销公司法（EVA计算）
- 📊 **参考基准**: 不同行业的费率建议

##### e. 产品组合
- 📖 **R&D资本化**: 产品周期折旧说明
- ⏱️ **行业周期**: 不同行业产品周期参考

#### 4. 交互式体验优化

- 💡 **工具提示**: 每个参数都有详细说明
- 📊 **实时更新**: 参数调整后图表立即刷新
- 🎯 **可展开面板**: 高级功能折叠，保持界面简洁
- ℹ️ **信息图标**: 点击查看详细文档

#### 5. WACC计算增强

- 📖 **完整说明**: WACC公式和组成部分
- 🔄 **Beta方法**: 可选择不同Beta计算方法
- 📊 **敏感性分析**: WACC变化对EPV的影响

### 🔧 技术改进

- ✅ 修复所有数据类型错误
- ✅ 优化数据处理流程
- ✅ 增强错误处理
- ✅ 改进缓存机制（使用session_state）
- ✅ 添加数据验证

### 📚 文档更新

- ✅ 新增 `tooltips.py` - 工具提示和说明文本
- ✅ 新增 `CHANGELOG.md` - 更新日志
- ✅ 更新 `README.md` - 添加增强版说明
- ✅ 更新 `USAGE_GUIDE.md` - 详细使用指南

### 🚀 使用方法

**启动增强版:**
```bash
./run_enhanced.sh
```

**或手动启动:**
```bash
streamlit run dashboard/app_enhanced.py
```

**原版仍然可用:**
```bash
streamlit run dashboard/app.py
```

---

## v1.0 初始版本 (2026-02-07)

### 核心功能

- ✅ Asset Value (AV) 计算
- ✅ Earning Power Value (EPV) 计算  
- ✅ 多市场支持（美股/港股/A股沪深）
- ✅ 数据可视化（8种图表）
- ✅ Excel/文本报告导出
- ✅ 参数调整面板
- ✅ 敏感性分析

### 估值方法

#### Asset Value
- 账面权益
- PPE调整（固定资产重估）
- 商誉调整
- 品牌价值（特许权费法/营销公司法）
- 员工价值
- 产品组合价值

#### Earning Power Value
- 7年利润平滑
- 非经常性项目调整
- 折旧调整
- 增长性支出调整
- WACC计算

### 数据来源

- Yahoo Finance API
- 实时市场数据
- 历史财务报表

---

## 后续计划

### v2.1 (计划中)
- [ ] 多公司批量对比
- [ ] 行业平均值参考
- [ ] 更多Beta调整方法
- [ ] PDF报告导出
- [ ] 数据缓存优化

### v2.2 (计划中)
- [ ] 中文财报支持
- [ ] 更多数据源接入
- [ ] AI辅助分析建议
- [ ] 移动端适配

---

**反馈和建议**: 欢迎提出改进意见！
