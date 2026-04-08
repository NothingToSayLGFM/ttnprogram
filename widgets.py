import threading
import time
from datetime import date

import customtkinter as ctk

import api as np_api

C_GREEN  = "#27ae60"
C_ORANGE = "#f39c12"
C_RED    = "#e74c3c"
C_GRAY   = "#7f8c8d"
C_DARK   = "#2b2b2b"
C_BLUE   = "#2980b9"


# ── Рядок ТТН (ліва панель) ──────────────────────────────

class TTNRow(ctk.CTkFrame):
    COLORS = {
        "pending":    (C_GRAY,   "Очікує"),
        "processing": (C_ORANGE, "Аналіз..."),
        "not_found":  (C_RED,    "Не знайдено"),
        "already":    (C_ORANGE, "Вже в реєстрі"),
        "ok":         (C_GREEN,  ""),        # sender shown in label
        "done":       (C_GREEN,  "Додано"),
        "duplicate":  (C_RED,    "Дублікат"),
        "error":      (C_RED,    ""),
    }

    def __init__(self, parent, index: int, ttn: str, on_retry=None):
        super().__init__(parent, fg_color=C_DARK, corner_radius=5)
        self.grid_columnconfigure(3, weight=1)  # spacer між кнопкою і статусом
        self._on_retry = on_retry

        ctk.CTkLabel(
            self, text=f"#{index}", width=32,
            font=ctk.CTkFont(size=11), text_color=C_GRAY
        ).grid(row=0, column=0, padx=(8, 4), pady=5)

        ctk.CTkLabel(
            self, text=ttn,
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"), anchor="w"
        ).grid(row=0, column=1, sticky="w")

        ctk.CTkButton(
            self, text="⎘", width=24, height=20,
            fg_color="#444444", hover_color="#555555",
            font=ctk.CTkFont(size=11),
            command=lambda t=ttn: (self.clipboard_clear(), self.clipboard_append(t))
        ).grid(row=0, column=2, padx=(4, 0))

        # col 3 — spacer, растягивается

        self.dot = ctk.CTkLabel(self, text="●", text_color=C_GRAY, width=14)
        self.dot.grid(row=0, column=4, padx=(0, 4))

        self.lbl = ctk.CTkLabel(
            self, text="Очікує", width=160, anchor="e",
            font=ctk.CTkFont(size=11), text_color=C_GRAY
        )
        self.lbl.grid(row=0, column=5, padx=(0, 6))

        self._retry_btn = ctk.CTkButton(
            self, text="↻", width=28, height=20,
            fg_color=C_ORANGE, hover_color="#c87f0a",
            font=ctk.CTkFont(size=12),
            command=self._handle_retry,
        )
        self._retry_btn.grid(row=0, column=6, padx=(0, 8))
        self._retry_btn.grid_remove()  # hidden until status == "error"

    def _handle_retry(self):
        if self._on_retry:
            self._on_retry()

    def set_status(self, status: str, msg: str = ""):
        color, text = self.COLORS.get(status, (C_GRAY, status))
        if not text:
            text = msg
        self.dot.configure(text_color=color)
        self.lbl.configure(text=text, text_color=color)
        if status == "error":
            self._retry_btn.grid()
        else:
            self._retry_btn.grid_remove()

    def add_sub_ttns(self, sub_ttns: list[str]):
        """Render sub-TTNs indented below parent in row=1."""
        sub_frame = ctk.CTkFrame(self, fg_color="transparent")
        sub_frame.grid(row=1, column=0, columnspan=6, sticky="ew", padx=(48, 8), pady=(0, 6))
        for i, ttn in enumerate(sub_ttns):
            ctk.CTkLabel(
                sub_frame, text=ttn,
                font=ctk.CTkFont(family="Consolas", size=11),
                text_color="#aaaaaa", anchor="w"
            ).grid(row=i, column=0, sticky="w")
            ctk.CTkButton(
                sub_frame, text="⎘", width=24, height=18,
                fg_color="#444444", hover_color="#555555",
                font=ctk.CTkFont(size=11),
                command=lambda t=ttn: (self.clipboard_clear(), self.clipboard_append(t))
            ).grid(row=i, column=1, padx=(6, 0))


