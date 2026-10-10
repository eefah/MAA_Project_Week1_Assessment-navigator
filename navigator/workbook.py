"""Read the NHS Community Health Services waiting-list workbook.

The layout is discovered from the content (sheet titles, header text and
notes) rather than fixed row or column positions. Cell values are kept as
they appear in the workbook: blanks stay blank and suppression markers stay
as text. Nothing is ever converted to zero.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

SERVICE_PATTERN = re.compile(r"community paediatric", re.IGNORECASE)
ORG_NAME_PATTERN = re.compile(r"^organi[sz]ation name$", re.IGNORECASE)
ORG_TYPE_PATTERN = re.compile(r"^organi[sz]ation type$", re.IGNORECASE)
ORG_CODE_PATTERN = re.compile(r"^organi[sz]ation code$", re.IGNORECASE)
TOTAL_TITLE_PATTERN = re.compile(r"total waiting list by service", re.IGNORECASE)
BAND_TITLE_PATTERN = re.compile(r"number waiting\s+(?P<band>.+?)\s+by service", re.IGNORECASE)
PERIOD_PATTERN = re.compile(r"by service,\s*(?P<period>[A-Za-z]+\s+\d{4})")
RANGE_WEEKS_PATTERN = re.compile(r"(\d+)\s*-\s*(\d+)\s*weeks", re.IGNORECASE)
OVER_WEEKS_PATTERN = re.compile(r"over\s*(\d+)\s*weeks", re.IGNORECASE)
BLANK_NOTE_PATTERN = re.compile(r"\bblanks?\b", re.IGNORECASE)
MARKER_NOTE_PATTERN = re.compile(r"^(?P<marker>[^\w\s(]{1,3})\s+(?P<text>.+)$")
NUMBER_PATTERN = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$|^-?\d+(\.\d+)?$")

MAX_HEADER_SCAN_ROWS = 30


class WorkbookError(Exception):
    """The file could not be read as the expected NHS workbook."""


@dataclass(frozen=True)
class Cell:
    """One workbook value, with its original form preserved.

    kind is "number", "blank" or "marker". value is only set for numbers.
    """

    raw: object
    kind: str
    value: Optional[float] = None

    @property
    def is_number(self) -> bool:
        return self.kind == "number"

    def display_raw(self) -> str:
        return "" if self.kind == "blank" else str(self.raw)


def classify_cell(raw: object) -> Cell:
    if raw is None:
        return Cell(raw="", kind="blank")
    if isinstance(raw, float) and pd.isna(raw):
        return Cell(raw="", kind="blank")
    if isinstance(raw, bool):
        return Cell(raw=raw, kind="marker")
    if isinstance(raw, (int, float)):
        return Cell(raw=raw, kind="number", value=float(raw))
    text = str(raw)
    stripped = text.strip()
    if stripped == "":
        return Cell(raw=text, kind="blank")
    if NUMBER_PATTERN.match(stripped):
        return Cell(raw=text, kind="number", value=float(stripped.replace(",", "")))
    return Cell(raw=text, kind="marker")


@dataclass
class Band:
    label: str
    lower_weeks: int
    upper_weeks: Optional[int]

    @property
    def short_label(self) -> str:
        if self.upper_weeks is None:
            return f"Over {self.lower_weeks} weeks"
        if self.lower_weeks == 0:
            return f"0–{self.upper_weeks} weeks"
        return f"Over {self.lower_weeks}–{self.upper_weeks} weeks"


def parse_band(text: str) -> Optional[Band]:
    match = RANGE_WEEKS_PATTERN.search(text)
    if match:
        return Band(label=text, lower_weeks=int(match.group(1)), upper_weeks=int(match.group(2)))
    match = OVER_WEEKS_PATTERN.search(text)
    if match:
        return Band(label=text, lower_weeks=int(match.group(1)), upper_weeks=None)
    return None


@dataclass
class ServiceSheet:
    """A sheet holding one measure (total or one band) by organisation."""

    name: str
    title: str
    kind: str  # "total" or "band"
    band: Optional[Band]
    period: Optional[str]
    header_row: int  # zero-based
    notes: list[str]
    type_col: Optional[int]
    code_col: Optional[int]
    name_col: int
    service_col: int
    service_header: str
    frame: pd.DataFrame  # the original sheet, header=None


@dataclass
class Check:
    status: str  # "ok", "warning" or "error"
    message: str


@dataclass
class Organisation:
    org_type: str
    code: str
    name: str

    @property
    def key(self) -> str:
        return f"{self.org_type}|{self.code}|{self.name}"

    @property
    def label(self) -> str:
        if self.org_type.lower() == "national":
            return f"{self.name} (national)"
        return self.name


@dataclass
class ParsedWorkbook:
    sheet_names: list[str]
    raw_sheets: dict[str, pd.DataFrame]
    cover: list[tuple[str, str]]
    total: Optional[ServiceSheet]
    bands: list[ServiceSheet]
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(c.status == "error" for c in self.checks)

    @property
    def period(self) -> Optional[str]:
        return self.total.period if self.total else None

    @property
    def notes(self) -> list[str]:
        seen: list[str] = []
        for sheet in [self.total, *self.bands]:
            if sheet is None:
                continue
            for note in sheet.notes:
                if note not in seen:
                    seen.append(note)
        return seen

    @property
    def blank_note(self) -> Optional[str]:
        """The workbook's own explanation of blank cells, if it gives one."""
        for note in self.notes:
            if BLANK_NOTE_PATTERN.search(note):
                return note
        return None

    @property
    def marker_notes(self) -> dict[str, str]:
        """Markers whose meaning the workbook documents in a note."""
        found: dict[str, str] = {}
        for note in self.notes:
            match = MARKER_NOTE_PATTERN.match(note)
            if match:
                found.setdefault(match.group("marker"), note)
        return found

    @property
    def sum_note(self) -> Optional[str]:
        for frame in self.raw_sheets.values():
            for value in frame.head(MAX_HEADER_SCAN_ROWS).iloc[:, 0]:
                text = str(value)
                if "sum of weekly breakdowns" in text.lower():
                    return text.strip()
        return None

    def organisations(self) -> list[Organisation]:
        if self.total is None:
            return []
        return _organisations(self.total)

    def selectable_organisations(self) -> list[Organisation]:
        """National first, then providers alphabetically."""
        orgs = self.organisations()
        national = [o for o in orgs if o.org_type.lower() == "national"]
        providers = sorted(
            (o for o in orgs if o.org_type.lower() == "provider"), key=lambda o: o.name.lower()
        )
        if not national and not providers:
            return orgs
        return national + providers

    def figures_for(self, org: Organisation) -> "OrgFigures":
        total = _lookup(self.total, org) if self.total else None
        band_cells = [(sheet.band, _lookup(sheet, org), sheet) for sheet in self.bands]
        return OrgFigures(organisation=org, total=total, bands=band_cells)


