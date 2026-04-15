import streamlit as st
import json
import time
import base64
import requests
import urllib.parse
from datetime import datetime, timedelta

# ==========================================
# 0. 页面基本配置
# ==========================================
st.set_page_config(page_title="AI 跨境饰品选品引擎", page_icon="💎", layout="wide")
st.title("💎 跨境平价饰品 AI 智能选品引擎 (全能升级版)")
st.markdown("基于多维数据加权与 90 天趋势预测的 TikTok Shop 深度选品工具")

# ==========================================
# 1. 凭证与初始化
# ==========================================
try:
    OPENROUTER_API_KEY = st.secrets["OPENROUTER_API_KEY"]
    ECHOTIK_ACCOUNT = st.secrets["echotik"]["account"]
    ECHOTIK_API_KEY = st.secrets["echotik"]["api_key"]
except KeyError as e:
    st.error(f"⚠️ 密钥配置不全: {e}。请检查 Secrets。")
    st.stop()

# ==========================================
# 2. 常量配置 (汇率、类目、市场)
# ==========================================
CATEGORY_MAP = {
    "耳环": "605268", "脚链": "605272", "戒指": "605273", 
    "手环与手链": "605274", "项链": "605280", "首饰吊件及装饰": "907400",
    "身体饰品": "907528", "钥匙扣": "907656", "首饰套装": "907784", 
    "珠宝调节保护工具": "995080"
}

MARKET_CONFIG = {
    "泰国 (TH)": {"code": "TH", "rate": 36.5, "sym": "฿"},
    "越南 (VN)": {"code": "VN", "rate": 25400, "sym": "₫"},
    "菲律宾 (PH)": {"code": "PH", "rate": 58.5, "sym": "₱"},
    "马来西亚 (MY)": {"code": "MY", "rate": 4.7, "sym": "RM"},
    "新加坡 (SG)": {"code": "SG", "rate": 1.35, "sym": "S$"},
    "美国 (US)": {"code": "US", "rate": 1.0, "sym": "$"},
    "印尼 (ID)": {"code": "ID", "rate": 16000, "sym": "Rp"}
}

# ==========================================
# 3. 数据拉取核心函数
# ==========================================

def get_auth_headers():
    auth_str = f"{ECHOTIK_ACCOUNT}:{ECHOTIK_API_KEY}"
    b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    return {"Authorization": f"Basic {b64_auth}", "Content-Type": "application/json"}

@st.cache_data(ttl=3600)
def fetch_products(region, l3_id, rank_type, limit):
    """
    1. 获取榜单基础数据
    """
    api_url = "https://open.echotik.live/api/v3/echotik/product/ranklist"
    today = datetime.now()
    
    # 周期日期计算逻辑
    if rank_type == 1: # 日榜
        target_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    elif rank_type == 2: # 周榜
        target_date = (today - timedelta(days=today.weekday() + 7)).strftime("%Y-%m-%d")
    else: # 月榜
        target_date = today.replace(day=1).strftime("%Y-%m-%d")

    params = {
        "date": target_date, "region": region, "category_id": "605248",
        "category_l2_id": "905608", "category_l3_id": l3_id,
        "product_rank_field": 1, "rank_type": rank_type,
        "page_num": 1, "page_size": limit
    }
    
    try:
        res = requests.get(api_url, headers=get_auth_headers(), params=params, timeout=15).json()
        return res.get("data", [])
    except: return []

def fetch_potential_index(product_id):
    """
    2. 获取近90天趋势并判断潜力
    """
    api_url = "https://open.echotik.live/api/v3/echotik/product/trend"
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    
    params = {"product_id": product_id, "start_date": start_date, "end_date": end_date}
    try:
        res = requests.get(api_url, headers=get_auth_headers(), params=params, timeout=10).json()
        trends = res.get("data", [])
        if len(trends) < 2: return "数据不足", 0
        
        # 简单算法：最近10天销量均值 vs 前80天均值
        recent = sum(t.get("total_sale_cnt", 0) for t in trends[:10]) / 10
        history = sum(t.get("total_sale_cnt", 0) for t in trends[10:]) / (len(trends)-10)
        
        if recent > history * 1.2: return "🔥 显著上升", recent
        elif recent < history * 0.8: return "📉 正在下降", recent
        else: return "➡️ 趋势平稳", recent
    except: return "计算失败", 0

def fetch_product_videos(product_id):
    """
    3. 获取关联视频列表
    """
    api_url = "https://open.echotik.live/api/v3/echotik/product/video"
    params = {"product_id": product_id, "page_size": 3} # 只取前3个做参考
    try:
        res = requests.get(api_url, headers=get_auth_headers(), params=params, timeout=10).json()
        return res.get("data", [])
    except: return []

