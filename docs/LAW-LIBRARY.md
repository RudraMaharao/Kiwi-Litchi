# Law library

The application ships no purported current tax-law corpus. `examples/demo-law.jsonl` is fictional and must only be imported with `--demo`. Normal searches exclude it. A CA or other qualified reviewer must verify real source text, effective periods and the applicability of any result.

Prepare UTF-8 JSON Lines, one section record per line:

```json
{"act":"Exact act name","section":"Exact section number","heading":"Section heading","text":"Verified source text, preserving paragraphs.","source_url":"https://official-source.example/section","as_of":"2026-10-30","valid_from":"2026-04-01","valid_to":"9999-12-31","chapter":"Chapter name","reviewed":true}
```

The example URL is a placeholder. Use the actual authoritative source URL. `as_of` means the date this source version is known/checked; `valid_from` and `valid_to` are its effective period. Retrieval excludes sources checked after the requested date, as well as sources outside their effective period. Preserve earlier versions for historical questions; replace the matching version when correcting it. Do not mark unverified text `reviewed` just to make an import pass.

```bash
source .venv/bin/activate
litchi law-import /path/to/reviewed-law.jsonl
litchi law-index
litchi law-search 'your question' --on 2026-10-30
litchi law-search 'your question' --on 2026-10-30 --bm25-only
litchi law-search 'your question' --on 2026-10-30 --extract
```

Sections are split into bounded chunks with their metadata intact. Search combines SQLite BM25 and Qdrant cosine ranks using reciprocal-rank fusion, returning at most five passages. Filters include act, effective date, source-check date and demonstration status. When vectors are unavailable the result explicitly reports its BM25 fallback. A corpus change invalidates the vector index until rebuilt.

The UI's **Select exact answering passages** option asks the local model to select quotations. Each returned quote must be an exact substring of a retrieved source with a known source ID. Unsupported quotations are discarded. A source quote still needs applicability review; exact quotation is not proof that a legal conclusion is correct. This pilot provides source passages and extractive answers, rather than unrestricted legal prose.

Write and freeze the 50 CA-reviewed questions before measuring retrieval/answer quality. Record expected sections, applicable dates, answerability, and independent reviewer verdicts. Targets remain unverified until those evaluations are completed; see ACCEPTANCE.md.
