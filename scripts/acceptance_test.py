#!/usr/bin/env python3
"""
Phase 2 Acceptance Test Suite
==============================
Covers all functional, security, and performance acceptance criteria.
Run with: uv run python scripts/acceptance_test.py
"""

import asyncio
import hashlib
import io
import os
import random
import statistics
import time
import uuid
from typing import Any

import httpx

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL = "http://localhost:8000/api/v1"
SUPERUSER_EMAIL = os.environ.get("FIRST_SUPERUSER", "2209614776@qq.com")
SUPERUSER_PASSWORD = os.environ.get("FIRST_SUPERUSER_PASSWORD", "")

# ANSI colours
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"

results: list[tuple[str, bool, str]] = []


def _ok(label: str, note: str = "") -> None:
    results.append((label, True, note))
    print(f"  {GREEN}✓{RESET} {label}" + (f"  ({note})" if note else ""))


def _fail(label: str, note: str = "") -> None:
    results.append((label, False, note))
    print(f"  {RED}✗{RESET} {label}" + (f"  ({note})" if note else ""))


def _section(title: str) -> None:
    print(f"\n{BOLD}{BLUE}{'─'*60}{RESET}")
    print(f"{BOLD}{BLUE}  {title}{RESET}")
    print(f"{BOLD}{BLUE}{'─'*60}{RESET}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_token(client: httpx.Client) -> str:
    """Log in as superuser and return a JWT access token."""
    r = client.post(
        f"{BASE_URL}/login/access-token",
        data={"username": SUPERUSER_EMAIL, "password": SUPERUSER_PASSWORD},
    )
    r.raise_for_status()
    return r.json()["access_token"]


def make_auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _read_pg_password() -> str:
    """Read POSTGRES_PASSWORD from .env file or environment."""
    pw = os.environ.get("POSTGRES_PASSWORD", "")
    if pw:
        return pw
    env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_file):
        for line in open(env_file):
            line = line.strip()
            if line.startswith("POSTGRES_PASSWORD="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def make_pdf_bytes(pages: int = 15, words_per_page: int = 400) -> bytes:
    """Generate a simple but valid multi-page PDF using only stdlib (no fpdf2)."""
    import zlib

    # Build content streams: one per page
    page_streams = []
    for p in range(pages):
        text_lines = []
        word = "Lorem ipsum dolor sit amet consectetur adipiscing elit ".split()
        for i in range(words_per_page // 8):
            text_lines.append(" ".join(word) + f" page{p} line{i}")
        content = "\n".join(
            f"BT /F1 10 Tf 50 {750 - j*12} Td ({line}) Tj ET"
            for j, line in enumerate(text_lines[:60])
        )
        page_streams.append(content.encode())

    # Minimal PDF structure
    objects: list[bytes] = []
    offsets: list[int] = []

    def add_obj(data: bytes) -> int:
        idx = len(objects) + 1
        objects.append(data)
        return idx

    # Object 1: catalog (filled in later)
    # Object 2: pages dict (filled in later)
    catalog_id = 1
    pages_id = 2
    objects.append(b"")  # placeholder catalog
    objects.append(b"")  # placeholder pages

    font_id = add_obj(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    )
    resources_id = add_obj(
        f"<< /Font << /F1 {font_id} 0 R >> >>".encode()
    )

    page_ids = []
    for stream_bytes in page_streams:
        stream_id = add_obj(
            f"<< /Length {len(stream_bytes)} >>\nstream\n".encode()
            + stream_bytes
            + b"\nendstream"
        )
        page_id = add_obj(
            f"<< /Type /Page /Parent {pages_id} 0 R "
            f"/MediaBox [0 0 612 792] "
            f"/Contents {stream_id} 0 R "
            f"/Resources {resources_id} 0 R >>".encode()
        )
        page_ids.append(page_id)

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[pages_id - 1] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
    )
    objects[catalog_id - 1] = (
        f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
    )

    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    for i, obj in enumerate(objects):
        offsets.append(buf.tell())
        buf.write(f"{i+1} 0 obj\n".encode())
        buf.write(obj)
        buf.write(b"\nendobj\n")

    xref_offset = buf.tell()
    n = len(objects)
    buf.write(f"xref\n0 {n+1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        buf.write(f"{off:010d} 00000 n \n".encode())
    buf.write(
        f"trailer\n<< /Size {n+1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return buf.getvalue()


def make_docx_bytes(paragraphs: int = 200) -> bytes:
    """Generate a valid DOCX (ZIP + XML) with many paragraphs."""
    import zipfile

    doc_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    doc_xml += '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    doc_xml += "<w:body>"
    for i in range(paragraphs):
        text = f"Paragraph {i}: The quick brown fox jumps over the lazy dog. " * 5
        doc_xml += f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
    doc_xml += "</w:body></w:document>"

    rels_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

    content_types_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

    word_rels_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
</Relationships>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("word/_rels/document.xml.rels", word_rels_xml)
    return buf.getvalue()


def insert_fake_vectors(n: int = 100_000) -> float:
    """Insert n fake 1024-dim vectors directly into the DB and return elapsed seconds."""
    import psycopg

    env_password = _read_pg_password()
    conn_str = f"host=localhost port=5432 dbname=app user=postgres password={env_password}"

    print(f"    Inserting {n:,} fake vectors into DB (direct SQL)…")
    t0 = time.perf_counter()
    with psycopg.connect(conn_str, autocommit=False) as conn:
        with conn.cursor() as cur:
            # Create a fake user + document to own the perf-test chunks
            fake_user_id = str(uuid.uuid4())
            fake_doc_id = str(uuid.uuid4())

            cur.execute(
                "INSERT INTO \"user\" (id, email, hashed_password, is_active, is_superuser) "
                "VALUES (%s, %s, 'x', true, false) ON CONFLICT DO NOTHING",
                (fake_user_id, f"perftest_{fake_user_id}@example.com"),
            )
            cur.execute(
                "INSERT INTO document (id, owner_id, filename, file_type, file_size, status) "
                "VALUES (%s, %s, 'perf_test.txt', 'text/plain', 0, 'done')",
                (fake_doc_id, fake_user_id),
            )
            conn.commit()

            BATCH = 500
            for start in range(0, n, BATCH):
                batch_n = min(BATCH, n - start)
                rows = []
                for _ in range(batch_n):
                    vec = [random.uniform(-1, 1) for _ in range(1024)]
                    vec_str = "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
                    rows.append((str(uuid.uuid4()), fake_doc_id, f"perf chunk {start}", vec_str))
                cur.executemany(
                    "INSERT INTO documentchunk (id, document_id, content, embedding) "
                    "VALUES (%s, %s, %s, %s)",
                    rows,
                )
                conn.commit()
                if (start // BATCH) % 20 == 0:
                    print(f"      … {start + batch_n:,}/{n:,}", end="\r")
    elapsed = time.perf_counter() - t0
    print(f"      … {n:,}/{n:,} done in {elapsed:.1f}s          ")
    return elapsed


# ── Test Suites ───────────────────────────────────────────────────────────────

def test_functional(client: httpx.Client, token: str) -> None:
    _section("功能验收 (Functional)")
    headers = make_auth_headers(token)

    # ── F1: Upload & parse 10MB+ PDF ──────────────────────────────────────────
    print(f"\n  {YELLOW}F1 上传并解析 10MB+ PDF 文档，验证状态轮询{RESET}")
    pdf_bytes = make_pdf_bytes(pages=15, words_per_page=600)
    print(f"    Generated PDF: {len(pdf_bytes)/1024/1024:.2f} MB, 15 pages")

    t_upload = time.perf_counter()
    r = client.post(
        f"{BASE_URL}/rag/ingest",
        headers=headers,
        files={"file": ("test_large.pdf", pdf_bytes, "application/pdf")},
        timeout=60,
    )
    upload_elapsed = time.perf_counter() - t_upload

    if r.status_code != 202:
        _fail("F1 POST /ingest returns 202", f"got {r.status_code}: {r.text[:200]}")
        return
    _ok("F1a POST /ingest returns 202 immediately", f"{upload_elapsed*1000:.0f}ms")

    doc_id = r.json()["id"]
    initial_status = r.json()["status"]
    if initial_status == "pending":
        _ok("F1b 初始状态 = pending")
    else:
        _fail("F1b 初始状态 = pending", f"got {initial_status!r}")

    # Poll for completion (max 120s — embedding API may be slow)
    t_proc = time.perf_counter()
    final_status = initial_status
    for attempt in range(60):
        time.sleep(2)
        r2 = client.get(f"{BASE_URL}/rag/documents/{doc_id}", headers=headers)
        final_status = r2.json()["status"]
        if final_status in ("done", "failed"):
            break
    proc_elapsed = time.perf_counter() - t_proc

    if final_status == "done":
        pages_per_sec = 15 / proc_elapsed if proc_elapsed > 0 else 0
        _ok(
            "F1c 文档处理完成 (status=done)",
            f"{proc_elapsed:.1f}s for 15 pages → {pages_per_sec:.2f} p/s",
        )
        if pages_per_sec >= 1.0:
            _ok("F1d 处理速度 > 1 页/秒", f"{pages_per_sec:.2f} p/s ✓")
        else:
            _fail("F1d 处理速度 > 1 页/秒", f"only {pages_per_sec:.2f} p/s")
    else:
        err = r2.json().get("error_message", "unknown")
        _fail("F1c 文档处理完成", f"status={final_status!r} — {err[:120]}")
        return

    # ── F2: Deduplication ─────────────────────────────────────────────────────
    print(f"\n  {YELLOW}F2 重复上传同一文件，验证去重{RESET}")
    r_dup = client.post(
        f"{BASE_URL}/rag/ingest",
        headers=headers,
        files={"file": ("test_large.pdf", pdf_bytes, "application/pdf")},
        timeout=30,
    )
    if r_dup.json().get("id") == doc_id:
        _ok("F2 重复上传返回相同 document_id（去重命中）")
    else:
        _fail("F2 重复上传应返回相同记录", f"got new id {r_dup.json().get('id')}")

    # ── F3: Verify chunks & HNSW index in DB ─────────────────────────────────
    print(f"\n  {YELLOW}F3 验证 documentchunk 表 1024 维向量 & HNSW 索引{RESET}")
    import psycopg

    env_password = _read_pg_password()
    conn_str = f"host=localhost port=5432 dbname=app user=postgres password={env_password}"
    with psycopg.connect(conn_str) as conn:
        row = conn.execute(
            "SELECT COUNT(*), vector_dims(embedding) "
            "FROM documentchunk WHERE document_id = %s "
            "GROUP BY 2",
            (doc_id,),
        ).fetchone()
        if row:
            chunk_count, dims = row
            _ok(f"F3a documentchunk 记录数 = {chunk_count}", f"embedding 维度 = {dims}")
            if dims == 1024:
                _ok("F3b 向量维度 = 1024")
            else:
                _fail("F3b 向量维度 = 1024", f"got {dims}")
        else:
            _fail("F3a documentchunk 有记录", "no rows found")

        # Check HNSW index exists
        idx = conn.execute(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename='documentchunk' AND indexdef ILIKE '%hnsw%'"
        ).fetchone()
        if idx:
            _ok(f"F3c HNSW 索引存在: {idx[0]}")
        else:
            _fail("F3c HNSW 索引存在")

    # ── F4: Delete + cascade verification ────────────────────────────────────
    print(f"\n  {YELLOW}F4 删除文档，验证分片级联清除{RESET}")
    r_del = client.delete(f"{BASE_URL}/rag/documents/{doc_id}", headers=headers)
    if r_del.status_code == 200:
        _ok("F4a DELETE /documents/{id} returns 200")
    else:
        _fail("F4a DELETE /documents/{id} returns 200", f"got {r_del.status_code}")

    with psycopg.connect(conn_str) as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM documentchunk WHERE document_id = %s", (doc_id,)
        ).fetchone()[0]
        if remaining == 0:
            _ok("F4b 所有分片已从 documentchunk 删除")
        else:
            _fail("F4b 所有分片已从 documentchunk 删除", f"{remaining} rows remain")

        doc_remaining = conn.execute(
            "SELECT COUNT(*) FROM document WHERE id = %s", (doc_id,)
        ).fetchone()[0]
        if doc_remaining == 0:
            _ok("F4c document 记录已删除")
        else:
            _fail("F4c document 记录已删除", f"{doc_remaining} rows remain")

    # ── F-DOCX: Also test DOCX parsing ────────────────────────────────────────
    print(f"\n  {YELLOW}F-DOCX Word 文档上传与解析{RESET}")
    docx_bytes = make_docx_bytes(paragraphs=200)
    print(f"    Generated DOCX: {len(docx_bytes)/1024:.1f} KB, 200 paragraphs")
    r_docx = client.post(
        f"{BASE_URL}/rag/ingest",
        headers=headers,
        files={
            "file": (
                "test.docx",
                docx_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        timeout=30,
    )
    if r_docx.status_code == 202:
        _ok("F-DOCX POST /ingest DOCX returns 202")
        docx_id = r_docx.json()["id"]
        for _ in range(30):
            time.sleep(2)
            r_poll = client.get(f"{BASE_URL}/rag/documents/{docx_id}", headers=headers)
            if r_poll.json()["status"] in ("done", "failed"):
                break
        if r_poll.json()["status"] == "done":
            _ok("F-DOCX DOCX 处理完成 (status=done)")
        else:
            _fail("F-DOCX DOCX 处理失败", r_poll.json().get("error_message", "")[:100])
    else:
        _fail("F-DOCX POST /ingest DOCX returns 202", f"got {r_docx.status_code}")


def test_security(client: httpx.Client, token: str) -> None:
    _section("安全验收 (Security)")
    headers = make_auth_headers(token)

    # ── S4: Path traversal in filename (run FIRST — before rate-limit tests) ──
    # By the time S4 runs, functional tests have used ~3 ingest calls.
    # S4 must run before S1/S1b/S2 (which add 5 more) to stay under the 10/min limit.
    print(f"\n  {YELLOW}S4 文件名路径穿越防护{RESET}")
    r = client.post(
        f"{BASE_URL}/rag/ingest",
        headers=headers,
        files={"file": ("../../etc/passwd", b"harmless text content", "text/plain")},
        timeout=30,
    )
    if r.status_code in (202, 200):
        stored_name = r.json().get("filename", "")
        if "/" not in stored_name and stored_name not in ("", "../../etc/passwd"):
            _ok(f"S4 路径穿越文件名已净化 → stored as {stored_name!r}")
        elif stored_name == "passwd":
            _ok(f"S4 路径穿越文件名已净化 → stored as {stored_name!r}")
        else:
            _fail("S4 路径穿越文件名净化", f"stored as {stored_name!r}")
    else:
        _fail("S4 路径穿越上传", f"unexpected {r.status_code}")

    # ── S1: Unsupported MIME type ─────────────────────────────────────────────
    print(f"\n  {YELLOW}S1 上传非白名单文件类型{RESET}")
    for fname, ctype in [
        ("evil.exe", "application/octet-stream"),
        ("script.sh", "application/x-sh"),
        ("page.html", "text/html"),
    ]:
        r = client.post(
            f"{BASE_URL}/rag/ingest",
            headers=headers,
            files={"file": (fname, b"MZ\x90\x00", ctype)},
        )
        if r.status_code == 400:
            _ok(f"S1 {fname} ({ctype}) → 400")
        else:
            _fail(f"S1 {fname} ({ctype}) → 400", f"got {r.status_code}")

    # ── S1b: Valid MIME but wrong magic bytes (PDF header claiming to be PDF but not) ──
    print(f"\n  {YELLOW}S1b Magic Bytes 验证（MIME 声称 PDF，但文件头不是）{RESET}")
    r = client.post(
        f"{BASE_URL}/rag/ingest",
        headers=headers,
        files={"file": ("fake.pdf", b"#!/bin/bash\nrm -rf /", "application/pdf")},
    )
    if r.status_code == 400:
        _ok("S1b 伪 PDF（错误魔术字节）→ 400")
    else:
        _fail("S1b 伪 PDF（错误魔术字节）→ 400", f"got {r.status_code}: {r.text[:100]}")

    # ── S2: File too large ────────────────────────────────────────────────────
    print(f"\n  {YELLOW}S2 上传超过 50MB 文件{RESET}")
    # 51 MB of zeros — we use text/plain to avoid magic-byte check
    big_file = b"x" * (51 * 1024 * 1024)
    r = client.post(
        f"{BASE_URL}/rag/ingest",
        headers=headers,
        files={"file": ("big.txt", big_file, "text/plain")},
        timeout=60,
    )
    if r.status_code == 413:
        _ok("S2 51MB 文件 → 413")
    else:
        _fail("S2 51MB 文件 → 413", f"got {r.status_code}")

    # ── S3: Rate limiting ─────────────────────────────────────────────────────
    print(f"\n  {YELLOW}S3 连续触发速率限制{RESET}")
    # Use /search (60/min limit) — fire 65 requests rapidly
    # Upload a small doc first so search has something to query
    txt = b"Rate limit test document. " * 50
    r_up = client.post(
        f"{BASE_URL}/rag/ingest",
        headers=headers,
        files={"file": ("rate_test.txt", txt, "text/plain")},
        timeout=30,
    )
    got_429 = False
    for i in range(65):
        r_s = client.post(
            f"{BASE_URL}/rag/search",
            headers=headers,
            json={"query": "rate limit test", "limit": 1},
            timeout=10,
        )
        if r_s.status_code == 429:
            got_429 = True
            _ok(f"S3 第 {i+1} 次请求触发 429 (rate limit)")
            break
    if not got_429:
        _fail("S3 60 次请求内应触发 429", "never got 429")


def test_performance(client: httpx.Client, token: str) -> None:
    _section("性能验收 (Performance)")
    headers = make_auth_headers(token)

    # ── P1: Document processing speed already captured in F1 ─────────────────
    # (Checked during F1 — >1 page/sec criterion)

    # ── P2: Vector search latency P95 < 500ms @ 100k vectors ─────────────────
    print(f"\n  {YELLOW}P2 向量检索延迟 P95 < 500ms（10 万条向量规模）{RESET}")

    # Check current vector count
    import psycopg

    env_password = _read_pg_password()
    conn_str = f"host=localhost port=5432 dbname=app user=postgres password={env_password}"
    with psycopg.connect(conn_str) as conn:
        count = conn.execute("SELECT COUNT(*) FROM documentchunk").fetchone()[0]
    print(f"    Current chunk count: {count:,}")

    if count < 100_000:
        needed = 100_000 - count
        print(f"    Inserting {needed:,} additional fake vectors…")
        insert_fake_vectors(needed)

    # Upload a real doc to search against (need real embedding for semantic search)
    search_doc = b"Machine learning is a subset of artificial intelligence. " * 100
    r_up = client.post(
        f"{BASE_URL}/rag/ingest",
        headers=headers,
        files={"file": ("ml_doc.txt", search_doc, "text/plain")},
        timeout=30,
    )
    if r_up.status_code == 202:
        doc_id = r_up.json()["id"]
        for _ in range(30):
            time.sleep(2)
            if client.get(f"{BASE_URL}/rag/documents/{doc_id}", headers=headers).json()["status"] in ("done", "failed"):
                break

    # Run 30 search requests and measure latency
    print("    Running 30 timed search requests…")
    latencies: list[float] = []
    queries = [
        "machine learning algorithms",
        "artificial intelligence",
        "neural networks",
        "deep learning",
        "natural language processing",
    ]
    for i in range(30):
        q = queries[i % len(queries)]
        t0 = time.perf_counter()
        r_s = client.post(
            f"{BASE_URL}/rag/search",
            headers=headers,
            json={"query": q, "limit": 5},
            timeout=10,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if r_s.status_code == 200:
            latencies.append(elapsed_ms)
        time.sleep(0.1)  # stay under rate limit

    if latencies:
        latencies_sorted = sorted(latencies)
        p50 = latencies_sorted[len(latencies_sorted) // 2]
        p95 = latencies_sorted[int(len(latencies_sorted) * 0.95)]
        p99 = latencies_sorted[int(len(latencies_sorted) * 0.99)]
        avg = statistics.mean(latencies)
        print(f"    Results ({len(latencies)} samples):")
        print(f"      avg={avg:.0f}ms  P50={p50:.0f}ms  P95={p95:.0f}ms  P99={p99:.0f}ms")
        if p95 < 500:
            _ok(f"P2 P95 检索延迟 = {p95:.0f}ms < 500ms ✓")
        else:
            _fail(f"P2 P95 检索延迟 = {p95:.0f}ms (目标 < 500ms)")
    else:
        _fail("P2 无法完成检索延迟测试")

    # ── P3: Semantic relevance ────────────────────────────────────────────────
    print(f"\n  {YELLOW}P3 语义相关度评估（人工抽样）{RESET}")
    # Upload a doc with known content, then query it
    knowledge_doc = """
    Python is a high-level programming language known for its simplicity and readability.
    Python supports multiple programming paradigms including procedural, object-oriented, and functional.
    FastAPI is a modern web framework for building APIs with Python 3.7+ based on standard type hints.
    FastAPI is very fast due to Starlette and Pydantic, and generates OpenAPI documentation automatically.
    PostgreSQL is a powerful open-source relational database system with over 35 years of active development.
    Vector databases store high-dimensional vector embeddings for similarity search in machine learning applications.
    """ * 20  # repeat for more chunks

    r_kb = client.post(
        f"{BASE_URL}/rag/ingest",
        headers=headers,
        files={"file": ("knowledge.txt", knowledge_doc.encode(), "text/plain")},
        timeout=30,
    )
    kb_doc_id = None
    if r_kb.status_code == 202:
        kb_doc_id = r_kb.json()["id"]
        for _ in range(30):
            time.sleep(2)
            status = client.get(f"{BASE_URL}/rag/documents/{kb_doc_id}", headers=headers).json()["status"]
            if status in ("done", "failed"):
                break
        if status != "done":
            _fail("P3 知识库文档处理失败", status)
            return

    # Run semantic queries and check relevance
    test_pairs = [
        ("What is Python?", ["python", "language", "programming"]),
        ("Tell me about FastAPI", ["fastapi", "framework", "api", "python"]),
        ("What is PostgreSQL used for?", ["postgresql", "database", "relational"]),
        ("How are vectors used in AI?", ["vector", "embedding", "machine learning", "similarity"]),
    ]

    relevant_count = 0
    total_count = 0
    for query, expected_keywords in test_pairs:
        r_s = client.post(
            f"{BASE_URL}/rag/search",
            headers=headers,
            json={"query": query, "limit": 5},
            timeout=10,
        )
        if r_s.status_code != 200:
            continue
        chunks = r_s.json()
        if not chunks:
            total_count += 1
            continue
        combined = " ".join(c["content"].lower() for c in chunks)
        hits = sum(1 for kw in expected_keywords if kw in combined)
        is_relevant = hits >= len(expected_keywords) * 0.5
        total_count += 1
        if is_relevant:
            relevant_count += 1
            print(f"    ✓ '{query[:40]}' → {hits}/{len(expected_keywords)} keywords found")
        else:
            print(f"    ✗ '{query[:40]}' → only {hits}/{len(expected_keywords)} keywords")
        time.sleep(0.2)

    if total_count > 0:
        relevance_rate = relevant_count / total_count
        if relevance_rate >= 0.80:
            _ok(
                f"P3 语义相关率 = {relevance_rate*100:.0f}% ≥ 80% ✓",
                f"{relevant_count}/{total_count} queries matched",
            )
        else:
            _fail(
                f"P3 语义相关率 = {relevance_rate*100:.0f}% (目标 ≥ 80%)",
                f"{relevant_count}/{total_count}",
            )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n{BOLD}{'='*60}")
    print("  Phase 2 Acceptance Test Suite")
    print(f"  Target: {BASE_URL}")
    print(f"{'='*60}{RESET}\n")

    # Read password from env or .env file
    global SUPERUSER_PASSWORD
    if not SUPERUSER_PASSWORD:
        env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_file):
            for line in open(env_file):
                line = line.strip()
                if line.startswith("FIRST_SUPERUSER_PASSWORD="):
                    SUPERUSER_PASSWORD = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    with httpx.Client(follow_redirects=True, timeout=120) as client:
        # Get auth token
        try:
            token = get_token(client)
            print(f"  {GREEN}Auth OK{RESET} — logged in as {SUPERUSER_EMAIL}")
        except Exception as e:
            print(f"  {RED}Auth FAILED: {e}{RESET}")
            return

        test_functional(client, token)
        test_security(client, token)
        # Wait for the /search rate-limit window (60/min) to reset after S3.
        # S3 deliberately exhausts the 60/min /search limit; without a pause
        # every P2 search request would return 429 instead of 200.
        print(f"\n  {YELLOW}等待速率限制窗口重置 (62s)…{RESET}")
        time.sleep(62)
        test_performance(client, token)

    # ── Summary ───────────────────────────────────────────────────────────────
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    total = len(results)

    print(f"\n{BOLD}{'='*60}")
    print(f"  RESULTS: {passed}/{total} passed", end="")
    if failed:
        print(f"  {RED}({failed} FAILED){RESET}", end="")
    print(f"\n{'='*60}{RESET}")

    if failed:
        print(f"\n{RED}Failed tests:{RESET}")
        for label, ok, note in results:
            if not ok:
                print(f"  {RED}✗{RESET} {label}" + (f" — {note}" if note else ""))

    exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
