"""
Prometheus metrics for AutoForge — LLM, vector search, graph, and audit counters.
"""
from prometheus_client import Counter, Gauge, Histogram

# ── LLM ──
llm_calls_total = Counter(
    "autoforge_llm_calls_total", "Total LLM calls", ["model", "endpoint"]
)
llm_tokens_total = Counter(
    "autoforge_llm_tokens_total", "Total tokens consumed", ["direction"]
)
llm_duration_seconds = Histogram(
    "autoforge_llm_duration_seconds", "LLM call latency", ["model"]
)

# ── Vector DB ──
vector_search_total = Counter(
    "autoforge_vector_search_total", "Total vector searches", ["tenant"]
)
vector_search_duration = Histogram(
    "autoforge_vector_search_duration_seconds", "Vector search latency"
)

# ── Graph DB ──
graph_expand_total = Counter(
    "autoforge_graph_expand_total", "Total graph expansions"
)
graph_expand_duration = Histogram(
    "autoforge_graph_expand_duration_seconds", "Graph expand latency"
)
graph_entities_upserted = Counter(
    "autoforge_graph_entities_upserted_total", "Entities upserted"
)

# ── Rerank ──
rerank_calls_total = Counter(
    "autoforge_rerank_calls_total", "Total rerank calls"
)
rerank_duration = Histogram(
    "autoforge_rerank_duration_seconds", "Rerank latency"
)

# ── Audit ──
audit_results_total = Counter(
    "autoforge_audit_results_total", "Audit results", ["status"]
)

# ── Knowledge ──
facts_learned_total = Counter(
    "autoforge_facts_learned_total", "Facts learned", ["tenant"]
)
facts_cleaned_total = Counter(
    "autoforge_facts_cleaned_total", "Old facts removed"
)

# ── Sessions ──
active_proposals = Gauge(
    "autoforge_active_proposals", "Proposals in-flight"
)
