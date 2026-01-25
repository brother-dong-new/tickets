import type { FinalPick } from '../api/stock';

interface FinalPickCardProps {
  pick: FinalPick;
}

export default function FinalPickCard({ pick }: FinalPickCardProps) {
  return (
    <div className="featured-card">
      <div className="card-header">
        <div className="stock-info">
          {pick.rank && <span className="rank-badge">#{pick.rank}</span>}
          <span className="stock-name">{pick.name}</span>
          <span className="stock-code">{pick.code}</span>
          {pick.board_type && (
            <span
              className="board-tag"
              style={{ backgroundColor: pick.board_type.color }}
              title={pick.board_type.risk_note}
            >
              {pick.board_type.name}
            </span>
          )}
          {/* 新增：来源标签 */}
          {pick.source_label && (
            <span 
              className={`source-tag ${pick.source === 'ai' ? 'source-ai' : 'source-technical'}`}
              title={pick.source === 'ai' ? '基于12维度AI综合评分' : '基于技术指标筛选补充'}
            >
              {pick.source_label}
            </span>
          )}
          {/* 新增：热门行业标识 */}
          {pick.is_hot_industry && (
            <span 
              className="hot-industry-tag"
              title={`所属行业(${pick.concepts?.join('/')})近30分钟主力资金大幅抢筹(>=1亿)`}
            >
              🔥 热门行业
            </span>
          )}
        </div>
        <div className="stock-price">
          <span className="price">{pick.price.toFixed(2)}</span>
          <span className="change up">+{pick.change_percent.toFixed(2)}%</span>
        </div>
      </div>

      {/* 综合分析总结 */}
      <div className="card-analysis">
        <div className="analysis-item">
          <span className="pass">综合结论：</span>
          <span>{pick.summary}</span>
        </div>
      </div>

      {/* 评分与明日预判 */}
      <div className="card-metrics">
        {typeof pick.score === 'number' && (
          <div className="metric">
            <span className="metric-label">AI评分</span>
            <span className="metric-value">{pick.score}</span>
          </div>
        )}
        {pick.open_probability && (
          <div className="metric">
            <span className="metric-label">明日高开概率</span>
            <span className="metric-value">
              {pick.open_probability === 'high'
                ? '高'
                : pick.open_probability === 'medium'
                ? '中'
                : '低'}
            </span>
          </div>
        )}
        {pick.capital_flow && (
          <div className="metric">
            <span className="metric-label">主力资金</span>
            <span className="metric-value">
              {pick.capital_flow.is_inflow ? '+' : ''}
              {pick.capital_flow.main_inflow}亿
            </span>
          </div>
        )}
        {/* 新增：市值信息 */}
        {pick.market_cap && (
          <div className="metric">
            <span className="metric-label">流通市值</span>
            <span className="metric-value">{pick.market_cap.toFixed(1)}亿</span>
          </div>
        )}
      </div>

      {/* 新增：行业概念信息 */}
      {pick.concepts && pick.concepts.length > 0 && (
        <div className="card-concepts">
          <span className="concepts-label">所属行业：</span>
          <div className="concepts-tags">
            {pick.concepts.map((concept, idx) => (
              <span key={idx} className="concept-tag">
                {concept}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* 选股理由详细分解 */}
      {pick.reasons.length > 0 && (
        <div className="ai-reasons">
          <div className="reasons-title">✅ 选股逻辑拆解</div>
          <ul className="reasons-list">
            {pick.reasons.map((reason, idx) => (
              <li key={idx}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      {/* 风险提示 */}
      {pick.warnings.length > 0 && (
        <div className="ai-warnings">
          <div className="warnings-title">⚠️ 风险点</div>
          <ul className="warnings-list">
            {pick.warnings.map((warning, idx) => (
              <li key={idx}>{warning}</li>
            ))}
          </ul>
        </div>
      )}

      {/* 交易计划（止损止盈） */}
      {pick.trade_plan && (
        <div className="trade-plan">
          <div className="trade-plan-title">💰 交易计划（T+1）</div>
          <div className="trade-plan-content">
            <div className="trade-row">
              <span className="trade-label">建议买入价：</span>
              <span className="trade-value entry">{pick.trade_plan.entry_price.toFixed(2)}元</span>
              <span className="trade-note">（{pick.trade_plan.entry_time}）</span>
            </div>
            <div className="trade-row">
              <span className="trade-label">止损价：</span>
              <span className="trade-value stop-loss">{pick.trade_plan.stop_loss_price.toFixed(2)}元</span>
              <span className="trade-ratio loss">（{pick.trade_plan.stop_loss_ratio.toFixed(1)}%）</span>
            </div>
            <div className="trade-row">
              <span className="trade-label">止盈价：</span>
              <span className="trade-value take-profit">{pick.trade_plan.take_profit_price.toFixed(2)}元</span>
              <span className="trade-ratio profit">（+{pick.trade_plan.take_profit_ratio.toFixed(1)}%）</span>
            </div>
            <div className="trade-row">
              <span className="trade-label">次日预期：</span>
              <span className="trade-value expected">{pick.trade_plan.expected_return >= 0 ? '+' : ''}{pick.trade_plan.expected_return.toFixed(1)}%</span>
              <span className="trade-note">（盈亏比 {pick.trade_plan.risk_reward_ratio}:1）</span>
            </div>
          </div>
        </div>
      )}

      {/* 操作建议 */}
      {pick.operation_tips && pick.operation_tips.length > 0 && (
        <div className="operation-tips">
          <div className="operation-title">📌 操作建议</div>
          <ul className="operation-list">
            {pick.operation_tips.map((tip, idx) => (
              <li key={idx}>{tip}</li>
            ))}
          </ul>
        </div>
      )}

      {/* 利空风险概览 */}
      {pick.negative_risk && (
        <div className={`news-alert ${pick.negative_risk.risk_level}`}>
          <div className="news-alert-header">
            <span className="news-icon">
              {pick.negative_risk.has_negative_news ? '⚠️' : '✅'}
            </span>
            <span className="news-title">
              {pick.negative_risk.has_negative_news
                ? `发现 ${pick.negative_risk.negative_count} 条利空消息`
                : '近3日无明显利空'}
            </span>
          </div>
        </div>
      )}

      {/* 大盘环境简述 */}
      {pick.market_environment && (
        <div className="market-status">
          <span className="market-icon">
            {pick.market_environment.safe_to_buy ? '🟢' : '🟡'}
          </span>
          <span>
            {pick.market_environment.index_name || '上证'} {pick.market_environment.index_change >= 0 ? '+' : ''}
            {pick.market_environment.index_change.toFixed(2)}%
          </span>
          <span className="market-tag">
            {pick.market_environment.market_sentiment === 'bullish'
              ? '多头环境'
              : pick.market_environment.market_sentiment === 'bearish'
              ? '空头环境'
              : '震荡环境'}
          </span>
        </div>
      )}
    </div>
  );
}
