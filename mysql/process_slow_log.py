import os
import re
import json
import mysql.connector
import threading
import asyncio
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

from flask import Flask, request, Response
from openai import AsyncOpenAI, APIError, APIConnectionError, Timeout

# 应用配置 - 非敏感配置集中管理
@dataclass
class AppConfig:
    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 5001
    DEBUG: bool = False
    
    # 路径配置
    CURRENT_DIR: str = os.path.dirname(os.path.abspath(__file__))
    LOG_DIR: str = os.path.join(CURRENT_DIR, "logs")
    REPORT_DIR: str = os.path.join(CURRENT_DIR, "reports")
    SLOW_REPORT_PATH: str = os.path.join(REPORT_DIR, "slow_report.json")  # 统一报告文件路径
    
    # 日志文件路径
    OPERATION_LOG_PATH: str = os.path.join(LOG_DIR, "api_operation.log")
    ERROR_LOG_PATH: str = os.path.join(LOG_DIR, "api_error.log")
    
    # LLM配置
    LLM_BASE_URL: str = "https://api.deepseek.com"
    LLM_MODEL: str = "deepseek-chat"
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 2000
    
    # 数据库连接配置
    DB_CONNECT_TIMEOUT: int = 10
    DB_CHARSET: str = "utf8mb4"
    DEFAULT_DB_SCHEMA: str = "testdb"  # 无schema时使用的默认数据库
    
    # 内容类型配置
    SUPPORTED_CONTENT_TYPE: str = "application/x-ndjson"

# 初始化配置与目录
config = AppConfig()
os.makedirs(config.LOG_DIR, exist_ok=True)
os.makedirs(config.REPORT_DIR, exist_ok=True)

# 初始化报告文件（如果不存在）
if not os.path.exists(config.SLOW_REPORT_PATH):
    with open(config.SLOW_REPORT_PATH, 'w', encoding='utf-8') as f:
        json.dump([], f, ensure_ascii=False, indent=2)

# 初始化Flask应用与LLM客户端（延迟初始化）
app = Flask(__name__)
llm_client: Optional[AsyncOpenAI] = None


def init_llm_client() -> AsyncOpenAI:
    """初始化LLM客户端，检查API密钥"""
    global llm_client
    if llm_client is None:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("未找到DEEPSEEK_API_KEY环境变量，请配置")
        
        llm_client = AsyncOpenAI(
            api_key=api_key,
            base_url=config.LLM_BASE_URL
        )
    return llm_client


def get_db_config(schema: Optional[str] = None) -> Dict[str, Any]:
    """从环境变量获取数据库配置，支持指定schema"""
    config_dict = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'user': os.getenv('DB_USER', 'root'),
        'password': os.getenv('DB_PASSWORD', 'root'),
        'port': int(os.getenv('DB_PORT', 3306)),
        'connect_timeout': config.DB_CONNECT_TIMEOUT,
        'charset': config.DB_CHARSET,
        'autocommit': True
    }
    
    # 如果指定了schema，则添加到配置
    if schema:
        config_dict['database'] = schema
        
    return config_dict


