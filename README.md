# AutoForge API v7.0

**AI記憶・監査エンジン — SaaS-Ready マルチテナント API**

HyDE + Multi-hop RAG + GraphRAG + ECK Audit を1つの API に統合。
どんなドメイン（広告最適化、音楽制作、etc）でもテナント分離して使い回せる。

---

## ✨ 特徴

| 機能 | 実装 |
|------|------|
| **HyDE** | 仮説文書生成 → ベクトル検索精度向上 |
| **Multi-hop RAG** | 多段推論で深い知識を引き出す |
| **GraphRAG** | Neo4j エンティティ関係展開 |
| **LLM リランキング** | 検索結果をスコア順に再評価 |
| **ECK 監査** | ドメイン別ルールで AI 出力を検証 |
| **マルチテナント** | `X-Tenant-ID` ヘッダーで知識ベース分離 |
| **DeepSeek 対応** | API費用 1/10（$0.28/1M tokens） |
| **Granian** | 高速 ASGI サーバー |

---

## 🚀 Quick Start

```bash
# 1. Clone
git clone https://github.com/tanakaryotadayo-wq/autoforge-api.git
cd autoforge-api

# 2. 環境変数
cp .env.example .env
# .env に DeepSeek or OpenAI の API キーを設定

# 3. 起動（OrbStack / Docker）
docker compose up -d

# 4. DB 初期化
uv run python scripts/init_db.py

# 5. サンプル知識データ投入
uv run python scripts/seed_knowledge.py --file data/sample_knowledge.json

# 6. ヘルスチェック
curl http://localhost:8100/health
```

---

## 📡 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | 全コンポーネントのヘルスチェック |
| `POST` | `/token` | JWT トークン取得 |
| `POST` | `/v1/learn` | 知識を KB に追加 |
| `POST` | `/v1/query` | RAG + GraphRAG で知識検索 |
| `POST` | `/v1/propose` | AI 提案生成 + ECK 監査 |
| `POST` | `/v1/feedback` | 提案へのフィードバック記録 |
| `POST` | `/admin/cleanup` | 古い知識の手動クリーンアップ |

### 提案リクエスト例

```bash
curl -X POST http://localhost:8100/v1/propose \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: ad-optimizer" \
  -d '{
    "user_data": {
      "campaign": "遺品整理_東京",
      "current_cpa": 12000,
      "budget": 500000,
      "impressions": 15000,
      "clicks": 300,
      "conversions": 25
    },
    "domain": "ad_optimization"
  }'
```

---

## 🏗️ Architecture

```
Client (Node.js / Python / Next.js)
  ↓ HTTP + X-Tenant-ID
FastAPI (Granian)
  ├── JWT Auth
  ├── Tenant Middleware
  └── ContextEngine
       ├── HyDE → Hypothetical Document Generation
       ├── pgvector → Vector Similarity Search
       ├── Neo4j → Graph Entity Expansion
       ├── LLM Reranker → Relevance Scoring
       ├── Proposal Generator → Domain-specific AI
       └── ECK Audit → Output Validation
```

---

## 🎯 Supported Domains

| Domain | Tenant ID | Description |
|--------|-----------|-------------|
| `ad_optimization` | `ad-optimizer` | 広告運用最適化（Google/Yahoo Ads） |
| `music_production` | `ai-daw` | AI DAW 音楽制作支援 |
| *(custom)* | *(any)* | ドメインプロンプト追加で拡張 |

---

## 💰 Cost Estimate

| Component | Monthly Cost |
|-----------|-------------|
| Cloud Run | $0〜5 |
| Cloud SQL (pgvector) | $10〜25 |
| Neo4j AuraDB Free | $0 |
| DeepSeek API | $1〜5 |
| **Total** | **$11〜35（~5,000円）** |

---

## 📁 Project Structure

```
autoforge-api/
├── pyproject.toml              # uv + dependencies
├── Dockerfile                  # Granian deploy
├── docker-compose.yml          # Local dev (OrbStack)
├── data/
│   └── sample_knowledge.json   # Sample seed data
├── scripts/
│   ├── init_db.py              # DB migration
│   └── seed_knowledge.py       # Knowledge bulk loader
├── tests/
│   └── test_api.py             # API integration tests
└── src/autoforge/
    ├── config.py               # DeepSeek/OpenAI auto-switch
    ├── interfaces.py           # Protocol definitions
    ├── models.py               # Pydantic schemas
    ├── main.py                 # FastAPI app
    ├── adapters/
    │   ├── pgvector.py         # Vector DB
    │   ├── neo4j_graph.py      # Graph DB
    │   ├── embedder.py         # Embedding client
    │   ├── llm_client.py       # Token-aware LLM
    │   └── metrics.py          # Prometheus counters
    ├── auth/
    │   └── jwt.py              # JWT + tenant extraction
    └── engine/
        └── context.py          # HyDE + RAG + GraphRAG + Audit
```

---

## License

MIT
