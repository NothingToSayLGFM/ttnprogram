import requests

API_URL = "https://api.novaposhta.ua/v2.0/json/"


def call(api_key: str, model: str, method: str, properties: dict = None) -> dict:
    payload = {
        "apiKey": api_key,
        "modelName": model,
        "calledMethod": method,
        "methodProperties": properties or {},
    }
    r = requests.post(API_URL, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def get_document_info(api_key: str, ttn: str) -> dict | None:
    """Returns full document data for a TTN, or None if not found."""
    # No date filter: drafts have no dispatch date and are excluded by DateTimeFrom/DateTimeTo
    data = call(api_key, "InternetDocument", "getDocumentList", {
        "IntDocNumber": ttn,
        "GetFullList":  "1",
    })
    if data.get("success") and data.get("data"):
        return data["data"][0]
    return None


def get_scan_sheet_list(api_key: str) -> list:
    """Returns list of all scan sheets."""
    data = call(api_key, "ScanSheetGeneral", "getScanSheetList", {})
    if data.get("success"):
        return data.get("data", [])
    return []


def get_printed_documents(api_key: str, date_str: str) -> list:
    """Returns documents for the given date (DD.MM.YYYY) where Printed='1'."""
    data = call(api_key, "InternetDocument", "getDocumentList", {
        "DateTimeFrom": date_str,
        "DateTimeTo":   date_str,
        "GetFullList":  "1",
    })
    docs = data.get("data", []) if data.get("success") else []
    return [d for d in docs if str(d.get("Printed", "0")) == "1"]


def insert_documents(api_key: str, doc_refs: list[str],
                     scan_sheet_ref: str = "", description: str = "") -> dict:
    """
    Adds documents to a scan sheet.
    - scan_sheet_ref=""  + description="NAME" → creates NEW scan sheet with that name
    - scan_sheet_ref=existing_ref             → adds to existing sheet
    Returns raw API response.
    """
    props = {"Ref": scan_sheet_ref, "DocumentRefs": doc_refs}
    if description:
        props["Description"] = description
    return call(api_key, "ScanSheetGeneral", "insertDocuments", props)
