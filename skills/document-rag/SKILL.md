---
name: document-rag
description: 解析 PDF、DOCX、PPTX、学校通知、账单和课程材料，执行 chunking、RAG indexing、embedding、BM25 + vector hybrid retrieval。当用户上传文件、要求基于文件问答、要求索引资料或需要证据追溯时触发此 Skill。
---

# Document RAG Skill

## 能力概述

你是文件解析与 RAG 能力模块，负责把用户上传的文档转成可检索、可追溯的知识片段。你可以：

1. 使用 Docling 解析 PDF、DOCX、PPTX。
2. 识别页面文本质量，决定是否需要 native / region OCR / full OCR 策略。
3. 生成结构化 chunks，保留页码、章节、内容类型和来源文件。
4. 生成 embedding，并写入 PostgreSQL / pgvector。
5. 使用 BM25 + vector hybrid retrieval 返回带 evidence 的候选片段。
6. 在 OCR candidate 页面上调用 Deepdoc OCR 适配器补充可检索文本。

## 后端实现

- Parser：`backend/app/documents/parser.py`
- OCR：`backend/app/documents/ocr.py`
- Chunking：`backend/app/documents/chunking.py`
- Page quality：`backend/app/documents/page_quality.py`
- RAG indexing：`backend/app/rag/indexer.py`
- Retrieval：`backend/app/rag/retriever.py`
- Repository：`backend/app/rag/repository.py`
- API：`backend/app/api/routes/rag.py`

## 工作流程

### Step 1: 文件解析

读取上传文件路径，调用 Docling parser，输出 `ParsedDocument`。

必须保留：

- source file id
- source file name
- page number
- section heading
- content type
- raw text

### Step 2: 页面质量判断

读取 [references/page_quality.md](references/page_quality.md)，判断：

- native text 是否足够。
- 是否标记为 OCR candidate。
- 是否需要触发 Deepdoc OCR 适配器。

如果命中 OCR candidate，调用 `OcrDocumentProcessor.apply_ocr_if_needed()`。OCR 执行依赖运行环境中可用的 Deepdoc SDK；如果 SDK 不存在或失败，不虚构内容，只保留 page quality metadata 和策略标记。

### Step 3: Chunking

按结构优先切分：

1. heading / section
2. page
3. paragraph
4. token budget

chunk 不应丢失页码和来源。

### Step 4: Indexing

为每个 chunk 写入：

- text
- metadata
- embedding
- search vector

当前版本使用 PostgreSQL + pgvector，不接入 Milvus。

### Step 5: Hybrid Retrieval

检索时合并：

- PostgreSQL full-text / BM25 style score
- vector similarity score
- metadata filter

返回 `RetrievalCandidate`，供 Assignment Agent、Email Agent 或 Planner 使用。

## 重要边界

- OCR 已有 Deepdoc 适配入口，但实际执行依赖环境配置；失败时只能标记质量和策略，不能补写猜测文本。
- 不丢弃低质量页；应标记质量和策略。
- 不把检索结果直接当最终事实，最终事实仍需 Agent verifier 检查。
