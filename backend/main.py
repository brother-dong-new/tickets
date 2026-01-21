"""
A股行情数据API服务
使用 FastAPI + 腾讯股票API 获取实时股票数据
"""

import os
import re
import subprocess
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

# 禁用代理
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'
for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    if key in os.environ:
        del os.environ[key]

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
import pandas as pd
from datetime import datetime, timedelta

app = FastAPI(
    title="A股行情API",
    description="提供A股实时行情、K线数据、股票筛选等接口",
    version="2.3.0"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def fetch_qq_stock_data(codes: List[str], timeout: int = 30) -> str:
    """使用curl调用腾讯股票API"""
    try:
        # 格式化代码：sh600000, sz000001
        formatted_codes = ",".join(codes)
        url = f"https://qt.gtimg.cn/q={formatted_codes}"
        
        cmd = ['curl', '-s', '--connect-timeout', str(timeout), url]
        result = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
        
        if result.returncode == 0:
            # 尝试用gbk解码
            for enc in ['gbk', 'gb2312', 'utf-8', 'latin-1']:
                try:
                    return result.stdout.decode(enc)
                except (UnicodeDecodeError, LookupError):
                    continue
            return result.stdout.decode('latin-1')
        raise Exception(f"请求失败: {result.stderr.decode('utf-8', errors='ignore')}")
    except subprocess.TimeoutExpired:
        raise Exception("请求超时")


def fetch_qq_kline_data(code: str, days: int = 120) -> Dict[str, Any]:
    """获取腾讯K线数据"""
    try:
        # 确定市场前缀
        if code.startswith('6') or code.startswith('9'):
            symbol = f"sh{code}"
        else:
            symbol = f"sz{code}"
        
        start_date = (datetime.now() - timedelta(days=days*2)).strftime('%Y-%m-%d')
        url = f"https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get?param={symbol},day,{start_date},,{days},qfq"
        
        cmd = ['curl', '-s', '--connect-timeout', '15', url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        
        if result.returncode == 0 and result.stdout:
            return json.loads(result.stdout)
        return {}
    except Exception as e:
        print(f"获取K线数据失败: {e}")
        return {}


def parse_qq_stock_line(line: str) -> Dict[str, Any]:
    """解析腾讯股票数据行"""
    # 格式: v_sh600000="1~浦发银行~600000~10.85~..."
    match = re.match(r'v_(\w+)="(.*)";?', line.strip())
    if not match:
        return None
    
    full_code = match.group(1)
    data = match.group(2)
    
    if not data or data == '':
        return None
    
    parts = data.split('~')
    if len(parts) < 50:
        return None
    
    try:
        # 腾讯数据字段说明：
        # 0: 未知, 1: 股票名称, 2: 代码, 3: 最新价, 4: 昨收
        # 5: 今开, 6: 成交量(手), 31: 涨跌额, 32: 涨跌幅
        # 38: 换手率, 39: 市盈率, 44: 最高, 45: 最低
        # 46: 振幅, 47: 流通市值(亿), 48: 总市值(亿)
        # 49: 市净率, 52: 量比
        
        price = float(parts[3]) if parts[3] and parts[3] != '' else 0
        if price <= 0:
            return None
        
        return {
            'code': parts[2],
            'name': parts[1],
            'price': price,
            'pre_close': float(parts[4]) if parts[4] else 0,
            'open': float(parts[5]) if parts[5] else 0,
            'volume': float(parts[6]) if parts[6] else 0,  # 手
            'change': float(parts[31]) if len(parts) > 31 and parts[31] else 0,
            'change_percent': float(parts[32]) if len(parts) > 32 and parts[32] else 0,
            'high': float(parts[33]) if len(parts) > 33 and parts[33] else 0,
            'low': float(parts[34]) if len(parts) > 34 and parts[34] else 0,
            'amount': float(parts[37]) if len(parts) > 37 and parts[37] else 0,  # 万元
            'turnover': float(parts[38]) if len(parts) > 38 and parts[38] else 0,
            'pe_ratio': float(parts[39]) if len(parts) > 39 and parts[39] else 0,
            'market_cap': float(parts[45]) if len(parts) > 45 and parts[45] else 0,  # 亿
            'total_value': float(parts[46]) if len(parts) > 46 and parts[46] else 0,  # 亿
            'volume_ratio': float(parts[49]) if len(parts) > 49 and parts[49] else 1.0,
        }
    except (ValueError, IndexError) as e:
        return None


def generate_stock_codes() -> List[str]:
    """生成A股代码列表"""
    codes = []
    
    # 沪市主板: 600xxx, 601xxx, 603xxx, 605xxx
    for prefix in ['600', '601', '603', '605']:
        for i in range(1000):
            codes.append(f"sh{prefix}{i:03d}")
    
    # 深市主板: 000xxx, 001xxx, 002xxx, 003xxx
    for prefix in ['000', '001', '002', '003']:
        for i in range(1000):
            codes.append(f"sz{prefix}{i:03d}")
    
    # 创业板: 300xxx, 301xxx
    for prefix in ['300', '301']:
        for i in range(1000):
            codes.append(f"sz{prefix}{i:03d}")
    
    # 科创板: 688xxx
    for i in range(1000):
        codes.append(f"sh688{i:03d}")
    
    return codes


def get_all_stocks_data() -> List[Dict[str, Any]]:
    """获取所有A股实时数据"""
    all_codes = generate_stock_codes()
    batch_size = 80  # 每批80只
    all_stocks = []
    
    def fetch_batch(batch_codes):
        try:
            data = fetch_qq_stock_data(batch_codes)
            results = []
            for line in data.strip().split('\n'):
                if line:
                    stock = parse_qq_stock_line(line)
                    if stock:
                        results.append(stock)
            return results
        except Exception as e:
            print(f"获取批次失败: {e}")
            return []
    
    # 使用线程池并行获取
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for i in range(0, len(all_codes), batch_size):
            batch = all_codes[i:i+batch_size]
            futures.append(executor.submit(fetch_batch, batch))
        
        for future in as_completed(futures):
            try:
                stocks = future.result()
                all_stocks.extend(stocks)
            except Exception as e:
                print(f"处理批次失败: {e}")
    
    return all_stocks


# 数字经济板块关键词
DIGITAL_KEYWORDS = [
    "软件", "科技", "信息", "数据", "智能", "网络", "电子",
    "计算", "云", "芯", "半导体", "通信", "互联", "数字",
    "算力", "存储", "服务器", "安全", "光电", "集成", "微电"
]

# 利空消息关键词
NEGATIVE_KEYWORDS = [
    # 业绩相关
    "亏损", "下滑", "下降", "减少", "预亏", "预减", "首亏", "续亏", "巨亏",
    # 监管相关
    "处罚", "立案", "调查", "警示", "问询", "违规", "违法", "整改", "罚款",
    # 风险相关
    "诉讼", "仲裁", "纠纷", "索赔", "败诉", "冻结", "查封",
    # 股权相关
    "减持", "清仓", "质押", "爆仓", "平仓", "强制执行",
    # 经营相关
    "停产", "停工", "召回", "事故", "退市", "暂停上市", "终止上市",
    "破产", "重整", "清算", "解散",
    # ST相关
    "ST", "*ST", "风险警示", "退市风险",
    # 其他
    "取消", "终止", "失败", "延期", "推迟", "负面", "不利"
]


def get_stock_news(code: str, days: int = 3) -> List[Dict[str, Any]]:
    """获取股票相关新闻和公告（东方财富）"""
    news_list = []
    
    try:
        # 获取公司公告
        # 沪市代码以6开头，深市其他
        if code.startswith('6'):
            market = "SH"
        else:
            market = "SZ"
        
        # 东方财富公告接口
        url = f"https://np-anotice-stock.eastmoney.com/api/security/ann?sr=-1&page_size=30&page_index=1&ann_type=A&stock_list={market}{code}&f_node=0"
        
        cmd = [
            'curl', '-s', '--connect-timeout', '10',
            '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            '-H', 'Referer: https://data.eastmoney.com/',
            url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        
        if result.returncode == 0 and result.stdout:
            data = json.loads(result.stdout)
            if data.get('success') and data.get('data', {}).get('list'):
                # 计算3天前的日期
                three_days_ago = datetime.now() - timedelta(days=days)
                
                for item in data['data']['list']:
                    try:
                        # 解析公告时间
                        notice_date_str = item.get('notice_date', '')
                        if notice_date_str:
                            notice_date = datetime.strptime(notice_date_str[:10], '%Y-%m-%d')
                            
                            # 只保留最近N天的公告
                            if notice_date >= three_days_ago:
                                news_list.append({
                                    'title': item.get('title', ''),
                                    'date': notice_date_str[:10],
                                    'type': 'announcement',
                                    'source': '公司公告'
                                })
                    except Exception:
                        continue
    except Exception as e:
        print(f"获取公告失败 {code}: {e}")
    
    try:
        # 获取股票新闻（东方财富搜索）
        search_url = f"https://searchapi.eastmoney.com/api/Info/search?appid=default&searchScope=&type=NP&pageNo=1&pageSize=20&keyword={code}"
        
        cmd = [
            'curl', '-s', '--connect-timeout', '10',
            '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            '-H', 'Referer: https://so.eastmoney.com/',
            search_url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        
        if result.returncode == 0 and result.stdout:
            data = json.loads(result.stdout)
            if data.get('result') and data['result'].get('data'):
                three_days_ago = datetime.now() - timedelta(days=days)
                
                for item in data['result']['data']:
                    try:
                        title = item.get('title', '').replace('<em>', '').replace('</em>', '')
                        date_str = item.get('datetime', '')[:10]
                        
                        if date_str:
                            news_date = datetime.strptime(date_str, '%Y-%m-%d')
                            if news_date >= three_days_ago:
                                news_list.append({
                                    'title': title,
                                    'date': date_str,
                                    'type': 'news',
                                    'source': item.get('source', '财经新闻')
                                })
                    except Exception:
                        continue
    except Exception as e:
        print(f"获取新闻失败 {code}: {e}")
    
    return news_list


def get_minute_data(code: str, minutes: int = 30) -> Dict[str, Any]:
    """获取分时成交量数据
    
    A股交易时间：
    - 上午：9:30 - 11:30
    - 下午：13:00 - 15:00
    
    逻辑：
    - 交易时间内：返回最近N分钟数据
    - 收盘后（15:00之后）：返回尾盘数据（14:27-14:57）
    
    返回：包含数据和时间范围的字典
    """
    from datetime import datetime
    
    empty_result = {
        'data': [],
        'time_range': '',
        'is_after_close': False,
        'fetch_time': datetime.now().strftime('%H:%M:%S')
    }
    
    try:
        # 确定市场前缀
        if code.startswith('6') or code.startswith('9'):
            symbol = f"sh{code}"
        else:
            symbol = f"sz{code}"
        
        url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={symbol}"
        
        cmd = ['curl', '-s', '--connect-timeout', '10', url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        
        if result.returncode == 0 and result.stdout:
            data = json.loads(result.stdout)
            
            if data.get('code') == 0 and data.get('data', {}).get(symbol, {}).get('data', {}).get('data'):
                minute_data = data['data'][symbol]['data']['data']
                
                # 判断当前是否为收盘后
                now = datetime.now()
                current_time = now.hour * 100 + now.minute
                is_after_close = current_time >= 1500  # 15:00之后
                
                # 解析分时数据
                # 格式: "0930 11.03 5008 5523824.00"
                # 时间 价格 累计成交量 累计成交额
                parsed = []
                prev_volume = 0
                
                for item in minute_data:
                    parts = item.split(' ')
                    if len(parts) >= 4:
                        time_str = parts[0]
                        
                        # A股交易时间：9:30-11:30, 13:00-15:00
                        hour = int(time_str[:2])
                        minute = int(time_str[2:])
                        time_val = hour * 100 + minute
                        
                        # 只保留交易时间内的数据
                        is_trading_time = (930 <= time_val <= 1130) or (1300 <= time_val <= 1500)
                        
                        if not is_trading_time:
                            continue
                        
                        price = float(parts[1])
                        cum_volume = int(parts[2])  # 累计成交量（手）
                        
                        # 计算当前分钟的成交量（增量）
                        volume = cum_volume - prev_volume
                        prev_volume = cum_volume
                        
                        parsed.append({
                            'time': f"{time_str[:2]}:{time_str[2:]}",
                            'price': price,
                            'volume': volume,  # 单分钟成交量（手）
                            'cum_volume': cum_volume,
                            'time_val': time_val  # 用于筛选
                        })
                
                # 收盘后：返回尾盘数据（14:27-14:57，避开收盘集合竞价）
                if is_after_close:
                    # 筛选14:27-14:57的数据（共30分钟）
                    tail_data = [d for d in parsed if 1427 <= d['time_val'] <= 1457]
                    # 移除time_val字段
                    for d in tail_data:
                        del d['time_val']
                    
                    time_range = "14:27 ~ 14:57" if tail_data else ""
                    return {
                        'data': tail_data,
                        'time_range': time_range,
                        'is_after_close': True,
                        'fetch_time': now.strftime('%H:%M:%S')
                    }
                else:
                    # 交易时间内：返回最近N分钟
                    # 移除time_val字段
                    for d in parsed:
                        del d['time_val']
                    result_data = parsed[-minutes:] if len(parsed) > minutes else parsed
                    
                    if result_data:
                        time_range = f"{result_data[0]['time']} ~ {result_data[-1]['time']}"
                    else:
                        time_range = ""
                    
                    return {
                        'data': result_data,
                        'time_range': time_range,
                        'is_after_close': False,
                        'fetch_time': now.strftime('%H:%M:%S')
                    }
        
        return empty_result
    except Exception as e:
        print(f"获取分时数据失败 {code}: {e}")
        return empty_result


def check_negative_news(code: str, days: int = 3) -> Dict[str, Any]:
    """检查是否有利空消息"""
    news_list = get_stock_news(code, days)
    
    negative_news = []
    
    for news in news_list:
        title = news.get('title', '')
        is_negative = False
        matched_keywords = []
        
        for keyword in NEGATIVE_KEYWORDS:
            if keyword in title:
                is_negative = True
                matched_keywords.append(keyword)
        
        if is_negative:
            negative_news.append({
                'title': title,
                'date': news.get('date', ''),
                'source': news.get('source', ''),
                'keywords': matched_keywords
            })
    
    has_negative = len(negative_news) > 0
    
    return {
        'has_negative_news': has_negative,
        'negative_count': len(negative_news),
        'total_news_count': len(news_list),
        'negative_news': negative_news[:5],  # 最多返回5条
        'risk_level': 'high' if len(negative_news) >= 3 else ('medium' if len(negative_news) >= 1 else 'low')
    }


# ===================== AI精选增强功能 =====================

def get_market_environment() -> Dict[str, Any]:
    """获取大盘环境"""
    try:
        # 获取上证指数数据
        data = fetch_qq_stock_data(["sh000001"])
        for line in data.strip().split('\n'):
            match = re.match(r'v_(\w+)="(.*)";?', line.strip())
            if match:
                parts = match.group(2).split('~')
                if len(parts) > 35:
                    price = float(parts[3]) if parts[3] else 0
                    change_percent = float(parts[32]) if parts[32] else 0
                    
                    # 获取上证指数K线判断是否在5日线上
                    kline = fetch_qq_kline_data("000001", days=10)
                    above_ma5 = False
                    if kline:
                        try:
                            if 'data' in kline and 'sh000001' in kline['data']:
                                qfqday = kline['data']['sh000001'].get('qfqday', [])
                                if len(qfqday) >= 5:
                                    closes = [float(d[2]) for d in qfqday[-5:]]
                                    ma5 = sum(closes) / 5
                                    above_ma5 = price > ma5
                        except:
                            pass
                    
                    return {
                        'index_price': price,
                        'index_change': change_percent,
                        'above_ma5': above_ma5,
                        'market_sentiment': 'bullish' if change_percent > 0.5 else ('bearish' if change_percent < -0.5 else 'neutral'),
                        'safe_to_buy': change_percent > -1 and above_ma5
                    }
    except Exception as e:
        print(f"获取大盘环境失败: {e}")
    
    return {
        'index_price': 0,
        'index_change': 0,
        'above_ma5': False,
        'market_sentiment': 'unknown',
        'safe_to_buy': False
    }


def get_capital_flow(code: str) -> Dict[str, Any]:
    """获取资金流向（东方财富）"""
    try:
        if code.startswith('6'):
            secid = f"1.{code}"
        else:
            secid = f"0.{code}"
        
        url = f"https://push2.eastmoney.com/api/qt/stock/fflow/kline/get?secid={secid}&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56&klt=1&lmt=1"
        
        cmd = [
            'curl', '-s', '--connect-timeout', '10',
            '-H', 'User-Agent: Mozilla/5.0',
            '-H', 'Referer: https://quote.eastmoney.com/',
            url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        
        if result.returncode == 0 and result.stdout:
            data = json.loads(result.stdout)
            if data.get('data') and data['data'].get('klines'):
                # 解析最新的资金流向
                latest = data['data']['klines'][-1]
                parts = latest.split(',')
                if len(parts) >= 6:
                    main_inflow = float(parts[1]) / 100000000  # 转为亿
                    return {
                        'main_inflow': round(main_inflow, 2),
                        'is_inflow': main_inflow > 0,
                        'flow_strength': 'strong' if main_inflow > 0.5 else ('weak' if main_inflow > 0 else 'outflow')
                    }
    except Exception as e:
        print(f"获取资金流向失败 {code}: {e}")
    
    return {'main_inflow': 0, 'is_inflow': False, 'flow_strength': 'unknown'}


def calculate_rsi(closes: List[float], period: int = 14) -> float:
    """计算RSI指标"""
    if len(closes) < period + 1:
        return 50
    
    gains = []
    losses = []
    
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    if len(gains) < period:
        return 50
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return round(rsi, 2)


def calculate_macd(closes: List[float]) -> Dict[str, float]:
    """计算MACD指标"""
    if len(closes) < 26:
        return {'macd': 0, 'signal': 0, 'histogram': 0, 'golden_cross': False}
    
    # EMA计算
    def ema(data, period):
        multiplier = 2 / (period + 1)
        ema_values = [data[0]]
        for i in range(1, len(data)):
            ema_values.append((data[i] - ema_values[-1]) * multiplier + ema_values[-1])
        return ema_values
    
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    
    dif = [ema12[i] - ema26[i] for i in range(len(closes))]
    dea = ema(dif, 9)
    macd = [(dif[i] - dea[i]) * 2 for i in range(len(closes))]
    
    # 判断金叉
    golden_cross = False
    if len(dif) >= 2 and len(dea) >= 2:
        golden_cross = dif[-2] < dea[-2] and dif[-1] > dea[-1]
    
    return {
        'macd': round(macd[-1], 4) if macd else 0,
        'dif': round(dif[-1], 4) if dif else 0,
        'dea': round(dea[-1], 4) if dea else 0,
        'golden_cross': golden_cross
    }


def get_5day_change(kline_data: List[dict]) -> float:
    """计算近5日涨幅"""
    if len(kline_data) < 5:
        return 0
    
    price_5days_ago = kline_data[-5]['close']
    current_price = kline_data[-1]['close']
    
    if price_5days_ago > 0:
        return round((current_price - price_5days_ago) / price_5days_ago * 100, 2)
    return 0


def check_touched_limit(code: str, current_price: float, pre_close: float) -> bool:
    """检查今日是否触及涨停"""
    if pre_close <= 0:
        return False
    
    # ST股涨跌幅5%，其他10%（科创板/创业板20%）
    if code.startswith('688') or code.startswith('300') or code.startswith('301'):
        limit_rate = 0.20
    else:
        limit_rate = 0.10
    
    limit_price = pre_close * (1 + limit_rate)
    # 如果当前价格接近涨停价（差距小于0.5%），认为触及过涨停
    return current_price >= limit_price * 0.995


def analyze_tail_trend(minute_data: List[Dict]) -> Dict[str, Any]:
    """分析尾盘30分钟走势"""
    if len(minute_data) < 10:
        return {'trend': 'unknown', 'strength': 0, 'description': '数据不足'}
    
    # 取最后的数据
    recent = minute_data[-10:]  # 最后10分钟
    earlier = minute_data[:-10] if len(minute_data) > 10 else minute_data[:5]
    
    # 计算尾盘价格变化
    if len(recent) >= 2 and len(earlier) >= 1:
        tail_start_price = recent[0]['price']
        tail_end_price = recent[-1]['price']
        early_avg_price = sum(m['price'] for m in earlier) / len(earlier)
        
        tail_change = (tail_end_price - tail_start_price) / tail_start_price * 100 if tail_start_price > 0 else 0
        
        # 计算尾盘成交量占比
        tail_volume = sum(m['volume'] for m in recent)
        total_volume = sum(m['volume'] for m in minute_data)
        tail_volume_ratio = tail_volume / total_volume * 100 if total_volume > 0 else 0
        
        # 判断趋势
        if tail_change > 0.5 and tail_volume_ratio > 30:
            return {
                'trend': 'strong_up',
                'strength': min(100, int(tail_change * 20 + tail_volume_ratio)),
                'tail_change': round(tail_change, 2),
                'tail_volume_ratio': round(tail_volume_ratio, 1),
                'description': f'尾盘强势拉升{tail_change:.2f}%，成交量占比{tail_volume_ratio:.1f}%'
            }
        elif tail_change > 0.2:
            return {
                'trend': 'up',
                'strength': min(80, int(tail_change * 15 + tail_volume_ratio * 0.5)),
                'tail_change': round(tail_change, 2),
                'tail_volume_ratio': round(tail_volume_ratio, 1),
                'description': f'尾盘温和上涨{tail_change:.2f}%'
            }
        elif tail_change < -0.3:
            return {
                'trend': 'down',
                'strength': -min(80, int(abs(tail_change) * 15)),
                'tail_change': round(tail_change, 2),
                'tail_volume_ratio': round(tail_volume_ratio, 1),
                'description': f'尾盘回落{tail_change:.2f}%，需警惕'
            }
        else:
            return {
                'trend': 'stable',
                'strength': 30,
                'tail_change': round(tail_change, 2),
                'tail_volume_ratio': round(tail_volume_ratio, 1),
                'description': '尾盘走势平稳'
            }
    
    return {'trend': 'unknown', 'strength': 0, 'description': '数据异常'}


def calculate_upside_space(current_price: float, pre_close: float, code: str) -> Dict[str, Any]:
    """计算上涨空间（距离涨停）"""
    if pre_close <= 0:
        return {'space': 0, 'limit_price': 0, 'near_limit': False}
    
    # 判断涨跌幅限制
    if code.startswith('688') or code.startswith('300') or code.startswith('301'):
        limit_rate = 0.20  # 科创板/创业板 20%
    else:
        limit_rate = 0.10  # 主板 10%
    
    limit_price = round(pre_close * (1 + limit_rate), 2)
    current_change = (current_price - pre_close) / pre_close * 100
    remaining_space = limit_rate * 100 - current_change
    
    return {
        'space': round(remaining_space, 2),
        'limit_price': limit_price,
        'current_change': round(current_change, 2),
        'near_limit': remaining_space < 2,  # 距离涨停不足2%
        'limit_rate': limit_rate * 100
    }


def ai_select_stocks(screened_stocks: List[Dict], all_stocks_data: List[Dict]) -> List[Dict]:
    """AI精选算法 - T+1短线优化版
    
    策略：收盘前20分钟买入，第二天卖出
    重点关注：尾盘走势、资金抢筹、上涨空间、明日高开概率
    """
    
    # 获取大盘环境
    market_env = get_market_environment()
    
    candidates = []
    
    for stock in screened_stocks:
        code = stock['code']
        name = stock['name']
        
        reasons = []
        score = 0
        warnings = []
        
        current_price = stock['price']
        pre_close = stock.get('pre_close', 0)
        change_percent = stock['change_percent']
        turnover = stock.get('turnover', 0)
        volume_ratio = stock.get('volume_ratio', 1)
        
        # 1. 获取分时数据分析尾盘走势
        minute_result = get_minute_data(code, minutes=30)
        minute_data = minute_result.get('data', [])
        tail_trend = analyze_tail_trend(minute_data)
        
        # 2. 计算上涨空间
        upside = calculate_upside_space(current_price, pre_close, code)
        
        # 3. 获取资金流向
        capital_flow = get_capital_flow(code)
        
        # 4. 检查利空消息
        negative_info = check_negative_news(code, days=3)
        
        # ===== T+1短线评分逻辑 =====
        
        # 【核心】尾盘走势评分 (权重最高)
        if tail_trend['trend'] == 'strong_up':
            score += 30
            reasons.append(f"🚀 {tail_trend['description']}")
        elif tail_trend['trend'] == 'up':
            score += 20
            reasons.append(f"📈 {tail_trend['description']}")
        elif tail_trend['trend'] == 'stable':
            score += 10
            reasons.append(tail_trend['description'])
        elif tail_trend['trend'] == 'down':
            score -= 20
            warnings.append(f"📉 {tail_trend['description']}")
        
        # 【核心】上涨空间评分
        if upside['space'] >= 5:
            score += 25
            reasons.append(f"距涨停还有{upside['space']}%空间，明日上涨潜力大")
        elif upside['space'] >= 3:
            score += 15
            reasons.append(f"距涨停{upside['space']}%，仍有上涨空间")
        elif upside['near_limit']:
            score -= 15
            warnings.append(f"距涨停仅{upside['space']}%，追高风险大")
        
        # 【核心】资金流向评分
        if capital_flow['is_inflow']:
            if capital_flow['main_inflow'] > 1:
                score += 30
                reasons.append(f"💰 主力大幅净流入{capital_flow['main_inflow']}亿，资金抢筹明显")
            elif capital_flow['main_inflow'] > 0.3:
                score += 20
                reasons.append(f"主力净流入{capital_flow['main_inflow']}亿，资金看好")
            else:
                score += 10
                reasons.append(f"主力小幅净流入{capital_flow['main_inflow']}亿")
        else:
            if capital_flow['main_inflow'] < -0.5:
                score -= 25
                warnings.append(f"⚠️ 主力大幅净流出{abs(capital_flow['main_inflow'])}亿，可能出货")
            else:
                score -= 10
                warnings.append(f"主力净流出{abs(capital_flow['main_inflow'])}亿")
        
        # 换手率评分 (短线需要活跃但不能太高)
        if 5 <= turnover <= 12:
            score += 15
            reasons.append(f"换手率{turnover}%，交投活跃适中")
        elif 3 <= turnover < 5:
            score += 5
            reasons.append(f"换手率{turnover}%，交投尚可")
        elif turnover > 20:
            score -= 20
            warnings.append(f"换手率{turnover}%过高，可能主力出货")
        elif turnover > 15:
            score -= 10
            warnings.append(f"换手率{turnover}%偏高")
        
        # 量比评分
        if 1.5 <= volume_ratio <= 3:
            score += 10
            reasons.append(f"量比{volume_ratio:.1f}，温和放量")
        elif volume_ratio > 5:
            score -= 5
            warnings.append(f"量比{volume_ratio:.1f}过大，可能异常波动")
        
        # 当日涨幅评分 (T+1短线，涨幅3-5%是较好位置)
        if 3 <= change_percent <= 5:
            score += 15
            reasons.append(f"当日涨幅{change_percent}%，处于拉升初期")
        elif 5 < change_percent <= 7:
            score += 5
            reasons.append(f"当日涨幅{change_percent}%，涨幅适中")
        elif change_percent > 8:
            score -= 10
            warnings.append(f"当日涨幅{change_percent}%，追高风险增加")
        
        # 利空消息评分
        if not negative_info['has_negative_news']:
            score += 10
            reasons.append("无近期利空消息")
        else:
            score -= negative_info['negative_count'] * 15
            warnings.append(f"⚠️ 发现{negative_info['negative_count']}条利空消息，明日可能低开")
        
        # 大盘环境
        if market_env['market_sentiment'] == 'bullish':
            score += 10
            reasons.append("大盘强势，有利于个股表现")
        elif market_env['index_change'] < -1:
            score -= 15
            warnings.append("大盘下跌，明日系统性风险")
        
        # 明日高开概率预判
        open_probability = 'high' if score >= 60 else ('medium' if score >= 40 else 'low')
        
        candidates.append({
            'code': code,
            'name': name,
            'price': current_price,
            'change_percent': change_percent,
            'volume_ratio': volume_ratio,
            'market_cap': stock['market_cap'],
            'turnover': turnover,
            'score': score,
            'reasons': reasons,
            'warnings': warnings,
            'indicators': {
                'tail_trend': tail_trend,
                'upside_space': upside,
                'capital_flow': capital_flow,
                'open_probability': open_probability
            },
            'negative_news': negative_info,
            'minute_volume': minute_result,
            'board_type': get_board_type(code)
        })
    
    # 按评分排序，取前3只
    candidates.sort(key=lambda x: x['score'], reverse=True)
    
    # 过滤掉评分过低的（短线要求更严格）
    qualified = [c for c in candidates if c['score'] >= 40]
    
    return qualified[:6]


def get_board_type(code: str) -> Dict[str, Any]:
    """获取股票所属板块类型"""
    # 提取纯数字代码
    pure_code = code.replace('sh', '').replace('sz', '')
    
    if pure_code.startswith('688'):
        return {
            'type': 'kcb',
            'name': '科创板',
            'color': '#00b894',
            'risk_note': '20%涨跌幅限制'
        }
    elif pure_code.startswith('300') or pure_code.startswith('301'):
        return {
            'type': 'cyb',
            'name': '创业板',
            'color': '#6c5ce7',
            'risk_note': '20%涨跌幅限制'
        }
    elif pure_code.startswith('60'):
        return {
            'type': 'sh',
            'name': '沪市主板',
            'color': '#0984e3',
            'risk_note': '10%涨跌幅限制'
        }
    elif pure_code.startswith('00'):
        return {
            'type': 'sz',
            'name': '深市主板',
            'color': '#00cec9',
            'risk_note': '10%涨跌幅限制'
        }
    else:
        return {
            'type': 'other',
            'name': '其他',
            'color': '#636e72',
            'risk_note': ''
        }


def is_digital_economy_stock(code: str, name: str = "") -> bool:
    """判断是否属于数字经济板块"""
    # 科创板(688)和创业板(300)中的科技股更可能属于数字经济
    if code.startswith('688'):
        return True
    
    # 通过名称关键词匹配
    for keyword in DIGITAL_KEYWORDS:
        if keyword in name:
            return True
    
    return False


def check_volume_pattern(kline_data: List[dict]) -> bool:
    """检查是否阶梯式放量"""
    if len(kline_data) < 5:
        return False
    
    volumes = [d["volume"] for d in kline_data[-5:]]
    avg_volume = sum(volumes) / len(volumes)
    
    # 检查最近3天是否呈现放量趋势
    recent_3 = volumes[-3:]
    increasing_count = 0
    for i in range(1, len(recent_3)):
        if recent_3[i] > recent_3[i-1] * 0.9:
            increasing_count += 1
    
    latest_volume_ratio = volumes[-1] / avg_volume if avg_volume > 0 else 0
    
    return increasing_count >= 1 and latest_volume_ratio > 1.2


def check_above_ma5_and_high(kline_data: List[dict], current_price: float) -> bool:
    """检查是否站稳5日线+近期高点"""
    if len(kline_data) < 10:
        return False
    
    closes = [d["close"] for d in kline_data[-10:]]
    ma5 = sum(closes[-5:]) / 5
    
    highs = [d["high"] for d in kline_data[-10:]]
    recent_high = max(highs[:-1]) if len(highs) > 1 else highs[0]
    
    above_ma5 = current_price > ma5 * 0.98
    near_high = current_price >= recent_high * 0.97
    
    return above_ma5 and near_high


def calculate_support_level(kline_data: List[dict]) -> float:
    """计算支撑位"""
    if len(kline_data) < 5:
        return 0
    lows = [d["low"] for d in kline_data[-5:]]
    return min(lows)


@app.get("/")
async def root():
    return {
        "message": "A股行情API服务",
        "version": "2.3.0",
        "data_source": "腾讯股票 (qt.gtimg.cn)",
        "endpoints": [
            "/api/screen - 筛选股票",
            "/api/filter - 过滤精选股票",
            "/api/realtime - 获取实时行情",
            "/api/kline - 获取K线数据",
        ]
    }


@app.get("/api/screen")
async def screen_stocks(
    change_min: float = Query(3.0, description="涨幅下限(%)"),
    change_max: float = Query(5.0, description="涨幅上限(%)"),
    volume_ratio_min: float = Query(1.5, description="量比下限"),
    volume_ratio_max: float = Query(3.0, description="量比上限"),
    market_cap_min: float = Query(50, description="流通市值下限(亿)"),
    market_cap_max: float = Query(300, description="流通市值上限(亿)"),
    limit: int = Query(30, description="返回数量")
):
    """筛选股票"""
    try:
        print(f"开始筛选股票: 涨幅{change_min}%-{change_max}%, 量比{volume_ratio_min}-{volume_ratio_max}, 市值{market_cap_min}-{market_cap_max}亿")
        
        # 获取所有股票数据
        all_stocks = get_all_stocks_data()
        print(f"获取到 {len(all_stocks)} 只股票数据")
        
        # 筛选
        filtered = []
        for stock in all_stocks:
            # 排除ST股票
            if 'ST' in stock['name'] or 'st' in stock['name']:
                continue
            
            # 涨幅筛选
            if not (change_min <= stock['change_percent'] <= change_max):
                continue
            
            # 量比筛选
            if not (volume_ratio_min <= stock['volume_ratio'] <= volume_ratio_max):
                continue
            
            # 流通市值筛选（亿）
            if not (market_cap_min <= stock['market_cap'] <= market_cap_max):
                continue
            
            filtered.append(stock)
        
        # 按涨幅排序
        filtered.sort(key=lambda x: x['change_percent'], reverse=True)
        filtered = filtered[:limit]
        
        print(f"筛选后剩余 {len(filtered)} 只股票")
        
        result = []
        for stock in filtered:
            result.append({
                "code": stock['code'],
                "name": stock['name'],
                "price": stock['price'],
                "change": stock['change'],
                "change_percent": stock['change_percent'],
                "volume_ratio": stock['volume_ratio'],
                "turnover": stock['turnover'],
                "market_cap": stock['market_cap'],
                "amount": stock['amount'] * 10000,  # 转为元
                "volume": stock['volume'] * 100,  # 转为股
            })
        
        return {
            "count": len(result),
            "criteria": {
                "change_range": f"{change_min}%-{change_max}%",
                "volume_ratio_range": f"{volume_ratio_min}-{volume_ratio_max}",
                "market_cap_range": f"{market_cap_min}-{market_cap_max}亿"
            },
            "data": result
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"筛选股票失败: {str(e)}")


@app.get("/api/filter")
async def filter_stocks(codes: str = Query(..., description="股票代码列表，用逗号分隔")):
    """过滤精选股票"""
    try:
        code_list = [c.strip() for c in codes.split(",") if c.strip()]
        
        if not code_list:
            raise HTTPException(status_code=400, detail="请提供股票代码列表")
        
        # 格式化代码
        formatted_codes = []
        for code in code_list:
            if code.startswith('6') or code.startswith('9'):
                formatted_codes.append(f"sh{code}")
            else:
                formatted_codes.append(f"sz{code}")
        
        # 获取实时数据
        data = fetch_qq_stock_data(formatted_codes)
        stocks_map = {}
        for line in data.strip().split('\n'):
            if line:
                stock = parse_qq_stock_line(line)
                if stock:
                    stocks_map[stock['code']] = stock
        
        qualified_stocks = []
        analysis_results = []
        
        for code in code_list:
            if code not in stocks_map:
                continue
            
            stock = stocks_map[code]
            stock_name = stock['name']
            current_price = stock['price']
            
            # 获取K线数据
            kline_response = fetch_qq_kline_data(code)
            kline_data = []
            
            try:
                # 解析腾讯K线数据
                if code.startswith('6') or code.startswith('9'):
                    symbol = f"sh{code}"
                else:
                    symbol = f"sz{code}"
                
                if 'data' in kline_response and symbol in kline_response['data']:
                    qfqday = kline_response['data'][symbol].get('qfqday', [])
                    for day in qfqday[-20:]:
                        if len(day) >= 6:
                            kline_data.append({
                                "date": day[0],
                                "open": float(day[1]),
                                "close": float(day[2]),
                                "high": float(day[3]),
                                "low": float(day[4]),
                                "volume": float(day[5]),
                            })
            except Exception as e:
                print(f"解析K线数据失败: {e}")
            
            if len(kline_data) < 10:
                continue
            
            # 检查条件
            has_volume_pattern = check_volume_pattern(kline_data)
            above_ma5_high = check_above_ma5_and_high(kline_data, current_price)
            is_digital = is_digital_economy_stock(code, stock_name)
            support_level = calculate_support_level(kline_data)
            
            closes = [d["close"] for d in kline_data[-5:]]
            ma5 = sum(closes) / 5 if closes else 0
            
            analysis = {
                "code": code,
                "name": stock_name,
                "price": current_price,
                "change_percent": stock['change_percent'],
                "volume_ratio": stock['volume_ratio'],
                "market_cap": stock['market_cap'],
                "ma5": round(ma5, 2),
                "support_level": round(support_level, 2),
                "has_volume_pattern": has_volume_pattern,
                "above_ma5_high": above_ma5_high,
                "is_digital_economy": is_digital,
                "qualified": has_volume_pattern and above_ma5_high and is_digital
            }
            
            analysis_results.append(analysis)
            
            if has_volume_pattern and above_ma5_high and is_digital:
                # 检查利空消息
                negative_info = check_negative_news(code, days=3)
                # 获取最近30分钟成交量数据
                minute_result = get_minute_data(code, minutes=30)
                
                qualified_stocks.append({
                    "code": code,
                    "name": stock_name,
                    "price": current_price,
                    "change_percent": stock['change_percent'],
                    "volume_ratio": stock['volume_ratio'],
                    "market_cap": round(stock['market_cap'], 2),
                    "turnover": stock['turnover'],
                    "amount": stock['amount'] * 10000,
                    "ma5": round(ma5, 2),
                    "support_level": round(support_level, 2),
                    "analysis": {
                        "volume_pattern": "阶梯式放量 ✓",
                        "price_position": "站稳5日线+近期高点 ✓",
                        "sector": "数字经济板块 ✓"
                    },
                    "negative_news": negative_info,
                    "minute_volume": minute_result,
                    "board_type": get_board_type(code)
                })
        
        # 如果不足6只，降低条件
        if len(qualified_stocks) < 6:
            for analysis in sorted(analysis_results, 
                                   key=lambda x: sum([x["has_volume_pattern"], 
                                                      x["above_ma5_high"], 
                                                      x["is_digital_economy"]]), 
                                   reverse=True):
                if analysis["code"] not in [s["code"] for s in qualified_stocks]:
                    score = sum([analysis["has_volume_pattern"], 
                                 analysis["above_ma5_high"], 
                                 analysis["is_digital_economy"]])
                    if score >= 2:
                        # 检查利空消息
                        negative_info = check_negative_news(analysis["code"], days=3)
                        # 获取最近30分钟成交量数据
                        minute_result = get_minute_data(analysis["code"], minutes=30)
                        
                        qualified_stocks.append({
                            "code": analysis["code"],
                            "name": analysis["name"],
                            "price": analysis["price"],
                            "change_percent": analysis["change_percent"],
                            "volume_ratio": analysis["volume_ratio"],
                            "market_cap": round(analysis["market_cap"], 2),
                            "ma5": analysis["ma5"],
                            "support_level": analysis["support_level"],
                            "analysis": {
                                "volume_pattern": "阶梯式放量 ✓" if analysis["has_volume_pattern"] else "放量不明显",
                                "price_position": "站稳5日线+近期高点 ✓" if analysis["above_ma5_high"] else "未站稳",
                                "sector": "数字经济板块 ✓" if analysis["is_digital_economy"] else "非数字经济"
                            },
                            "negative_news": negative_info,
                            "minute_volume": minute_result,
                            "board_type": get_board_type(analysis["code"])
                        })
                        
                if len(qualified_stocks) >= 6:
                    break
        
        # AI精选：从所有筛选出的股票中进行智能分析
        print("开始AI精选分析...")
        screened_for_ai = []
        for code in code_list:
            if code in stocks_map:
                stock = stocks_map[code]
                screened_for_ai.append({
                    'code': code,
                    'name': stock['name'],
                    'price': stock['price'],
                    'pre_close': stock.get('pre_close', 0),
                    'change_percent': stock['change_percent'],
                    'volume_ratio': stock['volume_ratio'],
                    'market_cap': stock['market_cap'],
                    'turnover': stock.get('turnover', 0),
                })
        
        ai_selected = ai_select_stocks(screened_for_ai, [])
        print(f"AI精选完成，选出 {len(ai_selected)} 只股票")
        
        # 获取大盘环境
        market_env = get_market_environment()
        
        return {
            "count": len(qualified_stocks[:6]),
            "total_analyzed": len(code_list),
            "filter_criteria": {
                "volume_pattern": "阶梯式放量",
                "price_position": "站稳5日线+近期高点",
                "sector": "数字经济板块"
            },
            "data": qualified_stocks[:6],
            "all_analysis": analysis_results,
            "ai_selected": ai_selected,
            "market_environment": market_env
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"过滤股票失败: {str(e)}")


@app.get("/api/realtime")
async def get_realtime_quote(code: str = Query(..., description="股票代码")):
    """获取单只股票实时行情"""
    try:
        if code.startswith('6') or code.startswith('9'):
            formatted = f"sh{code}"
        else:
            formatted = f"sz{code}"
        
        data = fetch_qq_stock_data([formatted])
        for line in data.strip().split('\n'):
            if line:
                stock = parse_qq_stock_line(line)
                if stock:
                    return stock
        
        raise HTTPException(status_code=404, detail=f"未找到股票: {code}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取数据失败: {str(e)}")


@app.get("/api/kline")
async def get_kline_data(
    code: str = Query(..., description="股票代码"),
    period: str = Query("daily", description="周期"),
    days: int = Query(90, description="获取天数")
):
    """获取K线历史数据"""
    try:
        kline_response = fetch_qq_kline_data(code, days)
        
        if code.startswith('6') or code.startswith('9'):
            symbol = f"sh{code}"
        else:
            symbol = f"sz{code}"
        
        if 'data' not in kline_response or symbol not in kline_response['data']:
            raise HTTPException(status_code=404, detail=f"未找到股票K线数据: {code}")
        
        qfqday = kline_response['data'][symbol].get('qfqday', [])
        
        result = []
        for day in qfqday:
            if len(day) >= 6:
                result.append({
                    "date": day[0],
                    "open": float(day[1]),
                    "close": float(day[2]),
                    "high": float(day[3]),
                    "low": float(day[4]),
                    "volume": float(day[5]),
                })
        
        return {"code": code, "period": period, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取K线数据失败: {str(e)}")


@app.get("/api/hot")
async def get_hot_stocks(limit: int = Query(20, description="返回数量")):
    """获取热门股票（按成交额排序）"""
    try:
        all_stocks = get_all_stocks_data()
        
        # 按成交额排序
        all_stocks.sort(key=lambda x: x['amount'], reverse=True)
        top_stocks = all_stocks[:limit]
        
        result = []
        for stock in top_stocks:
            result.append({
                "code": stock['code'],
                "name": stock['name'],
                "price": stock['price'],
                "change_percent": stock['change_percent'],
                "amount": stock['amount'] * 10000,
                "turnover": stock['turnover'],
            })
        
        return {"count": len(result), "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取热门股票失败: {str(e)}")


@app.get("/api/index")
async def get_index_data():
    """获取主要指数行情"""
    try:
        indices = ["sh000001", "sz399001", "sz399006", "sh000300", "sh000905"]
        data = fetch_qq_stock_data(indices)
        
        result = []
        for line in data.strip().split('\n'):
            if line:
                # 指数数据解析略有不同
                match = re.match(r'v_(\w+)="(.*)";?', line.strip())
                if match:
                    parts = match.group(2).split('~')
                    if len(parts) > 5:
                        result.append({
                            "code": parts[2] if len(parts) > 2 else "",
                            "name": parts[1] if len(parts) > 1 else "",
                            "price": float(parts[3]) if len(parts) > 3 and parts[3] else 0,
                            "change": float(parts[31]) if len(parts) > 31 and parts[31] else 0,
                            "change_percent": float(parts[32]) if len(parts) > 32 and parts[32] else 0,
                        })
        
        return {"data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取指数数据失败: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
