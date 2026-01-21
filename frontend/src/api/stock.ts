/**
 * 股票API服务
 */
import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';

const api = axios.create({
  baseURL: API_BASE,
  timeout: 60000,
});

// 筛选后的股票信息
export interface ScreenedStock {
  code: string;
  name: string;
  price: number;
  change: number;
  change_percent: number;
  volume_ratio: number;
  turnover: number;
  market_cap: number;
  amount: number;
  volume: number;
}

// 利空消息详情
export interface NegativeNewsItem {
  title: string;
  date: string;
  source: string;
  keywords: string[];
}

// 利空消息检测结果
export interface NegativeNewsInfo {
  has_negative_news: boolean;
  negative_count: number;
  total_news_count: number;
  negative_news: NegativeNewsItem[];
  risk_level: 'low' | 'medium' | 'high';
}

// 分时成交量数据
export interface MinuteVolumeItem {
  time: string;
  price: number;
  volume: number;
  cum_volume: number;
}

// 过滤后的精选股票信息
export interface FilteredStock {
  code: string;
  name: string;
  price: number;
  change_percent: number;
  volume_ratio: number;
  market_cap: number;
  turnover?: number;
  amount?: number;
  ma5: number;
  support_level: number;
  analysis: {
    volume_pattern: string;
    price_position: string;
    sector: string;
  };
  negative_news?: NegativeNewsInfo;
  minute_volume?: MinuteVolumeItem[];
}

// 分析结果
export interface AnalysisResult {
  code: string;
  name: string;
  price: number;
  change_percent: number;
  volume_ratio: number;
  market_cap: number;
  ma5: number;
  support_level: number;
  has_volume_pattern: boolean;
  above_ma5_high: boolean;
  is_digital_economy: boolean;
  qualified: boolean;
}

export interface StockQuote {
  code: string;
  name: string;
  price: number;
  change: number;
  change_percent: number;
  volume: number;
  amount: number;
  high: number;
  low: number;
  open: number;
  pre_close: number;
  turnover?: number;
  volume_ratio?: number;
  pe_ratio?: number;
  total_value?: number;
  market_cap?: number;
}

export interface KLineItem {
  date: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
  amount?: number;
  change_percent?: number;
}

export interface IndexData {
  code: string;
  name: string;
  price: number;
  change: number;
  change_percent: number;
  volume: number;
  amount: number;
}

// 筛选股票
export async function screenStocks(params?: {
  change_min?: number;
  change_max?: number;
  volume_ratio_min?: number;
  volume_ratio_max?: number;
  market_cap_min?: number;
  market_cap_max?: number;
  limit?: number;
}): Promise<{
  count: number;
  criteria: {
    change_range: string;
    volume_ratio_range: string;
    market_cap_range: string;
  };
  data: ScreenedStock[];
}> {
  const response = await api.get('/screen', { params });
  return response.data;
}

// 过滤精选股票
export async function filterStocks(codes: string[]): Promise<{
  count: number;
  total_analyzed: number;
  filter_criteria: {
    volume_pattern: string;
    price_position: string;
    sector: string;
  };
  data: FilteredStock[];
  all_analysis: AnalysisResult[];
}> {
  const response = await api.get('/filter', { 
    params: { codes: codes.join(',') } 
  });
  return response.data;
}

// 获取实时行情
export async function getRealtimeQuote(code: string): Promise<StockQuote> {
  const response = await api.get('/realtime', { params: { code } });
  return response.data;
}

// 获取K线数据
export async function getKLineData(
  code: string,
  period: 'daily' | 'weekly' | 'monthly' = 'daily',
  days: number = 90
): Promise<{ code: string; period: string; data: KLineItem[] }> {
  const response = await api.get('/kline', { params: { code, period, days } });
  return response.data;
}

// 获取热门股票
export async function getHotStocks(limit: number = 20): Promise<{ count: number; data: StockQuote[] }> {
  const response = await api.get('/hot', { params: { limit } });
  return response.data;
}

// 获取主要指数
export async function getIndexData(): Promise<{ data: IndexData[] }> {
  const response = await api.get('/index');
  return response.data;
}
