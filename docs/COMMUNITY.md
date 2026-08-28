# Community and Distribution

Webhook Delivery Platform is a standalone service for reliable callback delivery from
asynchronous media-processing pipelines. This document explains how the source code is licensed,
how the project is currently distributed, and what users can expect from the community project.

## License

The repository is licensed under the [MIT License](../LICENSE). The SPDX identifier is `MIT`.

The license permits private, internal, commercial, and hosted use. It also permits modification,
redistribution, sublicensing, and sale of copies, provided that the copyright and permission notice
remain with copies or substantial portions of the software. The software is supplied without a
warranty or liability commitment.

The MIT license applies to this repository's source code and documentation. Third-party libraries,
container base images, hosted infrastructure, customer data, support commitments, service-level
agreements, and the terms of a future managed service remain subject to their own licenses or
contracts.

## How the Project Is Provided

The current public offering is source distribution for self-hosting:

1. obtain the source and locked dependencies from the repository;
2. build the application and receiver images locally;
3. operate PostgreSQL, RabbitMQ, networking, backups, monitoring, and upgrades in your own
   environment;
4. integrate media pipelines through organization-scoped API keys and verified callback endpoints.

The backend does not bundle a graphical interface. The separate
[webhook_delivery_platform client](https://github.com/TheReptilianSet/webhook_delivery_platform)
provides interfaces for Web, iOS, and Android and connects to this backend through its public API.
The client is distributed and versioned independently from this repository.

The Compose stack is intended for local development and acceptance checks. It is not a hosted
service, production deployment template, or service-level commitment. No official public SaaS,
binary package, or long-term-support channel is promised by version `0.1`.

A managed commercial service may later operate the same delivery engine behind a hosted control
plane. Access to that service would be provided under separate account, subscription, support,
privacy, and service terms. Paying for a hosted service would purchase operation and support; it
would not remove the MIT rights already granted for the repository code.

## Community Support

Community support is best effort and has no guaranteed response or resolution time. Useful reports
include the affected version, expected and actual behavior, a minimal reproduction, sanitized logs,
and the result of the documented verification commands.

Never place API keys, endpoint secrets, signatures, event payloads, private endpoint URLs, customer
data, or personal data in a public issue. Security vulnerabilities should be reported privately to
the repository owner or through the hosting provider's private security-reporting feature.

## Contributions

Bug fixes, tests, documentation improvements, and narrowly scoped product changes are welcome.
Contributions should:

- preserve tenant isolation, SSRF controls, at-least-once semantics, and exact request signing;
- include tests appropriate to the changed behavior;
- update API, migration, operational, or security documentation when a contract changes;
- avoid unrelated dependencies, infrastructure, or speculative abstractions;
- pass the frozen lock, Ruff, mypy, pytest, migration, and container checks relevant to the change.

Unless explicitly agreed otherwise, submitted contributions are accepted under the repository's MIT
license. A contributor must have the right to submit the work and must not include confidential or
third-party material without compatible permission.

## Governance and Product Boundaries

The project is maintainer-led. Product behavior is defined by the active specification; durable
architecture changes are recorded as decisions. Compatibility, security, operability, and a clear
media-processing use case take priority over feature count.

The community backend does not currently promise an embedded dashboard, billing, customer
invitations, SSO, private-network destinations, custom delivery methods, exactly-once delivery, or
multi-region operation. Such capabilities require explicit product and operational design rather
than an implied support commitment. Support and release commitments for the separate client remain
within that project's own documentation.

## Versioning and Support Expectations

Version `0.1` is an evolving pre-GA release. Breaking public API, task, or migration changes require
a documented compatibility and rollout plan, but no long-term support window is currently offered.
Production operators remain responsible for validating releases in their own environment, retaining
backups, and maintaining a rollback path.
