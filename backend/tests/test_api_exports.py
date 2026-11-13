"""Exports API integration coverage."""

import pytest
from fastapi.testclient import TestClient
from flow_helpers import (
    closing_event,
    closing_message,
    connect_test_organization,
    event_body,
    login,
)


def test_signup_exports_use_saved_placements_and_scope(client):
    import csv
    import io

    headers, event, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    rows = client.get(path + "/signups").json()
    pdf = client.get(path + "/signups.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-")
    assert pdf.headers["content-disposition"].endswith('.pdf"')
    assert (
        client.get(path + "/signups.pdf?timezone=America%2FNew_York").status_code == 200
    )
    assert client.get(path + "/signups.pdf?timezone=Invalid").status_code == 400
    export = client.get(path + "/signups.csv")
    assert export.status_code == 200
    parsed = list(csv.DictReader(io.StringIO(export.content.decode("utf-8-sig"))))
    assert len(parsed) == sum(
        len(row["players"]) + len(row["waitlist"]) for row in rows
    )
    assert {row["Status"] for row in parsed} == {"Seated", "Waitlisted"}
    summary = client.get("/api/exports/signups.csv")
    all_rows = list(csv.DictReader(io.StringIO(summary.content.decode("utf-8-sig"))))
    assert len(all_rows) == len(parsed)
    assert {row["Event ID"] for row in all_rows} == {event["id"]}
    assert client.get("/api/events/missing/signups.csv").status_code == 404
    assert client.get("/api/events/missing/signups.pdf").status_code == 404


def test_public_assignment_link_is_opt_in_scoped_and_live(client):
    headers, event, path, _ = closing_event(client)
    assert client.post(path + "/share", headers=headers).status_code == 409
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    assert client.post(path + "/share").status_code == 403
    shared = client.post(path + "/share", headers=headers)
    assert shared.status_code == 200
    assert client.post(path + "/share", headers=headers).json() == shared.json()
    token = shared.json()["path"].rsplit("/", 1)[1]
    with TestClient(client.app) as public:
        assert public.get(path + "/signups").status_code == 401
        assert public.get("/api/public/events/unknown").status_code == 404
        response = public.get(f"/api/public/events/{token}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        data = response.json()
        assert data["title"] == event["title"]
        assert set(data) == {
            "timezone",
            "title",
            "description",
            "location",
            "starts_at",
            "archived",
            "tables",
        }
        assert all(
            set(player) == {"name"}
            for table in data["tables"]
            for key in ("players", "waitlist")
            for player in table[key]
        )
        rows = client.get(path + "/signups").json()
        removed = rows[0]["players"][0]["id"]
        assert (
            client.delete(
                path + f"/manager-players/{removed}", headers=headers
            ).status_code
            == 200
        )
        current = client.get(path + "/signups").json()
        updated = public.get(f"/api/public/events/{token}").json()
        assert [[p["name"] for p in t["players"]] for t in updated["tables"]] == [
            [p.get("display_name") or p["name"] for p in t["players"]] for t in current
        ]
    client.app.state.discord.identity.return_value = {
        "id": "other",
        "username": "Other",
    }
    other_headers = login(client)
    assert client.post(path + "/share", headers=other_headers).status_code == 404


def test_assigned_exports_reflect_current_roster_and_display_names(client):
    import csv
    import io
    from unittest.mock import patch

    headers, _, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    initial = client.get(path + "/signups").json()
    table = next(row for row in initial if row["waitlist"])
    removed = table["players"][0]["id"]
    promoted = table["waitlist"][0]["id"]
    assert (
        client.delete(path + f"/manager-players/{removed}", headers=headers).status_code
        == 200
    )
    current = client.get(path + "/signups").json()
    assert any(p["id"] == promoted for row in current for p in row["players"])
    assert all(p["id"] != removed for row in current for p in row["players"])
    assert (
        client.put(
            f"/api/players/{promoted}",
            headers=headers,
            json={"real_name": "Current display name"},
        ).status_code
        == 200
    )
    current = client.get(path + "/signups").json()
    csv_response = client.get(path + "/signups.csv")
    assert csv_response.headers["cache-control"] == "no-store"
    csv_rows = list(
        csv.DictReader(io.StringIO(csv_response.content.decode("utf-8-sig")))
    )
    assert any(
        row["Discord ID"] == promoted
        and row["Player"] == "Current display name"
        and row["Status"] == "Seated"
        for row in csv_rows
    )
    assert not any(
        row["Discord ID"] == removed and row["Status"] == "Seated" for row in csv_rows
    )
    with patch("app.routes.signups.event_pdf", return_value=b"%PDF-current") as render:
        pdf_response = client.get(path + "/signups.pdf")
    assert pdf_response.headers["cache-control"] == "no-store"
    assert render.call_args.args[1] == current
    assert client.get("/api/exports/signups.csv").headers["cache-control"] == "no-store"


def test_signup_csv_quotes_spreadsheet_formulas():
    import csv
    import io

    from app.signup_exports import event_csv

    content = event_csv(
        [
            {
                "name": "=TABLE()",
                "players": [{"id": "123", "name": "+discord", "display_name": "@Name"}],
                "waitlist": [],
            }
        ]
    )
    row = next(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    assert row["Table"] == "'=TABLE()"
    assert row["Player"] == "'@Name"
    assert row["Discord username"] == "'+discord"


@pytest.mark.parametrize("table_count", [4, 6])
def test_pdf_fits_full_tables_on_one_portrait_page(table_count):
    import re
    from types import SimpleNamespace

    from app.signup_exports import event_pdf

    tables = [
        {"name": f"Table {index}", "capacity": 15} for index in range(table_count)
    ]
    rows = [
        {
            "name": table["name"],
            "players": [
                {
                    "name": f"player-{table_index}-{number}",
                    "display_name": f"Player {number}",
                }
                for number in range(15)
            ],
            "waitlist": [
                {"name": f"waiting-{table_index}-{number}"} for number in range(5)
            ],
        }
        for table_index, table in enumerate(tables)
    ]
    event = SimpleNamespace(
        title="Monday Tables",
        starts_at=1794265200,
        tables=tables,
        status="assigned",
    )
    pdf = event_pdf(event, rows)
    assert pdf.startswith(b"%PDF-")
    assert len(re.findall(rb"/Type\s*/Page\b", pdf)) == 1
    assert b"/MediaBox [ 0 0 612 792 ]" in pdf


def test_summary_export_respects_selected_organization(client):
    import csv
    import io

    headers, personal, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    organization = client.post(
        "/api/organizations", headers=headers, json={"name": "Export Scope"}
    ).json()
    connect_test_organization(client, organization["id"])
    assert (
        client.put(
            "/api/organizations/selection",
            headers=headers,
            json={"organization_id": organization["id"]},
        ).status_code
        == 200
    )
    shared = client.post("/api/events", headers=headers, json=event_body()).json()
    response = client.get("/api/exports/signups.csv")
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(rows) == 1
    assert rows[0]["Event ID"] == shared["id"]
    assert rows[0]["Player"] == ""
    assert client.get(f"/api/events/{personal['id']}/signups.pdf").status_code == 404
    assert client.get(f"/api/events/{personal['id']}/signups.csv").status_code == 404
