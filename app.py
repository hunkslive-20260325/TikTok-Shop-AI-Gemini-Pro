import streamlit as st
import json
import google.generativeai as genai
import pandas as pd
import time

# ==========================================
# 0. 页面基本配置
# ==========================================
st.set_page_config(page_title="AI 跨境饰品选品引擎", page_icon="💎", layout="wide")
st.title("💎 跨境平价饰品 AI 智能选品引擎")
st.markdown("基于多维数据加权与大模型语意分析的 TikTok Shop 爆款挖掘机")

# ==========================================
# 1. 凭证与初始化
# ==========================================
# 安全读取 Secrets
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
except KeyError:
    st.error("⚠️ 未检测到 Gemini API Key。请在 Streamlit 后台的 Secrets 中配置 `GEMINI_API_KEY`。")
    st.stop()

# ==========================================
# 2. 模拟数据获取 (替代真实 EchoTik API)
# ==========================================
def get_mock_products(limit):
    """这里使用模拟数据以便演示。实际对接时替换为 EchoTik API 请求"""
    return [
        {
            "id": "p101", "original_title": "สร้อยคอไข่มุกแฟชั่นสไตล์เกาหลี 2024", "price_thb": 120,
            "sales_growth_7d": 850, "new_creators_7d": 15, "engagement_rate": 0.08, "profit_margin_est": 0.50,
            "reviews": ["สวยมาก", "ส่งไว", "แพ้คันนิดหน่อย"], "image_url": "https://placehold.co/150x150?text=Pearl+Necklace"
        },
        {
            "id": "p102", "original_title": "แหวนเพชร CZ มินิมอล", "price_thb": 85,
            "sales_growth_7d": 420, "new_creators_7d": 5, "engagement_rate": 0.04, "profit_margin_est": 0.65,
            "reviews": ["น่ารักดี", "เล็กไปหน่อย"], "image_url": "https://placehold.co/150x150?text=Minimal+Ring"
        },
        {
            "id": "p103", "original_title": "สร้อยข้อมือลูกปัดโชคดี", "price_thb": 45,
            "sales_growth_7d": 1200, "new_creators_7d": 25, "engagement_rate": 0.12, "profit_margin_est": 0.30,
            "reviews": ["สีสดใส", "ขาดง่าย"], "image_url": "https://placehold.co/150x150?text=Lucky+Bracelet"
        }
    ][:limit]

# ==========================================
# 3. AI 分析模块
# ==========================================
@st.cache_data(show_spinner=False) # 缓存 AI 结果，避免重复调用扣费
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
        response = model.generate_content(prompt, generation_config=genai.GenerationConfig(response_mime_type="application/json"))
        return json.loads(response.text)
    except Exception as e:
        return {"cn_name": "AI 分析出错", "selling_points": "-", "pain_points": "-", "compliance_warning": str(e)}

# ==========================================
# 4. 侧边栏与打分权重控制
# ==========================================
with st.sidebar:
    st.header("⚙️ 选品参数设置")
    target_country = st.selectbox("目标市场", ["泰国 (TH)", "越南 (VN)", "菲律宾 (PH)", "美国 (US)"])
    item_limit = st.select_slider("拉取商品数量", options=[5, 10, 20, 30], value=5)
    
    st.markdown("---")
    st.header("🧮 潜力打分权重设置")
    w_growth = st.slider("近7天销量增速", 0, 100, 40)
    w_creators = st.slider("新增达人/视频", 0, 100, 30)
    w_engagement = st.slider("视频平均互动率", 0, 100, 20)
    w_margin = st.slider("预计利润空间", 0, 100, 10)

# 计算公式
def calculate_score(p):
    score = (p["sales_growth_7d"]/1000 * w_growth) + (p["new_creators_7d"]/30 * w_creators) + (p["engagement_rate"]/0.15 * w_engagement) + (p["profit_margin_est"] * w_margin)
    return round(score, 1)

# ==========================================
# 5. 主面板交互与结果展示
# ==========================================
if st.button("🚀 开始 AI 智能选品引擎", type="primary", use_container_width=True):
    with st.spinner('正在从数据库拉取近期热卖商品...'):
        time.sleep(1) # 模拟网络延迟
        products = get_mock_products(item_limit)
    
    analyzed_data = []
    
    progress_text = "🧠 正在调用 Gemini 模型进行多维分析..."
    my_bar = st.progress(0, text=progress_text)
    
    for idx, p in enumerate(products):
        # AI 分析
        ai_result = analyze_product_with_ai(p["original_title"], p["reviews"], target_country)
        # 融合数据
        full_p = {**p, **ai_result}
        full_p["score"] = calculate_score(full_p)
        analyzed_data.append(full_p)
        my_bar.progress((idx + 1) / len(products), text=f"分析进度: {idx + 1}/{len(products)}")
    
    my_bar.empty()
    
    # 排序并展示
    analyzed_data.sort(key=lambda x: x["score"], reverse=True)
    
    st.success("✅ 选品分析完成！以下是基于您设定权重的推荐排行榜：")
    
    for idx, item in enumerate(analyzed_data):
        with st.container(border=True):
            col1, col2, col3 = st.columns([1, 3, 2])
            
            with col1:
                st.image(item["image_url"], use_container_width=True)
                st.metric(label="🏆 综合潜力分", value=item["score"])
                
            with col2:
                st.subheader(f"Top {idx+1}: {item['cn_name']}")
                st.caption(f"原文: {item['original_title']}")
                st.markdown(f"**🏷️ 核心卖点:** {item['selling_points']}")
                st.markdown(f"**🩸 客户痛点:** {item['pain_points']}")
                if "无" not in item['compliance_warning']:
                    st.error(f"**⚠️ 合规警告:** {item['compliance_warning']}")
                else:
                    st.success("**✅ 合规筛查:** 暂无明显风险")
            
            with col3:
                st.markdown("📊 **数据表现**")
                st.write(f"📈 7天销量增速: **{item['sales_growth_7d']}**")
                st.write(f"👥 新增带货达人: **{item['new_creators_7d']}**")
                st.write(f"💬 视频互动率: **{item['engagement_rate']*100}%**")
                st.write(f"💰 预估利润率: **{item['profit_margin_est']*100}%**")
                st.button("🔍 去 1688 找货源", key=f"btn_{item['id']}")
