import streamlit as st
import json
import time
import base64
import requests
from datetime import datetime, timedelta
from google import genai
from google.genai import types

# ==========================================
# 0. 页面基本配置
# ==========================================
st.set_page_config(page_title="AI 跨境饰品选品引擎", page_icon="💎", layout="wide")
st.title("💎 跨境平价饰品 AI 智能选品引擎")
st.markdown("基于多维数据加权与大模型语意分析的 TikTok Shop 爆款挖掘机")

# ==========================================
# 1. 凭证与初始化
# ==========================================
try:
    # 检查并初始化 Gemini API
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # 检查并初始化 EchoTik 凭证
    ECHOTIK_ACCOUNT = st.secrets["echotik"]["account"]
    ECHOTIK_API_KEY = st.secrets["echotik"]["api_key"]
except KeyError as e:
    st.error(f"⚠️ 缺少必要的密钥配置: {e}。请检查 Streamlit 后台的 Secrets 设置。")
    st.stop()

# ==========================================
# 2. 核心类目映射字典
# ==========================================
CATEGORY_MAP = {
    "耳环": "605268",
    "脚链": "605272",
    "戒指": "605273",
    "手环与手链": "605274",
    "项链": "605280",
    "首饰吊件及装饰": "907400",
    "身体饰品": "907528",
    "钥匙扣": "907656",
    "首饰套装": "907784",
    "珠宝调节保护工具": "995080"
}

