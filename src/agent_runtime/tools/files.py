"""File and web tools for the OpenAI persona runner.

The Claude Agent SDK ships Read/Write/Edit/Glob/Grep/WebFetch as CLI
built-ins; this module gives the OpenAI runner the same tools, with the same
names, so persona prompts work unchanged. Access is limited to the chat's
directories and the DAXAGENT data folder.
"""

import fnmatch
import os
import re
from typing import Any

import httpx

from src.agent_runtime.tools.context import ToolContext
from src.configs.settings import settings

MAX_READ_CHARS = 200_000
MAX_GREP_MATCHES = 200
MAX_GLOB_RESULTS = 500
MAX_FETCH_CHARS = 60_000
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".cache", "dist", "build"}


def _text(payload: str) -> dict:
    return {"content": [{"type": "text", "text": payload}]}


def _error(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}], "is_error": True}


def _roots(ctx: ToolContext) -> list[str]:
    roots = [ctx.chat_dir, ctx.working_directory, ctx.file_location, ctx.artifacts_dir, settings.ROOT_DIR]
    return [os.path.realpath(r) for r in roots if r]


def _resolve(ctx: ToolContext, path: str) -> str:
    """Absolute path under one of the allowed roots, or a ValueError."""
    candidate = path if os.path.isabs(path) else os.path.join(ctx.working_directory, path)
    real = os.path.realpath(candidate)
    for root in _roots(ctx):
        if real == root or real.startswith(root + os.sep):
            return real
    raise ValueError(
        f"'{path}' is outside the directories this persona may touch "
        f"(working directory {ctx.working_directory}, shared files {ctx.file_location})."
    )


def _is_binary(sample: bytes) -> bool:
    return b"\0" in sample


