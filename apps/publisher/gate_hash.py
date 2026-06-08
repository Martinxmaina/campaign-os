import hashlib


def canonical_content_hash(text: str, media_refs: list[str] | None = None) -> str:
    parts = [text.strip()]
    parts.extend((media_refs or []))
    joined = "\n".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
