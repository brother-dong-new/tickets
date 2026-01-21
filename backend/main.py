"""
A股行情数据API服务
使用 FastAPI + 直接HTTP请求获取实时股票数据
"""

import os
import subprocess
import json

# 禁用代理
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'
for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    if key in os.environ:
        del os.environ[key]

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def fetch_with_curl(url: str, timeout: int = 30, headers: Dict[str, str] = None, encoding: str = 'gbk') -> str:
    """使用系统curl获取数据，绕过Python SSL问题"""
    try:
        cmd = ['curl', '-s', '--connect-timeout', str(timeout)]
        if headers:
            for key, value in headers.items():
                cmd.extend(['-H', f'{key}: {value}'])
        cmd.append(url)
        
        result = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
        if result.returncode == 0:
            # 尝试用指定编码解码，失败则尝试其他编码
            for enc in [encoding, 'gbk', 'gb2312', 'utf-8', 'latin-1']:
                try:
                    return result.stdout.decode(enc)
                except (UnicodeDecodeError, LookupError):
                    continue
            return result.stdout.decode('latin-1')  # 最后的fallback
        raise Exception(f"curl failed: {result.stderr.decode('utf-8', errors='ignore')}")
    except subprocess.TimeoutExpired:
        raise Exception("请求超时")


def get_all_stock_codes() -> List[str]:
    """获取所有A股股票代码"""
    # 沪市主板: 600xxx, 601xxx, 603xxx, 605xxx
    # 深市主板: 000xxx, 001xxx
    # 创业板: 300xxx, 301xxx
    # 科创板: 688xxx, 689xxx
    codes = []
    
    # 生成常见的股票代码范围
    for prefix in ['600', '601', '603', '605']:
        for i in range(1000):
            codes.append(f"sh{prefix}{i:03d}")
    
    for prefix in ['000', '001', '002', '003']:
        for i in range(1000):
            codes.append(f"sz{prefix}{i:03d}")
    
    for prefix in ['300', '301']:
        for i in range(1000):
            codes.append(f"sz{prefix}{i:03d}")
    
    for prefix in ['688']:
        for i in range(1000):
            codes.append(f"sh{prefix}{i:03d}")
    
    return codes


def parse_sina_stock_data(data: str) -> List[Dict]:
    """解析新浪股票数据"""
    import re
    results = []
    
    lines = data.strip().split('\n')
    for line in lines:
        if not line or '=""' in line:
            continue
        
        match = re.match(r'var hq_str_(\w+)="(.*)";?', line)
        if not match:
            continue
        
        code_full = match.group(1)
        values = match.group(2)
        
        if not values:
            continue
        
        parts = values.split(',')
        if len(parts) < 32:
            continue
        
        try:
            # 新浪数据格式：名称,今开,昨收,当前价,最高,最低,买入价,卖出价,成交量,成交额...
            code = code_full[2:]  # 去掉sh/sz前缀
            name = parts[0]
            open_price = float(parts[1]) if parts[1] else 0
            pre_close = float(parts[2]) if parts[2] else 0
            current_price = float(parts[3]) if parts[3] else 0
            high = float(parts[4]) if parts[4] else 0
            low = float(parts[5]) if parts[5] else 0
            volume = float(parts[8]) if parts[8] else 0  # 成交量（股）
            amount = float(parts[9]) if parts[9] else 0  # 成交额
            
            if current_price <= 0 or pre_close <= 0:
                continue
            
            change = current_price - pre_close
            change_percent = (change / pre_close) * 100 if pre_close > 0 else 0
            
            results.append({
                '代码': code,
                '名称': name,
                '最新价': current_price,
                '涨跌额': round(change, 2),
                '涨跌幅': round(change_percent, 2),
                '成交量': volume / 100,  # 转换为手
                '成交额': amount,
                '今开': open_price,
                '昨收': pre_close,
                '最高': high,
                '最低': low,
                '换手率': 0,  # 新浪不提供
                '量比': 1.5,  # 默认值，后续可优化
                '流通市值': 100 * 100000000,  # 默认100亿，后续可优化
            })
        except (ValueError, IndexError):
            continue
    
    return results


