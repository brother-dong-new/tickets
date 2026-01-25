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


# 是否启用东方财富新闻搜索接口
# 说明：原来的 searchapi.eastmoney.com 接口当前返回 404，
# 如果继续调用不仅拿不到新闻，还会造成额外的无效请求。
# 因此这里增加一个开关，默认关闭新闻搜索，仅使用“公司公告”做利空检测。
ENABLE_EASTMONEY_NEWS_SEARCH = False


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
            # 防御：确保返回是字典且包含预期字段
            if isinstance(data, dict) and data.get('success') and isinstance(data.get('data'), dict) and data['data'].get('list'):
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
    
    # 可选：东方财富新闻搜索（当前默认关闭，因为接口已返回 404）
    if ENABLE_EASTMONEY_NEWS_SEARCH:
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
                # 防御：确保 result 为字典且内部结构正确，避免 data 为 int 等异常情况
                if isinstance(data, dict) and isinstance(data.get('result'), dict) and data['result'].get('data'):
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
    """检查是否有利空消息（只看公告 + 技术风险）

    - 公告：使用东方财富公告接口，结合 NEGATIVE_KEYWORDS 识别业绩/处罚/减持等利空。
    - 技术风险：基于最近数日 K 线，检测大跌、连续下跌、放量长阴等技术面风险。
    - 不再依赖任何新闻搜索接口（例如 searchapi.eastmoney.com）。
    """
    # 1）公告利空（文本层面）
    news_list = get_stock_news(code, days)
    negative_news: List[Dict[str, Any]] = []
    
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

    # 2）技术面风险（K线）
    technical_risks: List[Dict[str, Any]] = []
    try:
        kline = fetch_qq_kline_data(code, days=15)
        # 确定 symbol
        if code.startswith('6') or code.startswith('9'):
            symbol = f"sh{code}"
        else:
            symbol = f"sz{code}"
        
        if isinstance(kline, dict) and 'data' in kline and symbol in kline['data']:
            qfqday = kline['data'][symbol].get('qfqday', []) or []
            kline_data = []
            for d in qfqday[-10:]:  # 只看最近10日
                if len(d) >= 6:
                    try:
                        kline_data.append({
                            'date': d[0],
                            'open': float(d[1]),
                            'close': float(d[2]),
                            'high': float(d[3]),
                            'low': float(d[4]),
                            'volume': float(d[5]),
                        })
                    except Exception:
                        continue
            
            if len(kline_data) >= 3:
                today = kline_data[-1]
                yesterday = kline_data[-2]
                # 今日单日大跌
                if yesterday['close'] > 0:
                    change_today = (today['close'] - yesterday['close']) / yesterday['close'] * 100
                    if change_today <= -7:
                        technical_risks.append({
                            'title': f"[技术风险] 今日大跌{change_today:.2f}%",
                            'date': today['date'],
                            'source': '技术面',
                            'keywords': ['大跌', '技术风险']
                        })
                
                # 近3日累计大跌
                if len(kline_data) >= 4:
                    base_close = kline_data[-4]['close']
                    if base_close > 0:
                        change_3d = (today['close'] - base_close) / base_close * 100
                        if change_3d <= -12:
                            technical_risks.append({
                                'title': f"[技术风险] 近3日累计下跌{change_3d:.2f}%",
                                'date': today['date'],
                                'source': '技术面',
                                'keywords': ['连续下跌', '技术风险']
                            })
                
                # 放量长阴（放量下跌）
                hist = kline_data[:-1]
                if hist:
                    avg_vol = sum(d['volume'] for d in hist[-5:]) / min(5, len(hist))
                    if (
                        today['close'] < today['open'] and  # 阴线
                        avg_vol > 0 and
                        today['volume'] >= avg_vol * 2.5
                    ):
                        technical_risks.append({
                            'title': "[技术风险] 放量长阴，可能有资金出逃",
                            'date': today['date'],
                            'source': '技术面',
                            'keywords': ['放量下跌', '技术风险']
                        })
    except Exception as e:
        print(f"技术风险检测失败 {code}: {e}")

    # 将技术风险也并入 negative_news，统一计数和展示
    negative_news.extend(technical_risks)
    
    has_negative = len(negative_news) > 0
    total_negative = len(negative_news)
    
    if total_negative >= 3:
        risk_level = 'high'
    elif total_negative >= 1:
        risk_level = 'medium'
    else:
        risk_level = 'low'
    
    return {
        'has_negative_news': has_negative,
        'negative_count': total_negative,
        'total_news_count': len(news_list),
        'negative_news': negative_news[:5],  # 最多返回5条（包含公告+技术面）
        'risk_level': risk_level
    }


# ===================== AI精选增强功能 =====================

def get_market_environment(stock_code: str = None) -> Dict[str, Any]:
    """获取大盘环境（增强版：增加5日趋势判断）
    
    参数:
        stock_code: 股票代码，用于动态选择参考指数
                    - 688xxx → 参考科创50 (000688)
                    - 300xxx/301xxx → 参考创业板指 (399006)
                    - 其他 → 参考上证指数 (000001)
    """
    try:
        # 根据股票代码选择参考指数
        if stock_code:
            pure_code = stock_code.replace('sh', '').replace('sz', '')
            if pure_code.startswith('688'):
                index_code = 'sh000688'  # 科创50
                index_name = '科创50'
            elif pure_code.startswith('300') or pure_code.startswith('301'):
                index_code = 'sz399006'  # 创业板指
                index_name = '创业板指'
            else:
                index_code = 'sh000001'  # 上证指数
                index_name = '上证指数'
        else:
            index_code = 'sh000001'
            index_name = '上证指数'
        
        # 获取指数数据
        data = fetch_qq_stock_data([index_code])
        for line in data.strip().split('\n'):
            match = re.match(r'v_(\w+)="(.*)";?', line.strip())
            if match:
                parts = match.group(2).split('~')
                if len(parts) > 35:
                    price = float(parts[3]) if parts[3] else 0
                    change_percent = float(parts[32]) if parts[32] else 0
                    
                    # 获取指数K线判断是否在5日线上，以及近5日趋势
                    kline_code = index_code.replace('sh', '').replace('sz', '')
                    kline = fetch_qq_kline_data(kline_code, days=10)
                    above_ma5 = False
                    trend_5d = 'neutral'  # 新增：5日趋势
                    change_5d = 0  # 新增：5日涨跌幅
                    
                    if kline:
                        try:
                            if 'data' in kline and index_code in kline['data']:
                                qfqday = kline['data'][index_code].get('qfqday', [])
                                if len(qfqday) >= 5:
                                    closes = [float(d[2]) for d in qfqday[-5:]]
                                    ma5 = sum(closes) / 5
                                    above_ma5 = price > ma5
                                    
                                    # 计算5日涨跌幅
                                    if closes[-5] > 0:
                                        change_5d = (closes[-1] - closes[-5]) / closes[-5] * 100
                                        if change_5d > 2:
                                            trend_5d = 'strong_bullish'
                                        elif change_5d > 0.5:
                                            trend_5d = 'bullish'
                                        elif change_5d < -2:
                                            trend_5d = 'strong_bearish'
                                        elif change_5d < -0.5:
                                            trend_5d = 'bearish'
                        except:
                            pass
                    
                    return {
                        'index_code': index_code,
                        'index_name': index_name,
                        'index_price': price,
                        'index_change': change_percent,
                        'above_ma5': above_ma5,
                        'trend_5d': trend_5d,  # 新增
                        'change_5d': round(change_5d, 2),  # 新增
                        'market_sentiment': 'bullish' if change_percent > 0.5 else ('bearish' if change_percent < -0.5 else 'neutral'),
                        'safe_to_buy': change_percent > -1 and above_ma5 and trend_5d not in ['strong_bearish', 'bearish']
                    }
    except Exception as e:
        print(f"获取大盘环境失败: {e}")
    
    return {
        'index_code': 'sh000001',
        'index_name': '上证指数',
        'index_price': 0,
        'index_change': 0,
        'above_ma5': False,
        'trend_5d': 'unknown',
        'change_5d': 0,
        'market_sentiment': 'unknown',
        'safe_to_buy': False
    }


