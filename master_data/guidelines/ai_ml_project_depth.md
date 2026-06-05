---
title: AI/ML Project Depth — Signaling Substance Without Hype
tags: [ml, ai, llm, rag, projects, depth, end-to-end]
role_fit: [ml, ai, data]
applies_when: when the JD is ML/AI focused (Machine Learning, AI, Applied Scientist, etc.)
---

## The Hierarchy of ML Claims

When tailoring for an ML/AI role, **distinguish what you actually did** from
adjacent work. ML recruiters and engineers spot bluffing fast.

| Tier | Claim | Example |
| --- | --- | --- |
| 1 — Pretraining / from-scratch | Designed + trained a foundation model | "Pretrained 350M-param transformer on 12B tokens" |
| 2 — Fine-tuning | Fine-tuned a base model on labeled data | "Fine-tuned Llama-3-8B on 100K labeled support tickets" |
| 3 — Eval / data work | Built dataset pipelines, evals, or RLHF | "Designed eval harness measuring 5 RAG retrieval metrics" |
| 4 — Inference / serving | Deployed models, optimized inference | "Cut p99 inference latency 60% via TensorRT batching" |
| 5 — RAG / agentic | Wired LLM + retrieval + tools | "Built RAG chatbot over 50K-doc corpus with Azure AI Search" |
| 6 — Prompt engineering | Engineered prompts + structured outputs | "Designed multi-step LangGraph workflow for config drafting" |

**Be honest about tier.** A candidate who built tier 5/6 should NOT pretend
to tier 1/2. The summary should say "shipped LLM and RAG systems" — not
"developed multimodal generative AI" if no multimodal model was trained.

## Signaling End-to-End Ownership

Strong ML resume bullets cover the **pipeline**, not just one stage:

- **Data:** "Curated 50K examples, designed sampling for class balance."
- **Train / fine-tune:** (only if you did) "Fine-tuned Llama-3-8B over X."
- **Eval:** "Built eval rubric with 5 metrics; tracked across model versions."
- **Deploy:** "Containerized inference, deployed on Kubernetes with K8s
  autoscaling; cut p99 60%."

A bullet covering 2–3 of these stages signals ownership. A bullet that
covers only one ("trained a model with 95% accuracy") signals coursework.

## Quantifying ML Quality — What Numbers To Use

**Model quality:** accuracy delta vs baseline, F1, precision/recall at K,
ROUGE/BLEU for generation, retrieval@K for RAG.

**System quality:** inference latency (p50 / p99), throughput (req/s,
tokens/s), cost per 1K predictions, eval-suite pass rate.

**Business quality:** % of automation actually adopted, hours saved per
team, error rate reduction in downstream task.

Mix at least two of the three layers. ML-only metrics signal "still in
research"; system + business metrics signal "shipped".

## Common Pitfalls in Tailored ML Resumes

- ❌ **Listing every framework as a skill.** "PyTorch, TensorFlow, JAX, Keras,
  scikit-learn, XGBoost, LightGBM, ..." → reads like a CV padder. Pick the
  3-4 you actually used.
- ❌ **Generic "AI/ML enthusiast" summary.** Lead with what you *shipped*
  ("ML/AI engineer who shipped a RAG chatbot serving 30+ teams"), not what
  you "are passionate about."
- ❌ **Inflating Tier 5/6 to Tier 1.** "Built generative AI system" is fine
  if it's truthful for prompt engineering work; "designed neural
  architecture" is not.
- ❌ **Mentioning ML coursework as if it were a project.** "Implemented BERT
  for sentiment analysis" — if it was a class assignment, it's worth less
  than half a line.

## Cover Letter Hook for ML Roles

Lead with the *problem* you've already solved that maps to the JD:
- "Your team's data platform needs MLOps tooling that lets product teams
  ship without an ML Eng. I built that exact thing at UBS — AutoFlow lets
  20 engineering teams convert natural-language descriptions into validated
  automation workflows."

NOT:
- "I'm passionate about machine learning and would love to work at [Company]."

## Reference Projects in This Master

- **AutoFlow:** Tier 5/6 — LLM + LangGraph + validation loop. Strongest
  ML-adjacent project for SWE+ML hybrid roles.
- **RAG chatbot:** Tier 5 — Azure AI Search + LLM, 50K docs.
- **GenASL:** Tier 4/5 — End-to-end pipeline (FAISS + sentence-transformers +
  FFmpeg compositing). Good for CV+NLP overlap roles.
