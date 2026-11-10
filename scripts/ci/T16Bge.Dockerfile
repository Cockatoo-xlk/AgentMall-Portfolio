# Frozen product runs in a bounded cgroup: its existing memory oracle reads memory.max.
FROM ghcr.io/astral-sh/uv:0.9.18@sha256:5713fa8217f92b80223bc83aac7db36ec80a84437dbc0d04bbc659cae030d8c9 AS uv
FROM python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends strace ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /work
COPY backend/pyproject.toml backend/uv.lock backend/.python-version backend/
COPY backend/src/agentmall/__init__.py backend/src/agentmall/__init__.py
ENV UV_NO_CACHE=1 HF_HUB_DISABLE_TELEMETRY=1
RUN uv sync --project backend --locked --extra embedding
COPY . .
RUN python ci_harness/t16_models.py
ENV PATH="/work/backend/.venv/bin:${PATH}" PYTHONPATH=/work HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
CMD ["sleep", "infinity"]
