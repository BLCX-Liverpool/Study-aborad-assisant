# Study Abroad Assistant Backend

This backend follows the approved Phase 1 scope from `docs/study_abroad_assistant_technical_design.md`.

Phase 1 includes backend foundations:

- FastAPI application skeleton
- Configuration layer
- OpenAI-compatible LLM provider abstraction
- SQLAlchemy model base and MVP database models
- PostgreSQL connection configuration
- Redis client placeholder
- Basic file upload endpoint
- Test skeleton

Phase 2 adds Assignment Agent foundations:

- Docling-backed PDF/DOCX/PPTX parser adapter
- PDF page quality and OCR strategy decision helpers
- Structural document chunking
- RAG indexing service with embedding generation and PostgreSQL/pgvector storage
- Hybrid retrieval service with PostgreSQL full-text search and vector search
- Requirement extractor scaffold that returns `AssignmentAnalysis`
- Evidence helper
- Assignment verifier

Current scope still does not implement OCR execution, email drafting, MCP tools, or non-MVP agents.

Phase 3 adds Task Planner foundations:

- Assignment deadline-to-plan logic
- Conflict checker against existing schedule blocks
- Reminder scheduler for tasks and events
- Local persistence for tasks, events, and reminders
- Planner API endpoints

Phase 4 adds Email Agent foundations:

- Recipient classifier
- Email style policy resolver
- Draft generator scaffold
- Approval gate for send actions
- Email draft API endpoint

Phase 6 adds simplified P1 agents:

- Travel Agent for student travel preparation, checklists, risk notes, and approval-aware booking boundaries
- Finance Agent for student budgeting, CSV expense parsing, and risk/action item generation
- Wellbeing Agent for low-risk support, crisis/high-risk detection, and professional-help guidance

Current scope still does not execute OCR, send real emails, connect to Gmail/Outlook, book travel, make payments, or provide diagnosis/financial advice.

## Local setup

Runtime dependencies are listed in `requirements.txt`.

Development and test dependencies are listed in `requirements-dev.txt`.

See `../docs/environment_setup.md` for the full Chinese setup guide.
