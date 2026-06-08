---
name: project-model-split
description: OpenAI model assignments — gpt-4.1 for generation, gpt-4.1-mini for judge and all preprocessing
metadata:
  type: project
---

gpt-4.1 (`openai_generation_model`) is used exclusively in `generate_with_judge` for the final answer generation step.

gpt-4.1-mini (`openai_model`) is used everywhere else: judge evaluation, query preprocessing, chunk summarisation, general session summary, and stance extraction.

**Why:** Cost optimisation — smaller model for classification/extraction tasks, larger model only for user-facing generation.

**How to apply:** When reviewing LLM calls, flag any `model=settings.openai_model` used in a context where quality matters (e.g. final generation), and flag any `model=settings.openai_generation_model` used where cost is more important (e.g. pure classification). Also note that `vergadering_summary_service.py` generates the public-facing session summary using `openai_model` (mini) — this may be intentional but is worth flagging.
