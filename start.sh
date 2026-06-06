#!/bin/bash

# Deep Research 项目启动脚本
# 用于本地开发和演示

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查 Java 版本
check_java() {
    print_info "检查 Java 版本..."
    if ! command -v java &> /dev/null; then
        print_error "未找到 Java，请安装 Java 21"
        exit 1
    fi

    JAVA_VERSION=$(java -version 2>&1 | head -n 1 | cut -d'"' -f2 | cut -d'.' -f1)
    if [ "$JAVA_VERSION" != "21" ]; then
        print_error "当前 Java 版本为 $JAVA_VERSION，需要 Java 21"
        exit 1
    fi
    print_success "Java 版本检查通过: $(java -version 2>&1 | head -n 1)"
}

# 检查 Maven
check_maven() {
    print_info "检查 Maven..."
    if ! command -v mvn &> /dev/null; then
        print_error "未找到 Maven，请安装 Maven 3.8+"
        exit 1
    fi
    print_success "Maven 版本: $(mvn -version 2>&1 | head -n 1)"
}

# 检查 MySQL 连接
check_mysql() {
    print_info "检查 MySQL 连接..."

    # 使用环境变量或默认值
    DB_HOST=${DB_HOST:-127.0.0.1}
    DB_PORT=${DB_PORT:-3306}
    DB_USERNAME=${DB_USERNAME:-root}
    DB_PASSWORD=${DB_PASSWORD:-}
    DB_NAME=${DB_NAME:-db_deep_research}

    # 尝试连接 MySQL
    if command -v mysql &> /dev/null; then
        if [ -z "$DB_PASSWORD" ]; then
            mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USERNAME" -e "SELECT 1" &> /dev/null
        else
            mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USERNAME" -p"$DB_PASSWORD" -e "SELECT 1" &> /dev/null
        fi

        if [ $? -eq 0 ]; then
            print_success "MySQL 连接成功"
        else
            print_error "无法连接到 MySQL"
            print_info "请确保 MySQL 服务已启动，并检查以下配置："
            print_info "  DB_HOST=$DB_HOST"
            print_info "  DB_PORT=$DB_PORT"
            print_info "  DB_USERNAME=$DB_USERNAME"
            exit 1
        fi
    else
        print_warning "未找到 mysql 客户端，跳过连接检查"
    fi
}

# 创建数据库（如果不存在）
create_database() {
    print_info "检查并创建数据库..."

    DB_HOST=${DB_HOST:-127.0.0.1}
    DB_PORT=${DB_PORT:-3306}
    DB_USERNAME=${DB_USERNAME:-root}
    DB_PASSWORD=${DB_PASSWORD:-}
    DB_NAME=${DB_NAME:-db_deep_research}

    if command -v mysql &> /dev/null; then
        CREATE_DB_SQL="CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
        if [ -z "$DB_PASSWORD" ]; then
            mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USERNAME" -e "$CREATE_DB_SQL"
        else
            mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USERNAME" -p"$DB_PASSWORD" -e "$CREATE_DB_SQL"
        fi

        if [ $? -eq 0 ]; then
            print_success "数据库 $DB_NAME 已就绪"
        else
            print_error "创建数据库失败"
            exit 1
        fi
    else
        print_warning "未找到 mysql 客户端，请手动创建数据库: $DB_NAME"
    fi
}

# 初始化数据库表
init_database() {
    print_info "初始化数据库表..."

    DB_HOST=${DB_HOST:-127.0.0.1}
    DB_PORT=${DB_PORT:-3306}
    DB_USERNAME=${DB_USERNAME:-root}
    DB_PASSWORD=${DB_PASSWORD:-}
    DB_NAME=${DB_NAME:-db_deep_research}

    SQL_FILE="src/main/resources/data.sql"

    if [ ! -f "$SQL_FILE" ]; then
        print_warning "未找到 SQL 文件: $SQL_FILE"
        return
    fi

    if command -v mysql &> /dev/null; then
        if [ -z "$DB_PASSWORD" ]; then
            mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USERNAME" "$DB_NAME" < "$SQL_FILE"
        else
            mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USERNAME" -p"$DB_PASSWORD" "$DB_NAME" < "$SQL_FILE"
        fi

        if [ $? -eq 0 ]; then
            print_success "数据库表初始化完成"
        else
            print_warning "数据库表初始化失败（可能已存在）"
        fi
    else
        print_warning "未找到 mysql 客户端，请手动执行 SQL 文件: $SQL_FILE"
    fi
}

# 检查 Redis 连接
check_redis() {
    print_info "检查 Redis 连接..."

    REDIS_HOST=${REDIS_HOST:-127.0.0.1}
    REDIS_PORT=${REDIS_PORT:-6379}
    REDIS_PASSWORD=${REDIS_PASSWORD:-}

    if command -v redis-cli &> /dev/null; then
        if [ -z "$REDIS_PASSWORD" ]; then
            redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping &> /dev/null
        else
            redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" ping &> /dev/null
        fi

        if [ $? -eq 0 ]; then
            print_success "Redis 连接成功"
        else
            print_error "无法连接到 Redis"
            print_info "请确保 Redis 服务已启动，并检查以下配置："
            print_info "  REDIS_HOST=$REDIS_HOST"
            print_info "  REDIS_PORT=$REDIS_PORT"
            exit 1
        fi
    else
        print_warning "未找到 redis-cli，跳过连接检查"
    fi
}

# 编译项目
build_project() {
    print_info "编译项目..."
    mvn clean package -DskipTests -q

    if [ $? -eq 0 ]; then
        print_success "项目编译成功"
    else
        print_error "项目编译失败"
        exit 1
    fi
}

# 启动应用
start_app() {
    print_info "启动 Deep Research 应用..."

    # 查找 JAR 文件
    JAR_FILE=$(find target -name "*.jar" -not -name "*-sources.jar" | head -n 1)

    if [ -z "$JAR_FILE" ]; then
        print_error "未找到 JAR 文件"
        exit 1
    fi

    print_success "找到 JAR 文件: $JAR_FILE"
    print_info "应用启动中..."
    print_info "访问地址: http://localhost:8080"
    print_info "API 文档: http://localhost:8080/swagger-ui.html"
    print_info "按 Ctrl+C 停止应用"
    echo ""

    # 启动应用
    java -jar "$JAR_FILE"
}

# 主函数
main() {
    echo ""
    echo "=========================================="
    echo "   Deep Research 项目启动脚本"
    echo "=========================================="
    echo ""

    # 检查环境
    check_java
    check_maven

    # 检查服务
    check_mysql
    create_database
    init_database
    check_redis

    # 编译并启动
    build_project
    start_app
}

# 运行主函数
main
