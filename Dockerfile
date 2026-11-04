# JobPilot-Agent —— 一键容器化部署
# 构建：docker build -t jobpilot-agent .
# 运行：docker compose up -d   （或见 docker-compose.yml）
FROM python:3.12-slim

WORKDIR /app

# 先装依赖层（利用缓存）：pyproject 变化才重装
COPY pyproject.toml README.md LICENSE ./
COPY jobpilot ./jobpilot
COPY data ./data
COPY app.py ./
COPY .streamlit ./.streamlit

# [rag] extra 会拉入 sentence-transformers/torch（约 2GB）
RUN pip install --no-cache-dir -e ".[rag]" && \
    mkdir -p /app/data

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"

# .env 里的 DEEPSEEK_API_KEY 等经 docker-compose env_file 注入，绝不打进镜像
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]