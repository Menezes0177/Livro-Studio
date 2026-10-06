import sys
import math
import os
import re
import shutil
import sqlite3
import json
import uuid
import urllib.request
from pathlib import Path

from PySide6.QtCore import (
    Qt,
    QSize,
    QRect,
    QPoint,
    QTimer,
    Signal,
    Property,
    QPropertyAnimation,
    QEasingCurve
)

from PySide6.QtGui import (
    QColor,
    QFont,
    QPixmap,
    QPainter,
    QPen,
    QMovie,
    QPainterPath,
    QIcon,
    QTextCursor,
    QTextCharFormat,
    QTextListFormat
)

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QTextBrowser,
    QFileDialog,
    QScrollArea,
    QMessageBox,
    QFrame,
    QSizePolicy,
    QStackedWidget,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QComboBox,
    QDialog,
    QDialogButtonBox
)

from database import Database
from online import OnlineService, OnlineConfigError, OnlineAuthError


# ============================================================
# CAMINHOS
# ============================================================

# Pasta do programa / recursos
# Em desenvolvimento: pasta do main.py
# Em PyInstaller: pasta temporária interna do executável
APP_DIR = Path(__file__).resolve().parent

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    RESOURCE_DIR = Path(sys._MEIPASS)
else:
    RESOURCE_DIR = APP_DIR

ASSETS_DIR = RESOURCE_DIR / "assets"
STYLE_PATH = RESOURCE_DIR / "style.qss"
ICON_PATH = RESOURCE_DIR / "livrostudio.ico"

# Dados do usuário ficam fora de Program Files.
# Isso permite que o aplicativo instalado grave livros normalmente.
LOCAL_APPDATA = Path(
    os.environ.get(
        "LOCALAPPDATA",
        Path.home() / "AppData" / "Local"
    )
)

USER_DATA_DIR = LOCAL_APPDATA / "LivroStudio"
COVERS_DIR = USER_DATA_DIR / "covers"
DB_PATH = USER_DATA_DIR / "livrostudio.db"

USER_DATA_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# V3.5 - CONFIGURAÇÕES VISUAIS
# ============================================================

SETTINGS_PATH = USER_DATA_DIR / "settings.json"
DEFAULT_WALLPAPER = ASSETS_DIR / "background.gif"


def load_settings():
    import json
    try:
        if SETTINGS_PATH.exists():
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        print(f"LivroStudio: falha ao ler configurações: {exc}")
    return {"theme": "dark", "wallpaper": "background.gif"}


def save_settings(data):
    import json
    try:
        SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"LivroStudio: falha ao salvar configurações: {exc}")


APP_SETTINGS = load_settings()


def available_wallpapers():
    if not ASSETS_DIR.exists():
        return []
    return sorted([x for x in ASSETS_DIR.iterdir() if x.is_file() and x.suffix.lower() in (".gif", ".png", ".jpg", ".jpeg", ".webp")], key=lambda x: x.name.lower())


def theme_stylesheet(theme):
    theme_file = RESOURCE_DIR / ("theme_light.qss" if theme == "light" else "theme_dark.qss")
    if theme_file.exists():
        return theme_file.read_text(encoding="utf-8")
    return ""


COVERS_DIR.mkdir(
    parents=True,
    exist_ok=True
)


def prepare_user_database():
    """
    Migra a biblioteca antiga de APP_DIR/data para a pasta
    permanente do usuário na primeira execução.

    Isso é importante porque a versão de desenvolvimento salvava
    o banco dentro da pasta do projeto, enquanto a versão instalada
    ficará normalmente em Program Files.
    """

    old_data_dir = APP_DIR / "data"
    old_db = old_data_dir / "livrostudio.db"

    if not old_db.exists() or DB_PATH.exists():
        return

    try:
        shutil.copy2(old_db, DB_PATH)

        old_covers = old_data_dir / "covers"

        if old_covers.exists():
            for source in old_covers.iterdir():
                if source.is_file():
                    destination = COVERS_DIR / source.name
                    if not destination.exists():
                        shutil.copy2(source, destination)

        # O banco antigo pode conter caminhos absolutos para a pasta
        # antiga. Atualizamos esses caminhos para a nova pasta.
        with sqlite3.connect(DB_PATH) as con:
            rows = con.execute(
                "SELECT id, cover_path FROM books"
            ).fetchall()

            for book_id, cover_path in rows:
                if not cover_path:
                    continue

                filename = Path(cover_path).name
                new_cover = COVERS_DIR / filename

                if new_cover.exists():
                    con.execute(
                        "UPDATE books SET cover_path=? WHERE id=?",
                        (str(new_cover), book_id)
                    )

            con.commit()

        print("LivroStudio: biblioteca antiga migrada com sucesso.")

    except Exception as exc:
        print(f"LivroStudio: falha ao migrar biblioteca: {exc}")


def delete_book_completely(db, book_id):
    """Exclui livro do SQLite e remove sua capa do computador."""

    book = db.get_book(book_id)

    if not book:
        return False

    cover_path = book.get("cover_path")

    with db.connect() as con:
        con.execute(
            "DELETE FROM books WHERE id=?",
            (book_id,)
        )
        con.commit()

    # Remove somente o arquivo da capa que pertence ao livro.
    if cover_path:
        try:
            cover = Path(cover_path)
            if cover.exists() and cover.is_file():
                cover.unlink()
        except OSError as exc:
            print(f"LivroStudio: não foi possível remover a capa: {exc}")

    return True


prepare_user_database()


# ============================================================
# BOTÃO
# ============================================================

class AnimatedButton(QPushButton):

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(46)
        self.setProperty("hovered", False)
        self.setProperty("pressed", False)

        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(0)
        self.shadow.setOffset(0, 3)
        self.shadow.setColor(QColor(0, 0, 0, 90))
        self.setGraphicsEffect(self.shadow)

        self.shadow_anim = QPropertyAnimation(self.shadow, b"blurRadius", self)
        self.shadow_anim.setDuration(170)
        self.shadow_anim.setEasingCurve(QEasingCurve.OutCubic)

    def _polish(self):
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _animate_shadow(self, target):
        self.shadow_anim.stop()
        self.shadow_anim.setStartValue(self.shadow.blurRadius())
        self.shadow_anim.setEndValue(target)
        self.shadow_anim.start()

    def enterEvent(self, event):
        self.setProperty("hovered", True)
        self._polish()
        self._animate_shadow(22)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setProperty("hovered", False)
        self.setProperty("pressed", False)
        self._polish()
        self._animate_shadow(0)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setProperty("pressed", True)
            self._polish()
            self.shadow.setOffset(0, 1)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.setProperty("pressed", False)
        self._polish()
        self.shadow.setOffset(0, 3)
        super().mouseReleaseEvent(event)


# ============================================================
# PÁGINA BASE
# ============================================================

class Page(QWidget):

    def __init__(self):

        super().__init__()

        self.setAttribute(
            Qt.WA_StyledBackground,
            True
        )


# ============================================================
# HOME
# ============================================================

