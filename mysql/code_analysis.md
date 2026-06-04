# process_slow_log.py 代码逐行解读

## 一、这个文件是做什么的？

简单来说，这是一个 **MySQL 慢查询自动分析服务**。

它的核心工作流程是：
1. 启动一个 Web 服务（Flask），监听 HTTP 请求
2. 接收慢查询日志数据（NDJSON 格式）
3. 连接 MySQL 数据库，获取涉及表的结构信息（DDL、行数等）
4. 把日志 + 表结构信息打包发给 DeepSeek 大模型（AI）
5. AI 返回优化建议，保存为 JSON 报告文件

**通俗比喻：** 就像你把一条写得很慢的 SQL 语句交给一个 DBA 专家，专家看了表结构后告诉你怎么优化。这里"专家"就是 DeepSeek AI。

---

## 二、用到了哪些技术？

| 技术 | 作用 |
|------|------|
| **Flask** | Python Web 框架，用来创建 HTTP 接口 |
| **mysql.connector** | Python 连接 MySQL 数据库的库 |
| **openai (AsyncOpenAI)** | 调用 DeepSeek 大模型 API 的客户端库（兼容 OpenAI 接口） |
| **asyncio / threading** | 异步编程 + 多线程，让 AI 调用不阻塞主服务 |
| **dataclass** | Python 的数据类，用来组织配置信息 |

---

## 三、代码结构总览

整个文件从上到下分为这几个部分：

```
1. 配置类 AppConfig          ← 所有可调参数集中在这里
2. 初始化代码                ← 创建目录、报告文件、Flask应用
3. 工具函数                  ← 日志记录、表名清理、数据库操作
4. AI 相关函数               ← 生成提示词、调用 DeepSeek API
5. 报告处理函数              ← 保存分析报告到 JSON 文件
6. 核心处理流程              ← 后台分析的完整流程
7. API 路由                  ← Flask 的两个 HTTP 接口
8. 启动入口                  ← if __name__ == '__main__'
```

---

## 四、逐段详解

### 4.1 导入模块（第 1-12 行）

```python
import os          # 操作文件路径、创建目录、读取环境变量
import re          # 正则表达式，用于清理表名中的反引号
import json        # JSON 读写
import mysql.connector   # 连接 MySQL 数据库
import threading   # 多线程，让后台任务不阻塞主线程
import asyncio     # 异步编程，配合 AI API 的 async 调用
from datetime import datetime      # 获取当前时间
from dataclass import ...          # 数据类装饰器
from typing import ...             # 类型提示（让代码更规范）
from flask import Flask, request, Response   # Web 框架
from openai import AsyncOpenAI, ...          # AI API 客户端
```

### 4.2 配置类 AppConfig（第 15-44 行）

```python
@dataclass
class AppConfig:
```

这是一个"配置中心"，把所有可配置的参数集中管理。`@dataclass` 是 Python 装饰器，自动生成初始化方法。

| 配置项 | 默认值 | 含义 |
|--------|--------|------|
| HOST | "0.0.0.0" | 监听所有网络接口（可被外部访问） |
| PORT | 5001 | 服务端口号 |
| LOG_DIR | 同目录下 logs/ | 日志文件存放目录 |
| REPORT_DIR | 同目录下 reports/ | 报告文件存放目录 |
| LLM_BASE_URL | DeepSeek API 地址 | 大模型的接口地址 |
| LLM_MODEL | "deepseek-chat" | 使用的模型名称 |
| LLM_TEMPERATURE | 0.7 | AI 回答的"创造性"，0-1 越高越随机 |
| LLM_MAX_TOKENS | 2000 | AI 回答的最大长度 |
| DB_CONNECT_TIMEOUT | 10 | 连接数据库超时时间（秒） |
| DEFAULT_DB_SCHEMA | "testdb" | 表名没指定数据库时的默认数据库 |

### 4.3 初始化代码（第 47-58 行）

```python
config = AppConfig()                              # 创建配置实例
os.makedirs(config.LOG_DIR, exist_ok=True)        # 创建 logs 目录（已存在不报错）
os.makedirs(config.REPORT_DIR, exist_ok=True)     # 创建 reports 目录
```

接下来检查报告文件是否存在，如果不存在就创建一个空的 JSON 数组 `[]`。

最后创建 Flask 应用实例和一个全局的 AI 客户端变量（初始为 None，用到时再初始化）。

### 4.4 init_llm_client() - 初始化 AI 客户端（第 61-73 行）

```python
def init_llm_client() -> AsyncOpenAI:
```

