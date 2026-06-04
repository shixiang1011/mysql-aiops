import streamlit as st
import json
import os
from datetime import datetime

# 页面基础配置
st.set_page_config(
    page_title="慢查询分析报告查看器",
    page_icon="📊",
    layout="wide"
)

# 自定义CSS - 按钮样式和间隔
st.markdown("""
<style>
    .report-btn {
        width: 100%;
        text-align: left;
        margin-bottom: 8px;
        padding: 8px 12px;
        border-radius: 4px;
        border: none;
        cursor: pointer;
        transition: all 0.2s ease;
    }
    .report-btn:not(.selected) {
        background-color: #f0f2f6;
        color: #333;
    }
    .report-btn:not(.selected):hover {
        background-color: #e6e9ed;
    }
    .report-btn.selected {
        background-color: #0066cc;
        color: white;
    }
    .report-container {
        max-height: 600px;
        overflow-y: auto;
        padding-right: 8px;
    }
</style>
""", unsafe_allow_html=True)

# 报告文件路径
REPORT_PATH = os.path.join("reports", "slow_report.json")

# ----------------------
# 回调函数 - 用于即时更新选中状态
# ----------------------
def update_selected_report(report_id):
    """更新选中的报告ID（回调函数）"""
    st.session_state.selected_report_id = report_id

# ----------------------
# 工具函数
# ----------------------
def load_reports():
    """加载并排序报告（按时间倒序），处理文件异常"""
    try:
        if not os.path.exists(REPORT_PATH):
            st.warning(f"报告文件不存在：{REPORT_PATH}")
            return []
        
        with open(REPORT_PATH, 'r', encoding='utf-8') as f:
            reports = json.load(f)
        
        # 按时间戳倒序排序（最新报告在前）
        reports.sort(
            key=lambda x: x.get('timestamp', ''),
            reverse=True
        )
        return reports
    
    except json.JSONDecodeError:
        st.error("报告文件格式错误，无法解析（可能是JSON损坏）")
        return []
    except PermissionError:
        st.error(f"无权限访问报告文件：{REPORT_PATH}")
        return []
    except Exception as e:
        st.error(f"加载报告失败：{str(e)}")
        return []

def format_timestamp(timestamp_str):
    """格式化ISO时间戳为易读格式"""
    try:
        dt = datetime.fromisoformat(timestamp_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return timestamp_str

def search_reports(reports, query):
    """根据搜索词过滤报告（支持标题、表名、内容）"""
    if not query:
        return reports
        
    query_lower = query.lower()
    return [
        report for report in reports
        if (
            query_lower in report.get('title', '').lower() or
            any(query_lower in str(table).lower() for table in report.get('original_data', {}).get('tables', [])) or
            query_lower in report.get('analysis_report', '').lower() or
            query_lower in report.get('original_data', {}).get('log', '').lower()
        )
    ]

# ----------------------
# 主逻辑
# ----------------------
reports = load_reports()
st.title("📊 慢查询分析报告查看器")

# 初始化会话状态
if 'selected_report_id' not in st.session_state:
    if reports:
        st.session_state.selected_report_id = reports[0]['id']
    else:
        st.session_state.selected_report_id = None

# 侧边栏 - 报告列表和搜索
with st.sidebar:
    st.header("报告列表")
    
    # 搜索框
    search_query = st.text_input("搜索报告", placeholder="输入标题、表名或内容关键词...")
    filtered_reports = search_reports(reports, search_query)
    
    # 显示统计信息
    st.caption(f"显示 {len(filtered_reports)} 份报告（共 {len(reports)} 份）")
    
    # 报告列表
    if filtered_reports:
        # 确保选中的ID在当前过滤列表中
        valid_ids = [r['id'] for r in filtered_reports]
        if (st.session_state.selected_report_id is None or 
            st.session_state.selected_report_id not in valid_ids):
            st.session_state.selected_report_id = valid_ids[0]
        
        # 报告容器（带滚动）
        st.markdown('<div class="report-container">', unsafe_allow_html=True)
        
        # 逐个显示报告按钮，使用回调函数更新状态
        for report in filtered_reports:
            report_id = report['id']
            timestamp = format_timestamp(report['timestamp'])
            title = report['title']
            
            # 按钮状态判断
            is_selected = (report_id == st.session_state.selected_report_id)
            
            # 使用回调函数确保状态即时更新
            st.button(
                label=f"[{timestamp}] {title}",
                key=f"btn_{report_id}",
                use_container_width=True,
                type="primary" if is_selected else "secondary",
                on_click=update_selected_report,
                args=(report_id,)
            )
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # 获取选中的报告
        selected_report = next(
            (r for r in filtered_reports if r['id'] == st.session_state.selected_report_id),
            None
        )
    else:
        st.info("没有找到匹配的报告")
        selected_report = None

# 主内容区 - 显示报告详情
if selected_report:
    st.subheader(selected_report['title'])
    
    # 基本信息卡片
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info(f"**报告ID**\n\n{selected_report['id']}")
    with col2:
        st.info(f"**生成时间**\n\n{format_timestamp(selected_report['timestamp'])}")
    with col3:
        st.info(f"**请求ID**\n\n{selected_report['request_id']}")
    
    # 性能指标
    st.subheader("查询性能指标")
    original_data = selected_report.get('original_data', {})
    metrics_col1, metrics_col2, metrics_col3, metrics_col4 = st.columns(4)
    with metrics_col1:
        st.metric("查询时间", f"{original_data.get('query_time', 'N/A')} 秒")
    with metrics_col2:
        st.metric("锁定时间", f"{original_data.get('lock_time', 'N/A')} 秒")
    with metrics_col3:
        st.metric("返回行数", original_data.get('rows_sent', 'N/A'))
    with metrics_col4:
        st.metric("扫描行数", original_data.get('rows_examined', 'N/A'))
    
    # 涉及表名
    st.subheader("涉及表名")
    tables = original_data.get('tables', [])
    if tables:
        for table in tables:
            st.text(f"- {table}")
    else:
        st.text("无表信息")
    
    # 原始SQL
    with st.expander("查看原始SQL", expanded=False):
        st.code(original_data.get('log', '无SQL日志'), language="sql")
    
    # 表结构信息
    st.subheader("表结构详情")
    table_info_list = selected_report.get('table_info', [])
    for table_info in table_info_list:
        with st.expander(f"表: {table_info.get('cleaned_name', '未知表')}"):
            if table_info.get('error'):
                st.error(f"获取表信息失败: {table_info['error']}")
            else:
                st.text(f"预估行数: {table_info.get('row_count', '未知')}")
                st.code(table_info.get('ddl', '无DDL信息'), language="sql")
    
    # 分析报告
    st.subheader("优化建议")
    st.markdown(selected_report.get('analysis_report', '无分析内容'))

else:
    if reports:
        st.info("请从侧边栏选择一份报告查看详情")
    else:
        st.info("暂无报告数据，请先运行分析任务生成报告")
    