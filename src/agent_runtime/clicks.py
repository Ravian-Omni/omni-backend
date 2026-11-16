"""Click tracking: the links in an outgoing email go through our own redirect (/r/<token>), and a click is an event
Brain_Hands can read (kind "click").

Off until DAXAGENT_PUBLIC_URL is set: a link on localhost cannot be opened by whoever gets the email. There is no
open-tracking pixel: it is unreliable (mail apps preload images) and it hurts delivery.
"""

import os
import re
import secrets

from src.database import save_link

BARE = re.compile(r"https?://[^\s<>\"')\]]+")
HTML_BARE = re.compile(r"(?<![\"'=])" + BARE.pattern)  # in HTML a URL straight after a quote or "=" is an attribute (an image's src), not a link
HREF = re.compile(r'(?<=href=")https?://[^"]+', re.I)
TRAILING = ".,;:!?"  # punctuation after a link in prose is not part of it


def base() -> str:
    return os.getenv("DAXAGENT_PUBLIC_URL", "").rstrip("/")


async def rewrite(body: str, is_html: bool, recipient: str, plan_id: str, step: int | None, subject: str) -> str:
    """The body with every link sent through its own redirect for this recipient; unchanged while no public URL is set."""
    if not base():
        return body
    patterns = ((HREF, False), (HTML_BARE, True)) if is_html else ((BARE, True),)  # (pattern, strip trailing punctuation)

    def link(match: re.Match, trim: bool) -> str:
        return match.group(0).rstrip(TRAILING) if trim else match.group(0)

    tracked = {}
    for pattern, trim in patterns:
        for url in {link(m, trim) for m in pattern.finditer(body)} - tracked.keys():
            token = secrets.token_urlsafe(8)
            await save_link({"token": token, "url": url, "recipient": recipient.lower(), "plan_id": plan_id, "step": step, "subject": subject})
            tracked[url] = f"{base()}/r/{token}"
    for pattern, trim in patterns:
        body = pattern.sub(lambda m, trim=trim: tracked[link(m, trim)] + m.group(0)[len(link(m, trim)):], body)
    return body
