from __future__ import annotations


def message_link(chat_id: int, message_id: int) -> str | None:
    """Ссылка на сообщение в приватной супергруппе: t.me/c/<id без -100>/<msg>."""
    raw = str(chat_id)
    if not raw.startswith("-100"):
        return None
    return f"https://t.me/c/{raw[4:]}/{message_id}"


def dropoff_chart(rows: list[tuple[int, int]], width: int = 20) -> str:
    if not rows:
        return ""
    peak = max(n for _, n in rows) or 1
    lines = []
    for day, count in rows[-14:]:
        bar = "█" * max(1, round(count / peak * width))
        lines.append(f"д{day:>3} {bar} {count}")
    return "<pre>" + "\n".join(lines) + "</pre>"
