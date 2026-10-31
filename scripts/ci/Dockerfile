# Project-only reproducibility image. Never published by this task.
FROM ghcr.io/astral-sh/uv:0.9.18@sha256:5713fa8217f92b80223bc83aac7db36ec80a84437dbc0d04bbc659cae030d8c9 AS uv
FROM node:24.21.0-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20 AS node
FROM python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
WORKDIR /work
COPY backend/pyproject.toml backend/uv.lock backend/.python-version backend/
COPY backend/src backend/src
RUN uv sync --project backend --locked --no-extra embedding
COPY frontend/package.json frontend/package-lock.json frontend/
RUN npm --prefix frontend ci
ENV PLAYWRIGHT_BROWSERS_PATH=/work/frontend/.cache/ms-playwright
RUN cd frontend && npx --no-install playwright install --with-deps chromium
COPY . .
ENV PATH="/work/backend/.venv/bin:${PATH}" PYTHONPATH=/work
CMD ["python", "scripts/ci/run.py"]
