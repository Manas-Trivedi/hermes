# The Hermes proxy: the matching engine (C++) and the gateway (Python) in one image.
#
#   docker build -t hermes .
#   docker run -v $PWD/deploy/hermes.example.toml:/etc/hermes/hermes.toml:ro -p 8080:8080 hermes
#
# Both stages use the same base so the engine binary finds the libraries it was built against.
FROM ubuntu:24.04 AS engine
RUN apt-get update && apt-get install -y --no-install-recommends gcc-14 g++-14 cmake make ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY engine /src/engine
# Only the engine itself is built; the configure step still fetches GoogleTest, so the build needs network.
RUN cmake -S /src/engine -B /build -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=gcc-14 -DCMAKE_CXX_COMPILER=g++-14 \
    && cmake --build /build --target matcha -j"$(nproc)"

FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --no-create-home hermes
COPY --from=engine /build/matcha /usr/local/bin/matcha
WORKDIR /app
COPY pyproject.toml ./
COPY client client
COPY scheduler scheduler
COPY pricing pricing
COPY store store
COPY feed feed
COPY gateway gateway
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir .
ENV PATH="/opt/venv/bin:$PATH" HERMES_ENGINE=/usr/local/bin/matcha PYTHONUNBUFFERED=1
USER hermes
EXPOSE 8080
# The config must set server.host = "0.0.0.0" and keep server.port = 8080 inside the container.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"
CMD ["python3", "-m", "gateway.proxy", "--config", "/etc/hermes/hermes.toml"]