def get_capital_flow(code: str) -> Dict[str, Any]:
    """使用腾讯分时数据估算尾盘30分钟资金净流入（优化版）

    优化策略：
    1. 使用前后成交额变化率判断资金流向（而非单纯成交额大小）
    2. 结合价格涨跌判断主买主卖
    3. 综合计算得出净流入估算值
    
    返回值：
    - main_inflow: 尾盘30分钟净流入估算值，单位：亿（正数=流入，负数=流出）
    - is_inflow: 是否净流入
    - flow_strength: strong_in(强力流入) / weak_in(弱流入) / weak_out(弱流出) / strong_out(强流出)
    - has_data: 是否成功获取数据
    """
    try:
        minute_result = get_minute_data(code, minutes=30)
        data = minute_result.get('data', [])
        if len(data) < 10:
            return {
                'main_inflow': 0,
                'is_inflow': False,
                'flow_strength': 'unknown',
                'has_data': False,
            }

        # 分段计算：前15分钟 vs 后15分钟
        mid_point = len(data) // 2
        early_data = data[:mid_point]
        late_data = data[mid_point:]
        
        def calc_vwap_and_amount(segment):
            """计算段内加权平均价和成交额"""
            total_amount = 0
            total_volume = 0
            for item in segment:
                try:
                    price = float(item.get('price', 0) or 0)
                    vol_hand = float(item.get('volume', 0) or 0)
                    amount = price * vol_hand * 100
                    total_amount += amount
                    total_volume += vol_hand
                except:
                    continue
            vwap = total_amount / (total_volume * 100) if total_volume > 0 else 0
            return vwap, total_amount / 1e8  # 转为亿
        
        early_vwap, early_amount = calc_vwap_and_amount(early_data)
        late_vwap, late_amount = calc_vwap_and_amount(late_data)
        
        # 计算价格动能：后半段均价 vs 前半段均价
        price_momentum = (late_vwap - early_vwap) / early_vwap * 100 if early_vwap > 0 else 0
        
        # 计算成交额动能：后半段成交额 vs 前半段成交额
        amount_momentum = (late_amount - early_amount) / early_amount * 100 if early_amount > 0 else 0
        
        # 综合判断净流入：
        # 1. 价格上涨+成交额增加 → 强买入（主力流入）
        # 2. 价格下跌+成交额增加 → 主力流出
        # 3. 价格上涨+成交额减少 → 弱买入（散户追涨）
        # 4. 价格下跌+成交额减少 → 弱卖出
        
        total_amount = early_amount + late_amount
        
        if price_momentum > 0.5:  # 价格明显上涨
            if amount_momentum > 20:  # 成交额显著放大
                # 强力流入：放量上涨
                net_flow = total_amount * 0.7  # 假设70%为净流入
                flow_strength = 'strong_in'
            elif amount_momentum > 0:
                # 弱流入：温和放量上涨
                net_flow = total_amount * 0.4
                flow_strength = 'weak_in'
            else:
                # 缩量上涨：谨慎看待
                net_flow = total_amount * 0.2
                flow_strength = 'weak_in'
        elif price_momentum < -0.5:  # 价格明显下跌
            if amount_momentum > 20:  # 成交额显著放大
                # 强力流出：放量下跌（砸盘）
                net_flow = -total_amount * 0.7
                flow_strength = 'strong_out'
            elif amount_momentum > 0:
                # 弱流出：温和放量下跌
                net_flow = -total_amount * 0.4
                flow_strength = 'weak_out'
            else:
                # 缩量下跌：自然回落
                net_flow = -total_amount * 0.2
                flow_strength = 'weak_out'
        else:  # 价格横盘
            if amount_momentum > 30:
                # 横盘放量：可能是换手，略偏流入
                net_flow = total_amount * 0.2
                flow_strength = 'weak_in'
            else:
                # 横盘缩量：观望
                net_flow = 0
                flow_strength = 'neutral'
        
        main_inflow = round(net_flow, 2)
        is_inflow = main_inflow >= 0.3

        return {
            'main_inflow': main_inflow,
            'is_inflow': is_inflow,
            'flow_strength': flow_strength,
            'has_data': True,
            'price_momentum': round(price_momentum, 2),
            'amount_momentum': round(amount_momentum, 1),
        }
    except Exception as e:
        print(f"尾盘资金流估算失败 {code}: {e}")
        return {
            'main_inflow': 0,
            'is_inflow': False,
            'flow_strength': 'unknown',
            'has_data': False,
        }


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


def check_touched_limit(code: str, current_price: float, pre_close: float) -> Dict[str, Any]:
    """检查今日是否触及涨停（增强版：检测涨停打开）
    
    返回:
        touched: 是否触及过涨停
        opened: 触及涨停后是否打开（高风险信号）
        current_at_limit: 当前是否在涨停价
    """
    if pre_close <= 0:
        return {'touched': False, 'opened': False, 'current_at_limit': False}
    
    # ST股涨跌幅5%，其他10%（科创板/创业板20%）
    if code.startswith('688') or code.startswith('300') or code.startswith('301'):
        limit_rate = 0.20
    else:
        limit_rate = 0.10
    
    limit_price = pre_close * (1 + limit_rate)
    current_at_limit = current_price >= limit_price * 0.995
    
    # 尝试从分时数据判断是否触及过涨停
    touched = False
    opened = False
    
    try:
        minute_result = get_minute_data(code, minutes=240)
        minute_data = minute_result.get('data', [])
        
        if minute_data:
            max_price = max(m['price'] for m in minute_data if m['price'] > 0)
            touched = max_price >= limit_price * 0.995
            
            # 如果触及过涨停，但当前价格低于涨停价1%以上，说明打开了
            if touched and current_price < limit_price * 0.99:
                opened = True
    except:
        # 如果获取分时数据失败，只能根据当前价格简单判断
        touched = current_at_limit
    
    return {
        'touched': touched,
        'opened': opened,
        'current_at_limit': current_at_limit
    }


