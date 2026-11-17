# Model specifications and runtime configuration

Measured from the installed Ollama `/api/version`, `/api/tags` and `/api/show` endpoints on 17 November 2026 — full fields and the installed chat template are preserved in [ollama-model-specs.json](verification/ollama-model-specs.json)

## Installed models

| Property | Intent / exact-quote model | Embedding model |
|---|---|---|
| Exact tag | `llama3.2:1b-instruct-q4_K_M` | `nomic-embed-text:latest` |
| Exact parameter count | 1,235,814,432 | 136,727,040 |
| Registry size label | 1B, metadata displays 1.2B | 137M |
| Architecture | Llama decoder, instruction tuned upstream | Nomic BERT encoder, non-causal attention |
| Format / precision | GGUF / Q4_K_M | GGUF / F16 |
| Installed artifact size | 807,709,787 bytes | 274,302,450 bytes |
| Layers | 16 | 12 |
| Hidden / embedding width | 2,048 internal hidden width | 768 output dimensions |
| Attention heads | 32 query / 8 KV | 12 |
| Feed-forward width | 8,192 | 3,072 |
| Metadata context | 131,072 tokens | 2,048 tokens |
| Application context | 4,096 tokens per structured request | No per-request context override |
| Installed model parameter override | No `parameters` field returned | `num_ctx 8192` |
| RoPE base | 500,000 | 1,000 |
| Tokenizer | GGUF gpt2 / llama-bpe, vocabulary 128,256 | BERT tokenizer |
| App purpose | Convert questions to validated intent, select exact retrieved quotes | Historical ledger neighbours and optional law vectors |

The embedding model has a context discrepancy between GGUF metadata (2,048) and the installed parameter override (8,192) — neither long-input boundary has been acceptance-tested, so this package does not claim an effective 8K input limit

`Q4_K_M` is the supplied mixed quantization format — it is not a claim that every tensor occupies exactly four bits

Full immutable digests

- Intent: `22bc6b92eb0160c4629782fca05a9032c59d306ab2058b7dacc8a4644fbafa02`
- Embedding: `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f`

## Application request settings

| Setting | Structured intent and quote extraction | Embeddings |
|---|---|---|
| Endpoint | `/api/generate` | `/api/embed` |
| Temperature | 0 | Not applicable |
| JSON schema | Required, additional fields rejected by the intent guard | Not applicable |
| Streaming | false | Not used |
| num_ctx | 4096 | Not explicitly set |
| num_predict | 300 | Not applicable |
| num_thread | 2 | 2 |
| num_gpu | 0, CPU only | 0, CPU only |
| keep_alive | 5m | 5m |
| Truncation | No app input truncation added | `truncate=false`, overlong inputs should fail rather than be silently cut |
| App batch size | One structured request | Up to 8 historical lines or law chunks |
| top_k, top_p, seed, repeat_penalty | Not explicitly set by the application — runtime defaults are not asserted | Not applicable |

Ollama runtime version is **0.40.13** — configured service environment binds `127.0.0.1:11434`, disables cloud access, limits loaded models to one, limits parallel requests to one, and uses a five-minute keep-alive

Tag metadata reported `ggml`, while actual loaded-model snapshots reported `llamacpp` for both models — metadata capabilities such as tool calling are model capabilities, not features exposed by this app

## Retrieval and ledger suggestions

- Prefix documents with `search_document: ` and queries with `search_query: `
- L2-normalize vectors and store float32 values in each client SQLite database
- Keep the target ledger out of embedding features
- Retrieve 10 prior neighbours using cosine similarity and exclude same-day/future history
- Return the top 3 ledger votes with weight `max(0, similarity)^2 × exp(-days / 730)`
- Cache against model digest and line-feature hash
- Apply existing firm rules, learned corrections and own-account handling before optional model suggestions
- Vote share is a ranking weight, not a calibrated probability
- Human approval remains required, including after a calibration gate passes

The law path combines top-20 BM25 and Qdrant candidates with reciprocal-rank fusion `1 / (60 + rank + 1)`, returns at most five passages, filters effective dates and source versions, and accepts generated quotes only when they are exact substrings of cited text

## What we changed — and what we did not train

No fine-tuning, LoRA, QLoRA, weight updates or new quantization was performed locally — epochs, optimizer, learning rate and training batch size are therefore not applicable

The instruction tuning and quantization were supplied upstream, and the installed digests above identify those fixed artifacts

Our model-facing changes were application code and prompts

1. Ground structured prompts with the exact client ledger list, allowed measures and explicit financial-year bounds
2. Constrain the response to four fields: ledger, measure, start and end
3. Reject unsupported ledgers/measures, extra or missing fields and reversed dates
4. Reject model intents that conflict with a supported deterministic interpretation instead of silently replacing the model answer
5. Add eight model-intent regression cases
6. Keep arithmetic in parameterized SQL over integer paise — the LLM does not calculate book totals

Kiwi learning is saved rule/correction memory and retrieval over historical postings, not neural-network weight training

See [the complete change log](CHANGELOG.md), [prompt source](../kiwi_litchi/intelligence.py) and [quote-extraction source](../kiwi_litchi/law.py)

## Measured smoke benchmark

Three fixed synthetic prompts yielded **2/3 exact intents** — the failed case confused a Hinglish receipt question with a payment

Warm intent median wall time: **5.454 seconds** across two warm requests

Warm embedding throughput: **10.479 texts/second** for one batch of eight short texts

These are a tiny raw-model smoke test and a single-machine timing sample, not a 100-question app evaluation, a representative language benchmark, a p95 latency result or proof of held-out prediction quality

[All outputs, expected intents, token counts and raw timings](verification/model-smoke-benchmark.json) · [Reproduction script](../scripts/benchmark-local-models.py)

## Upstream references

- [Exact Ollama Llama tag](https://ollama.com/library/llama3.2:1b-instruct-q4_K_M)
- [Ollama Nomic embedding model](https://ollama.com/library/nomic-embed-text)
- [Meta upstream model card and licence](https://huggingface.co/meta-llama/Llama-3.2-1B-Instruct)
- [Nomic upstream model card](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5)

Registry descriptions are references — the locally measured tags, digests and runtime configuration above define this package's actual setup

## Loaded-model snapshots and individual timings

| Field | Llama | Nomic |
|---|---|---|
| API-reported allocated model size | 1,010,114,231 bytes | 389,053,152 bytes |
| API size_vram | 0 bytes | 0 bytes |
| Actual loaded context_length | 4096 | 2048 |
| Loaded runner | llamacpp | llamacpp |

These are Ollama snapshots, not whole-process RSS or whole-machine peak RAM — the actual embedding run reported 2048 context despite the installed 8192 parameter override

| Smoke request | Wall seconds | Generation tokens/s |
|---|---|---|
| First intent after requested unload | 13.437 | 11.562 |
| Warm English receipt | 5.641 | 9.186 |
| Warm Hinglish receipt, wrong measure | 5.266 | 9.946 |
| First 8-text embedding batch | 1.923 | Not generation, 4.159 texts/s |
| Warm 8-text embedding batch | 0.763 | Not generation, 10.479 texts/s |

Generation rate excludes prompt evaluation and loading — it is not interchangeable with wall time
