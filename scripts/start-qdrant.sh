#!/usr/bin/env bash
set -euo pipefail
[[ "$(uname -s)" == Linux ]] || { echo 'Run this on Linux.' >&2; exit 1; }
command -v docker >/dev/null || { echo 'Install Docker on Linux first; see docs/AI-SETUP.md.' >&2; exit 1; }
if ! docker info >/dev/null 2>&1; then
  echo 'Docker is not accessible. Start its service, or run this script with sudo if using rootful Docker.' >&2
  exit 1
fi
if docker container inspect kiwi-litchi-qdrant >/dev/null 2>&1; then
  echo 'Container already exists; check docker inspect before changing it. Start with: docker start kiwi-litchi-qdrant'
  exit 0
fi
# Exact version is fixed for repeatability; update intentionally after validation.
docker run -d --name kiwi-litchi-qdrant --restart unless-stopped \
  --memory 512m --memory-swap 512m --cpus 1 \
  -p 127.0.0.1:6333:6333 \
  -e QDRANT__TELEMETRY_DISABLED=true \
  -v kiwi-litchi-law:/qdrant/storage \
  -v kiwi-litchi-law-snapshots:/qdrant/snapshots \
  qdrant/qdrant:v1.20.0
echo 'Qdrant is starting at http://127.0.0.1:6333. Client books never go into this collection.'
