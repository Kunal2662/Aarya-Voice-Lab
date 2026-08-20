"""Phase 3: speaker identity.

Everything in this package reasons about *who* is speaking — the question
Phase 2 was structurally forbidden to touch.

Phase 3 software status: the architecture, engines, schemas, and policy
are implemented and tested against synthetic fixtures. **No real speaker
model is installed, no real embedding has been computed, and no real
recording has been read.** The only embedding provider that exists is a
deterministic synthetic one, and every artifact it produces is marked
`provider_is_synthetic: true` so it can never be mistaken for a real
identity decision.
"""
