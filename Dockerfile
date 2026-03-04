# Stage 1: Base build stage
FROM python:3.14-slim AS builder

# Create the app directory
RUN mkdir /app

# Set the working directory
WORKDIR /app

# Set environment variables to optimize Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Upgrade pip and install dependencies
RUN pip install --upgrade pip

# Copy the requirements file first (better caching)
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Production stage
FROM python:3.14-slim

RUN useradd -m -r appuser && \
    mkdir /app && \
    chown -R appuser /app

# Copy the Python dependencies from the builder stage
COPY --from=builder /usr/local/lib/python3.14/site-packages/ /usr/local/lib/python3.14/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/
RUN apt update -y && apt install -y nginx locales git && locale-gen de_DE.UTF-8 && rm -f /etc/nginx/sites-enabled/default
# Set the working directory
COPY nginx.conf /etc/nginx/
WORKDIR /app

# Copy application code
#COPY --chown=appuser:appuser . .

# Set environment variables to optimize Python
ENV LANG=de_DE.UTF-8
ENV LC_ALL=de_DE.UTF-8

# Switch to non-root user
#USER appuser

# Expose the application port
EXPOSE 8000

# Start the application using Gunicorn
CMD ["/app/start.sh"]
