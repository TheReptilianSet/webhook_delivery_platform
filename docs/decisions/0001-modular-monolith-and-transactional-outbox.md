# ADR 0001: Modular monolith with a transactional outbox

Status: Accepted

## Context

Event acceptance must not depend on immediate broker availability and must preserve tenant and
delivery invariants.

## Decision

Use one modular Python codebase with separate API, dispatcher, scheduler, and worker roles.
PostgreSQL is the product source of truth. Event, initial deliveries, and outbox rows commit in one
transaction; RabbitMQ transports versioned identifier-only commands.

## Consequences

Publisher uncertainty can create duplicate commands, so consumers use conditional transitions.
At-least-once delivery remains visible to receivers and operators.