def write_operation_log(message: str, request_id: Optional[str] = None) -> None:
    """记录操作日志，包含时间戳和请求ID"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    request_id = request_id or "N/A"
    log_entry = f"[{timestamp}] [REQUEST={request_id}] OPERATION: {message}\n"
    try:
        with open(config.OPERATION_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(log_entry)
        print(log_entry.strip())
    except Exception as e:
        print(f"[日志系统错误] 写入操作日志失败: {str(e)} | 原始消息: {message}")


def write_error_log(error_message: str, request_id: Optional[str] = None) -> None:
    """记录错误日志，包含时间戳和请求ID"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    request_id = request_id or "N/A"
    log_entry = f"[{timestamp}] [REQUEST={request_id}] ERROR: {error_message}\n"
    try:
        with open(config.ERROR_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(log_entry)
        print(log_entry.strip())
    except Exception as e:
        print(f"[日志系统错误] 写入错误日志失败: {str(e)} | 原始错误: {error_message}")


def clean_table_name(table_name: str) -> tuple[str, str]:
    """
    清理表名中的反引号和提取数据库前缀
    优化点：无schema时使用配置的默认数据库
    """
    # 移除反引号
    cleaned = re.sub(r'`', '', table_name)
    # 分割数据库和表名（如果存在）
    parts = cleaned.split('.')
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()  # (数据库名, 表名)
    # 无schema时使用默认数据库
    return config.DEFAULT_DB_SCHEMA, cleaned.strip()  # (默认数据库, 表名)


def get_table_info(table_name: str, request_id: str) -> Dict[str, Any]:
    """获取表的 DDL 和行数，优化无schema表名的处理"""
    db_name, clean_name = clean_table_name(table_name)
    write_operation_log(f"开始获取表 {table_name} 的信息 (清理后: {db_name}.{clean_name})", request_id)
    
    try:
        # 获取数据库配置，指定数据库名
        db_config = get_db_config(db_name)
        write_operation_log(f"使用数据库配置: host={db_config['host']}, port={db_config['port']}, database={db_name}, user={db_config['user']}", request_id)
        
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # 获取表的 DDL
        cursor.execute(f"SHOW CREATE TABLE `{clean_name}`")
        create_table = cursor.fetchone()
        ddl = create_table['Create Table'] if create_table else None
        write_operation_log(f"成功获取表 {db_name}.{clean_name} 的DDL信息", request_id)
        
        # 获取表的行数（快速近似值）
        cursor.execute(f"SHOW TABLE STATUS LIKE '{clean_name}'")
        table_status = cursor.fetchone()
        row_count = table_status['Rows'] if table_status else None
        write_operation_log(f"成功获取表 {db_name}.{clean_name} 的行数信息: {row_count}", request_id)
        
        result = {
            'table_name': table_name,
            'cleaned_name': f"{db_name}.{clean_name}",
            'database': db_name,
            'table': clean_name,
            'ddl': ddl,
            'row_count': row_count,
            'error': None
        }
        
        cursor.close()
        conn.close()
        write_operation_log(f"完成表 {table_name} 的信息获取", request_id)
        return result
        
    except mysql.connector.Error as e:
        # 更详细的数据库错误处理
        error_msg = f"数据库错误 (代码: {e.errno}): {e.msg}"
        write_error_log(f"获取表 {db_name}.{clean_name} 信息失败: {error_msg}", request_id)
        return {
            'table_name': table_name,
            'cleaned_name': f"{db_name}.{clean_name}",
            'database': db_name,
            'table': clean_name,
            'error': error_msg,
            'ddl': None,
            'row_count': None
        }
    except Exception as e:
        error_msg = f"获取表信息失败: {str(e)}"
        write_error_log(f"获取表 {db_name}.{clean_name} 信息失败: {error_msg}", request_id)
        return {
            'table_name': table_name,
            'cleaned_name': f"{db_name}.{clean_name}",
            'database': db_name,
            'table': clean_name,
            'error': error_msg,
            'ddl': None,
            'row_count': None
        }


def generate_report_title(log_data: Dict[str, Any]) -> str:
    """生成报告标题，包含关键信息"""
    query_time = log_data.get('query_time', '未知')
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tables_str = log_data.get('tables_str', '多个表')
    
    # 提取SQL中的主要操作（SELECT/UPDATE/DELETE等）
    sql_body = log_data.get('log', '').upper()
    operation = '查询'
    if 'UPDATE' in sql_body:
        operation = '更新'
    elif 'DELETE' in sql_body:
        operation = '删除'
    elif 'INSERT' in sql_body:
        operation = '插入'
    
    return f"{timestamp} - 慢{operation}分析报告（耗时: {query_time}秒，涉及表: {tables_str[:50]}）"


def generate_prompt(log_data: Dict[str, Any], table_info_list: List[Dict[str, Any]], request_id: str) -> str:
    """生成发送给大模型的提示词"""
    write_operation_log("开始生成提示词", request_id)
    
    prompt = f"""请分析以下MySQL慢查询日志，并提供优化建议。

慢查询日志详情:
{log_data['log']}

查询时间: {log_data['query_time']} 秒
锁定时间: {log_data['lock_time']} 秒
返回行数: {log_data['rows_sent']}
扫描行数: {log_data['rows_examined']}

涉及表结构及行数:
"""
    for table_info in table_info_list:
        if table_info['error']:
            prompt += f"- 表 {table_info['cleaned_name']}: 错误 - {table_info['error']}\n"
        else:
            prompt += f"- 表 {table_info['cleaned_name']} (约 {table_info['row_count']} 行):\n"
            prompt += f"  DDL: {table_info['ddl'][:500]}...\n\n"
    
    prompt += """
请基于以上信息，分析该慢查询的性能问题原因，并提供具体的优化建议，包括但不限于:
1. 索引优化建议
2. SQL语句改写建议
3. 表结构优化建议
4. 其他可能的性能改进方案

请提供详细且可操作的建议，避免泛泛而谈。
"""
    
    write_operation_log(f"提示词生成完成，长度: {len(prompt)}字符", request_id)
    return prompt


async def call_deepseek_api(prompt: str, request_id: str) -> str:
    """调用DeepSeek API生成分析报告"""
    write_operation_log("开始调用DeepSeek API", request_id)
    
    try:
        client = init_llm_client()
        response = await client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是一位数据库性能优化专家，擅长分析MySQL慢查询并提供优化建议。"},
                {"role": "user", "content": prompt}
            ],
            temperature=config.LLM_TEMPERATURE,
            max_tokens=config.LLM_MAX_TOKENS,
            stream=False
        )
        
        write_operation_log(f"API调用成功，响应ID: {response.id}", request_id)
        write_operation_log(
            f"Token使用情况: 输入={response.usage.prompt_tokens}, 输出={response.usage.completion_tokens}",
            request_id
        )
        
        return response.choices[0].message.content
        
    except APIError as e:
        error_msg = f"LLM API错误 (状态码: {e.status_code}): {e.message}"
        write_error_log(error_msg, request_id)
        return f"分析失败: {error_msg}"
    except APIConnectionError as e:
        error_msg = f"LLM连接错误: {str(e)}"
        write_error_log(error_msg, request_id)
        return f"分析失败: {error_msg}"
    except Timeout as e:
        error_msg = f"LLM调用超时: {str(e)}"
        write_error_log(error_msg, request_id)
        return f"分析失败: {error_msg}"
    except Exception as e:
        error_msg = f"LLM调用未知错误: {str(e)}"
        write_error_log(error_msg, request_id)
        return f"分析失败: {error_msg}"


