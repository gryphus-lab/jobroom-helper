#!/usr/bin/env python3
"""Parse the 5 Swiss RAV "Nachweis persönliche Arbeitsbemühungen" (NpA) PDFs
into structured application rows and (optionally) backfill the local SQLite
tracker via the repo's own ApplicationStore.

Usage:
    python scripts/parse_npa.py --pdf-dir /path/to/pdfs           # parse + print only
    python scripts/parse_npa.py --pdf-dir /path/to/pdfs --write   # also insert into DB

Deterministic, no invented data. Ambiguous company/role/contact detections are
flagged in each row's `flags` list so a human can eyeball them.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

try:
    import pymupdf  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - handled during runtime
    pymupdf = None

if pymupdf is None:
    raise RuntimeError(
        "pymupdf is required to parse NpA PDFs. Install it with: pip install pymupdf"
    )

MONTHS = (os.environ.get("NPA_MONTHS", "05,06,07,08,09")).split(",")
MONTH_NAMES = {
    "05": "May 2026",
    "06": "June 2026",
    "07": "July 2026",
    "08": "August 2026",
    "09": "September 2026",
}

DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
PHONE_RE = re.compile(r"^\+?[\d][\d\s()/\-]{5,}$")
CH_RE = re.compile(r"CH-\s?\d{3,4}|\b\d{4}\s+[A-ZÄÖÜ]")  # address marker

# Lines that are page-footer / column-header boilerplate to ignore entirely.
BOILERPLATE = {
    "Pensum",
    "Bewerbung",
    "Ergebnis der Bewerbung",
    "Absagegrund",
    "Datum der",
    "Firma",
    "Adresse",
    "Kontaktperson",
    "E-Mail",
    "Telefon-Nr.",
    "Stellenbezeichnung",
    "Link zum Online-Formular",
    "Zuweisung RAV",
    "Vollzeit",
    "Teilzeit (%)",
    "Brieflich /",
    "elektronisch",
    "Persönlich",
    "Telefonisch",
    "Noch offen",
    "Vorstellungs-",
    "gespräch",
    "Anstellung",
    "Absage",
    "Hinweis",
}
BOILERPLATE_PREFIX = (
    "Seite ",
    "Die versicherte",
    "Berufes ",
    "AVIV)",
    "Nach dem 5.",
    "Versicherte Personen",
    "eingestellt (Art",
    "Mit unwahren",
)

# Job-title keywords: presence strongly implies a line is a ROLE, not a contact name.
ROLE_KEYWORDS = re.compile(
    r"architect|architekt|engineer|manager|lead|leiter|head|director|consultant|"
    r"consulting|officer|owner|analyst|developer|specialist|cto|ciso|ceo|"
    r"founder|principal|senior|junior|deputy|solution|platform|data|ai|software|"
    r"system|program|delivery|strategy|responsible|practice|ingenieur|"
    r"transformation|integration|management|excellence|infrastructure|"
    r"digital|cloud|security|business|technical|technology|vice president|"
    r"president|sr\.|managing",
    re.IGNORECASE,
)

# Rejection / interview signal phrases (lowercased contains-match).
REJECT_SIGNALS = [
    "regret",
    "unable to consider",
    "not be proceeding",
    "not in a position",
    "move forward with another",
    "other candidate",
    "won't be able to move forward",
    "won’t be able to move forward",
    "unfortunately",
    "nicht mehr offen",
    "absage",
    "indispensable",
    "not to proceed",
    "not proceeding",
    "not move forward",
    "not to move forward",
    "will not proceed",
    "not to pursue",
    "not able to move forward",
    "unable to pursue",
    "unable to offer",
    "decided to move forward with other",
    "decided to pursue other",
    "no longer under consideration",
    "position has been filled",
    "leider",
    "nicht weiter zu verfolgen",
    "absagen müssen",
    "nicht berücksichtigen",
    "not been selected",
    "not to progress",
    "not to move forward",
    "not moving forward",
    "cannot consider",
    "moving forward with other",
    "narrowed our pool",
    "not sicher",
    "nicht sicher",
]
INTERVIEW_SIGNALS = [
    "vorstellungsgespräch",
    "vorstellungsgesprach",
    "erstgespräch",
    "interview",
    "einladung zur",
]


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def slug(s: str) -> str:
    s = strip_accents(s).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "x"


@dataclass
class Row:
    month: str
    applied_date: str  # ISO
    applied_date_raw: str
    saved_date_raw: str
    company: str
    address: str
    contact: str = ""
    email: str = ""
    phone: str = ""
    role: str = ""
    link: str = ""
    result: str = ""
    stage: str = "Applied"
    flags: List[str] = field(default_factory=list)
    row_number: int = 0  # One-based position in the monthly source PDF.


def iter_pdf_lines(path: str) -> List[str]:
    if pymupdf is None:
        raise RuntimeError(
            "pymupdf is required to parse NpA PDFs. "
            "Install it with: pip install pymupdf"
        )
    with pymupdf.open(path) as doc:
        lines: List[str] = []
        for page in doc:
            raw_text = page.get_text("text")
            if not isinstance(raw_text, str):
                continue
            for ln in raw_text.splitlines():
                lines.append(ln.strip())
        return lines


def is_boilerplate(line: str) -> bool:
    if line in BOILERPLATE:
        return True
    if line.startswith("gespeichert"):
        return True
    return any(line.startswith(p) for p in BOILERPLATE_PREFIX)


def find_row_starts(lines: List[str]) -> List[int]:
    starts = []
    for i, ln in enumerate(lines):
        if (
            DATE_RE.match(ln)
            and i + 1 < len(lines)
            and lines[i + 1].startswith("gespeichert")
        ):
            starts.append(i)
    return starts


def iso_date(raw: str) -> str:
    d, m, y = raw.split(".")
    return f"{y}-{m}-{d}"


def looks_like_name(line: str) -> bool:
    """A plausible person name: letters/spaces/dots/hyphens,
    1-4 tokens, no job keyword.
    """
    if "@" in line or PHONE_RE.match(line):
        return False
    if ROLE_KEYWORDS.search(line):
        return False
    if any(ch.isdigit() for ch in line):
        return False
    if "%" in line or "(" in line or "|" in line:
        return False
    toks = line.split()
    if not (1 <= len(toks) <= 4):
        return False
    # Must be mostly alphabetic title-ish tokens.
    if not all(re.match(r"^[A-Za-zÄÖÜäöüßéáíóúñ.\-']+$", t) for t in toks):
        return False
    return True


def parse_company_and_address(
    blk: List[str], start_index: int, flags: List[str]
) -> tuple[str, str, int]:
    company_parts: List[str] = []
    addr_idx: Optional[int] = None
    j = start_index
    while j < len(blk):
        ln = blk[j]
        if is_boilerplate(ln):
            j += 1
            continue
        if CH_RE.search(ln):
            addr_idx = j
            break
        company_parts.append(ln)
        j += 1
    if addr_idx is None:
        raise ValueError("not a valid NpA block: missing address")

    company = " ".join(company_parts).strip()
    locality_cont = {
        "See",
        "SZ",
        "SG",
        "ZH",
        "ZG",
        "BE",
        "BL",
        "BS",
        "AG",
        "TG",
        "LU",
        "VD",
        "GE",
        "Winterthur",
        "Gallen",
    }
    address = blk[addr_idx]
    k = addr_idx + 1
    if k < len(blk):
        nxt = blk[k]
        ends_at_postcode = bool(re.search(r"CH-\s?\d{4}\s*$", address))
        is_locality = nxt in locality_cont or nxt.split()[:1] == ["St."]
        if (
            nxt
            and "@" not in nxt
            and not PHONE_RE.match(nxt)
            and not nxt.startswith("http")
            and nxt != "X"
            and not ROLE_KEYWORDS.search(nxt)
            and len(nxt.split()) <= 3
            and (ends_at_postcode or is_locality)
        ):
            address = f"{address} {nxt}"
            k += 1
            flags.append("address-wrapped")
    return company, address, k


def parse_contact_email_phone(
    blk: List[str], start_index: int, flags: List[str]
) -> tuple[str, str, str, int]:
    contact = ""
    email = ""
    phone = ""
    kk = start_index
    if kk < len(blk) and looks_like_name(blk[kk]):
        following = blk[kk + 1] if kk + 1 < len(blk) else ""
        if (
            "@" in following
            or PHONE_RE.match(following or "")
            or (not following.startswith("http") and following != "X")
        ):
            contact = blk[kk]
            kk += 1
            flags.append("contact-detected")
    if kk < len(blk) and "@" in blk[kk]:
        email = blk[kk]
        kk += 1
    if kk < len(blk) and PHONE_RE.match(blk[kk]):
        phone = blk[kk]
        kk += 1
    return contact, email, phone, kk


def parse_role_and_result(blk: List[str], start_index: int) -> tuple[str, str, str]:
    role_parts: List[str] = []
    m = start_index
    link = ""
    while m < len(blk):
        ln = blk[m]
        if ln.startswith("http"):
            link = ln
            m += 1
            break
        if ln == "X":
            break
        if is_boilerplate(ln):
            m += 1
            continue
        role_parts.append(ln)
        m += 1
    role = " ".join(role_parts).strip()

    while m < len(blk) and blk[m] == "X":
        m += 1

    result_parts: List[str] = []
    while m < len(blk):
        ln = blk[m]
        if ln == "X" or is_boilerplate(ln) or not ln:
            m += 1
            continue
        result_parts.append(ln)
        m += 1
    result = " ".join(result_parts).strip()
    return role, link, result


def derive_stage(result: str) -> str:
    low = result.lower()
    if any(sig in low for sig in REJECT_SIGNALS):
        return "Rejected"
    if any(sig in low for sig in INTERVIEW_SIGNALS):
        return "Interview"
    return "Applied"


def parse_block(month: str, lines: List[str], start: int, end: int) -> Optional[Row]:
    blk = lines[start:end]
    if len(blk) < 4:
        return None

    applied_raw = blk[0]
    saved_raw = blk[2] if DATE_RE.match(blk[2]) else ""
    idx = 3 if saved_raw else 2
    flags: List[str] = []

    try:
        company, address, next_index = parse_company_and_address(blk, idx, flags)
    except ValueError:
        return None

    (
        contact,
        email,
        phone,
        role_start,
    ) = parse_contact_email_phone(blk, next_index, flags)
    role, link, result = parse_role_and_result(blk, role_start)
    stage = derive_stage(result)

    if not company:
        flags.append("no-company")
    if not role:
        flags.append("no-role")
    if not link:
        flags.append("no-link")

    return Row(
        month=month,
        applied_date=iso_date(applied_raw),
        applied_date_raw=applied_raw,
        saved_date_raw=saved_raw,
        company=company,
        address=address,
        contact=contact,
        email=email,
        phone=phone,
        role=role,
        link=link,
        result=result,
        stage=stage,
        flags=flags,
    )


def header_count_from_lines(lines: List[str]) -> int | None:
    for i, ln in enumerate(lines):
        if ln == "Anzahl Bewerbungen" and i + 1 < len(lines):
            try:
                return int(lines[i + 1].strip())
            except ValueError:
                return None
    return None


def rows_from_starts(month: str, lines: List[str], starts: List[int]) -> List[Row]:
    rows: List[Row] = []
    for a, start in enumerate(starts):
        end = starts[a + 1] if a + 1 < len(starts) else len(lines)
        row = parse_block(month, lines, start, end)
        if row:
            row.row_number = a + 1
            rows.append(row)
    return rows


def parse_pdf(month: str, path: str) -> tuple[List[Row], int | None]:
    lines = iter_pdf_lines(path)
    header_count = header_count_from_lines(lines)
    starts = find_row_starts(lines)
    rows = rows_from_starts(month, lines, starts)
    return rows, header_count


def build_url(r: Row) -> str:
    """Identify a row within an unchanged monthly PDF.

    Legacy URLs without the source-row suffix need manual reconciliation before
    reimporting into a database populated by an older version of this script.
    """
    if r.row_number < 1:
        raise ValueError("NpA URL requires a positive source row number")
    return (
        f"npa://{r.applied_date}/{slug(r.company)}/{slug(r.role)[:40]}"
        f"/{r.month}-{r.row_number}"
    )


def load_rows(pdf_dir: str) -> tuple[List[Row], list[tuple[str, int | None, int]]]:
    all_rows: List[Row] = []
    summary: list[tuple[str, int | None, int]] = []
    for month in MONTHS:
        path = os.path.join(pdf_dir, f"NpA_2026-{month}.pdf")
        if not os.path.exists(path):
            print(f"Skipping missing PDF: {path}", file=sys.stderr)
            continue
        rows, hdr = parse_pdf(month, path)
        all_rows.extend(rows)
        summary.append((month, hdr, len(rows)))
    return all_rows, summary


def print_parsed_rows(all_rows: List[Row]) -> None:
    print(f"{'date':<12} {'company':<34} {'role':<44} stage")
    print("-" * 110)
    for r in all_rows:
        print(f"{r.applied_date:<12} {r.company[:33]:<34} {r.role[:43]:<44} {r.stage}")


def print_summary(summary: list[tuple[str, int | None, int]]) -> None:
    print("\n=== Count per month (header 'Anzahl Bewerbungen' vs parsed detail) ===")
    tot_hdr = tot_det = 0
    for month, hdr, det in summary:
        tot_hdr += hdr or 0
        tot_det += det
        delta = (hdr - det) if hdr is not None else None
        label = MONTH_NAMES.get(month, month)
        print(f"  {label:<16} header={hdr}  parsed={det}  delta={delta}")
    print(
        f"  {'TOTAL':<16} header={tot_hdr}  parsed={tot_det}  delta={tot_hdr - tot_det}"
    )


def print_stage_breakdown(all_rows: List[Row]) -> None:
    print("\n=== Stage breakdown ===")
    from collections import Counter

    sc = Counter(r.stage for r in all_rows)
    for st, c in sc.items():
        print(f"  {st}: {c}")


def print_flagged_rows(all_rows: List[Row]) -> None:
    print("\n=== Flagged rows (contact/address/uncertain) ===")
    for r in all_rows:
        interesting = [f for f in r.flags if f != "no-link"]
        if interesting:
            print(
                "  ["
                f"{','.join(interesting)}] {r.applied_date} {r.company} | "
                f"role='{r.role}' | contact='{r.contact}' "
                f"email='{r.email}' phone='{r.phone}'"
            )


def insert_rows(all_rows: List[Row], db_path: str) -> int:
    sys.path.insert(
        0,
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"
        ),
    )
    from jobroom_helper.utils.db_helper import ApplicationStore

    store = ApplicationStore(db_path=db_path)
    inserted = 0
    for r in all_rows:
        url = build_url(r)
        props = {
            "Company": r.company,
            "Role": r.role,
            "URL": url,
            "Date": r.applied_date,
            "Applied date": r.applied_date,
            "Stage": r.stage,
            "Source": f"Job-Room (NpA {MONTH_NAMES.get(r.month, r.month)})",
            "Notes": r.result,
            "Address": r.address,
        }
        if r.contact:
            props["Contact"] = r.contact
        if r.email:
            props["Email"] = r.email
        if r.phone:
            props["Phone"] = r.phone
        rid = store.create_page(properties=props, return_existing=False)
        if rid:
            inserted += 1
    return inserted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--write", action="store_true")
    ap.add_argument(
        "--db-path",
        default=os.environ.get("JOBROOM_DB_PATH", "data/applications.db"),
    )
    args = ap.parse_args()

    all_rows, summary = load_rows(args.pdf_dir)
    print_parsed_rows(all_rows)
    print_summary(summary)
    print_stage_breakdown(all_rows)
    print_flagged_rows(all_rows)

    if not args.write:
        print("\n(dry run; pass --write to insert into DB)")
        return

    inserted = insert_rows(all_rows, args.db_path)
    print(f"\nInserted {inserted} / {len(all_rows)} rows (idempotent via npa:// URL).")


if __name__ == "__main__":
    main()
