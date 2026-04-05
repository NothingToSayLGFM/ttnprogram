import re
from datetime import date
from pathlib import Path

import api as np_api

SEATS_FIELD = 'SeatsAmount'  # verify field name from real API response


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def expected_sub_ttns(ttn: str, seats: int) -> list[str]:
    """Returns list of sub-TTN strings for a multi-seat shipment."""
    return [f"{ttn}{i:04d}" for i in range(1, seats)]


def read_chunks(input_file: str) -> list[list[str]]:
    """Reads TTNs from file, splitting into chunks on empty lines or '-'."""
    raw = Path(input_file).read_text(encoding="utf-8").splitlines()
    chunks: list[list[str]] = []
    current: list[str] = []
    for line in raw:
        stripped = line.strip()
        if not stripped or stripped == '-':
            if current:
                chunks.append(current)
                current = []
        else:
            ttn = normalize(stripped)
            if ttn:
                current.append(ttn)
    if current:
        chunks.append(current)
    return chunks if chunks else [[]]


def validate_ttn(api_key: str, ttn: str) -> tuple[str, dict | None]:
    """
    Returns:
      ('not_found', None)           — TTN не знайдено в особистому кабінеті
      ('already_in_registry', doc)  — TTN вже в реєстрі (ScanSheetNumber не порожній)
      ('ok', doc)                   — TTN знайдена і вільна
    """
    doc = np_api.get_document_info(api_key, ttn)
    if not doc:
        return ('not_found', None)
    if doc.get('ScanSheetNumber', '').strip():
        return ('already_in_registry', doc)
    return ('ok', doc)


def classify_file_change(old: list[list[str]], fresh: list[list[str]]) -> str:
    """
    Compares old and fresh chunk lists and returns change type:
      'unchanged'    — identical
      'append_only'  — new chunks appended, existing unchanged
      'chunk_append' — TTNs appended to existing chunks, no removals
      'full_reset'   — anything else (TTNs removed or reordered)
    """
    if fresh == old:
        return 'unchanged'
    old_n, new_n = len(old), len(fresh)
    if new_n > old_n and fresh[:old_n] == old:
        return 'append_only'
    if (new_n == old_n
            and all(fresh[i][:len(old[i])] == old[i] for i in range(old_n))):
        return 'chunk_append'
    return 'full_reset'


def compute_canonical(ok_indices: dict[str, list[int]]) -> tuple[dict[str, int], dict[str, list[int]]]:
    """
    Given ok_indices mapping ttn -> [abs_idx, ...] (all 'ok' occurrences),
    returns:
      canonical      — ttn -> last abs_idx (the one that will be distributed)
      duplicate_idxs — ttn -> [earlier abs_idxs to mark as duplicate]
    """
    canonical: dict[str, int] = {}
    duplicate_idxs: dict[str, list[int]] = {}
    for ttn, idxs in ok_indices.items():
        canonical[ttn] = idxs[-1]
        dupes = idxs[:-1]
        if dupes:
            duplicate_idxs[ttn] = dupes
    return canonical, duplicate_idxs


def _sender_key(doc: dict) -> tuple:
    sender_ref = doc.get('Sender', '')
    warehouse_ref = (
        doc.get('SettlmentAddressData', {}).get('SenderWarehouseRef', '')
        or doc.get('SenderAddress', '')
    )
    return (sender_ref, warehouse_ref)


def _registry_name(doc: dict) -> str:
    sender = doc.get('SenderDescription', '').strip()
    short_name = sender.split()[0] if sender else 'Unknown'
    today = date.today().strftime('%Y.%d.%m')
    warehouse_num = doc.get('SettlmentAddressData', {}).get('SenderWarehouseNumber', '?')
    return f"{short_name}_{today}_ВД{warehouse_num}"


def group_ttns(ttn_doc_pairs: list[tuple[str, dict]]) -> dict:
    """
    Групує ТТН по (відправник, склад).
    key -> {ttns, doc_refs, suggested_name, sender_description, warehouse_description, scan_sheet_ref}
    """
    groups: dict = {}
    for ttn, doc in ttn_doc_pairs:
        key = _sender_key(doc)
        if key not in groups:
            groups[key] = {
                'ttns': [],
                'doc_refs': [],
                'suggested_name': _registry_name(doc),
                'sender_description': doc.get('SenderDescription', ''),
                'warehouse_description': doc.get('SenderAddressDescription', ''),
            }
        groups[key]['ttns'].append(ttn)
        groups[key]['doc_refs'].append(doc.get('Ref', ''))
    return groups


def _get_existing_sheet_ref(sheets: list, name: str) -> str:
    """Returns Ref of existing scan sheet with given name, or '' if not found."""
    for s in sheets:
        if s.get('Description', '').strip() == name:
            return s.get('Ref', '')
    return ''


def get_sheet_name_by_number(api_key: str, sheet_number: str) -> str:
    """Returns Description of scan sheet by its Number, or sheet_number if not found."""
    if not sheet_number:
        return sheet_number
    sheets = np_api.get_scan_sheet_list(api_key)
    for s in sheets:
        if s.get('Number', '') == sheet_number:
            return s.get('Description', '') or sheet_number
    return sheet_number


def distribute(api_key: str, groups: dict, log) -> dict:
    """
    Для кожної групи знаходить існуючий реєстр або створює новий, і додає ТТН.
    Повертає dict: group_key -> list of (ttn, status, message)
    """
    results = {}
    sheets = np_api.get_scan_sheet_list(api_key)
    for key, group in groups.items():
        name = group['suggested_name']

        existing_ref = _get_existing_sheet_ref(sheets, name)
        if existing_ref:
            log(f"  Реєстр '{name}' вже існує — додаю {len(group['doc_refs'])} ТТН до нього...")
        else:
            log(f"  Створюю реєстр '{name}' і додаю {len(group['doc_refs'])} ТТН...")

        try:
            result = np_api.insert_documents(
                api_key,
                doc_refs=group['doc_refs'],
                scan_sheet_ref=existing_ref,
                description=name if not existing_ref else "",
            )
        except Exception as e:
            log(f"  ПОМИЛКА запиту: {e}")
            results[key] = [(ttn, 'error', str(e)) for ttn in group['ttns']]
            continue

        if not result.get('success'):
            errors = result.get('errors', [])
            msg = '; '.join(errors) if errors else 'Невідома помилка'
            log(f"  ПОМИЛКА: {msg}")
            results[key] = [(ttn, 'error', msg) for ttn in group['ttns']]
            continue

        # Парсимо результат по кожній ТТН
        sheet_data = result.get('data', [{}])[0]
        sheet_number = sheet_data.get('Number', '')
        log(f"  Реєстр {sheet_number} створено!")

        success_set  = {normalize(str(d.get('Number', ''))) for d in sheet_data.get('Success', [])}
        warning_map  = {normalize(str(d.get('Number', ''))): d.get('ScanSheetNumber', '')
                        for d in sheet_data.get('Warnings', [])}
        error_set    = {normalize(str(d.get('Number', ''))) for d in sheet_data.get('Errors', [])}

        group_results = []
        for ttn in group['ttns']:
            if ttn in success_set:
                group_results.append((ttn, 'done', f'Реєстр {sheet_number}'))
            elif ttn in warning_map:
                group_results.append((ttn, 'already', f"Вже в реєстрі {warning_map[ttn]}"))
            elif ttn in error_set:
                group_results.append((ttn, 'error', 'Помилка додавання'))
            else:
                group_results.append((ttn, 'done', f'Реєстр {sheet_number}'))

        results[key] = group_results

    return results
