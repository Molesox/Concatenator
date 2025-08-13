# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import pathlib
from typing import Iterable, List, Optional, cast
import sys
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QPainter, QColor
from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QApplication

from PySide6.QtCore import (
    Qt, QMimeData, QSize, QSettings, QUrl, QByteArray, QTimer
)
 

from PySide6.QtGui import QPalette, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem,
    QPushButton, QFileDialog, QLineEdit,
    QCheckBox, QDoubleSpinBox, QLabel, QMessageBox, QProgressBar, QGroupBox,
    QSplitter, QComboBox, QInputDialog, QAbstractItemView, QHeaderView, QToolButton
)

from models import Options
from core import (
    unique_paths, parse_csv_list, normalize_exts, human_size,
    gather_candidate_files, concat_to_file, concat_to_string
)

ROLE_META = int(Qt.ItemDataRole.UserRole)
ROLE_HOOKED = ROLE_META + 1


class ConcatCancelled(Exception):
    """Exception levée pour interrompre la concaténation."""
    pass


# ----- Icônes (SVG recolorés selon la palette) -----
def _icons_dir() -> pathlib.Path:
    base = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).resolve().parent))
    return base / "icons"

def _render_svg_to_icon(svg_path: pathlib.Path, size: QSize, color: QColor) -> QIcon:
    if not svg_path.exists():
        return QIcon()
    try:
        txt = svg_path.read_text(encoding="utf-8")
    except Exception:
        return QIcon()
    txt = txt.replace("currentColor", color.name())
    ba = QByteArray(txt.encode("utf-8"))
    renderer = QSvgRenderer(ba)
    if not renderer.isValid():
        return QIcon()
    screen = QApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen else 1.0
    pm = QPixmap(int(size.width() * dpr), int(size.height() * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    return QIcon(pm)

def ico(name: str, size: QSize = QSize(20, 20), color: QColor | None = None) -> QIcon:
    p = _icons_dir() / name
    if color is None:
        pal = QApplication.palette()
        color = pal.color(QPalette.ColorRole.ButtonText)
        if not color.isValid():
            color = pal.color(QPalette.ColorRole.WindowText)
        if not color.isValid():
            color = QColor("#000000")
    return _render_svg_to_icon(p, size, color)

# ----- Liste avec DnD + colonne bouton supprimer -----
class DropTreeWidget(QTreeWidget):
    def __init__(self, parent=None, get_files_cb=None, mark_dirty_cb=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setMinimumHeight(200)
        self.setColumnCount(2)
        hdr = self.header()
        hdr.setVisible(False)
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(1, 28)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.get_files_cb = get_files_cb
        self.mark_dirty_cb = mark_dirty_cb
        self.itemExpanded.connect(self._maybe_populate_children)
        self.setUniformRowHeights(True)
        self.setAllColumnsShowFocus(True)
        self.setIndentation(10)      
        self.setIconSize(QSize(16,16))  

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        md: QMimeData = e.mimeData()
        if md.hasUrls():
            paths = []
            for url in md.urls():
                p = url.toLocalFile()
                if p:
                    paths.append(p)
            self.add_paths(paths)
            e.acceptProposedAction()
        else:
            super().dropEvent(e)

    def add_paths(self, paths: Iterable[str]):
        existing: set[str] = set()
        for i in range(self.topLevelItemCount()):
            it = self.topLevelItem(i)
            if it is not None:
                existing.add(it.text(0))
        for p in unique_paths(paths):
            if p in existing:
                continue
            it = QTreeWidgetItem([p])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked)
            it.setData(0, ROLE_META, {'type': 'dir' if os.path.isdir(p) else 'file', 'populated': False})
            if os.path.isdir(p):
                it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            self.addTopLevelItem(it)
            self._attach_remove_button(it)
        if self.mark_dirty_cb:
            self.mark_dirty_cb()

    def selected_paths(self) -> List[str]:
        return [i.text(0) for i in self.selectedItems() if not i.parent()]

    def all_paths(self) -> List[str]:
        out: List[str] = []
        for i in range(self.topLevelItemCount()):
            it = self.topLevelItem(i)
            if it is not None:
                out.append(it.text(0))
        return out

    def checked_paths(self) -> List[str]:
        """Retourne tous les chemins cochés, y compris ceux des enfants.

        Un dossier n'est retourné que si tous ses descendants sont cochés.
        Sinon, seuls les sous-éléments cochés sont listés afin d'exclure
        précisément les fichiers décochés.
        """

        def collect(item: QTreeWidgetItem) -> tuple[bool, List[str]]:
            """Retourne (full, paths) pour l'item.

            * full=True si l'item et tous ses descendants sont cochés.
            * paths=list des chemins cochés dans ce sous-arbre.
            """

            if item.checkState(0) != Qt.CheckState.Checked:
                return False, []

            if item.childCount() == 0:
                return True, [item.text(0)]

            all_checked = True
            paths: List[str] = []
            for j in range(item.childCount()):
                ch = item.child(j)
                if ch is None:
                    continue
                ch_full, ch_paths = collect(ch)
                if not ch_full:
                    all_checked = False
                paths.extend(ch_paths)

            if all_checked:
                return True, [item.text(0)]
            return True, paths

        out: List[str] = []
        for i in range(self.topLevelItemCount()):
            it = self.topLevelItem(i)
            if it is None:
                continue
            _, paths = collect(it)
            out.extend(paths)
        return out

    def _attach_remove_button(self, item: QTreeWidgetItem):
        btn = QToolButton()
        btn.setAutoRaise(True)
        btn.setIcon(ico("delete.svg"))
        btn.setIconSize(QSize(16, 16))
        btn.setToolTip("Retirer cet élément de la liste")
        btn.setStyleSheet("QToolButton{padding:0;margin:0;border:0;}")
        btn.clicked.connect(lambda _=False, it=item: self._remove_item(it))
        self.setItemWidget(item, 1, btn)
        self._ensure_delete_col_width_for(btn)

    def _ensure_delete_col_width_for(self, btn: QToolButton):
        w = btn.sizeHint().width() + 10
        if w > self.columnWidth(1):
            self.setColumnWidth(1, w)

    def fix_delete_column_width(self):
        maxw = self.columnWidth(1)
        for i in range(self.topLevelItemCount()):
            it = self.topLevelItem(i)
            if it is not None:
                w = self.itemWidget(it, 1)
                if isinstance(w, QToolButton):
                    maxw = max(maxw, w.sizeHint().width() + 10)
                for j in range(it.childCount()):
                    ch = it.child(j)
                    if ch is not None:
                        w = self.itemWidget(ch, 1)
                        if isinstance(w, QToolButton):
                            maxw = max(maxw, w.sizeHint().width() + 10)
        self.setColumnWidth(1, maxw)

    def _remove_item(self, item: QTreeWidgetItem):
        if item.parent():
            item.parent().removeChild(item)
        else:
            idx = self.indexOfTopLevelItem(item)
            if idx >= 0:
                self.takeTopLevelItem(idx)
        if self.mark_dirty_cb:
            self.mark_dirty_cb()

    def _maybe_populate_children(self, item: QTreeWidgetItem):
        meta = item.data(0, ROLE_META) or {}
        if not isinstance(meta, dict):
            meta = {}
        if meta.get('type') != 'dir' or meta.get('populated') or self.get_files_cb is None:
            return
        dir_path = item.text(0)
        files = self.get_files_cb([dir_path]) or []
        for fp in files:
            child = QTreeWidgetItem([fp])
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            child.setCheckState(0, Qt.CheckState.Checked)
            child.setData(0, ROLE_META, {'type': 'file'})
            item.addChild(child)
            self._attach_remove_button(child)
        meta['populated'] = True
        item.setData(0, ROLE_META, meta)
        if not bool(item.data(0, ROLE_HOOKED)):
            def propagate(state: Qt.CheckState):
                for j in range(item.childCount()):
                    ch = item.child(j)
                    if ch is not None:
                        ch.setCheckState(0, state)
            def on_changed(changed: QTreeWidgetItem, parent=item):
                if changed is parent:
                    propagate(parent.checkState(0))
            self.itemChanged.connect(on_changed)  # type: ignore[arg-type]
            item.setData(0, ROLE_HOOKED, True)

# ----- Fenêtre principale -----
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Concatenator - Sélection & concaténation")
        self.setWindowIcon(ico("app.svg", QSize(24, 24)))
        self.resize(980, 680)
    
        self.dirty = False
        self._block_dirty = False
        self._cancel_concat = False
        self._concat_running = False

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(800)
        self._autosave_timer.timeout.connect(
            lambda: self.save_profile_to_settings(self.current_profile_name() or "Défaut")
        )

        prof_row = QHBoxLayout()

        # Profils
        self.cmb_profile = QComboBox()
        self.cmb_profile.setMinimumWidth(220)
        self.btn_prof_new = QToolButton(); self.btn_prof_new.setAutoRaise(True); self.btn_prof_new.setIcon(ico("new_profile.svg")); self.btn_prof_new.setIconSize(QSize(18, 18))
        self.btn_prof_rename = QToolButton(); self.btn_prof_rename.setAutoRaise(True); self.btn_prof_rename.setIcon(ico("edit.svg")); self.btn_prof_rename.setIconSize(QSize(18, 18))
        self.btn_prof_delete = QToolButton(); self.btn_prof_delete.setAutoRaise(True); self.btn_prof_delete.setIcon(ico("delete.svg")); self.btn_prof_delete.setIconSize(QSize(18, 18))

        prof_row.addStretch(1)
      
        prof_row.addSpacing(8)

        prof_row.addSpacing(16)
        prof_row.addWidget(QLabel("Profil :"))
        prof_row.addWidget(self.cmb_profile, 1)
        prof_row.addWidget(self.btn_prof_new)
        prof_row.addWidget(self.btn_prof_rename)
        prof_row.addWidget(self.btn_prof_delete)
        root.addLayout(prof_row)

        top = QHBoxLayout()
        self.btn_add_files = QToolButton(); self.btn_add_files.setAutoRaise(True); self.btn_add_files.setIcon(ico("add_file.svg")); self.btn_add_files.setIconSize(QSize(20, 20))
        self.btn_add_dirs = QToolButton(); self.btn_add_dirs.setAutoRaise(True); self.btn_add_dirs.setIcon(ico("add_folder.svg")); self.btn_add_dirs.setIconSize(QSize(20, 20))
        self.btn_clear = QToolButton(); self.btn_clear.setAutoRaise(True); self.btn_clear.setIcon(ico("delete.svg")); self.btn_clear.setIconSize(QSize(20, 20))
        self.btn_add_files.setToolTip("Ajouter des fichiers…")
        self.btn_add_dirs.setToolTip("Ajouter des dossiers…")
        self.btn_clear.setToolTip("Vider la liste")
        top.addWidget(self.btn_add_files)
        top.addWidget(self.btn_add_dirs)
        top.addWidget(self.btn_clear)
        top.addStretch(1)
        root.addLayout(top)

        self.split = QSplitter()
        self.split.setChildrenCollapsible(False)
        root.addWidget(self.split, 1)

        self.listw = DropTreeWidget(
            get_files_cb=lambda roots: self.gather_candidate_files(roots, self.current_options()),
            mark_dirty_cb=self.mark_dirty
        )
        self.listw.setToolTip("Glissez-déposez des fichiers/dossiers ici")
        self.split.addWidget(self.listw)

        opts_panel = QWidget()
        opts_layout = QVBoxLayout(opts_panel)

        gb_filter = QGroupBox("Filtre d'extensions (vide = tout)")
        ly_filter = QHBoxLayout(gb_filter)
        self.ed_exts = QLineEdit(".py,.ts,.tsx,.js,.java,.kt,.cs,.cpp,.h,.hpp")
        ly_filter.addWidget(QLabel("Extensions :"))
        ly_filter.addWidget(self.ed_exts)
        opts_layout.addWidget(gb_filter)

        gb_ex = QGroupBox("Exclure ces dossiers (noms, virgules)")
        ly_ex = QHBoxLayout(gb_ex)
        self.ed_excludedirs = QLineEdit(".git,node_modules,venv,build,dist,.idea,.vscode,target,bin,obj")
        ly_ex.addWidget(QLabel("Dossiers :"))
        ly_ex.addWidget(self.ed_excludedirs)
        opts_layout.addWidget(gb_ex)

        gb_flags = QGroupBox("Options")
        ly_flags = QVBoxLayout(gb_flags)
        self.chk_recursive = QCheckBox("Récursif pour les dossiers"); self.chk_recursive.setChecked(True)
        self.chk_headers = QCheckBox("Ajouter un séparateur avec le chemin du fichier"); self.chk_headers.setChecked(True)
        self.chk_ignore_bin = QCheckBox("Ignorer les fichiers binaires"); self.chk_ignore_bin.setChecked(True)
        self.chk_norm_eol = QCheckBox("Normaliser les fins de ligne en \\n"); self.chk_norm_eol.setChecked(True)
        ly_flags.addWidget(self.chk_recursive)
        ly_flags.addWidget(self.chk_headers)
        ly_flags.addWidget(self.chk_ignore_bin)
        ly_flags.addWidget(self.chk_norm_eol)
        hl_size = QHBoxLayout()
        self.spin_maxmb = QDoubleSpinBox(); self.spin_maxmb.setDecimals(1); self.spin_maxmb.setRange(0.1, 1024.0); self.spin_maxmb.setSingleStep(0.5); self.spin_maxmb.setValue(5.0)
        hl_size.addWidget(QLabel("Taille max / fichier :")); hl_size.addWidget(self.spin_maxmb); hl_size.addWidget(QLabel("Mo"))
        ly_flags.addLayout(hl_size)
        opts_layout.addWidget(gb_flags)
        opts_layout.addStretch(1)
        self.split.addWidget(opts_panel)
        self.split.setSizes([640, 340])

        out_row = QHBoxLayout()
        self.ed_out = QLineEdit(str(pathlib.Path.home() / 'concat.txt'))
        self.btn_browse_out = QPushButton("Parcourir…"); self.btn_browse_out.setMinimumWidth(140)
        self.btn_open_out = QPushButton("Ouvrir"); self.btn_open_out.setIcon(ico("open.svg")); self.btn_open_out.setIconSize(QSize(18, 18)); self.btn_open_out.setMinimumWidth(140)
        out_row.addWidget(QLabel("Fichier de sortie :"))
        out_row.addWidget(self.ed_out, 1)
        out_row.addWidget(self.btn_browse_out)
        out_row.addWidget(self.btn_open_out)
        root.addLayout(out_row)

        actions = QHBoxLayout()
        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        self.btn_concat = QPushButton("Concaténer"); self.btn_concat.setIcon(ico("app.svg", QSize(18, 18))); self.btn_concat.setIconSize(QSize(18, 18)); self.btn_concat.setMinimumWidth(140)
        self.btn_copy = QPushButton("Copier"); self.btn_copy.setIcon(ico("copy.svg")); self.btn_copy.setIconSize(QSize(18, 18)); self.btn_copy.setMinimumWidth(140)
        actions.addWidget(self.progress, 1)
        actions.addWidget(self.btn_concat)
        actions.addWidget(self.btn_copy)
        root.addLayout(actions)

        self.menuBar().hide()

        self.btn_add_files.clicked.connect(self.on_add_files)
        self.btn_add_dirs.clicked.connect(self.on_add_dirs)
        self.btn_clear.clicked.connect(self.on_clear)
        self.btn_browse_out.clicked.connect(self.on_browse_out)
        self.btn_concat.clicked.connect(self.on_concat)
        self.btn_copy.clicked.connect(self.on_copy_to_clipboard)
        self.btn_open_out.clicked.connect(self.on_open_out)
      
        self.cmb_profile.currentIndexChanged.connect(self.on_profile_combo_changed)
        self.btn_prof_new.clicked.connect(self.on_profile_new)
        self.btn_prof_rename.clicked.connect(self.on_profile_rename)
        self.btn_prof_delete.clicked.connect(self.on_profile_delete)

        self.listw.itemChanged.connect(self.mark_dirty)
        self.listw.itemSelectionChanged.connect(self.mark_dirty)
        self.ed_exts.textChanged.connect(self.mark_dirty)
        self.ed_excludedirs.textChanged.connect(self.mark_dirty)
        self.chk_recursive.toggled.connect(self.mark_dirty)
        self.chk_headers.toggled.connect(self.mark_dirty)
        self.chk_ignore_bin.toggled.connect(self.mark_dirty)
        self.chk_norm_eol.toggled.connect(self.mark_dirty)
        self.spin_maxmb.valueChanged.connect(self.mark_dirty)
        self.ed_out.textChanged.connect(self.mark_dirty)

        self.init_profiles_and_load()
        self._last_profile_name = self.current_profile_name()
        s = QSettings(); s.beginGroup("ui")
        s.endGroup()
        self.setWindowIcon(ico("app.svg", QSize(24, 24)))
        self._fix_delete_column_width()

    def _fix_delete_column_width(self):
        try:
            self.listw.fix_delete_column_width()
        except Exception:
            pass

    # ----- Dirty helpers -----
    def mark_dirty(self, *args):
        if self._block_dirty:
            return
        self.dirty = True
        self.setWindowTitle("Concatenator - Sélection & concaténation")
        self._autosave_timer.start()

    def clear_dirty(self):
        self.dirty = False
        self.setWindowTitle("Concatenator - Sélection & concaténation")

    # ----- Profils -----
    def profiles_root(self) -> str:
        return "profiles"

    def list_profiles(self) -> List[str]:
        s = QSettings()
        s.beginGroup(self.profiles_root())
        names = s.childGroups()
        s.endGroup()
        return sorted(names)

    def current_profile_name(self) -> str:
        return self.cmb_profile.currentText().strip()

    def set_current_profile_name(self, name: str):
        idx = self.cmb_profile.findText(name)
        if idx >= 0:
            self.cmb_profile.setCurrentIndex(idx)

    def refresh_profiles_combo(self, select: str | None = None):
        names = self.list_profiles()
        self._block_dirty = True
        try:
            self.cmb_profile.blockSignals(True)
            self.cmb_profile.clear()
            for n in names:
                self.cmb_profile.addItem(n)
            if select and select in names:
                self.cmb_profile.setCurrentText(select)
            elif names:
                self.cmb_profile.setCurrentIndex(0)
        finally:
            self.cmb_profile.blockSignals(False)
            self._block_dirty = False

    def ensure_default_profile(self):
        names = self.list_profiles()
        if not names:
            self.save_profile_to_settings("Défaut")
        self.refresh_profiles_combo(select="Défaut")

    def on_profile_combo_changed(self, idx: int):
        if idx < 0:
            return
        if hasattr(self, "_last_profile_name") and self._last_profile_name:
            try:
                self.save_profile_to_settings(self._last_profile_name)
            except Exception:
                pass
        name = self.cmb_profile.itemText(idx)
        self.load_profile_from_settings(name)
        self._last_profile_name = name

    def on_profile_new(self):
        name, ok = QInputDialog.getText(self, "Nouveau profil", "Nom du profil :")
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self.list_profiles():
            QMessageBox.warning(self, "Existe déjà", f"Le profil '{name}' existe déjà.")
            return
        self.save_profile_to_settings(name)
        self.refresh_profiles_combo(select=name)
        self.clear_dirty()
        self._last_profile_name = name

    def on_profile_rename(self):
        old = self.current_profile_name()
        if not old:
            return
        new, ok = QInputDialog.getText(self, "Renommer le profil", "Nouveau nom :", text=old)
        if not ok or not new.strip():
            return
        new = new.strip()
        if new == old:
            return
        if new in self.list_profiles():
            QMessageBox.warning(self, "Existe déjà", f"Le profil '{new}' existe déjà.")
            return
        s = QSettings()
        s.beginGroup(self.profiles_root())
        s.beginGroup(old)
        keys = s.allKeys()
        values = {k: s.value(k) for k in keys}
        s.endGroup()
        s.beginGroup(new)
        for k, v in values.items():
            s.setValue(k, v)
        s.endGroup()
        s.remove(old)
        s.endGroup()
        self.refresh_profiles_combo(select=new)
        self.clear_dirty()
        self._last_profile_name = new

    def on_profile_delete(self):
        name = self.current_profile_name()
        if not name:
            return
        if QMessageBox.question(
            self, "Supprimer le profil",
            f"Supprimer définitivement le profil '{name}' ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        s = QSettings()
        s.beginGroup(self.profiles_root())
        s.remove(name)
        s.endGroup()
        self.refresh_profiles_combo()
        if self.cmb_profile.count() == 0:
            self.ensure_default_profile()
        self.load_profile_from_settings(self.current_profile_name())
        self.clear_dirty()
        self._last_profile_name = self.current_profile_name()

    # ----- Enregistrement / chargement d'un profil -----
    def save_profile_to_settings(self, prof_name: str):
        s = QSettings()
        s.beginGroup(self.profiles_root())
        s.beginGroup(prof_name)

        items: list[str] = []
        for i in range(self.listw.topLevelItemCount()):
            it = self.listw.topLevelItem(i)
            if it is None:
                continue
            chk = '1' if it.checkState(0) == Qt.CheckState.Checked else '0'
            items.append(f"{it.text(0)}|{chk}")
        s.setValue("list/items", items)

        s.setValue("opts/exts", self.ed_exts.text())
        s.setValue("opts/excludedirs", self.ed_excludedirs.text())
        s.setValue("opts/recursive", self.chk_recursive.isChecked())
        s.setValue("opts/headers", self.chk_headers.isChecked())
        s.setValue("opts/ignore_bin", self.chk_ignore_bin.isChecked())
        s.setValue("opts/normalize_eol", self.chk_norm_eol.isChecked())
        s.setValue("opts/max_mb", self.spin_maxmb.value())
        s.setValue("out/path", self.ed_out.text())

        s.setValue("ui/geometry", self.saveGeometry())
        s.setValue("ui/state", self.saveState())
        s.setValue("ui/splitter_sizes", self.split.sizes())

        s.endGroup()
        s.endGroup()
        QSettings().setValue("profiles/current", prof_name)

    def load_profile_from_settings(self, prof_name: str):
        self._block_dirty = True
        try:
            s = QSettings()
            s.beginGroup(self.profiles_root())
            s.beginGroup(prof_name)
            self.listw.blockSignals(True)
            self.listw.clear()
            items = cast(list[str], s.value("list/items", [], list))
            if items:
                existing = set()
                for entry in items:
                    try:
                        path, chk = entry.rsplit('|', 1)
                    except ValueError:
                        path, chk = entry, '1'
                    path = os.path.normpath(os.path.abspath(path))
                    if path in existing:
                        continue
                    existing.add(path)
                    it = QTreeWidgetItem([path])
                    it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    it.setCheckState(0, Qt.CheckState.Checked if chk == '1' else Qt.CheckState.Unchecked)
                    it.setData(0, ROLE_META, {'type': 'dir' if os.path.isdir(path) else 'file', 'populated': False})
                    if os.path.isdir(path):
                        it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
                    self.listw.addTopLevelItem(it)
                    self.listw._attach_remove_button(it)
            self.listw.blockSignals(False)

            exts = cast(Optional[str], s.value("opts/exts", None, str))
            if exts is not None:
                self.ed_exts.setText(exts)
            exdirs = cast(Optional[str], s.value("opts/excludedirs", None, str))
            if exdirs is not None:
                self.ed_excludedirs.setText(exdirs)

            self.chk_recursive.setChecked(cast(bool, s.value("opts/recursive", self.chk_recursive.isChecked(), bool)))
            self.chk_headers.setChecked(cast(bool, s.value("opts/headers", self.chk_headers.isChecked(), bool)))
            self.chk_ignore_bin.setChecked(cast(bool, s.value("opts/ignore_bin", self.chk_ignore_bin.isChecked(), bool)))
            self.chk_norm_eol.setChecked(cast(bool, s.value("opts/normalize_eol", self.chk_norm_eol.isChecked(), bool)))

            max_mb = cast(Optional[float], s.value("opts/max_mb", None, float))
            if max_mb is not None:
                try:
                    self.spin_maxmb.setValue(float(max_mb))
                except Exception:
                    pass

            outp = cast(Optional[str], s.value("out/path", None, str))
            if outp is not None:
                self.ed_out.setText(outp)

            geo = cast(Optional[QByteArray], s.value("ui/geometry", None))
            if geo:
                self.restoreGeometry(geo)
            st = cast(Optional[QByteArray], s.value("ui/state", None))
            if st:
                self.restoreState(st)
            split_sizes = cast(Optional[list[int]], s.value("ui/splitter_sizes", None, list))
            if split_sizes:
                try:
                    self.split.setSizes([int(x) for x in split_sizes])
                except Exception:
                    pass

            s.endGroup()
            s.endGroup()

            self.clear_dirty()
            QSettings().setValue("profiles/current", prof_name)
        finally:
            self._block_dirty = False
    def init_profiles_and_load(self):
        self.ensure_default_profile()
        last = QSettings().value("profiles/current")
        if last and last in self.list_profiles():
            self.set_current_profile_name(last)
        else:
            self.set_current_profile_name("Défaut")
        self.load_profile_from_settings(self.current_profile_name())

        # ----- Slots -----
    def on_open_out(self):
        path = self.ed_out.text().strip()
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.warning(self, "Fichier introuvable", "Le fichier spécifié n'existe pas.")

    def on_clear(self):
        self.listw.clear()
        self.mark_dirty()

    def on_add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Choisir des fichiers")
        if files:
            self.listw.add_paths(files)

    def on_add_dirs(self):
        dirpath = QFileDialog.getExistingDirectory(self, "Choisir un dossier")
        if dirpath:
            self.listw.add_paths([dirpath])

    def on_browse_out(self):
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer sous", self.ed_out.text(), "Text (*.txt);;Tous (*.*)")
        if path:
            self.ed_out.setText(path)

    def current_options(self) -> Options:
        return Options(
            recursive=self.chk_recursive.isChecked(),
            include_exts=normalize_exts(parse_csv_list(self.ed_exts.text())),
            exclude_dirs=set(parse_csv_list(self.ed_excludedirs.text())),
            ignore_binaries=self.chk_ignore_bin.isChecked(),
            max_mb=self.spin_maxmb.value(),
            add_headers=self.chk_headers.isChecked(),
            normalize_eol=self.chk_norm_eol.isChecked(),
        )

    def gather_candidate_files(self, paths: Iterable[str], opts: Options) -> List[str]:
        return gather_candidate_files(paths, opts)

    def _set_progress(self, i: int, total: int):
        pct = int(i * 100 / max(1, total))
        self.progress.setValue(pct)

    def on_concat(self):
        from PySide6.QtWidgets import QApplication
        if self._concat_running:
            self._cancel_concat = True
            return

        paths = self.listw.checked_paths()
        if not paths:
            QMessageBox.information(self, "Rien à faire", "Coche au moins un élément (ou ajoutez des fichiers/dossiers).")
            return
        opts = self.current_options()
        out_path = self.ed_out.text().strip()
        if not out_path:
            QMessageBox.warning(self, "Chemin manquant", "Spécifiez un fichier de sortie.")
            return

        files = self.gather_candidate_files(paths, opts)
        if not files:
            QMessageBox.information(self, "Aucun fichier", "Aucun fichier correspondant aux critères.")
            return

        self.progress.setValue(0)
        self.btn_concat.setText("Annuler")
        self._cancel_concat = False
        self._concat_running = True

        def cb(i, total):
            self._set_progress(i, total)
            QApplication.processEvents()
            if self._cancel_concat:
                raise ConcatCancelled()

        try:
            written, skipped = concat_to_file(files, opts, out_path, cb)
        except ConcatCancelled:
            self.progress.setValue(0)
            try:
                os.remove(out_path)
            except Exception:
                pass
            QMessageBox.information(self, "Annulé", "Concaténation annulée.")
        else:
            self.progress.setValue(100)
            msg = [f"Concaténation terminée : {written} fichier(s) écrit(s).", f"Sortie : {out_path}",]
            if skipped:
                msg.append("\nFichiers ignorés :")
                msg.extend([f"- {p} ({why})" for p, why in skipped])
            QMessageBox.information(self, "Terminé", "".join(msg))
        finally:
            self.btn_concat.setText("Concaténer")
            self._concat_running = False
            self._cancel_concat = False

    def on_copy_to_clipboard(self):
        from PySide6.QtWidgets import QApplication
        paths = self.listw.checked_paths()
        if not paths:
            QMessageBox.information(self, "Rien à faire", "Coche au moins un élément (ou ajoutez des fichiers/dossiers).")
            return
        opts = self.current_options()
        files = self.gather_candidate_files(paths, opts)
        if not files:
            QMessageBox.information(self, "Aucun fichier", "Aucun fichier correspondant aux critères.")
            return
        self.progress.setValue(0)
        def cb(i, total):
            self._set_progress(i, total)
            QApplication.processEvents()
        final_text, written, skipped = concat_to_string(files, opts, cb)
        self.progress.setValue(100)
        QApplication.clipboard().setText(final_text)
        msg = [f"Concaténation copiée dans le presse-papiers : {written} fichier(s)."]
        if skipped:
            msg.append("Fichiers ignorés :")
            msg.extend([f"- {p} ({why})" for p, why in skipped])
        QMessageBox.information(self, "Presse-papiers", "".join(msg))

    def closeEvent(self, event):
        try:
            if self.dirty:
                name = self.current_profile_name() or "Défaut"
                self.save_profile_to_settings(name)
        finally:
            super().closeEvent(event)
