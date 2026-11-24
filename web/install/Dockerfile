# syntax=docker/dockerfile:1
# MoolaKata's image (requirements S17.8). Releases are published as ghcr.io/mojokata/moolakata
# (S17.8.2, built by .github/workflows/release.yml); to build it yourself, from the repository's root:
#   docker buildx build -f web/install/Dockerfile -t ghcr.io/mojokata/moolakata:$(cat web/VERSION) --load .
# Another architecture: add --platform linux/arm64 (or amd64), which runs under QEMU.

ARG PYTHON=python:3.14-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83

FROM ${PYTHON} AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_PROJECT_ENVIRONMENT=/opt/moolakata/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
COPY web/install/build-requirements.txt /tmp/
RUN pip install --no-cache-dir --require-hashes -r /tmp/build-requirements.txt
WORKDIR /opt/moolakata
# Dependencies first, from the lock with its hashes, so a code change reuses this layer.
COPY web/VERSION web/
COPY web/server/pyproject.toml web/server/uv.lock web/server/
RUN cd web/server && uv sync --frozen --no-dev --no-install-project
COPY web/server/src web/server/src
# Dev mode's code stays out of the image: its seed users and their fixed password (S17.7).
RUN cd web/server && uv sync --frozen --no-dev && rm -rf src/moolakata/dev
COPY web/ui web/ui
RUN python3 web/ui/vendor/vendor.py extract \
    && rm -f web/ui/vendor/*.tgz \
    && rm -rf web/ui/tests web/ui/mockup
COPY docs/mockups/MoolaKata-mock.html docs/mockups/

FROM ${PYTHON}
RUN groupadd --gid 10001 moolakata \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent \
       --shell /usr/sbin/nologin moolakata \
    && install -d -o 10001 -g 10001 -m 0700 /var/lib/moolakata /var/backups/moolakata \
    && install -d -o 0 -g 0 -m 0755 /etc/moolakata
COPY --from=build /opt/moolakata /opt/moolakata
ENV PATH=/opt/moolakata/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
LABEL org.opencontainers.image.source="https://github.com/MojoKata/MoolaKata" \
      org.opencontainers.image.description="MoolaKata: a self-hosted personal finance server for a household"
USER 10001:10001
EXPOSE 37373
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["moolakata", "health"]
ENTRYPOINT ["moolakata"]
CMD ["serve"]
