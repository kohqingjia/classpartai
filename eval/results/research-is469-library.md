# Research: single-pass RAG vs agentic RAG

20 labelled items (data/is469/eval_contributions.jsonl), run 2026-11-06 23:47. Model `openai:gpt-5-mini`, embedder `openai:text-embedding-3-small`, web search `None`, corpus 7 library documents, 353 chunks, seed 42. Means over the items each metric applies to (definitions in `src/classpartai/research/evaluate.py`); seconds, tokens and usd are per item.

| metric | single_pass | agentic |
|---|---|---|
| routed_correctly | n/a | 0.85 |
| correctness_ok | 0.88 | 0.94 |
| answers_question_ok | n/a | 0.35 |
| reasoning_ok | n/a | 0.83 |
| mistake_ok | n/a | 0.80 |
| context_precision | 0.88 | 0.94 |
| gold_hit | 1.00 | 0.94 |
| quoted | 0.98 | 0.99 |
| llm_calls | 1.00 | 16.05 |
| searches | 1.00 | 2.45 |
| seconds | 22.08 | 112.52 |
| tokens | 2995 | 49848 |
| usd | 0.0042 | 0.0247 |

Totals per system (API calls are chat and query-embedding calls; output tokens include the model's reasoning tokens):

| system | API calls | input tokens | output tokens | US$ total | seconds total |
|---|---|---|---|---|---|
| single_pass | 40 | 20150 | 39751 | 0.0844 | 441.7 |
| agentic | 370 | 790680 | 206276 | 0.4939 | 2250.3 |

Indexing the corpus: US$0.0000.

## Per item

Correctness as labelled / single-pass / agentic; the agent's route and whether it
found a gold file.

| id | label | single-pass | agentic | route | routed ok | answers q (label / agent) | gold hit (sp / agent) |
|---|---|---|---|---|---|---|---|
| i01 | – | unverified – | – – | course | ✗ | no / no | – / – |
| i02 | – | unverified – | unverified – | course | ✗ | yes / partly | – / – |
| i03 | correct | correct ✓ | correct ✓ | course | ✓ | yes / yes | ✓ / ✓ |
| i04 | incorrect | incorrect ✓ | partially_correct ✗ | course | ✓ | yes / partly | ✓ / ✓ |
| i05 | correct | correct ✓ | correct ✓ | course | ✓ | yes / yes | ✓ / ✓ |
| i06 | incorrect | incorrect ✓ | incorrect ✓ | course | ✓ | yes / no | ✓ / ✓ |
| i07 | correct | correct ✓ | correct ✓ | course | ✓ | yes / partly | ✓ / ✓ |
| i08 | incorrect | incorrect ✓ | incorrect ✓ | course | ✓ | yes / no | ✓ / ✓ |
| i09 | correct | correct ✓ | correct ✓ | course | ✓ | partly / partly | ✓ / ✓ |
| i10 | correct | correct ✓ | correct ✓ | course | ✓ | yes / partly | ✓ / ✓ |
| i11 | incorrect | incorrect ✓ | incorrect ✓ | course | ✓ | yes / no | ✓ / ✓ |
| i12 | correct | correct ✓ | correct ✓ | course | ✓ | partly / partly | ✓ / ✓ |
| i13 | correct | correct ✓ | correct ✓ | course | ✓ | yes / partly | ✓ / ✓ |
| i14 | correct | unverified ✗ | correct ✓ | course | ✓ | yes / partly | ✓ / ✗ |
| i15 | correct | correct ✓ | correct ✓ | course | ✓ | yes / partly | ✓ / ✓ |
| i16 | incorrect | incorrect ✓ | incorrect ✓ | course | ✓ | yes / no | ✓ / ✓ |
| i17 | – | unverified – | unverified – | course | ✗ | yes / partly | – / – |
| i18 | correct | unverified ✗ | correct ✓ | course | ✓ | partly / partly | ✓ / ✓ |
| i19 | correct | correct ✓ | correct ✓ | course | ✓ | no / no | ✓ / ✓ |
| i20 | incorrect | incorrect ✓ | incorrect ✓ | course | ✓ | yes / no | ✓ / ✓ |
