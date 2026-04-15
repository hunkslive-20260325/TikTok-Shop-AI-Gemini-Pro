import streamlit as st
import json
import time
import base64
import requests
import urllib.parse
from datetime import datetime, timedelta

# ==========================================
# 0. 页面基本配置与全局状态
# ==========================================
st.set_page_config(page_title="平价饰品 AI 选品引擎", page_icon="💎", layout="wide")
st.title("💎 平价饰品 AI 选品引擎")
st.markdown("基于多维数据加权与 90 天趋势预测的 TikTok Shop 深度选品工具")

# 初始化日志状态
if "app_logs" not in st.session_state:
    st.session_state.app_logs = []

def add_log(title, request_data, response_data):
    """添加调试日志的辅助函数"""
    time_str = datetime.now().strftime("%H:%M:%S")
    # 为了防止界面卡顿，如果是超长响应只截取前 300 个字符
    res_str = str(response_data)
    if len(res_str) > 300: res_str = res_str[:300] + " ... (已省略过长内容)"
    log_content = f"[{time_str}] {title}\n👉 入参: {request_data}\n👈 返参: {res_str}"
    st.session_state.app_logs.insert(0, log_content) # 插在最前面

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
# 2. 常量配置
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
    api_url = "https://open.echotik.live/api/v3/echotik/product/ranklist"
    today = datetime.now()
    
    if rank_type == 1:
        target_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    elif rank_type == 2:
        target_date = (today - timedelta(days=today.weekday() + 7)).strftime("%Y-%m-%d")
    else:
        target_date = today.replace(day=1).strftime("%Y-%m-%d")

    params = {
        "date": target_date, "region": region, "category_id": "605248",
        "category_l2_id": "905608", "category_l3_id": l3_id,
        "product_rank_field": 1, "rank_type": rank_type,
        "page_num": 1, "page_size": limit
    }
    try:
        res = requests.get(api_url, headers=get_auth_headers(), params=params, timeout=15).json()
        add_log("📊 大盘商品拉取", params, f"成功获取 {len(res.get('data', []))} 条数据" if res.get("code")==0 else res)
        return res.get("data", [])
    except Exception as e:
        add_log("❌ 大盘拉取异常", params, str(e))
        return []

def fetch_potential_index(product_id, rank_type):
    """
    根据筛选周期，动态计算未来趋势
    """
    api_url = "https://open.echotik.live/api/v3/echotik/product/trend"
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    
    params = {"product_id": product_id, "start_date": start_date, "end_date": end_date}
    try:
        res = requests.get(api_url, headers=get_auth_headers(), params=params, timeout=10).json()
        
        if res.get("code") != 0:
            add_log("❌ 趋势接口报错", params, res)
            return "计算失败 (接口拒绝)", 0
            
        trends = res.get("data", [])
        if len(trends) < 14: # 数据量太少无法测算
            return "新商品/数据不足", 0
            
        # 提取日销量增量，排倒序（最新的在前）
        daily_sales = [t.get("total_sale_1d_cnt") or 0 for t in trends]
        daily_sales.reverse()
        
        # 动态趋势算法
        if rank_type == 1: # 日榜：对比近3天均值 与 往前推7天均值
            recent_avg = sum(daily_sales[:3]) / 3
            history_avg = sum(daily_sales[3:10]) / 7
        elif rank_type == 2: # 周榜：对比近7天均值 与 往前推21天均值
            recent_avg = sum(daily_sales[:7]) / 7
            history_avg = sum(daily_sales[7:28]) / 21 if len(daily_sales) >= 28 else 1
        else: # 月榜：对比近30天均值 与 往前推60天均值
            recent_avg = sum(daily_sales[:30]) / 30
            history_avg = sum(daily_sales[30:90]) / 60 if len(daily_sales) >= 90 else 1
            
        # 避免除以 0
        history_avg = max(history_avg, 0.1)
        ratio = recent_avg / history_avg
        
        add_log(f"📈 趋势测算 ({product_id})", f"周期:{rank_type}, 最近均值:{recent_avg:.1f}, 历史均值:{history_avg:.1f}", f"比值: {ratio:.2f}")

        if ratio > 1.25: return f"🔥 显著上升 (增速 {int((ratio-1)*100)}%)", recent_avg
        elif ratio < 0.8: return f"📉 正在下降 (跌幅 {int((1-ratio)*100)}%)", recent_avg
        else: return "➡️ 趋势平稳", recent_avg
        
    except Exception as e:
        add_log("❌ 趋势计算异常", params, str(e))
        return "计算失败 (代码异常)", 0

def fetch_product_videos(product_id):
    api_url = "https://open.echotik.live/api/v3/echotik/product/video"
    params = {"product_id": product_id, "page_size": 3} 
    try:
        res = requests.get(api_url, headers=get_auth_headers(), params=params, timeout=10).json()
        return res.get("data", [])
    except: return []

