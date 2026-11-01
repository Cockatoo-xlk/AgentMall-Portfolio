# Backend-only local playground/test image. Browser and Vite stay on the Mac host.
FROM ghcr.io/astral-sh/uv:0.9.18@sha256:5713fa8217f92b80223bc83aac7db36ec80a84437dbc0d04bbc659cae030d8c9 AS uv
FROM python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /work
COPY backend/pyproject.toml backend/uv.lock backend/.python-version backend/
# Editable package metadata is static. Keeping the unchanged package marker here
# allows dependency layers to survive application changes; full source is copied below.
COPY backend/src/agentmall/__init__.py backend/src/agentmall/__init__.py
ARG INSTALL_EMBEDDING=0
RUN if [ "$INSTALL_EMBEDDING" = 1 ]; then uv sync --project backend --locked --extra embedding; else uv sync --project backend --locked --no-extra embedding; fi
COPY . .
ENV PATH="/work/backend/.venv/bin:${PATH}" PYTHONPATH=/work
CMD ["python", "-m", "agentmall.playground", "--help"]
