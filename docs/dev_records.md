# 开发记录 (Development Records)

## 2026-03-12 | 阶段一：模板解构与生产级环境 [已完成]

### 核心目标
理解 FastAPI 模板架构，完成 RAG 基础设施改造，打通数据库向量支持与 Embedding 客户端注入。

### 完成任务清单
1. **基础设施 (Infrastructure)**
   - 修改 `compose.yml` 数据库服务，使用 `ankane/pgvector:latest` 镜像。
   - 在 `backend/app/backend_pre_start.py` 中增加 `CREATE EXTENSION IF NOT EXISTS vector` 逻辑，实现数据库启动自动初始化向量功能。
   - 确认 MacBook Air M4 (16G) 环境适配，确定使用 **硅基流动 (SiliconFlow)** 提供的 BGE-M3 API 以节省本地内存。

2. **配置层 (Configuration)**
   - 更新 `backend/app/core/config.py`，增加 `DEEPSEEK_API_KEY`, `EMBEDDING_API_KEY`, `EMBEDDING_MODEL` (BGE-M3), `EMBEDDING_DIMENSION` (1024) 等 RAG 相关配置。
   - 同步更新 `.env.example`。

3. **依赖注入 (Dependency Injection)**
   - 在 `backend/app/api/deps.py` 中实现 `get_embedding_client` 异步生成器。
   - 定义 `EmbeddingDep = Annotated[httpx.AsyncClient, Depends(get_embedding_client)]`，支持在 API 路由中直接注入预配置的向量化客户端。

4. **物理存储层 (Storage & Models)**
   - 在 `backend/app/models.py` 中定义 `DocumentChunk` 模型，包含 `content` (str), `metadata_json` (JSON), `embedding` (Vector(1024))。
   - 成功执行 Alembic 数据库迁移，生成 `documentchunk` 表。

5. **依赖库更新**
   - 使用 `uv` 添加 `pgvector` (数据库适配器) 和 `langchain-text-splitters` (文档切片工具)。

### 关键结论与决策
- **模型选型**：LLM 采用 DeepSeek，Embedding 采用 BGE-M3 (1024 维度)。
- **架构决策**：坚持 FastAPI 的“依赖注入”模式，将 Embedding 客户端生命周期托管给框架，确保异步高性能。
- **环境平衡**：考虑到 M4 16G 内存限制，暂不本地运行 Embedding 模型，优先采用 API 方式。

---
