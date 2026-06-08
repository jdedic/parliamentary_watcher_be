# Plan: Transcript Validation After XML → JSON Transformation

## Context
After `build_transcript()` converts XML to JSON, there is currently no validation step.
Invalid or garbled transcripts silently flow into chunking and summarisation, wasting OpenAI tokens.
Two validation layers are needed: structural (fast, free) and LLM-based content validation (sampled, cheap).

---

## Layer 1 — Structural Validation (no LLM)

**New file:** `app/services/transcript_validation_service.py`

Checks run immediately after `build_transcript()`:
- Every utterance has `utterance_id`, `speaker`, `quote`
- No empty or whitespace-only quotes
- No duplicate `utterance_id` values
- At least one utterance exists in the transcript
- Timestamps are valid ISO format if present

If any check fails → raise `ValueError` → `session_service.py` catches it and marks status `FAILED`.

---

## Layer 2 — LLM Content Validation (sampled)

**Same file:** `app/services/transcript_validation_service.py`

- Sample 3–5 random utterances from the transcript
- Send to `gpt-4o-mini` with a focused prompt
- Use **structured JSON output** (OpenAI response_format with json_schema)

### Prompt
```
You are validating a Dutch parliamentary transcript excerpt.
Check the following utterances and return a JSON object with:
- is_valid (boolean)
- confidence (float 0-1)
- issues (list of strings describing specific problems found)

Check for:
1. Language consistency — text should be Dutch
2. Text coherence — no garbled characters, XML artifacts (&amp;, &#160;), encoding errors
3. Quote completeness — sentences should end properly, not cut off mid-word
4. Parliamentary plausibility — text should resemble a parliamentary speech
```

### Response schema
```json
{
  "is_valid": true,
  "confidence": 0.95,
  "issues": []
}
```

If `is_valid` is false → log a warning with issues listed, but **do not block the pipeline** (soft failure).
If `confidence` < 0.7 → log a warning regardless of `is_valid`.

---

## Integration in session_service.py

```python
_, chair_name = build_transcript(session_id)
await validate_transcript(session_id)   # NEW — raises ValueError on hard failure, warns on soft
if chair_name:
    await repo.update_chair(session_id, chair_name)
build_chunks(session_id)
```

---

## Critical files
- `app/services/transcript_validation_service.py` — new file (both layers)
- `app/services/session_service.py` — call `validate_transcript()` after `build_transcript()`

---

## Verification
1. Inject a transcript with a missing `speaker` field → status should be `FAILED`
2. Inject a transcript with garbled text → warning logged, pipeline continues
3. Valid transcript → `is_valid: true`, pipeline proceeds normally
4. Check logs for `transcript_validation_passed` / `transcript_validation_warning` / `transcript_validation_failed`