# ==========================================
# 3. 真实数据拉取模块 (已修复缓存重放错误)
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_real_echotik_products(region_code, l3_category_id, item_limit):
    """
    调用 EchoTik V3 榜单接口。
    注意：为了避免 CacheReplayClosureError，本函数内部不包含任何 st. 命令。
    """
    api_url = "https://open.echotik.live/api/v3/echotik/product/ranklist"
    
    # 1. 构造鉴权 (Basic Auth)
    auth_str = f"{ECHOTIK_ACCOUNT}:{ECHOTIK_API_KEY}"
    b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/json"
    }
    
    # 2. 自动计算“上周一”日期
    today = datetime.now()
    days_to_subtract = today.weekday() + 7 
    last_monday_str = (today - timedelta(days=days_to_subtract)).strftime("%Y-%m-%d")

    # 3. 构建请求参数
    params = {
        "date": last_monday_str,
        "region": region_code,
        "category_id": "605248",       # 一级：时尚配件
        "category_l2_id": "905608",    # 二级：平价饰品
        "category_l3_id": l3_category_id,
        "product_rank_field": 1,       # 按销量排序
        "rank_type": 2,                # 周榜
        "page_num": 1,
        "page_size": 1
    }

    try:
        response = requests.get(api_url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        resp_json = response.json()
        
        if resp_json.get("code") != 0:
            return None # 异常时返回 None
            
        raw_data = resp_json.get("data", [])
        
        # 4. 数据清洗
        cleaned_products = []
        for item in raw_data:
            cleaned_products.append({
                "id": item.get("product_id"),
                "original_title": item.get("product_name", "未知商品"),
                "price_local": item.get("spu_avg_price", 0),
                "sales_growth_7d": item.get("total_sale_cnt", 0),
                "new_creators_7d": item.get("total_lfl_cnt", 0),
                "engagement_rate": min(item.get("total_video_cnt", 0) / 100.0, 1.0), 
                "profit_margin_est": 0.45, 
                "reviews": ["Good quality", "Fast delivery"], 
                "image_url": item.get("cover_url", "https://placehold.co/150x150?text=Hot+Item") 
            })
        return cleaned_products

    except Exception:
        return None

# ==========================================
# 4. AI 分析模块 (升级至 Gemini 2.0-Flash)
# ==========================================
@st.cache_data(show_spinner=False)
def analyze_product_with_ai(original_title, reviews, target_country):
    prompt = f"""
    你是一个专业的 TikTok Shop (国家：{target_country}) 跨境电商选品专家。
    请分析以下商品信息：
    - 商品原名：{original_title}
    - 客户评价片段：{', '.join(reviews)}

    请以严格的 JSON 格式输出，包含以下字段：
    {{"cn_name": "中文商品名称", "selling_points": "3个核心售卖关键词(逗号分隔)", "pain_points": "1个客户痛点", "compliance_warning": "合规提示或填'无'"}}
    """
    try:
        response = client.models.generate_content(
            # 使用最新的 2.0-flash 模型，避免 404 错误
            # model='gemini-2.0-flash', 
            # 退回 1.5 版本，免费额度最稳
            model='gemini-1.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        return json.loads(response.text)
    except Exception as e:
        return {"cn_name": "AI 分析不可用", "selling_points": "-", "pain_points": "-", "compliance_warning": str(e)}

# ==========================================
# 5. 侧边栏与打分控制
# ==========================================
with st.sidebar:
    st.header("⚙️ 选品参数设置")
    
    target_country_raw = st.selectbox("目标市场", ["泰国 (TH)", "越南 (VN)", "菲律宾 (PH)", "美国 (US)"])
    region_code = target_country_raw.split("(")[1].replace(")", "")
    
    selected_l3_name = st.selectbox("细分类目", list(CATEGORY_MAP.keys()))
    selected_l3_id = CATEGORY_MAP[selected_l3_name]
    
    item_limit = st.select_slider("拉取商品数量", options=[5, 10, 20, 30], value=10)
    
    st.markdown("---")
    st.header("🧮 潜力打分权重设置")
    w_growth = st.slider("近7天销量增速", 0, 100, 40)
    w_creators = st.slider("新增达人/视频", 0, 100, 30)
    w_engagement = st.slider("视频平均互动率", 0, 100, 20)
    w_margin = st.slider("预计利润空间", 0, 100, 10)

def calculate_score(p):
    score = (p["sales_growth_7d"]/1000 * w_growth) + (p["new_creators_7d"]/30 * w_creators) + (p["engagement_rate"]/0.15 * w_engagement) + (p["profit_margin_est"] * w_margin)
    return round(score, 1)

# ==========================================
# 6. 主面板交互逻辑
# ==========================================
if st.button("🚀 开始 AI 智能选品引擎", type="primary", use_container_width=True):
    # 1. 数据拉取阶段
    with st.spinner(f'📡 正在拉取【{target_country_raw} - {selected_l3_name}】大盘真实数据...'):
        products = fetch_real_echotik_products(region_code, selected_l3_id, item_limit)
        
        if products is None or len(products) == 0:
            st.warning("⚠️ 未能拉取到有效数据。可能原因：该类目上周无排行、日期不匹配或 API 限制。")
            st.stop()
        else:
            st.toast("✅ 数据抓取成功！正在转交 AI 进行深度分析...", icon="✅")
    
    # 2. AI 分析阶段
    analyzed_data = []
    progress_text = "🧠 正在调用 Gemini 2.0 模型分析商品潜力..."
    my_bar = st.progress(0, text=progress_text)
    
    for idx, p in enumerate(products):
        ai_result = analyze_product_with_ai(p["original_title"], p["reviews"], target_country_raw)
        full_p = {**p, **ai_result}
        full_p["score"] = calculate_score(full_p)
        analyzed_data.append(full_p)
        my_bar.progress((idx + 1) / len(products), text=f"分析进度: {idx + 1}/{len(products)}")

        # 🚦 核心修复：每次分析完停顿 4 秒，完美绕过免费版 API 的并发限制
        if idx < len(products) - 1:
            time.sleep(4)
            
    my_bar.empty()
    
    # 3. 排序与渲染
    analyzed_data.sort(key=lambda x: x["score"], reverse=True)
    st.success(f"✅ 选品分析完成！已为您生成【{selected_l3_name}】潜力排行榜：")
    
    for idx, item in enumerate(analyzed_data):
        with st.container(border=True):
            col1, col2, col3 = st.columns([1, 3, 2])
            
            with col1:
                st.image(item["image_url"], use_container_width=True)
                st.metric(label="🏆 综合潜力分", value=item["score"])
                
            with col2:
                st.subheader(f"Top {idx+1}: {item['cn_name']}")
                st.caption(f"原文: {item['original_title']} (ID: {item['id']})")
                st.markdown(f"**🏷️ 核心卖点:** {item['selling_points']}")
                st.markdown(f"**🩸 客户痛点:** {item['pain_points']}")
                if "无" not in item['compliance_warning'] and "AI 分析出错" not in item['cn_name']:
                    st.error(f"**⚠️ 合规警告:** {item['compliance_warning']}")
                else:
                    st.success("**✅ 合规筛查:** 暂无明显风险")
            
            with col3:
                st.markdown("📊 **数据表现**")
                st.write(f"💰 均价: **{item['price_local']}** (当地货币)")
                st.write(f"📈 7天销量: **{item['sales_growth_7d']}**")
                st.write(f"👥 关联达人数: **{item['new_creators_7d']}**")
                st.write(f"💵 预估利润率: **{item['profit_margin_est']*100}%**")
                st.link_button("🔍 去 1688 找货源", "https://s.1688.com/", use_container_width=True)
