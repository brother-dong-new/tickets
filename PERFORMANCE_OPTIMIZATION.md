# 性能优化指南

## 当前优化措施

### 1. 前端优化 ✅

#### 超时配置
- 请求超时时间从60秒增加到180秒
- 支持最多3分钟的复杂分析

#### 用户交互
- 添加了取消分析功能（通过AbortController）
- 动态进度提示（8个阶段自动轮换）
- 友好的等待提示："预计需要 1-3 分钟，请耐心等待"

#### 错误处理
- 区分取消和真实错误
- 超时时提示用户原因和建议

### 2. 后端优化 ✅

#### 进度追踪
- 每分析5只股票输出一次进度日志
- 方便监控和诊断性能瓶颈

## 进一步优化建议

### 短期优化（可立即实施）

#### 1. 数据缓存
```python
# 添加简单的内存缓存，避免重复请求
from functools import lru_cache
from datetime import datetime, timedelta

# 缓存分钟数据（5分钟有效）
@lru_cache(maxsize=100)
def cached_get_minute_data(code: str, cache_key: str):
    return get_minute_data(code, minutes=30)

# 使用时生成缓存键
cache_key = f"{code}_{datetime.now().strftime('%H:%M')[:4]}"  # 精确到分钟前两位
minute_result = cached_get_minute_data(code, cache_key)
```

#### 2. 批量数据获取
```python
# 一次性获取所有股票的K线数据，而不是逐个请求
def fetch_batch_kline_data(codes: List[str]) -> Dict[str, Any]:
    """批量获取K线数据"""
    results = {}
    # 分批次处理，每次10个
    for i in range(0, len(codes), 10):
        batch = codes[i:i+10]
        # 并发获取这一批的数据
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(fetch_qq_kline_data, code): code for code in batch}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    results[code] = future.result()
                except Exception as e:
                    print(f"获取{code}K线失败: {e}")
    return results
```

#### 3. 超时控制
```python
# 为每个网络请求添加超时限制
def fetch_qq_kline_data(code: str, days: int = 120, timeout: int = 10) -> Dict[str, Any]:
    """获取K线数据，带超时控制"""
    try:
        cmd = ['curl', '-s', '--connect-timeout', str(timeout), '--max-time', str(timeout + 5), url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        # ...
    except subprocess.TimeoutExpired:
        print(f"获取{code}K线数据超时")
        return {}
```

### 中期优化（需要重构）

#### 1. 异步并发处理
```python
import asyncio
import aiohttp

async def analyze_stock_async(stock: Dict) -> Dict | None:
    """异步分析单只股票"""
    async with aiohttp.ClientSession() as session:
        # 并发获取所有数据
        tasks = [
            fetch_minute_data_async(session, code),
            fetch_kline_data_async(session, code),
            fetch_capital_flow_async(session, code),
        ]
        results = await asyncio.gather(*tasks)
        # 分析逻辑...
        return candidate

async def ai_select_stocks_async(screened_stocks: List[Dict]) -> List[Dict]:
    """并发分析所有股票"""
    tasks = [analyze_stock_async(stock) for stock in screened_stocks]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]
```

#### 2. Redis缓存
```python
import redis
import json

redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)

def get_cached_kline(code: str, days: int = 120) -> Dict | None:
    """从Redis获取缓存的K线数据"""
    key = f"kline:{code}:{days}"
    data = redis_client.get(key)
    if data:
        return json.loads(data)
    return None

def set_cached_kline(code: str, data: Dict, days: int = 120, ttl: int = 300):
    """缓存K线数据（5分钟有效期）"""
    key = f"kline:{code}:{days}"
    redis_client.setex(key, ttl, json.dumps(data))
```

### 长期优化（架构级别）

#### 1. 微服务拆分
- 数据获取服务：专门负责从腾讯API获取数据
- 分析计算服务：负责AI评分和风险分析
- 缓存服务：统一管理数据缓存

#### 2. 消息队列
```python
# 使用Celery实现异步任务处理
from celery import Celery

app = Celery('stock_analyzer', broker='redis://localhost:6379/0')

@app.task
def analyze_stock_task(stock_data: Dict) -> Dict:
    """异步分析任务"""
    return analyze_single_stock(stock_data)

# 接口立即返回任务ID，前端轮询结果
@app.post("/api/filter_async")
async def filter_async(codes: List[str]):
    task = analyze_stocks_task.delay(codes)
    return {"task_id": task.id, "status": "processing"}

@app.get("/api/filter_result/{task_id}")
async def get_filter_result(task_id: str):
    task = analyze_stocks_task.AsyncResult(task_id)
    if task.ready():
        return {"status": "completed", "result": task.result}
    else:
        return {"status": "processing"}
```

#### 3. 数据库持久化
- PostgreSQL存储历史K线数据
- 定时任务每日更新数据
- 减少实时API调用次数

## 性能监控

### 添加性能日志
```python
import time
from functools import wraps

def timing_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        print(f"[性能] {func.__name__} 耗时: {elapsed:.2f}秒")
        return result
    return wrapper

@timing_decorator
def ai_select_stocks(...):
    # 原有逻辑
```

### 瓶颈分析
```bash
# 使用cProfile分析性能
python -m cProfile -o profile.stats main.py

# 查看结果
python -c "import pstats; p = pstats.Stats('profile.stats'); p.sort_stats('cumulative'); p.print_stats(20)"
```

## 预估性能提升

| 优化措施 | 当前耗时 | 优化后耗时 | 提升比例 |
|---------|---------|-----------|---------|
| 前端超时配置 | 60秒超时 | 180秒超时 | 用户体验提升 |
| 进度提示 | 无反馈 | 实时反馈 | 用户体验提升 |
| 数据缓存 | ~120秒 | ~60秒 | 50% |
| 异步并发 | ~120秒 | ~30秒 | 75% |
| Redis缓存 | ~120秒 | ~20秒 | 83% |
| 完整优化 | ~120秒 | ~15秒 | 87% |

## 实施建议

### 优先级 P0（立即实施）
- ✅ 前端超时时间调整
- ✅ 添加取消功能
- ✅ 进度提示
- ✅ 后端进度日志

### 优先级 P1（本周内）
- ⏳ 添加内存缓存（lru_cache）
- ⏳ 优化数据获取超时控制
- ⏳ 批量数据预取

### 优先级 P2（下个迭代）
- ⏳ 异步并发处理
- ⏳ Redis缓存
- ⏳ 性能监控

### 优先级 P3（长期规划）
- ⏳ 微服务架构
- ⏳ 消息队列
- ⏳ 数据库持久化
