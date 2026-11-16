# CodePilot AI — Full-Stack Developer Workbench & AI Learning Copilot

[![Next.js](https://img.shields.io/badge/Next.js-15.5-black?logo=next.js)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19.0-61DAFB?logo=react)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.7-blue?logo=typescript)](https://www.typescriptlang.org/)
[![Docker](https://img.shields.io/badge/Docker-Sandboxed-2496ED?logo=docker)](https://www.docker.com/)
[![Neon PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791?logo=postgresql)](https://neon.tech/)
[![Google Gemini](https://img.shields.io/badge/AI-Google%20Gemini-4285F4?logo=google)](https://deepmind.google/technologies/gemini/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-FF6F00)](https://langchain-ai.github.io/langgraph/)

**CodePilot AI** is an engineered developer workbench and full-stack AI learning copilot designed for computer science students and software engineers. It bridges the divide between computer science curriculum and modern production engineering by combining curriculum-grounded retrieval-augmented generation (RAG), automated multi-agent code analysis, and isolated containerized code execution.

---

## Features

### 🎓 AI Learning Tutor (Curriculum RAG)
* **Verbatim Grounded Answering**: Employs Google Gemini (`gemini-2.5-pro` / `gemini-2.5-flash`) with strict citation grounding in user-provided PDF lecture slides and textbooks.
* **Multi-User Vector Isolation**: Powered by Neon PostgreSQL with the `pgvector` extension, ensuring complete data isolation between user workspaces via cryptographic user IDs.
* **Multi-Modal Document Processing**: Ingests, cleans, chunks, and indexes PDF course literature with real-time vectorization.

### 🔍 Multi-Agent Code Reviewer (LangGraph)
* **Automated Big-O Complexity**: Derives asymptotic time and space complexities ($O(1)$, $O(\log n)$, $O(n)$, $O(n^2)$, $O(2^n)$).
* **Static & AST Analysis**: Validates abstract syntax trees, identifying antipatterns and reference equality bugs.
* **Edge-Case & Vulnerability Auditing**: Proactively audits bounds, recursion depths, null checks, and memory leaks before execution.
* **Executable Sample Library**: Preloaded, interactive code samples across Python, Java, and C++ with automatic STDIN pairing.

### ⚡ Code Execution Sandbox
* **Triple Language Support**: Sandboxed execution for **Python 3.12**, **Java 21**, and **C++ 14**.
* **Zero Host Pollution**: Ephemeral, in-memory `tmpfs` workspaces with zero host disk bind mounts.
* **Hardened Isolation**: Enforces non-root execution (`1000:1000`), drops Linux capabilities (`--cap-drop ALL`), disables privilege escalation, isolates networking (`--network none`), and sets strict process limits (`--pids-limit 64`).

### 💻 CodePilot Local Runtime & Desktop Installer
* **Client-Side Execution**: Replaces third-party cloud runners by executing code directly in the user's local Docker daemon over localhost (`127.0.0.1:8088`).
* **Cryptographic Browser Pairing**: One-time handshake with time-limited pairing codes and persistent HMAC bearer tokens.
* **Native Windows Installer & Portable Package**: One-click setup wizard (`installer/setup.py`) that audits Docker, pulls language images, and manages background daemons.

---

## Technology Stack

* **Frontend:** Next.js 15 (App Router), React 19, TypeScript 5.7, Tailwind CSS 3.4, Monaco Editor
* **Backend:** FastAPI 0.115, Pydantic v2, Uvicorn (ASGI)
* **AI & Multi-Agent:** Google Gemini 2.5 (Pro & Flash), LangGraph, LangChain Core
* **Database & Vector Search:** Neon Serverless PostgreSQL 16, `pgvector`, SQLAlchemy 2.0, Alembic
* **Sandboxed Execution & Runtime:** Docker Engine, CodePilot Local Runtime Daemon
* **Authentication & Security:** Neon Auth (JWT & JWKS), HMAC-SHA256

---

## Getting Started (Local Development)

### Prerequisites
* **Node.js**: v20.x or higher
* **Python**: v3.11 or v3.12 (Python 3.13 supported)
* **Docker Desktop**: Installed and running
* **Git**: Installed

---

### Environment Configuration

1. **Frontend Configuration**:
   Create a `.env.local` file inside `frontend/` based on `frontend/.env.example`:
   ```bash
   cp frontend/.env.example frontend/.env.local
   ```
   Set the following variables:
   * `NEXT_PUBLIC_API_URL`: `http://localhost:8000` (for local backend)
   * `NEON_AUTH_BASE_URL`: Your Neon Auth project URL
   * `NEON_AUTH_COOKIE_SECRET`: A secure 32-character random string

2. **Backend Configuration**:
   Create a `.env` file inside `backend/` based on `backend/.env.example`:
   ```bash
   cp backend/.env.example backend/.env
   ```
   Set the following variables:
   * `DATABASE_URL`: `postgresql+psycopg://username:password@host/neondb?sslmode=require`
   * `GEMINI_API_KEY`: Your Google Gemini API Key
   * `NEON_AUTH_URL`: Your Neon Auth URL

---

### Running the Applications

#### 1. Backend (FastAPI)
```bash
cd backend
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Interactive API documentation will be available at: `http://127.0.0.1:8000/docs`

#### 2. Frontend (Next.js)
```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
```
Open `http://localhost:3000` in your browser.

#### 3. Local Runtime Daemon (Optional for Local Docker Execution)
```bash
python -m uvicorn runtime.server:runtime_app --host 127.0.0.1 --port 8088
```
Open the web app at `http://localhost:3000`, click **Pair Runtime** in the header, and complete pairing with the displayed code.

---

## Testing & Verification

### Frontend Type-Checking & Production Build
```bash
cd frontend
npx tsc --noEmit
npm run build
```

### Backend Automated Test Suite
```bash
cd backend
python -m pytest tests/test_sandbox_api.py tests/test_reviewer.py -v
```

### Local Runtime Test Suite
```bash
python -m pytest tests/test_local_runtime.py -v
```

---

## License

This project is developed as an academic and portfolio engineering project. Distributed under the MIT License.
