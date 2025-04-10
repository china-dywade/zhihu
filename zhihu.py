import requests
import json
from bs4 import BeautifulSoup
import time
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging
import random
import http.client
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class HotItem(BaseModel):
    rank: int
    title: str
    link: str
    hot_degree: str
    update_time: str

class ZhihuHotMonitor:
    def __init__(self):
        self.cached_hot_list: List[HotItem] = []
        self.last_update_time: str = ""
        self.headers = {
            'User-Agent': random.choice([
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15'
            ]),
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'x-api-version': '3.0.91'
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        
        # 设置基础 cookies
        self.session.cookies.update({
            '_zap': ''.join(random.choices('0123456789abcdef', k=32)),
            'KLBRSID': ''.join(random.choices('0123456789abcdef', k=32)),
            'd_c0': '"' + ''.join(random.choices('0123456789abcdef', k=32)) + '==|' + str(int(time.time())) + '"',
        })

    def format_hot_degree(self, target):
        """格式化热度值"""
        try:
            if isinstance(target, dict):
                metrics_area = target.get('metrics_area', {})
                if isinstance(metrics_area, dict):
                    return metrics_area.get('text', '热度未知')
            return "热度未知"
        except Exception as e:
            logging.error(f"格式化热度值失败: {str(e)}")
            return "热度未知"

    async def get_hot_list(self) -> List[HotItem]:
        try:
            # 获取 CSRF Token
            logging.debug("正在获取 CSRF Token...")
            response = self.session.get("https://www.zhihu.com/api/v3/oauth/captcha?lang=en", timeout=10)
            if response.status_code == 200:
                self.session.cookies.update({
                    '_xsrf': response.cookies.get('_xsrf', '')
                })
            
            # 访问热榜
            logging.debug("正在访问知乎热榜...")
            api_url = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=50&desktop=true"
            
            response = self.session.get(api_url, timeout=10)
            response.raise_for_status()
            
            logging.debug(f"热榜 API 状态码: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    hot_items = []
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    if 'data' in data:
                        logging.debug(f"找到 {len(data['data'])} 条热榜数据")
                        for idx, item in enumerate(data['data'], 1):
                            try:
                                target = item.get('target', {})
                                
                                # 获取标题
                                title_area = target.get('title_area', {})
                                title = title_area.get('text', '')
                                
                                # 获取链接
                                card_id = item.get('card_id', '')
                                if card_id.startswith('Q_'):
                                    question_id = card_id[2:]
                                    url = f"https://www.zhihu.com/question/{question_id}"
                                else:
                                    url = ''
                                
                                # 获取热度
                                hot_degree = self.format_hot_degree(target)
                                
                                if title and url:
                                    hot_items.append(HotItem(
                                        rank=idx,
                                        title=title,
                                        link=url,
                                        hot_degree=hot_degree,
                                        update_time=current_time
                                    ))
                            except Exception as e:
                                logging.error(f"处理第 {idx} 条热榜数据时出错: {str(e)}")
                                logging.debug("错误详情:", exc_info=True)
                                continue
                        
                        if hot_items:
                            logging.info(f"成功获取到 {len(hot_items)} 条热榜内容")
                            self.cached_hot_list = hot_items
                            self.last_update_time = current_time
                            return hot_items
                        else:
                            raise HTTPException(status_code=500, detail="未能解析出任何热榜内容")
                    else:
                        raise HTTPException(status_code=500, detail="API 响应中没有 data 字段")
                except json.JSONDecodeError as e:
                    raise HTTPException(status_code=500, detail=f"解析 JSON 响应失败: {str(e)}")
            else:
                raise HTTPException(status_code=response.status_code, detail="知乎 API 请求失败")
            
        except requests.Timeout:
            raise HTTPException(status_code=504, detail="请求超时")
        except requests.RequestException as e:
            raise HTTPException(status_code=500, detail=f"请求失败: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"获取知乎热榜失败: {str(e)}")

app = FastAPI(
    title="知乎热榜 API",
    description="获取知乎实时热榜数据的 API 服务",
    version="1.0.0"
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

monitor = ZhihuHotMonitor()

# 创建调度器
scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup_event():
    """应用启动时初始化数据并启动调度器"""
    # 首次获取数据
    await monitor.get_hot_list()
    # 添加定时任务，每5分钟执行一次
    scheduler.add_job(monitor.get_hot_list, 'interval', minutes=5)
    # 启动调度器
    scheduler.start()

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时关闭调度器"""
    scheduler.shutdown()

@app.get("/", response_model=List[HotItem])
async def get_hot_list():
    """获取知乎实时热榜"""
    if not monitor.cached_hot_list:
        return await monitor.get_hot_list()
    return monitor.cached_hot_list

@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "last_update": monitor.last_update_time
    }
