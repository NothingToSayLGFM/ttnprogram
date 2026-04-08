import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_URL = "https://api.novaposhta.ua/v2.0/json/"
MAX_RETRIES = 5


class NPConnectionError(Exception):
    """Raised when all retry attempts to the Nova Poshta API have failed."""
    pass


def _make_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=Retry(total=0))
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_session = _make_session()


def call(api_key: str, model: str, method: str, properties: dict = None) -> dict:
    payload = {
        "apiKey": api_key,
        "modelName": model,
        "calledMethod": method,
        "methodProperties": properties or {},
    }
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            r = _session.post(API_URL, json=payload, timeout=30)
            r.raise_for_status()
            return r.json()
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)  # 1, 2, 4, 8 s between attempts
    raise NPConnectionError(
        f"Усі {MAX_RETRIES} спроби з'єднатися з Новою Поштою провалились"
    ) from last_err


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
