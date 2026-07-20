# Provena — Promotion Guide

Ready-to-post content for promoting Provena across channels. Copy-paste and customize.

---

## 1. Reddit Posts

### r/Python (Show & Tell)

**Title:** Provena — Context governance for AI agents. Tamper-evident audit trails in 3 lines of Python.

**Body:**
Hey r/Python! I built Provena, an open-source library that adds tamper-evident audit trails to AI agent context pipelines.

**The problem:** Your AI agent makes a decision based on data from 6 different sources. Can you prove which ones? Can you verify it wasn't tampered with?

**What Provena does:**
```python
from provena import ContextTrail

trail = ContextTrail()

@trail.track(source="retriever")
def search(query):
    return retriever.search(query)
```

Every call is logged with a SHA-256 hash chain, provenance validation, and freshness checking. Sub-1ms overhead, zero dependencies for the core.

**Features:**
- 6 framework adapters (LangChain, LlamaIndex, CrewAI, AutoGen, OpenAI Agents, Google ADK)
- PostgreSQL backend for production
- Policy engine (LOG/WARN/BLOCK)
- MCP server for self-auditing agents
- Multi-agent governance with handoff tracking
- EU AI Act Art. 12 compliance reports

`pip install provena` | Apache 2.0 | 420+ tests

GitHub: https://github.com/rajfirke/provena

Looking for contributors! We have 11 "good first issue" labels and 17 "help wanted" issues. All well-scoped with code examples.

---

### r/MachineLearning

**Title:** [P] Provena — Tamper-evident audit trails for LLM agent context (EU AI Act compliance)

**Body:**
Context poisoning is OWASP's #6 risk for agentic AI (ASI06). Provena is an open-source Python library that adds governance to the context input layer — the data flowing INTO the LLM context window.

Unlike guardrails tools (which govern outputs) or AGT (which governs actions), Provena governs what agents KNOW — retriever results, tool outputs, agent messages, memory recalls, MCP resources.

Key features: SHA-256 hash-chained audit trails, provenance validation, freshness checking, policy enforcement, multi-agent governance with handoff tracking.

Pure Python, sub-1ms, zero ML model dependencies.

GitHub: https://github.com/rajfirke/provena

---

### r/opensource

**Title:** Looking for contributors! Provena — AI agent governance library (Python, 26 open issues, 11 good-first-issues)

**Body:**
Provena is a Python library for context governance in AI agent systems. We have 26 well-scoped open issues across:

- 🐛 8 bugs (with suggested fixes)
- 📝 9 documentation tasks (with templates and outlines)
- ✨ 9 enhancements (with code examples)

11 issues labeled "good first issue" — perfect for your first OSS contribution. Each issue includes:
- Exact file paths
- Code snippets showing what to do
- Test templates

Stack: Python 3.10+, pytest, Click, MkDocs, SQLite/PostgreSQL

GitHub: https://github.com/rajfirke/provena

---

## 2. Hacker News (Show HN)

**Title:** Show HN: Provena – Tamper-evident audit trails for AI agent context (Python)

**URL:** https://github.com/rajfirke/provena

---

## 3. Dev.to Article

**Title:** I Built an Open-Source Library for AI Agent Context Governance — Here's Why

**Tags:** python, ai, opensource, security

**Intro paragraph:**
Nobody governs the context input layer. Tools exist to govern what agents DO (Microsoft AGT), what agents SAY (Guardrails AI), and how agents COMMUNICATE (NeMo). But the data flowing INTO the context window — retriever results, tool outputs, agent messages — is completely ungoverned. That's what Provena fixes.

---

## 4. Twitter/X Thread

```
🧵 I built Provena — context governance for AI agents.

Your agent just made a decision based on 6 data sources.
Can you trace them? Prove they weren't tampered with?

3 lines of Python:
from provena import ContextTrail
trail = ContextTrail()

@trail.track(source="retriever")
def search(query):
    return retriever.search(query)

Every call → SHA-256 hash chain → tamper-evident audit trail.

Features:
• 6 framework adapters (LangChain, CrewAI, AutoGen, etc.)
• Policy engine (LOG/WARN/BLOCK)
• EU AI Act Art. 12 compliance reports
• Multi-agent governance with handoff tracking
• MCP server for self-auditing agents

pip install provena | Apache 2.0 | 420+ tests

Looking for contributors! 26 open issues, 11 good-first-issues.

github.com/rajfirke/provena
```

---

## 5. LinkedIn Post

```
🚀 Excited to share Provena — an open-source Python library for context governance in AI agent systems.

The problem: As AI agents become more autonomous, nobody is governing the data flowing into their context windows. OWASP ranked context poisoning as #6 in their Top 10 for Agentic AI.

Provena adds tamper-evident audit trails to any AI agent pipeline — in 3 lines of Python. Sub-1ms overhead, EU AI Act Art. 12 ready, 6 framework integrations.

We're looking for open-source contributors! 26 well-scoped issues with "good first issue" and "help wanted" labels.

🔗 github.com/rajfirke/provena
📦 pip install provena

#OpenSource #AI #Python #EUAIAct #OWASP #Governance
```

---

## 6. Aggregator Sites to Submit To

| Site | URL | How to Submit |
|------|-----|---------------|
| **Good First Issue** | goodfirstissue.dev | Google Form (needs 10+ contributors) |
| **Up For Grabs** | up-for-grabs.net | PR to their repo adding your project |
| **CodeTriage** | codetriage.com | Sign up, add your repo |
| **Awesome Python** | github.com/vinta/awesome-python | PR to add under "AI" section |
| **Awesome LLM** | github.com/Hannibal046/Awesome-LLM | PR to add under "Tools" |
| **GitHub Trending** | github.com/trending/python | Organic (need stars + activity spike) |

---

## 7. Communities to Engage

| Community | Platform | How |
|-----------|----------|-----|
| Python Discord | discord.gg/python | Share in #showcase channel |
| MLOps Community | mlops.community | Post in Slack |
| LangChain Discord | discord.gg/langchain | Share in #showcase |
| AI Engineer Discord | discord.gg/ai-engineer | Share integration story |
| OWASP GenAI | genai.owasp.org | Reference ASI06 coverage |