def build(ctx: ToolContext):
    from claude_agent_sdk import tool

    @tool(
        "Read",
        "Read a text file. Returns numbered lines (number, tab, text). Use offset/limit for large files.",
        {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path, or relative to the working directory"},
                "offset": {"type": "integer", "minimum": 1, "description": "First line to return (1-based)"},
                "limit": {"type": "integer", "minimum": 1, "description": "Number of lines to return"},
            },
            "required": ["file_path"],
        },
    )
    async def read_file(args: dict) -> dict:
        try:
            path = _resolve(ctx, args["file_path"])
        except ValueError as e:
            return _error(str(e))
        if not os.path.isfile(path):
            return _error(f"No such file: {args['file_path']}")
        with open(path, "rb") as f:
            head = f.read(4096)
        if _is_binary(head):
            return _error(f"{args['file_path']} is a binary file ({os.path.getsize(path)} bytes); read it with run_python instead")
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        offset = max(1, int(args.get("offset") or 1))
        limit = int(args.get("limit") or 2000)
        chunk = lines[offset - 1 : offset - 1 + limit]
        body = "\n".join(f"{offset + i}\t{line}" for i, line in enumerate(chunk))
        if len(body) > MAX_READ_CHARS:
            body = body[:MAX_READ_CHARS] + f"\n... truncated; {len(lines)} lines in file, use offset/limit"
        elif offset - 1 + limit < len(lines):
            body += f"\n... {len(lines) - (offset - 1 + limit)} more lines; continue with offset={offset + limit}"
        return _text(body or "(empty file)")

    @tool(
        "Write",
        "Create or overwrite a file with the given text. Parent directories are created.",
        {
            "type": "object",
            "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["file_path", "content"],
        },
    )
    async def write_file(args: dict) -> dict:
        try:
            path = _resolve(ctx, args["file_path"])
        except ValueError as e:
            return _error(str(e))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(args.get("content") or "")
        return _text(f"Wrote {len(args.get('content') or '')} characters to {path}")

    def _apply_edit(text: str, old: str, new: str, replace_all: bool) -> tuple[str, str | None]:
        count = text.count(old)
        if count == 0:
            return text, "old_string not found in the file (it must match exactly, including whitespace)"
        if count > 1 and not replace_all:
            return text, f"old_string occurs {count} times; include more context to make it unique or set replace_all"
        return (text.replace(old, new) if replace_all else text.replace(old, new, 1)), None

    @tool(
        "Edit",
        "Replace an exact string in a file. old_string must occur exactly once unless replace_all is true.",
        {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
                "replace_all": {"type": "boolean"},
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    )
    async def edit_file(args: dict) -> dict:
        try:
            path = _resolve(ctx, args["file_path"])
        except ValueError as e:
            return _error(str(e))
        if not os.path.isfile(path):
            return _error(f"No such file: {args['file_path']}")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        text, err = _apply_edit(text, args["old_string"], args["new_string"], bool(args.get("replace_all")))
        if err:
            return _error(err)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return _text(f"Edited {path}")

    @tool(
        "MultiEdit",
        "Apply several exact-string replacements to one file in order; all succeed or none are written.",
        {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"old_string": {"type": "string"}, "new_string": {"type": "string"}, "replace_all": {"type": "boolean"}},
                        "required": ["old_string", "new_string"],
                    },
                },
            },
            "required": ["file_path", "edits"],
        },
    )
    async def multi_edit(args: dict) -> dict:
        try:
            path = _resolve(ctx, args["file_path"])
        except ValueError as e:
            return _error(str(e))
        if not os.path.isfile(path):
            return _error(f"No such file: {args['file_path']}")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for i, e in enumerate(args.get("edits") or []):
            text, err = _apply_edit(text, e["old_string"], e["new_string"], bool(e.get("replace_all")))
            if err:
                return _error(f"Edit {i + 1}: {err}; nothing was written")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return _text(f"Applied {len(args.get('edits') or [])} edits to {path}")

    @tool(
        "Glob",
        "Find files by glob pattern (e.g. '**/*.csv') under a directory (default: the working directory). Newest first.",
        {
            "type": "object",
            "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
            "required": ["pattern"],
        },
    )
    async def glob_files(args: dict) -> dict:
        try:
            root = _resolve(ctx, args.get("path") or ctx.working_directory)
        except ValueError as e:
            return _error(str(e))
        pattern = args["pattern"]
        hits: list[tuple[float, str]] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, root)
                if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(name, pattern) or ("**" in pattern and fnmatch.fnmatch(rel, pattern.replace("**/", ""))):
                    try:
                        hits.append((os.path.getmtime(full), full))
                    except OSError:
                        continue
            if len(hits) > MAX_GLOB_RESULTS * 4:
                break
        hits.sort(reverse=True)
        listed = [p for _, p in hits[:MAX_GLOB_RESULTS]]
        return _text("\n".join(listed) if listed else f"No files match {pattern} under {root}")

    @tool(
        "Grep",
        "Search file contents with a regular expression under a directory (default: the working directory). "
        "Returns path:line: text for up to 200 matches.",
        {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
                "glob": {"type": "string", "description": "Only files whose name matches this glob, e.g. '*.py'"},
                "ignore_case": {"type": "boolean"},
            },
            "required": ["pattern"],
        },
    )
    async def grep_files(args: dict) -> dict:
        try:
            root = _resolve(ctx, args.get("path") or ctx.working_directory)
        except ValueError as e:
            return _error(str(e))
        try:
            rx = re.compile(args["pattern"], re.IGNORECASE if args.get("ignore_case") else 0)
        except re.error as e:
            return _error(f"Invalid regular expression: {e}")
        name_glob = args.get("glob")
        out: list[str] = []
        files = [root] if os.path.isfile(root) else []
        if not files:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                for name in filenames:
                    if name_glob and not fnmatch.fnmatch(name, name_glob):
                        continue
                    files.append(os.path.join(dirpath, name))
        for full in files:
            try:
                if os.path.getsize(full) > 2_000_000:
                    continue
                with open(full, "rb") as f:
                    if _is_binary(f.read(2048)):
                        continue
                with open(full, encoding="utf-8", errors="replace") as f:
                    for n, line in enumerate(f, 1):
                        if rx.search(line):
                            out.append(f"{full}:{n}: {line.rstrip()[:300]}")
                            if len(out) >= MAX_GREP_MATCHES:
                                break
            except OSError:
                continue
            if len(out) >= MAX_GREP_MATCHES:
                out.append(f"... stopped at {MAX_GREP_MATCHES} matches")
                break
        return _text("\n".join(out) if out else f"No matches for /{args['pattern']}/ under {root}")

    @tool(
        "WebFetch",
        "Fetch a web page or API URL (GET) and return its text with HTML tags removed.",
        {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    )
    async def web_fetch(args: dict) -> dict:
        url = str(args.get("url") or "")
        if not url.startswith(("http://", "https://")):
            return _error("url must start with http:// or https://")
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={"User-Agent": "DAXAGENT/1.0"}) as client:
                r = await client.get(url)
        except Exception as e:
            return _error(f"Fetch failed: {e}")
        body = r.text
        if "html" in (r.headers.get("content-type") or ""):
            body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
            body = re.sub(r"<[^>]+>", " ", body)
            body = re.sub(r"[ \t]+", " ", body)
            body = re.sub(r"\n\s*\n+", "\n", body)
        if len(body) > MAX_FETCH_CHARS:
            body = body[:MAX_FETCH_CHARS] + "\n... truncated"
        return _text(f"HTTP {r.status_code} {url}\n\n{body.strip()}")

    return [read_file, write_file, edit_file, multi_edit, glob_files, grep_files, web_fetch]
