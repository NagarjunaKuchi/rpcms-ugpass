"""Boundary to UGPass (NITA-U). The real interface, NGO/organisation onboarding and e-Seal
availability are UNCONFIRMED. Implement ``UgpassClient`` against the confirmed interface and set
``RPCMS_UGPASS_CLIENT_IMPL``."""

from __future__ import annotations

import secrets
from typing import Protocol, runtime_checkable


class UpstreamUnavailable(Exception):
    """UGPass could not be reached or returned something unusable (HTTP 502)."""


@runtime_checkable
class UgpassClient(Protocol):
    def send_signing_request(self, mou_id: str, document_hash: str, signatory_name: str) -> str:
        """Push a signing request to the signatory's UGPass app; return UGPass's request id."""

    def apply_seal(self, mou_id: str, document_hash: str, organisation: str) -> str:
        """Apply the organisation's e-Seal; return a seal reference."""


class MockUgpassClient:
    """Development stand-in: returns random references, signs nothing. Organisations named
    with ``-NOSEAL`` suffix simulate an unavailable seal (UpstreamUnavailable)."""

    def send_signing_request(self, mou_id, document_hash, signatory_name):
        return "UGP-REQ-" + secrets.token_hex(5).upper()

    def apply_seal(self, mou_id, document_hash, organisation):
        if organisation.upper().endswith("-NOSEAL"):
            raise UpstreamUnavailable("mock seal unavailable")
        return "UGP-SEAL-" + secrets.token_hex(5).upper()