def append_to_report(report_data: Dict[str, Any], request_id: str) -> bool:
    """将报告数据追加到slow_report.json数组中"""
    write_operation_log(f"开始将报告追加到 {config.SLOW_REPORT_PATH}", request_id)
    
    try:
        # 读取现有报告
        existing_reports = []
        if os.path.exists(config.SLOW_REPORT_PATH):
            try:
                with open(config.SLOW_REPORT_PATH, 'r', encoding='utf-8') as f:
                    existing_reports = json.load(f)
                write_operation_log(f"成功读取现有报告，共{len(existing_reports)}条记录", request_id)
            except json.JSONDecodeError:
                write_error_log("报告文件损坏，将重新初始化", request_id)
                existing_reports = []
        
        # 添加新报告
        existing_reports.append(report_data)
        
        # 写入更新后的报告
        with open(config.SLOW_REPORT_PATH, 'w', encoding='utf-8') as f:
            json.dump(existing_reports, f, ensure_ascii=False, indent=2)
        
        write_operation_log(f"报告已成功追加到 {config.SLOW_REPORT_PATH}", request_id)
        return True
        
    except Exception as e:
        error_msg = f"追加报告到文件失败: {str(e)}"
        write_error_log(error_msg, request_id)
        return False


def extract_valid_log_records(ndjson_data: List[str], request_id: str) -> List[Dict[str, Any]]:
    """解析NDJSON数据并提取有效的日志记录"""
    write_operation_log(f"开始解析NDJSON数据，共{len(ndjson_data)}行", request_id)
    records = []
    
    for i, line in enumerate(ndjson_data):
        line = line.strip()
        if not line:
            write_operation_log(f"第{i+1}行是空白行，已忽略", request_id)
            continue
            
        try:
            record = json.loads(line)
            if isinstance(record, dict) and 'log' in record and 'tables' in record:
                records.append(record)
                write_operation_log(f"第{i+1}行NDJSON解析成功，包含有效日志记录", request_id)
            else:
                missing_fields = []
                if 'log' not in record:
                    missing_fields.append('log')
                if 'tables' not in record:
                    missing_fields.append('tables')
                write_operation_log(
                    f"第{i+1}行NDJSON缺少必要字段: {', '.join(missing_fields)}，已忽略", 
                    request_id
                )
        except json.JSONDecodeError as e:
            error_msg = f"第{i+1}行NDJSON解析失败: {str(e)}"
            write_error_log(error_msg, request_id)
    
    write_operation_log(f"NDJSON解析完成，共获取{len(records)}条有效日志记录", request_id)
    return records


