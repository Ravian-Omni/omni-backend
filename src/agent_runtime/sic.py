"""Standard Industrial Classification (SIC) lookup.

Data Axle filters businesses by ``primary_sic_code`` and accepts the 4-digit
SIC code (2-digit and 6-digit prefixes work too). Users describe industries in
words, and the SIC vocabulary is formal ("Eating Places" for restaurants,
"Legal Services" for law firms), so the lookup combines a synonym table for
everyday terms with token matching against the bundled public 4-digit list at
``configs/sic_codes.csv``.
"""

import csv
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

_CSV_PATH = Path(__file__).parent.parent.parent / "configs" / "sic_codes.csv"

_DIVISIONS = {
    "A": "Agriculture, Forestry and Fishing",
    "B": "Mining",
    "C": "Construction",
    "D": "Manufacturing",
    "E": "Transportation, Communications, Electric, Gas and Sanitary Services",
    "F": "Wholesale Trade",
    "G": "Retail Trade",
    "H": "Finance, Insurance and Real Estate",
    "I": "Services",
    "J": "Public Administration",
}

# Everyday industry words -> the SIC codes people usually mean. Each phrase is
# matched as a whole word/phrase inside the query, longest phrase first.
_SYNONYMS: dict[str, list[str]] = {
    "restaurant": ["5812"], "cafe": ["5812"], "coffee shop": ["5812"], "diner": ["5812"],
    "fast food": ["5812"], "pizza": ["5812"], "catering": ["5812"], "bar": ["5813"], "pub": ["5813"],
    "brewery": ["2082"], "winery": ["2084"], "bakery": ["5461", "2051"],
    "law firm": ["8111"], "lawyer": ["8111"], "attorney": ["8111"], "legal": ["8111"],
    "software": ["7372", "7371", "7373"], "saas": ["7372"], "app developer": ["7371"],
    "web design": ["7371"], "web development": ["7371"], "it services": ["7379", "7373"],
    "it consulting": ["7379"], "managed services": ["7379"], "data center": ["7374"],
    "data processing": ["7374"], "cybersecurity": ["7379", "7382"], "computer repair": ["7378"],
    "dentist": ["8021"], "dental": ["8021"], "orthodontist": ["8021"],
    "doctor": ["8011"], "physician": ["8011"], "medical practice": ["8011"], "clinic": ["8011"],
    "urgent care": ["8011"], "hospital": ["8062"], "chiropractor": ["8041"], "optometrist": ["8042"],
    "physical therapy": ["8049"], "therapist": ["8049"], "mental health": ["8049", "8063"],
    "nursing home": ["8051"], "assisted living": ["8051", "8361"], "home health": ["8082"],
    "medical lab": ["8071"], "veterinarian": ["0742"], "vet clinic": ["0742"], "pharmacy": ["5912"],
    "plumber": ["1711"], "plumbing": ["1711"], "hvac": ["1711"], "heating and cooling": ["1711"],
    "electrician": ["1731"], "electrical contractor": ["1731"], "roofing": ["1761"], "roofer": ["1761"],
    "general contractor": ["1521", "1542"], "home builder": ["1521"], "remodeling": ["1521"],
    "commercial construction": ["1542"], "painting contractor": ["1721"], "flooring": ["1752"],
    "landscaping": ["0782"], "lawn care": ["0782"], "tree service": ["0783"], "pest control": ["7342"],
    "cleaning service": ["7349"], "janitorial": ["7349"], "security guard": ["7381"],
    "real estate": ["6531"], "realtor": ["6531"], "property management": ["6531"],
    "mortgage": ["6162"], "bank": ["6021", "6022"], "credit union": ["6061"],
    "insurance agency": ["6411"], "insurance agent": ["6411"], "insurance": ["6411", "6311"],
    "financial advisor": ["6282"], "wealth management": ["6282"], "investment": ["6211", "6282"],
    "accounting": ["8721"], "accountant": ["8721"], "cpa": ["8721"], "bookkeeping": ["8721"],
    "tax preparation": ["7291"], "payroll": ["8721", "7374"],
    "marketing agency": ["7311", "8742"], "advertising": ["7311"], "digital marketing": ["7311"],
    "public relations": ["8743"], "consulting": ["8742"], "management consulting": ["8742"],
    "staffing": ["7363", "7361"], "recruiting": ["7361"], "temp agency": ["7363"],
    "engineering": ["8711"], "architect": ["8712"], "surveying": ["8713"],
    "school": ["8211"], "private school": ["8211"], "college": ["8221"], "university": ["8221"],
    "tutoring": ["8299"], "training": ["8299"], "daycare": ["8351"], "child care": ["8351"],
    "gym": ["7991"], "fitness": ["7991"], "yoga": ["7991"], "salon": ["7231"], "hair salon": ["7231"],
    "barber": ["7241"], "spa": ["7231"], "nail salon": ["7231"], "tattoo": ["7299"],
    "hotel": ["7011"], "motel": ["7011"], "bed and breakfast": ["7011"],
    "auto repair": ["7538"], "mechanic": ["7538"], "body shop": ["7532"], "car wash": ["7542"],
    "car dealer": ["5511"], "auto dealer": ["5511"], "used cars": ["5521"], "auto parts": ["5531"],
    "gas station": ["5541"], "trucking": ["4213"], "freight": ["4731", "4213"], "logistics": ["4731"],
    "courier": ["4215"], "moving company": ["4214"], "warehouse": ["4225"], "taxi": ["4121"],
    "grocery": ["5411"], "supermarket": ["5411"], "convenience store": ["5411"], "liquor store": ["5921"],
    "clothing store": ["5651", "5621"], "boutique": ["5621"], "shoe store": ["5661"],
    "furniture store": ["5712"], "jewelry": ["5944"], "florist": ["5992"], "gift shop": ["5947"],
    "sporting goods": ["5941"], "bookstore": ["5942"], "pet store": ["5999"], "hardware store": ["5251"],
    "electronics store": ["5731"], "computer store": ["5734"], "e-commerce": ["5961"], "online store": ["5961"],
    "printing": ["2752"], "print shop": ["2752"], "sign company": ["3993"], "photography": ["7221"],
    "photographer": ["7221"], "video production": ["7812"], "event planning": ["7389"],
    "wedding": ["7299"], "funeral home": ["7261"], "dry cleaning": ["7216"], "laundromat": ["7215"],
    "church": ["8661"], "nonprofit": ["8399"], "charity": ["8399"], "association": ["8611", "8621"],
    "telecom": ["4813"], "internet provider": ["4813"], "utility": ["4911", "4931"],
    "solar": ["1731", "4911"], "oil and gas": ["1311"], "mining": ["1000", "1400"],
    "farm": ["0100", "0191"], "ranch": ["0212"], "nursery": ["0181"],
    "manufacturer": ["3999"], "manufacturing": ["3999"], "machine shop": ["3599"],
    "metal fabrication": ["3444"], "plastics": ["3089"], "packaging": ["2670", "3085"],
    "food manufacturing": ["2000"], "chemical": ["2800"], "pharmaceutical": ["2834"],
    "medical device": ["3841", "3845"], "electronics manufacturer": ["3670", "3679"],
    "wholesale": ["5000", "5100"], "distributor": ["5000", "5100"],
    "biotech": ["8731", "2836"], "research lab": ["8731"], "laboratory": ["8734"],
    "travel agency": ["4724"], "airline": ["4512"], "storage": ["4225", "4226"], "self storage": ["4225"],
    "apartment": ["6513"], "commercial real estate": ["6512"], "coworking": ["6512"],
    "radio station": ["4832"], "tv station": ["4833"], "newspaper": ["2711"], "publisher": ["2731"],
    "recording studio": ["7389"], "museum": ["8412"], "golf course": ["7992"], "amusement": ["7996"],
    "movie theater": ["7832"], "bowling": ["7933"], "casino": ["7999"],
}

