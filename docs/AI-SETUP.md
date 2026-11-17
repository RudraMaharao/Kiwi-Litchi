# Local AI setup on Linux Mint

First get Kiwi working using README steps 1–3. Run every command here on the Linux laptop. The app makes model requests only to `127.0.0.1:11434` and law-vector requests only to `127.0.0.1:6333`.

## Ollama

Download and inspect the official installer, then run it:

```bash
curl -fsSL https://ollama.com/install.sh -o /tmp/kiwi-ollama-install.sh
less /tmp/kiwi-ollama-install.sh
sh /tmp/kiwi-ollama-install.sh
sudo systemctl edit ollama.service
```

Paste this service override, save, then exit the editor:

```ini
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_NO_CLOUD=1"
Environment="OLLAMA_KEEP_ALIVE=5m"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
ollama pull nomic-embed-text
ollama pull llama3.2:1b-instruct-q4_K_M
ollama list
```

Use the exact quantized tag above. This pilot selects a 1B model for your 8 GB CPU machine. No larger generation model is required. Calls request two CPU threads and zero GPU layers. Actual speed must be measured on the laptop; estimates in the build plan are not measured results.

Official references: [Linux installation](https://docs.ollama.com/linux), [local configuration](https://docs.ollama.com/faq), [embedding API](https://docs.ollama.com/api/embed), [model tag](https://ollama.com/library/llama3.2:1b-instruct-q4_K_M).

## Qdrant

For a fresh Mint installation without Docker, the distribution package is a simple option:

```bash
sudo apt install -y docker.io
sudo systemctl enable --now docker
cd ~/Apps/kiwi-litchi-linux
sudo bash scripts/start-qdrant.sh
curl http://127.0.0.1:6333/
```

If Docker is already installed, keep that installation. The script uses image `qdrant/qdrant:v1.20.0`, named persistent volumes, localhost port publishing, disabled telemetry, 1 CPU and a 512 MB memory limit. It refuses to replace an existing container. Start an existing one with `sudo docker start kiwi-litchi-qdrant`.

Qdrant holds only your imported law corpus. Client embeddings remain in per-client SQLite databases. Law indexing uses on-disk vectors and payloads. A memory limit can terminate an oversized collection; it does not guarantee every corpus fits. Reindexing creates a new collection and activates it only when complete. Old collections remain until deliberately cleaned up.

References: [Qdrant quickstart](https://qdrant.tech/documentation/quickstart/), [release versions](https://github.com/qdrant/qdrant/releases), [Docker installation and derivative-distribution caveat](https://docs.docker.com/engine/install/ubuntu/).

## Check the real services

```bash
cd ~/Apps/kiwi-litchi-linux
source .venv/bin/activate
python scripts/check-live-stack.py
```

This performs real sqlite-vec, Ollama embedding, structured-intent and Qdrant round trips. It writes `live-stack-results.json` and fails if any check fails; it never substitutes mocks. Its uniquely named Qdrant test collection is removed afterwards. This has to pass on Linux before claiming the local stack works there.