async def process_analysis_background(log_records: List[Dict[str, Any]], request_id: str) -> None:
    """后台处理分析流程"""
    try:
        write_operation_log(f"开始后台分析流程，共处理{len(log_records)}条记录", request_id)
        
        for record_idx, log_data in enumerate(log_records):
            write_operation_log(f"开始处理第{record_idx+1}/{len(log_records)}条记录", request_id)
            
            # 1. 生成报告标题
            report_title = generate_report_title(log_data)
            write_operation_log(f"生成报告标题: {report_title}", request_id)
            
            # 2. 获取所有表的信息
            table_info_list = []
            for table_name in log_data.get('tables', []):
                table_info = get_table_info(table_name, request_id)
                table_info_list.append(table_info)
            
            # 3. 生成提示词并调用API
            prompt = generate_prompt(log_data, table_info_list, request_id)
            analysis_report = await call_deepseek_api(prompt, request_id)
            
            # 4. 准备报告数据
            report_data = {
                "id": f"{request_id}-record-{record_idx+1}",
                "title": report_title,
                "request_id": request_id,
                "record_index": record_idx + 1,
                "total_records": len(log_records),
                "timestamp": datetime.now().isoformat(),
                "original_data": {
                    "query_time": log_data.get('query_time'),
                    "lock_time": log_data.get('lock_time'),
                    "rows_sent": log_data.get('rows_sent'),
                    "rows_examined": log_data.get('rows_examined'),
                    "log": log_data.get('log'),
                    "tables": log_data.get('tables')
                },
                "table_info": table_info_list,
                "analysis_report": analysis_report
            }
            
            # 5. 追加到报告文件
            if append_to_report(report_data, request_id):
                write_operation_log(f"第{record_idx+1}条记录分析报告已追加到汇总文件", request_id)
            else:
                write_error_log(f"第{record_idx+1}条记录分析报告追加失败", request_id)
        
        write_operation_log("所有记录分析完成", request_id)
        
    except Exception as e:
        write_error_log(f"后台分析流程失败: {str(e)}", request_id)


def run_async_task(log_records: List[Dict[str, Any]], request_id: str) -> None:
    """线程包装器，运行异步任务"""
    try:
        write_operation_log("启动异步处理线程", request_id)
        asyncio.run(process_analysis_background(log_records, request_id))
    except Exception as e:
        write_error_log(f"异步任务执行失败: {str(e)}", request_id)


@app.route('/analyze-slow-query', methods=['POST'])
def analyze_slow_query():
    """分析慢查询日志的API端点"""
    # 生成唯一请求ID
    request_id = datetime.now().strftime("%Y%m%d%H%M%S") + f"-{os.urandom(4).hex()}"
    write_operation_log("收到慢查询分析请求", request_id)
    
    try:
        # 记录请求基本信息
        call_timestamp = datetime.now().isoformat()
        write_operation_log(
            f"请求信息 - 方法: {request.method}, 客户端IP: {request.remote_addr}, Content-Type: {request.content_type}",
            request_id
        )
        
        # 验证内容类型
        if request.content_type != config.SUPPORTED_CONTENT_TYPE:
            error_msg = f"不支持的Content-Type: {request.content_type}，仅接受{config.SUPPORTED_CONTENT_TYPE}"
            write_error_log(error_msg, request_id)
            return Response(
                json.dumps({
                    "status": "error",
                    "message": error_msg,
                    "request_id": request_id
                }, ensure_ascii=False, indent=2),
                mimetype="application/json",
                status=415
            )
        
        # 解析NDJSON数据
        write_operation_log("开始读取并解析NDJSON数据", request_id)
        try:
            ndjson_data = request.data.decode('utf-8').splitlines()
            write_operation_log(f"成功读取{len(ndjson_data)}行NDJSON数据", request_id)
        except UnicodeDecodeError as e:
            error_msg = f"数据解码失败: {str(e)}"
            write_error_log(error_msg, request_id)
            return Response(
                json.dumps({
                    "status": "error",
                    "message": error_msg,
                    "request_id": request_id
                }, ensure_ascii=False, indent=2),
                mimetype="application/json",
                status=400
            )
        
        # 提取有效日志记录
        log_records = extract_valid_log_records(ndjson_data, request_id)
        
        # 未找到有效日志时返回正常响应
        if not log_records:
            write_operation_log("未找到有效日志记录，返回正常响应", request_id)
            return Response(
                json.dumps({
                    "status": "completed",
                    "message": "未找到需要处理的有效日志记录",
                    "request_id": request_id,
                    "total_lines_received": len(ndjson_data),
                    "valid_records_found": 0
                }, ensure_ascii=False, indent=2),
                mimetype="application/json",
                status=200
            )
        
        # 有有效日志时启动后台处理
        thread = threading.Thread(
            target=run_async_task,
            args=(log_records, request_id),
            daemon=True
        )
        thread.start()
        write_operation_log("后台处理线程已启动", request_id)
        
        # 返回接受响应
        response_data = {
            "status": "accepted",
            "message": "请求已接收，正在后台处理",
            "request_id": request_id,
            "timestamp": call_timestamp,
            "total_records": len(log_records),
            "total_lines_received": len(ndjson_data)
        }
        
        # write_operation_log("请求处理完成，返回响应", request_id)
        return Response(
            json.dumps(response_data, ensure_ascii=False, indent=2),
            mimetype="application/json",
            status=200
        )
        
    except Exception as e:
        # 仅逻辑错误返回错误响应
        error_msg = f"请求处理失败: {str(e)}"
        write_error_log(error_msg, request_id)
        return Response(
            json.dumps({
                "status": "error",
                "message": error_msg,
                "request_id": request_id
            }, ensure_ascii=False, indent=2),
            mimetype="application/json",
            status=500
        )


