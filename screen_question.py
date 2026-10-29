# -*- coding: utf-8 -*-
"""Вопрос с экрана: Ctrl+Y -> захват экрана; Ctrl+T -> перевод выделенного текста.
OpenAI-совместимый API (в т.ч. xAI/Grok).

Только для своих материалов, QA и доступности. Пока захват активен, на экране виден индикатор.
Отправка выполняется только по явному действию пользователя (горячая клавиша, кнопка, меню значка).
"""
import ctypes
import queue
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlparse

from PIL import Image, ImageTk

import core

IS_WIN = sys.platform == "win32"
ASSETS = Path(__file__).resolve().parent / "assets"
HOTKEY = "Ctrl+Y"
HOTKEY_TRANSLATE = "Ctrl+T"
GREEN, ORANGE, BLUE, RED = "#1b7f3b", "#b35c00", "#1a56b0", "#b3261e"

if IS_WIN:
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass

_MUTEX = None


def single_instance():
    """Одна копия программы: второй экземпляр не сможет занять горячие клавиши."""
    global _MUTEX
    if not IS_WIN:
        return True
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateMutexW.restype = wintypes.HANDLE
    _MUTEX = k.CreateMutexW(None, False, "Local\\ScreenQuestionSingleInstance")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


class Hotkey:
    """Глобальные Ctrl+Y (захват) и Ctrl+T (перевод выделенного текста) через RegisterHotKey.
    Работает в любой раскладке: регистрируется код клавиши, а не символ."""
    MOD_CONTROL, MOD_NOREPEAT, WM_HOTKEY, WM_QUIT = 0x2, 0x4000, 0x0312, 0x0012
    VK_Y, VK_T = 0x59, 0x54
    ID_CAPTURE, ID_TRANSLATE = 1, 2

    def __init__(self, events):
        self.events = events
        self.thread = None
        self.tid = None
        self.error = ""

    def start(self):
        """Возвращает текст ошибки или пустую строку."""
        if not IS_WIN:
            return "Глобальные горячие клавиши работают только в Windows. Используйте кнопки и меню значка."
        ready = threading.Event()
        self.error = ""
        self.thread = threading.Thread(target=self._run, args=(ready,), name="Hotkey", daemon=True)
        self.thread.start()
        if not ready.wait(3):
            return "Не удалось зарегистрировать горячие клавиши (нет ответа от системы)."
        return self.error

    def _run(self, ready):
        u = ctypes.WinDLL("user32", use_last_error=True)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        u.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        u.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        u.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        msg = wintypes.MSG()
        u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # создаёт очередь сообщений потока
        self.tid = k.GetCurrentThreadId()
        mods = self.MOD_CONTROL | self.MOD_NOREPEAT
        ok_y = u.RegisterHotKey(None, self.ID_CAPTURE, mods, self.VK_Y)
        ok_t = u.RegisterHotKey(None, self.ID_TRANSLATE, mods, self.VK_T)
        if not ok_y or not ok_t:
            code = ctypes.get_last_error()
            failed = []
            if not ok_y:
                failed.append("Ctrl+Y")
                u.UnregisterHotKey(None, self.ID_CAPTURE)
            if not ok_t:
                failed.append("Ctrl+T")
                u.UnregisterHotKey(None, self.ID_TRANSLATE)
            self.error = (f"Сочетание {'/'.join(failed)} уже занято другой программой (код Windows {code}). "
                          "Закройте её или используйте кнопки в окне программы.")
            ready.set()
            return
        ready.set()
        try:
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == self.WM_HOTKEY:
                    if msg.wParam == self.ID_CAPTURE:
                        self.events.put(("capture", None))
                    elif msg.wParam == self.ID_TRANSLATE:
                        self.events.put(("translate", None))
        finally:
            u.UnregisterHotKey(None, self.ID_CAPTURE)
            u.UnregisterHotKey(None, self.ID_TRANSLATE)

    def stop(self):
        if IS_WIN and self.tid and self.thread and self.thread.is_alive():
            ctypes.WinDLL("user32").PostThreadMessageW(self.tid, self.WM_QUIT, 0, 0)
            self.thread.join(1)
        self.tid = None


def enable_clipboard(widget, readonly=False):
    """Копирование/вставка: контекстное меню и Ctrl+C/V/X/A по физическим клавишам (работает в русской раскладке)."""
    def select_all():
        if isinstance(widget, (tk.Entry, ttk.Entry)):
            widget.selection_range(0, tk.END)
        else:
            widget.tag_add("sel", "1.0", "end-1c")
        return "break"

    def on_key(event):
        if not IS_WIN or not event.state & 0x4:
            return None
        if event.keycode == 67:
            widget.event_generate("<<Copy>>")
        elif event.keycode == 86 and not readonly:
            widget.event_generate("<<Paste>>")
        elif event.keycode == 88 and not readonly:
            widget.event_generate("<<Cut>>")
        elif event.keycode == 65:
            return select_all()
        else:
            return None
        return "break"

    menu = tk.Menu(widget, tearoff=False)
    menu.add_command(label="Копировать", command=lambda: widget.event_generate("<<Copy>>"))
    if not readonly:
        menu.add_command(label="Вставить", command=lambda: widget.event_generate("<<Paste>>"))
        menu.add_command(label="Вырезать", command=lambda: widget.event_generate("<<Cut>>"))
    menu.add_command(label="Выделить всё", command=select_all)
    widget.bind("<Control-KeyPress>", on_key, add="+")
    widget.bind("<Button-3>", lambda e: (widget.focus_set(), menu.tk_popup(e.x_root, e.y_root)))


