FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    libreoffice \
    libreoffice-script-provider-python \
    python3-venv \
    tini \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH="/usr/lib/python3/dist-packages:/usr/lib/libreoffice/program"
ENV UNO_PATH="/usr/lib/libreoffice/program"
ENV URE_BOOTSTRAP="vnd.sun.star.pathname:/usr/lib/libreoffice/program/fundamentalrc"
WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv --system-site-packages /venv
RUN /venv/bin/pip install -r requirements.txt fastapi uvicorn "mcp[cli]"

COPY . .

# Run LibreOffice headless in background and FastMCP SSE server in foreground
RUN echo '#!/bin/bash\nsoffice --headless --accept="socket,host=localhost,port=2083;urp;" &\nsleep 3\n/venv/bin/mcp run libreoffice.py:mcp --transport sse\n' > /app/start.sh && chmod +x /app/start.sh

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/start.sh"]