# ==========================================
# 4. AI 分析模块 (OpenRouter)
# ==========================================
def analyze_with_ai(title, region):
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "google/gemini-2.0-flash-001",
        "messages": [{"role": "user", "content": f"分析TikTok商品：{title}。市场：{region}。以JSON输出：cn_name(中文名), selling_points(3个卖点), pain_points(1个痛点)。"}]
    }
    try:
        res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=20).json()
        content = res["choices"][0]["message"]["content"]
        # 清洗 Markdown
        clean_json = content.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except:
        return {"cn_name": "解析失败", "selling_points": "-", "pain_points": "-"}

# ==========================================
# 5. 侧边栏
# ==========================================
with st.sidebar:
    st.header("⚙️ 选品参数设置")
    market_label = st.selectbox("目标市场", list(MARKET_CONFIG.keys()))
    m_info = MARKET_CONFIG[market_label]
    
    period_label = st.selectbox("筛选周期", ["日榜", "周榜", "月榜"])
    rank_type = {"日榜":1, "周榜":2, "月榜":3}[period_label]
    
    l3_name = st.selectbox("细分类目", list(CATEGORY_MAP.keys()))
    l3_id = CATEGORY_MAP[l3_name]
    
    limit = st.select_slider("拉取数量", options=[5, 10, 15], value=5)

# ==========================================
# 6. 主逻辑渲染
# ==========================================
if st.button("🚀 开始 AI 智能选品引擎", type="primary", use_container_width=True):
    raw_products = fetch_products(m_info["code"], l3_id, rank_type, limit)
    
    if not raw_products:
        st.warning("未能拉取到数据，请更换周期或市场尝试。")
        st.stop()

    for idx, p in enumerate(raw_products):
        p_id = p.get("product_id")
        
        # 深度数据获取
        with st.status(f"正在深度分析第 {idx+1} 个商品: {p.get('product_name')[:20]}...", expanded=False):
            ai_res = analyze_with_ai(p.get("product_name"), market_label)
            p_trend, recent_avg = fetch_potential_index(p_id)
            videos = fetch_product_videos(p_id)
            time.sleep(0.5)

        # 渲染卡片 (无图片布局)
        with st.container(border=True):
            col1, col2 = st.columns([3, 2])
            
            with col1:
                st.subheader(f"Top {idx+1}: {ai_res['cn_name']}")
                st.caption(f"原始名称: {p.get('product_name')} (ID: {p_id})")
                st.write(f"🏷️ **核心卖点**: {ai_res['selling_points']}")
                st.write(f"🩸 **客户痛点**: {ai_res['pain_points']}")
                
                # 潜力指数展示
                st.info(f"🔮 **潜力预测 (90天)**: {p_trend}")
            
            with col2:
                st.markdown("📊 **核心数据 (EchoTik USD 转换)**")
                local_price = round(p.get("spu_avg_price", 0) * m_info["rate"], 2)
                st.write(f"💰 均价: **{local_price} {m_info['sym']}** (参考: ${p.get('spu_avg_price')} USD)")
                st.write(f"📈 周期销量: **{p.get('total_sale_cnt')}**")
                st.write(f"👥 关联达人数: **{p.get('total_lfl_cnt')}**")
                st.write(f"🎥 关联视频数: **{p.get('total_video_cnt')}**")
                
                # 视频列表链接展示
                if videos:
                    with st.expander("查看关联带货视频链接"):
                        for v in videos:
                            st.markdown(f"- [点击查看视频素材]({v.get('video_url', '#')}) (播放: {v.get('total_view_cnt', 0)})")
                else:
                    st.caption("暂无视频链接数据")

            # 底部操作栏
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                echotik_url = f"https://echotik.live/products/{p_id}"
                st.link_button("🔗 在 EchoTik 查看详情(含图)", echotik_url, use_container_width=True)
            
            with btn_col2:
                # 1688 乱码修复逻辑
                # 使用 utf-8 编码关键词。如果 1688 仍然显示乱码，尝试更换搜索入口
                kw = ai_res['cn_name'] if ai_res['cn_name'] != "解析失败" else p.get('product_name')
                encoded_kw = urllib.parse.quote(kw)
                search_1688 = f"https://s.1688.com/selloffer/offer_search.htm?keywords={encoded_kw}"
                st.link_button("🛒 1688 搜同款 (已修复乱码)", search_1688, use_container_width=True)
