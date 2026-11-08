FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y gcc g++ && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m spacy download nl_core_news_sm
RUN python -c "import nltk; nltk.download('punkt_tab'); nltk.download('punkt')"
COPY . .
EXPOSE 8000
# exec so uvicorn becomes PID 1 and receives SIGTERM on redeploys
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
