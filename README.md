# Nova Poshta Scanner

A desktop app for processing Nova Poshta shipments. You provide a text file with TTN numbers, the app validates each one against the Nova Poshta API, groups them by sender and warehouse, and creates scan sheet registries in bulk.

Built with Python, CustomTkinter, and PyInstaller.


## What it does

- Reads a plain text file with TTN numbers, one per line. Empty lines or a dash split the list into batches (portions).
- Validates each TTN via the Nova Poshta API: checks if it exists in your account, is not already assigned to a registry, and has all expected sub-TTNs present (for multi-seat shipments).
- Warns about duplicates, missing sub-TTNs, and TTNs already in a registry.
- Groups valid TTNs by sender and warehouse into suggested registries.
- Creates or updates scan sheet registries via the API in one click.
- Supports incremental re-analysis: if you add TTNs to the file, only new ones are processed.


## File format

One TTN per line. Separate batches with an empty line or a single dash:

```
20400512031414
20400512031415
20400512031416

20400512031417
20400512031418
```

Sub-TTNs (18-digit numbers whose first 14 digits match a parent TTN in the file) are detected automatically and do not appear as separate rows.


## Requirements

- Python 3.10 or later
- Nova Poshta API key (personal account)


## Setup

```
pip install -r requirements.txt
```

Add your API key and the path to your TTN file in the settings dialog inside the app. The config is saved to `config.json` next to the executable.


## Running

```
python app.py
```


## Building the executable

```
pyinstaller TTNScanner.spec
```

Output goes to `dist/TTNScanner/`.


## Running tests

```
python -m pytest tests/ -v
```

All tests mock the GUI and API layer, so no display or network connection is required.


## Project structure

- `app.py` - main window and all UI logic
- `scanner.py` - business logic: file parsing, TTN validation, grouping, registry distribution
- `api.py` - thin Nova Poshta API v2 client
- `widgets.py` - reusable UI components (TTNRow, RegistryCard, PrintedModal)
- `tests/` - pytest test suite
