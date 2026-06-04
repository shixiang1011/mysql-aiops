# show_slow_report.py 代码逐行解读

## 一、这个文件是做什么的？

这是一个 **慢查询分析报告的可视化查看器**。

简单来说：`process_slow_log.py` 负责生成报告，`show_slow_report.py` 负责展示报告。两者是"生产者"和"消费者"的关系。

它使用 **Streamlit** 框架构建了一个 Web 页面，你可以在浏览器里：
- 查看所有历史分析报告列表
- 搜索/过滤报告
- 查看每份报告的详细信息（性能指标、表结构、AI 优化建议）

**通俗比喻：** 如果 `process_slow_log.py` 是写报告的秘书，那 `show_slow_report.py` 就是把报告排好版放在你面前的前台。

---

## 二、用到了哪些技术？

| 技术 | 作用 |
|------|------|
| **Streamlit** | Python 的快速 Web 应用框架，几行代码就能做出交互式网页 |
| **json** | 读取报告文件 |
| **os** | 文件路径操作、判断文件是否存在 |
| **datetime** | 时间格式化 |

---

## 三、代码结构总览

```
1. 页面配置           ← 设置页面标题、图标、布局
2. 自定义 CSS         ← 美化按钮和容器样式
3. 工具函数           ← 加载报告、格式化时间、搜索过滤
4. 侧边栏             ← 报告列表 + 搜索框
5. 主内容区           ← 显示选中报告的详情
```

---

## 四、逐段详解

### 4.1 页面基础配置（第 1-11 行）

```python
import streamlit as st
import json
import os
from datetime import datetime

st.set_page_config(
    page_title="慢查询分析报告查看器",
    page_icon="📊",
    layout="wide"
)
```

- `page_title`：浏览器标签页显示的标题
- `page_icon`：浏览器标签页的小图标（emoji）
- `layout="wide"`：使用宽屏布局，充分利用屏幕空间

### 4.2 自定义 CSS 样式（第 14-43 行）

```python
st.markdown("""<style>...</style>""", unsafe_allow_html=True)
```

Streamlit 默认样式比较有限，这里用 CSS 自定义了：
- `.report-btn`：侧边栏报告按钮的样式（圆角、悬停变色、选中高亮）
- `.report-container`：报告列表容器（最大高度 600px，超出可滚动）

**为什么要写 CSS？** 让侧边栏的报告列表更好看、更好用。

### 4.3 报告文件路径（第 46 行）

```python
REPORT_PATH = os.path.join("reports", "slow_report.json")
```

报告文件路径指向 `reports/slow_report.json`——这正是 `process_slow_log.py` 写入报告的位置。两个文件通过这个路径关联。

### 4.4 回调函数 update_selected_report()（第 51-53 行）

```python
def update_selected_report(report_id):
    st.session_state.selected_report_id = report_id
```

**什么是 `st.session_state`？**

Streamlit 的特殊机制：每次你点击页面上的任何按钮，整个脚本会从头到尾重新执行一遍。`session_state` 就是一个"记忆空间"，用来在重新执行时保留状态（比如"用户选了哪份报告"）。

**什么是"回调函数"？**

用户点击按钮时，先执行回调函数更新状态，然后再重新运行整个脚本。这比在按钮后面判断"是否被点击"更可靠。

### 4.5 load_reports() - 加载报告（第 58-83 行）

```python
def load_reports():
```

**作用：** 读取 `slow_report.json` 文件，返回报告列表。

**处理逻辑：**
1. 文件不存在 → 显示警告，返回空列表
2. 文件存在 → 读取 JSON，按时间倒序排列（最新的在前面）
3. JSON 格式损坏 → 显示错误提示
4. 没有文件权限 → 显示错误提示
5. 其他异常 → 显示错误提示

### 4.6 format_timestamp() - 时间格式化（第 85-91 行）

```python
def format_timestamp(timestamp_str):
```

把 ISO 格式的时间字符串（如 `2026-06-04T14:30:00.123456`）转成易读格式（如 `2026-06-04 14:30:00`）。

### 4.7 search_reports() - 搜索过滤（第 93-107 行）

```python
def search_reports(reports, query):
```

根据搜索关键词过滤报告，支持在以下字段中搜索：
- 报告标题（title）
- 涉及的表名（tables）
- AI 分析报告内容（analysis_report）
- 原始 SQL 日志（log）

全部转小写后匹配，所以搜索不区分大小写。

### 4.8 初始化（第 112-120 行）

```python
reports = load_reports()
st.title("📊 慢查询分析报告查看器")

if 'selected_report_id' not in st.session_state:
    if reports:
        st.session_state.selected_report_id = reports[0]['id']
    else:
        st.session_state.selected_report_id = None
```