def get_selected_text(timeout=2.0):
    """Скопировать текущее выделение.
    Для Блокнота пробует напрямую EM_GETSEL + WM_GETTEXT.
    Для остальных — SendInput Ctrl+C с паузой после отпускания клавиш.
    """
    if not IS_WIN:
        return "", "Получение выделения доступно только в Windows."

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    WM_COPY = 0x0301
    EM_GETSEL = 0x00B0
    WM_GETTEXT = 0x000D
    WM_GETTEXTLENGTH = 0x000E
    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    VK_CONTROL = 0x11
    VK_C = 0x43

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
        ]

    class INPUT(ctypes.Structure):
        class _INPUT(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]
        _anonymous_ = ("_input",)
        _fields_ = [("type", wintypes.DWORD), ("_input", _INPUT)]

    def send_ctrl_c():
        extra = ctypes.pointer(wintypes.ULONG(0))
        inputs = (INPUT * 4)()
        inputs[0].type = INPUT_KEYBOARD
        inputs[0].ki = KEYBDINPUT(VK_CONTROL, 0, 0, 0, extra)
        inputs[1].type = INPUT_KEYBOARD
        inputs[1].ki = KEYBDINPUT(VK_C, 0, 0, 0, extra)
        inputs[2].type = INPUT_KEYBOARD
        inputs[2].ki = KEYBDINPUT(VK_C, 0, KEYEVENTF_KEYUP, 0, extra)
        inputs[3].type = INPUT_KEYBOARD
        inputs[3].ki = KEYBDINPUT(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0, extra)
        user32.SendInput(4, ctypes.byref(inputs), ctypes.sizeof(INPUT))

    def open_clip(retries=15):
        for _ in range(retries):
            if user32.OpenClipboard(None):
                return True
            time.sleep(0.03)
        return False

    def close_clip():
        try:
            user32.CloseClipboard()
        except Exception:
            pass

    def get_clip_text():
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return ""
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr) or ""
        finally:
            kernel32.GlobalUnlock(h)

    def set_clip_text(s):
        user32.EmptyClipboard()
        if not s:
            return
        data = (s + "\0").encode("utf-16-le")
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            return
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            kernel32.GlobalFree(h)
            return
        try:
            ctypes.memmove(ptr, data, len(data))
        finally:
            kernel32.GlobalUnlock(h)
        user32.SetClipboardData(CF_UNICODETEXT, h)

    # Save clipboard
    saved = ""
    if open_clip():
        try:
            saved = get_clip_text()
        finally:
            close_clip()

    hwnd = user32.GetForegroundWindow()
    text_found = ""

    # Special case: Notepad (class "Notepad" or modern "Notepad" with Edit child)
    if hwnd:
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        class_name = cls.value
        edit = None
        if class_name == "Notepad":
            edit = user32.FindWindowExW(hwnd, None, "Edit", None)
        elif class_name in ("Chrome_WidgetWin_1", "MozillaWindowClass"):
            # browsers often don't respond well; fall through to SendInput
            pass

        if edit:
            # Try to get selection range and text from Edit control
            sel = user32.SendMessageW(edit, EM_GETSEL, 0, 0)
            start = sel & 0xFFFF
            end = (sel >> 16) & 0xFFFF
            if end > start:
                length = user32.SendMessageW(edit, WM_GETTEXTLENGTH, 0, 0)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.SendMessageW(edit, WM_GETTEXT, length + 1, buf)
                    full = buf.value
                    if full and end <= len(full):
                        text_found = full[start:end].strip()

    # Fallback: SendInput Ctrl+C after a short pause (so hotkey Ctrl is released)
    if not text_found:
        time.sleep(0.15)  # give time for Ctrl from hotkey to be released
        send_ctrl_c()
        time.sleep(0.25)

        deadline = time.time() + timeout
        while time.time() < deadline:
            if open_clip():
                try:
                    current = (get_clip_text() or "").strip()
                    if current and current != (saved or "").strip():
                        text_found = current
                        break
                finally:
                    close_clip()
            time.sleep(0.08)

    # Restore clipboard
    if open_clip():
        try:
            set_clip_text(saved)
        finally:
            close_clip()

    if not text_found:
        return "", "Нет выделенного текста (попробуйте выделить текст в Блокноте или нажать Ctrl+C вручную перед Ctrl+T)."
    return text_found, ""




class Badge:
    """Заметный индикатор состояния в углу экрана. Текст дублирует цвет."""
    def __init__(self, app):
        self.app = app
        self.job = None
        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.frame = tk.Frame(self.win, padx=12, pady=7)
        self.frame.pack()
        self.label = tk.Label(self.frame, font=("Segoe UI", 11, "bold"), fg="white")
        self.label.pack(side="left")
        self.button = tk.Button(self.frame, text="Отмена", relief="flat", command=app.cancel_request)

    def show(self, text, color, cancel=False, ms=None):
        if self.job:
            self.win.after_cancel(self.job)
            self.job = None
        self.frame.configure(bg=color)
        self.label.configure(text=text, bg=color)
        if cancel:
            self.button.pack(side="left", padx=(10, 0))
        else:
            self.button.pack_forget()
        self.win.update_idletasks()
        x = self.win.winfo_screenwidth() - self.win.winfo_reqwidth() - 16
        self.win.geometry(f"+{x}+16")
        self.win.deiconify()
        self.win.lift()
        if ms:
            self.job = self.win.after(ms, self.app.refresh_badge)

    def hide(self):
        if self.job:
            self.win.after_cancel(self.job)
            self.job = None
        self.win.withdraw()


