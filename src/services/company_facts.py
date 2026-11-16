"""Company facts for Brain_Hands' fit grade (contract [11]): one free Data Axle business search, no agent and no credits.

Data Axle's search takes no domain and its free sample records carry no website, so the company is matched by name: the
name given, else the domain's first label, against headquarters records ("Acme Widgets Inc" matches acmewidgets.com).
Two different headquarters with that name are ambiguous and give None, as no match does.
"""

import json
import re
from typing import Any
from urllib.parse import urlparse

from src.mcp_client import call_tool

SERVER, TOOL = "data-axle", "salesgenie_business_search"
SUFFIXES = re.compile(r"\b(inc|llc|ltd|corp|corporation|co|company|the|group|holdings|plc|lp|llp)\b")


def _key(name: str) -> str:
    """A company name as compared: lower case, without legal suffixes, spaces or punctuation."""
    return re.sub(r"[^a-z0-9]", "", SUFFIXES.sub("", name.lower()))


async def facts(website: str, name: str = "") -> dict[str, Any] | None:
    """{name, website, industry, employees, city, state} for the company at `website`, leaving out what the free sample
    does not give or masks; None when no single headquarters matches.
    Raises RuntimeError when Data Axle answers with an error, PermissionError when it is not connected."""
    domain = (urlparse(website if "//" in website else f"//{website}").hostname or "").removeprefix("www.")
    asked = name.strip() or domain.split(".")[0]
    if not _key(asked):
        return None
    text = await call_tool(SERVER, TOOL, {"name": asked, "place_type": "Headquarter"})
    try:
        records = json.loads(text).get("sampleRecords") or []
    except (ValueError, AttributeError):
        raise RuntimeError(f"Data Axle: {text[:300]}") from None
    matches = {r.get("infogroupId"): r.get("values") or {} for r in records if _key(str((r.get("values") or {}).get("businessName") or "")) == _key(asked)}
    if len(matches) != 1:
        return None
    v = next(iter(matches.values()))
    out = {"name": v.get("businessName"), "website": domain, "industry": v.get("primarySicDescription"),
           "employees": v.get("corporateEmployeeSizeRange") or v.get("locationEmployeeSizeRange"), "city": v.get("city"), "state": v.get("state")}
    return {k: val for k, val in out.items() if val not in (None, "") and "*" not in str(val)}  # a masked value is not a fact