**作用：** 创建一个连接 DeepSeek AI 的客户端。

**要点：**
- 从环境变量 `DEEPSEEK_API_KEY` 读取 API 密钥
- 如果没配置密钥，直接报错
- 使用"延迟初始化"模式——第一次调用时才创建，之后复用同一个客户端
- `global llm_client` 表示修改全局变量

### 4.5 get_db_config() - 获取数据库连接配置（第 76-92 行）

```python
def get_db_config(schema: Optional[str] = None) -> Dict[str, Any]:
```

**作用：** 从环境变量读取数据库连接信息，返回一个字典。

默认连接 `localhost:3306`，用户 `root`，密码 `root`。如果指定了 schema（数据库名），就加到配置里。

**为什么用环境变量？** 因为密码等敏感信息不应该写死在代码里。

### 4.6 日志函数 write_operation_log / write_error_log（第 95-118 行）

这两个函数做的事情一样，只是写到不同文件：
- 操作日志 → `logs/api_operation.log`
- 错误日志 → `logs/api_error.log`

日志格式：`[时间] [REQUEST=请求ID] OPERATION/ERROR: 消息内容`

`request_id` 是每次请求的唯一标识，方便排查问题时追踪完整链路。

### 4.7 clean_table_name() - 清理表名（第 121-133 行）

```python
def clean_table_name(table_name: str) -> tuple[str, str]:
```

MySQL 的表名可能带有反引号（如 `` `mydb`.`mytable` ``），这个函数：
1. 去掉反引号
2. 分离数据库名和表名
3. 如果没有数据库前缀，使用默认数据库 `testdb`

**示例：**
- 输入 `` `mydb`.`users` `` → 返回 `("mydb", "users")`
- 输入 `orders` → 返回 `("testdb", "orders")`

### 4.8 get_table_info() - 获取表的结构信息（第 136-200 行）

```python
def get_table_info(table_name: str, request_id: str) -> Dict[str, Any]:
```

**作用：** 连接 MySQL 数据库，获取某个表的建表语句（DDL）和行数。

**执行的 SQL：**
- `SHOW CREATE TABLE 表名` → 获取建表语句（包含索引、字段类型等）
- `SHOW TABLE STATUS LIKE '表名'` → 获取表的行数等状态信息

**返回的字典包含：** 表名、数据库名、DDL 语句、行数、错误信息（如果有）

**为什么要获取这些？** 因为 AI 分析慢查询时，需要知道表有多少行、有没有索引、字段类型是什么，才能给出靠谱的优化建议。

### 4.9 generate_report_title() - 生成报告标题（第 203-219 行）

```python
def generate_report_title(log_data: Dict[str, Any]) -> str:
```

根据慢查询信息生成一个人类可读的标题，比如：
`2026-06-04 14:30:00 - 慢查询分析报告（耗时: 5.2秒，涉及表: users, orders）`

它会自动识别 SQL 是 SELECT、UPDATE、DELETE 还是 INSERT。

### 4.10 generate_prompt() - 生成 AI 提示词（第 222-256 行）

```python
def generate_prompt(log_data, table_info_list, request_id) -> str:
```

**作用：** 把慢查询日志和表结构信息组装成一段"提示词"，发给 AI 分析。

提示词内容包括：
- 原始 SQL 语句
- 查询时间、锁定时间、返回行数、扫描行数
- 每个涉及表的 DDL 和行数
- 最后要求 AI 给出索引优化、SQL 改写、表结构优化等建议

**这就像你把一份"病例"整理好交给医生，医生才能对症下药。**

### 4.11 call_deepseek_api() - 调用 AI 分析（第 259-299 行）

```python
async def call_deepseek_api(prompt: str, request_id: str) -> str:
```

**作用：** 把提示词发给 DeepSeek AI，获取分析结果。

**关键点：**
- `async` 表示这是一个异步函数，调用时不会阻塞其他任务
- 给 AI 设定了角色："你是一位数据库性能优化专家"
- `temperature=0.7` 让回答有一定创造性但不会太离谱
- 处理了 4 种错误：API 错误、连接错误、超时、未知错误

### 4.12 append_to_report() - 保存报告（第 302-331 行）

```python
def append_to_report(report_data: Dict[str, Any], request_id: str) -> bool:
```

**作用：** 把分析结果追加到 `slow_report.json` 文件中。

**流程：**
1. 读取现有的报告数组
2. 把新报告 append 进去
3. 写回文件

**为什么用追加而不是覆盖？** 因为可能同时有多条慢查询在分析，而且历史报告需要保留。