# ── Картка реєстру (права панель) ────────────────────────

class RegistryCard(ctk.CTkFrame):
    def __init__(self, parent, group: dict):
        super().__init__(parent, fg_color="#333333", corner_radius=8)
        self.grid_columnconfigure(0, weight=1)

        name    = group['suggested_name']
        sender  = group['sender_description']
        wh      = group['warehouse_description']
        count   = len(group['ttns'])

        self.grid_columnconfigure(0, weight=1)

        name_row = ctk.CTkFrame(self, fg_color="transparent")
        name_row.grid(row=0, column=0, padx=12, pady=(10, 2), sticky="ew")

        ctk.CTkLabel(
            name_row, text=name,
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"), anchor="w"
        ).pack(side="left")

        self._name = name
        ctk.CTkButton(
            name_row, text="⎘", width=28, height=24,
            fg_color="#444444", hover_color="#555555",
            font=ctk.CTkFont(size=13),
            command=self._copy_name
        ).pack(side="left", padx=(8, 0))

        ctk.CTkLabel(
            self, text=f"{sender}  •  {wh}",
            font=ctk.CTkFont(size=11), text_color=C_GRAY, anchor="w", wraplength=360
        ).grid(row=1, column=0, padx=12, pady=(0, 2), sticky="w")

        self._total_ttns = count
        self.count_lbl = ctk.CTkLabel(
            self, text=f"{count} ТТН",
            font=ctk.CTkFont(size=11), text_color=C_GRAY, anchor="w"
        )
        self.count_lbl.grid(row=2, column=0, padx=12, pady=(0, 6), sticky="w")

        self.status_lbl = ctk.CTkLabel(
            self, text="⏳  Очікування перевірки",
            font=ctk.CTkFont(size=12), text_color=C_GRAY, anchor="w"
        )
        self.status_lbl.grid(row=3, column=0, padx=12, pady=(0, 10), sticky="w")
        self._next_ttn_row = 4  # рядок для наступних TTN-лейблів

    def _copy_name(self):
        self.clipboard_clear()
        self.clipboard_append(self._name)

    def set_pending(self):
        self.status_lbl.configure(text="⏳  Буде створено автоматично", text_color=C_GRAY)

    def add_ttns_pending(self, extra_count: int):
        """Оновлює лічильник ТТН і скидає статус — для наступної порції в той самий реєстр."""
        self._total_ttns += extra_count
        self.count_lbl.configure(text=f"{self._total_ttns} ТТН")
        self.set_pending()

    def update_count(self, new_total: int):
        """Sets the displayed TTN count to an absolute value (no accumulation)."""
        self._total_ttns = new_total
        self.count_lbl.configure(text=f"{new_total} ТТН")
        self.set_pending()

    def set_done(self, done: int, err: int, ttns: list[str] = None):
        if err == 0:
            self.status_lbl.configure(text=f"✅  Додано {done} ТТН", text_color=C_GREEN)
        else:
            self.status_lbl.configure(text=f"⚠️  Додано {done}, помилок {err}", text_color=C_ORANGE)
        if ttns:
            for i, ttn in enumerate(ttns):
                row_frame = ctk.CTkFrame(self, fg_color="transparent")
                row_frame.grid(row=self._next_ttn_row + i, column=0, padx=24, pady=(0, 2), sticky="w")
                ctk.CTkLabel(
                    row_frame, text=ttn,
                    font=ctk.CTkFont(family="Consolas", size=11), text_color=C_GREEN, anchor="w"
                ).pack(side="left")
                ctk.CTkButton(
                    row_frame, text="⎘", width=24, height=20,
                    fg_color="#444444", hover_color="#555555",
                    font=ctk.CTkFont(size=11),
                    command=lambda t=ttn: (self.clipboard_clear(), self.clipboard_append(t))
                ).pack(side="left", padx=(6, 0))
            self._next_ttn_row += len(ttns)


