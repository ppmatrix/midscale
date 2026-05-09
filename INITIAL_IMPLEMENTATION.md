You are a senior network engineer and backend architect.

I want to build a private self-hosted VPN orchestration platform inspired by Tailscale, but fully controlled by me and based directly on WireGuard.

The project goal is educational first, but it should evolve into a production-grade system.

Main requirements:

- Use WireGuard as the VPN layer
- Self-hosted control server
- Peer management system
- Automatic key generation
- Automatic IP allocation
- Web dashboard
- Device registration and revocation
- Secure API
- Internal DNS support
- ACL / access rules
- Multi-platform clients
- Docker-friendly architecture
- Linux-first implementation
- Future support for subnet routers and exit nodes

Preferred stack:

Backend:
- Python
- FastAPI preferred
- PostgreSQL
- SQLAlchemy
- Alembic
- Redis optional

Frontend:
- React
- Tailwind
- Simple and clean UI

Infrastructure:
- Docker / docker-compose
- WireGuard
- nftables or iptables
- Optional CoreDNS integration

Project constraints:

- Modular architecture
- Clean separation between:
  - control plane
  - VPN layer
  - authentication
  - peer management
  - DNS
  - ACL engine
- Secure by default
- Production-oriented structure
- Avoid monolithic design
- Use environment variables for secrets
- Use async patterns where appropriate
- Generate maintainable code
- Include comments explaining networking logic
- Explain security implications when relevant

I do NOT want a simplified toy example.

I want a real architecture roadmap and implementation plan.

Start by:

1. Designing the overall architecture
2. Explaining the role of each component
3. Defining the database schema
4. Designing the API structure
5. Suggesting the project folder structure
6. Defining the WireGuard integration strategy
7. Explaining how peers should authenticate
8. Designing automatic configuration generation
9. Planning future NAT traversal support
10. Suggesting an MVP milestone roadmap

Then begin implementing Phase 1 step-by-step.

For every major decision:
- explain tradeoffs
- explain security considerations
- explain scalability implications

Act as if this project may later evolve into a serious self-hosted networking platform.