class HomePage(Page):

    create_requested = Signal()
    library_requested = Signal()
    explorer_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("homePage")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        page = QWidget()
        page.setObjectName("homeContent")
        content = QVBoxLayout(page)
        content.setContentsMargins(58, 52, 58, 46)
        content.setSpacing(0)

        kicker = QLabel("SEU ESPAÇO CRIATIVO")
        kicker.setObjectName("homeKicker")
        content.addWidget(kicker)
        content.addSpacing(12)

        title = QLabel("Suas histórias<br><span>começam aqui.</span>")
        title.setObjectName("homeTitle")
        title.setTextFormat(Qt.RichText)
        title.setWordWrap(True)
        content.addWidget(title)
        content.addSpacing(13)

        subtitle = QLabel("Crie, organize e compartilhe suas histórias em um só lugar.")
        subtitle.setObjectName("homeSubtitle")
        content.addWidget(subtitle)
        content.addSpacing(38)

        section = QLabel("COMECE POR AQUI")
        section.setObjectName("homeSection")
        content.addWidget(section)
        content.addSpacing(12)

        cards = QHBoxLayout()
        cards.setSpacing(18)
        self.library_card = self._make_card("BIBLIOTECA", "Seus livros", "Continue lendo ou organize suas histórias.", self.library_requested)
        self.explorer_card = self._make_card("EXPLORER", "Descubra histórias", "Encontre livros publicados pela comunidade.", self.explorer_requested)
        self.create_card = self._make_card("CRIAR", "Nova história", "Comece uma nova obra do zero.", self.create_requested)
        cards.addWidget(self.library_card, 1)
        cards.addWidget(self.explorer_card, 1)
        cards.addWidget(self.create_card, 1)
        content.addLayout(cards)
        content.addSpacing(34)

        tip = QFrame()
        tip.setObjectName("homeTip")
        tip_layout = QHBoxLayout(tip)
        tip_layout.setContentsMargins(18, 16, 18, 16)
        tip_layout.setSpacing(14)
        tip_icon = QLabel()
        tip_icon.setObjectName("homeTipIcon")
        tip_icon.setAlignment(Qt.AlignCenter)
        tip_icon.setFixedSize(46, 46)

        png_path = ASSETS_DIR / "LivroStudioPng.png"

        pixmap = QPixmap(str(png_path))

        if not pixmap.isNull():
            tip_icon.setPixmap(
                pixmap.scaled(
                    46,
                    46,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
        )
        tip_layout.addWidget(tip_icon)
        tip_text = QVBoxLayout()
        tip_title = QLabel("Seu espaço, suas histórias.")
        tip_title.setObjectName("homeTipTitle")
        tip_desc = QLabel("Tudo fica salvo localmente. Quando estiver online, você também pode publicar no Explorer.")
        tip_desc.setObjectName("homeTipText")
        tip_desc.setWordWrap(True)
        tip_text.addWidget(tip_title)
        tip_text.addWidget(tip_desc)
        tip_layout.addLayout(tip_text, 1)
        content.addWidget(tip)
        content.addStretch(1)

        footer = QHBoxLayout()
        footer.setContentsMargins(2, 18, 2, 0)
        status = QLabel("LIVROSTUDIO  •  CRIE. LEIA. PUBLIQUE.")
        status.setObjectName("homeStatus")
        footer.addWidget(status)
        footer.addStretch()
        version = QLabel("v3.5")
        version.setObjectName("homeVersion")
        footer.addWidget(version)
        content.addLayout(footer)
        root.addWidget(page, 1)

    def _make_card(self, label, title, description, signal):
        card = AnimatedButton("")
        card.setObjectName("homeActionCard")
        card.setMinimumHeight(172)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(7)

        top = QLabel(label)
        top.setObjectName("homeCardTag")
        layout.addWidget(top)
        title_label = QLabel(title)
        title_label.setObjectName("homeCardTitle")
        layout.addWidget(title_label)
        desc = QLabel(description)
        desc.setObjectName("homeCardDescription")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        layout.addStretch()
        arrow = QLabel("ABRIR  →")
        arrow.setObjectName("homeCardArrow")
        layout.addWidget(arrow)
        card.clicked.connect(signal.emit)
        return card

    def set_wallpaper(self, path):
        return

    def resizeEvent(self, event):
        super().resizeEvent(event)


# ============================================================
# SELETOR DE CAPA
# ============================================================

class CoverPicker(QFrame):

    def __init__(self):

        super().__init__()

        self.cover_path = None

        self.setObjectName(
            "coverPicker"
        )

        self.setCursor(
            Qt.PointingHandCursor
        )

        self.setMinimumSize(
            250,
            390
        )

        self.setMaximumSize(
            290,
            440
        )

        layout = QVBoxLayout(
            self
        )

        layout.setContentsMargins(
            14,
            14,
            14,
            14
        )

        self.image = QLabel(
            "CAPA DO LIVRO\n\n"
            "Clique para escolher"
        )

        self.image.setObjectName(
            "coverPreview"
        )

        self.image.setAlignment(
            Qt.AlignCenter
        )

        self.image.setWordWrap(
            True
        )

        layout.addWidget(
            self.image
        )

        hint = QLabel(
            "PNG • JPG • WEBP"
        )

        hint.setObjectName(
            "smallHint"
        )

        hint.setAlignment(
            Qt.AlignCenter
        )

        layout.addWidget(
            hint
        )

    def mousePressEvent(
        self,
        event
    ):

        if event.button() != Qt.LeftButton:

            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Escolher capa",
            "",
            "Imagens (*.png *.jpg *.jpeg *.webp)"
        )

        if path:

            self.set_cover(
                path
            )

    def set_cover(
        self,
        path
    ):

        self.cover_path = path

        pix = QPixmap(
            path
        )

        if pix.isNull():

            return

        self.image.setPixmap(
            pix.scaled(
                QSize(
                    240,
                    340
                ),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
        )

        self.image.setText(
            ""
        )


# ============================================================
# EDITOR DE TEXTO RICO
# ============================================================

class RichBookEditor(QTextEdit):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(True)
        self.setUndoRedoEnabled(True)

    def _apply_block_heading(self, level):
        cursor = self.textCursor()
        block = cursor.block()
        text = block.text()
        prefix = "#" * level + " "
        if not text.startswith(prefix):
            return
        start = block.position()
        # Remove the markdown prefix.
        c = QTextCursor(self.document())
        c.setPosition(start)
        c.setPosition(start + len(prefix), QTextCursor.KeepAnchor)
        c.removeSelectedText()
        # Format the whole paragraph like a heading.
        c = QTextCursor(self.document())
        c.setPosition(start)
        c.setPosition(start + len(text) - len(prefix), QTextCursor.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Bold)
        fmt.setFontPointSize({1: 29, 2: 24, 3: 20}[level])
        c.mergeCharFormat(fmt)
        self.setTextCursor(QTextCursor(self.document()))
        cur = self.textCursor()
        cur.setPosition(start + max(0, len(text) - len(prefix)))
        self.setTextCursor(cur)

    def _convert_bold_markdown(self):
        cursor = self.textCursor()
        block = cursor.block()
        block_text = block.text()
        pos_in_block = cursor.position() - block.position()
        if pos_in_block < 2 or not block_text[:pos_in_block].endswith("**"):
            return

        end_marker = pos_in_block - 2
        start_marker = block_text.rfind("**", 0, end_marker)
        if start_marker < 0 or end_marker <= start_marker + 2:
            return

        global_start = block.position() + start_marker
        global_end = block.position() + end_marker + 2
        # Remove closing marker first.
        c = QTextCursor(self.document())
        c.setPosition(global_end - 2)
        c.setPosition(global_end, QTextCursor.KeepAnchor)
        c.removeSelectedText()
        # Remove opening marker.
        c = QTextCursor(self.document())
        c.setPosition(global_start)
        c.setPosition(global_start + 2, QTextCursor.KeepAnchor)
        c.removeSelectedText()
        # Apply bold to the text between the markers.
        inner_start = global_start
        inner_end = global_end - 2 - 2
        c = QTextCursor(self.document())
        c.setPosition(inner_start)
        c.setPosition(inner_end, QTextCursor.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Bold)
        c.mergeCharFormat(fmt)
        c.clearSelection()
        c.setPosition(inner_end)
        self.setTextCursor(c)

    def keyPressEvent(self, event):
        super().keyPressEvent(event)

        if event.key() == Qt.Key_Space:
            text = self.textCursor().block().text()
            for level in (3, 2, 1):
                if text.startswith("#" * level + " ") and len(text) == level + 1:
                    self._apply_block_heading(level)
                    break

        elif event.key() == Qt.Key_Asterisk:
            self._convert_bold_markdown()


# ============================================================
# EDITOR
# ============================================================

class EditorPage(Page):

    back_requested = Signal()
    saved = Signal(int)

    def __init__(
        self,
        db
    ):

        super().__init__()
        self.setObjectName("editorPage")

        self.db = db

        root = QVBoxLayout(
            self
        )

        root.setContentsMargins(
            35,
            25,
            35,
            30
        )

        # ----------------------------------------------------
        # TOPO
        # ----------------------------------------------------

        top = QHBoxLayout()

        back = QPushButton(
            "←  INÍCIO"
        )

        back.setObjectName(
            "textButton"
        )

        back.clicked.connect(
            self.back_requested.emit
        )

        title = QLabel(
            "Criar novo livro"
        )

        title.setObjectName(
            "pageTitle"
        )

        top.addWidget(
            back
        )

        top.addStretch()

        top.addWidget(
            title
        )

        top.addStretch()

        top.addSpacing(
            80
        )

        root.addLayout(
            top
        )

        # ----------------------------------------------------
        # ÁREA
        # ----------------------------------------------------

        content = QHBoxLayout()

        content.setSpacing(
            30
        )

        # ----------------------------------------------------
        # ESQUERDA
        # ----------------------------------------------------

        left = QVBoxLayout()

        left.setSpacing(
            14
        )

        self.cover = CoverPicker()

        left.addWidget(
            self.cover,
            alignment=Qt.AlignHCenter
        )

        self.title_input = QLineEdit()

        self.title_input.setPlaceholderText(
            "Nome da história..."
        )

        self.title_input.setObjectName(
            "titleInput"
        )

        left.addWidget(
            self.title_input
        )

        self.author_input = QLineEdit()
        self.author_input.setPlaceholderText("Autor / nome de exibição...")
        self.author_input.setObjectName("authorInput")
        left.addWidget(self.author_input)

        self.synopsis_input = QTextEdit()
        self.synopsis_input.setPlaceholderText("Sinopse curta para o Explorer...")
        self.synopsis_input.setObjectName("synopsisInput")
        self.synopsis_input.setFixedHeight(105)
        left.addWidget(self.synopsis_input)

        self.visibility_combo = QComboBox()
        self.visibility_combo.setObjectName("visibilityCombo")
        self.visibility_combo.addItem("Privado", "private")
        self.visibility_combo.addItem("Público — Explorer", "public")
        self.visibility_combo.addItem("Não listado", "unlisted")
        left.addWidget(self.visibility_combo)

        self.send_btn = AnimatedButton(
            "PUBLICAR LIVRO   →"
        )

        self.send_btn.clicked.connect(
            self.publish
        )

        left.addWidget(
            self.send_btn
        )

        left_panel = QWidget()
        left_panel.setLayout(left)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setWidget(left_panel)
        content.addWidget(left_scroll, 0)

        # ----------------------------------------------------
        # EDITOR RICO + BARRA DE FORMATAÇÃO
        # ----------------------------------------------------

        editor_column = QVBoxLayout()
        editor_column.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        def tool_button(text, tooltip, callback, object_name="editorTool"):
            btn = QPushButton(text)
            btn.setObjectName(object_name)
            btn.setToolTip(tooltip)
            btn.setFixedHeight(38)
            btn.clicked.connect(callback)
            toolbar.addWidget(btn)
            return btn

        tool_button("B", "Negrito (Ctrl+B)", self.toggle_bold)
        tool_button("I", "Itálico (Ctrl+I)", self.toggle_italic)
        tool_button("U", "Sublinhado (Ctrl+U)", self.toggle_underline)

        size_combo = QComboBox()
        size_combo.setObjectName("editorSizeCombo")
        size_combo.addItems(["12", "14", "16", "18", "20", "24", "28", "32"])
        size_combo.setCurrentText("18")
        size_combo.setToolTip("Tamanho da letra")
        size_combo.setFixedWidth(78)
        size_combo.currentTextChanged.connect(self.change_font_size)
        toolbar.addWidget(size_combo)
        self.size_combo = size_combo

        tool_button("H1", "Título grande", lambda: self.apply_heading(1))
        tool_button("H2", "Título médio", lambda: self.apply_heading(2))
        tool_button("• Lista", "Lista com marcadores", self.toggle_bullets)
        tool_button("↶", "Desfazer", self.editor_undo)
        tool_button("↷", "Refazer", self.editor_redo)
        toolbar.addStretch()

        editor_column.addLayout(toolbar)

        self.editor = RichBookEditor()
        self.editor.setObjectName("bookEditor")
        self.editor.setPlaceholderText(
            "Comece a escrever sua história...\n\n"
            "Dicas: # Título grande   •   **texto em negrito**\n"
            "Você também pode selecionar um trecho e usar a barra de ferramentas."
        )
        self.editor.setTabStopDistance(28)
        editor_column.addWidget(self.editor, 1)
        content.addLayout(editor_column, 1)

        root.addLayout(
            content,
            1
        )

    # ========================================================
    # FERRAMENTAS DO EDITOR
    # ========================================================

    def merge_format(self, fmt):
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.WordUnderCursor)
        cursor.mergeCharFormat(fmt)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def toggle_bold(self):
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Normal if self.editor.fontWeight() == QFont.Bold else QFont.Bold)
        self.merge_format(fmt)

    def toggle_italic(self):
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.editor.fontItalic())
        self.merge_format(fmt)

    def toggle_underline(self):
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self.editor.fontUnderline())
        self.merge_format(fmt)

    def change_font_size(self, value):
        try:
            size = float(value)
        except ValueError:
            return
        fmt = QTextCharFormat()
        fmt.setFontPointSize(size)
        self.merge_format(fmt)

    def apply_heading(self, level):
        cursor = self.editor.textCursor()
        cursor.select(QTextCursor.BlockUnderCursor)
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Bold)
        fmt.setFontPointSize({1: 29, 2: 24, 3: 20}.get(level, 18))
        cursor.mergeCharFormat(fmt)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def toggle_bullets(self):
        self.editor.textCursor().createList(QTextListFormat.ListDisc)
        self.editor.setFocus()

    def editor_undo(self):
        self.editor.undo()
        self.editor.setFocus()

    def editor_redo(self):
        self.editor.redo()
        self.editor.setFocus()

    def reset(self):

        self.title_input.clear()
        self.author_input.clear()
        self.synopsis_input.clear()
        self.visibility_combo.setCurrentIndex(0)

        self.editor.clear()

        self.cover.cover_path = None

        self.cover.image.clear()

        self.cover.image.setText(
            "CAPA DO LIVRO\n\n"
            "Clique para escolher"
        )

    def publish(self):

        title = (
            self.title_input
            .text()
            .strip()
        )

        text = self.editor.toHtml().strip()
        plain_text = self.editor.toPlainText().strip()
        author = self.author_input.text().strip() or "Você"
        synopsis = self.synopsis_input.toPlainText().strip()
        visibility = self.visibility_combo.currentData() or "private"

        if not title:

            QMessageBox.warning(
                self,
                "Título ausente",
                "Digite o título do livro."
            )

            return

        if not plain_text:

            QMessageBox.warning(
                self,
                "Livro vazio",
                "Escreva alguma coisa antes de publicar."
            )

            return

        if not self.cover.cover_path:

            QMessageBox.warning(
                self,
                "Capa ausente",
                "Escolha uma capa para o livro."
            )

            return

        try:

            book_id = self.db.create_book(
                title=title,
                text=text,
                cover_source=Path(self.cover.cover_path),
                synopsis=synopsis,
                author=author,
                visibility=visibility
            )

        except Exception as exc:

            QMessageBox.critical(
                self,
                "Erro",
                str(exc)
            )

            return

        if visibility == "public":
            try:
                if not self.window().online.configured or not self.window().online.current_user():
                    QMessageBox.warning(self, "Conta necessária", "Entre em uma conta online antes de publicar um livro no Explorer.")
                    return
                cover_url = self.window().online.publish_book(
                    title=title,
                    text=text,
                    synopsis=synopsis,
                    author=author,
                    cover_source=Path(self.cover.cover_path),
                )
            except Exception as exc:
                QMessageBox.critical(self, "Erro no Explorer", f"O livro foi salvo localmente, mas não foi publicado online.\n\n{exc}")
                return

        self.reset()

        self.saved.emit(
            book_id
        )


