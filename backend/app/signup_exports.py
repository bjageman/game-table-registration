"""Downloadable views of the current event signup and placement rows."""

import csv
import io
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import reportlab
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.graphics.shapes import Path as CheckPath
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
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


def event_pdf(
    event: Any, rows: list[dict[str, Any]], time_zone: ZoneInfo | None = None
) -> bytes:
    output = io.BytesIO()
    page_width = 8.5 * inch
    page_height = 11 * inch
    margin = 0.36 * inch
    document = SimpleDocTemplate(
        output,
        pagesize=(page_width, page_height),
        leftMargin=margin,
        rightMargin=margin,
        topMargin=0.72 * inch,
        bottomMargin=margin,
        title=f"{event.title} signups",
    )
    fonts = Path(reportlab.__file__).parent / "fonts"
    pdfmetrics.registerFont(TTFont("SignupVera", str(fonts / "Vera.ttf")))
    pdfmetrics.registerFont(TTFont("SignupVeraBold", str(fonts / "VeraBd.ttf")))
    expanded = len(rows) <= 4 and all(
        len(table.get("players", [])) + len(table.get("waitlist", [])) <= 20
        for table in rows
    )
    font_size = 10.5 if expanded else 8
    leading = 12 if expanded else 9
    row_padding = 1.35 if expanded else 0.25
    name_style = ParagraphStyle(
        "SignupName",
        fontName="SignupVera",
        fontSize=font_size,
        leading=leading,
    )
    header_style = ParagraphStyle(
        "SignupHeader",
        fontName="SignupVeraBold",
        fontSize=font_size,
        leading=leading,
    )
    title_style = ParagraphStyle(
        "SignupTableTitle",
        fontName="SignupVeraBold",
        fontSize=11 if expanded else 9,
        leading=13 if expanded else 11,
    )
    card_width = (page_width - 2 * margin) / 2 - 8
    cards: list[list[Any]] = []

    def check_icon() -> Drawing:
        icon = Drawing(9, 9)
        square = Rect(0, 0, 9, 9, rx=2, ry=2)
        square.fillColor = colors.HexColor("#238b45")
        square.strokeColor = None
        icon.add(square)
        mark = CheckPath(fillColor=None, strokeColor=colors.white, strokeWidth=1.6)
        mark.moveTo(1.8, 4.4)
        mark.lineTo(3.8, 2.3)
        mark.lineTo(7.4, 6.8)
        icon.add(mark)
        return icon

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
        players = [("Seated", player) for player in seated] + [
            ("Waitlisted", player) for player in waiting
        ]
        heading = Paragraph(
            f"{escape(table['name'])} ({count})",
            title_style,
        )
        values: list[list[Any]] = [
            [
                check_icon(),
                Paragraph("Display Name", header_style),
                Paragraph("Username", header_style),
            ]
        ]
        sections: list[int] = []
        last_status = ""
        for status, player in players:
            if status == "Waitlisted" and status != last_status:
                sections.append(len(values))
                values.append(
                    [
                        Paragraph(status, header_style),
                        Spacer(0, 0),
                        Spacer(0, 0),
                    ]
                )
                last_status = status
            values.append(
                [
                    Spacer(0, 0),
                    Paragraph(escape(player.get("display_name") or ""), name_style),
                    Paragraph(escape(player["name"]), name_style),
                ]
            )
        if not players:
            values.append(
                [
                    Spacer(0, 0),
                    Paragraph("No signups", name_style),
                    Spacer(0, 0),
                ]
            )
        listing = Table(
            values,
            colWidths=[17, card_width - 121, 104],
            hAlign="LEFT",
        )
        styling: list[tuple[Any, ...]] = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf2")),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b8c2cb")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), row_padding),
            ("BOTTOMPADDING", (0, 0), (-1, -1), row_padding),
            ("LEFTPADDING", (0, 0), (-1, -1), 1.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1.5),
        ]
        for section in sections:
            styling.extend(
                [
                    ("SPAN", (0, section), (-1, section)),
                    (
                        "BACKGROUND",
                        (0, section),
                        (-1, section),
                        colors.HexColor("#f3f5f7"),
                    ),
                ]
            )
        listing.setStyle(TableStyle(styling))
        cards.append([heading, listing])

    def page_header(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        title_size = 13.0
        while (
            title_size > 8
            and pdfmetrics.stringWidth(event.title, "SignupVeraBold", title_size)
            > page_width - 2 * margin
        ):
            title_size -= 0.5
        canvas.setFont("SignupVeraBold", title_size)
        canvas.drawCentredString(page_width / 2, page_height - 0.31 * inch, event.title)
        canvas.setFont("SignupVera", 8.5)
        zone = time_zone or ZoneInfo("UTC")
        date = datetime.fromtimestamp(event.starts_at, zone).strftime(
            "%B %d, %Y at %I:%M %p %Z"
        )
        signup_count = sum(
            len(row.get("players", [])) + len(row.get("waitlist", [])) for row in rows
        )
        canvas.drawCentredString(
            page_width / 2,
            page_height - 0.47 * inch,
            f"{date}  ·  {len(rows)} tables  ·  "
            f"{signup_count} signups (including waitlist)",
        )
        canvas.setFont("SignupVera", 7)
        canvas.drawRightString(page_width - margin, 0.22 * inch, str(doc.page))
        canvas.restoreState()

    story: list[Any] = []
    for start in range(0, len(cards), 6):
        group = cards[start : start + 6]
        grid_rows: list[list[Any]] = [group[i : i + 2] for i in range(0, len(group), 2)]
        for grid_row in grid_rows:
            if len(grid_row) == 1:
                grid_row.append("")
        grid = Table(
            grid_rows,
            colWidths=[(page_width - 2 * margin) / 2] * 2,
            hAlign="LEFT",
            splitByRow=1,
        )
        grid.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        if story:
            story.append(PageBreak())
        story.append(grid)
    if not story:
        story.append(Paragraph("No tables", name_style))
    document.build(story, onFirstPage=page_header, onLaterPages=page_header)
    return output.getvalue()
