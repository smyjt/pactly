# Pactly — System Design

> Full design is captured in `/CLAUDE.md`. This doc summarizes key decisions.

**Goal:** Production-grade AI Contract Intelligence Engine — uploads contracts, extracts clauses, scores risk, supports free-text RAG queries.

**Architecture:** Modular monolith with Celery workers. FastAPI + PostgreSQL + pgvector + Redis + OpenAI API. Docker Compose.

**Key decisions:**
- Approach C: modular monolith + Celery (not microservices)
- OpenAI as primary LLM provider, abstracted via Strategy Pattern for easy swap to Claude/Ollama
- pgvector inside PostgreSQL (not a separate vector DB) — one DB, transactional consistency
- Chunks (for retrieval) and Clauses (for analysis) are separate tables
- Two query modes: auto-analysis on upload (pre-computed) + free-text RAG queries (on-demand)
- Every LLM call logged to `llm_usage_logs` for cost tracking

**See CLAUDE.md for:** full project structure, DB schema, layer rules, coding standards, build phases.
