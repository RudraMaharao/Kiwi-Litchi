# Workflow and automation map

![Statement workflow](diagrams/workflow.svg)

![Local automation](diagrams/automation.svg)

## From statement to evidence

```mermaid
flowchart TD
    A[CSV, Excel, PDF, scan or photo] --> B[Parse rows and normalize dates and integer paise]
    B --> C[Running-balance checks and duplicate detection]
    C --> D{Balance and direction resolved?}
    D -- No --> E[Human correction or source-file repair]
    E --> C
    D -- Yes --> F[Kiwi rules, correction memory and own-account handling]
    F --> G[Optional Litchi historical ledger suggestions]
    G --> H[Human ledger review and approval]
    H --> I[Plan Payment, Receipt or Contra]
    I --> J[Create missing ledgers in intended groups]
    J --> K{Reviewed output choice}
    K --> L[Tally XML file]
    K --> M[Explicit post to configured Tally company]
    L --> N[User selects company and imports in Tally]
    M --> O{Definitive response received?}
    O -- Yes --> P[Record accepted rows]
    O -- Timeout --> Q[Stop and inspect actual Tally vouchers before retry]
    N --> R[Tally masters and full-period voucher export]
    P --> R
    Q --> R
    R --> S[Litchi sync by stable voucher identity]
    S --> T[Replace amendments and exclude cancelled or optional objects]
    T --> U[Fixed SQL totals with voucher evidence]
    T --> V[Embeddings, review signals and later suggestions]
```

A watcher or model suggestion never approves a voucher or moves money automatically

## Local architecture

```mermaid
flowchart LR
    Browser[Shared browser workspace] --> Web[Waitress on localhost 8765]
    Web --> Kiwi[Kiwi parser and review engine]
    Web --> Litchi[Litchi assistant]
    Kiwi --> KDB[(Kiwi SQLite)]
    Litchi --> Books[(Per-client books SQLite and sqlite-vec)]
    Kiwi --> Tally[TallyPrime XML server on localhost 9000]
    Tally --> Books
    Litchi --> Ollama[Ollama on localhost 11434 CPU]
    Litchi --> Law[(Versioned law text and SQLite FTS5)]
    Law --> Qdrant[Qdrant on localhost 6333]
    Ollama --> Books
    Ollama --> Qdrant
```

The LLM routes supported questions — arithmetic comes from SQL, and legal passages come from a separately loaded verified corpus

## Scheduled automation

```mermaid
flowchart TD
    Boot[User services available after boot or login] --> Web[Kiwi web service]
    Boot --> Watch[After 2 minutes, then every 60 seconds]
    Watch --> Sidecar[Validate inbox JSON sidecar and wait for completed file copy]
    Sidecar --> Import[Import for review and save result or error]
    Backup[00:30 local time] --> Snapshot[Consistent SQLite and files backup, retain 14 successful sets]
    Lab[00:45 local time] --> Regression[Statement regression lab]
    Night[01:00 local time] --> Lock[Acquire exclusive batch lock]
    Lock --> Sync[Sync client identities]
    Sync --> Embed[Embed changed eligible lines if enabled]
    Embed --> Cache[Cache remaining review-row suggestions]
    Cache --> Audit[Generate review signals and reports]
    Audit --> Unload[Unload model]
```

| Job | Schedule | Boundaries |
|---|---|---|
| `kiwi-web.service` | Enabled user startup service | Restart on failure after 5 seconds |
| `kiwi-watch.timer` | OnBootSec=2min, then OnUnitActiveSec=60s | Inbox sidecar workflow, no silent posting |
| `kiwi-backup.timer` | 00:30 local time | Last 14 successful backup sets retained |
| `kiwi-lab.timer` | 00:45 local time | Synthetic parser regression report |
| `litchi-batch.timer` | 01:00 local time | Optional embeddings, cached suggestions, audit, report |

Generated services set MemoryMax=2G, Nice=10, UMask=0077, PrivateTmp and NoNewPrivileges — batch jobs have a five-hour timeout

Timers use Persistent=false, so a missed scheduled job is not replayed on wake — the laptop must be awake, and running while logged out depends on user lingering being enabled

Qdrant is separately limited to 512 MiB — a web/batch service limit is not a cap on total system RAM or the separate Ollama service

[Operating guide](OPERATIONS.md) · [Timer generator](../scripts/write-services.py) · [Batch/watch implementation](../kiwi_litchi/operations.py)
