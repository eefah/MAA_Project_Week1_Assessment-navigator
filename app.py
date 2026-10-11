"""Assessment Navigator – a local prototype for parents.

Run with:  uv run streamlit run app.py
"""

from __future__ import annotations

import html
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from navigator import ai
from navigator import guidance as guidance_mod
from navigator import personal
from navigator.auth import is_hosted, require_password, secret
from navigator.workbook import (
    Cell,
    ParsedWorkbook,
    WorkbookError,
    default_organisation,
    parse_workbook,
)

APP_DIR = Path(__file__).resolve().parent
BUNDLED_PATTERN = "Community-health-services-waiting-lists-*.xlsx"

st.set_page_config(page_title="Assessment Navigator", page_icon="🧭", layout="wide")

CSS = """
<style>
.block-container {padding-top: 2.5rem; padding-bottom: 5rem; max-width: 1200px; margin: 0 auto;}
.an-list {list-style: none; padding-left: 0; margin: 0 0 1.25rem 0;}
.an-list li {padding: 0.7rem 0; border-bottom: 1px solid rgba(128,128,128,0.2); line-height: 1.6;}
.an-list li:last-child {border-bottom: none;}
.an-src {display: block; font-size: 0.85rem; opacity: 0.75; margin-top: 0.25rem;}
.an-list li.an-unverified {border: 1px dashed #c98500; border-radius: 0.5rem;
  padding: 0.7rem 0.9rem; margin: 0.5rem 0; background: rgba(237,161,0,0.08);}
.an-flag {display: inline-block; font-size: 0.75rem; font-weight: 600; letter-spacing: 0.03em;
  padding: 0.05rem 0.5rem; border-radius: 0.3rem; background: #fab219; color: #1a1a19;
  margin-right: 0.4rem;}
@media (max-width: 640px) {
  .block-container {padding-left: 1rem; padding-right: 1rem; padding-top: 1.5rem;}
}
</style>
"""

PROVENANCE = {
    "nhs": ("NHS data", ":material/database:", "blue"),
    "guidance": ("Sourced guidance", ":material/menu_book:", "green"),
    "parent": ("Your information", ":material/person:", "violet"),
    "ai": ("AI-generated", ":material/smart_toy:", "orange"),
}


# ---------------------------------------------------------------- helpers


def provenance(kind: str) -> None:
    label, icon, colour = PROVENANCE[kind]
    st.badge(label, icon=icon, color=colour)


def uk_date(value: Optional[str | date]) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return f"{value.day} {value:%B %Y}"


def render_items(items: list[dict[str, Any]], sources: dict[str, Any]) -> None:
    """A list of guidance items, each with its source or an 'unverified' flag."""
    if not items:
        return
    parts = ['<ul class="an-list">']
    for item in items:
        text = html.escape(item["text"])
        if item["status"] == "verified":
            src = sources[item["source"]]
            link = (
                f'<a href="{html.escape(src["url"])}" target="_blank" rel="noopener">'
                f'{html.escape(src["publisher"])} – {html.escape(src["title"])}</a>'
            )
            parts.append(
                f'<li>{text}<span class="an-src">Source: {link} · '
                f'checked {uk_date(src["verified_on"])}</span></li>'
            )
        else:
            parts.append(
                f'<li class="an-unverified"><span class="an-flag">Not verified</span>{text}'
                '<span class="an-src">No official source has been checked for this yet. '
                "Please confirm with the service.</span></li>"
            )
    parts.append("</ul>")
    st.markdown("".join(parts), unsafe_allow_html=True)


@st.cache_data(show_spinner="Reading the workbook…")
def cached_parse(data: bytes) -> ParsedWorkbook:
    return parse_workbook(data)


def bundled_workbook() -> Optional[Path]:
    found = sorted(APP_DIR.glob(BUNDLED_PATTERN))
    return found[-1] if found else None


# ---------------------------------------------------------------- tab 1: my child


STAGE_KEY = "p_current_stage"
DATE_KEYS = {
    "paed_referral_date": "p_paed_referral_date",
    "paed_accepted_date": "p_paed_accepted_date",
    "autism_referral_date": "p_autism_referral_date",
    "autism_accepted_date": "p_autism_accepted_date",
}
NOTES_KEY = "p_contact_notes"


