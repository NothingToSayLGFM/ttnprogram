import json
import queue
import threading
import time
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

import api as np_api
import scanner as sc
import desktop_client as dc
from widgets import (
    C_GREEN, C_ORANGE, C_RED, C_GRAY, C_BLUE,
    TTNRow, RegistryCard, PrintedModal,
)

import sys
BASE_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


# ── Головне вікно ─────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("TTNFlow Scanner")
        self.geometry("1020x720")
        self.minsize(800, 520)

        cfg = self._load_config()
        self.api_key    = ctk.StringVar(value=cfg.get("api_key", ""))
        self.input_file = ctk.StringVar(value=cfg.get("input_file", ""))

        self.event_queue: queue.Queue = queue.Queue()

        self.ttn_rows: dict[int, TTNRow] = {}    # abs_index -> TTNRow
        self.ttn_indices: dict[str, list[int]] = {}  # ttn -> [abs_index, ...]
        self.groups:     dict = {}      # groups від останньої порції
        self.all_groups: dict = {}      # накопичені groups з усіх порцій

        self.all_chunks: list[list[str]] = []   # порції з файлу
        self.all_ttns:   list[str] = []          # плоский список для індексації
        self.selected_chunk_var = tk.IntVar(value=0)
        self.done_reg_rows: int = 0
        self._next_ttn_grid_row: int = 0         # наступний grid row у ttn_list
        self._stop_analysis = threading.Event()
        self.all_reg_cards: dict = {}  # name -> RegistryCard, зберігається між порціями
        self._canonical_indices: dict[str, int] = {}  # ttn -> canonical abs_idx (last 'ok')
        self._parent_sub_map: dict[str, list[str]] = {}  # parent ttn -> [sub_ttns]
        self._analyze_all_mode = False
        self._current_session_id: str | None = None
        self._ttn_statuses: dict[str, tuple[str, str]] = {}  # ttn -> (status, message)

        self._build_ui()
        self.after(80, self._poll_events)

    # ── UI ────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)  # панелі розтягуються

        # ── Рядок кнопок: ліва — Аналізувати, права — Аналізувати все + іконки ──
        self.analyze_btn = ctk.CTkButton(
            self, text="Аналізувати", height=36,
            fg_color=C_BLUE, hover_color="#2471a3",
            command=self._analyze
        )
        self.analyze_btn.grid(row=0, column=0, sticky="ew", padx=(16, 8), pady=(10, 0))

        right_btn_row = ctk.CTkFrame(self, fg_color="transparent")
        right_btn_row.grid(row=0, column=1, sticky="ew", padx=(8, 16), pady=(10, 0))
        right_btn_row.grid_columnconfigure(0, weight=1)

        self.analyze_all_btn = ctk.CTkButton(
            right_btn_row, text="Аналізувати все", height=36,
            fg_color="#1a7a3c", hover_color="#145e2e",
            command=self._analyze_all
        )
        self.analyze_all_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            right_btn_row, text="🖨", width=36, height=36,
            fg_color="#444444", hover_color="#555555",
            font=ctk.CTkFont(size=16),
            command=self._open_printed_modal
        ).grid(row=0, column=1, padx=(0, 4))

        ctk.CTkButton(
            right_btn_row, text="⚙", width=36, height=36,
            fg_color="#444444", hover_color="#555555",
            font=ctk.CTkFont(size=16),
            command=self._open_settings
        ).grid(row=0, column=2)


        # ── Ліва панель: список ТТН ──
        left = ctk.CTkFrame(self, fg_color="transparent")
        left.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=10)
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)

        self.ttn_list = ctk.CTkScrollableFrame(left, label_text="ТТН")
        self.ttn_list.grid(row=0, column=0, sticky="nsew")
        self.ttn_list.grid_columnconfigure(0, weight=1)

        # ── Права панель: реєстри ──
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=10)
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self.reg_list = ctk.CTkScrollableFrame(right, label_text="Реєстри для створення")
        self.reg_list.grid(row=0, column=0, sticky="nsew")
        self.reg_list.grid_columnconfigure(0, weight=1)

        # ── Кнопка авторозподілу (на всю ширину внизу) ──
        self.distribute_btn = ctk.CTkButton(
            self, text="Авторозподіл", height=38,
            fg_color=C_GREEN, hover_color="#1e8449",
            state="disabled", command=self._distribute
        )
        self.distribute_btn.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 4))

        # Статус
        self.status_bar = ctk.CTkLabel(
            self, text="", anchor="w",
            font=ctk.CTkFont(family="Consolas", size=11), text_color=C_GRAY
        )
        self.status_bar.grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 8))

    def _open_printed_modal(self):
        api_key = self.api_key.get().strip()
        if not api_key:
            self._status("Вкажіть API ключ."); return
        PrintedModal(self, api_key)

    # ── Налаштування ──────────────────────────────────────

    def _open_settings(self):
        popup = ctk.CTkToplevel(self)
        popup.title("Налаштування")
        popup.geometry("480x200")
        popup.resizable(False, False)
        popup.grab_set()
        popup.lift()
        popup.focus_force()

        # Локальні копії для редагування
        api_var  = ctk.StringVar(value=self.api_key.get())
        file_var = ctk.StringVar(value=self.input_file.get())

        frm = ctk.CTkFrame(popup, fg_color="transparent")
        frm.pack(fill="both", expand=True, padx=20, pady=16)
        frm.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frm, text="API ключ:", width=80, anchor="w").grid(row=0, column=0, pady=(0, 10))
        ctk.CTkEntry(frm, textvariable=api_var, height=32, show="*").grid(
            row=0, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(0, 10)
        )

        ctk.CTkLabel(frm, text="Файл ТТН:", width=80, anchor="w").grid(row=1, column=0)
        ctk.CTkEntry(frm, textvariable=file_var, height=32).grid(
            row=1, column=1, sticky="ew", padx=(8, 6)
        )

        def _browse_in_popup():
            path = filedialog.askopenfilename(
                filetypes=[("Text files", "*.txt"), ("Всі файли", "*.*")]
            )
            if path:
                file_var.set(path)

        ctk.CTkButton(frm, text="...", width=36, height=32, command=_browse_in_popup).grid(row=1, column=2)

        btn_frm = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frm.pack(pady=(0, 16))

        def _save():
            self.api_key.set(api_var.get())
            self.input_file.set(file_var.get())
            self._save_config()
            popup.grab_release()
            popup.destroy()

        def _cancel():
            popup.grab_release()
            popup.destroy()

        ctk.CTkButton(btn_frm, text="Зберегти", width=110, height=34,
                      fg_color=C_BLUE, hover_color="#2471a3",
                      command=_save).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_frm, text="Відміна", width=110, height=34,
                      fg_color="#555555", hover_color="#444444",
                      command=_cancel).pack(side="left")

        popup.protocol("WM_DELETE_WINDOW", _cancel)

    # ── Аналіз ────────────────────────────────────────────

    def _render_ttn_chunk(self, chunk_n: int, chunk_ttns: list, file_ttn_set: set,
                          abs_idx: int, grid_row: int, with_sep: bool) -> tuple[int, int]:
        if with_sep:
            sep = ctk.CTkFrame(self.ttn_list, height=1, fg_color="#555555")
            sep.grid(row=grid_row, column=0, sticky="ew", pady=(6, 2))
            grid_row += 1

        ctk.CTkRadioButton(
            self.ttn_list,
            text=f"Порція {chunk_n + 1}",
            variable=self.selected_chunk_var,
            value=chunk_n,
            font=ctk.CTkFont(size=11),
            text_color="#aaaaaa",
        ).grid(row=grid_row, column=0, sticky="w", padx=8, pady=(2, 2))
        grid_row += 1

        for ttn in chunk_ttns:
            if len(ttn) == 18 and ttn[:14] in file_ttn_set:
                abs_idx += 1
                continue
            row = TTNRow(self.ttn_list, abs_idx + 1, ttn,
                         on_retry=lambda i=abs_idx, t=ttn: self._retry_single_ttn(i, t))
            row.grid(row=grid_row, column=0, sticky="ew", pady=2)
            self.ttn_rows[abs_idx] = row
            self.ttn_indices.setdefault(ttn, []).append(abs_idx)
            abs_idx  += 1
            grid_row += 1

        return abs_idx, grid_row

    def _analyze_all(self):
        if self._analyze_all_mode:
            # User pressed "Зупинити" — cancel the loop
            self._analyze_all_mode = False
            self.analyze_all_btn.configure(text="Аналізувати все")
            return
        self._analyze_all_mode = True
        self.analyze_all_btn.configure(text="Зупинити")
        self._analyze()

    def _analyze(self):
        api_key    = self.api_key.get().strip()
        input_file = self.input_file.get().strip()

        if not api_key:
            self._status("Вкажіть API ключ."); return
        if not input_file or not Path(input_file).exists():
            self._status("Файл не знайдено."); return

        self._save_config()
        self.analyze_btn.configure(state="disabled")
        self.distribute_btn.configure(state="disabled")
        self._stop_analysis.clear()
        self._start_analyze_after_balance_check(api_key, input_file)

    def _start_analyze_after_balance_check(self, api_key: str, input_file: str):

        # Читаємо файл і порівнюємо з поточним станом UI
        try:
            fresh_chunks = sc.read_chunks(input_file)
        except Exception as e:
            self._status(f"Помилка читання файлу: {e}")
            self.analyze_btn.configure(state="normal")
            return

        old_n     = len(self.all_chunks)
        new_n     = len(fresh_chunks)
        # Set of all TTNs in file — used to detect sub-TTNs (18-digit, parent is 14-digit in file)
        file_ttn_set = set(t for c in fresh_chunks for t in c)

        change = sc.classify_file_change(self.all_chunks, fresh_chunks)
        unchanged    = change == 'unchanged'
        append_only  = change == 'append_only'
        chunk_append = change == 'chunk_append'

        if unchanged:
            # Файл не змінився — просто переаналізовуємо вибрану порцію
            sel         = self.selected_chunk_var.get()
            n_chunks    = old_n
            chunk       = self.all_chunks[sel]
            chunk_start = sum(len(c) for c in self.all_chunks[:sel])
            self._status(f"Аналізую порцію {sel + 1} / {n_chunks}...")

        elif append_only:
            # Старі порції збережені — дорисовуємо тільки нові
            new_chunks = fresh_chunks[old_n:]
            abs_idx    = len(self.all_ttns)
            grid_row   = self._next_ttn_grid_row

            for chunk_n, chunk_ttns in enumerate(new_chunks, start=old_n):
                abs_idx, grid_row = self._render_ttn_chunk(
                    chunk_n, chunk_ttns, file_ttn_set, abs_idx, grid_row, with_sep=True
                )

            self._next_ttn_grid_row = grid_row
            self.all_chunks = fresh_chunks
            self.all_ttns   = [t for c in self.all_chunks for t in c]
            # Авто-перемикаємо на першу нову порцію
            self.selected_chunk_var.set(old_n)
            n_chunks    = new_n
            sel         = old_n
            chunk       = self.all_chunks[sel]
            chunk_start = sum(len(c) for c in self.all_chunks[:sel])
            self._status(f"Додано {new_n - old_n} нових порцій. Аналізую порцію {old_n + 1}/{n_chunks}...")

        elif chunk_append:
            # TTN додані в кінець існуючих порцій — рендеримо тільки нові рядки
            old_chunk_sizes = [len(c) for c in self.all_chunks]
            grid_row        = self._next_ttn_grid_row
            first_changed   = -1

            for i in range(old_n):
                old_len = old_chunk_sizes[i]
                if len(fresh_chunks[i]) <= old_len:
                    continue
                if first_changed == -1:
                    first_changed = i
                abs_start = sum(len(c) for c in self.all_chunks[:i]) + old_len
                for ttn in fresh_chunks[i][old_len:]:
                    if len(ttn) == 18 and ttn[:14] in file_ttn_set:
                        abs_start += 1
                        continue
                    row = TTNRow(self.ttn_list, abs_start + 1, ttn,
                                 on_retry=lambda i=abs_start, t=ttn: self._retry_single_ttn(i, t))
                    row.grid(row=grid_row, column=0, sticky="ew", pady=2)
                    self.ttn_rows[abs_start] = row
                    self.ttn_indices.setdefault(ttn, []).append(abs_start)
                    abs_start += 1
                    grid_row  += 1

            self._next_ttn_grid_row = grid_row
            self.all_chunks = fresh_chunks
            self.all_ttns   = [t for c in self.all_chunks for t in c]

            sel = first_changed if first_changed >= 0 else self.selected_chunk_var.get()
            self.selected_chunk_var.set(sel)
            n_chunks    = new_n
            chunk_start = sum(len(c) for c in fresh_chunks[:sel]) + old_chunk_sizes[sel]
            chunk       = fresh_chunks[sel][old_chunk_sizes[sel]:]
            self._status(f"Аналізую нові ТТН у порції {sel + 1}/{n_chunks}...")

        else:
            # Старі порції змінились — повний скид
            self._clear_ui()
            self.all_chunks = fresh_chunks
            self.all_ttns   = [t for c in self.all_chunks for t in c]
            total    = len(self.all_ttns)
            n_chunks = new_n
            self._status(f"Знайдено {total} ТТН ({n_chunks} порцій). Аналізую...")

            grid_row  = 0
            abs_idx   = 0
            for chunk_n, chunk_ttns in enumerate(self.all_chunks):
                abs_idx, grid_row = self._render_ttn_chunk(
                    chunk_n, chunk_ttns, file_ttn_set, abs_idx, grid_row, with_sep=(chunk_n > 0)
                )

            self._next_ttn_grid_row = grid_row
            sel         = self.selected_chunk_var.get()
            chunk       = self.all_chunks[sel]
            chunk_start = sum(len(c) for c in self.all_chunks[:sel])

        def _worker(ttns=chunk, api_key=api_key, start=chunk_start):
          try:
            ok_pairs: dict[str, tuple[str, dict]] = {}  # ttn -> (ttn, doc), останній перезаписує
            ok_indices: dict[str, list[int]] = {}       # ttn -> [abs_idx, ...] що отримали 'ok'
            parent_sub_map: dict[str, list[str]] = {}   # parent ttn -> [sub_ttns]
            _sheet_name_cache: dict = {}
            _file_ttn_set = set(self.all_ttns)
            scanned_count: int = 0  # actual TTNs validated (for balance deduction)

            def _sheet_label(sheet_number: str) -> str:
                if sheet_number not in _sheet_name_cache:
                    _sheet_name_cache[sheet_number] = sc.get_sheet_name_by_number(api_key, sheet_number)
                return _sheet_name_cache[sheet_number]

            for i, ttn in enumerate(ttns):
                abs_idx = start + i

                # Skip sub-TTNs — they are validated via parent's SeatsAmount check
                if len(ttn) == 18 and ttn[:14] in _file_ttn_set:
                    continue

                self.event_queue.put(("ttn_status", abs_idx, ttn, "processing", ""))

                # Перевіряємо дублікат по всьому файлу
                first_idx = self.ttn_indices.get(ttn, [abs_idx])[0]
                if abs_idx != first_idx:
                    reply = threading.Event()
                    self.event_queue.put(("show_warning", ttn,
                                          f"ТТН {ttn}\nвже зустрічається у файлі.\nУ разі пропуску буде взятий\nостанній знайдений результат.",
                                          reply))
                    reply.wait()
                    if self._stop_analysis.is_set():
                        break
                    # Mark all earlier occurrences as duplicate — current will become canonical
                    for prev_idx in self.ttn_indices.get(ttn, []):
                        if prev_idx < abs_idx:
                            self.event_queue.put(("ttn_status", prev_idx, ttn, "duplicate", "Дублікат"))

                scanned_count += 1
                try:
                    status, doc = sc.validate_ttn(api_key, ttn)
                except np_api.NPConnectionError:
                    self.event_queue.put(("ttn_status", abs_idx, ttn, "error", "Помилка з'єднання"))
                    self.event_queue.put(("np_connection_error",))
                    return
                time.sleep(1.0)

                if status == 'ok':
                    seats = int(doc.get(sc.SEATS_FIELD, 1) or 1)
                    if seats > 1:
                        sub_ttns = sc.expected_sub_ttns(ttn, seats)
                        missing = [s for s in sub_ttns if s not in _file_ttn_set]
                        if missing:
                            self.event_queue.put(("ttn_status", abs_idx, ttn, "error",
                                                  f"Відсутні {len(missing)} з {seats} місць"))
                            reply = threading.Event()
                            preview = missing[:5]
                            extra = len(missing) - len(preview)
                            missing_str = "\n".join(preview)
                            if extra > 0:
                                missing_str += f"\n...і ще {extra}"
                            self.event_queue.put(("show_warning", ttn,
                                                  f"ТТН {ttn}\nочікується {seats} місць.\n"
                                                  f"Відсутні у файлі:\n" + missing_str,
                                                  reply))
                            reply.wait()
                            if self._stop_analysis.is_set():
                                break
                        else:
                            self.event_queue.put(("ttn_status", abs_idx, ttn, "ok",
                                                  doc.get('SenderDescription', '')))
                            ok_pairs[ttn] = (ttn, doc)
                            ok_indices.setdefault(ttn, []).append(abs_idx)
                            parent_sub_map[ttn] = sub_ttns
                    else:
                        self.event_queue.put(("ttn_status", abs_idx, ttn, "ok",
                                              doc.get('SenderDescription', '')))
                        ok_pairs[ttn] = (ttn, doc)
                        ok_indices.setdefault(ttn, []).append(abs_idx)
                elif status == 'already_in_registry':
                    sheet = doc.get('ScanSheetNumber', '') if doc else ''
                    sheet_name = _sheet_label(sheet) if sheet else sheet
                    self.event_queue.put(("ttn_status", abs_idx, ttn, "already",
                                          f"Реєстр {sheet_name}"))
                    reply = threading.Event()
                    self.event_queue.put(("show_warning", ttn,
                                          f"ТТН {ttn}\nвже додана до реєстру\n«{sheet_name}»",
                                          reply))
                    reply.wait()
                    if self._stop_analysis.is_set():
                        break
                else:
                    self.event_queue.put(("ttn_status", abs_idx, ttn, "not_found", ""))
                    reply = threading.Event()
                    self.event_queue.put(("show_warning", ttn,
                                          f"ТТН {ttn}\nвідсутня в чернетках!",
                                          reply))
                    reply.wait()
                    if self._stop_analysis.is_set():
                        break

            # Визначаємо канонічні індекси і помічаємо попередні 'ok' як дублікати
            canonical, dup_idxs = sc.compute_canonical(ok_indices)
            for ttn, idxs in dup_idxs.items():
                for idx in idxs:
                    self.event_queue.put(("ttn_status", idx, ttn, "duplicate", "Дублікат"))

            groups = sc.group_ttns(list(ok_pairs.values()))
            self.event_queue.put(("analysis_done", groups, canonical, parent_sub_map, scanned_count))
          except Exception as e:
            self.event_queue.put(("worker_error", str(e), traceback.format_exc()))

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_analysis_done(self, groups: dict, canonical: dict, parent_sub_map: dict, scanned_count: int = 0):
        self._canonical_indices.update(canonical)
        self.groups = groups
        # Merge groups into all_groups: add only new TTNs, never overwrite existing ones.
        # This prevents both double-counting on re-analysis and losing TTNs from earlier
        # portions when two portions contribute to the same registry.
        for key, group in groups.items():
            if key in self.all_groups:
                existing = self.all_groups[key]
                seen = set(existing['ttns'])
                new_ttns = group.get('ttns', [])
                new_refs = group.get('doc_refs', [None] * len(new_ttns))
                for ttn, ref in zip(new_ttns, new_refs):
                    if ttn not in seen:
                        existing['ttns'].append(ttn)
                        existing['doc_refs'].append(ref)
                        seen.add(ttn)
            else:
                self.all_groups[key] = {
                    **group,
                    'ttns': list(group.get('ttns', [])),
                    'doc_refs': list(group.get('doc_refs', [])),
                }
        self._render_registry_cards()
        self.distribute_btn.configure(state="normal" if self.all_groups else "disabled")
        self._parent_sub_map.update(parent_sub_map)
        self._apply_sub_ttn_grouping(parent_sub_map, canonical)
        self._save_analysis_async()

        sel      = self.selected_chunk_var.get()
        n_chunks = len(self.all_chunks)

        if not groups:
            self._status(f"Порція {sel + 1}/{n_chunks}: немає ТТН для розподілу.")
            next_chunk = sel + 1
            if next_chunk < n_chunks:
                self.selected_chunk_var.set(next_chunk)
                self.analyze_btn.configure(state="normal", text="Аналізувати")
            else:
                self.selected_chunk_var.set(0)
                self.analyze_btn.configure(state="normal", text="Аналізувати")
            if self._analyze_all_mode:
                if next_chunk < n_chunks:
                    self.after(200, self._analyze)
                else:
                    self._analyze_all_mode = False
                    self.analyze_all_btn.configure(text="Аналізувати все")
            return

        # Є групи — чекаємо розподілу (аналіз залишається доступним)
        self.analyze_btn.configure(state="normal", text="Аналізувати")
        names = [g['suggested_name'] for g in groups.values()]
        self._status(f"Порція {sel + 1}/{n_chunks} проаналізована. Реєстри: {', '.join(names)}. Розподіліть ТТН.")
        # Auto-switch to next portion so user can press Analyze again without manual switching
        next_chunk = sel + 1
        if next_chunk < n_chunks:
            self.selected_chunk_var.set(next_chunk)
        if self._analyze_all_mode:
            if next_chunk < n_chunks:
                self.after(200, self._analyze)
            else:
                self._analyze_all_mode = False
                self.analyze_all_btn.configure(text="Аналізувати все")

    def _abandon_session_async(self):
        """Finish any open running session without distribution (e.g. on reset/new file)."""
        session_id = self._current_session_id
        if not session_id:
            return
        ttns = [
            {"ttn": ttn, "status": status, "message": msg, "registry": ""}
            for ttn, (status, msg) in self._ttn_statuses.items()
        ]

        def _worker():
            dc.finish_session(session_id, ttns)

        threading.Thread(target=_worker, daemon=True).start()

    def _save_analysis_async(self):
        """Save accumulated analysis TTN statuses to backend in a background thread."""
        ttns = [
            {"ttn": ttn, "status": status, "message": msg}
            for ttn, (status, msg) in self._ttn_statuses.items()
        ]
        if not ttns:
            return
        session_id = self._current_session_id

        def _worker():
            if session_id is None:
                sid = dc.create_session(ttns)
                if sid:
                    self._current_session_id = sid
            else:
                dc.update_session_ttns(session_id, ttns)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_sub_ttn_grouping(self, parent_sub_map: dict, canonical: dict):
        """Attach sub-TTN labels to their parent TTNRow widgets."""
        for parent_ttn, sub_ttns in parent_sub_map.items():
            parent_idx = canonical.get(parent_ttn)
            if parent_idx is not None:
                row = self.ttn_rows.get(parent_idx)
                if row:
                    row.add_sub_ttns(sub_ttns)

    # ── Рендер карток реєстрів ────────────────────────────

    def _render_registry_cards(self):
        # Видаляємо лише orphan-віджети (не картки реєстрів) — картки попередніх порцій залишаємо
        card_widgets = set(self.all_reg_cards.values())
        children = self.reg_list.winfo_children()
        for w in children[self.done_reg_rows:]:
            if w not in card_widgets:
                w.destroy()

        if not self.groups:
            if not self.all_reg_cards and self.done_reg_rows == 0:
                ctk.CTkLabel(
                    self.reg_list, text="Немає груп для розподілу",
                    text_color=C_GRAY
                ).grid(row=0, column=0, padx=20, pady=20)
            return

        new_row = self.done_reg_rows + len(self.all_reg_cards)
        for key, group in self.groups.items():
            name = group['suggested_name']
            if name in self.all_reg_cards:
                # Card already exists — set count from merged all_groups (no double-counting)
                card = self.all_reg_cards[name]
                card.update_count(len(self.all_groups[key]['ttns']))
            else:
                # Нова картка
                card = RegistryCard(self.reg_list, group)
                card.grid(row=new_row, column=0, sticky="ew", pady=4)
                card.set_pending()
                self.all_reg_cards[name] = card
                new_row += 1

    # ── Авторозподіл ──────────────────────────────────────

    def _distribute(self):
        api_key = self.api_key.get().strip()
        if not api_key:
            return

        needed = sum(len(g.get('ttns', [])) for g in self.all_groups.values())
        balance = dc.check_balance()
        if balance is not None and balance != -1 and balance < needed:
            self._show_insufficient_balance_popup(balance, needed)
            return

        self.distribute_btn.configure(state="disabled", text="Розподіляю...")
        self._status("Розподіл по реєстрах...")

        groups_copy = {k: dict(v) for k, v in self.all_groups.items()}

        def _worker():
            results = sc.distribute(
                api_key, groups_copy,
                lambda msg: self.event_queue.put(("log", msg))
            )
            self.event_queue.put(("distribute_done", results))

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_distribute_done(self, results: dict):
        all_ttn_report: list[dict] = []
        for key, res_list in results.items():
            group = self.all_groups.get(key, {})
            registry_name = group.get('suggested_name', '')
            card  = self.all_reg_cards.get(registry_name)
            if card:
                done_ttns = [ttn for ttn, s, _ in res_list if s == 'done']
                err  = sum(1 for _, s, _ in res_list if s == 'error')
                card.set_done(len(done_ttns), err, done_ttns)
            for ttn, status, msg in res_list:
                all_ttn_report.append({
                    "ttn": ttn, "status": status,
                    "registry": registry_name if status == 'done' else "",
                    "message": msg or "",
                })
                canonical_idx = self._canonical_indices.get(ttn)
                if canonical_idx is not None:
                    row = self.ttn_rows.get(canonical_idx)
                    if row:
                        row.set_status(status, msg)
                else:
                    for idx in self.ttn_indices.get(ttn, []):
                        row = self.ttn_rows.get(idx)
                        if row:
                            row.set_status(status, msg)

        if all_ttn_report:
            session_id = self._current_session_id

            def _finish_worker():
                if session_id:
                    dc.finish_session(session_id, all_ttn_report, "desktop")
                else:
                    dc.report_scan(all_ttn_report, "desktop")

            threading.Thread(target=_finish_worker, daemon=True).start()

        self._current_session_id = None
        self._ttn_statuses.clear()
        self.distribute_btn.configure(text="Авторозподіл", state="disabled")
        self.done_reg_rows = len(self.reg_list.winfo_children())
        self.all_groups.clear()
        self.groups.clear()
        self.all_reg_cards.clear()
        self._canonical_indices.clear()

        sel        = self.selected_chunk_var.get()
        n_chunks   = len(self.all_chunks)
        next_chunk = sel + 1

        if next_chunk < n_chunks:
            self.selected_chunk_var.set(next_chunk)
            self.analyze_btn.configure(state="normal", text="Аналізувати")
            self._status(f"Розподіл завершено. Натисніть 'Далі' для наступної порції.")
        else:
            self.selected_chunk_var.set(0)
            self.analyze_btn.configure(state="normal", text="Аналізувати")
            self._status("Всі ТТН розподілено!")

    # ── Retry одної ТТН ───────────────────────────────────

    def _retry_single_ttn(self, abs_idx: int, ttn: str):
        api_key = self.api_key.get().strip()
        if not api_key:
            return
        self.event_queue.put(("ttn_status", abs_idx, ttn, "processing", ""))

        def _worker():
            try:
                status, doc = sc.validate_ttn(api_key, ttn)
            except np_api.NPConnectionError:
                self.event_queue.put(("ttn_status", abs_idx, ttn, "error", "Помилка з'єднання"))
                self.event_queue.put(("np_connection_error",))
                return
            except Exception as e:
                self.event_queue.put(("ttn_status", abs_idx, ttn, "error", str(e)))
                return

            if status == "ok":
                self.event_queue.put(("ttn_status", abs_idx, ttn, "ok",
                                      doc.get("SenderDescription", "")))
                self.event_queue.put(("retry_ttn_ok", abs_idx, ttn, doc))
            elif status == "already_in_registry":
                sheet = doc.get("ScanSheetNumber", "") if doc else ""
                self.event_queue.put(("ttn_status", abs_idx, ttn, "already",
                                      f"Реєстр {sheet}"))
            else:
                self.event_queue.put(("ttn_status", abs_idx, ttn, "not_found", ""))

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_retry_ttn_ok(self, abs_idx: int, ttn: str, doc: dict):
        """Integrate a successfully retried TTN into groups and refresh registry cards."""
        self._canonical_indices[ttn] = abs_idx
        new_groups = sc.group_ttns([(ttn, doc)])
        for key, group in new_groups.items():
            if key in self.all_groups:
                existing = self.all_groups[key]
                if ttn not in existing["ttns"]:
                    existing["ttns"].append(ttn)
                    existing["doc_refs"].append(doc.get("Ref", ""))
            else:
                self.all_groups[key] = {
                    **group,
                    "ttns": list(group.get("ttns", [])),
                    "doc_refs": list(group.get("doc_refs", [])),
                }
        self.groups = new_groups
        self._render_registry_cards()
        if self.all_groups:
            self.distribute_btn.configure(state="normal")

    def _show_np_connection_error_popup(self):
        popup = ctk.CTkToplevel(self)
        popup.title("Помилка з'єднання")
        popup.geometry("420x180")
        popup.resizable(False, False)
        popup.grab_set()
        popup.lift()
        popup.focus_force()

        ctk.CTkLabel(
            popup,
            text="Усі спроби з'єднатись з Новою Поштою провалились.\n"
                 "Перезапустіть програму або зачекайте декілька хвилин\n"
                 "і спробуйте знову.",
            font=ctk.CTkFont(size=13), text_color=C_ORANGE,
            wraplength=380, justify="center",
        ).pack(expand=True, pady=(24, 10))

        def _ok():
            popup.grab_release()
            popup.destroy()

        ctk.CTkButton(
            popup, text="OK", width=100, height=34,
            fg_color=C_ORANGE, hover_color="#c87f0a",
            command=_ok,
        ).pack(pady=(0, 20))

        popup.protocol("WM_DELETE_WINDOW", _ok)

    # ── Утиліти ───────────────────────────────────────────

    def _clear_ui(self):
        for w in self.ttn_list.winfo_children():
            w.destroy()
        for w in self.reg_list.winfo_children():
            w.destroy()
        self.ttn_rows.clear()
        self.ttn_indices.clear()
        self.groups.clear()
        self.all_groups.clear()
        self.all_chunks         = []
        self.all_ttns           = []
        self.selected_chunk_var.set(0)
        self.done_reg_rows      = 0
        self._next_ttn_grid_row = 0
        self.all_reg_cards = {}
        self._canonical_indices = {}
        self._parent_sub_map = {}
        self.analyze_btn.configure(text="Аналізувати")
        self._analyze_all_mode = False
        self.analyze_all_btn.configure(text="Аналізувати все")
        self._abandon_session_async()
        self._current_session_id = None
        self._ttn_statuses.clear()

    def _show_warning_popup(self, message: str, reply_event: threading.Event):
        popup = ctk.CTkToplevel(self)
        popup.title("Увага")
        popup.geometry("380x280")
        popup.resizable(False, False)
        popup.grab_set()
        popup.lift()
        popup.focus_force()

        ctk.CTkLabel(
            popup, text=message,
            font=ctk.CTkFont(size=13), text_color=C_RED,
            wraplength=320, justify="center"
        ).pack(expand=True, pady=(20, 10))

        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(pady=(0, 16))

        def _ok():
            popup.grab_release()
            popup.destroy()
            reply_event.set()

        def _stop():
            self._stop_analysis.set()
            _ok()

        ctk.CTkButton(
            btn_frame, text="OK", width=100, height=34,
            fg_color=C_RED, hover_color="#c0392b",
            command=_ok
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_frame, text="Зупинити", width=110, height=34,
            fg_color="#555555", hover_color="#444444",
            command=_stop
        ).pack(side="left")

        popup.protocol("WM_DELETE_WINDOW", _ok)

    def _show_error_popup(self, tb: str):
        popup = ctk.CTkToplevel(self)
        popup.title("Помилка аналізу")
        popup.geometry("600x400")
        popup.grab_set()
        popup.lift()
        popup.focus_force()

        ctk.CTkLabel(
            popup, text="Виникла неочікувана помилка. Трейсбек:",
            font=ctk.CTkFont(size=13), text_color=C_RED,
        ).pack(pady=(16, 4), padx=16, anchor="w")

        tb_box = ctk.CTkTextbox(
            popup, font=ctk.CTkFont(family="Consolas", size=11),
            wrap="none",
        )
        tb_box.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        tb_box.insert("1.0", tb)
        tb_box.configure(state="disabled")

        ctk.CTkButton(
            popup, text="OK", width=100, height=34,
            fg_color=C_RED, hover_color="#c0392b",
            command=lambda: (popup.grab_release(), popup.destroy()),
        ).pack(pady=(0, 16))

        popup.protocol("WM_DELETE_WINDOW", lambda: (popup.grab_release(), popup.destroy()))

    def _status(self, msg: str):
        self.status_bar.configure(text=msg)
        print(msg)

    # ── Events ────────────────────────────────────────────

    def _poll_events(self):
        while not self.event_queue.empty():
            ev = self.event_queue.get_nowait()
            match ev[0]:
                case "ttn_status":
                    _, abs_idx, ttn, status, msg = ev
                    row = self.ttn_rows.get(abs_idx)
                    if row:
                        row.set_status(status, msg)
                    if status not in ("processing",):
                        norm = {"already": "already_in_registry"}.get(status, status)
                        self._ttn_statuses[ttn] = (norm, msg)
                case "analysis_done":
                    self._handle_analysis_done(ev[1], ev[2], ev[3], ev[4] if len(ev) > 4 else 0)
                case "distribute_done":
                    self._handle_distribute_done(ev[1])
                case "show_warning":
                    _, ttn, msg, reply_event = ev
                    self._show_warning_popup(msg, reply_event)
                case "log":
                    self._status(ev[1])
                case "np_connection_error":
                    self.analyze_btn.configure(state="normal")
                    self._analyze_all_mode = False
                    self.analyze_all_btn.configure(text="Аналізувати все")
                    self._status("Помилка з'єднання з Новою Поштою.")
                    self._show_np_connection_error_popup()
                case "retry_ttn_ok":
                    _, abs_idx, ttn, doc = ev
                    self._handle_retry_ttn_ok(abs_idx, ttn, doc)
                case "worker_error":
                    _, err_msg, tb = ev
                    self.analyze_btn.configure(state="normal")
                    self._analyze_all_mode = False
                    self.analyze_all_btn.configure(text="Аналізувати все")
                    self._status(f"Помилка аналізу: {err_msg}")
                    self._show_error_popup(tb)
        self.after(80, self._poll_events)

    # ── Конфіг ────────────────────────────────────────────

    def _load_config(self) -> dict:
        if CONFIG_FILE.exists():
            try:
                return json.loads(CONFIG_FILE.read_text())
            except Exception:
                pass
        return {}

    def _save_config(self):
        # Preserve existing fields (email, desktop_token) when saving user settings
        existing = self._load_config()
        existing["api_key"] = self.api_key.get()
        existing["input_file"] = self.input_file.get()
        CONFIG_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2))

    def _show_insufficient_balance_popup(self, balance: int, needed: int):
        popup = ctk.CTkToplevel(self)
        popup.title("Недостатньо сканувань")
        popup.geometry("420x220")
        popup.resizable(False, False)
        popup.grab_set()
        popup.lift()
        popup.focus_force()

        ctk.CTkLabel(
            popup,
            text=f"Недостатньо сканувань!\n\n"
                 f"Потрібно: {needed}  |  Доступно: {balance}\n\n"
                 f"Поповніть баланс на сторінці ttnflow.com/app/",
            font=ctk.CTkFont(size=13), text_color=C_ORANGE,
            wraplength=380, justify="center",
        ).pack(expand=True, pady=(24, 10))

        def _ok():
            popup.grab_release()
            popup.destroy()

        ctk.CTkButton(
            popup, text="OK", width=100, height=34,
            fg_color=C_ORANGE, hover_color="#c87f0a",
            command=_ok,
        ).pack(pady=(0, 20))

        popup.protocol("WM_DELETE_WINDOW", _ok)


if __name__ == "__main__":
    App().mainloop()
