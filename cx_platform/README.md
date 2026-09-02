# CX Platform

This directory is the canonical application package for the AI-native customer service platform.

Do not create a second `src/cx_platform` package. The reference mock business remains under `src/mock_business` and is treated as an external business system by this application.

The CX platform owns customer-service operations: conversations, tickets, messages, escalations, approvals as presented to operators, outcomes, CSAT, CX events, and links to agent/runtime/business evidence.

The CX platform uses https://github.com/etimbukafia/enterprise-agent-harness as an in-process library for governed agent execution. It does not implement a second general-purpose agent runtime.

Architecture baseline: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

Accepted architecture decisions: [`docs/ARCHITECTURE_DECISIONS.md`](docs/ARCHITECTURE_DECISIONS.md)