class Selector:
    """Полупрозрачный слой на всех мониторах: тянем рамку мышью. Слой убирается сразу после выбора."""
    def __init__(self, app, monitor, on_done):
        self.app, self.m, self.on_done = app, monitor, on_done
        self.done, self.start_xy, self.rect = False, None, None
        w, h, left, top = monitor["width"], monitor["height"], monitor["left"], monitor["top"]
        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", 0.4)
        except tk.TclError:
            pass
        self.win.configure(bg="black")
        self.win.geometry(f"{w}x{h}{left:+d}{top:+d}")
        self.canvas = tk.Canvas(self.win, bg="black", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<Button-3>", lambda e: self.finish(None))
        self.win.bind("<Escape>", lambda e: self.finish(None))
        px, py = app.root.winfo_pointerx(), app.root.winfo_pointery()
        self.hint = tk.Toplevel(app.root)
        self.hint.overrideredirect(True)
        self.hint.attributes("-topmost", True)
        tk.Label(self.hint, text="Выделите область мышью. Esc или правая кнопка: отмена.",
                 bg="#202733", fg="white", font=("Segoe UI", 12), padx=12, pady=8).pack()
        self.hint.geometry(f"+{px + 20}+{py + 20}")
        self.win.deiconify()
        self.win.lift()
        self.hint.lift()
        self.win.focus_force()
        self.win.grab_set()

    def clamp(self, x, y):
        return max(0, min(x, self.m["width"])), max(0, min(y, self.m["height"]))

    def press(self, e):
        self.start_xy = self.clamp(e.x, e.y)
        if self.rect:
            self.canvas.delete(self.rect)
        x, y = self.start_xy
        self.rect = self.canvas.create_rectangle(x, y, x, y, outline="#70d6ff", width=3)

    def drag(self, e):
        if self.start_xy:
            x, y = self.clamp(e.x, e.y)
            self.canvas.coords(self.rect, *self.start_xy, x, y)

    def release(self, e):
        if not self.start_xy:
            return
        x, y = self.clamp(e.x, e.y)
        (sx, sy) = self.start_xy
        if abs(x - sx) < 12 or abs(y - sy) < 12:
            self.canvas.delete(self.rect)
            self.start_xy = None
            return
        self.finish((sx, sy, x, y))

    def finish(self, box):
        if self.done:
            return
        self.done = True
        for w in (self.win, self.hint):
            try:
                w.destroy()
            except tk.TclError:
                pass
        self.app.root.after(30, lambda: self.on_done(box))


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.s, load_err = core.load_settings()
        self.save_blocked = bool(load_err)  # не затираем повреждённый файл автоматически
        self.keystore = core.KeyStore()
        try:
            self.key = (self.keystore.get() or "").strip()
        except Exception:
            self.key = ""
        self.log = core.SessionLog(level=self.s["log_level"])
        self.log.add_secret(self.key)
        self.busy = self.active = self.closing = False
        self.cancel = threading.Event()
        self.hidden, self.selector, self.popup, self.answer_text = [], None, None, None
        self.last_answer, self.save_job, self.confirm_win = "", None, None
        self.skip_confirm, self.once_region, self.cursor = False, None, None
        self.hotkey, self.tray = Hotkey(self.events), None
        self.status = tk.StringVar(value="Готов. Нажмите «Начать».")
        root.title("Вопрос с экрана")
        root.geometry("720x640")
        root.minsize(640, 560)
        try:
            self.icon = ImageTk.PhotoImage(Image.open(ASSETS / "icon.png"))
            root.iconphoto(True, self.icon)
        except Exception:
            pass
        root.protocol("WM_DELETE_WINDOW", self.close_settings)
        self.badge = Badge(self)
        self.build_ui()
        self.watch_vars()
        root.after(80, self.poll)
        if load_err:
            self.set_status("Ошибка: файл настроек повреждён", RED)
            root.after(150, lambda: messagebox.showwarning(
                "Настройки", load_err + "\nПока вы не нажмёте «Сохранить настройки», файл не будет перезаписан.", parent=root))
        self.log.event("INFO", "APP_READY", mode=self.s["mode"], keystore=self.keystore.backend)

    # ---------- интерфейс ----------
    def build_ui(self):
        r = self.root
        top = ttk.Frame(r, padding=(14, 12, 14, 4))
        top.pack(fill="x")
        self.status_label = ttk.Label(top, textvariable=self.status, font=("Segoe UI", 13, "bold"), wraplength=660)
        self.status_label.pack(anchor="w")
        row = ttk.Frame(top)
        row.pack(fill="x", pady=(8, 0))
        self.start_btn = ttk.Button(row, text="Начать", command=self.toggle_active)
        self.start_btn.pack(side="left")
        ttk.Button(row, text=f"Захватить экран ({HOTKEY})", command=self.start_capture).pack(side="left", padx=6)
        ttk.Button(row, text=f"Перевести выделение ({HOTKEY_TRANSLATE})", command=self.start_translate).pack(side="left", padx=6)
        ttk.Button(row, text="Выбрать область", command=self.pick_region_button).pack(side="left")
        ttk.Button(row, text="Отмена запроса", command=self.cancel_request).pack(side="left", padx=6)
        ttk.Button(row, text="Выход", command=self.quit).pack(side="right")

        nb = ttk.Notebook(r)
        nb.pack(fill="both", expand=True, padx=14, pady=10)
        t1, t2, t3 = (ttk.Frame(nb, padding=12) for _ in range(3))
        nb.add(t1, text="Подключение и захват")
        nb.add(t2, text="Параметры запроса")
        nb.add(t3, text="Безопасность и лог")
        s = self.s
        self.v = {k: tk.StringVar(value=str(s[k])) for k in
                  ("endpoint", "model", "mode", "monitor", "temperature", "max_tokens", "timeout", "retries",
                   "image_format", "log_level", "translate_language")}
        self.v["confirm_before_send"] = tk.BooleanVar(value=bool(s["confirm_before_send"]))
        self.v["save_images"] = tk.BooleanVar(value=bool(s["save_images"]))
        self.v["follow_cursor"] = tk.BooleanVar(value=bool(s["follow_cursor"]))
        self.v["follow_cursor"].trace_add("write", lambda *_: self.schedule_save())
        self.v_key = tk.StringVar()

        def field(parent, label, widget, row_no):
            ttk.Label(parent, text=label).grid(row=row_no, column=0, sticky="w", pady=4, padx=(0, 10))
            widget.grid(row=row_no, column=1, sticky="ew", pady=4)
            return widget

        t1.columnconfigure(1, weight=1)
        e = field(t1, "Endpoint", ttk.Entry(t1, textvariable=self.v["endpoint"]), 0)
        enable_clipboard(e)
        field(t1, "Модель", ttk.Entry(t1, textvariable=self.v["model"]), 1)
        ttk.Label(t1, text="Для xAI: grok-4, grok-4.7, grok-4.6 и т.п. (не gpt-*).",
                  foreground="#555").grid(row=2, column=1, sticky="w", pady=(0, 6))
        keyrow = ttk.Frame(t1)
        ke = ttk.Entry(keyrow, textvariable=self.v_key, show="•")
        ke.pack(side="left", fill="x", expand=True)
        enable_clipboard(ke)
        ttk.Button(keyrow, text="Сохранить ключ", command=self.save_key).pack(side="left", padx=6)
        ttk.Button(keyrow, text="Удалить ключ", command=self.delete_key).pack(side="left")
        field(t1, "Новый API-ключ", keyrow, 3)
        self.key_info = ttk.Label(t1, wraplength=560)
        self.key_info.grid(row=4, column=1, sticky="w")
        modes = ttk.Frame(t1)
        ttk.Radiobutton(modes, text="Онлайн-съёмка (весь экран или монитор)", value="online", variable=self.v["mode"]).pack(anchor="w")
        ttk.Radiobutton(modes, text="Выделять область при каждом Ctrl+Y", value="select", variable=self.v["mode"]).pack(anchor="w")
        ttk.Radiobutton(modes, text="Запомнить область и повторять её", value="region", variable=self.v["mode"]).pack(anchor="w")
        field(t1, "Режим", modes, 5)
        count = self.monitor_count()
        mon_box = ttk.Frame(t1)
        ttk.Combobox(mon_box, textvariable=self.v["monitor"], width=6, state="readonly",
                     values=[str(i) for i in range(count + 1)]).pack(side="left")
        ttk.Checkbutton(mon_box, text="Брать монитор, где курсор (номер игнорируется)",
                        variable=self.v["follow_cursor"]).pack(side="left", padx=(12, 0))
        field(t1, "Монитор (0 = все)", mon_box, 6)
        self.region_label = ttk.Label(t1)
        field(t1, "Сохранённая область", self.region_label, 7)
        ttk.Label(t1, text="Ключ хранится отдельно от файла настроек и не попадает в логи.",
                  foreground="#555").grid(row=8, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.update_key_info()
        self.update_region_label()

        t2.columnconfigure(1, weight=1)
        ttk.Label(t2, text="Системная инструкция").grid(row=0, column=0, sticky="nw", pady=4, padx=(0, 10))
        self.t_sys = tk.Text(t2, height=5, wrap="word")
        self.t_sys.insert("1.0", s["system_prompt"])
        self.t_sys.grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(t2, text="Текст запроса").grid(row=1, column=0, sticky="nw", pady=4, padx=(0, 10))
        self.t_user = tk.Text(t2, height=3, wrap="word")
        self.t_user.insert("1.0", s["user_prompt"])
        self.t_user.grid(row=1, column=1, sticky="ew", pady=4)
        for t in (self.t_sys, self.t_user):
            enable_clipboard(t)
            t.bind("<KeyRelease>", lambda ev: self.schedule_save())
        for i, (k, label) in enumerate((("temperature", "Temperature (0-2)"), ("max_tokens", "Макс. размер ответа (токены)"),
                                        ("timeout", "Тайм-аут, сек"), ("retries", "Повторы при временных ошибках"))):
            field(t2, label, ttk.Entry(t2, textvariable=self.v[k], width=10), 2 + i)
        field(t2, "Формат изображения", ttk.Combobox(t2, textvariable=self.v["image_format"], width=8, state="readonly",
                                                    values=["PNG", "JPEG"]), 6)
        ttk.Separator(t2, orient="horizontal").grid(row=7, column=0, columnspan=2, sticky="ew", pady=12)
        ttk.Label(t2, text="Перевод выделенного текста (Ctrl+T)", font=("Segoe UI", 10, "bold")).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(0, 6))
        field(t2, "Язык перевода", ttk.Entry(t2, textvariable=self.v["translate_language"]), 9)
        ttk.Label(t2, text="Системная инструкция (перевод)").grid(row=10, column=0, sticky="nw", pady=4, padx=(0, 10))
        self.t_tr_sys = tk.Text(t2, height=3, wrap="word")
        self.t_tr_sys.insert("1.0", s.get("translate_system_prompt", core.TRANSLATE_SYSTEM_PROMPT))
        self.t_tr_sys.grid(row=10, column=1, sticky="ew", pady=4)
        ttk.Label(t2, text="Шаблон запроса (перевод)\n{language}, {text}").grid(
            row=11, column=0, sticky="nw", pady=4, padx=(0, 10))
        self.t_tr_user = tk.Text(t2, height=3, wrap="word")
        self.t_tr_user.insert("1.0", s.get("translate_user_prompt",
            "Переведи следующий текст на {language}:\n\n{text}"))
        self.t_tr_user.grid(row=11, column=1, sticky="ew", pady=4)
        for t in (self.t_tr_sys, self.t_tr_user):
            enable_clipboard(t)
            t.bind("<KeyRelease>", lambda ev: self.schedule_save())
        ttk.Label(t2, text="Выделите текст в любом приложении и нажмите Ctrl+T — он будет скопирован и отправлен на перевод.",
                  wraplength=560, foreground="#555").grid(row=12, column=0, columnspan=2, sticky="w", pady=(8, 0))

        t3.columnconfigure(0, weight=1)
        ttk.Checkbutton(t3, text="Запрашивать подтверждение перед отправкой (показывает миниатюру)",
                        variable=self.v["confirm_before_send"]).grid(sticky="w", pady=4)
        ttk.Checkbutton(t3, text="Сохранять отправленные изображения на диск (по умолчанию выключено)",
                        variable=self.v["save_images"]).grid(sticky="w", pady=4)
        lv = ttk.Frame(t3)
        ttk.Label(lv, text="Уровень лога").pack(side="left")
        ttk.Combobox(lv, textvariable=self.v["log_level"], width=9, state="readonly",
                     values=["DEBUG", "INFO", "WARNING", "ERROR"]).pack(side="left", padx=8)
        lv.grid(sticky="w", pady=4)
        ttk.Button(t3, text="Сохранить лог сессии…", command=self.save_log).grid(sticky="w", pady=4)
        ttk.Button(t3, text="Сохранить настройки", command=lambda: self.save_now(explicit=True)).grid(sticky="w", pady=4)
        ttk.Label(t3, text="В логах нет ключа, заголовков и содержимого изображений: только id, размер, формат и SHA-256.",
                  wraplength=620, foreground="#555").grid(sticky="w", pady=(12, 0))

    def monitor_count(self):
        try:
            with core._default_factory() as g:
                return len(g.monitors) - 1
        except Exception:
            return 1

    def watch_vars(self):
        for var in self.v.values():
            var.trace_add("write", lambda *a: self.schedule_save())

    def update_key_info(self):
        shown = core.mask_key(self.key) if self.key else "не задан"
        self.key_info.configure(text=f"Сохранённый ключ: {shown}. Хранилище: {self.keystore.backend}.")

    def update_region_label(self):
        r = self.s.get("region")
        self.region_label.configure(text=(f"{r['width']}×{r['height']} в точке ({r['left']}, {r['top']})" if r else "не выбрана"))

    # ---------- настройки ----------
    def collect(self):
        s = dict(self.s)
        for k in ("endpoint", "model", "mode", "image_format", "log_level", "translate_language"):
            s[k] = self.v[k].get().strip()
        for k, cast in (("temperature", float), ("max_tokens", int), ("timeout", int), ("retries", int), ("monitor", int)):
            try:
                s[k] = cast(self.v[k].get())
            except (ValueError, tk.TclError):
                pass  # пока вводят: остаётся прежнее значение
        s["confirm_before_send"] = bool(self.v["confirm_before_send"].get())
        s["follow_cursor"] = bool(self.v["follow_cursor"].get())
        s["save_images"] = bool(self.v["save_images"].get())
        s["system_prompt"] = self.t_sys.get("1.0", "end-1c")
        s["user_prompt"] = self.t_user.get("1.0", "end-1c")
        s["translate_system_prompt"] = self.t_tr_sys.get("1.0", "end-1c")
        s["translate_user_prompt"] = self.t_tr_user.get("1.0", "end-1c")
        return core.validate(s)

    def schedule_save(self):
        if self.save_job:
            self.root.after_cancel(self.save_job)
        self.save_job = self.root.after(600, self.save_now)

    def save_now(self, explicit=False):
        self.save_job = None
        self.s = self.collect()
        self.log.set_level(self.s["log_level"])
        if self.save_blocked and not explicit:
            return
        try:
            core.save_settings(self.s)
            self.save_blocked = False
            if explicit:
                self.set_status("Настройки сохранены", BLUE, 2500)
        except OSError as exc:
            self.log.event("ERROR", "SETTINGS_SAVE_FAILED", error=type(exc).__name__)
            self.set_status("Ошибка: не удалось сохранить настройки", RED, 4000)

    def save_key(self):
        k = self.v_key.get().strip()
        if not k:
            messagebox.showinfo("API-ключ", "Введите ключ в поле выше.", parent=self.root)
            return
        try:
            self.keystore.set(k)
        except Exception as exc:
            self.log.event("ERROR", "KEY_SAVE_FAILED", error=type(exc).__name__)
            messagebox.showerror("API-ключ", "Не удалось сохранить ключ в защищённом хранилище.", parent=self.root)
            return
        self.key = k
        self.log.add_secret(k)
        self.v_key.set("")
        self.update_key_info()
        self.log.event("INFO", "KEY_SAVED")
        self.set_status("Ключ сохранён", BLUE, 2500)

    def delete_key(self):
        if not messagebox.askyesno("Удалить ключ", "Удалить сохранённый API-ключ из этого компьютера?\n"
                                   "Сам ключ у провайдера это не отзывает.", parent=self.root):
            return
        try:
            self.keystore.delete()
        except Exception as exc:
            self.log.event("ERROR", "KEY_DELETE_FAILED", error=type(exc).__name__)
        self.key = ""
        self.update_key_info()
        self.log.event("INFO", "KEY_DELETED")
        self.set_status("Ключ удалён", BLUE, 2500)

    def save_log(self):
        dest = filedialog.asksaveasfilename(parent=self.root, defaultextension=".log",
                                            filetypes=[("Лог", "*.log"), ("Текст", "*.txt")],
                                            initialfile=self.log.path.name)
        if dest:
            try:
                self.log.save_copy(dest)
                self.set_status("Лог сохранён", BLUE, 2500)
            except OSError:
                messagebox.showerror("Лог", "Не удалось сохранить файл.", parent=self.root)

    # ---------- статус и индикатор ----------
    def set_status(self, text, color=None, ms=None, cancel=False):
        self.status.set(text)
        self.status_label.configure(foreground=color or "")
        if self.tray:
            try:
                self.tray.title = f"Вопрос с экрана: {text}"
            except Exception:
                pass
        if color:
            self.badge.show(text, color, cancel=cancel, ms=ms)
        if ms:
            self.root.after(ms, self.reset_status)

    def reset_status(self):
        if not self.busy:
            self.status.set("Активен (Ctrl+Y / Ctrl+T)" if self.active else "Готов. Нажмите «Начать».")
            self.status_label.configure(foreground=GREEN if self.active else "")

    def refresh_badge(self):
        if self.busy:
            self.badge.show("Запрос отправляется", ORANGE, cancel=True)
        elif self.active:
            self.badge.show(f"Активен ({HOTKEY} / {HOTKEY_TRANSLATE})", GREEN)
        else:
            self.badge.hide()

    # ---------- запуск, трей, горячая клавиша ----------
    def toggle_active(self):
        if self.active:
            self.deactivate()
            return
        self.save_now()
        err = self.hotkey.start()
        if err and IS_WIN:
            self.log.event("WARNING", "HOTKEY_FAILED", reason=err)
            self.set_status("Ошибка: горячая клавиша недоступна", RED, 5000)
            messagebox.showerror("Горячая клавиша", err, parent=self.root)
            return
        if err:
            messagebox.showinfo("Горячая клавиша", err, parent=self.root)
        self.log.event("INFO", "HOTKEY_REGISTERED" if not err else "HOTKEY_UNSUPPORTED")
        self.active = True
        tray_ok = self.start_tray()
        self.start_btn.configure(text="Остановить")
        self.status.set("Активен (Ctrl+Y / Ctrl+T)")
        self.status_label.configure(foreground=GREEN)
        self.refresh_badge()
        (self.root.withdraw if tray_ok else self.root.iconify)()

    def deactivate(self):
        self.hotkey.stop()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
            self.tray = None
        self.active = False
        self.start_btn.configure(text="Начать")
        self.log.event("INFO", "CAPTURE_STOPPED")
        self.reset_status()
        self.refresh_badge()

    def start_tray(self):
        if self.tray:
            return True
        try:
            import pystray
            put = lambda name: (lambda icon, item: self.events.put((name, None)))
            menu = pystray.Menu(
                pystray.MenuItem("Настройки", put("settings"), default=True),
                pystray.MenuItem(f"Захватить экран ({HOTKEY})", put("capture")),
                pystray.MenuItem(f"Перевести выделение ({HOTKEY_TRANSLATE})", put("translate")),
                pystray.MenuItem("Последний ответ", put("answer")),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Выход", put("quit")))
            self.tray = pystray.Icon("screen_question", Image.open(ASSETS / "icon.png"),
                                     f"Вопрос с экрана ({HOTKEY} / {HOTKEY_TRANSLATE})", menu)
            self.tray.run_detached()
            return True
        except Exception as exc:
            self.tray = None
            self.log.event("WARNING", "TRAY_FAILED", error=type(exc).__name__)
            return False

    def show_settings(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def close_settings(self):
        if self.active:
            (self.root.withdraw if self.tray else self.root.iconify)()
        else:
            self.quit()

    # ---------- захват ----------
    def hide_windows(self):
        self.hidden = []
        for w in (self.root, self.popup):
            if w is not None and w.winfo_exists() and w.state() == "normal":
                self.hidden.append(w)
                w.withdraw()

    def restore_windows(self):
        for w in self.hidden:
            if w.winfo_exists():
                w.deiconify()
        self.hidden = []

    def start_capture(self):
        if self.busy:
            self.set_status("Запрос уже выполняется", ORANGE, 2500, cancel=True)
            return
        self.s = self.collect()
        msg = core.validate_request(self.s, self.key)
        if msg:
            self.show_settings()
            messagebox.showwarning("Настройки", msg, parent=self.root)
            return
        self.cursor = core.cursor_pos()  # монитор определяем по курсору в момент Ctrl+Y
        self.busy = True
        self.cancel = threading.Event()
        self.log.event("INFO", "CAPTURE_REQUESTED", mode=self.s["mode"], monitor=self.s["monitor"])
        self.hide_windows()
        mode = self.s["mode"]
        if mode == "select" or (mode == "region" and not self.s.get("region")):
            self.root.after(200, lambda: self.open_selector(capture_after=True))
        else:
            self.badge.hide()  # на ~0,3 с, чтобы индикатор не попал в кадр
            self.root.after(300, self.grab_async)

    def start_translate(self):
        """Ctrl+T: взять выделенный текст и отправить на перевод."""
        if self.busy:
            self.set_status("Запрос уже выполняется", ORANGE, 2500, cancel=True)
            return
        self.s = self.collect()
        msg = core.validate_request(self.s, self.key)
        if msg:
            self.show_settings()
            messagebox.showwarning("Настройки", msg, parent=self.root)
            return
        text, err = get_selected_text()
        if err or not text:
            self.set_status(err or "Нет выделенного текста", RED, 3500)
            self.log.event("WARNING", "TRANSLATE_NO_TEXT", reason=err or "empty")
            return
        self.busy = True
        self.cancel = threading.Event()
        self.log.event("INFO", "TRANSLATE_REQUESTED", chars=len(text),
                       language=self.s.get("translate_language", ""))
        self.set_status("Перевод отправляется", ORANGE, cancel=True)
        threading.Thread(target=self.translate_worker, args=(text, dict(self.s), self.key, self.cancel),
                         name="Translate", daemon=True).start()

    def pick_region_button(self):
        if self.busy:
            return
        self.cursor = core.cursor_pos()
        self.busy = True
        self.cancel = threading.Event()
        self.hide_windows()
        self.badge.hide()
        self.root.after(200, lambda: self.open_selector(capture_after=False))

    def open_selector(self, capture_after):
        try:
            with core._default_factory() as g:
                mons = list(g.monitors)
            idx = core.resolve_monitor(self.s, mons, self.cursor) if self.s.get("follow_cursor") else 0
            if not 0 <= idx < len(mons):
                idx = 0
            mon = dict(mons[idx])  # слой выделения только на нужном мониторе
            self.selector = Selector(self, mon, lambda box: self.region_chosen(box, mon, capture_after))
        except Exception as exc:
            self.fail(f"Не удалось показать слой выбора области ({type(exc).__name__}).")

    def region_chosen(self, box, mon, capture_after):
        self.selector = None
        if box is None or self.cancel.is_set():
            self.finish_idle("Выбор области отменён")
            return
        region = core.make_region(*box, mon["left"], mon["top"])
        if region is None:
            self.fail("Область слишком маленькая.")
            return
        if self.s["mode"] == "select" and capture_after:
            self.once_region = region  # разовая область, в настройки не пишется
        else:
            self.s["region"] = region
            self.update_region_label()
            self.save_now()
        self.log.event("INFO", "REGION_SELECTED", width=region["width"], height=region["height"])
        if capture_after:
            self.root.after(250, self.grab_async)
        else:
            self.finish_idle("Область сохранена")

    def grab_async(self):
        s = dict(self.s)
        once, self.once_region = self.once_region, None
        pt = self.cursor

        def work():
            try:
                region = once or (s["region"] if s["mode"] == "region" else None)
                with core._default_factory() as g:
                    mons = list(g.monitors)
                monitor = core.resolve_monitor(s, mons, pt)
                self.events.put(("grabbed", core.grab(monitor, region)))
            except core.CaptureError as exc:
                self.events.put(("error", str(exc)))
            except Exception as exc:
                self.log.event("ERROR", "CAPTURE_FAILED", error=type(exc).__name__)
                self.events.put(("error", "Не удалось сделать снимок экрана."))
        threading.Thread(target=work, name="Grab", daemon=True).start()

    def on_grabbed(self, img):
        self.restore_windows()
        if self.cancel.is_set():
            self.finish_idle("Запрос отменён")
            return
        self.log.event("INFO", "CAPTURE_DONE", size=f"{img.width}x{img.height}")
        if self.s["confirm_before_send"] and not self.skip_confirm:
            self.confirm_dialog(img)
        else:
            self.begin_send(img)

    def confirm_dialog(self, img):
        host = urlparse(self.s["endpoint"]).hostname or self.s["endpoint"]
        win = tk.Toplevel(self.root)
        self.confirm_win = win
        win.title("Отправить снимок?")
        win.attributes("-topmost", True)
        thumb = img.copy()
        thumb.thumbnail((560, 340))
        photo = ImageTk.PhotoImage(thumb, master=win)
        lab = ttk.Label(win, image=photo)
        lab.image = photo
        lab.pack(padx=14, pady=(14, 8))
        ttk.Label(win, text=f"Снимок {img.width}×{img.height} будет отправлен на {host}.\n"
                            "Убедитесь, что на нём нет лишних личных данных.", justify="center").pack(padx=14)
        skip = tk.BooleanVar(master=win, value=False)
        ttk.Checkbutton(win, text="Не показывать в текущей сессии и сразу отправлять",
                        variable=skip).pack(padx=14, pady=(10, 0))
        row = ttk.Frame(win)
        row.pack(pady=12)
        done = {"v": False}

        def answer(ok):
            if done["v"]:
                return
            done["v"] = True
            skipped = bool(skip.get())
            win.destroy()
            self.confirm_win = None
            if ok:
                if skipped:
                    self.skip_confirm = True  # только до закрытия программы, в файл не пишется
                    self.log.event("INFO", "CONFIRM_SKIPPED_FOR_SESSION")
                self.begin_send(img)
            else:
                self.log.event("INFO", "SEND_DECLINED")
                self.finish_idle("Отправка отменена")
        ok_btn = ttk.Button(row, text="Отправить", command=lambda: answer(True))
        ok_btn.pack(side="left", padx=6)
        ttk.Button(row, text="Отмена", command=lambda: answer(False)).pack(side="left", padx=6)
        win.protocol("WM_DELETE_WINDOW", lambda: answer(False))
        win.bind("<Escape>", lambda e: answer(False))
        win.update_idletasks()
        win.geometry(f"+{(win.winfo_screenwidth() - win.winfo_width()) // 2}+{(win.winfo_screenheight() - win.winfo_height()) // 3}")
        win.focus_force()
        ok_btn.focus_set()
        self.status.set("Ожидает подтверждения отправки")

    # ---------- запрос ----------
    def begin_send(self, img):
        self.set_status("Запрос отправляется", ORANGE, cancel=True)
        threading.Thread(target=self.worker, args=(img, dict(self.s), self.key, self.cancel),
                         name="Request", daemon=True).start()

    def worker(self, img, s, key, cancel):
        log = self.log
        try:
            data, mime, meta = core.prepare_image(img, s["image_format"], s["max_side"], s["jpeg_quality"])
            log.event("INFO", "IMAGE_PREPARED", **meta)
            if s["save_images"]:
                d = core.config_dir() / "images"
                d.mkdir(exist_ok=True)
                p = d / f"{meta['image_id']}.{'png' if mime.endswith('png') else 'jpg'}"
                p.write_bytes(data)
                core.restrict(p)
                log.event("INFO", "IMAGE_SAVED", path=str(p))
            payload = core.build_payload(s, data, mime)
            log.event("INFO", "REQUEST_SENT", model=s["model"], endpoint=s["endpoint"], image_id=meta["image_id"])
            text = core.send_request(s, key, payload, cancel, log)
            log.event("INFO", "RESPONSE_OK", chars=len(text))
            self.events.put(("result", text))
        except core.Cancelled:
            log.event("INFO", "REQUEST_CANCELLED")
            self.events.put(("cancelled", None))
        except core.ApiError as exc:
            log.event("ERROR", "REQUEST_ERROR", status=exc.status or 0)
            self.events.put(("error", core.scrub(str(exc), key)))
        except Exception as exc:
            log.event("ERROR", "REQUEST_FAILED", error=type(exc).__name__)
            self.events.put(("error", "Не удалось подготовить или отправить запрос."))
        finally:
            del img

    def translate_worker(self, text, s, key, cancel):
        log = self.log
        try:
            payload = core.build_translate_payload(s, text)
            log.event("INFO", "TRANSLATE_SENT", model=s["model"], endpoint=s["endpoint"],
                      chars=len(text), language=s.get("translate_language", ""))
            result = core.send_request(s, key, payload, cancel, log)
            log.event("INFO", "TRANSLATE_OK", chars=len(result))
            self.events.put(("result", result))
        except core.Cancelled:
            log.event("INFO", "REQUEST_CANCELLED")
            self.events.put(("cancelled", None))
        except core.ApiError as exc:
            log.event("ERROR", "REQUEST_ERROR", status=exc.status or 0)
            self.events.put(("error", core.scrub(str(exc), key)))
        except Exception as exc:
            log.event("ERROR", "REQUEST_FAILED", error=type(exc).__name__)
            self.events.put(("error", "Не удалось отправить текст на перевод."))

    def cancel_request(self):
        if self.busy:
            self.cancel.set()
            self.log.event("INFO", "CANCEL_REQUESTED")
            self.status.set("Отмена…")
            if self.selector:
                self.selector.finish(None)

    def finish_idle(self, text):
        self.busy = False
        self.restore_windows()
        self.set_status(text, BLUE, 2500)

    def fail(self, text):
        self.busy = False
        self.restore_windows()
        self.log.event("ERROR", "OPERATION_FAILED", message=text)
        self.set_status("Ошибка", RED, 5000)
        self.show_popup(text, "Ошибка")

    # ---------- окно ответа ----------
    def show_popup(self, text, title="Ответ"):
        if self.closing:
            return
        if self.popup is None or not self.popup.winfo_exists():
            p = self.popup = tk.Toplevel(self.root)
            p.geometry("740x480")
            p.minsize(450, 280)
            p.protocol("WM_DELETE_WINDOW", p.withdraw)
            p.bind("<Escape>", lambda e: p.withdraw())
            outer = ttk.Frame(p, padding=14)
            outer.pack(fill="both", expand=True)
            bar = ttk.Frame(outer)
            bar.pack(fill="x", pady=(0, 8))
            ttk.Button(bar, text="Копировать всё", command=self.copy_answer).pack(side="left")
            ttk.Label(bar, text="  Esc: скрыть окно. «Последний ответ» в меню значка откроет его снова.").pack(side="left")
            area = ttk.Frame(outer)
            area.pack(fill="both", expand=True)
            sb = ttk.Scrollbar(area)
            sb.pack(side="right", fill="y")
            self.answer_text = tk.Text(area, wrap="word", font=("Segoe UI", 12), padx=12, pady=12,
                                       yscrollcommand=sb.set, exportselection=False)
            self.answer_text.pack(side="left", fill="both", expand=True)
            sb.configure(command=self.answer_text.yview)
            enable_clipboard(self.answer_text, readonly=True)
        self.popup.title(f"Вопрос с экрана: {title}")
        self.answer_text.configure(state="normal")
        self.answer_text.delete("1.0", "end")
        self.answer_text.insert("1.0", text)
        self.answer_text.configure(state="disabled")
        self.popup.deiconify()
        self.popup.lift()
        self.popup.attributes("-topmost", True)
        self.popup.after(800, lambda: self.popup.winfo_exists() and self.popup.attributes("-topmost", False))
        self.popup.focus_force()

    def copy_answer(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.last_answer or self.answer_text.get("1.0", "end-1c"))

    def show_last_answer(self):
        if self.last_answer:
            self.show_popup(self.last_answer)
        else:
            self.set_status("Ответов пока нет", BLUE, 2000)

    # ---------- цикл событий ----------
    def poll(self):
        if self.closing:
            return
        try:
            while True:
                name, data = self.events.get_nowait()
                if name == "capture":
                    self.start_capture()
                elif name == "translate":
                    self.start_translate()
                elif name == "settings":
                    self.show_settings()
                elif name == "answer":
                    self.show_last_answer()
                elif name == "quit":
                    self.quit()
                    return
                elif name == "grabbed":
                    self.on_grabbed(data)
                elif name == "result":
                    self.busy = False
                    self.last_answer = data
                    self.set_status("Готово", BLUE, 3000)
                    if not self.cancel.is_set():
                        self.show_popup(data)
                elif name == "error":
                    self.fail(data)
                elif name == "cancelled":
                    self.finish_idle("Запрос отменён")
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def quit(self):
        if self.closing:
            return
        self.closing = True
        self.cancel.set()
        self.hotkey.stop()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        if self.selector:
            self.selector.finish(None)
        try:
            self.save_now()
        finally:
            self.log.event("INFO", "APP_EXIT")
            self.log.finish()
            self.root.destroy()


def main():
    if not single_instance():
        msg = "Программа уже запущена. Её значок в области уведомлений (возможно, под стрелкой скрытых значков)."
        if IS_WIN:
            ctypes.windll.user32.MessageBoxW(None, msg, "Вопрос с экрана", 0x40)
        else:
            print(msg)
        return
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
