# -*- coding: utf-8 -*-
"""Tkinter front end of the release .exe: pick the game folder, install or remove.

    python tools/installer_gui.py

All the work is done by installer.py (install / restore); this only runs it in a
worker thread and shows its printed progress in the log box.
"""
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import installer  # noqa: E402

TITLE = "Русификатор TCG Card Shop Simulator"


class QueueWriter:
    """File-like object for sys.stdout that forwards text to the UI thread."""

    def __init__(self, q):
        self.q = q

    def write(self, text):
        self.q.put(("log", text))

    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.busy = False
        self.data_dir = None

        root.title("%s %s" % (TITLE, installer.version()))
        root.minsize(560, 380)
        frm = ttk.Frame(root, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(4, weight=1)

        ttk.Label(frm, text="Папка игры (где лежит Card Shop Simulator.exe):").grid(
            row=0, column=0, columnspan=2, sticky="w")
        self.path = tk.StringVar()
        self.path.trace_add("write", lambda *_: self.on_path())
        ttk.Entry(frm, textvariable=self.path).grid(row=1, column=0, sticky="ew", pady=4)
        self.browse_btn = ttk.Button(frm, text="Обзор…", command=self.browse)
        self.browse_btn.grid(row=1, column=1, padx=(6, 0))

        self.info = ttk.Label(frm, text="", justify="left")
        self.info.grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 8))

        buttons = ttk.Frame(frm)
        buttons.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.install_btn = ttk.Button(buttons, text="Установить", command=self.install)
        self.install_btn.pack(side="left")
        self.remove_btn = ttk.Button(buttons, text="Удалить", command=self.remove)
        self.remove_btn.pack(side="left", padx=6)
        self.progress = ttk.Progressbar(buttons, mode="indeterminate", length=160)

        log_frame = ttk.Frame(frm)
        log_frame.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        self.log = tk.Text(log_frame, height=10, wrap="word", state="disabled",
                           relief="flat", background=root.cget("background"))
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        root.protocol("WM_DELETE_WINDOW", self.close)
        found = installer.detect_game()
        self.path.set(os.path.dirname(found) if found else "")
        self.poll()

    def close(self):
        if self.busy:
            messagebox.showwarning(TITLE, "Дождитесь окончания — файлы игры сейчас "
                                          "записываются.", parent=self.root)
            return
        self.root.destroy()

    # -------------------------------------------------------------- path
    def browse(self):
        start = self.path.get() if os.path.isdir(self.path.get()) else None
        chosen = filedialog.askdirectory(parent=self.root, initialdir=start,
                                         title="Папка TCG Card Shop Simulator")
        if chosen:
            self.path.set(os.path.normpath(chosen))

    def on_path(self):
        self.data_dir = installer.data_dir_of(self.path.get()) if self.path.get().strip() else None
        if not self.data_dir:
            self.info.configure(foreground="#b00020", text=(
                "Укажите папку игры." if not self.path.get().strip() else
                "Здесь нет папки %s." % installer.DATA_DIR_NAME))
        else:
            game_ver, made_for = installer.versions(self.data_dir)
            text = "Версия игры: %s, перевод сделан для %s." % (game_ver or "?", made_for or "?")
            mismatch = game_ver and made_for and game_ver != made_for
            if mismatch:
                text += "\n" + installer.VERSION_MISMATCH
            self.info.configure(foreground="#b06000" if mismatch else "", text=text)
        self.update_buttons()

    def update_buttons(self):
        ok = bool(self.data_dir) and not self.busy
        self.install_btn.configure(state="normal" if ok else "disabled")
        self.remove_btn.configure(
            state="normal" if ok and installer.has_backup(self.data_dir) else "disabled")
        self.browse_btn.configure(state="disabled" if self.busy else "normal")

    # -------------------------------------------------------------- actions
    def install(self):
        self.start("install")

    def remove(self):
        if messagebox.askyesno(TITLE, "Удалить перевод и вернуть оригинальные файлы игры?",
                               parent=self.root):
            self.start("restore")

    def start(self, action):
        self.busy = True
        self.update_buttons()
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.progress.pack(side="right")
        self.progress.start(12)
        threading.Thread(target=self.work, args=(action, self.data_dir), daemon=True).start()

    def work(self, action, data_dir):
        old = sys.stdout
        sys.stdout = QueueWriter(self.q)
        try:
            script_ids = installer.check_game(data_dir)
            if action == "install":
                installer.install(data_dir, script_ids)
                result = ("ok", "Перевод установлен.\n\n"
                                "Запустите игру и выберите «Русский» в Settings → Language.")
            else:
                installer.restore(data_dir)
                result = ("ok", "Перевод удалён, оригинальные файлы возвращены.")
        except installer.Fail as e:
            result = ("error", str(e))
        except Exception as e:  # noqa: BLE001 — show anything to the user
            import traceback
            traceback.print_exc(file=sys.stdout)
            result = ("error", "Непредвиденная ошибка: %s\n\n"
                               "Скопируйте текст из окна и приложите к issue на GitHub." % e)
        finally:
            sys.stdout = old
        self.q.put(("done", result))

    def poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log.configure(state="normal")
                    self.log.insert("end", payload)
                    self.log.see("end")
                    self.log.configure(state="disabled")
                else:
                    self.finish(*payload)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def finish(self, status, message):
        self.busy = False
        self.progress.stop()
        self.progress.pack_forget()
        self.update_buttons()
        if status == "ok":
            messagebox.showinfo(TITLE, message, parent=self.root)
        else:
            messagebox.showerror(TITLE, message, parent=self.root)


def main():
    if sys.platform == "win32":
        try:  # crisp text on scaled displays
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
