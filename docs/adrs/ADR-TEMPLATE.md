---
date: MM-DD-YYYY
adr-number: ADR-N
status: accepted | deprecated | superseded by ADR-NNNN
---

# ADR-N: Short title of the decision

## Context

## Decision

## Alternatives Considered

---

# Sample

---

date: 01-01-2000
adr-number: ADR-1
status: accepted
---

# ADR-1: Use PostgreSQL for primary database

## Context

We need a primary database for the task management application. Key requirements:

- Relational data model (users, tasks, teams with relationships)
- ACID transactions for task state changes
- Support for full-text search on task content
- Managed hosting available (for small team, limited ops capacity)

## Decision

Use PostgreSQL with Prisma ORM.

## Alternatives Considered

### MongoDB

- Pros: Flexible schema, easy to start with
- Cons: Our data is inherently relational; would need to manage relationships manually
- Rejected: Relational data in a document store leads to complex joins or data duplication

### SQLite

- Pros: Zero configuration, embedded, fast for reads
- Cons: Limited concurrent write support, no managed hosting for production
- Rejected: Not suitable for multi-user web application in production

### MySQL

- Pros: Mature, widely supported
- Cons: PostgreSQL has better JSON support, full-text search, and ecosystem tooling
- Rejected: PostgreSQL is the better fit for our feature requirements

## Consequences

- Prisma provides type-safe database access and migration management
- We can use PostgreSQL's full-text search instead of adding Elasticsearch
- Team needs PostgreSQL knowledge (standard skill, low risk)
- Hosting on managed service (Supabase, Neon, or RDS)