def analyze_tail_trend(minute_data: List[Dict]) -> Dict[str, Any]:
    """分析尾盘30分钟走势（优化版：成交量加权）"""
    if len(minute_data) < 10:
        return {'trend': 'unknown', 'strength': 0, 'description': '数据不足'}
    
    # 取最后10分钟作为尾盘，前面的作为早盘参考
    recent = minute_data[-10:]  # 最后10分钟
    earlier = minute_data[:-10] if len(minute_data) > 10 else minute_data[:5]
    
    # 计算尾盘价格变化（改用成交量加权平均价，避免单点波动误判）
    if len(recent) >= 2 and len(earlier) >= 1:
        # 尾盘加权平均价（成交量加权）
        tail_total_amount = sum(m['price'] * m['volume'] for m in recent)
        tail_total_volume = sum(m['volume'] for m in recent)
        tail_vwap = tail_total_amount / tail_total_volume if tail_total_volume > 0 else 0
        
        # 早盘加权平均价
        early_total_amount = sum(m['price'] * m['volume'] for m in earlier)
        early_total_volume = sum(m['volume'] for m in earlier)
        early_vwap = early_total_amount / early_total_volume if early_total_volume > 0 else 0
        
        # 计算尾盘相对早盘的价格变化
        tail_change = (tail_vwap - early_vwap) / early_vwap * 100 if early_vwap > 0 else 0
        
        # 计算尾盘成交量占比
        tail_volume = sum(m['volume'] for m in recent)
        total_volume = sum(m['volume'] for m in minute_data)
        tail_volume_ratio = tail_volume / total_volume * 100 if total_volume > 0 else 0
        
        # 判断趋势（阈值保持不变，但判断更准确）
        if tail_change > 0.5 and tail_volume_ratio > 30:
            return {
                'trend': 'strong_up',
                'strength': min(100, int(tail_change * 20 + tail_volume_ratio)),
                'tail_change': round(tail_change, 2),
                'tail_volume_ratio': round(tail_volume_ratio, 1),
                'description': f'尾盘强势拉升{tail_change:.2f}%（成交量加权），占比{tail_volume_ratio:.1f}%'
            }
        elif tail_change > 0.2:
            return {
                'trend': 'up',
                'strength': min(80, int(tail_change * 15 + tail_volume_ratio * 0.5)),
                'tail_change': round(tail_change, 2),
                'tail_volume_ratio': round(tail_volume_ratio, 1),
                'description': f'尾盘温和上涨{tail_change:.2f}%（成交量加权）'
            }
        elif tail_change < -0.3:
            return {
                'trend': 'down',
                'strength': -min(80, int(abs(tail_change) * 15)),
                'tail_change': round(tail_change, 2),
                'tail_volume_ratio': round(tail_volume_ratio, 1),
                'description': f'尾盘回落{tail_change:.2f}%（成交量加权），需警惕'
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


AI_MIN_SCORE_BASE = 40   # 正常行情下入选最低分
AI_MIN_SCORE_BEAR = 50   # 大盘极弱时抬高门槛
AI_MAX_PICKS = 6         # 最多返回只数


def calculate_next_day_expectation(
    current_score: float,
    tail_trend: Dict[str, Any],
    upside_space: Dict[str, Any],
    capital_flow: Dict[str, Any],
    change_percent: float,
    turnover: float,
    market_env: Dict[str, Any],
) -> Dict[str, Any]:
    """评估明日收盘预期涨幅和风险（T+1策略核心）
    
    返回:
        expected_return: 预期收盘涨幅（%）
        confidence: 信心度 (0-100)
        risk_factors: 高开低走风险因素列表
    """
    # 基础预期（根据综合评分映射）
    if current_score >= 70:
        base_return = 3.0
    elif current_score >= 60:
        base_return = 2.5
    elif current_score >= 50:
        base_return = 2.0
    elif current_score >= 40:
        base_return = 1.5
    else:
        base_return = 1.0
    
    confidence = 60  # 基础信心度
    risk_factors = []
    
    # 【风险因子1】当日涨幅过大 + 尾盘不强 → 高开低走风险
    if change_percent > 7:
        if tail_trend.get('trend') not in ['strong_up', 'up']:
            base_return -= 1.5
            confidence -= 15
            risk_factors.append('当日涨幅较大但尾盘走弱，次日易高开低走')
        elif tail_trend.get('trend') == 'up':  # 尾盘温和，风险略低
            base_return -= 0.5
            confidence -= 5
            risk_factors.append('当日涨幅较大，次日获利盘抛压存在')
    
    # 【风险因子2】换手率过高 + 资金流出 → 次日抛压大
    if turnover > 15:
        has_flow_data = capital_flow.get('has_data', False)
        if has_flow_data and not capital_flow.get('is_inflow', False):
            base_return -= 1.0
            confidence -= 10
            risk_factors.append('换手率高且资金流出，次日抛压较大')
        elif turnover > 20:
            base_return -= 0.5
            confidence -= 5
            risk_factors.append('换手率过高，次日波动可能加大')
    
    # 【风险因子3】距涨停很近 → 次日上涨空间受限
    if upside_space.get('near_limit', False):
        base_return -= 1.0
        confidence -= 10
        risk_factors.append('已接近涨停，次日继续上涨空间有限')
    
    # 【增强因子1】尾盘强势 + 资金流入 + 距涨停远
    if tail_trend.get('trend') == 'strong_up':
        has_flow_data = capital_flow.get('has_data', False)
        if has_flow_data and capital_flow.get('is_inflow', False):
            if upside_space.get('space', 0) >= 5:
                base_return += 1.0
                confidence += 15
            else:
                base_return += 0.5
                confidence += 10
    
    # 【增强因子2】大盘环境好
    if market_env.get('market_sentiment') == 'bullish':
        base_return += 0.5
        confidence += 5
    elif market_env.get('index_change', 0) < -1:
        base_return -= 0.5
        confidence -= 10
    
    # 【增强因子3】尾盘温和上涨 + 当日涨幅适中（3-5%）→ 健康走势
    if tail_trend.get('trend') in ['up', 'strong_up'] and 3 <= change_percent <= 5:
        base_return += 0.3
        confidence += 5
    
    # 限制范围
    expected_return = max(-2.0, min(5.0, base_return))  # 预期涨幅限制在 -2% 到 5%
    confidence = max(0, min(100, confidence))            # 信心度 0-100
    
    # 风险等级
    if len(risk_factors) >= 3:
        risk_level = 'high'
    elif len(risk_factors) >= 1:
        risk_level = 'medium'
    else:
        risk_level = 'low'
    
    return {
        'expected_return': round(expected_return, 2),
        'confidence': confidence,
        'risk_level': risk_level,
        'risk_factors': risk_factors,
    }


def ai_select_stocks(
    screened_stocks: List[Dict],
    all_stocks_data: List[Dict],
    include_kcb_cyb: bool = False,
    prefer_tail_inflow: bool = False,
    strict_risk_control: bool = False,
) -> List[Dict]:
    """AI精选算法 - T+1短线优化版
    
    策略：收盘前20分钟买入，第二天卖出
    重点关注：尾盘走势、资金抢筹、上涨空间、明日高开概率
    """
    
    # 获取上证指数的全局环境（用于整体判断）
    global_market_env = get_market_environment()
    
    print(f"[AI精选] 开始分析 {len(screened_stocks)} 只股票...")
    candidates = []
    
    for idx, stock in enumerate(screened_stocks, 1):
        code = stock['code']
        name = stock['name']
        
        # 进度提示
        if idx % 5 == 0 or idx == len(screened_stocks):
            print(f"[AI精选] 进度: {idx}/{len(screened_stocks)} ({idx*100//len(screened_stocks)}%)")
        
        # ===== 排除ST/退市风险股票 =====
        if 'ST' in name or '*ST' in name or 'S' == name[0] or '退' in name:
            continue  # 跳过所有特殊处理股票
        
        # 如果不包含科创板/创业板，则跳过
        if not include_kcb_cyb:
            if code.startswith('688') or code.startswith('300') or code.startswith('301'):
                continue
        
        # 根据股票所在板块动态获取大盘环境
        market_env = get_market_environment(code)
        
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
        
        # ===== 新增：检测盘中闪崩 =====
        flash_crash = False
        if len(minute_data) >= 10:
            try:
                # 检测任意5分钟内暴跌超过3%
                for i in range(len(minute_data) - 5):
                    window = minute_data[i:i+5]
                    if len(window) >= 2:
                        start_price = window[0]['price']
                        min_price = min(m['price'] for m in window)
                        drop_percent = (start_price - min_price) / start_price * 100 if start_price > 0 else 0
                        
                        if drop_percent > 3:
                            flash_crash = True
                            score -= 15
                            warnings.append(f"盘中出现闪崩（5分钟内暴跌{drop_percent:.1f}%），筹码不稳定")
                            break
            except Exception as e:
                print(f"闪崩检测失败 {code}: {e}")
        
        # ===== 新增：尾盘拉升陷阱检测 =====
        tail_trap = False
        if len(minute_data) >= 30:
            try:
                # 获取全天分时数据
                full_day_result = get_minute_data(code, minutes=240)
                full_day_data = full_day_result.get('data', [])
                
                if len(full_day_data) >= 60:
                    # 计算全天均价和最低价
                    all_prices = [m['price'] for m in full_day_data if m['price'] > 0]
                    if all_prices:
                        day_avg_price = sum(all_prices) / len(all_prices)
                        day_low_price = min(all_prices)
                        
                        # 计算午盘（10:30-13:00）均价
                        morning_data = [m for m in full_day_data if 60 <= full_day_data.index(m) < 150]
                        if morning_data:
                            morning_prices = [m['price'] for m in morning_data if m['price'] > 0]
                            if morning_prices:
                                morning_avg = sum(morning_prices) / len(morning_prices)
                                
                                # 尾盘拉升陷阱特征：
                                # 1. 全天大部分时间在下跌（当前价 < 午盘均价3%以上）
                                # 2. 尾盘突然拉升（尾盘涨幅 > 2%）
                                # 3. 全天振幅较大（> 5%）
                                if pre_close > 0:
                                    day_range = (max(all_prices) - day_low_price) / pre_close * 100
                                    price_vs_morning = (current_price - morning_avg) / morning_avg * 100
                                    
                                    if day_range > 5 and price_vs_morning < -2 and tail_trend.get('tail_change', 0) > 2:
                                        tail_trap = True
                                        score -= 20
                                        warnings.append(f"⚠️ 尾盘拉升陷阱：全天低迷突然尾拉，诱多嫌疑")
            except Exception as e:
                print(f"尾盘陷阱检测失败 {code}: {e}")
        
        # ===== 新增：诱多识别 =====
        fake_pump = False
        if len(minute_data) >= 30:
            try:
                # 获取全天数据
                full_day_result = get_minute_data(code, minutes=240)
                full_day_data = full_day_result.get('data', [])
                
                if len(full_day_data) >= 60:
                    # 开盘30分钟数据
                    opening_data = full_day_data[:30] if len(full_day_data) >= 30 else full_day_data[:10]
                    if opening_data and len(opening_data) >= 2:
                        opening_price = opening_data[0]['price']
                        opening_30m_high = max(m['price'] for m in opening_data)
                        opening_30m_change = (opening_30m_high - opening_price) / opening_price * 100 if opening_price > 0 else 0
                        
                        # 诱多特征1：开盘30分钟冲高 > 2%，但尾盘回落到涨幅 < 1%
                        if opening_30m_change > 2 and change_percent < 1:
                            fake_pump = True
                            score -= 10
                            warnings.append(f"⚠️ 开盘冲高回落：开盘30分钟冲高{opening_30m_change:.1f}%后回落，诱多形态")
                    
                    # 诱多特征2：尾盘急拉但成交量萎缩
                    if tail_trend.get('tail_change', 0) > 1.5:
                        tail_volume_ratio = tail_trend.get('tail_volume_ratio', 50)
                        if tail_volume_ratio < 25:  # 尾盘成交量占比 < 25%
                            fake_pump = True
                            score -= 8
                            warnings.append(f"⚠️ 尾盘急拉缩量：成交量占比仅{tail_volume_ratio:.1f}%，拉升无力")
            except Exception as e:
                print(f"诱多识别失败 {code}: {e}")

        # 根据当前时间和是否已收盘，动态调整尾盘信号权重（越接近收盘权重越高）
        # 优化：13:30后就开始提升权重，避免错过早期信号
        now = datetime.now()
        current_time = now.hour * 100 + now.minute
        is_after_close = minute_result.get('is_after_close', False)
        if is_after_close:
            tail_weight = 1.2
        elif current_time >= 1450:
            tail_weight = 1.0
        elif current_time >= 1430:
            tail_weight = 0.8
        elif current_time >= 1400:
            tail_weight = 0.7  # 优化：从0.6提升至0.7
        elif current_time >= 1330:
            tail_weight = 0.5  # 新增：13:30-14:00区间
        else:
            tail_weight = 0.4
        
        # 2. 计算上涨空间
        upside = calculate_upside_space(current_price, pre_close, code)
        
        # 3. 获取资金流向
        capital_flow = get_capital_flow(code)
        has_flow_data = capital_flow.get('has_data', False)
        
        # 3.5 检查涨停板风险（增强版）
        limit_info = check_touched_limit(code, current_price, pre_close)
        if limit_info['opened']:  # 涨停打开，高风险
            score -= 20
            warnings.append("⚠️⚠️ 触及涨停后打开，主力出货嫌疑极大")
        elif limit_info['current_at_limit']:  # 当前在涨停
            score -= 8
            warnings.append("当前涨停，次日高开低走风险")
        elif limit_info['touched']:  # 触及过涨停但未打开
            score -= 5
            warnings.append("盘中触及涨停，追高需谨慎")
        
        # 4. 检查利空消息
        negative_info = check_negative_news(code, days=3)

        # 5. 阶段涨幅（近20日）+ 跳空缺口 + 成交量异常检测 + 【新增】超跌反弹检测
        phase_change_20d = None
        consecutive_up_days = 0  # 连续阳线天数
        has_gap = False  # 是否有未回补缺口
        volume_surge = False  # 成交量异常放大
        oversold_rebound = False  # 超跌反弹机会
        oversold_score_bonus = 0  # 超跌反弹加分
        
        if strict_risk_control:
            try:
                kline = fetch_qq_kline_data(code, days=30)
                if code.startswith('6') or code.startswith('9'):
                    symbol = f"sh{code}"
                else:
                    symbol = f"sz{code}"

                if isinstance(kline, dict) and 'data' in kline and symbol in kline['data']:
                    qfqday = kline['data'][symbol].get('qfqday', []) or []
                    closes = []
                    opens = []
                    highs = []
                    lows = []
                    volumes = []
                    
                    for d in qfqday:
                        if len(d) >= 6:
                            try:
                                opens.append(float(d[1]))
                                closes.append(float(d[2]))
                                highs.append(float(d[3]))
                                lows.append(float(d[4]))
                                volumes.append(float(d[5]))
                            except Exception:
                                continue
                    
                    # 计算阶段涨幅
                    if len(closes) >= 20:
                        base_price = closes[-20]
                        last_price = closes[-1]
                        if base_price > 0:
                            phase_change_20d = (last_price - base_price) / base_price * 100

                            # 高位惩罚：近20日涨幅过大，T+1 风险显著增加
                            if phase_change_20d >= 60:
                                score -= 30
                                warnings.append(f"近20日累计上涨约{phase_change_20d:.1f}% ，处于高位，短线风险大")
                            elif phase_change_20d >= 40:
                                score -= 15
                                warnings.append(f"近20日累计上涨约{phase_change_20d:.1f}% ，属于较大涨幅区间，需防回调")
                            
                            # 【新增】超跌反弹检测：近20日累计下跌>=15%，且最近3日开始企稳/反弹
                            elif phase_change_20d <= -15:
                                # 检查最近3日是否出现企稳信号
                                if len(closes) >= 23 and len(volumes) >= 23:
                                    recent_3d_change = (closes[-1] - closes[-4]) / closes[-4] * 100 if closes[-4] > 0 else 0
                                    
                                    # 新增：成交量验证 - 近3日成交量需要放大
                                    avg_volume_before = sum(volumes[-23:-3]) / 20 if len(volumes) >= 23 else 0
                                    avg_volume_recent = sum(volumes[-3:]) / 3
                                    volume_increase = (avg_volume_recent / avg_volume_before - 1) * 100 if avg_volume_before > 0 else 0
                                    
                                    # 启用技术指标辅助判断
                                    rsi_value = calculate_rsi(closes)
                                    macd_data = calculate_macd(closes)
                                    rsi_oversold = rsi_value < 35  # RSI < 35视为超卖
                                    macd_golden = macd_data.get('golden_cross', False)
                                    
                                    # 条件：1. 近20日跌幅>=15%  2. 最近3日反弹>=3%  3. 当日上涨  4. 成交量放大>=20%
                                    if recent_3d_change >= 3 and change_percent > 0 and volume_increase >= 20:
                                        oversold_rebound = True
                                        oversold_score_bonus = 25  # 超跌反弹大幅加分
                                        score += oversold_score_bonus
                                        reasons.append(f"🔄 超跌反弹机会：近20日跌{abs(phase_change_20d):.1f}%，最近3日反弹{recent_3d_change:.1f}%，成交量放大{volume_increase:.1f}%")
                                        
                                        # 技术指标加分
                                        if rsi_oversold:
                                            score += 5
                                            reasons.append(f"📊 RSI超卖反弹：RSI={rsi_value:.1f}")
                                        if macd_golden:
                                            score += 5
                                            reasons.append("📊 MACD金叉")
                                    
                                    # 条件：1. 近20日跌幅>=15%  2. 最近3日反弹>=1.5%  3. 成交量放大>=10%
                                    elif recent_3d_change >= 1.5 and volume_increase >= 10:
                                        oversold_rebound = True
                                        oversold_score_bonus = 15  # 超跌反弹适度加分
                                        score += oversold_score_bonus
                                        reasons.append(f"🔄 超跌企稳：近20日跌{abs(phase_change_20d):.1f}%，最近3日企稳反弹{recent_3d_change:.1f}%")
                                        
                                        # 技术指标加分
                                        if rsi_oversold:
                                            score += 3
                                            reasons.append(f"📊 RSI={rsi_value:.1f}")
                                    
                                    # 如果成交量不足，给出警告
                                    elif recent_3d_change >= 1.5 and volume_increase < 10:
                                        warnings.append(f"⚠️ 超跌企稳但成交量不足（仅放大{volume_increase:.1f}%），反弹可持续性存疑")
                    
                    # 检测连续阳线（从最近一天往回数）
                    if len(closes) >= 7 and len(opens) >= 7:
                        for i in range(len(closes) - 1, max(len(closes) - 8, -1), -1):
                            if closes[i] > opens[i]:  # 阳线
                                consecutive_up_days += 1
                            else:
                                break
                        
                        # 连续阳线风险提示（超跌反弹除外）
                        if not oversold_rebound:
                            if consecutive_up_days >= 7:
                                score -= 20
                                warnings.append(f"连续{consecutive_up_days}根阳线，技术形态过热，回调风险极高")
                            elif consecutive_up_days >= 5:
                                score -= 10
                                warnings.append(f"连续{consecutive_up_days}根阳线，小心技术性回调")
                    
                    # ===== 新增：检测跳空缺口（近5日） =====
                    if len(opens) >= 5 and len(highs) >= 5 and len(lows) >= 5:
                        for i in range(len(closes) - 1, max(len(closes) - 6, 0), -1):
                            prev_high = highs[i - 1]
                            curr_low = lows[i]
                            # 向上跳空：今日最低价 > 昨日最高价
                            gap_up_percent = (curr_low - prev_high) / prev_high * 100 if prev_high > 0 else 0
                            
                            if gap_up_percent > 3:  # 跳空超过3%
                                # 检查是否已回补（后续是否有K线最低价低于缺口）
                                gap_filled = False
                                for j in range(i + 1, len(lows)):
                                    if lows[j] <= prev_high:
                                        gap_filled = True
                                        break
                                
                                if not gap_filled:
                                    has_gap = True
                                    score -= 15
                                    warnings.append(f"存在未回补跳空缺口（{gap_up_percent:.1f}%），次日有回补压力")
                                    break
                    
                    # ===== 新增：检测成交量异常放大 =====
                    if len(volumes) >= 6:
                        # 计算前5日平均成交量
                        avg_volume_5d = sum(volumes[-6:-1]) / 5
                        current_volume = volumes[-1]
                        
                        if avg_volume_5d > 0:
                            volume_ratio_5d = current_volume / avg_volume_5d
                            
                            # 成交量突然放大5倍以上，属于异常
                            if volume_ratio_5d >= 5:
                                volume_surge = True
                                score -= 20
                                warnings.append(f"成交量异常放大{volume_ratio_5d:.1f}倍，次日剧烈波动风险高")
                            elif volume_ratio_5d >= 3.5:
                                volume_surge = True
                                score -= 10
                                warnings.append(f"成交量放大{volume_ratio_5d:.1f}倍，需防范异常波动")
                    
            except Exception as e:
                print(f"风险因子检测失败 {code}: {e}")
        
        # ===== T+1短线评分逻辑 =====
        
        # 【核心】尾盘走势评分 (权重最高，盘中过早信号会降权)
        if tail_trend['trend'] == 'strong_up':
            score += int(30 * tail_weight)
            reasons.append(f"🚀 {tail_trend['description']}")
        elif tail_trend['trend'] == 'up':
            score += int(20 * tail_weight)
            reasons.append(f"📈 {tail_trend['description']}")
        elif tail_trend['trend'] == 'stable':
            score += int(10 * tail_weight)
            reasons.append(tail_trend['description'])
        elif tail_trend['trend'] == 'down':
            score -= int(20 * tail_weight)
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
        
        # 【核心】资金流向评分（优化版：区分流向+强度）
        # 权重：prefer_tail_inflow=True时权重提高到2.5
        flow_weight = 2.5 if prefer_tail_inflow else 1.0
        if has_flow_data:
            flow_strength = capital_flow.get('flow_strength', 'unknown')
            main_inflow = capital_flow['main_inflow']
            
            # 根据flow_strength精细化评分
            if flow_strength == 'strong_in':  # 强力流入（放量上涨）
                score += int(35 * flow_weight)
                reasons.append(f"💰💰 主力强力流入{abs(main_inflow):.2f}亿，放量上涨")
            elif flow_strength == 'weak_in':  # 弱流入（温和上涨或缩量上涨）
                score += int(20 * flow_weight)
                reasons.append(f"💰 主力流入{abs(main_inflow):.2f}亿，温和上涨")
            elif flow_strength == 'neutral':  # 横盘
                score += int(5 * flow_weight)
                reasons.append("横盘震荡，观望资金")
            elif flow_strength == 'weak_out':  # 弱流出（温和下跌或缩量下跌）
                score -= int(15 * flow_weight)
                warnings.append(f"⚠️ 主力流出{abs(main_inflow):.2f}亿，温和下跌")
            elif flow_strength == 'strong_out':  # 强力流出（放量下跌/砸盘）
                score -= int(30 * flow_weight)
                warnings.append(f"⚠️⚠️ 主力强力流出{abs(main_inflow):.2f}亿，放量下跌")
        else:
            reasons.append("资金流数据暂缺，不参与资金因子打分")
        
        # 换手率评分 (短线需要活跃但不能太高)
        if 5 <= turnover <= 12:
            score += 15
            reasons.append(f"换手率{turnover}%，交投活跃适中")
        elif 3 <= turnover < 5:
            score += 5
            reasons.append(f"换手率{turnover}%，交投尚可")
        elif 12 < turnover <= 15:
            score += 0  # 中性，不加分也不减分
            reasons.append(f"换手率{turnover}%，交投偏活跃")
        elif turnover > 20:
            score -= 20
            warnings.append(f"换手率{turnover}%过高，可能主力出货")
        elif turnover > 15:
            score -= 10
            warnings.append(f"换手率{turnover}%偏高")
        elif turnover < 3:
            score -= 5
            warnings.append(f"换手率{turnover}%过低，流动性不足")
        
        # 量比评分
        if 1.5 <= volume_ratio <= 3:
            score += 10
            reasons.append(f"量比{volume_ratio:.1f}，温和放量")
        elif 3 < volume_ratio <= 5:
            score += 5
            reasons.append(f"量比{volume_ratio:.1f}，放量较大")
        elif volume_ratio > 5:
            score -= 5
            warnings.append(f"量比{volume_ratio:.1f}过大，可能异常波动")
        elif volume_ratio < 1.5:
            score -= 5
            warnings.append(f"量比{volume_ratio:.1f}偏低，成交不活跃")
        
        # 当日涨幅评分 (T+1短线，涨幅3-5%是较好位置)
        if 3 <= change_percent <= 5:
            score += 15
            reasons.append(f"当日涨幅{change_percent}%，处于拉升初期")
        elif 5 < change_percent <= 7:
            score += 5
            reasons.append(f"当日涨幅{change_percent}%，涨幅适中")
        elif 7 < change_percent <= 8:
            score += 0  # 中性
            reasons.append(f"当日涨幅{change_percent}%，涨幅偏高")
        elif change_percent > 8:
            score -= 10
            warnings.append(f"当日涨幅{change_percent}%，追高风险增加")
        elif 1 <= change_percent < 3:
            score += 5
            reasons.append(f"当日涨幅{change_percent}%，温和上涨")
        elif change_percent < 1:
            score -= 5
            warnings.append(f"当日涨幅{change_percent}%，启动不明显")
        
        # 利空消息评分
        if not negative_info['has_negative_news']:
            score += 10
            reasons.append("无近期利空消息")
        else:
            score -= negative_info['negative_count'] * 15
            warnings.append(f"⚠️ 发现{negative_info['negative_count']}条利空消息，明日可能低开")
        
        # 大盘环境（增强版：考虑5日趋势）
        trend_5d = market_env.get('trend_5d', 'neutral')
        if market_env['market_sentiment'] == 'bullish':
            score += 10
            reasons.append(f"大盘强势（{market_env['index_name']}当日+{market_env['index_change']:.2f}%）")
            
            # 5日趋势加分
            if trend_5d == 'strong_bullish':
                score += 8
                reasons.append(f"大盘5日强势（近5日+{market_env.get('change_5d', 0):.2f}%），做多氛围浓厚")
            elif trend_5d == 'bullish':
                score += 5
                reasons.append("大盘5日向好")
        elif market_env['index_change'] < -1:
            score -= 15
            warnings.append(f"大盘下跌（{market_env['index_name']}{market_env['index_change']:.2f}%），明日系统性风险")
            
            # 5日趋势惩罚
            if trend_5d == 'strong_bearish':
                score -= 10
                warnings.append(f"大盘5日持续走弱（近5日{market_env.get('change_5d', 0):.2f}%），趋势不利")
            elif trend_5d == 'bearish':
                score -= 5
                warnings.append("大盘5日偏弱")
        
        # 评估明日收盘预期（T+1策略核心）
        next_day_expectation = calculate_next_day_expectation(
            current_score=score,
            tail_trend=tail_trend,
            upside_space=upside,
            capital_flow=capital_flow,
            change_percent=change_percent,
            turnover=turnover,
            market_env=market_env,
        )
        
        # 将高开低走风险纳入warnings
        if next_day_expectation['risk_factors']:
            for risk in next_day_expectation['risk_factors']:
                warnings.append(f"⚠️ {risk}")
        
        # 根据次日预期调整最终评分
        expected_return = next_day_expectation['expected_return']
        if expected_return < 1.0:  # 预期收益<1%，显著降低评分
            score -= 10
            warnings.append(f"明日收盘预期仅{expected_return}%，持有价值不高")
        
        # 保留高开概率字段用于兼容（基于预期收益映射）
        if expected_return >= 2.5:
            open_probability = 'high'
        elif expected_return >= 1.5:
            open_probability = 'medium'
        else:
            open_probability = 'low'
        
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
                'open_probability': open_probability,
                'next_day_expectation': next_day_expectation,  # 新增：明日收盘预期
            },
            'negative_news': negative_info,
            'minute_volume': minute_result,
            'board_type': get_board_type(code),
            'phase_change_20d': phase_change_20d,
        })
    
    # 按评分排序，优先尾盘大资金流入
    if candidates:
        if any(c['indicators']['capital_flow']['is_inflow'] for c in candidates) and prefer_tail_inflow:
            # 优先主力净流入，其次按主力净流入金额，再按综合得分
            candidates.sort(
                key=lambda x: (
                    0 if x['indicators']['capital_flow']['is_inflow'] else 1,
                    -x['indicators']['capital_flow']['main_inflow'],
                    -x['score'],
                )
            )
        else:
            candidates.sort(key=lambda x: x['score'], reverse=True)
    
    # 根据大盘环境动态调整入选门槛
    index_change = market_env.get('index_change', 0)
    if index_change <= -2:
        min_score = AI_MIN_SCORE_BEAR
    else:
        min_score = AI_MIN_SCORE_BASE

    # 过滤掉评分过低的（短线要求更严格）
    qualified = [c for c in candidates if c['score'] >= min_score]

    # 集中度限制：在严格风控模式下，控制同一板块+概念的持股数量
    if strict_risk_control and qualified:
        max_per_board = 2  # 每个板块最多2只
        max_per_concept = 2  # 每个概念最多2只
        board_counts: Dict[str, int] = {}
        concept_counts: Dict[str, int] = {}
        balanced: List[Dict[str, Any]] = []

        for c in qualified:
            # 板块限制
            board = (c.get('board_type') or {}).get('type') or 'other'
            board_count = board_counts.get(board, 0)
            
            # 概念限制
            stock_name = c.get('name', '')
            concepts = extract_concept_tags(stock_name)
            
            # 检查是否所有概念都已达到上限
            concept_blocked = False
            for concept in concepts:
                if concept_counts.get(concept, 0) >= max_per_concept:
                    concept_blocked = True
                    break
            
            # 如果板块已满或所有概念都已满，跳过
            if board_count >= max_per_board or concept_blocked:
                continue
            
            # 通过限制，添加到结果
            balanced.append(c)
            board_counts[board] = board_count + 1
            for concept in concepts:
                concept_counts[concept] = concept_counts.get(concept, 0) + 1
            
            if len(balanced) >= AI_MAX_PICKS:
                break

        return balanced

    return qualified[:AI_MAX_PICKS]