# ============================================================
# CARROSSEL
# ============================================================

class CarouselWidget(QWidget):

    book_clicked = Signal(int)

    def __init__(self):

        super().__init__()

        self.books = []

        self.pixmaps = {}

        self.current_index = 0

        self._position = 0.0

        self.target_position = 0.0

        self.mouse_x = 0.0

        self.mouse_y = 0.0

        self.setMouseTracking(
            True
        )

        self.setFocusPolicy(
            Qt.StrongFocus
        )

        # ----------------------------------------------------
        # ANIMAÇÃO
        # ----------------------------------------------------

        self.timer = QTimer(
            self
        )

        self.timer.setInterval(
            16
        )

        self.timer.timeout.connect(
            self.animate
        )

        self.timer.start()

    # ========================================================
    # POSITION
    # ========================================================

    def get_position(self):

        return self._position

    def set_position(
        self,
        value
    ):

        self._position = value

        self.update()

    position = Property(
        float,
        get_position,
        set_position
    )

    # ========================================================
    # LIVROS
    # ========================================================

    def set_books(
        self,
        books
    ):

        self.books = list(
            books or []
        )

        self.pixmaps.clear()

        for book in self.books:

            path = book.get(
                "cover_path"
            )

            if path:

                pix = QPixmap(
                    path
                )

                if not pix.isNull():

                    self.pixmaps[
                        book["id"]
                    ] = pix

        if not self.books:

            self.current_index = 0

            self._position = 0

            self.target_position = 0

            self.update()

            return

        self.current_index = min(
            self.current_index,
            len(self.books) - 1
        )

        self.target_position = float(
            self.current_index
        )

        self.update()

    # ========================================================
    # ANIMAÇÃO
    # ========================================================

    def animate(self):

        difference = (
            self.target_position
            - self._position
        )

        if abs(difference) < 0.001:

            self._position = (
                self.target_position
            )

        else:

            self._position += (
                difference * 0.16
            )

        self.update()

    # ========================================================
    # NAVEGAÇÃO
    # ========================================================

    def go_to(
        self,
        index
    ):

        if not self.books:

            return

        index = max(
            0,
            min(
                index,
                len(self.books) - 1
            )
        )

        self.current_index = index

        self.target_position = float(
            index
        )

        self.setFocus()

    def previous(self):

        self.go_to(
            self.current_index - 1
        )

    def next(self):

        self.go_to(
            self.current_index + 1
        )

    # ========================================================
    # TECLADO
    # ========================================================

    def keyPressEvent(
        self,
        event
    ):

        if event.key() == Qt.Key_Left:

            self.previous()

            return

        if event.key() == Qt.Key_Right:

            self.next()

            return

        if event.key() in (
            Qt.Key_Return,
            Qt.Key_Enter,
            Qt.Key_Space
        ):

            self.open_current()

            return

        super().keyPressEvent(
            event
        )

    # ========================================================
    # MOUSE
    # ========================================================

    def mouseMoveEvent(
        self,
        event
    ):

        self.mouse_x = (
            event.position().x()
        )

        self.mouse_y = (
            event.position().y()
        )

        self.update()

    def leaveEvent(
        self,
        event
    ):

        self.mouse_x = (
            self.width() / 2
        )

        self.mouse_y = (
            self.height() / 2
        )

        self.update()

    def wheelEvent(
        self,
        event
    ):

        if event.angleDelta().y() > 0:

            self.previous()

        else:

            self.next()

        event.accept()

    def mousePressEvent(
        self,
        event
    ):

        if event.button() != Qt.LeftButton:

            return

        if not self.books:

            return

        center_x = (
            self.width() / 2
        )

        distance = (
            event.position().x()
            - center_x
        )

        if abs(distance) < 190:

            self.open_current()

        elif distance < 0:

            self.previous()

        else:

            self.next()

    # ========================================================
    # ABRIR
    # ========================================================

    def open_current(self):

        if not self.books:

            return

        book = self.books[
            self.current_index
        ]

        self.book_clicked.emit(
            book["id"]
        )

    # ========================================================
    # PAINT
    # ========================================================

    def paintEvent(
        self,
        event
    ):

        painter = QPainter(self)
        if not painter.isActive():
            return

        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        if not self.books:
            painter.setPen(QColor("#888888"))
            painter.setFont(QFont("Segoe UI", 15))
            painter.drawText(
                self.rect(),
                Qt.AlignCenter,
                "SUA BIBLIOTECA ESTÁ VAZIA\n\nCrie seu primeiro livro."
            )
            painter.end()
            return

        center_x = self.width() // 2
        center_y = self.height() // 2
        base_w = 245
        base_h = 365
        current = self._position

        first = max(0, int(math.floor(current)) - 3)
        last = min(len(self.books), int(math.ceil(current)) + 4)
        cards = []

        for index in range(first, last):
            distance = index - current
            absolute = abs(distance)
            scale = max(0.70, 1.0 - absolute * 0.10)
            width = int(base_w * scale)
            height = int(base_h * scale)
            x = int(center_x + distance * 285 - width / 2)
            y = int(center_y - height / 2)
            cards.append((index, distance, absolute, QRect(x, y, width, height)))

        cards.sort(key=lambda item: item[2], reverse=True)
        is_dark = APP_SETTINGS.get("theme", "dark") != "light"

        for index, distance, absolute, rect in cards:
            book = self.books[index]
            pix = self.pixmaps.get(book["id"])
            if pix is None:
                continue

            is_center = absolute < 0.12
            hover_strength = 0.0
            if is_center:
                dx = self.mouse_x - center_x
                dy = self.mouse_y - center_y
                radius = max(1.0, min(self.width(), self.height()) * 0.62)
                hover_strength = max(0.0, min(1.0, 1.0 - math.hypot(dx, dy) / radius))

            # Efeito novo: a capa permanece estável. O mouse apenas
            # aumenta discretamente a escala e a elevação, evitando
            # o parallax estranho da versão anterior.
            lift = int(10 * hover_strength) if is_center else 0
            scale_boost = 1.0 + (0.025 * hover_strength if is_center else 0.0)
            if scale_boost != 1.0:
                new_w = int(rect.width() * scale_boost)
                new_h = int(rect.height() * scale_boost)
                draw_rect = QRect(
                    rect.center().x() - new_w // 2,
                    rect.center().y() - new_h // 2 - lift,
                    new_w,
                    new_h
                )
            else:
                draw_rect = rect

            # sombra em duas camadas para profundidade suave
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 55 if is_dark else 35))
            shadow1 = draw_rect.adjusted(7, 12, 7, 14)
            painter.drawRoundedRect(shadow1, 24, 24)
            painter.setBrush(QColor(0, 0, 0, 35 if is_dark else 20))
            shadow2 = draw_rect.adjusted(3, 6, 3, 8)
            painter.drawRoundedRect(shadow2, 22, 22)

            opacity = max(0.50, 1.0 - absolute * 0.15)
            painter.setOpacity(opacity)

            path = QPainterPath()
            path.addRoundedRect(draw_rect, 20, 20)
            painter.save()
            painter.setClipPath(path)

            scaled = pix.scaled(draw_rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            image_rect = QRect(
                draw_rect.center().x() - scaled.width() // 2,
                draw_rect.center().y() - scaled.height() // 2,
                scaled.width(),
                scaled.height()
            )
            painter.drawPixmap(image_rect, scaled)
            painter.restore()
            painter.setOpacity(1.0)

            # Borda refinada, apenas no item em foco.
            if is_center:
                border_alpha = int(75 + 100 * hover_strength)
                border = QColor(255, 255, 255, border_alpha) if is_dark else QColor(25, 25, 25, border_alpha)
                painter.setPen(QPen(border, 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(draw_rect, 20, 20)

                if hover_strength > 0.05:
                    glow = QColor(255, 255, 255, int(16 * hover_strength)) if is_dark else QColor(0, 0, 0, int(10 * hover_strength))
                    painter.setPen(QPen(glow, 5))
                    painter.drawRoundedRect(draw_rect.adjusted(2, 2, -2, -2), 19, 19)

        painter.end()

# ============================================================
# BIBLIOTECA
# ============================================================

class LibraryPage(Page):

    back_requested = Signal()
    book_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(
        self,
        db
    ):

        super().__init__()
        self.setObjectName("libraryPage")

        self.db = db

        root = QVBoxLayout(
            self
        )

        root.setContentsMargins(
            35,
            25,
            35,
            25
        )

        root.setSpacing(
            8
        )

        # ----------------------------------------------------
        # CABEÇALHO
        # ----------------------------------------------------

        top = QHBoxLayout()

        back = QPushButton(
            "←  INÍCIO"
        )

        back.setObjectName(
            "textButton"
        )

        back.clicked.connect(
            self.back_requested.emit
        )

        self.title = QLabel(
            "Minha Biblioteca"
        )

        self.title.setObjectName(
            "pageTitle"
        )

        self.counter = QLabel(
            "0 livros"
        )

        self.counter.setObjectName(
            "counter"
        )

        top.addWidget(
            back
        )

        top.addStretch()

        top.addWidget(
            self.title
        )

        top.addStretch()

        top.addWidget(
            self.counter
        )

        root.addLayout(
            top
        )

        # ----------------------------------------------------
        # SUBTÍTULO
        # ----------------------------------------------------

        self.hint = QLabel(
            "← →  navegar     •     ENTER  abrir     •     clique  selecionar"
        )

        self.hint.setObjectName(
            "smallHint"
        )

        self.hint.setAlignment(
            Qt.AlignCenter
        )

        root.addWidget(
            self.hint
        )

        self.search = QLineEdit()
        self.search.setObjectName("searchInput")
        self.search.setPlaceholderText("🔎  Pesquisar na biblioteca...")
        self.search.textChanged.connect(self.apply_search)
        root.addWidget(self.search)

        # ----------------------------------------------------
        # CARROSSEL
        # ----------------------------------------------------

        self.carousel = CarouselWidget()

        self.carousel.book_clicked.connect(
            self.book_requested.emit
        )

        root.addWidget(
            self.carousel,
            1
        )

        # ----------------------------------------------------
        # BOTÕES INFERIORES
        # ----------------------------------------------------

        bottom = QHBoxLayout()

        self.delete_btn = QPushButton(
            "🗑  EXCLUIR LIVRO"
        )

        self.delete_btn.setObjectName(
            "deleteButton"
        )

        self.delete_btn.setCursor(
            Qt.PointingHandCursor
        )

        self.delete_btn.clicked.connect(
            self.delete_current
        )

        bottom.addStretch()

        bottom.addWidget(
            self.delete_btn
        )

        bottom.addStretch()

        root.addLayout(
            bottom
        )

    # ========================================================
    # REFRESH
    # ========================================================

    def refresh(self):

        books = self.db.get_books()
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)

        self.carousel.set_books(
            books
        )

        if books:

            if len(books) == 1:

                self.counter.setText(
                    "1 livro"
                )

            else:

                self.counter.setText(
                    f"{len(books)} livros"
                )

            self.delete_btn.setEnabled(
                True
            )

            self.hint.setVisible(
                True
            )

        else:

            self.counter.setText(
                "0 livros"
            )

            self.delete_btn.setEnabled(
                False
            )

            self.hint.setVisible(
                False
            )

    def apply_search(self, text):
        query = text.strip().lower()
        books = self.db.get_books()
        if query:
            books = [b for b in books if query in b.get("title", "").lower() or query in b.get("author", "").lower()]
        self.carousel.set_books(books)
        count = len(books)
        self.counter.setText(f"{count} livro" if count == 1 else f"{count} livros")
        self.delete_btn.setEnabled(bool(books))
        self.hint.setVisible(bool(books))

    # ========================================================
    # DELETAR
    # ========================================================

    def delete_current(self):

        if not self.carousel.books:

            return

        book = self.carousel.books[
            self.carousel.current_index
        ]

        title = book[
            "title"
        ]

        answer = QMessageBox.question(
            self,
            "Excluir livro",
            (
                f'Você realmente quer excluir "{title}"?\n\n'
                "Essa ação apagará o livro do banco de dados "
                "e a capa do computador.\n\n"
                "Essa ação NÃO pode ser desfeita."
            ),
            QMessageBox.Yes
            | QMessageBox.No,
            QMessageBox.No
        )

        if answer != QMessageBox.Yes:

            return

        book_id = book[
            "id"
        ]

        try:

            success = delete_book_completely(
                self.db,
                book_id
            )

            if not success:

                QMessageBox.warning(
                    self,
                    "Erro",
                    "O livro não foi encontrado."
                )

                return

        except Exception as exc:

            QMessageBox.critical(
                self,
                "Erro ao excluir",
                str(exc)
            )

            return

        # Atualiza
        self.refresh()


# ============================================================
# EXPLORER V3.5
# ============================================================

class ExplorerCard(AnimatedButton):
    open_requested = Signal(str)
    add_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(self, book, can_remove=False, parent=None):
        super().__init__("", parent)
        self.book = book
        self.setObjectName("explorerCard")
        self.setMinimumHeight(485)
        self.setMaximumHeight(510)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        cover = QLabel()
        cover.setFixedHeight(285)
        cover.setMinimumWidth(205)
        cover.setAlignment(Qt.AlignCenter)
        cover.setObjectName("explorerCover")
        cover_source = book.get("cover_path") or book.get("cover_url", "")
        pix = QPixmap(cover_source)
        if pix.isNull() and book.get("cover_url"):
            try:
                data = urllib.request.urlopen(book["cover_url"], timeout=12).read()
                pix = QPixmap()
                pix.loadFromData(data)
            except Exception:
                pix = QPixmap()
        if not pix.isNull():
            cover.setPixmap(pix.scaled(205, 285, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            cover.setText("SEM CAPA")
        layout.addWidget(cover, alignment=Qt.AlignHCenter)

        title = QLabel(book.get("title", "Sem título"))
        title.setObjectName("explorerBookTitle")
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignCenter)
        title.setMaximumHeight(48)
        layout.addWidget(title)

        author = QLabel(f"por {book.get('author', 'Você')}")
        author.setObjectName("explorerAuthor")
        author.setAlignment(Qt.AlignCenter)
        layout.addWidget(author)

        synopsis = QLabel(book.get("synopsis", "Sem sinopse.") or "Sem sinopse.")
        synopsis.setObjectName("explorerSynopsis")
        synopsis.setWordWrap(True)
        synopsis.setAlignment(Qt.AlignCenter)
        synopsis.setMaximumHeight(55)
        layout.addWidget(synopsis)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        open_btn = QPushButton("Ler")
        open_btn.setObjectName("explorerActionPrimary")
        open_btn.clicked.connect(lambda: self.open_requested.emit(str(self.book["id"])))
        add_btn = QPushButton("+ Biblioteca")
        add_btn.setObjectName("explorerAction")
        add_btn.clicked.connect(lambda: self.add_requested.emit(str(self.book["id"])))
        buttons.addWidget(open_btn, 1)
        buttons.addWidget(add_btn, 1)
        layout.addLayout(buttons)

        if can_remove:
            remove_btn = QPushButton("Tirar do Explorer")
            remove_btn.setObjectName("explorerRemove")
            remove_btn.clicked.connect(lambda: self.remove_requested.emit(str(self.book["id"])))
            layout.addWidget(remove_btn)

    def mousePressEvent(self, event):
        # Only the card body opens the book; action buttons keep their own click behavior.
        if event.button() == Qt.LeftButton and self.childAt(event.position().toPoint()) is None:
            self.open_requested.emit(str(self.book["id"]))
        super().mousePressEvent(event)


class ExplorerPage(Page):
    back_requested = Signal()
    book_requested = Signal(str)

    def __init__(self, db, online=None):
        super().__init__()
        self.setObjectName("explorerPage")
        self.db = db
        self.online = online
        self.all_books = []

        root = QVBoxLayout(self)
        root.setContentsMargins(42, 34, 42, 38)
        root.setSpacing(16)

        top = QHBoxLayout()
        top.setSpacing(14)
        back = QPushButton("←  INÍCIO")
        back.setObjectName("textButton")
        back.clicked.connect(self.back_requested.emit)
        top.addWidget(back)
        top.addStretch()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("Explorer")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignCenter)
        subtitle = QLabel("Descubra histórias publicadas no LivroStudio")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        top.addLayout(title_box)
        top.addStretch()
        self.counter = QLabel("0 livros públicos")
        self.counter.setObjectName("counterBadge")
        top.addWidget(self.counter)
        root.addLayout(top)

        search_row = QHBoxLayout()
        search_row.setSpacing(10)
        self.search = QLineEdit()
        self.search.setObjectName("searchInput")
        self.search.setPlaceholderText("Pesquisar por título, autor ou sinopse...")
        self.search.textChanged.connect(self.apply_search)
        search_row.addWidget(self.search, 1)
        refresh = AnimatedButton("ATUALIZAR")
        refresh.setObjectName("secondaryAction")
        refresh.setMinimumWidth(120)
        refresh.clicked.connect(self.refresh)
        search_row.addWidget(refresh)
        root.addLayout(search_row)

        status_frame = QFrame()
        status_frame.setObjectName("explorerStatus")
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(14, 9, 14, 9)
        self.status = QLabel("")
        self.status.setObjectName("statusText")
        status_layout.addWidget(self.status)
        status_layout.addStretch()
        root.addWidget(status_frame)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("contentScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.wrapper = QWidget()
        self.wrapper.setObjectName("explorerWrapper")
        self.grid = QVBoxLayout(self.wrapper)
        self.grid.setContentsMargins(8, 8, 18, 30)
        self.grid.setSpacing(22)
        self.scroll.setWidget(self.wrapper)
        root.addWidget(self.scroll, 1)

    def clear_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()
            elif item.layout():
                row = item.layout()
                while row.count():
                    child = row.takeAt(0)
                    if child.widget():
                        w = child.widget()
                        w.setParent(None)
                        w.deleteLater()
                row.deleteLater()

    def refresh(self):
        try:
            if self.online and self.online.configured:
                self.all_books = self.online.public_books()
                self.status.setText("ONLINE  •  Explorer conectado e atualizado")
            else:
                self.all_books = self.db.get_public_books()
                self.status.setText("LOCAL  •  Configure o Supabase para publicar e descobrir livros online")
        except Exception as exc:
            self.all_books = self.db.get_public_books()
            self.status.setText(f"ONLINE INDISPONÍVEL  •  {exc}")
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.render(self.all_books)

    def apply_search(self, text):
        q = text.strip().lower()
        books = self.all_books
        if q:
            books = [b for b in books if q in b.get("title", "").lower() or q in b.get("author", "").lower() or q in b.get("synopsis", "").lower()]
        self.render(books)

    def render(self, books):
        self.clear_grid()
        self.counter.setText(f"{len(books)} livro público" if len(books) == 1 else f"{len(books)} livros públicos")
        if not books:
            empty = QFrame()
            empty.setObjectName("explorerEmpty")
            el = QVBoxLayout(empty)
            el.setContentsMargins(30, 42, 30, 42)
            title = QLabel("Nenhuma história encontrada")
            title.setObjectName("emptyTitle")
            title.setAlignment(Qt.AlignCenter)
            hint = QLabel("Tente outra pesquisa ou publique seu primeiro livro.")
            hint.setObjectName("smallHint")
            hint.setAlignment(Qt.AlignCenter)
            el.addWidget(title)
            el.addSpacing(6)
            el.addWidget(hint)
            self.grid.addWidget(empty)
            self.grid.addStretch()
            return

        current_user_id = None
        if self.online and self.online.configured:
            user = self.online.current_user()
            if user:
                current_user_id = str(user.id)

        row = QHBoxLayout()
        row.setSpacing(18)
        for i, book in enumerate(books):
            can_remove = bool(current_user_id and str(book.get("author_id", "")) == current_user_id)
            card = ExplorerCard(book, can_remove=can_remove)
            card.open_requested.connect(self.book_requested.emit)
            card.add_requested.connect(self.add_to_library)
            card.remove_requested.connect(self.remove_from_explorer)
            row.addWidget(card, 1)
            if (i + 1) % 4 == 0:
                self.grid.addLayout(row)
                row = QHBoxLayout()
                row.setSpacing(18)
        if row.count():
            row.addStretch()
            self.grid.addLayout(row)
        self.grid.addStretch()

    def remove_from_explorer(self, book_id):
        if not self.online or not self.online.configured:
            QMessageBox.information(self, "Explorer", "Entre em sua conta para gerenciar seus livros publicados.")
            return
        answer = QMessageBox.question(self, "Tirar do Explorer", "Tem certeza que deseja tirar este livro do Explorer?\n\nEle deixará de aparecer para outras pessoas, mas continuará na sua biblioteca.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            self.online.unpublish_book(book_id)
            self.refresh()
            QMessageBox.information(self, "Explorer", "O livro foi retirado do Explorer.")
        except Exception as exc:
            QMessageBox.critical(self, "Erro", str(exc))

    def add_to_library(self, book_id):
        if not self.online or not self.online.configured:
            QMessageBox.information(self, "Online", "Configure o modo online e entre em uma conta para adicionar livros públicos à sua biblioteca.")
            return
        try:
            book = self.online.get_public_book(book_id)
            if not book:
                raise RuntimeError("Livro não encontrado no servidor.")
            cover_path = self.online.download_cover(book.get("cover_url", ""), book["title"])
            self.db.create_book(title=book["title"], text=book.get("text", ""), cover_source=Path(cover_path), synopsis=book.get("synopsis", ""), author=book.get("author", "Autor"), visibility="private")
            self.online.add_to_library(book_id)
            QMessageBox.information(self, "Biblioteca", "Livro adicionado à sua biblioteca local.")
        except Exception as exc:
            QMessageBox.critical(self, "Erro", str(exc))

# ============================================================
# APARÊNCIA
# ============================================================


class OnlineConfigDialog(QDialog):
    def __init__(self, online, parent=None):
        super().__init__(parent)
        self.online = online
        self.setWindowTitle("Configurar Online")
        self.setModal(True)
        self.resize(520, 300)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("🌐 Configurar LivroStudio Online")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        info = QLabel(
            "Cole aqui o Project URL e a Publishable Key do seu projeto Supabase.\n"
            "Não use a Secret Key nem a service_role key no aplicativo."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://seu-projeto.supabase.co")
        self.url_edit.setText(online.url)
        layout.addWidget(QLabel("Project URL"))
        layout.addWidget(self.url_edit)

        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("sb_publishable_...")
        self.key_edit.setText(online.key)
        self.key_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(QLabel("Publishable Key"))
        layout.addWidget(self.key_edit)

        buttons = QHBoxLayout()
        cancel = QPushButton("Cancelar")
        save = QPushButton("Salvar e conectar")
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.save_config)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def save_config(self):
        try:
            self.online.configure(self.url_edit.text(), self.key_edit.text())
            QMessageBox.information(self, "Online", "Conexão com o Supabase configurada com sucesso!")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))


class AvatarLabel(QLabel):
    """Avatar circular com fallback elegante quando não há foto."""
    def __init__(self, size=112, parent=None):
        super().__init__(parent)
        self.avatar_size = size
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setObjectName("profileAvatar")
        self.setText("LS")
        self.setScaledContents(False)
        self._pixmap = None

    def set_avatar(self, path_or_url=""):
        if not path_or_url:
            self._pixmap = None
            self.setText("LS")
            self.update()
            return
        pix = QPixmap()
        if str(path_or_url).startswith("http://") or str(path_or_url).startswith("https://"):
            try:
                data = urllib.request.urlopen(str(path_or_url), timeout=8).read()
                pix.loadFromData(data)
            except Exception:
                pix = QPixmap()
        else:
            pix.load(str(path_or_url))
        if pix.isNull():
            self._pixmap = None
            self.setText("LS")
        else:
            self._pixmap = pix
            self.setText("")
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        path = QPainterPath()
        path.addEllipse(rect)
        painter.setClipPath(path)
        if self._pixmap and not self._pixmap.isNull():
            pix = self._pixmap.scaled(rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = rect.x() + (rect.width() - pix.width()) // 2
            y = rect.y() + (rect.height() - pix.height()) // 2
            painter.drawPixmap(x, y, pix)
        else:
            painter.fillRect(rect, QColor("#b86bd1"))
            painter.setPen(Qt.white)
            painter.setFont(QFont("Arial", max(12, self.avatar_size // 4), QFont.Bold))
            painter.drawText(rect, Qt.AlignCenter, "LS")
        painter.end()


class AccountDialog(QDialog):
    def __init__(self, online, parent=None):
        super().__init__(parent)
        self.online = online
        self.setWindowTitle("Conta — LivroStudio Online")
        self.setModal(True)
        self.resize(520, 430)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.title = QLabel("Conta LivroStudio")
        self.title.setObjectName("dialogTitle")
        layout.addWidget(self.title)

        profile_row = QHBoxLayout()
        profile_row.setSpacing(18)
        self.avatar = AvatarLabel(112)
        profile_row.addWidget(self.avatar, alignment=Qt.AlignTop)
        profile_info = QVBoxLayout()
        profile_info.setSpacing(7)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("profileStatus")
        profile_info.addWidget(self.status)
        self.avatar_btn = QPushButton("📷  Escolher foto")
        self.avatar_btn.clicked.connect(self.choose_avatar)
        profile_info.addWidget(self.avatar_btn)
        self.remove_avatar_btn = QPushButton("Remover foto")
        self.remove_avatar_btn.setObjectName("subtleButton")
        self.remove_avatar_btn.clicked.connect(self.remove_avatar)
        profile_info.addWidget(self.remove_avatar_btn)
        profile_info.addStretch()
        profile_row.addLayout(profile_info, 1)
        layout.addLayout(profile_row)

        self.config_btn = QPushButton("CONFIGURAR ONLINE")
        self.config_btn.clicked.connect(self.configure_online)
        layout.addWidget(self.config_btn)

        self.username_label = QLabel("Nome de usuário (cadastro)")
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("meu_nome")
        layout.addWidget(self.username_label)
        layout.addWidget(self.username_edit)

        layout.addWidget(QLabel("E-mail"))
        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("voce@email.com")
        layout.addWidget(self.email_edit)

        layout.addWidget(QLabel("Senha"))
        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("mínimo de 6 caracteres")
        self.password_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_edit)

        self.action_btn = QPushButton()
        self.action_btn.clicked.connect(self.action)
        layout.addWidget(self.action_btn)

        self.toggle_btn = QPushButton("Ainda não tenho conta → Criar conta")
        self.toggle_btn.setFlat(True)
        self.toggle_btn.clicked.connect(self.toggle_mode)
        layout.addWidget(self.toggle_btn)

        self.logout_btn = QPushButton("Sair da conta")
        self.logout_btn.clicked.connect(self.logout)
        layout.addWidget(self.logout_btn)

        close_btn = QPushButton("Fechar")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self.signup_mode = False
        self.refresh_state()

    def configure_online(self):
        dlg = OnlineConfigDialog(self.online, self)
        if dlg.exec():
            self.refresh_state()

    def toggle_mode(self):
        self.signup_mode = not self.signup_mode
        self.refresh_state()

    def refresh_state(self):
        user = self.online.current_user() if self.online.configured else None

        if not self.online.configured:
            self.status.setText("🔴 Online não configurado. Configure o Supabase para usar contas e o Explorer online.")
        elif user:
            profile = None
            try:
                profile = self.online.get_profile()
            except Exception:
                profile = None
            username = (profile or {}).get("username") or "Usuário"
            email = getattr(user, "email", "") or ""
            self.status.setText(f"🟢 Conectado\nUsuário: {username}\nE-mail: {email}")
            self.avatar.set_avatar((profile or {}).get("avatar_url", ""))
        else:
            self.status.setText("🟡 Online configurado, mas você não está conectado.")
            self.avatar.set_avatar("")

        logged = user is not None
        self.username_label.setVisible(not logged and self.signup_mode)
        self.username_edit.setVisible(not logged and self.signup_mode)
        self.email_edit.setVisible(not logged)
        self.password_edit.setVisible(not logged)
        self.action_btn.setVisible(not logged)
        self.toggle_btn.setVisible(not logged)
        self.logout_btn.setVisible(logged)
        self.config_btn.setVisible(not logged)
        self.avatar_btn.setVisible(logged)
        self.remove_avatar_btn.setVisible(logged and bool((self.online.get_profile() or {}).get("avatar_url")))

        if self.signup_mode:
            self.action_btn.setText("Criar conta")
            self.toggle_btn.setText("Já tenho conta → Entrar")
        else:
            self.action_btn.setText("Entrar")
            self.toggle_btn.setText("Ainda não tenho conta → Criar conta")

    def action(self):
        if not self.online.configured:
            QMessageBox.warning(self, "Online", "Configure o Supabase primeiro.")
            return

        email = self.email_edit.text().strip()
        password = self.password_edit.text()

        try:
            if self.signup_mode:
                username = self.username_edit.text().strip()
                result = self.online.sign_up(email, password, username)
                if result.get("session"):
                    QMessageBox.information(self, "Conta criada", "Conta criada e login realizado com sucesso!")
                    self.refresh_state()
                else:
                    QMessageBox.information(
                        self,
                        "Confirme seu e-mail",
                        "A conta foi criada. Verifique seu e-mail para confirmar a conta e depois faça login."
                    )
                    self.signup_mode = False
                    self.refresh_state()
            else:
                self.online.sign_in(email, password)
                QMessageBox.information(self, "Login", "Login realizado com sucesso!")
                self.refresh_state()
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))

    def choose_avatar(self):
        if not self.online.configured or not self.online.current_user():
            QMessageBox.information(self, "Foto de perfil", "Entre na sua conta primeiro.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Escolher foto de perfil",
            "",
            "Imagens (*.png *.jpg *.jpeg *.webp)"
        )
        if not path:
            return
        try:
            self.online.set_avatar(path)
            self.refresh_state()
            if self.parent() and hasattr(self.parent(), "refresh_account_avatar"):
                self.parent().refresh_account_avatar()
            QMessageBox.information(self, "Foto de perfil", "Sua foto de perfil foi atualizada!")
        except Exception as exc:
            QMessageBox.critical(self, "Foto de perfil", str(exc))

    def remove_avatar(self):
        try:
            self.online.remove_avatar()
            self.refresh_state()
            if self.parent() and hasattr(self.parent(), "refresh_account_avatar"):
                self.parent().refresh_account_avatar()
        except Exception as exc:
            QMessageBox.critical(self, "Foto de perfil", str(exc))

    def logout(self):
        try:
            self.online.sign_out()
            QMessageBox.information(self, "Conta", "Você saiu da conta.")
            self.refresh_state()
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))


class AppearanceDialog(QDialog):
    def __init__(self, theme, wallpaper, parent=None):
        super().__init__(parent)
        self.setObjectName("appearanceDialog")
        self.setWindowTitle("Aparência")
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(14)
        title = QLabel("Personalizar LivroStudio")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("Tema"))
        self.theme = QComboBox()
        self.theme.addItem("Escuro", "dark")
        self.theme.addItem("Claro", "light")
        self.theme.setCurrentIndex(0 if theme == "dark" else 1)
        layout.addWidget(self.theme)
        layout.addWidget(QLabel("Wallpaper / GIF"))
        self.wallpaper = QComboBox()
        for f in available_wallpapers():
            self.wallpaper.addItem(f.stem.replace("_", " ").title(), f.name)
        for i in range(self.wallpaper.count()):
            if self.wallpaper.itemData(i) == wallpaper:
                self.wallpaper.setCurrentIndex(i)
                break
        layout.addWidget(self.wallpaper)
        info = QLabel("Coloque GIFs ou imagens na pasta assets para eles aparecerem automaticamente nesta lista.")
        info.setObjectName("smallHint")
        info.setWordWrap(True)
        layout.addWidget(info)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return self.theme.currentData(), self.wallpaper.currentData()


