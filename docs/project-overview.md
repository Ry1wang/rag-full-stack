# RAG Full-Stack 项目开发说明

基于 `full-stack-fastapi-template`，以 FastAPI 官方文档为数据源，分四个阶段构建生产级 RAG 系统。

---

## 数据目录结构

```
data/
├── raw/
│   └── fastapi-docs/docs/en/   # FastAPI 英文文档（153 个 Markdown 文件，git sparse-clone）
├── processed/                  # 切片后的文本块（JSON/Parquet）
└── vectordb/                   # 本地向量索引缓存（Chroma / FAISS，开发用）
```

---

## 四阶段开发路线

### 阶段一：模板解构与生产级环境

**目标：** 理解模板工程化思维，完成 RAG 所需的基础设施改造。

关键任务：
- 将 `compose.yml` 中的 Postgres 镜像替换为 `ankane/pgvector:latest`
- 学习 `backend/app/api/deps.py` 的依赖注入模式
- 在 `deps.py` 中预留 `EmbeddingClient` / `VectorStore` 的异步单例注入

### 阶段二：RAG 核心与向量数据库

**目标：** 在模板内集成完整的 RAG 检索链路。

关键任务：
- 在 `backend/app/models.py` 中引入 `pgvector.sqlalchemy.Vector` 向量字段，通过 Alembic 迁移
- 在 `backend/app/services/` 下封装切片逻辑（固定长度 vs 语义切片对比实验）
- 实现混合搜索：Postgres TSVector 全文检索 + pgvector 余弦相似度组合查询

### 阶段三：高并发与底层性能

**目标：** 解决 AI 任务中的 I/O 与 CPU 瓶颈。

关键任务：
- 统一使用 `httpx.AsyncClient` 调用 OpenAI/Anthropic API，在 `deps.py` 中管理客户端生命周期
- 将文档解析和向量化解耦到 `backend/app/worker.py`（Celery），API 路由仅下发任务
- 大规模 Embedding 处理时使用 `gc` / `objgraph` 监控 Worker 内存

### 阶段四：Agent 架构与状态管理

**目标：** 构建具备上下文记忆的 Agent。

关键任务：
- 基于 Celery + Redis 实现长耗时任务：前端发任务 → 获取 `task_id` → 轮询结果（`react-query` 的 `refetchInterval`）
- 参考 `Item` 模型创建 `Conversation` / `Message` 实体，在数据库层维护 Short-term Memory
- 增加 `TaskLog` 模型，存储 Agent 中间推理过程（Chain-of-Thought），支持前端实时展示

---

## 核心技术选型

| 层次 | 选型 |
|---|---|
| 向量数据库 | pgvector（生产） / Chroma（本地开发） |
| Embedding API | BGE-M3 |
| LLM | DeepSeek |
| 异步任务 | Celery + Redis |
| 外部 HTTP 调用 | `httpx.AsyncClient` |

---

## 本地开发快速启动

```bash
# 启动完整栈（含 pgvector DB）
docker compose watch

# 单独运行文档预处理脚本（待实现）
cd backend
uv run python -m app.scripts.ingest_docs
```

数据源更新方式：

```bash
cd data/raw/fastapi-docs
git pull
```