@dataclass
class OrgFigures:
    organisation: Organisation
    total: Optional[Cell]
    bands: list[tuple[Band, Optional[Cell], ServiceSheet]]

    def waiting_over(self, weeks: int) -> Optional[float]:
        """Sum of published bands starting at or above `weeks`.

        Returns None unless every contributing band is a reported number.
        """
        relevant = [cell for band, cell, _ in self.bands if band.lower_weeks >= weeks]
        if not relevant or any(cell is None or not cell.is_number for cell in relevant):
            return None
        return sum(cell.value for cell in relevant)  # type: ignore[misc]

    def bands_contributing(self, weeks: int) -> list[Band]:
        return [band for band, _, _ in self.bands if band.lower_weeks >= weeks]

    def band_sum(self) -> Optional[float]:
        if not self.bands or any(cell is None or not cell.is_number for _, cell, _ in self.bands):
            return None
        return sum(cell.value for _, cell, _ in self.bands)  # type: ignore[misc]


def _clean(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _title(frame: pd.DataFrame) -> str:
    for row in range(min(MAX_HEADER_SCAN_ROWS, len(frame))):
        for value in frame.iloc[row]:
            text = _clean(value)
            if text:
                return text
    return ""


def find_header_row(frame: pd.DataFrame) -> Optional[int]:
    """First row with an organisation name heading and a community paediatric column."""
    for row in range(min(MAX_HEADER_SCAN_ROWS, len(frame))):
        cells = [_clean(v) for v in frame.iloc[row]]
        if any(ORG_NAME_PATTERN.match(c) for c in cells) and any(
            SERVICE_PATTERN.search(c) for c in cells
        ):
            return row
    return None


def _find_col(cells: list[str], pattern: re.Pattern) -> Optional[int]:
    for index, cell in enumerate(cells):
        if pattern.search(cell):
            return index
    return None


def _service_col(cells: list[str]) -> Optional[int]:
    matches = [i for i, c in enumerate(cells) if SERVICE_PATTERN.search(c)]
    if not matches:
        return None
    cyp = [i for i in matches if cells[i].upper().startswith("(CYP)")]
    return (cyp or matches)[0]


def _service_sheet(name: str, frame: pd.DataFrame) -> Optional[ServiceSheet]:
    title = _title(frame)
    if TOTAL_TITLE_PATTERN.search(title):
        kind, band = "total", None
    else:
        match = BAND_TITLE_PATTERN.search(title)
        if not match:
            return None
        band = parse_band(match.group("band"))
        if band is None:
            return None
        kind = "band"
    header_row = find_header_row(frame)
    if header_row is None:
        return None
    cells = [_clean(v) for v in frame.iloc[header_row]]
    name_col = _find_col(cells, ORG_NAME_PATTERN)
    service_col = _service_col(cells)
    if name_col is None or service_col is None:
        return None
    period_match = PERIOD_PATTERN.search(title)
    notes = [
        _clean(frame.iloc[row, 0])
        for row in range(1, header_row)
        if _clean(frame.iloc[row, 0])
    ]
    return ServiceSheet(
        name=name,
        title=title,
        kind=kind,
        band=band,
        period=period_match.group("period") if period_match else None,
        header_row=header_row,
        notes=notes,
        type_col=_find_col(cells, ORG_TYPE_PATTERN),
        code_col=_find_col(cells, ORG_CODE_PATTERN),
        name_col=name_col,
        service_col=service_col,
        service_header=cells[service_col],
        frame=frame,
    )


def _org_from_row(sheet: ServiceSheet, row: pd.Series) -> Organisation:
    return Organisation(
        org_type=_clean(row.iloc[sheet.type_col]) if sheet.type_col is not None else "",
        code=_clean(row.iloc[sheet.code_col]) if sheet.code_col is not None else "",
        name=_clean(row.iloc[sheet.name_col]),
    )


def _data_rows(sheet: ServiceSheet):
    for index in range(sheet.header_row + 1, len(sheet.frame)):
        row = sheet.frame.iloc[index]
        if _clean(row.iloc[sheet.name_col]):
            yield index, row


def _organisations(sheet: ServiceSheet) -> list[Organisation]:
    return [_org_from_row(sheet, row) for _, row in _data_rows(sheet)]


def _lookup(sheet: ServiceSheet, org: Organisation) -> Optional[Cell]:
    for _, row in _data_rows(sheet):
        candidate = _org_from_row(sheet, row)
        same_code = org.code and candidate.code == org.code
        same_name = candidate.name == org.name and candidate.org_type == org.org_type
        if same_code or (not org.code and same_name):
            return classify_cell(row.iloc[sheet.service_col])
    return None


def _cover(frames: dict[str, pd.DataFrame]) -> list[tuple[str, str]]:
    for name, frame in frames.items():
        if "cover" not in name.lower():
            continue
        pairs: list[tuple[str, str]] = []
        for _, row in frame.iterrows():
            values = [_clean(v) for v in row]
            label = values[0] if values else ""
            rest = " ".join(v for v in values[1:] if v)
            if label.endswith(":"):
                pairs.append((label.rstrip(":"), rest))
            elif not label and rest and pairs:
                pairs[-1] = (pairs[-1][0], f"{pairs[-1][1]} {rest}")
        return pairs
    return []


def _validate(parsed: ParsedWorkbook) -> list[Check]:
    checks: list[Check] = [
        Check("ok", f"Workbook opened: {len(parsed.sheet_names)} sheets found."),
    ]
    if parsed.cover:
        checks.append(Check("ok", "Cover page found with source details."))
    else:
        checks.append(Check("warning", "No cover page found, so source details are limited."))

    if parsed.total is None:
        checks.append(
            Check(
                "error",
                "Could not find a 'Total waiting list by service' sheet with an "
                "organisation name column and a community paediatric column.",
            )
        )
    else:
        checks.append(
            Check(
                "ok",
                f"Total waiting list found on '{parsed.total.name}' "
                f"(headings on row {parsed.total.header_row + 1}, "
                f"column '{parsed.total.service_header}').",
            )
        )

    if not parsed.bands:
        checks.append(Check("error", "No waiting-time band sheets found."))
    else:
        checks.append(Check("ok", f"{len(parsed.bands)} waiting-time band sheets found."))
        for previous, current in zip(parsed.bands, parsed.bands[1:]):
            if previous.band.upper_weeks != current.band.lower_weeks:  # type: ignore[union-attr]
                checks.append(
                    Check(
                        "warning",
                        f"Band '{previous.band.label}' is not followed directly by "  # type: ignore[union-attr]
                        f"'{current.band.label}'. A band may be missing.",  # type: ignore[union-attr]
                    )
                )
        if parsed.bands[-1].band.upper_weeks is not None:  # type: ignore[union-attr]
            checks.append(Check("warning", "No open-ended top band (for example 'over 104 weeks') found."))

    periods = {s.period for s in [parsed.total, *parsed.bands] if s is not None}
    if len(periods) > 1:
        checks.append(
            Check("warning", f"Sheets report different months: {', '.join(sorted(p or '?' for p in periods))}.")
        )
    elif periods and None not in periods:
        checks.append(Check("ok", f"Reporting month: {periods.pop()}."))
    return checks


def parse_workbook(data: bytes) -> ParsedWorkbook:
    try:
        frames = pd.read_excel(
            io.BytesIO(data),
            sheet_name=None,
            header=None,
            dtype=object,
            keep_default_na=False,  # keeps markers such as "N/A" or "-" as text
            na_values=[],
            engine="openpyxl",
        )
    except Exception as exc:  # openpyxl raises several types for bad files
        raise WorkbookError(
            "This file could not be opened as an Excel workbook (.xlsx). "
            "Please upload the original NHS file."
        ) from exc

    total: Optional[ServiceSheet] = None
    bands: list[ServiceSheet] = []
    for name, frame in frames.items():
        sheet = _service_sheet(name, frame)
        if sheet is None:
            continue
        if sheet.kind == "total" and total is None:
            total = sheet
        elif sheet.kind == "band":
            bands.append(sheet)
    bands.sort(key=lambda s: s.band.lower_weeks)  # type: ignore[union-attr]

    parsed = ParsedWorkbook(
        sheet_names=list(frames),
        raw_sheets=frames,
        cover=_cover(frames),
        total=total,
        bands=bands,
    )
    parsed.checks = _validate(parsed)
    return parsed


def default_organisation(orgs: list[Organisation]) -> Optional[Organisation]:
    """Guy's and St Thomas' if present, otherwise the national row."""
    for org in orgs:
        if org.code.upper() == "RJ1" or "GUY'S AND ST THOMAS" in org.name.upper().replace("’", "'"):
            return org
    for org in orgs:
        if org.org_type.lower() == "national":
            return org
    return orgs[0] if orgs else None
