# MCP Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans, inline implementation; one fresh read-only final reviewer. User explicitly delegates bounded implementation, no intermediate approval pauses, one final commit.

**Goal:** real official-SDK MCP stdio/localhost tools reusing AgentMall authorization and domains.
**Architecture:** role-scoped low-level SDK Server, strict Pydantic tool schemas, domain adapter, local transport guards and independent official Client.
**Tech Stack:** Python3.12, MCP Python2.3.0, existing SQLAlchemy/FastAPI/PostgreSQL.
**Spec:** docs/superpowers/specs/2026-11-07-mcp-gateway-design.md

## Global constraints

Base5f197611d6e4cb93a0a39c3882456f196c84551e; no real Provider or Key reads, remote writes, old DB/container changes, business state machine or LangGraph changes, new OAuth platform or 900-second monitoring. HTTP127.0.0.1 only; explicitly REMOTE_AUTH_NOT_IMPLEMENTED.

## Review focus

- Discovery and direct calls must both reauthorize after token expiry/user disable/Store reassignment.
- Untrusted arguments or metadata must not supply identity or request a stronger tool.
- Prompt injection, oversized input/output and exception prose must not leak credentials or bypass review.
- Cancelled/time-limited draft outcomes must preserve the same request identity; no automatic retries.
- Public products/policies, buyer ownership and merchant Store scopes must match existing domain facts.

## Tasks

- [x] Pin official SDK2.3.0 and lock only required additions, verify supported protocol/API source; prepare new owned test resources.
- [x] RED real protocol tests for discovery, domain reads, strict role scopes, draft replay, safe errors and transport bounds.
- [x] Implement mcp_gateway schemas/domain adapter and role-filtered official SDK server.
- [x] Implement separate stdio/localhost HTTP CLI with strict local transport guards and credentials outside tool input.
- [x] Add official independent client demo and tests over actual encoded stdio/HTTP; cancellation, malformed/version, no sensitive output.
- [x] Run directed backend/old behavior, Vitest, Playwright and static checks; fresh review and minimal fixes.
- [x] Write guide/tool mapping/receipts, privacy audit, clean only owned resources, local commit and CLEAN.
