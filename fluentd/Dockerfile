# 使用的基础镜像
FROM fluent/fluentd:v1.19.0-debian-amd64-2.0
# 切换用户为root方便接下来执行安装命令
USER root
# 安装系统依赖
RUN apt-get update && \
    apt-get install -y curl && \
    rm -rf /var/lib/apt/lists/*

# 卸载可能存在的高版本 Elasticsearch gem
RUN gem uninstall elasticsearch elasticsearch-api -a -x || true

# 安装指定版本 gem 和 Fluentd Elasticsearch 插件
RUN gem install elasticsearch -v 8.17.1 --no-document && \
    gem install elasticsearch-api -v 8.17.1 --no-document && \
    gem install fluent-plugin-elasticsearch -v 5.4.3 --no-document
USER fluent