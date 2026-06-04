# EFK + MySQL 慢查询智能分析系统

基于 EFK（Elasticsearch + Fluent Bit + Fluentd）日志采集架构，结合 DeepSeek AI 大模型，实现 MySQL 慢查询日志的自动采集、解析、存储和智能分析。

## 系统架构

    MySQL 5.7  -->  Fluent Bit  -->  Fluentd  -->  Elasticsearch 8
    (慢查询日志)    (日志采集)      (解析转发)      (数据存储)
                                    |                |
                                    v                v
                              Flask API          Kibana
                            (DeepSeek AI)       (可视化展示)
                                    |
                                    v
                              Streamlit App
                              (报告查看器)

**数据流向：**

1. MySQL 开启慢查询日志（阈值 3 秒）
2. Fluent Bit 实时采集慢日志文件，使用多行解析器合并跨行日志
3. Fluentd 接收日志，正则解析提取关键字段，转发到 ES 和 Flask API
4. Elasticsearch 存储结构化日志数据，Kibana 提供可视化查询
5. Flask API 接收慢查询日志，调用 DeepSeek AI 生成优化建议报告
6. Streamlit 应用展示分析报告，支持查看表结构详情

## 目录结构

    /data/
    +-- README.md                          # 项目说明文档
    +-- run.txt                            # 启动命令汇总
    +-- mysql-5.7/                         # MySQL 数据目录
    |   +-- conf/my.cnf                    # MySQL 配置（慢日志相关）
    |   +-- data/                          # 数据库数据文件
    |   +-- logs/slow.log                  # 慢查询日志文件
    +-- fluent-bit/                        # Fluent Bit 配置
    |   +-- etc/
    |       +-- fluent-bit.conf            # 主配置（输入/输出）
    |       +-- parsers_mysql_slow.conf    # MySQL 慢日志多行解析器
    +-- fluentd/                           # Fluentd 配置
    |   +-- Dockerfile                     # 自定义镜像（含 ES 插件）
    |   +-- conf/fluent.conf              # 主配置（输入/过滤/输出）
    +-- mysql/                             # Python 应用
        +-- .env                           # 环境变量（API Key、数据库配置）
        +-- process_slow_log.py            # Flask API（AI 分析服务）
        +-- show_slow_report.py            # Streamlit 报告查看器
        +-- logs/                          # 应用日志
        +-- reports/slow_report.json       # 分析报告存储

## 环境要求

- Docker
- Python 3.9+
- 服务器内存建议 4GB+（ES 默认占用 512MB）

## 快速部署

### 1. 创建 Docker 网络

```bash
docker network create efk-net
```

### 2. 启动 MySQL 5.7

```bash
docker run -d \
  --name mysql-5.7 \
  --network efk-net \
  --restart always \
  -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=Abc@1234 \
  -v /data/mysql-5.7/data:/var/lib/mysql \
  -v /data/mysql-5.7/logs:/var/log/mysql \
  -v /data/mysql-5.7/conf/my.cnf:/etc/mysql/conf.d/my.cnf \
  mysql:5.7
```

### 3. 启动 Elasticsearch

```bash
docker run -d \
  --name elasticsearch \
  --network efk-net \
  -p 9200:9200 \
  -e discovery.type=single-node \
  -e xpack.security.enabled=false \
  -e ES_JAVA_OPTS=-Xms512m -Xmx512m \
  -e cluster.name=efk-cluster \
  elasticsearch:8.13.0
```

### 4. 启动 Kibana

```bash
docker run -d \
  --name kibana \
  --network efk-net \
  -p 5601:5601 \
  -e ELASTICSEARCH_HOSTS=http://elasticsearch:9200 \
  kibana:8.13.0
```

### 5. 构建并启动 Fluentd

```bash
cd /data/fluentd && docker build -t fluentd-custom:v1 .

docker run -d \
  --name fluentd \
  --network efk-net \
  -p 24224:24224 \
  -p 24224:24224/udp \
  -p 24220:24220 \
  -v /data/fluentd/conf/fluent.conf:/fluentd/etc/fluent.conf \
  fluentd-custom:v1
```