### 4.13 extract_valid_log_records() - 解析 NDJSON（第 334-365 行）

```python
def extract_valid_log_records(ndjson_data: List[str], request_id) -> List[Dict]:
```

**什么是 NDJSON？** 就是"换行分隔的 JSON"，每行一个独立的 JSON 对象。类似这样：
```json
{"log": "SELECT * FROM users...", "tables": ["users"], "query_time": 5.2}
{"log": "UPDATE orders SET...", "tables": ["orders"], "query_time": 3.1}
```

这个函数逐行解析，只保留包含 `log` 和 `tables` 字段的有效记录。

### 4.14 process_analysis_background() - 后台分析主流程（第 368-419 行）

```python
async def process_analysis_background(log_records, request_id) -> None:
```

**这是整个文件的核心！** 把上面的函数串起来，对每条慢查询记录：

1. 生成报告标题
2. 获取所有涉及表的信息（DDL + 行数）
3. 生成提示词，调用 AI 分析
4. 组装报告数据（包含原始数据 + 表信息 + AI 分析结果）
5. 追加到报告文件

### 4.15 run_async_task() - 线程包装器（第 422-428 行）

```python
def run_async_task(log_records, request_id) -> None:
```

Flask 是同步框架，但 AI 调用是异步的。这个函数用 `asyncio.run()` 在新线程中运行异步代码，解决兼容问题。

### 4.16 API 路由 - /analyze-slow-query（第 431-534 行）

```python
@app.route('/analyze-slow-query', methods=['POST'])
def analyze_slow_query():
```

**这是对外暴露的 HTTP 接口，别人通过 POST 请求调用。**

**完整流程：**
1. 生成唯一的 `request_id`（时间戳 + 随机字符串）
2. 检查 Content-Type 必须是 `application/x-ndjson`
3. 读取请求体，按行分割得到 NDJSON 数据
4. 解析出有效的日志记录
5. 如果没有有效记录，直接返回"没有需要处理的数据"
6. 有记录的话，启动后台线程处理，立刻返回"已接收"
7. 后台处理完成后报告自动保存到文件

**注意：** 这是异步处理模式——收到请求后立刻返回 200，分析在后台进行。这样调用方不需要等待 AI 分析完成。

### 4.17 API 路由 - /health（第 537-610 行）

```python
@app.route('/health', methods=['GET'])
def health_check():
```

**健康检查接口**，检查三个组件的状态：
- AI 客户端是否正常
- 数据库是否可连接
- 报告文件是否可访问

返回每个组件的状态和整体状态（healthy / degraded）。

### 4.18 启动入口（第 613-628 行）

```python
if __name__ == '__main__':
```

直接运行此文件时执行。打印配置信息和环境变量检查结果，然后启动 Flask 服务。

---

## 五、整体流程图

```
用户/系统发送 POST 请求
        │
        ▼
┌─────────────────────┐
│  /analyze-slow-query │
│  (Flask 接口)        │
│                     │
│  1. 验证请求格式     │
│  2. 解析 NDJSON      │
│  3. 提取有效记录     │
│  4. 启动后台线程     │──→ 立刻返回 "已接收"
│                     │
└─────────────────────┘
        │
        ▼ (后台线程)
┌─────────────────────┐
│  对每条慢查询：       │
│                     │
│  1. 生成报告标题     │
│  2. 查 MySQL 获取    │
│     表结构(DDL+行数) │
│  3. 组装提示词       │
│  4. 调用 DeepSeek AI │
│  5. 保存报告到JSON   │
└─────────────────────┘
        │
        ▼
  reports/slow_report.json
```

---

## 六、环境变量清单

运行前需要配置以下环境变量：

| 变量名 | 必须 | 默认值 | 说明 |
|--------|------|--------|------|
| DEEPSEEK_API_KEY | 是 | 无 | DeepSeek API 密钥 |
| DB_HOST | 否 | localhost | MySQL 地址 |
| DB_USER | 否 | root | MySQL 用户名 |
| DB_PASSWORD | 否 | root | MySQL 密码 |
| DB_PORT | 否 | 3306 | MySQL 端口 |

---

## 七、调用示例

```bash
# 启动服务
python process_slow_log.py

# 调用分析接口
curl -X POST http://localhost:5001/analyze-slow-query \
  -H "Content-Type: application/x-ndjson" \
  -d '{"log":"SELECT * FROM users WHERE name = '\''test'\''","tables":["users"],"query_time":5.2,"lock_time":0.01,"rows_sent":100,"rows_examined":50000}'

# 健康检查
curl http://localhost:5001/health
```