_STOPWORDS = {
    "and", "or", "the", "of", "in", "for", "a", "an", "to", "with", "not", "elsewhere",
    "classified", "nec", "services", "service", "company", "companies", "business",
    "businesses", "firm", "firms", "office", "offices", "shop", "shops", "store", "stores",
    "local", "small", "near", "industry", "industries", "sector", "provider", "providers",
}


@dataclass(frozen=True)
class SicCode:
    """One row of the SIC table."""

    code: str
    description: str
    division: str
    major_group: str

    def as_dict(self) -> dict:
        return {
            "sic": self.code,
            "description": self.description,
            "division": _DIVISIONS.get(self.division, self.division),
            "major_group": self.major_group,
        }


@lru_cache(maxsize=1)
def _table() -> list[SicCode]:
    with _CSV_PATH.open() as f:
        return [
            SicCode(r["sic"], r["description"], r["division"], r["major_group"])
            for r in csv.DictReader(f)
        ]


@lru_cache(maxsize=1)
def _by_code() -> dict[str, SicCode]:
    return {c.code: c for c in _table()}


def _stem(word: str) -> str:
    for suffix in ("ies", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {_stem(w) for w in words if w not in _STOPWORDS and len(w) > 1}


def _token_match(q: str, d: str) -> bool:
    return q == d or SequenceMatcher(None, q, d).ratio() >= 0.85


def lookup(query: str, limit: int = 8) -> list[dict]:
    """Rank SIC codes for a free-text industry description.

    Args:
        query: Industry in words ("dentist", "software companies", "law firms")
            or a code prefix ("58", "5812").
        limit: Maximum number of matches to return.

    Returns:
        Best matches first, each with sic, description, division and
        major_group, plus ``match`` saying whether it came from the synonym
        table ("synonym") or from the code descriptions ("description").
    """
    query = (query or "").strip()
    if not query:
        return []
    table = _table()
    if query.isdigit():
        return [dict(c.as_dict(), match="code") for c in table if c.code.startswith(query)][:limit]

    q_lower = " " + re.sub(r"[^a-z0-9 ]+", " ", query.lower()) + " "
    results: list[dict] = []
    seen: set[str] = set()

    # 1. Synonyms, longest phrase first so "hair salon" wins over "salon".
    for phrase in sorted(_SYNONYMS, key=len, reverse=True):
        singular = phrase.rstrip("s")
        if f" {phrase} " in q_lower or f" {phrase}s " in q_lower or f" {singular} " in q_lower:
            for code in _SYNONYMS[phrase]:
                entry = _by_code().get(code)
                if entry and code not in seen:
                    seen.add(code)
                    results.append(dict(entry.as_dict(), match="synonym"))

    # 2. Token overlap with descriptions.
    q_tokens = _tokens(query)
    scored: list[tuple[float, SicCode]] = []
    if q_tokens:
        for code in table:
            if code.code in seen:
                continue
            d_tokens = _tokens(code.description)
            hits = sum(1 for q in q_tokens if any(_token_match(q, d) for d in d_tokens))
            if hits:
                # Prefer descriptions where the query covers most of the words.
                coverage = hits / max(len(d_tokens), 1)
                scored.append((hits * 2 + coverage, code))
    scored.sort(key=lambda s: (-s[0], s[1].code))
    for _, code in scored:
        results.append(dict(code.as_dict(), match="description"))
        if len(results) >= limit:
            break
    return results[:limit]