# ── Модалка «Надруковані ТТН» ─────────────────────────────

class PrintedModal(ctk.CTkToplevel):
    POLL_INTERVAL = 60  # seconds

    def __init__(self, parent, api_key: str):
        super().__init__(parent)
        self.title("Надруковані ТТН")
        self.geometry("520x600")
        self.minsize(400, 320)
        self.api_key = api_key
        self._seen: set = set()
        self._stop = threading.Event()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.grab_set()
        self.lift()
        self.focus_force()

        threading.Thread(target=self._poll_loop, daemon=True).start()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._status_lbl = ctk.CTkLabel(
            self, text="Очікую...",
            font=ctk.CTkFont(size=12), text_color=C_GRAY, anchor="w"
        )
        self._status_lbl.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", self._on_search)
        ctk.CTkEntry(
            self, textvariable=self._search_var,
            placeholder_text="Пошук ТТН...",
            height=32, font=ctk.CTkFont(family="Consolas", size=13)
        ).grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))

        self._scroll = ctk.CTkScrollableFrame(self, label_text="Надруковані ТТН")
        self._scroll.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self._scroll.grid_columnconfigure(0, weight=1)
        self._row_idx = 0
        self._row_widgets: list[tuple[str, ctk.CTkFrame]] = []  # (ttn, frame)

    def _poll_loop(self):
        while not self._stop.is_set():
            try:
                date_str = date.today().strftime('%d.%m.%Y')
                docs = np_api.get_printed_documents(self.api_key, date_str)
                new_ttns = [
                    d.get("IntDocNumber", "").strip()
                    for d in docs
                    if d.get("IntDocNumber", "").strip()
                    and d.get("IntDocNumber", "").strip() not in self._seen
                    and not d.get("ScanSheetNumber", "").strip()
                ]
                if new_ttns:
                    self.after(0, lambda ttns=new_ttns: self._add_ttns(ttns))
                self.after(0, lambda: self._status_lbl.configure(
                    text=f"Оновлено: {time.strftime('%H:%M:%S')}  •  всього {len(self._seen)} ТТН",
                    text_color=C_GRAY
                ))
            except Exception as e:
                self.after(0, lambda err=e: self._status_lbl.configure(
                    text=f"Помилка: {err}", text_color=C_RED
                ))
            for _ in range(self.POLL_INTERVAL):
                if self._stop.is_set():
                    return
                time.sleep(1)

    def _add_ttns(self, ttns: list):
        query = self._search_var.get().strip()
        for ttn in ttns:
            if ttn in self._seen:
                continue
            self._seen.add(ttn)
            row_frame = ctk.CTkFrame(self._scroll, fg_color="transparent")
            row_frame.grid(row=self._row_idx, column=0, sticky="ew", pady=2)
            ctk.CTkLabel(
                row_frame, text=ttn,
                font=ctk.CTkFont(family="Consolas", size=14, weight="bold"), anchor="w"
            ).pack(side="left", padx=(6, 0))
            ctk.CTkButton(
                row_frame, text="⎘", width=28, height=24,
                fg_color="#444444", hover_color="#555555",
                font=ctk.CTkFont(size=13),
                command=lambda t=ttn: (self.clipboard_clear(), self.clipboard_append(t))
            ).pack(side="left", padx=(8, 0))
            self._row_widgets.append((ttn, row_frame))
            self._row_idx += 1
            # Apply current filter immediately
            if query and query.lower() not in ttn.lower():
                row_frame.grid_remove()

    def _on_search(self, *_):
        query = self._search_var.get().strip().lower()
        for ttn, frame in self._row_widgets:
            if not query or query in ttn.lower():
                frame.grid()
            else:
                frame.grid_remove()

    def _on_close(self):
        self._stop.set()
        self.grab_release()
        self.destroy()