# ============================================================
# LEITOR
# ============================================================

class ReaderPage(Page):

    back_requested = Signal()

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.current_book_id = None
        self.setObjectName("readerPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 24, 34, 28)
        root.setSpacing(16)

        top = QHBoxLayout()
        top.setSpacing(16)

        back = QPushButton("←  BIBLIOTECA")
        back.setObjectName("textButton")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.back_requested.emit)
        top.addWidget(back)

        top.addStretch(1)

        self.title = QLabel()
        self.title.setObjectName("readerTitle")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top.addWidget(self.title, 2)

        top.addStretch(1)
        top.addSpacing(120)
        root.addLayout(top)

        # O próprio QTextBrowser faz a rolagem. Isso deixa o leitor
        # realmente longo, centralizado e com uma scrollbar dedicada.
        self.text = QTextBrowser()
        self.text.setObjectName("readerText")
        self.text.setReadOnly(True)
        self.text.setOpenLinks(False)
        self.text.setOpenExternalLinks(False)
        self.text.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.text.setFrameShape(QFrame.NoFrame)
        self.text.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.text.setMinimumWidth(700)
        self.text.setMaximumWidth(920)

        holder = QWidget()
        holder.setObjectName("readerHolder")
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(0, 8, 0, 18)
        holder_layout.addStretch(1)
        holder_layout.addWidget(self.text)
        holder_layout.addStretch(1)

        root.addWidget(holder, 1)

    def open_book(self, book_id):
        self.current_book_id = book_id
        book = self.db.get_book(book_id)
        if not book:
            return
        self.open_book_data(book)

    def open_book_data(self, book):
        self.current_book_id = book.get("id")
        self.title.setText(book.get("title", "Sem título"))
        source = book.get("text", "") or ""
        is_dark = APP_SETTINGS.get("theme", "dark") != "light"
        text_color = "#F0EDF2" if is_dark else "#28252A"
        paper = "#111014" if is_dark else "#FFFDF8"

        # QTextEdit.toHtml() normalmente gera um documento completo que pode
        # começar com <!DOCTYPE HTML> antes da tag <html>. Portanto, não
        # podemos testar apenas startswith("<html"). Livros publicados no
        # Explorer também chegam aqui com esse mesmo HTML completo.
        if re.search(r"<html\b", source, flags=re.IGNORECASE):
            body_match = re.search(
                r"<body[^>]*>(.*)</body>\s*</html>\s*$",
                source,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not body_match:
                body_match = re.search(
                    r"<body[^>]*>(.*)</body>",
                    source,
                    flags=re.IGNORECASE | re.DOTALL,
                )
            content = body_match.group(1) if body_match else source
        else:
            safe = source.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            parts = []
            for line in safe.split("\n"):
                if line.strip():
                    parts.append(f'<p>{line}</p>')
                else:
                    parts.append('<div class="spacer"></div>')
            content = "".join(parts)

        html = f"""
        <html><head><style>
            body {{ background: {paper}; color: {text_color}; margin: 0; padding: 42px 82px 110px 82px; font-family: Georgia, 'Times New Roman', serif; font-size: 19px; line-height: 1.82; text-align: center; }}
            p {{ color: {text_color}; margin: 0 0 25px 0; text-align: center; }}
            h1, h2, h3 {{ color: {text_color}; text-align: center; font-family: Georgia, 'Times New Roman', serif; margin: 28px 0 22px 0; }}
            strong, b, em, i, u, li {{ color: {text_color}; }}
            li {{ margin-bottom: 10px; }}
            .spacer {{ height: 14px; }}
        </style></head><body>{content}</body></html>
        """
        self.text.setStyleSheet(f"QTextBrowser#readerText {{ background: {paper}; color: {text_color}; }}")
        self.text.setHtml(html)
        self.text.verticalScrollBar().setValue(0)

    def refresh_theme(self):
        if self.current_book_id is not None:
            self.open_book(self.current_book_id)


# ============================================================
# JANELA PRINCIPAL
# ============================================================

class MainWindow(QMainWindow):

    def __init__(self):

        super().__init__()

        self.setWindowTitle(
            "LivroStudio V3.5"
        )
        self.setProperty("version", "3.5.0")

        self.resize(
            1440,
            860
        )

        self.setMinimumSize(
            1120,
            720
        )

        # ----------------------------------------------------
        # BANCO
        # ----------------------------------------------------

        self.db = Database(
            DB_PATH
        )
        self.online = OnlineService(USER_DATA_DIR / "online_config.json", USER_DATA_DIR / "online_session.json")

        # ----------------------------------------------------
        # STACK
        # ----------------------------------------------------

        self.stack = QStackedWidget()

        # Chrome superior inspirado na captura de referência.
        central = QWidget()
        central.setObjectName("appShell")
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        self.chrome = QWidget()
        self.chrome.setObjectName("appChrome")
        chrome_layout = QHBoxLayout(self.chrome)
        chrome_layout.setContentsMargins(14, 0, 14, 0)
        chrome_layout.setSpacing(8)

        dots = QWidget()
        dots_layout = QHBoxLayout(dots)
        dots_layout.setContentsMargins(0, 0, 0, 0)
        dots_layout.setSpacing(7)
        for obj in ("chromeDotRed", "chromeDotYellow", "chromeDotGreen"):
            dot = QLabel()
            dot.setObjectName(obj)
            dot.setFixedSize(7, 7)
            dots_layout.addWidget(dot)
        chrome_layout.addWidget(dots)
        chrome_layout.addStretch()
        chrome_title = QLabel("LivroStudio.exe")
        chrome_title.setObjectName("chromeTitle")
        chrome_layout.addWidget(chrome_title)
        chrome_layout.addStretch()
        chrome_layout.addSpacing(46)
        central_layout.addWidget(self.chrome)

        workspace = QWidget()
        workspace_layout = QHBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)

        # Barra lateral fixa, como na nova Home.
        self.nav = QWidget()
        self.nav.setObjectName("appNav")
        self.nav.setFixedWidth(214)
        nav_layout = QVBoxLayout(self.nav)
        nav_layout.setContentsMargins(16, 22, 16, 18)
        nav_layout.setSpacing(7)

        brand = QPushButton()

        brand.setObjectName("navBrand")
        brand.setFixedSize(50, 50)
        brand.setCursor(Qt.PointingHandCursor)

        png_path = ASSETS_DIR / "LivroStudioPng.png"
        pixmap = QPixmap(str(png_path))

        if not pixmap.isNull():
            brand.setIcon(QIcon(pixmap))
            brand.setIconSize(QSize(42, 42))

        brand.clicked.connect(self.show_home)

        nav_layout.addWidget(brand, alignment=Qt.AlignHCenter)
        nav_layout.addSpacing(28)

        self.nav_buttons = []
        for text, slot in [("Início", self.show_home), ("Explorer", self.show_explorer), ("Biblioteca", self.show_library), ("Criar", self.show_editor)]:
            b = QPushButton(text)
            b.setObjectName("navButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(48)
            b.clicked.connect(slot)
            nav_layout.addWidget(b)
            self.nav_buttons.append(b)

        nav_layout.addStretch()

        account = QPushButton("Conta")
        account.setObjectName("navButtonSecondary")
        account.setCursor(Qt.PointingHandCursor)
        account.clicked.connect(self.open_account)
        self.account_button = account
        nav_layout.addWidget(account)

        appearance = QPushButton("Aparência")
        appearance.setObjectName("navButtonSecondary")
        appearance.setCursor(Qt.PointingHandCursor)
        appearance.clicked.connect(self.open_appearance)
        nav_layout.addWidget(appearance)

        workspace_layout.addWidget(self.nav)
        workspace_layout.addWidget(self.stack, 1)
        central_layout.addWidget(workspace, 1)
        self.setCentralWidget(central)
        self.refresh_account_avatar()

        # ----------------------------------------------------
        # PÁGINAS
        # ----------------------------------------------------

        self.home = HomePage()

        self.editor = EditorPage(
            self.db
        )

        self.library = LibraryPage(
            self.db
        )

        self.explorer = ExplorerPage(
            self.db, self.online
        )

        self.reader = ReaderPage(
            self.db
        )

        self.stack.addWidget(
            self.home
        )

        self.stack.addWidget(
            self.editor
        )

        self.stack.addWidget(
            self.library
        )

        self.stack.addWidget(
            self.explorer
        )

        self.stack.addWidget(
            self.reader
        )

        # ----------------------------------------------------
        # CONEXÕES
        # ----------------------------------------------------

        self.home.create_requested.connect(
            self.show_editor
        )

        self.home.library_requested.connect(
            self.show_library
        )

        self.home.explorer_requested.connect(
            self.show_explorer
        )

        self.editor.back_requested.connect(
            self.show_home
        )

        self.editor.saved.connect(
            self.book_saved
        )

        self.library.back_requested.connect(
            self.show_home
        )

        self.library.book_requested.connect(
            self.show_reader
        )

        self.explorer.back_requested.connect(self.show_home)
        self.explorer.book_requested.connect(self.open_explorer_book)

        self.reader.back_requested.connect(
            self.show_library
        )

    def refresh_account_avatar(self):
        if not hasattr(self, "account_button"):
            return
        self.account_button.setIcon(QIcon())
        self.account_button.setIconSize(QSize(34, 34))
        if not self.online.configured or not self.online.current_user():
            self.account_button.setText("Conta")
            return
        try:
            profile = self.online.get_profile() or {}
            url = profile.get("avatar_url", "")
            if url:
                data = urllib.request.urlopen(url, timeout=5).read()
                pix = QPixmap()
                pix.loadFromData(data)
                if not pix.isNull():
                    pix = pix.scaled(34, 34, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                    self.account_button.setIcon(QIcon(pix))
                    self.account_button.setText("  Conta")
                    return
        except Exception:
            pass
        self.account_button.setText("Conta")

    def open_account(self):
        dlg = AccountDialog(self.online, self)
        dlg.exec()
        self.refresh_account_avatar()
        self.explorer.refresh()

    def open_explorer_book(self, book_id):
        try:
            if self.online and self.online.configured:
                book = self.online.get_public_book(book_id)
                if book:
                    self.reader.open_book_data(book)
                    self.stack.setCurrentWidget(self.reader)
                    self.update_nav(-1)
                    self.animate_page()
                    return
        except Exception as exc:
            QMessageBox.warning(self, "Explorer", str(exc))
        try:
            self.show_reader(int(book_id))
        except Exception:
            pass

    # ========================================================
    # TRANSIÇÃO
    # ========================================================

    def animate_page(
        self
    ):

        widget = self.stack.currentWidget()

        if widget is None:

            return

        effect = QGraphicsOpacityEffect(
            widget
        )

        widget.setGraphicsEffect(
            effect
        )

        animation = QPropertyAnimation(
            effect,
            b"opacity",
            self
        )

        animation.setDuration(
            230
        )

        animation.setStartValue(
            0.0
        )

        animation.setEndValue(
            1.0
        )

        animation.setEasingCurve(
            QEasingCurve.OutCubic
        )

        widget._animation = animation
        widget._effect = effect

        animation.finished.connect(
            lambda: self.remove_effect(
                widget
            )
        )

        animation.start(
            QPropertyAnimation.DeleteWhenStopped
        )

    def remove_effect(
        self,
        widget
    ):

        widget.setGraphicsEffect(
            None
        )

    def update_nav(self, active_index):
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == active_index)

    def show_explorer(self):
        self.explorer.refresh()
        self.stack.setCurrentWidget(self.explorer)
        self.update_nav(1)
        self.animate_page()

    def open_appearance(self):
        dialog = AppearanceDialog(APP_SETTINGS.get("theme", "dark"), APP_SETTINGS.get("wallpaper", "background.gif"), self)
        if dialog.exec() == QDialog.Accepted:
            theme, wallpaper = dialog.values()
            APP_SETTINGS["theme"] = theme or "dark"
            APP_SETTINGS["wallpaper"] = wallpaper or "background.gif"
            save_settings(APP_SETTINGS)
            self.apply_theme()
            self.home.set_wallpaper(ASSETS_DIR / APP_SETTINGS["wallpaper"])

    def apply_theme(self):
        app = QApplication.instance()
        base = STYLE_PATH.read_text(encoding="utf-8") if STYLE_PATH.exists() else ""
        theme = theme_stylesheet(APP_SETTINGS.get("theme", "dark"))
        app.setStyleSheet(base + "\n" + theme)
        app.setProperty("theme", APP_SETTINGS.get("theme", "dark"))
        app.style().unpolish(app)
        app.style().polish(app)
        for widget in app.allWidgets():
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        if hasattr(self, "reader"):
            self.reader.refresh_theme()

    # ========================================================
    # HOME
    # ========================================================

    def show_home(self):

        self.stack.setCurrentWidget(
            self.home
        )
        self.update_nav(0)

        self.animate_page()

    # ========================================================
    # EDITOR
    # ========================================================

    def show_editor(self):

        self.stack.setCurrentWidget(
            self.editor
        )
        self.update_nav(3)

        self.animate_page()

    # ========================================================
    # BIBLIOTECA
    # ========================================================

    def show_library(self):

        self.library.refresh()

        self.stack.setCurrentWidget(
            self.library
        )
        self.update_nav(2)

        self.animate_page()

        QTimer.singleShot(
            100,
            self.library.carousel.setFocus
        )

    # ========================================================
    # SALVOU
    # ========================================================

    def book_saved(
        self,
        book_id
    ):

        self.library.refresh()

        self.show_library()

    # ========================================================
    # LEITOR
    # ========================================================

    def show_reader(
        self,
        book_id
    ):

        self.reader.open_book(
            book_id
        )

        self.stack.setCurrentWidget(
            self.reader
        )
        self.update_nav(-1)

        self.animate_page()


# ============================================================
# MAIN
# ============================================================

def main():

    app = QApplication(
        sys.argv
    )

    app.setApplicationName(
        "LivroStudio"
    )
    app.setApplicationVersion("3.5.0")

    if ICON_PATH.exists():
        app.setWindowIcon(
            QIcon(str(ICON_PATH))
        )

    app.setFont(
        QFont(
            "Segoe UI",
            10
        )
    )

    # --------------------------------------------------------
    # STYLE
    # --------------------------------------------------------

    style_path = STYLE_PATH

    if style_path.exists():
        app.setStyleSheet(style_path.read_text(encoding="utf-8") + "\n" + theme_stylesheet(APP_SETTINGS.get("theme", "dark")))
        app.setProperty("theme", APP_SETTINGS.get("theme", "dark"))

    else:

        print(
            "AVISO: style.qss não encontrado."
        )

    # --------------------------------------------------------
    # JANELA
    # --------------------------------------------------------

    window = MainWindow()
    window.home.set_wallpaper(ASSETS_DIR / APP_SETTINGS.get("wallpaper", "background.gif"))
    window.show()

    sys.exit(
        app.exec()
    )


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    main()