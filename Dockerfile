FROM python:3.12-slim

# 国内服务器构建慢的话，可以在 deploy/.env 里把 PIP_INDEX_URL 换成镜像源
ARG PIP_INDEX_URL=https://pypi.org/simple

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" -r requirements.txt
COPY server ./server

ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000
CMD ["python", "-m", "server"]