### 6. 启动 Fluent Bit

```bash
docker run -d \
  --name fluent-bit \
  --network efk-net \
  -v /data/fluent-bit/etc:/fluent-bit/etc \
  -v /data/mysql-5.7/logs/slow.log:/var/log/mysql/slow.log \
  cr.fluentbit.io/fluent/fluent-bit:3.0
```

### 7. 启动 AI 分析 API

```bash
pip install flask openai mysql-connector-python
```

编辑 `/data/mysql/.env`：

```bash
DEEPSEEK_API_KEY=your_api_key
DB_HOST=127.0.0.1
DB_USER=root
DB_PASSWORD=your_password
DB_PORT=3306
```

启动服务：

```bash
cd /data/mysql
export $(grep -v '^#' .env | xargs)
nohup python3 process_slow_log.py > logs/flask_output.log 2>&1 &
```

### 8. 启动报告查看器

```bash
pip install streamlit

cd /data/mysql
nohup python3 -m streamlit run show_slow_report.py \
  --server.port 8501 \
  --server.address 0.0.0.0 \
  --server.headless true > logs/streamlit_output.log 2>&1 &
```

## 访问地址

| 服务            | 地址                | 说明              |
|-----------------|--------------------|--------------------|
| MySQL           | 服务器IP:3306       | 数据库连接         |
| Elasticsearch   | 服务器IP:9200       | ES REST API        |
| Kibana          | 服务器IP:5601       | 日志可视化         |
| AI 分析 API     | 服务器IP:5001       | 慢查询分析接口     |
| 报告查看器      | 服务器IP:8501       | Streamlit 报告页面 |

## 配置说明

### MySQL 慢日志配置（my.cnf）

```ini
[mysqld]
slow_query_log = 1
slow_query_log_file = /var/log/mysql/slow.log
long_query_time = 3
```

### Fluent Bit 关键配置

- **输入**：tail 插件监控 `/var/log/mysql/slow.log`，使用 `mysql_slow` 多行解析器
- **输出**：forward 插件转发到 Fluentd（端口 24224）

### Fluentd 关键配置

- **输入**：forward 插件接收 Fluent Bit 数据
- **过滤**：正则解析提取 time、user_host、query_time、lock_time、rows_sent、rows_examined、tables
- **输出**：Elasticsearch（索引 `fluentd-mysql.slow-YYYYMMDD`）、HTTP（POST 到 Flask API）、stdout

### 环境变量（.env）

```bash
DEEPSEEK_API_KEY=your_deepseek_api_key   # DeepSeek API 密钥
DB_HOST=127.0.0.1                          # MySQL 地址
DB_USER=root                               # MySQL 用户名
DB_PASSWORD=your_password                  # MySQL 密码
DB_PORT=3306                               # MySQL 端口
```

## Kibana 使用

1. 访问 `http://服务器IP:5601`
2. 进入 **Management > Stack Management > Index Patterns**
3. 创建索引模式：`fluentd-mysql.slow*`
4. 进入 **Discover** 页面查看慢查询日志
5. 可按 `query_time_float`、`tables`、`user_host` 等字段过滤和排序

## API 接口

### POST /analyze-slow-query

接收 Fluentd 转发的慢查询 NDJSON 数据，调用 AI 分析并生成报告。

### GET /health

健康检查，返回各服务状态。

## 常见问题

**Q: Kibana 看不到数据？**
A: 检查 ES 索引：`curl http://localhost:9200/_cat/indices?v`，确认有 `fluentd-mysql.slow-*` 索引。

**Q: 报告中表结构获取失败？**
A: 确认 `.env` 中 `DB_HOST` 指向正确的 MySQL 地址，且数据库用户有访问目标库的权限。

**Q: Fluentd 报 connection refused？**
A: 确认所有容器在同一 Docker 网络中，检查 ES 和 Flask API 是否正常运行。
