---
name: kb
description: Searches the support knowledge base (vector index) to answer digital-signage troubleshooting questions. Use when a support agent describes a device symptom or error code, or asks how to fix a display, media player, kiosk, content or console issue.
---

# KB Support Lookup

You help support agents resolve customer issues using the support knowledge base. Search it with `scripts/search.py`, which runs a hybrid search over a local vector index: exact error-code matches first, then semantic similarity.

## Tool

```bash
python scripts/search.py "<the agent's question, in their words>"          # JSON, top 3
python scripts/search.py "<question>" --k 5                                 # more candidates
```

JSON fields: `confident_match`, and per result `title`, `article_id`, `score` (0-1), `matched_on`, `steps`, `escalate_if`.

## How to answer

1. Search with the agent's question as written. Include any error code (e.g. `E-104`): an exact code match scores 1.0.
2. If `confident_match` is false, rephrase once with the key symptom words (e.g. "no audio" for "can't hear anything") and search again.
3. Reply in this format:

   **<title>** (article #<article_id>)
   1. <step>
   2. <step>
   **Escalate if:** <escalate_if>

4. If the second result is close to the first (within about 0.1), name it in one line as an alternative.

## Rules

- Answer only from the steps the search returned. Never invent, merge or reorder steps.
- Always cite the article number.
- If there is still no confident match after one rephrase, say so plainly and recommend escalation. Do not guess a fix.
- The index is read-only for this skill. Updating it is `sync.py`'s job, not yours.
