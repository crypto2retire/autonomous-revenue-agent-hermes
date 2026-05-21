FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Run the autonomous revenue agent (not the Hermes CLI)
CMD ["python", "-c", "import asyncio; from main import main; asyncio.run(main())"]
