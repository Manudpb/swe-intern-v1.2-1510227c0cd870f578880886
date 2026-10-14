FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    pytest==8.3.4 \
    requests==2.32.3 \
    httpx==0.28.1 \
    Pillow==11.1.0 \
    beautifulsoup4==4.12.3 \
    numpy==2.2.3

COPY tests/ /app/tests/
COPY conftest.py /app/conftest.py
COPY grade.py /app/grade.py
COPY trace_checks.py /app/trace_checks.py

CMD ["python", "grade.py"]
