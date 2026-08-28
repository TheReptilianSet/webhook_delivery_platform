from __future__ import annotations

from typing import Protocol


class CiphertextUnavailable(Exception):
    pass


class Cipher(Protocol):
    key_version: int

    def encrypt(self, plaintext: bytes, aad: bytes) -> tuple[bytes, bytes, int]: ...

    def decrypt(self, ciphertext: bytes, nonce: bytes, aad: bytes) -> bytes: ...
