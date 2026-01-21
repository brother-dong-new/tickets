/**
 * 股票筛选器
 * 实现股票筛选和精选过滤功能
 */
import { useState } from 'react';
import { screenStocks, filterStocks } from './api/stock';
import type { ScreenedStock, FilteredStock, AnalysisResult, AISelectedStock, MarketEnvironment } from './api/stock';
import './App.css';

type AppState = 'idle' | 'screening' | 'screened' | 'filtering' | 'filtered';

function App() {
  const [state, setState] = useState<AppState>('idle');
  const [screenedStocks, setScreenedStocks] = useState<ScreenedStock[]>([]);
  const [filteredStocks, setFilteredStocks] = useState<FilteredStock[]>([]);
  const [analysisResults, setAnalysisResults] = useState<AnalysisResult[]>([]);
  const [aiSelectedStocks, setAiSelectedStocks] = useState<AISelectedStock[]>([]);
  const [marketEnv, setMarketEnv] = useState<MarketEnvironment | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 筛选股票
  const handleScreen = async () => {
    setState('screening');
    setError(null);
    setFilteredStocks([]);
    setAnalysisResults([]);
    
    try {
      const result = await screenStocks({
        change_min: 3,
        change_max: 5,
        volume_ratio_min: 1.5,
        volume_ratio_max: 3,
        market_cap_min: 50,
        market_cap_max: 300,
        limit: 20
      });
      setScreenedStocks(result.data);
      setState('screened');
    } catch (err: any) {
      setError(err.response?.data?.detail || '筛选失败，请稍后重试');
      setState('idle');
    }
  };

  // 过滤精选股票
  const handleFilter = async () => {
    if (screenedStocks.length === 0) return;
    
    setState('filtering');
    setError(null);
    
    try {
      const codes = screenedStocks.map(s => s.code);
      const result = await filterStocks(codes);
      setFilteredStocks(result.data);
      setAnalysisResults(result.all_analysis);
      setAiSelectedStocks(result.ai_selected || []);
      setMarketEnv(result.market_environment || null);
      setState('filtered');
    } catch (err: any) {
      setError(err.response?.data?.detail || '过滤失败，请稍后重试');
      setState('screened');
    }
  };

  // 重置
  const handleReset = () => {
    setState('idle');
    setScreenedStocks([]);
    setFilteredStocks([]);
    setAnalysisResults([]);
    setAiSelectedStocks([]);
    setMarketEnv(null);
    setError(null);
  };

  // 格式化金额
  const formatAmount = (amount: number): string => {
    if (amount >= 100000000) {
      return (amount / 100000000).toFixed(2) + '亿';
    } else if (amount >= 10000) {
      return (amount / 10000).toFixed(2) + '万';
    }
    return amount.toFixed(2);
  };

  return (
    <div className="app">
      {/* 头部 */}
      <header className="app-header">
        <div className="header-content">
          <div className="logo">
            <span className="logo-icon">📊</span>
            <h1>股票智能筛选器</h1>
          </div>
          <p className="tagline">基于量价分析的A股精选系统</p>
        </div>
      </header>

      {/* 主内容区 */}
      <main className="app-main">
        {/* 筛选条件说明 */}
        <section className="criteria-section">
          <div className="criteria-card screen-criteria">
            <div className="criteria-header">
              <span className="criteria-icon">🔍</span>
              <h3>第一步：初步筛选</h3>
            </div>
            <div className="criteria-list">
              <div className="criteria-item">
                <span className="label">涨幅范围</span>
                <span className="value">3% - 5%</span>
              </div>
              <div className="criteria-item">
                <span className="label">量比范围</span>
                <span className="value">1.5 - 3</span>
              </div>
              <div className="criteria-item">
                <span className="label">流通市值</span>
                <span className="value">50 - 300亿</span>
              </div>
            </div>
            <button 
              className={`action-btn screen-btn ${state === 'screening' ? 'loading' : ''}`}
              onClick={handleScreen}
              disabled={state === 'screening' || state === 'filtering'}
            >
              {state === 'screening' ? (
                <>
                  <span className="spinner"></span>
                  筛选中...
                </>
              ) : (
                <>
                  <span className="btn-icon">🎯</span>
                  开始筛选
                </>
              )}
            </button>
          </div>

          <div className="criteria-arrow">→</div>

          <div className={`criteria-card filter-criteria ${screenedStocks.length === 0 ? 'disabled' : ''}`}>
            <div className="criteria-header">
              <span className="criteria-icon">⚡</span>
              <h3>第二步：精选过滤</h3>
            </div>
            <div className="criteria-list">
              <div className="criteria-item">
                <span className="label">量价形态</span>
                <span className="value">阶梯式放量</span>
              </div>
              <div className="criteria-item">
                <span className="label">技术位置</span>
                <span className="value">站稳5日线+近期高点</span>
              </div>
              <div className="criteria-item">
                <span className="label">热门板块</span>
                <span className="value">数字经济</span>
              </div>
            </div>
            <button 
              className={`action-btn filter-btn ${state === 'filtering' ? 'loading' : ''}`}
              onClick={handleFilter}
              disabled={screenedStocks.length === 0 || state === 'filtering' || state === 'screening'}
            >
              {state === 'filtering' ? (
                <>
                  <span className="spinner"></span>
                  分析中...
                </>
              ) : (
                <>
                  <span className="btn-icon">✨</span>
                  精选过滤
                </>
              )}
            </button>
          </div>
        </section>

        {/* 错误提示 */}
        {error && (
          <div className="error-banner">
            <span className="error-icon">⚠️</span>
            <span>{error}</span>
            <button onClick={() => setError(null)} className="close-btn">×</button>
          </div>
        )}

        {/* 筛选结果 */}
        {screenedStocks.length > 0 && (
          <section className="results-section">
            <div className="section-header">
              <h2>
                <span className="section-icon">📋</span>
                初步筛选结果
                <span className="count-badge">{screenedStocks.length}只</span>
              </h2>
              {state !== 'idle' && (
                <button className="reset-btn" onClick={handleReset}>
                  重新开始
                </button>
              )}
            </div>
            
            <div className="stock-table">
              <div className="table-header">
                <span className="col-index">#</span>
                <span className="col-name">股票名称</span>
                <span className="col-price">最新价</span>
                <span className="col-change">涨跌幅</span>
                <span className="col-ratio">量比</span>
                <span className="col-cap">流通市值</span>
                <span className="col-turnover">换手率</span>
                <span className="col-amount">成交额</span>
              </div>
              <div className="table-body">
                {screenedStocks.map((stock, index) => (
                  <div 
                    key={stock.code} 
                    className={`table-row ${
                      analysisResults.find(a => a.code === stock.code)?.qualified ? 'qualified' : ''
                    }`}
                  >
                    <span className="col-index">{index + 1}</span>
                    <span className="col-name">
                      <span className="stock-name">{stock.name}</span>
                      <span className="stock-code">{stock.code}</span>
                    </span>
                    <span className="col-price">{stock.price.toFixed(2)}</span>
                    <span className="col-change up">+{stock.change_percent.toFixed(2)}%</span>
                    <span className="col-ratio">{stock.volume_ratio.toFixed(2)}</span>
                    <span className="col-cap">{stock.market_cap.toFixed(1)}亿</span>
                    <span className="col-turnover">{stock.turnover.toFixed(2)}%</span>
                    <span className="col-amount">{formatAmount(stock.amount)}</span>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        {/* 精选结果 */}
        {filteredStocks.length > 0 && (
          <section className="results-section featured">
            <div className="section-header">
              <h2>
                <span className="section-icon">🏆</span>
                精选股票
                <span className="count-badge gold">{filteredStocks.length}只</span>
              </h2>
            </div>
            
            <div className="featured-grid">
              {filteredStocks.map((stock, index) => (
                <div key={stock.code} className="featured-card">
                  <div className="card-rank">#{index + 1}</div>
                  <div className="card-header">
                    <div className="stock-info">
                      <span className="stock-name">{stock.name}</span>
                      <span className="stock-code">{stock.code}</span>
                    </div>
                    <div className="stock-price">
                      <span className="price">{stock.price.toFixed(2)}</span>
                      <span className="change up">+{stock.change_percent.toFixed(2)}%</span>
                    </div>
                  </div>
                  
                  <div className="card-metrics">
                    <div className="metric">
                      <span className="metric-label">量比</span>
                      <span className="metric-value">{stock.volume_ratio.toFixed(2)}</span>
                    </div>
                    <div className="metric">
                      <span className="metric-label">市值</span>
                      <span className="metric-value">{stock.market_cap.toFixed(1)}亿</span>
                    </div>
                    <div className="metric">
                      <span className="metric-label">5日均线</span>
                      <span className="metric-value">{stock.ma5.toFixed(2)}</span>
                    </div>
                    <div className="metric">
                      <span className="metric-label">支撑位</span>
                      <span className="metric-value">{stock.support_level.toFixed(2)}</span>
                    </div>
                  </div>
                  
                  <div className="card-analysis">
                    <div className="analysis-item">
                      <span className={stock.analysis.volume_pattern.includes('✓') ? 'pass' : 'fail'}>
                        {stock.analysis.volume_pattern}
                      </span>
                    </div>
                    <div className="analysis-item">
                      <span className={stock.analysis.price_position.includes('✓') ? 'pass' : 'fail'}>
                        {stock.analysis.price_position}
                      </span>
                    </div>
                    <div className="analysis-item">
                      <span className={stock.analysis.sector.includes('✓') ? 'pass' : 'fail'}>
                        {stock.analysis.sector}
                      </span>
                    </div>
                  </div>
                  
                  {/* 30分钟成交量趋势图 */}
                  {stock.minute_volume && stock.minute_volume.length > 0 && (
                    <div className="volume-chart">
                      <div className="chart-header">
                        <span className="chart-title">📊 近30分钟行情</span>
                        <span className="chart-time">
                          {stock.minute_volume[0]?.time} - {stock.minute_volume[stock.minute_volume.length - 1]?.time}
                        </span>
                      </div>
                      {/* 价格区间显示 */}
                      {(() => {
                        const prices = stock.minute_volume.map(m => m.price);
                        const minPrice = Math.min(...prices);
                        const maxPrice = Math.max(...prices);
                        const firstPrice = stock.minute_volume[0].price;
                        const lastPrice = stock.minute_volume[stock.minute_volume.length - 1].price;
                        const priceChange = lastPrice - firstPrice;
                        return (
                          <div className="price-summary">
                            <span className="price-range">
                              价格区间: {minPrice.toFixed(2)} - {maxPrice.toFixed(2)}
                            </span>
                            <span className={`price-change ${priceChange >= 0 ? 'up' : 'down'}`}>
                              {priceChange >= 0 ? '+' : ''}{priceChange.toFixed(2)}
                            </span>
                          </div>
                        );
                      })()}
                      {/* 价格折线 + 成交量柱状图 */}
                      <div className="chart-wrapper">
                        {(() => {
                          const prices = stock.minute_volume.map(m => m.price);
                          const minPrice = Math.min(...prices);
                          const maxPrice = Math.max(...prices);
                          const priceRange = maxPrice - minPrice || 1;
                          const maxVolume = Math.max(...stock.minute_volume.map(m => m.volume));
                          
                          // 生成价格折线的SVG路径
                          const points = stock.minute_volume.map((m, idx) => {
                            const x = (idx / (stock.minute_volume!.length - 1)) * 100;
                            const y = 100 - ((m.price - minPrice) / priceRange) * 100;
                            return `${x},${y}`;
                          }).join(' ');
                          
                          return (
                            <>
                              {/* 成交量柱状图 */}
                              <div className="chart-container">
                                {stock.minute_volume.map((m, idx) => (
                                  <div 
                                    key={idx} 
                                    className="volume-bar"
                                    style={{ 
                                      height: `${maxVolume > 0 ? (m.volume / maxVolume) * 100 : 0}%`,
                                      opacity: 0.3 + (idx / stock.minute_volume!.length) * 0.5
                                    }}
                                    title={`${m.time}\n价格: ${m.price.toFixed(2)}\n成交量: ${m.volume}手`}
                                  />
                                ))}
                              </div>
                              {/* 价格折线叠加 */}
                              <svg className="price-line-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
                                <polyline
                                  points={points}
                                  fill="none"
                                  stroke="var(--color-gold)"
                                  strokeWidth="2"
                                  vectorEffect="non-scaling-stroke"
                                />
                              </svg>
                            </>
                          );
                        })()}
                      </div>
                      <div className="chart-labels">
                        <span>{stock.minute_volume[0]?.time}</span>
                        <span className="chart-legend">
                          <span className="legend-volume">■ 成交量</span>
                          <span className="legend-price">— 价格</span>
                        </span>
                        <span>{stock.minute_volume[stock.minute_volume.length - 1]?.time}</span>
                      </div>
                    </div>
                  )}
                  
                  {/* 利空消息提示 */}
                  {stock.negative_news && (
                    <div className={`news-alert ${stock.negative_news.risk_level}`}>
                      <div className="news-alert-header">
                        <span className="news-icon">
                          {stock.negative_news.has_negative_news ? '⚠️' : '✅'}
                        </span>
                        <span className="news-title">
                          {stock.negative_news.has_negative_news 
                            ? `发现 ${stock.negative_news.negative_count} 条利空消息` 
                            : '近3日无利空消息'}
                        </span>
                        <span className={`risk-badge ${stock.negative_news.risk_level}`}>
                          {stock.negative_news.risk_level === 'high' ? '高风险' : 
                           stock.negative_news.risk_level === 'medium' ? '需关注' : '低风险'}
                        </span>
                      </div>
                      {stock.negative_news.negative_news.length > 0 && (
                        <div className="news-list">
                          {stock.negative_news.negative_news.slice(0, 3).map((news, idx) => (
                            <div key={idx} className="news-item">
                              <span className="news-date">{news.date}</span>
                              <span className="news-text">{news.title}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {/* AI精选股票 */}
        {aiSelectedStocks.length > 0 && (
          <section className="results-section ai-featured">
            <div className="section-header">
              <h2>
                <span className="section-icon">🤖</span>
                AI智能精选
                <span className="count-badge ai">{aiSelectedStocks.length}只</span>
              </h2>
              {marketEnv && (
                <div className={`market-status ${marketEnv.safe_to_buy ? 'safe' : 'caution'}`}>
                  <span className="market-icon">{marketEnv.safe_to_buy ? '🟢' : '🟡'}</span>
                  <span>上证 {marketEnv.index_change >= 0 ? '+' : ''}{marketEnv.index_change.toFixed(2)}%</span>
                  <span className="market-tag">
                    {marketEnv.market_sentiment === 'bullish' ? '多头市场' : 
                     marketEnv.market_sentiment === 'bearish' ? '空头市场' : '震荡市场'}
                  </span>
                </div>
              )}
            </div>
            
            <div className="ai-grid">
              {aiSelectedStocks.map((stock, index) => (
                <div key={stock.code} className="ai-card">
                  <div className="ai-card-header">
                    <div className="ai-rank">
                      <span className="rank-icon">🏅</span>
                      <span className="rank-num">#{index + 1}</span>
                    </div>
                    <div className="ai-stock-info">
                      <span className="ai-stock-name">{stock.name}</span>
                      <span className="ai-stock-code">{stock.code}</span>
                    </div>
                    <div className="ai-score">
                      <span className="score-label">AI评分</span>
                      <span className={`score-value ${stock.score >= 60 ? 'high' : stock.score >= 40 ? 'medium' : 'low'}`}>
                        {stock.score}
                      </span>
                    </div>
                  </div>
                  
                  <div className="ai-price-row">
                    <span className="ai-price">{stock.price.toFixed(2)}</span>
                    <span className={`ai-change ${stock.change_percent >= 0 ? 'up' : 'down'}`}>
                      {stock.change_percent >= 0 ? '+' : ''}{stock.change_percent.toFixed(2)}%
                    </span>
                  </div>
                  
                  {/* T+1短线核心指标 */}
                  <div className="ai-indicators">
                    <div className="indicator wide">
                      <span className="ind-label">尾盘走势</span>
                      <span className={`ind-value ${
                        stock.indicators.tail_trend.trend === 'strong_up' ? 'good' : 
                        stock.indicators.tail_trend.trend === 'up' ? 'good' : 
                        stock.indicators.tail_trend.trend === 'down' ? 'warn' : ''
                      }`}>
                        {stock.indicators.tail_trend.trend === 'strong_up' ? '🚀 强势拉升' :
                         stock.indicators.tail_trend.trend === 'up' ? '📈 温和上涨' :
                         stock.indicators.tail_trend.trend === 'down' ? '📉 回落' :
                         stock.indicators.tail_trend.trend === 'stable' ? '➡️ 平稳' : '—'}
                      </span>
                    </div>
                    <div className="indicator wide">
                      <span className="ind-label">距涨停空间</span>
                      <span className={`ind-value ${
                        stock.indicators.upside_space.space >= 5 ? 'good' : 
                        stock.indicators.upside_space.near_limit ? 'warn' : ''
                      }`}>
                        {stock.indicators.upside_space.space.toFixed(1)}%
                      </span>
                    </div>
                    <div className="indicator">
                      <span className="ind-label">主力资金</span>
                      <span className={`ind-value ${stock.indicators.capital_flow.is_inflow ? 'good' : 'warn'}`}>
                        {stock.indicators.capital_flow.is_inflow ? '+' : ''}{stock.indicators.capital_flow.main_inflow}亿
                      </span>
                    </div>
                    <div className="indicator">
                      <span className="ind-label">明日预判</span>
                      <span className={`ind-value ${
                        stock.indicators.open_probability === 'high' ? 'good' : 
                        stock.indicators.open_probability === 'low' ? 'warn' : ''
                      }`}>
                        {stock.indicators.open_probability === 'high' ? '🟢 高开' :
                         stock.indicators.open_probability === 'medium' ? '🟡 平开' : '🔴 低开'}
                      </span>
                    </div>
                  </div>
                  
                  {/* 选股理由 */}
                  {stock.reasons.length > 0 && (
                    <div className="ai-reasons">
                      <div className="reasons-title">✅ 选股理由</div>
                      <ul className="reasons-list">
                        {stock.reasons.map((reason, idx) => (
                          <li key={idx}>{reason}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  
                  {/* 风险提示 */}
                  {stock.warnings.length > 0 && (
                    <div className="ai-warnings">
                      <div className="warnings-title">⚠️ 风险提示</div>
                      <ul className="warnings-list">
                        {stock.warnings.map((warning, idx) => (
                          <li key={idx}>{warning}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  
                  {/* 利空消息 */}
                  {stock.negative_news && (
                    <div className={`ai-news-alert ${stock.negative_news.risk_level}`}>
                      <span className="news-icon">{stock.negative_news.has_negative_news ? '⚠️' : '✅'}</span>
                      <span>{stock.negative_news.has_negative_news 
                        ? `${stock.negative_news.negative_count}条利空` 
                        : '无利空消息'}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {/* 分析详情 */}
        {analysisResults.length > 0 && (
          <section className="results-section analysis">
            <div className="section-header">
              <h2>
                <span className="section-icon">📊</span>
                分析详情
              </h2>
            </div>
            
            <div className="analysis-table">
              <div className="table-header">
                <span className="col-name">股票</span>
                <span className="col-check">阶梯放量</span>
                <span className="col-check">站稳5日线</span>
                <span className="col-check">数字经济</span>
                <span className="col-ma5">5日均线</span>
                <span className="col-support">支撑位</span>
                <span className="col-result">结果</span>
              </div>
              <div className="table-body">
                {analysisResults.map((result) => (
                  <div key={result.code} className={`table-row ${result.qualified ? 'qualified' : ''}`}>
                    <span className="col-name">
                      <span className="stock-name">{result.name}</span>
                      <span className="stock-code">{result.code}</span>
                    </span>
                    <span className="col-check">
                      {result.has_volume_pattern ? '✅' : '❌'}
                    </span>
                    <span className="col-check">
                      {result.above_ma5_high ? '✅' : '❌'}
                    </span>
                    <span className="col-check">
                      {result.is_digital_economy ? '✅' : '❌'}
                    </span>
                    <span className="col-ma5">{result.ma5.toFixed(2)}</span>
                    <span className="col-support">{result.support_level.toFixed(2)}</span>
                    <span className="col-result">
                      {result.qualified ? (
                        <span className="result-pass">通过</span>
                      ) : (
                        <span className="result-fail">未通过</span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        {/* 空状态 */}
        {state === 'idle' && (
          <section className="empty-state">
            <div className="empty-content">
              <span className="empty-icon">🚀</span>
              <h2>开始智能选股</h2>
              <p>点击上方「开始筛选」按钮，系统将自动筛选符合条件的股票</p>
            </div>
          </section>
        )}
      </main>

      {/* 底部 */}
      <footer className="app-footer">
        <p>数据来源：东方财富 | 仅供参考，不构成投资建议</p>
      </footer>
    </div>
  );
}

export default App;