# ==========================================
# 4. AI 分析模块 (加入日志)
# ==========================================
def analyze_with_ai(title, region):
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    prompt = f"分析TikTok商品：{title}。市场：{region}。以JSON输出：cn_name(中文名), selling_points(3个核心卖点,逗号分隔的纯文本), pain_points(1个痛点,纯文本)。"
    payload = {
        "model": "google/gemini-2.0-flash-001",
        "messages": [{"role": "user", "content": prompt}]
    }
    try:
        res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=20).json()
        content = res["choices"][0]["message"]["content"]
        
        add_log(f"🧠 AI解析 ({title[:10]}...)", prompt, content)
        
        clean_json = content.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        add_log("❌ AI解析异常", prompt, str(e))
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
    
    st.markdown("---")
    st.header("📝 系统运行日志")
    if st.button("🗑️ 清空日志"):
        st.session_state.app_logs = []
        
    with st.expander("点击查看 API 调试日志", expanded=False):
        if st.session_state.app_logs:
            for log in st.session_state.app_logs[:20]: # 仅显示最新20条
                st.text(log)
                st.markdown("---")
        else:
            st.caption("暂无运行记录...")

# ==========================================
# 6. 主逻辑渲染
# ==========================================
if st.button("🚀 开始 AI 智能选品", type="primary", use_container_width=True):
    raw_products = fetch_products(m_info["code"], l3_id, rank_type, limit)
    
    if not raw_products:
        st.warning("未能拉取到数据，请查看左侧日志排查具体原因。")
        st.stop()

    for idx, p in enumerate(raw_products):
        p_id = p.get("product_id")
        
        with st.status(f"正在深度分析第 {idx+1} 个商品...", expanded=False):
            ai_res = analyze_with_ai(p.get("product_name"), market_label)
            p_trend, recent_avg = fetch_potential_index(p_id, rank_type)
            videos = fetch_product_videos(p_id)
            time.sleep(0.5)

        # 清洗展示瑕疵 (把列表转为字符串)
        sp_display = ai_res.get('selling_points', '-')
        if isinstance(sp_display, list): sp_display = ", ".join([str(x) for x in sp_display])

        with st.container(border=True):
            col1, col2 = st.columns([3, 2])
            
            with col1:
                st.subheader(f"Top {idx+1}: {ai_res.get('cn_name', '解析失败')}")
                st.caption(f"原始名称: {p.get('product_name')} (ID: {p_id})")
                st.write(f"🏷️ **核心卖点**: {sp_display}")
                st.write(f"🩸 **客户痛点**: {ai_res.get('pain_points', '-')}")
                
                # 动态潜力指数展示
                if "上升" in p_trend:
                    st.success(f"🔮 **动态潜力预测 (依据选定周期)**: {p_trend}")
                elif "下降" in p_trend:
                    st.error(f"🔮 **动态潜力预测 (依据选定周期)**: {p_trend}")
                else:
                    st.info(f"🔮 **动态潜力预测 (依据选定周期)**: {p_trend}")
            
            with col2:
                st.markdown("📊 **核心数据 (EchoTik USD 转换)**")
                local_price = round(p.get("spu_avg_price", 0) * m_info["rate"], 2)
                st.write(f"💰 均价: **{local_price} {m_info['sym']}** (参考: ${p.get('spu_avg_price')} USD)")
                st.write(f"📈 周期销量: **{p.get('total_sale_cnt', 0)}**")
                
                # 修复 None 的问题
                lfl_cnt = p.get('total_lfl_cnt') or 0
                st.write(f"👥 关联达人数: **{lfl_cnt}**")
                
                v_cnt = p.get('total_video_cnt') or 0
                st.write(f"🎥 关联视频数: **{v_cnt}**")
                
                if videos:
                    with st.expander("👉 查看关联带货视频素材"):
                        for v in videos:
                            st.markdown(f"- [去 TikTok 播放]({v.get('video_url', '#')}) (播放量: {v.get('total_view_cnt', 0)})")
                else:
                    st.caption("EchoTik 暂未收录相关视频")

            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                st.link_button("🔗 在 EchoTik 查看详情", f"https://echotik.live/products/{p_id}", use_container_width=True)
            with btn_col2:
                kw = ai_res.get('cn_name', '') if ai_res.get('cn_name') != "解析失败" else p.get('product_name')
                try:
                    encoded_kw = urllib.parse.quote(kw.encode('gbk'))
                except:
                    encoded_kw = urllib.parse.quote(kw)
                st.link_button("🛒 1688 搜同款", f"https://s.1688.com/selloffer/offer_search.htm?keywords={encoded_kw}", use_container_width=True)