@app.route('/health', methods=['GET'])
def health_check():
    """健康检查接口"""
    request_id = f"health-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    write_operation_log("收到健康检查请求", request_id)
    
    # 检查LLM客户端
    llm_status = "healthy"
    llm_details = "未初始化"
    try:
        init_llm_client()
        llm_status = "healthy"
        llm_details = "客户端已初始化"
    except Exception as e:
        llm_status = "degraded"
        llm_details = f"初始化失败: {str(e)}"
    
    # 检查数据库连接
    db_status = "healthy"
    db_details = "连接成功"
    try:
        conn = mysql.connector.connect(** get_db_config())
        conn.close()
    except Exception as e:
        db_status = "degraded"
        db_details = f"连接失败: {str(e)}"
    
    # 检查报告文件
    report_status = "healthy"
    report_details = "文件正常"
    try:
        if not os.path.exists(config.SLOW_REPORT_PATH):
            report_status = "warning"
            report_details = "报告文件不存在，将在首次分析后创建"
        else:
            with open(config.SLOW_REPORT_PATH, 'r') as f:
                pass  # 仅检查文件是否可读取
    except Exception as e:
        report_status = "degraded"
        report_details = f"报告文件访问失败: {str(e)}"
    
    # 整体状态
    overall_status = "healthy"
    if llm_status != "healthy" or db_status != "healthy" or report_status == "degraded":
        overall_status = "degraded"
    
    response = {
        "status": overall_status,
        "services": {
            "llm_client": {
                "status": llm_status,
                "details": llm_details
            },
            "database": {
                "status": db_status,
                "details": db_details
            },
            "report_file": {
                "status": report_status,
                "details": report_details,
                "path": config.SLOW_REPORT_PATH
            }
        },
        "supported_content_type": config.SUPPORTED_CONTENT_TYPE,
        "default_schema": config.DEFAULT_DB_SCHEMA,
        "timestamp": datetime.now().isoformat(),
        "request_id": request_id
    }
    
    write_operation_log("健康检查完成", request_id)
    return Response(
        json.dumps(response, ensure_ascii=False, indent=2),
        mimetype="application/json"
    )


if __name__ == '__main__':
    print("慢查询分析API启动中...")
    print(f"服务器配置: {config.HOST}:{config.PORT} (调试模式: {'开启' if config.DEBUG else '关闭'})")
    print(f"内容类型支持: {config.SUPPORTED_CONTENT_TYPE}")
    print(f"默认数据库schema: {config.DEFAULT_DB_SCHEMA}")
    print(f"报告文件路径: {config.SLOW_REPORT_PATH}")
    print(f"LLM配置: 模型={config.LLM_MODEL}, 基础URL={config.LLM_BASE_URL}")
    print(f"日志目录: {config.LOG_DIR}")
    print("环境变量检查:")
    print(f"  - DEEPSEEK_API_KEY: {'已配置' if os.getenv('DEEPSEEK_API_KEY') else '未配置'}")
    print(f"  - 数据库配置: HOST={os.getenv('DB_HOST', 'localhost')}, USER={os.getenv('DB_USER', 'root')}")
    print("可用接口:")
    print("  - POST /analyze-slow-query - 分析慢查询日志")
    print("  - GET  /health - 健康检查")
    
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
    