页面加载时：
1. 读取所有报告
2. 显示页面标题
3. 如果是第一次打开（session_state 里没有选中记录），默认选中最新的一份报告

### 4.9 侧边栏（第 123-172 行）

侧边栏包含三个部分：

**（1）搜索框**
```python
search_query = st.text_input("搜索报告", placeholder="输入标题、表名或内容关键词...")
filtered_reports = search_reports(reports, search_query)
```
用户输入关键词后实时过滤报告。

**（2）统计信息**
```python
st.caption(f"显示 {len(filtered_reports)} 份报告（共 {len(reports)} 份）")
```
显示"找到 X 份 / 共 Y 份"。

**（3）报告按钮列表**
```python
for report in filtered_reports:
    st.button(
        label=f"[{timestamp}] {title}",
        key=f"btn_{report_id}",
        type="primary" if is_selected else "secondary",
        on_click=update_selected_report,
        args=(report_id,)
    )
```
每份报告显示为一个按钮，格式为 `[时间] 标题`。当前选中的按钮高亮显示（primary 样式）。

**注意：** 如果搜索后选中的报告不在过滤结果里，会自动选中第一条。

### 4.10 主内容区 - 报告详情（第 175-233 行）

选中报告后，页面右侧显示详情，分为几个区域：

**（1）基本信息卡片（第 179-185 行）**

三列并排显示：报告 ID、生成时间、请求 ID。

**（2）性能指标（第 188-198 行）**

四列并排显示关键指标：
| 指标 | 含义 |
|------|------|
| 查询时间 | SQL 执行了多久 |
| 锁定时间 | 等待锁花了多久 |
| 返回行数 | SQL 返回了多少行数据 |
| 扫描行数 | SQL 扫描了多少行数据（通常远大于返回行数，这就是慢的原因） |

**（3）涉及表名（第 201-207 行）**

列出这条慢查询涉及到的所有表。

**（4）原始 SQL（第 210-211 行）**

放在一个可折叠的区域里，点击"查看原始SQL"展开。用 SQL 语法高亮显示。

**（5）表结构详情（第 214-222 行）**

每个涉及的表单独一个折叠区域，显示：
- 预估行数
- DDL（建表语句，包含字段、索引等信息）

**（6）优化建议（第 225-226 行）**

直接用 Markdown 渲染 AI 生成的分析报告——这就是 DeepSeek AI 返回的优化建议。

---

## 五、页面布局示意

```
┌────────────────────────────────────────────────────────┐
│ 📊 慢查询分析报告查看器                                  │
├──────────────┬─────────────────────────────────────────┤
│  报告列表     │  [报告标题]                              │
│              │                                         │
│  [搜索框]    │  ┌────────┬────────┬────────┐           │
│              │  │报告ID   │生成时间 │请求ID  │           │
│  显示 X/Y 份 │  └────────┴────────┴────────┘           │
│              │                                         │
│  [时间] 标题1 │  查询性能指标                            │
│  [时间] 标题2 │  ┌────────┬────────┬────────┬────────┐  │
│  [时间] 标题3 │  │查询时间 │锁定时间 │返回行数 │扫描行数│  │
│  [时间] 标题4 │  └────────┴────────┴────────┴────────┘  │
│              │                                         │
│              │  涉及表名                                │
│              │  - users                                │
│              │                                         │
│              │  [▶ 查看原始SQL]                         │
│              │                                         │
│              │  表结构详情                              │
│              │  [▶ 表: testdb.users]                   │
│              │                                         │
│              │  优化建议                                │
│              │  AI 生成的分析报告内容...                  │
├──────────────┴─────────────────────────────────────────┤
│              （主内容区可滚动）                           │
└────────────────────────────────────────────────────────┘
```

---

## 六、两个文件如何配合

```
process_slow_log.py                    show_slow_report.py
(生产者)                               (消费者)
                                      
POST 请求 → 接收慢查询日志              用户打开浏览器 → 加载页面
        → 查 MySQL 获取表结构                  → 读取 slow_report.json
        → 调用 DeepSeek AI 分析                → 显示报告列表
        → 保存到 slow_report.json              → 点击查看详细报告
              │                                         ▲
              └──── reports/slow_report.json ────────────┘
                        （共享的数据文件）
```

---

## 七、如何运行

```bash
# 先确保有报告数据（运行过 process_slow_log.py）
# 然后启动 Streamlit 应用
streamlit run show_slow_report.py
```

浏览器会自动打开 `http://localhost:8501`，即可查看报告。
