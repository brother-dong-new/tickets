import ReactECharts from 'echarts-for-react';
import type { AISelectedStock } from '../api/stock';

interface AIRadarProps {
  stock: AISelectedStock;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export default function AIRadar({ stock }: AIRadarProps) {
  const tail = stock.indicators.tail_trend;
  const upside = stock.indicators.upside_space;
  const flow = stock.indicators.capital_flow;
  const turnover = stock.turnover ?? 0;
  const vr = stock.volume_ratio ?? 0;

  const tailScore = clamp(tail?.strength ?? 0, 0, 100);

  let spaceScore = 30;
  const space = upside?.space ?? 0;
  if (space >= 5) spaceScore = 100;
  else if (space >= 3) spaceScore = 80;
  else if (space >= 1) spaceScore = 60;

  let flowScore = 50;
  const mi = flow?.main_inflow ?? 0;
  if (mi > 1) flowScore = 100;
  else if (mi > 0.3) flowScore = 80;
  else if (mi > 0) flowScore = 60;
  else if (mi < -0.5) flowScore = 20;
  else if (mi < 0) flowScore = 40;

  let turnoverScore = 60;
  if (turnover >= 5 && turnover <= 12) turnoverScore = 100;
  else if (turnover >= 3 && turnover < 5) turnoverScore = 80;
  else if (turnover > 12 && turnover <= 20) turnoverScore = 50;
  else if (turnover > 20) turnoverScore = 30;
  else if (turnover < 1) turnoverScore = 20;

  let vrScore = 60;
  if (vr >= 1.5 && vr <= 3) vrScore = 100;
  else if (vr >= 1 && vr < 1.5) vrScore = 70;
  else if (vr > 3 && vr <= 5) vrScore = 60;
  else if (vr > 5) vrScore = 30;
  else if (vr < 1) vrScore = 40;

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(15, 23, 42, 0.9)',
      borderColor: '#334155',
      textStyle: { color: '#e2e8f0', fontSize: 11 },
    },
    radar: {
      indicator: [
        { name: '尾盘强度', max: 100 },
        { name: '上涨空间', max: 100 },
        { name: '主力资金', max: 100 },
        { name: '换手活跃', max: 100 },
        { name: '量比健康', max: 100 },
      ],
      center: ['50%', '55%'],
      radius: '65%',
      splitNumber: 4,
      shape: 'polygon',
      axisName: {
        color: '#9ca3af',
        fontSize: 10,
      },
      splitLine: {
        lineStyle: { color: ['#1f2937', '#111827'] },
      },
      splitArea: {
        areaStyle: { color: ['rgba(15,23,42,0.6)', 'rgba(15,23,42,0.3)'] },
      },
      axisLine: { lineStyle: { color: '#334155' } },
    },
    series: [
      {
        name: 'AI评分雷达',
        type: 'radar',
        symbol: 'circle',
        symbolSize: 3,
        areaStyle: {
          color: 'rgba(59,130,246,0.25)',
        },
        lineStyle: {
          color: '#3b82f6',
          width: 2,
        },
        itemStyle: {
          color: '#60a5fa',
        },
        data: [
          {
            value: [tailScore, spaceScore, flowScore, turnoverScore, vrScore],
            name: stock.name,
          },
        ],
      },
    ],
  };

  return (
    <div className="ai-radar">
      <ReactECharts option={option} style={{ height: '180px', width: '100%' }} notMerge={true} />
    </div>
  );
}
