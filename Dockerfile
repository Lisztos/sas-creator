FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

# Install display and VNC packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    x11vnc \
    fluxbox \
    fonts-liberation \
    fonts-noto-color-emoji \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install noVNC
RUN mkdir -p /opt/novnc/utils/websockify \
    && wget -qO- https://github.com/novnc/noVNC/archive/refs/tags/v1.5.0.tar.gz | tar xz --strip-components=1 -C /opt/novnc \
    && wget -qO- https://github.com/novnc/websockify/archive/refs/tags/v0.12.0.tar.gz | tar xz --strip-components=1 -C /opt/novnc/utils/websockify \
    && chmod +x /opt/novnc/utils/novnc_proxy

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy application code
COPY src/ ./src/

# Re-install with source code present (hatchling needs src/)
RUN pip install --no-cache-dir .

# Install Playwright browsers (Chromium only)
RUN playwright install chromium

# Copy entrypoint
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Environment defaults
ENV DISPLAY=:99 \
    VNC_PORT=5900 \
    NOVNC_PORT=6080 \
    SCREEN_WIDTH=1280 \
    SCREEN_HEIGHT=900 \
    SCREEN_DEPTH=24

EXPOSE 6080

ENTRYPOINT ["/entrypoint.sh"]
