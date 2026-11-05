"""Downloadable views of the current event signup and placement rows."""

import csv
import io
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

import reportlab
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

HEADERS = ("Table", "Status", "Position", "Player", "Discord username", "Discord ID")
SUMMARY_HEADERS = ("Event ID", "Event", "Starts at (UTC)", "Event status", *HEADERS)


def safe_cell(value: Any) -> str:
    """Keep spreadsheet programs from interpreting user supplied text as formulas."""
    cell = str(value)
    return "'" + cell if cell.lstrip().startswith(("=", "+", "-", "@")) else cell


def signup_rows(rows: list[dict[str, Any]]) -> list[tuple[str, ...]]:
    result: list[tuple[str, ...]] = []
    for table in rows:
        for status, key in (("Seated", "players"), ("Waitlisted", "waitlist")):
            for position, player in enumerate(table.get(key, []), 1):
                result.append(
                    (
                        str(table["name"]),
                        status,
                        str(position),
                        str(player.get("display_name") or player["name"]),
                        str(player["name"]),
                        str(player["id"]),
                    )
                )
    return result


def csv_bytes(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(safe_cell(value) for value in row)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def event_csv(rows: list[dict[str, Any]]) -> bytes:
    return csv_bytes(HEADERS, signup_rows(rows))


def summary_csv(events: list[tuple[Any, list[dict[str, Any]]]]) -> bytes:
    result: list[tuple[str, ...]] = []
    for event, tables in events:
        prefix = (
            str(event.id),
            str(event.title),
            datetime.fromtimestamp(event.starts_at, UTC).isoformat(),
            event.status,
        )
        players = signup_rows(tables)
        if players:
            result.extend(prefix + row for row in players)
        else:
            result.append(prefix + ("", "", "", "", "", ""))
    return csv_bytes(SUMMARY_HEADERS, result)


def event_pdf(event: Any, rows: list[dict[str, Any]]) -> bytes:
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=(8.5 * inch, 11 * inch),
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
        title=f"{event.title} signups",
    )
    styles = getSampleStyleSheet()
    fonts = Path(reportlab.__file__).parent / "fonts"
    pdfmetrics.registerFont(TTFont("SignupVera", str(fonts / "Vera.ttf")))
    pdfmetrics.registerFont(TTFont("SignupVeraBold", str(fonts / "VeraBd.ttf")))
    styles["Normal"].fontName = "SignupVera"
    styles["Title"].fontName = "SignupVeraBold"
    styles["Heading2"].fontName = "SignupVeraBold"
    starts_at = datetime.fromtimestamp(event.starts_at, UTC)
    story: list[Any] = [
        Paragraph(escape(event.title), styles["Title"]),
        Paragraph(
            f"{starts_at.strftime('%B %d, %Y %H:%M')} UTC"
            f" · {escape(event.status.title())}",
            styles["Normal"],
        ),
        Spacer(1, 0.25 * inch),
    ]
    for table in rows:
        seated = table.get("players", [])
        waiting = table.get("waitlist", [])
        capacity = next(
            (
                item["capacity"]
                for item in event.tables
                if item["name"] == table["name"]
            ),
            None,
        )
        count = f"{len(seated)} / {capacity}" if capacity else str(len(seated))
        heading = Paragraph(f"{escape(table['name'])} ({count})", styles["Heading2"])
        values: list[list[Any]] = [["#", "Seated players"]]
        values.extend(
            [
                str(i),
                Paragraph(
                    escape(player.get("display_name") or player["name"]),
                    styles["Normal"],
                ),
            ]
            for i, player in enumerate(seated, 1)
        )
        if waiting:
            values.append(["", "Waitlisted"])
            values.extend(
                [
                    str(i),
                    Paragraph(
                        escape(player.get("display_name") or player["name"]),
                        styles["Normal"],
                    ),
                ]
                for i, player in enumerate(waiting, 1)
            )
        if len(values) == 1:
            values.append(["", "No signups"])
        listing = Table(
            values, colWidths=[0.45 * inch, 6.6 * inch], repeatRows=1, hAlign="LEFT"
        )
        listing.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf2")),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#aab7c4")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.extend([heading, listing, Spacer(1, 0.2 * inch)])
    document.build(story)
    return output.getvalue()
