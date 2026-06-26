#!/bin/bash
export JAVA_HOME="C:/Program Files/Eclipse Adoptium/jdk-21.0.11.10-hotspot"
export PATH="$JAVA_HOME/bin:$PATH"

# 从宿主机连接 Docker 里的 MySQL/Redis，使用 127.0.0.1
export DB_URL="jdbc:mysql://127.0.0.1:3306/db_deep_research?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai"
export DB_USERNAME="deepresearch"
export DB_PASSWORD="deepresearch"
export REDIS_HOST="127.0.0.1"
export REDIS_PORT="6379"
export REDIS_PASSWORD=""

# 读取 .env 里的其他配置（TAVILY_KEY 等）
export TAVILY_API_KEY="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"
export TAVILY_BASE_URL="https://api.tavily.com"
export TAVILY_CACHE_ENABLED="true"
export TAVILY_CACHE_TTL_MINUTES="60"
export TAVILY_CACHE_MAX_ENTRIES="512"
export RESEARCH_SEARCH_MAX_RESULTS_PER_QUERY="3"
export RESEARCH_SEARCH_SUMMARY_TIMEOUT_SECONDS="60"
export RESEARCH_SEARCH_SUMMARY_RAW_CONTENT_MAX_CHARS="12000"
export RESEARCH_SEARCH_SUMMARY_FALLBACK_CONTENT_MAX_CHARS="1200"
export RESEARCH_SEARCH_SUMMARY_CACHE_ENABLED="true"
export RESEARCH_SEARCH_SUMMARY_CACHE_TTL_MINUTES="60"
export RESEARCH_SEARCH_SUMMARY_CACHE_MAX_ENTRIES="1024"
export JWT_SECRET="deep-research-jwt-secret-key-must-be-at-least-32-chars"
export APP_TIME_ZONE="Asia/Shanghai"
export RESEARCH_AGENT_FRAMEWORK="agentscope-java"
export LLM_TIMEOUT="120"
export LLM_LOG_REQUESTS="false"
export LLM_LOG_RESPONSES="false"
export RESEARCH_OBSERVABILITY_ENABLED="false"
export RESEARCH_OBSERVABILITY_PROVIDER="none"
export AGENTSCOPE_STUDIO_ENABLED="false"

echo "JAVA_HOME=$JAVA_HOME"
echo "DB_URL=$DB_URL"
echo "Starting Spring Boot..."
cd "C:/Users/zzy20/MyCodeSpace/deep-research"
"$JAVA_HOME/bin/java" --version
./mvnw spring-boot:run -DskipTests
