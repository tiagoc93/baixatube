import os
import sys
import threading
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QFrame, QFileDialog,
    QProgressBar, QTextEdit,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QColor, QPalette

try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False


# ── FFmpeg path setup (funciona tanto em dev quanto no .exe gerado) ───────────
def _setup_ffmpeg():
    """
    Adiciona ao PATH o diretório onde o ffmpeg.exe está localizado.
    - Em desenvolvimento: mesma pasta do script
    - Como .exe PyInstaller: pasta temporária _MEIPASS
    """
    if getattr(sys, "frozen", False):
        # Rodando como executável PyInstaller
        base = sys._MEIPASS
    else:
        # Rodando como script Python normal
        base = os.path.dirname(os.path.abspath(__file__))

    os.environ["PATH"] = base + os.pathsep + os.environ.get("PATH", "")

_setup_ffmpeg()


# ── Palette ───────────────────────────────────────────────────────────────────
BG      = "#0A0A0F"
CARD    = "#1A1A26"
BORDER  = "#2A2A3E"
ACCENT  = "#FF4D6D"
TEXT    = "#F0F0F8"
MUTED   = "#6B6B8A"
SUCCESS = "#00D68F"
WARNING = "#FFB347"
ERROR   = "#FF4D6D"


# ── Card ──────────────────────────────────────────────────────────────────────
class DownloadCard(QFrame):
    remove_requested = pyqtSignal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url    = url
        self.status = "idle"
        self._build()
        self._restyle("idle")

    def _build(self):
        self.setFixedHeight(82)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(10)

        self.icon_lbl = QLabel("○")
        self.icon_lbl.setFont(QFont("Segoe UI", 14))
        self.icon_lbl.setFixedWidth(22)

        col = QVBoxLayout()
        col.setSpacing(2)

        self.title_lbl = QLabel(self._clip(self.url, 72))
        self.title_lbl.setFont(QFont("Segoe UI Semibold", 10))
        self.title_lbl.setStyleSheet(f"color:{TEXT};")

        self.url_lbl = QLabel(self._clip(self.url, 85))
        self.url_lbl.setFont(QFont("Segoe UI", 9))
        self.url_lbl.setStyleSheet(f"color:{MUTED};")

        col.addWidget(self.title_lbl)
        col.addWidget(self.url_lbl)

        self.msg_lbl = QLabel("")
        self.msg_lbl.setFont(QFont("Segoe UI", 9))
        self.msg_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.msg_lbl.setMinimumWidth(90)

        self.rm_btn = QPushButton("✕")
        self.rm_btn.setFixedSize(24, 24)
        self.rm_btn.setCursor(Qt.PointingHandCursor)
        self.rm_btn.setStyleSheet(f"""
            QPushButton {{background:transparent;color:{MUTED};border:none;border-radius:12px;font-size:11px;}}
            QPushButton:hover {{background:{BORDER};color:{TEXT};}}
        """)
        self.rm_btn.clicked.connect(lambda: self.remove_requested.emit(self.url))

        row.addWidget(self.icon_lbl)
        row.addLayout(col, 1)
        row.addWidget(self.msg_lbl)
        row.addWidget(self.rm_btn)

        self.pbar = QProgressBar()
        self.pbar.setFixedHeight(3)
        self.pbar.setTextVisible(False)
        self.pbar.setRange(0, 100)
        self.pbar.setValue(0)
        self.pbar.hide()

        lay.addLayout(row)
        lay.addWidget(self.pbar)

    def ui_set_title(self, title: str):
        self.title_lbl.setText(self._clip(title, 72))

    def ui_set_progress(self, pct: int, msg: str):
        self.status = "progress"
        self.pbar.show()
        self.pbar.setValue(pct)
        self.msg_lbl.setText(msg)
        self.rm_btn.hide()
        self.icon_lbl.setText("↓")
        self._restyle("progress")

    def ui_set_done(self, msg: str):
        self.status = "done"
        self.pbar.setValue(100)
        self.pbar.show()
        self.msg_lbl.setText(msg)
        self.rm_btn.show()
        self.icon_lbl.setText("✓")
        self._restyle("done")

    def ui_set_error(self, msg: str):
        self.status = "error"
        self.pbar.hide()
        self.msg_lbl.setText(self._clip(msg, 45))
        self.rm_btn.show()
        self.icon_lbl.setText("✕")
        self._restyle("error")

    def _restyle(self, status: str):
        cols = {
            "idle":     (BORDER,  MUTED,   MUTED),
            "progress": (ACCENT,  ACCENT,  ACCENT),
            "done":     (SUCCESS, SUCCESS, SUCCESS),
            "error":    (ERROR,   ERROR,   ERROR),
        }
        bc, ic, mc = cols[status]
        self.setStyleSheet(f"""
            DownloadCard {{
                background:{CARD};
                border:1px solid {bc};
                border-radius:12px;
            }}
        """)
        self.icon_lbl.setStyleSheet(f"color:{ic};")
        self.msg_lbl.setStyleSheet(f"color:{mc};font-size:9pt;")
        self.pbar.setStyleSheet(f"""
            QProgressBar {{background:{BORDER};border-radius:2px;border:none;}}
            QProgressBar::chunk {{background:{bc};border-radius:2px;}}
        """)

    @staticmethod
    def _clip(t: str, n: int) -> str:
        return t if len(t) <= n else t[:n - 3] + "..."


