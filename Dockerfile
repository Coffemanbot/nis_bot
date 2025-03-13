FROM python:3.10

WORKDIR /app

COPY requirments.txt /app/

RUN pip install --no-cache-dir -r requirments.txt

RUN playwright install --with-deps chromium

COPY . /app

CMD ["python", "main.py"]