"""Utilities for the short novel script pipeline."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk")


@dataclass
class TextReadResult:
    """Group text read result behavior."""
    path: str
    encoding: str
    text: str
    byte_size: int
    char_count: int
    non_space_chars: int
    sha256: str

    def metadata(self) -> dict[str, object]:
        """Handle metadata."""
        return {
            "path": self.path,
            "encoding": self.encoding,
            "byte_size": self.byte_size,
            "char_count": self.char_count,
            "non_space_chars": self.non_space_chars,
            "sha256": self.sha256,
        }


def read_text_with_metadata(path: str | Path) -> TextReadResult:
    """Handle read text with metadata."""
    source = Path(path)
    data = source.read_bytes()
    errors: list[str] = []
    for encoding in ENCODINGS:
        try:
            text = data.decode(encoding)
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            return TextReadResult(
                path=str(source),
                encoding=encoding,
                text=normalized,
                byte_size=len(data),
                char_count=len(normalized),
                non_space_chars=sum(1 for char in normalized if not char.isspace()),
                sha256=hashlib.sha256(data).hexdigest(),
            )
        except UnicodeDecodeError as exc:
            errors.append(f"{encoding}: {exc}")
    raise UnicodeDecodeError("unknown", data, 0, 1, "; ".join(errors))
