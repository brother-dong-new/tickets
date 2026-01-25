/**
 * K线图组件
 */
import ReactECharts from 'echarts-for-react';
import type { KLineItem } from '../api/stock';

interface KLineChartProps {
  data: KLineItem[];
  title?: string;
}

export default function KLineChart({ data, title }: KLineChartProps) {
  const dates = data.map((item) => item.date);
  const klineData = data.map((item) => [item.open, item.close, item.low, item.high]);
  const volumes = data.map((item) => item.volume);
  const colors = data.map((item) => (item.close >= item.open ? '#ef4444' : '#22c55e'));

  const option = {
    backgroundColor: 'transparent',
    title: {
      text: title || 'K Line Chart',
      left: 'center',
      textStyle: {
        color: '#e2e8f0',
        fontSize: 16,
        fontWeight: 500,
      },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'cross',
      },
      backgroundColor: 'rgba(15, 23, 42, 0.9)',
      borderColor: '#334155',
      textStyle: {
        color: '#e2e8f0',
      },
      formatter: function (params: any) {
        const dataIndex = params[0]?.dataIndex;
        if (dataIndex === undefined) return '';
        const item = data[dataIndex];
        return `
          <div style="padding: 8px;">
            <div style="font-weight: bold; margin-bottom: 8px;">${item.date}</div>
            <div>Open: ${item.open.toFixed(2)}</div>
            <div>Close: ${item.close.toFixed(2)}</div>
            <div>High: ${item.high.toFixed(2)}</div>
            <div>Low: ${item.low.toFixed(2)}</div>
            <div>Vol: ${(item.volume / 10000).toFixed(2)}W</div>
            ${item.change_percent !== undefined ? `<div>Change: ${item.change_percent.toFixed(2)}%</div>` : ''}
          </div>
        `;
      },
    },
    legend: {
      data: ['K Line', 'Volume'],
      top: 30,
      textStyle: {
        color: '#94a3b8',
      },
    },
    grid: [
      {
        left: '10%',
        right: '10%',
        top: 80,
        height: '50%',
      },
      {
        left: '10%',
        right: '10%',
        top: '72%',
        height: '16%',
      },
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8' },
        splitLine: { show: false },
      },
      {
        type: 'category',
        gridIndex: 1,
        data: dates,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { show: false },
        splitLine: { show: false },
      },
    ],
    yAxis: [
      {
        type: 'value',
        scale: true,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8' },
        splitLine: { lineStyle: { color: '#1e293b' } },
      },
      {
        type: 'value',
        gridIndex: 1,
        scale: true,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: {
          color: '#94a3b8',
          formatter: (value: number) => `${(value / 10000).toFixed(0)}W`,
        },
        splitLine: { lineStyle: { color: '#1e293b' } },
      },
    ],
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1],
        start: 50,
        end: 100,
      },
      {
        show: true,
        xAxisIndex: [0, 1],
        type: 'slider',
        bottom: 10,
        start: 50,
        end: 100,
        borderColor: '#334155',
        backgroundColor: '#0f172a',
        fillerColor: 'rgba(59, 130, 246, 0.2)',
        handleStyle: {
          color: '#3b82f6',
        },
        textStyle: {
          color: '#94a3b8',
        },
      },
    ],
    series: [
      {
        name: 'K Line',
        type: 'candlestick',
        data: klineData,
        itemStyle: {
          color: '#ef4444',
          color0: '#22c55e',
          borderColor: '#ef4444',
          borderColor0: '#22c55e',
        },
      },
      {
        name: 'Volume',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes.map((v, i) => ({
          value: v,
          itemStyle: { color: colors[i] },
        })),
        label: {
          show: true,
          position: 'top',
          formatter: (params: any) => {
            const value = params.value;
            if (value >= 10000) {
              return `${(value / 10000).toFixed(1)}W`;
            }
            return value.toFixed(0);
          },
          color: '#94a3b8',
          fontSize: 10,
        },
      },
    ],
  };

  return (
    <ReactECharts
      option={option}
      style={{ height: '500px', width: '100%' }}
      notMerge={true}
    />
  );
}