# ── Main Window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    sig_title    = pyqtSignal(str, str)
    sig_progress = pyqtSignal(str, int, str)
    sig_done     = pyqtSignal(str, bool, str)
    sig_all_done = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.output_dir = os.path.expanduser("~/Downloads/mp3_downloads")
        self.cards: dict[str, DownloadCard] = {}

        self.sig_title.connect(self._on_title)
        self.sig_progress.connect(self._on_progress)
        self.sig_done.connect(self._on_done)
        self.sig_all_done.connect(self._on_all_done)

        self._build_ui()

    # ── Build ─────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.setWindowTitle("DownTube — YouTube para MP3")
        self.setMinimumSize(720, 560)
        self.resize(860, 660)
        self.setStyleSheet(f"QMainWindow{{background:{BG};}}")

        c = QWidget()
        c.setStyleSheet(f"background:{BG};")
        self.setCentralWidget(c)
        root = QVBoxLayout(c)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._header())
        root.addWidget(self._divider())
        root.addWidget(self._input_area())
        root.addWidget(self._divider())
        root.addWidget(self._list_area(), 1)
        root.addWidget(self._divider())
        root.addWidget(self._bottom_bar())

        if not YT_DLP_AVAILABLE:
            self._flash("⚠  yt-dlp não encontrado — pip install yt-dlp", WARNING)

    def _header(self):
        w = QWidget()
        w.setStyleSheet(f"background:{BG};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(32, 18, 32, 18)

        pill = QLabel("♪")
        pill.setAlignment(Qt.AlignCenter)
        pill.setFixedSize(38, 38)
        pill.setFont(QFont("Segoe UI", 16))
        pill.setStyleSheet(f"background:{ACCENT};color:{BG};border-radius:10px;")

        name = QLabel("DownTube")
        name.setFont(QFont("Segoe UI Black", 16, QFont.Black))
        name.setStyleSheet(f"color:{TEXT};")

        sub = QLabel("YouTube  →  MP3 Converter")
        sub.setFont(QFont("Segoe UI", 9))
        sub.setStyleSheet(f"color:{MUTED};")

        tcol = QVBoxLayout()
        tcol.setSpacing(1)
        tcol.addWidget(name)
        tcol.addWidget(sub)

        self.folder_btn = QPushButton()
        self.folder_btn.setCursor(Qt.PointingHandCursor)
        self.folder_btn.clicked.connect(self._pick_folder)
        self._refresh_folder_btn()

        lay.addWidget(pill)
        lay.addSpacing(10)
        lay.addLayout(tcol)
        lay.addStretch()
        lay.addWidget(self.folder_btn)
        return w

    def _input_area(self):
        w = QWidget()
        w.setStyleSheet(f"background:{BG};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(32, 20, 32, 20)
        lay.setSpacing(10)

        lbl = QLabel("URLS PARA DOWNLOAD")
        lbl.setFont(QFont("Segoe UI Semibold", 8))
        lbl.setStyleSheet(f"color:{MUTED};")

        row = QHBoxLayout()
        row.setSpacing(12)

        self.url_input = QTextEdit()
        self.url_input.setPlaceholderText("Cole aqui a URL do YouTube (uma por linha)...")
        self.url_input.setFixedHeight(90)
        self.url_input.setFont(QFont("Segoe UI", 10))
        self.url_input.setStyleSheet(f"""
            QTextEdit {{
                background:{CARD};color:{TEXT};
                border:1px solid {BORDER};border-radius:12px;
                padding:10px 14px;
            }}
            QTextEdit:focus {{border-color:{ACCENT};}}
        """)

        add_btn = QPushButton("＋  Adicionar")
        add_btn.setFixedSize(130, 90)
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setFont(QFont("Segoe UI Semibold", 11))
        add_btn.setStyleSheet(f"""
            QPushButton {{
                background:{ACCENT};color:{BG};
                border:none;border-radius:12px;font-weight:700;
            }}
            QPushButton:hover {{background:#e0445f;}}
            QPushButton:pressed {{background:#c0324a;}}
        """)
        add_btn.clicked.connect(self._add_urls)

        row.addWidget(self.url_input)
        row.addWidget(add_btn)
        lay.addWidget(lbl)
        lay.addLayout(row)
        return w

    def _list_area(self):
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(f"""
            QScrollArea {{background:{BG};border:none;}}
            QScrollBar:vertical {{background:{BG};width:6px;margin:0;}}
            QScrollBar::handle:vertical {{background:{BORDER};border-radius:3px;min-height:30px;}}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
        """)

        self.list_widget = QWidget()
        self.list_widget.setStyleSheet(f"background:{BG};")
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(32, 16, 32, 16)
        self.list_layout.setSpacing(8)
        self.list_layout.setAlignment(Qt.AlignTop)

        self.empty_w = QWidget()
        self.empty_w.setStyleSheet(f"background:{BG};")
        ev = QVBoxLayout(self.empty_w)
        ev.setAlignment(Qt.AlignCenter)
        for text, size, color in [
            ("♫", 42, BORDER),
            ("Nenhum download na fila", 12, MUTED),
            ("Cole uma URL acima e clique em Adicionar", 10, BORDER),
        ]:
            lbl = QLabel(text)
            lbl.setFont(QFont("Segoe UI", size))
            lbl.setStyleSheet(f"color:{color};")
            lbl.setAlignment(Qt.AlignCenter)
            ev.addWidget(lbl)

        self.list_layout.addWidget(self.empty_w)
        self.scroll.setWidget(self.list_widget)
        return self.scroll

    def _bottom_bar(self):
        w = QWidget()
        w.setStyleSheet(f"background:{BG};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(32, 14, 32, 14)

        self.status_lbl = QLabel("")
        self.status_lbl.setFont(QFont("Segoe UI", 9))
        self.status_lbl.setStyleSheet(f"color:{MUTED};")

        self.flash_lbl = QLabel("")
        self.flash_lbl.setFont(QFont("Segoe UI", 9))

        clear_btn = QPushButton("Limpar concluídos")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setFont(QFont("Segoe UI", 10))
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background:{CARD};color:{MUTED};
                border:1px solid {BORDER};border-radius:10px;
                padding:10px 20px;
            }}
            QPushButton:hover {{border-color:{MUTED};color:{TEXT};}}
        """)
        clear_btn.clicked.connect(self._clear_done)

        self.start_btn = QPushButton("▶   Iniciar Downloads")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setFont(QFont("Segoe UI Semibold", 11))
        self.start_btn.setStyleSheet(f"""
            QPushButton {{
                background:{ACCENT};color:{BG};
                border:none;border-radius:10px;
                padding:10px 28px;font-weight:700;
            }}
            QPushButton:hover {{background:#e0445f;}}
            QPushButton:pressed {{background:#c0324a;}}
            QPushButton:disabled {{background:{BORDER};color:{MUTED};}}
        """)
        self.start_btn.clicked.connect(self._start_downloads)

        lay.addWidget(self.status_lbl)
        lay.addSpacing(12)
        lay.addWidget(self.flash_lbl)
        lay.addStretch()
        lay.addWidget(clear_btn)
        lay.addSpacing(8)
        lay.addWidget(self.start_btn)
        return w

    def _divider(self):
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setFixedHeight(1)
        f.setStyleSheet(f"background:{BORDER};border:none;")
        return f

    # ── Signal slots ──────────────────────────────────────────────────────────
    def _on_title(self, url, title):
        card = self.cards.get(url)
        if card:
            card.ui_set_title(title)

    def _on_progress(self, url, pct, msg):
        card = self.cards.get(url)
        if card:
            card.ui_set_progress(pct, msg)
        self._update_status()

    def _on_done(self, url, ok, msg):
        card = self.cards.get(url)
        if card:
            card.ui_set_done(msg) if ok else card.ui_set_error(msg)
        self._update_status()

    def _on_all_done(self):
        self.start_btn.setEnabled(True)
        self._update_status()

    # ── Actions ───────────────────────────────────────────────────────────────
    def _pick_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Escolha a pasta de destino", self.output_dir
        )
        if path:
            self.output_dir = path
            self._refresh_folder_btn()

    def _refresh_folder_btn(self):
        home = os.path.expanduser("~")
        p = self.output_dir
        if p.startswith(home):
            p = "~" + p[len(home):]
        if len(p) > 38:
            p = "..." + p[-35:]
        self.folder_btn.setText(f"📁  {p}")
        self.folder_btn.setStyleSheet(f"""
            QPushButton {{
                background:{CARD};color:{MUTED};
                border:1px solid {BORDER};border-radius:8px;
                padding:6px 14px;font-size:10pt;font-family:'Segoe UI';
            }}
            QPushButton:hover {{border-color:{ACCENT};color:{TEXT};}}
        """)

    def _add_urls(self):
        raw  = self.url_input.toPlainText().strip()
        urls = [u.strip() for u in raw.splitlines() if u.strip()]
        if not urls:
            self._flash("Cole pelo menos uma URL válida.", WARNING)
            return

        added = 0
        for url in urls:
            if url not in self.cards:
                if self.empty_w.isVisible():
                    self.list_layout.removeWidget(self.empty_w)
                    self.empty_w.hide()

                card = DownloadCard(url)
                card.remove_requested.connect(self._remove_card)
                self.cards[url] = card
                self.list_layout.addWidget(card)
                added += 1

        self.url_input.clear()
        self._update_status()
        if added == 0:
            self._flash("Todas as URLs já estão na fila.", WARNING)

    def _remove_card(self, url):
        card = self.cards.pop(url, None)
        if card:
            self.list_layout.removeWidget(card)
            card.deleteLater()
        if not self.cards:
            self.list_layout.addWidget(self.empty_w)
            self.empty_w.show()
        self._update_status()

    def _clear_done(self):
        for url in [u for u, c in self.cards.items() if c.status in ("done", "error")]:
            self._remove_card(url)

    def _start_downloads(self):
        if not YT_DLP_AVAILABLE:
            self._flash("yt-dlp não instalado — pip install yt-dlp", ERROR)
            return
        pending = [url for url, c in self.cards.items() if c.status == "idle"]
        if not pending:
            self._flash("Nenhum item pendente na fila.", WARNING)
            return

        self.start_btn.setEnabled(False)

        def worker():
            for url in pending:
                self._download(url)
            self.sig_all_done.emit()

        threading.Thread(target=worker, daemon=True).start()

    def _download(self, url: str):
        def progress_hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
                dl    = d.get("downloaded_bytes", 0)
                pct   = int(min(dl / total * 100, 99))
                msg   = d.get("_percent_str", "").strip()
                self.sig_progress.emit(url, pct, msg)
            elif d["status"] == "finished":
                self.sig_progress.emit(url, 99, "Convertendo...")

        def pp_hook(d):
            if d.get("status") == "finished":
                fname = d.get("filename", "")
                if fname:
                    self.sig_title.emit(url, os.path.splitext(os.path.basename(fname))[0])

        opts = {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "outtmpl": os.path.join(self.output_dir, "%(title)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [pp_hook],
        }

        try:
            self.sig_progress.emit(url, 0, "Iniciando...")
            os.makedirs(self.output_dir, exist_ok=True)

            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            self.sig_done.emit(url, True, "Salvo como MP3 ✓")

        except Exception as e:
            self.sig_done.emit(url, False, str(e)[:80])

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _update_status(self):
        total   = len(self.cards)
        done    = sum(1 for c in self.cards.values() if c.status == "done")
        errors  = sum(1 for c in self.cards.values() if c.status == "error")
        pending = sum(1 for c in self.cards.values() if c.status in ("idle", "progress"))
        parts = []
        if total:   parts.append(f"{total} item{'s' if total != 1 else ''}")
        if done:    parts.append(f"{done} concluído{'s' if done != 1 else ''}")
        if errors:  parts.append(f"{errors} erro{'s' if errors != 1 else ''}")
        if pending: parts.append(f"{pending} pendente{'s' if pending != 1 else ''}")
        self.status_lbl.setText("  ·  ".join(parts))

    def _flash(self, msg: str, color: str = WARNING):
        self.flash_lbl.setStyleSheet(f"color:{color};font-size:9pt;")
        self.flash_lbl.setText(msg)
        QTimer.singleShot(4000, lambda: self.flash_lbl.setText(""))


# ── Entry ─────────────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window,     QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base,       QColor(CARD))
    pal.setColor(QPalette.Text,       QColor(TEXT))
    app.setPalette(pal)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()