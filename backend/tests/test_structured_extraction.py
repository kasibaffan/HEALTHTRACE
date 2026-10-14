"""Rule-based date / lab-result extraction: spans point at the source text, ambiguity is preserved, API is org-scoped."""
from app.services.structured_extraction import extract_dates, extract_fields, extract_lab_results

TEXT = "Collected 12 March 2025, 2025-04-01 and 03/04/2025.\nHbA1c 58 mmol/mol H\nSodium: 139 mmol/L\nHaemoglobin result 11.2 g/dL (L)\nplatelets were 250 x10^9/L"


def test_dates_have_exact_spans_and_ambiguous_dates_are_not_guessed():
    d = extract_dates([TEXT])
    assert [(x["text"], x["isoDate"], x["ambiguous"]) for x in d] == [("12 March 2025", "2025-03-12", False), ("2025-04-01", "2025-04-01", False), ("03/04/2025", None, True)]
    assert all(TEXT[x["start"]:x["end"]] == x["text"] for x in d)


def test_invalid_calendar_dates_are_left_unparsed():
    assert extract_dates(["Seen 31 February 2025."])[0]["isoDate"] is None


def test_lab_results_have_names_values_units_flags_and_exact_spans():
    labs = extract_lab_results([TEXT])
    assert [(x["testName"], x["value"], x["unit"], x["flag"]) for x in labs] == [
        ("HbA1c", 58.0, "mmol/mol", "h"), ("Sodium", 139.0, "mmol/L", None), ("Haemoglobin", 11.2, "g/dL", "l"), ("platelets", 250.0, "x10^9/L", None)]
    assert all(TEXT[x["start"]:x["end"]] == x["text"] for x in labs)


def test_page_numbers_and_no_false_positives():
    f = extract_fields(["nothing here", "Sodium 140 mmol/L"])
    assert f["labResults"][0]["page"] == 2 and f["dates"] == [] and f["method"] == "rule-based"
    assert extract_fields([""])["labResults"] == [] and extract_fields([])["dates"] == []


def test_endpoint_is_org_scoped_and_read_only(workspace, register):
    ws = workspace
    r = ws.analyst.post(f"/api/cases/{ws.case['id']}/documents", files={"file": ("Lab.txt", b"Blood drawn 12 March 2025. Sodium: 139 mmol/L. HbA1c 58 mmol/mol H.", "text/plain")})
    did = r.json()["id"]
    body = ws.viewer.get(f"/api/documents/{did}/structured-fields").json()
    assert body["documentId"] == did and body["dates"][0]["isoDate"] == "2025-03-12" and {x["testName"] for x in body["labResults"]} == {"Sodium", "HbA1c"}
    assert "not a machine-learning" in body["notice"]
    outsider = register("eve@other.test", "Org B", "Eve")
    assert outsider.get(f"/api/documents/{did}/structured-fields").status_code == 404
