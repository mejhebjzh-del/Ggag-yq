FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# إعدادات بايثون والمسار الصريح للمشروع
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# تثبيت أدوات مساعدة (curl لفحص الحالة)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# تثبيت المكتبات
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# نسخ الكود والصور
COPY app ./app
COPY media ./media

# إعطاء الصلاحيات للمستخدم الافتراضي لصورة Playwright (pwuser)
RUN chown -R pwuser:pwuser /app

# التحول للمستخدم الآمن (لتجنب مشاكل Playwright)
USER pwuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/health || exit 1

CMD ["python", "-m", "app.main"]
