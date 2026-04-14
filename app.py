import base64
import requests
from datetime import datetime, timedelta

# ==========================================
# 2. 真实数据拉取模块 (精准对接 EchoTik V3 榜单)
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_real_echotik_products(target_country, item_limit):
    """
    调用 EchoTik V3 榜单接口，拉取真实爆款数据
    """
    api_url = "https://open.echotik.live/api/v3/echotik/product/ranklist"
    
    # 1. 处理鉴权 (Basic Auth Base64 加密)
    # 将 "账号:密码" 拼接并转码
    auth_str = f"{ECHOTIK_ACCOUNT}:{ECHOTIK_API_KEY}"
    b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    
    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/json"
    }
    
    # 2. 动态获取日期 (取昨天的数据，确保大盘已更新)
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    # 从侧边栏提取国家代码 (如 "泰国 (TH)" -> "TH")
    region_code = target_country.split("(")[1].replace(")", "")
    
    # 3. 构建请求参数
    params = {
        "date": yesterday_str,
        "region": region_code,
        # "category_id": "填入你查到的一级类目ID", 
        # "category_l2_id": "填入你查到的二级类目ID(饰品)", 
        "product_rank_field": 1, # 1代表按销量排序
        "rank_type": 2,          # 2代表周榜 (刚好对应我们权重的近7天销量)
        "page_num": 1,
        "page_size": item_limit
    }

    try:
        # 发送 GET 请求 (注意文档写的是 GET，参数用 params 传)
        response = requests.get(api_url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        
        # 解析返回的 JSON 数据
        resp_json = response.json()
        if resp_json.get("code") != 0:
            st.error(f"EchoTik 接口报错: {resp_json.get('message')}")
            return []
            
        raw_data = resp_json.get("data", [])
        
        # 4. 数据清洗与打分引擎字段映射
        cleaned_products = []
        for item in raw_data:
            cleaned_products.append({
                "id": item.get("product_id"),
                "original_title": item.get("product_name", "未知商品"),
                "price_thb": item.get("spu_avg_price", 0),
                "sales_growth_7d": item.get("total_sale_cnt", 0), # 周榜总销量
                "new_creators_7d": item.get("total_lfl_cnt", 0),  # 关联达人数
                # 暂时用 视频数/100 模拟一个互动率，后续可对接真实互动接口
                "engagement_rate": min(item.get("total_video_cnt", 0) / 100.0, 1.0), 
                "profit_margin_est": 0.45, # 默认预估利润 45%，后续对接 1688 接口替换
                "reviews": ["Good quality", "Beautiful", "Recommend"], # 暂用占位符，需再调评论接口
                # 榜单接口如果没返回主图，先用占位图兜底
                "image_url": item.get("cover_url", "https://placehold.co/150?text=No+Image") 
            })
            
        return cleaned_products

    except requests.exceptions.RequestException as e:
        st.error(f"🚨 请求异常，请检查网络或 API 密钥: {e}")
        return []