def extract_concept_tags(stock_name: str) -> List[str]:
    """从股票名称提取概念标签（简易版）
    
    基于关键词匹配识别热点概念，用于集中度风控
    """
    concepts = []
    
    # 数字经济相关
    digital_keywords = ['科技', '云', '数据', '软件', '互联网', '信息', '网络', '通信', '电子', '计算机']
    if any(keyword in stock_name for keyword in digital_keywords):
        concepts.append('数字经济')
    
    # 半导体芯片
    chip_keywords = ['芯片', '半导体', '集成电路', '微电子']
    if any(keyword in stock_name for keyword in chip_keywords):
        concepts.append('半导体')
    
    # 新能源
    energy_keywords = ['新能源', '锂电', '光伏', '风电', '储能', '电池']
    if any(keyword in stock_name for keyword in energy_keywords):
        concepts.append('新能源')
    
    # AI人工智能
    ai_keywords = ['人工智能', 'AI', '智能', '机器人']
    if any(keyword in stock_name for keyword in ai_keywords):
        concepts.append('人工智能')
    
    # 医药生物
    medical_keywords = ['医药', '生物', '制药', '医疗', '健康']
    if any(keyword in stock_name for keyword in medical_keywords):
        concepts.append('医药生物')
    
    # 金融
    finance_keywords = ['银行', '证券', '保险', '信托', '金融']
    if any(keyword in stock_name for keyword in finance_keywords):
        concepts.append('金融')
    
    return concepts if concepts else ['其他']


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
    limit: int = Query(30, description="返回数量"),
    include_kcb_cyb: bool = Query(False, description="是否包含科创板/创业板"),
    prefer_tail_inflow: bool = Query(True, description="是否优先尾盘30分钟主力净流入（初筛过滤）"),
):
    """筛选股票"""
    try:
        print(f"开始筛选股票: 涨幅{change_min}%-{change_max}%, 量比{volume_ratio_min}-{volume_ratio_max}, 市值{market_cap_min}-{market_cap_max}亿, 包含科创板/创业板: {include_kcb_cyb}, 优先尾盘净流入: {prefer_tail_inflow}")
        
        # 获取所有股票数据
        all_stocks = get_all_stocks_data()
        print(f"获取到 {len(all_stocks)} 只股票数据")
        
        # 筛选
        filtered = []
        for stock in all_stocks:
            # 排除ST股票
            if 'ST' in stock['name'] or 'st' in stock['name']:
                continue
            
            # 如果不包含科创板/创业板，则排除
            code = stock['code']
            if not include_kcb_cyb:
                # 科创板: 688xxx, 创业板: 300xxx, 301xxx
                if code.startswith('688') or code.startswith('300') or code.startswith('301'):
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

        # 按涨幅排序，先取一批候选，再根据尾盘资金流做二次过滤
        filtered.sort(key=lambda x: x['change_percent'], reverse=True)
        candidates = filtered[: max(limit * 2, limit)]

        # 如需优先尾盘主力净流入，则只保留最近一笔资金流为净流入且金额>0的股票
        if prefer_tail_inflow and candidates:
            tail_filtered = []
            for stock in candidates:
                cf = get_capital_flow(stock['code'])
                if cf.get('is_inflow') and cf.get('main_inflow', 0) > 0:
                    tail_filtered.append(stock)

            # 如果尾盘净流入的股票不足，则退回到原候选集合避免结果为空
            if tail_filtered:
                candidates = tail_filtered

        # 最终按涨幅排序并截断到 limit
        candidates.sort(key=lambda x: x['change_percent'], reverse=True)
        final_list = candidates[:limit]

        print(f"筛选后剩余 {len(final_list)} 只股票")
        
        result = []
        for stock in final_list:
            # 获取主力资金净流入（亿），用于初筛结果展示
            capital_flow = get_capital_flow(stock['code'])
            main_inflow = capital_flow.get('main_inflow', 0)

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
                "main_inflow": main_inflow,  # 主力净流入（亿）
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
async def filter_stocks(
    codes: str = Query(..., description="股票代码列表，用逗号分隔"),
    include_kcb_cyb: bool = Query(False, description="是否包含科创板/创业板"),
    prefer_tail_inflow: bool = Query(False, description="是否优先尾盘30分钟大资金流入"),
    strict_risk_control: bool = Query(True, description="是否启用阶段涨幅+集中度限制（默认开启）"),
):
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
            
            # 如果不包含科创板/创业板，则跳过
            if not include_kcb_cyb:
                if code.startswith('688') or code.startswith('300') or code.startswith('301'):
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
                # 合格标准：以量价和位置为主，数字经济作为加分项而非硬性条件
                "qualified": has_volume_pattern and above_ma5_high
            }
            
            analysis_results.append(analysis)
            
            # 满足核心量价形态和技术位置即视为优选，数字经济只作为板块加分
            if has_volume_pattern and above_ma5_high:
                # 检查利空消息
                negative_info = check_negative_news(code, days=3)
                # 获取最近30分钟成交量数据
                minute_result = get_minute_data(code, minutes=30)
                # 获取资金流向（用于尾盘资金筛选和排序）
                capital_flow = get_capital_flow(code) if prefer_tail_inflow else None
                
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
                        "sector": "数字经济板块 ✓" if is_digital else "其他板块（数字经济加分）"
                    },
                    "negative_news": negative_info,
                    "minute_volume": minute_result,
                    "capital_flow": capital_flow,
                    "board_type": get_board_type(code)
                })
        
        # 如果不足6只，降低条件（数字经济作为加分项保留在排序得分中）
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
                        # 获取资金流向（用于尾盘资金筛选和排序）
                        capital_flow = get_capital_flow(analysis["code"]) if prefer_tail_inflow else None
                        
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
                                "sector": "数字经济板块 ✓" if analysis["is_digital_economy"] else "其他板块（数字经济加分）"
                            },
                            "negative_news": negative_info,
                            "minute_volume": minute_result,
                            "capital_flow": capital_flow,
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
        
        ai_selected = ai_select_stocks(screened_for_ai, [], include_kcb_cyb, prefer_tail_inflow, strict_risk_control)
        print(f"AI精选完成，选出 {len(ai_selected)} 只股票")

        # 最终精选候选（Top3）- 综合AI精选和技术精选（优化版）
        # 策略：
        # 1. 优先取AI精选前2名
        # 2. 从技术精选中补充1名（不与AI重复，按稳定性+资金流排序）
        # 3. 引入多样性评分：避免同一板块/概念扎堆
        final_picks = []
        
        # 1. 从AI精选中取前2名
        ai_top2 = ai_selected[:2] if len(ai_selected) >= 2 else ai_selected
        ai_codes = {s['code'] for s in ai_top2}
        ai_boards = set()  # 记录AI精选股票的板块
        ai_concepts = set()  # 记录AI精选股票的概念
        
        for candidate in ai_top2:
            board = candidate.get('board_type', {}).get('type', 'other')
            ai_boards.add(board)
            concepts = extract_concept_tags(candidate.get('name', ''))
            ai_concepts.update(concepts)
        
        # 2. 从技术精选(qualified_stocks)中选择1只不在AI前2的股票
        # 【新增】按稳定性评分排序：资金流入 + 多样性 + 换手率适中
        qualified_supplement = None
        if qualified_stocks:
            # 为每只技术精选股票计算综合补充得分
            for stock in qualified_stocks:
                if stock['code'] in ai_codes:
                    continue  # 跳过已在AI前2的股票
                
                supplement_score = 0
                
                # 资金流向加分
                capital_flow = stock.get('capital_flow', {})
                if capital_flow:
                    main_inflow = capital_flow.get('main_inflow', 0)
                    if main_inflow >= 1.0:
                        supplement_score += 40
                    elif main_inflow >= 0.5:
                        supplement_score += 25
                    elif main_inflow >= 0.3:
                        supplement_score += 15
                
                # 量比稳定性加分（1.5-3为温和放量，最稳定）
                volume_ratio = stock.get('volume_ratio', 0)
                if 1.5 <= volume_ratio <= 3:
                    supplement_score += 20
                elif 1.2 <= volume_ratio < 1.5:
                    supplement_score += 10
                
                # 换手率适中性加分
                turnover = stock.get('turnover', 0)
                if 5 <= turnover <= 10:
                    supplement_score += 15
                elif 3 <= turnover < 5:
                    supplement_score += 8
                
                # 【多样性加分】：不同板块+不同概念优先
                board = stock.get('board_type', {}).get('type', 'other')
                concepts = extract_concept_tags(stock.get('name', ''))
                
                # 板块多样性
                if board not in ai_boards:
                    supplement_score += 30  # 不同板块大幅加分
                
                # 概念多样性
                concept_overlap = len(set(concepts) & ai_concepts)
                if concept_overlap == 0:
                    supplement_score += 25  # 完全不同概念加分
                elif concept_overlap == 1:
                    supplement_score += 10  # 部分重叠小幅加分
                
                stock['_supplement_score'] = supplement_score
            
            # 按补充得分排序
            sorted_qualified = sorted(
                [s for s in qualified_stocks if s['code'] not in ai_codes],
                key=lambda x: x.get('_supplement_score', 0),
                reverse=True
            )
            
            if sorted_qualified:
                qualified_supplement = sorted_qualified[0]
                print(f"[最终精选] 技术精选补充：{qualified_supplement['name']}({qualified_supplement['code']})，"
                      f"补充得分={qualified_supplement.get('_supplement_score', 0)}")
        
        # 3. 组合候选：AI前2 + 技术精选1
        top_candidates = []
        
        # 添加AI前2
        for candidate in ai_top2:
            candidate['_selection_source'] = 'AI智能精选'
            top_candidates.append(candidate)
        
        # 添加技术精选补充（如果有）
        if qualified_supplement and len(top_candidates) < 3:
            # 将qualified_stock转换为ai_selected的格式
            supp_candidate = {
                'code': qualified_supplement['code'],
                'name': qualified_supplement['name'],
                'price': qualified_supplement['price'],
                'change_percent': qualified_supplement['change_percent'],
                'volume_ratio': qualified_supplement['volume_ratio'],
                'market_cap': qualified_supplement['market_cap'],
                'turnover': qualified_supplement.get('turnover', 0),
                'score': 70,  # 提高基准分（技术精选通过+补充评分高）
                'reasons': [
                    '✅ 技术精选：量价形态优秀',
                    '✅ 站稳5日线+近期高点',
                    f'✅ 补充得分：{qualified_supplement.get("_supplement_score", 0)}分（多样性+稳定性）'
                ],
                'warnings': ['⚠️ 该股票为技术筛选补充，综合AI精选研判'],
                'indicators': {
                    'tail_trend': {'trend': 'unknown', 'description': '技术精选股票'},
                    'upside_space': {'space': 0, 'near_limit': False},
                    'capital_flow': qualified_supplement.get('capital_flow', {}),
                    'open_probability': 'medium',
                    'next_day_expectation': {
                        'expected_return': 2.0,
                        'risk_level': 'medium',
                        'confidence': 'medium',
                        'risk_factors': []
                    }
                },
                'negative_news': qualified_supplement.get('negative_news', {}),
                'minute_volume': qualified_supplement.get('minute_volume', {}),
                'board_type': qualified_supplement.get('board_type'),
                'phase_change_20d': None,
                '_selection_source': '技术精选补充',
            }
            top_candidates.append(supp_candidate)
            print(f"[最终精选] 添加技术精选补充：{qualified_supplement['name']}({qualified_supplement['code']})")
        
        # 4. 如果还不够3只，继续从AI精选补充
        if len(top_candidates) < 3 and len(ai_selected) > 2:
            remaining_ai = [s for s in ai_selected[2:] if s['code'] not in {c['code'] for c in top_candidates}]
            for candidate in remaining_ai[:3 - len(top_candidates)]:
                candidate['_selection_source'] = 'AI智能精选'
                top_candidates.append(candidate)
        
        # ===== 优化：按主力资金抢筹行业重新排序（多维度综合判断） =====
        # 统计每个行业的资金流入情况和个股热度
        industry_analysis = {}  # {行业: {'count': 个股数, 'total_inflow': 总流入, 'is_hot': 是否热门}}
        
        # 遍历所有候选股票，统计行业资金流入
        all_candidates_for_analysis = list(ai_selected) + (
            [qualified_supplement] if qualified_supplement else []
        )
        
        for candidate in all_candidates_for_analysis:
            # 获取股票的概念标签
            concepts = extract_concept_tags(candidate.get('name', ''))
            
            # 获取资金流向
            capital_flow = None
            if 'indicators' in candidate:
                capital_flow = candidate['indicators'].get('capital_flow', {})
            elif 'capital_flow' in candidate:
                capital_flow = candidate['capital_flow']
            
            # 统计每个行业的情况
            for concept in concepts:
                if concept not in industry_analysis:
                    industry_analysis[concept] = {
                        'count': 0,
                        'total_inflow': 0,
                        'strong_count': 0,  # 强力流入的股票数
                        'is_hot': False
                    }
                
                industry_analysis[concept]['count'] += 1
                
                if capital_flow:
                    main_inflow = capital_flow.get('main_inflow', 0)
                    flow_strength = capital_flow.get('flow_strength', 'unknown')
                    
                    industry_analysis[concept]['total_inflow'] += main_inflow
                    
                    # 统计强力流入的股票数
                    if flow_strength == 'strong_in':
                        industry_analysis[concept]['strong_count'] += 1
        
        # 判断热门行业：
        # 条件1：该行业总资金流入 >= 1.5亿
        # 条件2：或者该行业有2只以上股票且至少1只强力流入
        for concept, data in industry_analysis.items():
            total_inflow = data['total_inflow']
            strong_count = data['strong_count']
            stock_count = data['count']
            
            if total_inflow >= 1.5:  # 总流入大于等于1.5亿
                data['is_hot'] = True
            elif stock_count >= 2 and strong_count >= 1:  # 有2只以上且至少1只强力流入
                data['is_hot'] = True
        
        hot_industries = [k for k, v in industry_analysis.items() if v['is_hot']]
        print(f"[行业分析] 近30分钟主力大幅抢筹的热门行业: {hot_industries}")
        for concept, data in industry_analysis.items():
            if data['is_hot']:
                print(f"  - {concept}: {data['count']}只股票, 总流入{data['total_inflow']:.2f}亿, "
                      f"强力流入{data['strong_count']}只")
        
        # 为每个候选股票添加行业热度标识和原始索引
        for idx, candidate in enumerate(top_candidates):
            concepts = extract_concept_tags(candidate.get('name', ''))
            candidate['concepts'] = concepts
            
            # 判断是否属于热门抢筹行业（任一概念属于热门即可）
            candidate['is_hot_industry'] = any(
                industry_analysis.get(c, {}).get('is_hot', False) for c in concepts
            )
            
            # 计算行业热度得分（用于更精细的排序）
            hot_score = 0
            for c in concepts:
                if industry_analysis.get(c, {}).get('is_hot', False):
                    # 热度得分 = 总流入金额 + 强力流入股票数*10
                    data = industry_analysis[c]
                    hot_score += data['total_inflow'] + data['strong_count'] * 10
            candidate['_hot_score'] = hot_score
            
            # 保存原始顺序索引
            candidate['_original_index'] = idx
        
        # 按行业热度重新排序：热门行业优先，其次按热度得分，最后保持原有顺序
        top_candidates.sort(key=lambda x: (
            not x.get('is_hot_industry', False),  # False(热门)排在前面
            -x.get('_hot_score', 0),  # 热度得分高的优先
            x.get('_original_index', 999)  # 使用保存的原始索引作为次要排序
        ))
        
        # 移除临时字段
        for candidate in top_candidates:
            candidate.pop('_original_index', None)
            candidate.pop('_hot_score', None)
        
        # 打印排序后的结果
        candidate_names = []
        for c in top_candidates:
            hot_mark = '🔥' if c.get('is_hot_industry') else ''
            source_mark = f"[{c.get('_selection_source', 'AI')}]"
            candidate_names.append(f"{c['name']}({c['code']}){hot_mark}{source_mark}")
        print(f"[最终精选] 按行业资金热度排序后：{candidate_names}")
        
        for rank, candidate in enumerate(top_candidates, start=1):
            best = candidate
            
            # 为每个候选股票动态获取对应板块的大盘环境
            market_env = get_market_environment(best['code'])
            
            indicators = best.get('indicators', {})
            tail_trend = indicators.get('tail_trend', {})
            upside_space = indicators.get('upside_space', {})
            capital_flow = indicators.get('capital_flow', {})
            open_prob = indicators.get('open_probability')
            next_day_exp = indicators.get('next_day_expectation', {})
            neg = best.get('negative_news', {}) or {}
            
            current_price = best['price']
            change_percent = best['change_percent']
            turnover = best.get('turnover', 0)

            # ===== 止损止盈逻辑（T+1策略核心） =====
            # 1. 基础止损止盈比例
            base_stop_loss = -2.0   # 基础止损 -2%
            base_take_profit = 3.0  # 基础止盈 +3%
            
            # 2. 根据风险等级调整
            risk_level = next_day_exp.get('risk_level', 'medium')
            if risk_level == 'high':
                base_stop_loss = -1.5   # 高风险严格止损
                base_take_profit = 2.0  # 降低目标
            elif risk_level == 'low':
                base_stop_loss = -2.5   # 低风险放宽止损
                base_take_profit = 4.0  # 提高目标
            
            # 3. 根据次日预期收益调整止盈
            expected_return = next_day_exp.get('expected_return', 2.0)
            if expected_return >= 3.0:
                base_take_profit = max(base_take_profit, expected_return + 0.5)
            elif expected_return < 1.5:
                base_take_profit = min(base_take_profit, 2.0)
            
            # 4. 根据波动率（换手率代理）调整
            if turnover > 15:  # 高波动
                base_stop_loss = max(base_stop_loss, -1.5)  # 严格止损
            elif turnover < 5:  # 低波动
                base_stop_loss = min(base_stop_loss, -2.5)  # 放宽止损
            
            # 5. 计算具体价位
            entry_price = round(current_price * 1.0, 2)  # 建议买入价（尾盘当前价）
            stop_loss_price = round(current_price * (1 + base_stop_loss / 100), 2)
            take_profit_price = round(current_price * (1 + base_take_profit / 100), 2)
            
            # 6. 次日开盘策略（动态应对高开/平开/低开）
            open_strategy = {
                'high_open_threshold': 3.0,  # 高开3%以上
                'high_open_action': '立即减仓50%，剩余仓位看5分钟走势决定',
                'low_open_threshold': -2.0,  # 低开2%以下
                'low_open_action': '观察3-5分钟，如反弹无力则止损离场',
                'flat_open_action': '按计划执行，触及止盈价分批减仓，触及止损价立即离场',
            }
            
            # 7. 生成操作建议
            trade_plan = {
                'entry_price': entry_price,
                'entry_time': '尾盘14:40-14:50分批介入',
                'stop_loss_price': stop_loss_price,
                'stop_loss_ratio': base_stop_loss,
                'take_profit_price': take_profit_price,
                'take_profit_ratio': base_take_profit,
                'expected_return': expected_return,
                'hold_period': 'T+1（次日卖出）',
                'risk_reward_ratio': round(abs(base_take_profit / base_stop_loss), 2),
                'open_strategy': open_strategy,  # 新增：开盘策略
            }
            
            # 8. 生成操作提示（包含开盘策略）
            operation_tips = []
            operation_tips.append(f"建议买入价：{entry_price}元（尾盘14:40-14:50分批介入）")
            operation_tips.append(f"止损价：{stop_loss_price}元（{base_stop_loss:+.1f}%）")
            operation_tips.append(f"止盈价：{take_profit_price}元（{base_take_profit:+.1f}%）")
            operation_tips.append("")  # 空行分隔
            operation_tips.append("【次日开盘策略】")
            operation_tips.append(f"• 高开≥{open_strategy['high_open_threshold']}%：{open_strategy['high_open_action']}")
            operation_tips.append(f"• 低开≤{open_strategy['low_open_threshold']}%：{open_strategy['low_open_action']}")
            operation_tips.append(f"• 平开（±2%内）：{open_strategy['flat_open_action']}")
            operation_tips.append("")  # 空行分隔
            
            if risk_level == 'high':
                operation_tips.append("⚠️ 高风险标的，建议半仓试仓，严格执行止损")
            elif expected_return >= 3.0:
                operation_tips.append("✅ 次日预期较好，可适当加仓，但仍需设置止损")
            
            if turnover > 15:
                operation_tips.append("📈 波动率较大，建议分批建仓，次日见好就收")
            
            # 大盘环境提示
            if market_env and market_env.get('index_change', 0) < -1:
                operation_tips.append("⚠️ 大盘弱势，建议次日开盘后首次冲高减仓")

            # 组合一段可读性强的分析总结
            summary_parts = []
            if tail_trend.get('description'):
                summary_parts.append(f"尾盘走势：{tail_trend['description']}")
            if upside_space.get('space') is not None:
                space = upside_space.get('space', 0)
                summary_parts.append(f"距涨停还有约{space:.1f}%空间")
            if capital_flow.get('main_inflow') is not None:
                mi = capital_flow.get('main_inflow', 0)
                if mi > 0:
                    summary_parts.append(f"主力净流入约{mi}亿，资金态度偏多")
                elif mi < 0:
                    summary_parts.append(f"主力净流出约{abs(mi)}亿，需关注资金态度")
                else:
                    summary_parts.append("主力资金整体持平")
            if neg:
                if neg.get('has_negative_news'):
                    summary_parts.append(f"近3日有{neg.get('negative_count', 0)}条利空消息，风险等级：{neg.get('risk_level', 'unknown')}")
                else:
                    summary_parts.append("近3日未检测到明显利空消息")
            # 大盘环境概览
            if market_env:
                idx_chg = market_env.get('index_change', 0)
                sentiment = market_env.get('market_sentiment', 'unknown')
                summary_parts.append(f"大盘今日{idx_chg:+.2f}%，整体情绪偏{sentiment}")

            pick_info = {
                'rank': rank,  # 新增：排名
                'code': best['code'],
                'name': best['name'],
                'price': best['price'],
                'change_percent': best['change_percent'],
                'volume_ratio': best['volume_ratio'],
                'market_cap': best['market_cap'],
                'turnover': best.get('turnover', 0),
                'score': best.get('score', 0),
                'open_probability': open_prob,
                'summary': '；'.join(summary_parts),
                'reasons': best.get('reasons', []),
                'warnings': best.get('warnings', []),
                'tail_trend': tail_trend,
                'upside_space': upside_space,
                'capital_flow': capital_flow,
                'negative_risk': {
                    'has_negative_news': neg.get('has_negative_news', False),
                    'risk_level': neg.get('risk_level', 'low'),
                    'negative_count': neg.get('negative_count', 0),
                },
                'board_type': best.get('board_type'),
                'market_environment': market_env,
                'trade_plan': trade_plan,
                'operation_tips': operation_tips,
                'source': 'ai' if rank <= len(ai_top2) else 'technical',  # 新增：来源标识
                'source_label': 'AI智能精选' if rank <= len(ai_top2) else '技术精选',  # 新增：来源显示
                'concepts': best.get('concepts', []),  # 新增：概念标签
                'is_hot_industry': best.get('is_hot_industry', False),  # 新增：是否热门行业
            }
            final_picks.append(pick_info)
        
        # 保留final_pick兼容旧版（取第一名）
        final_pick = final_picks[0] if final_picks else None
        
        return {
            "count": len(qualified_stocks[:6]),
            "total_analyzed": len(code_list),
            "filter_criteria": {
                "volume_pattern": "阶梯式放量",
                "price_position": "站稳5日线+近期高点",
                "sector": "优先数字经济（加分项）",
                "tail_inflow": "优先尾盘30分钟主力净流入" if prefer_tail_inflow else "不强制尾盘资金条件",
                "risk_control": "开启阶段涨幅+集中度限制" if strict_risk_control else "未开启阶段涨幅+集中度限制",
            },
            "data": qualified_stocks[:6],
            "all_analysis": analysis_results,
            "ai_selected": ai_selected,
            "market_environment": market_env,
            "final_pick": final_pick,  # 兼容旧版：单个精选（第一名）
            "final_picks": final_picks  # 新增：Top3候选列表
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
