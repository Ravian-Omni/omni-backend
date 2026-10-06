"""Ad creatives the user uploads for a campaign (the campaign page, Creatives).

Each one is used up to four ways: Campaign Builder reads its summary to match the copy (always);
a step can attach it; its public link can go in the copy; an image with a public link can be shown
inside the email. Files live next to the campaign's artifacts; the records are in the creatives table.
"""

import html
import mimetypes
import os
import re
import uuid
from typing import Any

from loguru import logger

from src.configs.datetime_utils import dt
from src.database import save_creative

IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
TEXT_TYPES = {"text/plain", "text/markdown"}
ALLOWED = IMAGE_TYPES | TEXT_TYPES | {"application/pdf"}
MAX_BYTES = 10 * 1024 * 1024  # Gmail takes 25 MB in total; one creative should stay well under it
SUMMARY_CHARS = 4000
DESCRIBE = ("This is an ad creative for an outbound sales campaign. Describe it for a copywriter in under 120 words: "
            "the headline and every line of text in it word for word, the offer, any numbers or claims, the call to action, "
            "and the look (colours, imagery). No opinions.")


def kind_of(name: str, mime: str = "") -> str:
    """The creative's media type: the browser's, or guessed from the file name."""
    mime = (mime or "").split(";")[0].strip().lower()
    if mime in ALLOWED:
        return mime
    guessed = mimetypes.guess_type(name)[0] or ("text/markdown" if name.lower().endswith(".md") else "")
    return guessed if guessed in ALLOWED else ""


async def summarise(data: bytes, mime: str) -> str:
    """What Campaign Builder reads: a PDF's or text file's words, or a description of an image ("" if unreadable)."""
    try:
        if mime in TEXT_TYPES:
            return data.decode("utf-8", errors="replace")[:SUMMARY_CHARS]
        if mime == "application/pdf":
            import io

            from pypdf import PdfReader

            text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages[:10])
            return re.sub(r"[ \t]+", " ", text).strip()[:SUMMARY_CHARS]
        if mime in IMAGE_TYPES:
            from src.agent_runtime import llm

            return (await llm.describe_image(data, mime, DESCRIBE))[:SUMMARY_CHARS]
    except Exception as e:
        logger.warning(f"[creatives] could not read a {mime}: {e}")
    return ""


async def store(chat_id: str, plan_id: str, artifacts_dir: str, name: str, mime: str, data: bytes) -> dict[str, Any]:
    """Save an uploaded creative next to the campaign's artifacts and read it once for the copywriter."""
    creative_id = f"creative-{uuid.uuid4().hex[:8]}"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(name))[-80:] or "file"
    folder = os.path.join(artifacts_dir, "creatives")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{creative_id}-{safe}")
    with open(path, "wb") as f:
        f.write(data)
    return await save_creative({
        "id": creative_id, "chat_id": chat_id, "plan_id": plan_id, "name": os.path.basename(name), "mime": mime,
        "path": path, "size": len(data), "url": "", "summary": await summarise(data, mime), "created_at": dt.now_iso(),
    })


def lint(step: dict[str, Any], assets: dict[str, dict]) -> list[str]:
    """Problems with a step's attachments and inline image; they hold the message back."""
    issues = [f"missing attachment {a}" for a in step.get("attachments") or [] if a not in assets]
    image = step.get("inline_image")
    if image:
        creative = assets.get(image)
        if not creative:
            issues.append(f"missing attachment {image}")
        elif creative["mime"] not in IMAGE_TYPES:
            issues.append("inline image is not an image")
        elif not creative["url"].startswith(("https://", "http://")):
            issues.append("inline image needs a public link")
    return issues


def html_body(body: str, image_url: str, alt: str) -> str:
    """The plain-text email as simple HTML with the image after its first paragraph."""
    paragraphs = [p for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    blocks = [f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in paragraphs]
    image = f'<p><img src="{html.escape(image_url, quote=True)}" alt="{html.escape(alt, quote=True)}" style="max-width:100%;height:auto"></p>'
    return "".join(blocks[:1] + [image] + blocks[1:])
