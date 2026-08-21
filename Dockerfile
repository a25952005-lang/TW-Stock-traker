FROM python:3.12-slim

WORKDIR /src
COPY . .

# GitHub 上目前是「攤平」結構（所有檔案都在根目錄，沒有 backend/frontend 子資料夾），
# 這裡在建置時自動依檔名歸位，避免還要手動搬檔案跟改程式碼路徑。
RUN mkdir -p /app/backend /app/frontend && \
    mv main.py finmind_service.py market_service.py calendar_service.py requirements.txt /app/backend/ && \
    mv index.html stock.html calendar.html style.css common.js /app/frontend/

WORKDIR /app/backend
RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