def checklist_key(stage_id: str, index: int) -> str:
    return f"chk_{stage_id}_{index}"


def load_saved_into_session(data: dict[str, Any]) -> None:
    if st.session_state.get("p_loaded"):
        return
    st.session_state["p_loaded"] = True
    record = personal.load()
    if not record:
        return
    for field, key in DATE_KEYS.items():
        st.session_state[key] = record[field]
    stage_ids = [s["id"] for s in data["stages"]]
    if record["current_stage"] in stage_ids:
        st.session_state[STAGE_KEY] = record["current_stage"]
    st.session_state[NOTES_KEY] = record["contact_notes"]
    for stage in data["stages"]:
        done = record["checklist"].get(stage["id"], set())
        for index, item in enumerate(stage["preparation"]):
            st.session_state[checklist_key(stage["id"], index)] = item["text"] in done
    st.session_state["p_saved_at"] = record.get("saved_at")


def clear_personal_session() -> None:
    for key in list(st.session_state.keys()):
        if key.startswith(("p_", "chk_")) and key != "p_loaded":
            del st.session_state[key]


def current_record(data: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {field: st.session_state.get(key) for field, key in DATE_KEYS.items()}
    record["current_stage"] = st.session_state.get(STAGE_KEY) or ""
    record["contact_notes"] = st.session_state.get(NOTES_KEY) or ""
    record["checklist"] = {
        stage["id"]: {
            item["text"]
            for index, item in enumerate(stage["preparation"])
            if st.session_state.get(checklist_key(stage["id"], index))
        }
        for stage in data["stages"]
    }
    return record


def referral_clock(
    title: str,
    referral: Optional[date],
    accepted: Optional[date],
    benchmark: Optional[dict[str, Any]],
    sources: dict[str, Any],
    today: date,
) -> None:
    with st.container(border=True):
        st.markdown(f"**{title}**")
        if referral is None:
            st.caption("Add a referral date above to see the time since referral.")
        else:
            st.markdown(
                f"Referred on {uk_date(referral)}: **{personal.describe_elapsed(referral, today)}** ago."
            )
            if accepted is not None:
                if accepted < referral:
                    st.warning("The acceptance date is earlier than the referral date. Please check both dates.")
                else:
                    st.markdown(
                        f"Accepted on {uk_date(accepted)}: "
                        f"**{personal.describe_elapsed(accepted, today)}** ago."
                    )
        if benchmark is None:
            return
        if benchmark["status"] == "verified" and benchmark.get("months"):
            src = sources[benchmark["source"]]
            st.markdown(
                f"{benchmark['kind']}: {benchmark['text']}  \n"
                f"*What it measures:* {benchmark['measures']}  \n"
                f"Source: [{src['publisher']} – {src['title']}]({src['url']}), "
                f"checked {uk_date(src['verified_on'])}."
            )
            if referral is not None and personal.add_months(referral, benchmark["months"]) <= today:
                st.markdown(
                    f"More than {benchmark['months']} months have passed since the referral date you entered."
                )
            st.caption(
                "This is a national recommendation for this referral only. It is not a "
                "prediction of when your child will be seen."
            )
        else:
            render_items([benchmark], sources)


def tab_my_child(data: dict[str, Any]) -> None:
    hosted = is_hosted()
    sources = data["sources"]
    stages = data["stages"]
    stage_ids = [s["id"] for s in stages]
    titles = {s["id"]: s["title"] for s in stages}
    today = date.today()

    if not hosted:
        load_saved_into_session(data)

    provenance("parent")
    st.header("My child's next steps")
    st.write(
        "Keep track of your child's referrals and get ready for your next conversation "
        "with the service. Everything on this tab is what you enter."
    )
    if hosted:
        st.info(
            "Information is processed on the hosting server for this session and is not "
            "deliberately saved to disk."
        )
    else:
        st.info(
            "Nothing you enter here is sent anywhere. When you press **Save**, it is stored "
            "in the `local_data/` folder on this computer. **Delete** removes it."
        )

    flash = st.session_state.pop("p_flash", None)
    if flash:
        st.success(flash)

    for key in DATE_KEYS.values():
        st.session_state.setdefault(key, None)

    st.subheader("Referral dates")
    st.caption(
        "Your child may have two separate referrals, each with its own waiting time. "
        "Leave any date blank if it doesn't apply yet."
    )
    left, right = st.columns(2)
    with left:
        st.markdown("**Community paediatrics**")
        st.date_input("Date referred", key=DATE_KEYS["paed_referral_date"],
                      max_value=today, format="DD/MM/YYYY")
        st.date_input("Date accepted (optional)", key=DATE_KEYS["paed_accepted_date"],
                      max_value=today, format="DD/MM/YYYY")
    with right:
        st.markdown("**Specialist autism assessment**")
        st.date_input("Date referred", key=DATE_KEYS["autism_referral_date"],
                      max_value=today, format="DD/MM/YYYY")
        st.date_input("Date accepted (optional)", key=DATE_KEYS["autism_accepted_date"],
                      max_value=today, format="DD/MM/YYYY")

    st.subheader("Time since each referral")
    benchmarks = {b["clock"]: b for b in data.get("benchmarks", [])}
    referral_clock(
        "Community paediatric referral",
        st.session_state.get(DATE_KEYS["paed_referral_date"]),
        st.session_state.get(DATE_KEYS["paed_accepted_date"]),
        benchmarks.get("paediatric"),
        sources,
        today,
    )
    referral_clock(
        "Specialist autism assessment referral",
        st.session_state.get(DATE_KEYS["autism_referral_date"]),
        st.session_state.get(DATE_KEYS["autism_accepted_date"]),
        benchmarks.get("autism"),
        sources,
        today,
    )

    st.subheader("Where are you now?")
    if st.session_state.get(STAGE_KEY) not in stage_ids:
        st.session_state[STAGE_KEY] = stage_ids[0]
    stage_id = st.selectbox(
        "Current stage", stage_ids, key=STAGE_KEY, format_func=lambda s: titles[s]
    )
    stage = guidance_mod.stage_by_id(data, stage_id)

    st.markdown("**Checklist for this stage**")
    for index, item in enumerate(stage["preparation"]):
        st.checkbox(item["text"], key=checklist_key(stage_id, index))
    st.caption("Checklist items come from the sourced guidance. See the Assessment pathway tab for sources.")

    st.markdown("**Questions for your next conversation**")
    render_items(stage["questions"], sources)

    st.subheader("Contact notes")
    st.text_area(
        "Who you spoke to, when, and what they said",
        key=NOTES_KEY,
        height=140,
        placeholder="For example: 14 Oct – phoned appointment enquiries, told referral is on the waiting list.",
    )

    if hosted:
        return

    st.divider()
    saved_at = st.session_state.get("p_saved_at")
    if saved_at:
        st.caption(f"Last saved on this computer: {saved_at.replace('T', ' at ')}")
    save_col, delete_col = st.columns(2)
    with save_col:
        if st.button("Save", type="primary", icon=":material/save:", width="stretch"):
            st.session_state["p_saved_at"] = personal.save(current_record(data))
            st.session_state["p_flash"] = "Saved to local_data/ on this computer."
            st.rerun()
    with delete_col:
        if st.button("Delete saved information", icon=":material/delete:", width="stretch"):
            st.session_state["p_confirm_delete"] = True
    if st.session_state.get("p_confirm_delete"):
        st.warning("This removes your saved information from this computer and clears this page.")
        yes, no = st.columns(2)
        if yes.button("Yes, delete it", width="stretch"):
            existed = personal.delete()
            clear_personal_session()
            st.session_state["p_flash"] = (
                "Your saved information has been deleted." if existed else "There was nothing saved to delete."
            )
            st.rerun()
        if no.button("Cancel", width="stretch"):
            st.session_state["p_confirm_delete"] = False
            st.rerun()


# ---------------------------------------------------------------- tab 2: pathway


def tab_pathway(data: dict[str, Any]) -> None:
    sources = data["sources"]
    stages = data["stages"]

    provenance("guidance")
    st.header("Assessment pathway")
    st.write(
        "A typical route through a community paediatric referral, based on official NHS, "
        "NICE and Evelina London information. Each point links to where it came from."
    )
    st.markdown("**Routes can vary**")
    render_items(data.get("route_notes", []), sources)

    st.markdown("**The five stages**")
    stage_tabs = st.tabs([f"{n}. {stage['title']}" for n, stage in enumerate(stages, start=1)])
    for position, (stage_tab, stage) in enumerate(zip(stage_tabs, stages), start=1):
        with stage_tab:
            st.subheader(f"Stage {position} of {len(stages)}: {stage['title']}")
            st.write(stage["summary"])
            for section, heading in [
                ("what_happens", "What happens"),
                ("preparation", "How to prepare"),
                ("questions", "Questions to ask"),
                ("contacts", "Service contacts"),
            ]:
                st.markdown(f"#### {heading}")
                render_items(stage[section], sources)

    with st.container(border=True):
        st.markdown("**Starting an assessment is not the same as a diagnosis**")
        render_items(data.get("assessment_vs_diagnosis", []), sources)

    with st.expander("About this guidance"):
        st.write(
            "The guidance is kept in `guidance/pathway.json`, separate from the app, so it can "
            "be checked and updated. Items marked **Not verified** have no official source yet."
        )
        for src in sources.values():
            st.markdown(
                f"- [{src['publisher']} – {src['title']}]({src['url']}), checked "
                f"{uk_date(src['verified_on'])}. {src.get('notes', '')}"
            )
        st.caption("This guidance is general information, not clinical advice for your child.")


# ---------------------------------------------------------------- tab 3: waiting list


def cell_text(cell: Optional[Cell]) -> str:
    if cell is None:
        return "Not found"
    if cell.kind == "number":
        value = cell.value or 0
        return f"{value:,.0f}" if float(value).is_integer() else f"{value:,}"
    if cell.kind == "blank":
        return "Not reported"
    return f"Shown as “{cell.raw}”"


def number_text(value: Optional[float]) -> str:
    return "Not available" if value is None else f"{value:,.0f}"


def days_from_label(label: str) -> str:
    match = re.search(r"\(([^)]*)\)", label)
    return match.group(1) if match else ""


def explain_missing(parsed: ParsedWorkbook, cells: list[Optional[Cell]]) -> None:
    if any(c is not None and c.kind == "blank" for c in cells):
        note = parsed.blank_note
        text = "**Not reported** means the cell is blank in the workbook."
        if note:
            text += f" The workbook says: “{note}”"
        st.caption(text)
    markers = {str(c.raw).strip() for c in cells if c is not None and c.kind == "marker"}
    documented = parsed.marker_notes
    for marker in sorted(markers):
        if marker in documented:
            st.caption(f"“{marker}” – the workbook says: “{documented[marker]}”")
        else:
            st.caption(f"“{marker}” is shown as it appears in the workbook. The workbook does not explain it.")


def band_chart(rows: list[tuple[str, str, float]]) -> go.Figure:
    dark = getattr(st.context.theme, "type", None) == "dark"
    colour = "#3987e5" if dark else "#2a78d6"
    labels = [r[0] for r in rows]
    fig = go.Figure(
        go.Bar(
            x=[r[2] for r in rows],
            y=labels,
            orientation="h",
            marker=dict(color=colour, cornerradius=4),
            text=[f"{r[2]:,.0f}" for r in rows],
            textposition="outside",
            cliponaxis=False,
            customdata=[r[1] for r in rows],
            hovertemplate="<b>%{y}</b><br>%{customdata}<br>%{x:,} waiting<extra></extra>",
        )
    )
    fig.update_yaxes(autorange="reversed", categoryorder="array", categoryarray=labels, title=None)
    fig.update_xaxes(
        title="Number waiting", showgrid=True, gridcolor="rgba(128,128,128,0.18)",
        zeroline=False, rangemode="tozero",
    )
    fig.update_layout(
        height=60 + 44 * len(rows),
        margin=dict(l=0, r=48, t=8, b=8),
        bargap=0.4,
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def tab_waiting_list() -> Optional[tuple]:
    """Render the tab. Returns (parsed, org, figures, file_origin) when figures are shown."""
    provenance("nhs")
    st.header("Waiting-list picture")
    st.info(
        "- These are **community paediatric** waiting-list figures. They include all "
        "children waiting for this service, not only those waiting for an autism assessment.\n"
        "- Provider figures cover the whole provider, **not Lambeth only**.\n"
        "- They **cannot predict** when an individual child will be seen."
    )

    uploaded = st.file_uploader(
        "Upload a newer NHS Community Health Services waiting-list workbook (optional)",
        type=["xlsx"],
        help="Use the original Excel file from NHS England. It is read on this computer only.",
    )
    bundled = bundled_workbook()
    if uploaded is not None:
        data, source_label, file_origin = uploaded.getvalue(), f"Uploaded file: {uploaded.name}", "uploaded"
    elif bundled is not None:
        data, source_label, file_origin = bundled.read_bytes(), f"Bundled workbook: {bundled.name}", "bundled"
    else:
        st.write("Upload the NHS workbook to see the figures.")
        return None

    try:
        parsed = cached_parse(data)
    except WorkbookError as exc:
        st.error(str(exc))
        return None

    errors = [c for c in parsed.checks if c.status == "error"]
    warnings = [c for c in parsed.checks if c.status == "warning"]
    if errors:
        st.error("This workbook could not be used:\n\n" + "\n".join(f"- {c.message}" for c in errors))
        return None
    for check in warnings:
        st.warning(check.message)

    st.caption(f"{source_label} · Reporting month: {parsed.period or 'not stated'}")

    orgs = parsed.selectable_organisations()
    default = default_organisation(orgs)
    keys = [o.key for o in orgs]
    by_key = {o.key: o for o in orgs}
    chosen_key = st.selectbox(
        "Provider or national view",
        keys,
        index=keys.index(default.key) if default else 0,
        format_func=lambda k: by_key[k].label,
        help="Guy's and St Thomas' runs Evelina London community paediatrics.",
        key="provider_key",
    )
    org = by_key[chosen_key]
    figures = parsed.figures_for(org)

    st.subheader(org.label)
    over_52 = figures.waiting_over(52)
    over_104 = figures.waiting_over(104)
    bands_52 = " and ".join(b.short_label.lower() for b in figures.bands_contributing(52))
    bands_104 = " and ".join(b.short_label.lower() for b in figures.bands_contributing(104))
    col1, col2, col3 = st.columns(3)
    col1.metric("Total waiting", cell_text(figures.total), border=True,
                help="Total community paediatric waiting list, as published.")
    col2.metric("Waiting over 52 weeks", number_text(over_52), border=True,
                help=f"Adds the published bands: {bands_52}. Shown only if each band has a reported number.")
    col3.metric("Waiting over 104 weeks", number_text(over_104), border=True,
                help=f"The published band: {bands_104}.")
    explain_missing(parsed, [figures.total] + [cell for _, cell, _ in figures.bands])

    st.markdown("#### How long children have been waiting")
    plotted = [
        (band.short_label, days_from_label(band.label), cell.value)
        for band, cell, _ in figures.bands
        if cell is not None and cell.is_number
    ]
    not_plotted = [
        f"{band.short_label}: {cell_text(cell)}"
        for band, cell, _ in figures.bands
        if cell is None or not cell.is_number
    ]
    if plotted:
        st.plotly_chart(
            band_chart(plotted),
            config={"displayModeBar": False, "responsive": True},
            alt=f"Bar chart of the community paediatric waiting list for {org.label} by waiting-time band.",
        )
    else:
        st.write("No waiting-time bands have reported numbers for this selection.")
    if not_plotted:
        st.caption("Not shown in the chart (no reported number): " + "; ".join(not_plotted) + ".")

    band_sum = figures.band_sum()
    if band_sum is None or figures.total is None or not figures.total.is_number:
        st.caption(
            "Comparing the bands with the total is incomplete, because the total or one or more "
            "bands is not a reported number."
        )
    else:
        if band_sum == figures.total.value:
            st.caption("The waiting-time bands add up to the total.")
        else:
            note = parsed.sum_note
            st.caption(
                f"The waiting-time bands add up to {band_sum:,.0f}, which is different from the total."
                + (f" The workbook says: “{note}”" if note else "")
            )

    table = pd.DataFrame(
        {
            "Waiting time": [band.short_label for band, _, _ in figures.bands],
            "Days": [days_from_label(band.label) for band, _, _ in figures.bands],
            "Number waiting": [cell_text(cell) for _, cell, _ in figures.bands],
        }
    )
    with st.expander("Table of these figures"):
        st.dataframe(table, hide_index=True, width="stretch")

    with st.expander("Original data"):
        st.caption("Values exactly as they appear in the workbook. Blank cells are left blank.")
        rows = []
        for sheet in [parsed.total, *parsed.bands]:
            cell = figures.total if sheet is parsed.total else next(
                c for b, c, s in figures.bands if s is sheet
            )
            rows.append(
                {
                    "Sheet": sheet.name,
                    "Measure": sheet.title,
                    "Column": sheet.service_header,
                    "Value in workbook": "" if cell is None else cell.display_raw(),
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        sheet_name = st.selectbox("Preview a whole sheet", parsed.sheet_names)
        raw = parsed.raw_sheets[sheet_name].map(lambda v: "" if v is None else str(v))
        raw.index = raw.index + 1
        raw.columns = [f"Col {i + 1}" for i in range(raw.shape[1])]
        st.dataframe(raw, width="stretch", height=360)

    with st.expander("Source details"):
        st.markdown(f"**File:** {source_label}")
        for label, value in parsed.cover:
            st.markdown(f"**{label}:** {value}")
        st.markdown("**Sheets:** " + ", ".join(parsed.sheet_names))
        if parsed.notes:
            st.markdown("**Notes in the workbook:**")
            for note in parsed.notes:
                st.markdown(f"- {note}")
        st.markdown("**Checks on this file:**")
        for check in parsed.checks:
            st.markdown(f"- {check.message}")

    return parsed, org, figures, file_origin


# ---------------------------------------------------------------- tab 4: AI assistant

def md_escape(text: str) -> str:
    """Show workbook text literally in Markdown."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~])", r"\\\1", text)


def reset_chat() -> None:
    st.session_state["ai_explanation"] = None
    st.session_state["ai_history"] = []


def ask_groq(api_key: str, model: str, messages: list[dict[str, str]]) -> Optional[str]:
    """Call Groq. Shows a friendly error and returns None on failure."""
    try:
        with st.spinner("Asking Groq…"):
            return ai.complete(ai.make_client(api_key), model, messages)
    except ai.AIError as exc:
        st.error(str(exc))
        return None


def tab_ai(selection: Optional[tuple], data: Optional[dict[str, Any]]) -> None:
    provenance("ai")
    st.header("AI assistant")
    st.write(
        "Get a plain-English explanation of the waiting-list figures, then ask follow-up questions. "
        "Answers use only the NHS figures and sourced guidance in this app."
    )
    st.info(
        "When you use this tab, the public NHS figures for the selected provider, the sourced "
        "guidance and the questions you type are sent to **Groq**, an external AI service. "
        "Nothing from *My child's next steps* is sent.\n\n"
        "Please don't type your child's name, date of birth, NHS number or anything else that "
        "could identify your family."
    )

    api_key = str(secret("GROQ_API_KEY", "") or "").strip()
    model = str(secret("GROQ_MODEL", "") or "").strip() or ai.DEFAULT_MODEL
    if not api_key:
        st.warning(
            "The AI assistant isn't set up yet. The other tabs work without it.\n\n"
            "To turn it on, open `.streamlit/secrets.toml`, paste your Groq API key between the "
            "quotes after `GROQ_API_KEY =`, save the file and restart the app."
        )
        return
    if data is None:
        st.warning("The guidance file couldn't be loaded, so the assistant is unavailable.")
        return
    if selection is None:
        st.write("Load a valid NHS workbook on the **Waiting-list picture** tab first.")
        return

    parsed, org, figures, file_origin = selection
    try:
        context = ai.build_context(parsed, org, figures, data, file_origin)
    except ai.AIError as exc:
        st.error(str(exc))
        return

    new_id = ai.context_id(context)
    if st.session_state.get("ai_context_id") != new_id:
        had_chat = bool(st.session_state.get("ai_explanation") or st.session_state.get("ai_history"))
        st.session_state["ai_context_id"] = new_id
        reset_chat()
        if had_chat:
            st.info("New context: the provider or dataset changed, so the chat has restarted.")

    st.markdown("**Context for this conversation**")
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"Provider  \n**{md_escape(context['provider']['name'])}**")
    c2.markdown(f"Service  \n**{md_escape(context['service'])}**")
    c3.markdown(f"Reporting month  \n**{md_escape(context['dataset']['reporting_month'])}**")
    st.caption("To change the provider, use the Waiting-list picture tab.")

    with st.expander("What is sent to Groq"):
        st.caption(
            "This is the information the assistant receives, along with your questions. "
            "All figures were calculated in Python."
        )
        st.json(context, expanded=False)

    if st.button("Generate explanation", type="primary", icon=":material/auto_awesome:"):
        answer = ask_groq(api_key, model, ai.explanation_messages(context))
        if answer:
            st.session_state["ai_explanation"] = answer

    explanation = st.session_state.get("ai_explanation")
    if explanation:
        with st.container(border=True):
            st.markdown(f"**Explanation: {md_escape(context['provider']['name'])}, "
                        f"{md_escape(context['dataset']['reporting_month'])}**")
            st.markdown(explanation)
            st.caption(
                "AI-generated from the figures and guidance shown in this app. It may contain "
                "mistakes, so check important points with the service."
            )

    st.subheader("Ask a follow-up question")
    history: list[dict[str, str]] = st.session_state.get("ai_history", [])
    for message in history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    asked = len(history) // 2
    if asked >= ai.MAX_FOLLOW_UPS:
        st.info(f"You've asked {ai.MAX_FOLLOW_UPS} questions in this chat. Start a new chat to ask more.")
    else:
        question = st.chat_input(
            "Ask about these figures or the assessment pathway",
            max_chars=ai.MAX_QUESTION_CHARS,
            key="ai_chat_input",
        )
        if question:
            try:
                messages = ai.chat_messages(context, explanation, history, question)
            except ai.AIError as exc:
                st.error(str(exc))
            else:
                answer = ask_groq(api_key, model, messages)
                if answer:
                    history.extend(
                        [{"role": "user", "content": question.strip()},
                         {"role": "assistant", "content": answer}]
                    )
                    st.session_state["ai_history"] = history
                    st.rerun()
        st.caption(
            f"Questions can be up to {ai.MAX_QUESTION_CHARS} characters. "
            f"{ai.MAX_FOLLOW_UPS - asked} of {ai.MAX_FOLLOW_UPS} questions left in this chat."
        )

    if explanation or history:
        if st.button("Start a new chat", icon=":material/restart_alt:"):
            reset_chat()
            st.rerun()


# ---------------------------------------------------------------- main


def main() -> None:
    require_password()  # nothing below runs until the password is correct

    st.markdown(CSS, unsafe_allow_html=True)
    st.title("Assessment Navigator")
    st.write(
        "Helping parents understand community paediatric waiting lists and their "
        "child's neurodevelopmental assessment."
    )

    try:
        data = guidance_mod.load_guidance()
    except guidance_mod.GuidanceError as exc:
        data = None
        guidance_problem = str(exc)

    my_child, pathway, waiting, assistant = st.tabs(
        ["My child's next steps", "Assessment pathway", "Waiting-list picture", "AI assistant"]
    )
    with my_child:
        if data is None:
            st.error(guidance_problem)
        else:
            tab_my_child(data)
    with pathway:
        if data is None:
            st.error(guidance_problem)
        else:
            tab_pathway(data)
    with waiting:
        selection = tab_waiting_list()
    with assistant:
        tab_ai(selection, data)


main()
