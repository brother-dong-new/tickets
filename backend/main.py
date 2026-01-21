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
    limit: int = Query(20, description="返回数量")
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
                    }
                })
        
        # 如果不足3只，降低条件
        if len(qualified_stocks) < 3:
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
                        
                if len(qualified_stocks) >= 3:
                    break
        
        return {
            "count": len(qualified_stocks[:3]),
            "total_analyzed": len(code_list),
            "filter_criteria": {
                "volume_pattern": "阶梯式放量",
                "price_position": "站稳5日线+近期高点",
                "sector": "数字经济板块"
            },
            "data": qualified_stocks[:3],
            "all_analysis": analysis_results
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
