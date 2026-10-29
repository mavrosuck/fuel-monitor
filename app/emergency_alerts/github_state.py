from __future__ import annotations

import base64
import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


STATE_FILE = "emergency-state.aesgcm"
STATE_AAD = b"fuel-monitor/emergency-state/v1"
STATE_VERSION = 1


def _key() -> bytes:
    try:
        key = base64.b64decode(os.environ["EMERGENCY_STATE_KEY_B64"], validate=True)
    except (KeyError, ValueError) as error:
        raise ValueError("valid emergency state encryption key is required") from error
    if len(key) != 32:
        raise ValueError("emergency state encryption key must contain exactly 32 bytes")
    return key


def encrypt_state(source: str, destination: str) -> None:
    source_path = Path(source)
    destination_path = Path(destination)
    if not source_path.is_file():
        raise FileNotFoundError("emergency SQLite state is unavailable")
    nonce = os.urandom(12)
    ciphertext = AESGCM(_key()).encrypt(nonce, source_path.read_bytes(), STATE_AAD)
    destination_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=destination_path.parent, delete=False) as output:
        output.write(bytes((STATE_VERSION,)) + nonce + ciphertext)
        temporary_path = Path(output.name)
    temporary_path.chmod(0o600)
    temporary_path.replace(destination_path)


def decrypt_state(source: str, destination: str) -> None:
    source_path = Path(source)
    payload = source_path.read_bytes()
    if len(payload) < 30 or payload[0] != STATE_VERSION:
        raise ValueError("unsupported or truncated emergency state")
    plaintext = AESGCM(_key()).decrypt(payload[1:13], payload[13:], STATE_AAD)
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=destination_path.parent, delete=False) as output:
        output.write(plaintext)
        temporary_path = Path(output.name)
    temporary_path.chmod(0o600)
    connection = sqlite3.connect(temporary_path)
    try:
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("decrypted emergency SQLite state failed integrity check")
    finally:
        connection.close()
    temporary_path.replace(destination_path)


class GitHubStateCheckpoint:
    def __init__(self, repository: str, sqlite_path: str) -> None:
        self.repository = Path(repository).resolve()
        self.sqlite_path = str(Path(sqlite_path).resolve())
        if not self.repository.is_dir():
            raise ValueError("emergency state worktree is unavailable")
        self.branch = os.environ.get("EMERGENCY_STATE_BRANCH", "emergency-runtime-state")
        self.expected_remote = self._head(optional=True)

    def _git(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("git", "-C", str(self.repository), *arguments),
            check=check,
            capture_output=True,
            text=True,
        )

    def _head(self, optional: bool = False) -> str | None:
        result = self._git("rev-parse", "HEAD", check=not optional)
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def save(self) -> None:
        encrypted_path = self.repository / STATE_FILE
        encrypt_state(self.sqlite_path, str(encrypted_path))
        self._git("add", STATE_FILE)
        if self.expected_remote is None:
            self._git(
                "-c", "user.name=github-actions[bot]",
                "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                "commit", "-m", "Store encrypted emergency runtime state",
            )
            lease = f"--force-with-lease=refs/heads/{self.branch}:"
        else:
            self._git(
                "-c", "user.name=github-actions[bot]",
                "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                "commit", "--amend", "--no-edit",
            )
            lease = f"--force-with-lease=refs/heads/{self.branch}:{self.expected_remote}"
        self._git("push", lease, "origin", f"HEAD:refs/heads/{self.branch}")
        self.expected_remote = self._head()