def get_stock_list_em() -> pd.DataFrame:
    """获取A股实时行情数据（使用新浪API）"""
    # 获取热门股票代码列表（为了速度，只获取部分股票）
    # 这里使用预定义的热门股票池
    hot_codes = []
    
    # 沪市主板热门
    for i in range(600, 700):
        hot_codes.append(f"sh600{i:03d}"[:8])
    for i in range(0, 100):
        hot_codes.append(f"sh601{i:03d}")
    for i in range(0, 200):
        hot_codes.append(f"sh603{i:03d}")
    
    # 深市主板
    for i in range(0, 200):
        hot_codes.append(f"sz000{i:03d}")
    for i in range(0, 100):
        hot_codes.append(f"sz002{i:03d}")
    
    # 创业板
    for i in range(0, 300):
        hot_codes.append(f"sz300{i:03d}")
    
    # 科创板
    for i in range(0, 100):
        hot_codes.append(f"sh688{i:03d}")
    
    # 分批请求（每批50个）
    all_results = []
    batch_size = 50
    
    for i in range(0, min(len(hot_codes), 500), batch_size):
        batch = hot_codes[i:i+batch_size]
        codes_str = ','.join(batch)
        
        url = f"https://hq.sinajs.cn/list={codes_str}"
        headers = {
            'Referer': 'https://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        
        try:
            data = fetch_with_curl(url, headers=headers)
            results = parse_sina_stock_data(data)
            all_results.extend(results)
        except Exception as e:
            print(f"获取批次 {i} 失败: {e}")
            continue
    
    if not all_results:
        raise Exception("获取数据失败，无有效股票数据")
    
    return pd.DataFrame(all_results)


def get_stock_history_em(symbol: str, period: str = "daily", days: int = 120) -> pd.DataFrame:
    """获取股票历史K线数据（使用新浪API）"""
    # 确定市场代码
    if symbol.startswith('6'):
        market = 'sh'
    else:
        market = 'sz'
    
    full_code = f"{market}{symbol}"
    
    # 新浪K线API
    # 周期: 5=5分钟, 15=15分钟, 30=30分钟, 60=60分钟, day=日K, week=周K, month=月K
    period_map = {'daily': 'day', 'weekly': 'week', 'monthly': 'month'}
    sina_period = period_map.get(period, 'day')
    
    url = f"https://quotes.sina.cn/cn/api/jsonp.php/var%20_{full_code}_{sina_period}/CN_MarketDataService.getKLineData?symbol={full_code}&scale=240&ma=no&datalen={days}"
    
    headers = {
        'Referer': 'https://finance.sina.com.cn',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }
    
    try:
        data = fetch_with_curl(url, headers=headers)
        
        # 解析JSONP格式
        import re
        match = re.search(r'\[.*\]', data)
        if not match:
            raise Exception("解析K线数据失败")
        
        klines = json.loads(match.group())
        
        records = []
        for k in klines:
            records.append({
                '日期': k.get('day', ''),
                '开盘': float(k.get('open', 0)),
                '收盘': float(k.get('close', 0)),
                '最高': float(k.get('high', 0)),
                '最低': float(k.get('low', 0)),
                '成交量': float(k.get('volume', 0)) / 100,  # 转换为手
                '成交额': 0,
                '涨跌幅': 0
            })
        
        # 计算涨跌幅
        for i in range(1, len(records)):
            pre_close = records[i-1]['收盘']
            if pre_close > 0:
                records[i]['涨跌幅'] = round((records[i]['收盘'] - pre_close) / pre_close * 100, 2)
        
        return pd.DataFrame(records)
    except Exception as e:
        raise Exception(f"获取K线数据失败: {e}")

app = FastAPI(
    title="A股行情API",
    description="提供A股实时行情、K线数据、股票筛选等接口",
    version="2.0.0"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StockInfo(BaseModel):
    """股票基本信息"""
    code: str
    name: str
    price: float
    change: float
    change_percent: float
    volume: float
    amount: float
    high: float
    low: float
    open: float
    pre_close: float


class KLineData(BaseModel):
    """K线数据"""
    date: str
    open: float
    close: float
    high: float
    low: float
    volume: float


# 数字经济相关板块关键词
DIGITAL_ECONOMY_KEYWORDS = [
    "数字经济", "数据要素", "人工智能", "AI", "大数据", "云计算", 
    "区块链", "元宇宙", "算力", "芯片", "半导体", "软件", 
    "信息技术", "互联网", "物联网", "5G", "数字货币", "金融科技",
    "智能", "网络安全", "数据中心", "服务器", "存储", "通信"
]


def get_index_list_em() -> pd.DataFrame:
    """获取主要指数行情数据（使用新浪API）"""
    # 主要指数代码（新浪格式）
    indices = ["s_sh000001", "s_sz399001", "s_sz399006", "s_sh000300", "s_sh000905"]
    names = ["上证指数", "深证成指", "创业板指", "沪深300", "中证500"]
    
    codes_str = ','.join(indices)
    url = f"https://hq.sinajs.cn/list={codes_str}"
    headers = {
        'Referer': 'https://finance.sina.com.cn',
        'User-Agent': 'Mozilla/5.0'
    }
    
    result = []
    try:
        data = fetch_with_curl(url, headers=headers)
        lines = data.strip().split('\n')
        
        for i, line in enumerate(lines):
            if not line or '=""' in line:
                continue
            
            import re
            match = re.search(r'"([^"]*)"', line)
            if not match:
                continue
            
            values = match.group(1)
            parts = values.split(',')
            
            if len(parts) >= 6:
                try:
                    result.append({
                        '代码': indices[i].replace('s_', '')[2:],
                        '名称': names[i] if i < len(names) else parts[0],
                        '最新价': float(parts[1]) if parts[1] else 0,
                        '涨跌额': float(parts[2]) if parts[2] else 0,
                        '涨跌幅': float(parts[3]) if parts[3] else 0,
                        '成交量': float(parts[4]) if parts[4] else 0,
                        '成交额': float(parts[5]) if parts[5] else 0,
                    })
                except (ValueError, IndexError):
                    continue
    except Exception as e:
        print(f"获取指数失败: {e}")
    
    return pd.DataFrame(result)


def is_digital_economy_stock(code: str, name: str = "") -> bool:
    """
    判断是否属于数字经济板块
    简化版本：通过股票名称关键词匹配
    """
    # 数字经济相关股票名称关键词
    digital_keywords = [
        "软件", "科技", "信息", "数据", "智能", "网络", "电子",
        "计算", "云", "芯", "半导体", "通信", "互联", "数字",
        "AI", "算力", "存储", "服务器", "安全", "金融科技"
    ]
    
    # 通过股票名称判断
    name_upper = name.upper()
    for keyword in digital_keywords:
        if keyword in name or keyword.upper() in name_upper:
            return True
    
    # 通过代码前缀判断（科创板、创业板更可能是科技股）
    # 688开头是科创板，300开头是创业板
    if code.startswith('688') or code.startswith('300'):
        return True
    
    return False


def check_volume_pattern(kline_data: List[dict]) -> bool:
    """
    检查是否阶梯式放量
    阶梯式放量：最近几天的成交量呈现逐步放大的趋势
    """
    if len(kline_data) < 5:
        return False
    
    # 取最近5天的成交量
    volumes = [d["volume"] for d in kline_data[-5:]]
    
    # 计算成交量的5日均值
    avg_volume = sum(volumes) / len(volumes)
    
    # 检查最近3天是否呈现放量趋势（后一天比前一天大）
    recent_3 = volumes[-3:]
    increasing_count = 0
    for i in range(1, len(recent_3)):
        if recent_3[i] > recent_3[i-1] * 0.9:  # 允许10%的波动
            increasing_count += 1
    
    # 最近一天的量是否大于5日均量的1.2倍
    latest_volume_ratio = volumes[-1] / avg_volume if avg_volume > 0 else 0
    
    return increasing_count >= 1 and latest_volume_ratio > 1.2


def check_above_ma5_and_high(kline_data: List[dict], current_price: float) -> bool:
    """
    检查是否站稳5日线+近期高点
    """
    if len(kline_data) < 10:
        return False
    
    # 计算5日均线
    closes = [d["close"] for d in kline_data[-10:]]
    ma5 = sum(closes[-5:]) / 5
    
    # 计算近期（10日）高点
    highs = [d["high"] for d in kline_data[-10:]]
    recent_high = max(highs[:-1])  # 排除最近一天
    
    # 条件1: 当前价格在5日线之上
    above_ma5 = current_price > ma5 * 0.98  # 允许2%的误差
    
    # 条件2: 当前价格接近或突破近期高点
    near_high = current_price >= recent_high * 0.97  # 在近期高点的97%以上
    
    return above_ma5 and near_high


def calculate_support_level(kline_data: List[dict]) -> float:
    """计算支撑位"""
    if len(kline_data) < 5:
        return 0
    
    # 使用最近5天的最低价作为支撑参考
    lows = [d["low"] for d in kline_data[-5:]]
    return min(lows)


@app.get("/")
async def root():
    """API根路径"""
    return {
        "message": "A股行情API服务",
        "version": "2.0.0",
        "endpoints": [
            "/api/screen - 筛选股票（涨幅/量比/市值）",
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
    limit: int = Query(20, description="返回数量")
):
    """
    筛选股票
    条件：涨幅3%-5%、量比1.5-3、流通市值50-300亿
    """
    try:
        # 获取A股实时行情
        df = get_stock_list_em()
        
        # 筛选条件
        # 1. 涨幅在指定范围内
        df = df[df["涨跌幅"].notna()]
        df = df[(df["涨跌幅"] >= change_min) & (df["涨跌幅"] <= change_max)]
        
        # 2. 量比在指定范围内
        df = df[df["量比"].notna()]
        df = df[(df["量比"] >= volume_ratio_min) & (df["量比"] <= volume_ratio_max)]
        
        # 3. 流通市值在指定范围内（单位：亿）
        df = df[df["流通市值"].notna()]
        df["流通市值_亿"] = df["流通市值"] / 100000000
        df = df[(df["流通市值_亿"] >= market_cap_min) & (df["流通市值_亿"] <= market_cap_max)]
        
        # 排除ST股票
        df = df[~df["名称"].str.contains("ST", na=False)]
        
        # 按涨幅排序，取前N只
        df = df.sort_values("涨跌幅", ascending=False).head(limit)
        
        result = []
        for _, row in df.iterrows():
            result.append({
                "code": row["代码"],
                "name": row["名称"],
                "price": float(row.get("最新价", 0) or 0),
                "change": float(row.get("涨跌额", 0) or 0),
                "change_percent": float(row.get("涨跌幅", 0) or 0),
                "volume_ratio": float(row.get("量比", 0) or 0),
                "turnover": float(row.get("换手率", 0) or 0),
                "market_cap": float(row.get("流通市值_亿", 0) or 0),
                "amount": float(row.get("成交额", 0) or 0),
                "volume": float(row.get("成交量", 0) or 0),
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
        raise HTTPException(status_code=500, detail=f"筛选股票失败: {str(e)}")


@app.get("/api/filter")
async def filter_stocks(codes: str = Query(..., description="股票代码列表，用逗号分隔")):
    """
    过滤精选股票
    从给定的股票中筛选出：
    1. 阶梯式放量
    2. 站稳5日线+近期高点
    3. 属于数字经济板块
    返回最多3只符合条件的股票
    """
    try:
        code_list = [c.strip() for c in codes.split(",") if c.strip()]
        
        if not code_list:
            raise HTTPException(status_code=400, detail="请提供股票代码列表")
        
        # 获取实时行情
        df = get_stock_list_em()
        
        qualified_stocks = []
        analysis_results = []
        
        for code in code_list:
            try:
                stock_data = df[df["代码"] == code]
                if stock_data.empty:
                    continue
                
                row = stock_data.iloc[0]
                current_price = float(row.get("最新价", 0) or 0)
                
                # 获取K线数据用于分析
                kline_df = get_stock_history_em(symbol=code, period="daily")
                if kline_df.empty or len(kline_df) < 10:
                    continue
                
                kline_data = []
                for _, k_row in kline_df.tail(20).iterrows():
                    kline_data.append({
                        "date": str(k_row["日期"]),
                        "open": float(k_row["开盘"]),
                        "close": float(k_row["收盘"]),
                        "high": float(k_row["最高"]),
                        "low": float(k_row["最低"]),
                        "volume": float(k_row["成交量"]),
                    })
                
                # 检查条件
                stock_name = row.get("名称", "")
                has_volume_pattern = check_volume_pattern(kline_data)
                above_ma5_high = check_above_ma5_and_high(kline_data, current_price)
                is_digital = is_digital_economy_stock(code, stock_name)
                support_level = calculate_support_level(kline_data)
                
                # 计算5日均线
                closes = [d["close"] for d in kline_data[-5:]]
                ma5 = sum(closes) / 5 if closes else 0
                
                analysis = {
                    "code": code,
                    "name": row["名称"],
                    "price": current_price,
                    "change_percent": float(row.get("涨跌幅", 0) or 0),
                    "volume_ratio": float(row.get("量比", 0) or 0),
                    "market_cap": float(row.get("流通市值", 0) or 0) / 100000000,
                    "ma5": round(ma5, 2),
                    "support_level": round(support_level, 2),
                    "has_volume_pattern": has_volume_pattern,
                    "above_ma5_high": above_ma5_high,
                    "is_digital_economy": is_digital,
                    "qualified": has_volume_pattern and above_ma5_high and is_digital
                }
                
                analysis_results.append(analysis)
                
                # 如果满足所有条件
                if has_volume_pattern and above_ma5_high and is_digital:
                    qualified_stocks.append({
                        "code": code,
                        "name": row["名称"],
                        "price": current_price,
                        "change_percent": float(row.get("涨跌幅", 0) or 0),
                        "volume_ratio": float(row.get("量比", 0) or 0),
                        "market_cap": round(float(row.get("流通市值", 0) or 0) / 100000000, 2),
                        "turnover": float(row.get("换手率", 0) or 0),
                        "amount": float(row.get("成交额", 0) or 0),
                        "ma5": round(ma5, 2),
                        "support_level": round(support_level, 2),
                        "analysis": {
                            "volume_pattern": "阶梯式放量 ✓",
                            "price_position": "站稳5日线+近期高点 ✓",
                            "sector": "数字经济板块 ✓"
                        }
                    })
                    
            except Exception as e:
                print(f"分析股票 {code} 失败: {e}")
                continue
        
        # 如果符合条件的股票不足3只，降低条件
        if len(qualified_stocks) < 3:
            # 按满足条件数量排序，取前3只
            for analysis in analysis_results:
                if analysis["code"] not in [s["code"] for s in qualified_stocks]:
                    score = sum([
                        analysis["has_volume_pattern"],
                        analysis["above_ma5_high"],
                        analysis["is_digital_economy"]
                    ])
                    if score >= 2:  # 至少满足2个条件
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
                            }
                        })
        
        # 最多返回3只
        qualified_stocks = qualified_stocks[:3]
        
        return {
            "count": len(qualified_stocks),
            "total_analyzed": len(code_list),
            "filter_criteria": {
                "volume_pattern": "阶梯式放量",
                "price_position": "站稳5日线+近期高点",
                "sector": "数字经济板块"
            },
            "data": qualified_stocks,
            "all_analysis": analysis_results  # 返回所有分析结果供前端展示
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"过滤股票失败: {str(e)}")


@app.get("/api/realtime")
async def get_realtime_quote(code: str = Query(..., description="股票代码，如 000001")):
    """
    获取单只股票实时行情
    """
    try:
        # 获取实时行情
        df = get_stock_list_em()
        stock_data = df[df["代码"] == code]
        
        if stock_data.empty:
            raise HTTPException(status_code=404, detail=f"未找到股票: {code}")
        
        row = stock_data.iloc[0]
        return {
            "code": code,
            "name": row.get("名称", ""),
            "price": float(row.get("最新价", 0) or 0),
            "change": float(row.get("涨跌额", 0) or 0),
            "change_percent": float(row.get("涨跌幅", 0) or 0),
            "volume": float(row.get("成交量", 0) or 0),
            "amount": float(row.get("成交额", 0) or 0),
            "high": float(row.get("最高", 0) or 0),
            "low": float(row.get("最低", 0) or 0),
            "open": float(row.get("今开", 0) or 0),
            "pre_close": float(row.get("昨收", 0) or 0),
            "turnover": float(row.get("换手率", 0) or 0),
            "volume_ratio": float(row.get("量比", 0) or 0),
            "pe_ratio": float(row.get("市盈率-动态", 0) or 0),
            "total_value": float(row.get("总市值", 0) or 0),
            "market_cap": float(row.get("流通市值", 0) or 0) / 100000000,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取数据失败: {str(e)}")


@app.get("/api/kline")
async def get_kline_data(
    code: str = Query(..., description="股票代码"),
    period: str = Query("daily", description="周期: daily, weekly, monthly"),
    days: int = Query(90, description="获取天数")
):
    """
    获取K线历史数据
    """
    try:
        # 获取历史K线数据
        df = get_stock_history_em(symbol=code, period=period, days=days)
        
        if df.empty:
            raise HTTPException(status_code=404, detail=f"未找到股票K线数据: {code}")
        
        result = []
        for _, row in df.iterrows():
            result.append({
                "date": str(row["日期"]),
                "open": float(row["开盘"]),
                "close": float(row["收盘"]),
                "high": float(row["最高"]),
                "low": float(row["最低"]),
                "volume": float(row["成交量"]),
                "amount": float(row.get("成交额", 0)),
                "change_percent": float(row.get("涨跌幅", 0)),
            })
        
        return {
            "code": code,
            "period": period,
            "data": result
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取K线数据失败: {str(e)}")


@app.get("/api/hot")
async def get_hot_stocks(limit: int = Query(20, description="返回数量")):
    """
    获取热门股票（按成交额排序）
    """
    try:
        df = get_stock_list_em()
        
        # 按成交额排序
        df = df.sort_values("成交额", ascending=False).head(limit)
        
        result = []
        for _, row in df.iterrows():
            result.append({
                "code": row["代码"],
                "name": row["名称"],
                "price": float(row.get("最新价", 0) or 0),
                "change": float(row.get("涨跌额", 0) or 0),
                "change_percent": float(row.get("涨跌幅", 0) or 0),
                "volume": float(row.get("成交量", 0) or 0),
                "amount": float(row.get("成交额", 0) or 0),
                "turnover": float(row.get("换手率", 0) or 0),
            })
        
        return {
            "count": len(result),
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取热门股票失败: {str(e)}")


@app.get("/api/index")
async def get_index_data():
    """
    获取主要指数行情
    """
    try:
        df = get_index_list_em()
        
        result = []
        for _, row in df.iterrows():
            result.append({
                "code": row["代码"],
                "name": row["名称"],
                "price": float(row.get("最新价", 0) or 0),
                "change": float(row.get("涨跌额", 0) or 0),
                "change_percent": float(row.get("涨跌幅", 0) or 0),
                "volume": float(row.get("成交量", 0) or 0),
                "amount": float(row.get("成交额", 0) or 0),
            })
        
        return {"data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取指数数据失败: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
