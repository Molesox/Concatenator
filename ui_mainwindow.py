# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import pathlib
from typing import Iterable, List, Optional, cast

from PySide6.QtCore import Qt, QMimeData, QSize, QSettings, QCoreApplication, QUrl, QByteArray
from PySide6.QtGui import QPalette, QAction, QDesktopServices
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QFileDialog, QLineEdit,
    QCheckBox, QDoubleSpinBox, QLabel, QMessageBox, QProgressBar, QGroupBox,
    QSplitter, QComboBox, QInputDialog, QAbstractItemView
)

from models import Options
from core import (
    unique_paths, parse_csv_list, normalize_exts, human_size,
    gather_candidate_files, concat_to_file, concat_to_string
)


# ------------------------ Widgets ------------------------

class DropListWidget(QListWidget):
    """QListWidget avec support glisser-déposer de fichiers/dossiers + cases à cocher."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setMinimumHeight(200)
        self.setStyleSheet(
            """
            QListWidget { border: 1px solid #888; border-radius: 10px; padding: 6px; }
            QListWidget::item { padding: 6px; }
            """
        )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        md: QMimeData = event.mimeData()
        if md.hasUrls():
            paths = []
            for url in md.urls():
                p = url.toLocalFile()
                if p:
                    paths.append(p)
            self.add_paths(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def add_paths(self, paths: Iterable[str]):
        existing = {self.item(i).text() for i in range(self.count())}
        for p in unique_paths(paths):
            if p not in existing:
                it = QListWidgetItem(p)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked)  # coché par défaut
                self.addItem(it)

    def selected_paths(self) -> List[str]:
        return [i.text() for i in self.selectedItems()]

    def all_paths(self) -> List[str]:
        return [self.item(i).text() for i in range(self.count())]

    def checked_paths(self) -> List[str]:
        out: List[str] = []
        for i in range(self.count()):
            it = self.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(it.text())
        return out


# ------------------------ Fenêtre principale ------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ConcatFiles – Sélection & concaténation")
        self.resize(980, 680)

        # Style Fusion agréable
        from PySide6.QtWidgets import QApplication
        QApplication.setStyle('Fusion')
        pal = self.palette()
        pal.setColor(
            QPalette.ColorRole.Highlight,
            pal.color(QPalette.ColorRole.Link)
        )
        self.setPalette(pal)

        self.dirty = False
        self._block_dirty = False

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # --- Barre Profils ---
        prof_row = QHBoxLayout()
        self.cmb_profile = QComboBox()
        self.cmb_profile.setMinimumWidth(220)
        self.btn_prof_new = QPushButton("Nouveau…")
        self.btn_prof_save = QPushButton("Enregistrer")
        self.btn_prof_rename = QPushButton("Renommer…")
        self.btn_prof_delete = QPushButton("Supprimer")
        prof_row.addWidget(QLabel("Profil :"))
        prof_row.addWidget(self.cmb_profile, 1)
        prof_row.addWidget(self.btn_prof_new)
        prof_row.addWidget(self.btn_prof_save)
        prof_row.addWidget(self.btn_prof_rename)
        prof_row.addWidget(self.btn_prof_delete)
        root.addLayout(prof_row)

        # --- Ligne de boutons haut ---
        top = QHBoxLayout()
        self.btn_add_files = QPushButton("Ajouter des fichiers…")
        self.btn_add_dirs = QPushButton("Ajouter des dossiers…")
        self.btn_remove = QPushButton("Supprimer la sélection")
        self.btn_clear = QPushButton("Vider")
        top.addWidget(self.btn_add_files)
        top.addWidget(self.btn_add_dirs)
        top.addStretch(1)
        top.addWidget(self.btn_remove)
        top.addWidget(self.btn_clear)
        root.addLayout(top)

        # --- Splitter: liste à gauche, options à droite ---
        self.split = QSplitter()
        self.split.setChildrenCollapsible(False)
        root.addWidget(self.split, 1)

        # Liste avec drag & drop
        self.listw = DropListWidget()
        self.listw.setToolTip("Glissez-déposez des fichiers/dossiers ici")
        self.split.addWidget(self.listw)

        # Panneau options
        opts_panel = QWidget()
        opts_layout = QVBoxLayout(opts_panel)

        # Filtre extensions
        gb_filter = QGroupBox("Filtre d'extensions (vide = tout)")
        ly_filter = QHBoxLayout(gb_filter)
        self.ed_exts = QLineEdit(".py,.ts,.tsx,.js,.java,.kt,.cs,.cpp,.h,.hpp")
        ly_filter.addWidget(QLabel("Extensions :"))
        ly_filter.addWidget(self.ed_exts)
        opts_layout.addWidget(gb_filter)

        # Exclusions dossiers
        gb_ex = QGroupBox("Exclure ces dossiers (noms, virgules)")
        ly_ex = QHBoxLayout(gb_ex)
        self.ed_excludedirs = QLineEdit(".git,node_modules,venv,build,dist,.idea,.vscode,target,bin,obj")
        ly_ex.addWidget(QLabel("Dossiers :"))
        ly_ex.addWidget(self.ed_excludedirs)
        opts_layout.addWidget(gb_ex)

        # Cases à cocher
        gb_flags = QGroupBox("Options")
        from PySide6.QtWidgets import QVBoxLayout as _QVBox
        ly_flags = _QVBox(gb_flags)
        self.chk_recursive = QCheckBox("Récursif pour les dossiers")
        self.chk_recursive.setChecked(True)
        self.chk_headers = QCheckBox("Ajouter un séparateur avec le chemin du fichier")
        self.chk_headers.setChecked(True)
        self.chk_ignore_bin = QCheckBox("Ignorer les fichiers binaires")
        self.chk_ignore_bin.setChecked(True)
        self.chk_norm_eol = QCheckBox("Normaliser les fins de ligne en \n")
        self.chk_norm_eol.setChecked(True)
        ly_flags.addWidget(self.chk_recursive)
        ly_flags.addWidget(self.chk_headers)
        ly_flags.addWidget(self.chk_ignore_bin)
        ly_flags.addWidget(self.chk_norm_eol)

        # Limite taille
        hl_size = QHBoxLayout()
        self.spin_maxmb = QDoubleSpinBox()
        self.spin_maxmb.setDecimals(1)
        self.spin_maxmb.setRange(0.1, 1024.0)
        self.spin_maxmb.setSingleStep(0.5)
        self.spin_maxmb.setValue(5.0)
        hl_size.addWidget(QLabel("Taille max / fichier :"))
        hl_size.addWidget(self.spin_maxmb)
        hl_size.addWidget(QLabel("Mo"))
        ly_flags.addLayout(hl_size)

        opts_layout.addWidget(gb_flags)
        opts_layout.addStretch(1)
        self.split.addWidget(opts_panel)
        self.split.setSizes([640, 340])

        # --- Sortie ---
        out_row = QHBoxLayout()
        self.ed_out = QLineEdit(str(pathlib.Path.home() / 'concat.txt'))
        self.btn_browse_out = QPushButton("Parcourir…")
        self.btn_browse_out.setMinimumWidth(160)
        self.btn_open_out = QPushButton("Ouvrir")
        self.btn_open_out.setMinimumWidth(160)

        out_row.addWidget(QLabel("Fichier de sortie :"))
        out_row.addWidget(self.ed_out, 1)
        out_row.addWidget(self.btn_browse_out)
        out_row.addWidget(self.btn_open_out)
        root.addLayout(out_row)

        # --- Actions ---
        actions = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.btn_concat = QPushButton("Concaténer →")
        self.btn_concat.setMinimumWidth(160)
        self.btn_copy = QPushButton("+ au presse-papiers")
        self.btn_copy.setMinimumWidth(160)
        actions.addWidget(self.progress, 1)
        actions.addWidget(self.btn_concat)
        actions.addWidget(self.btn_copy)
        root.addLayout(actions)

        # Menu (petit +)
        act_quit = QAction("Quitter", self)
        act_quit.triggered.connect(self.close)
        self.menuBar().addAction(act_quit)

        # Connexions
        self.btn_add_files.clicked.connect(self.on_add_files)
        self.btn_add_dirs.clicked.connect(self.on_add_dirs)
        self.btn_remove.clicked.connect(self.on_remove_selected)
        self.btn_clear.clicked.connect(self.on_clear)
        self.btn_browse_out.clicked.connect(self.on_browse_out)
        self.btn_concat.clicked.connect(self.on_concat)
        self.btn_copy.clicked.connect(self.on_copy_to_clipboard)
        self.btn_open_out.clicked.connect(self.on_open_out)

        # Profils
        self.cmb_profile.currentIndexChanged.connect(self.on_profile_combo_changed)
        self.btn_prof_new.clicked.connect(self.on_profile_new)
        self.btn_prof_save.clicked.connect(self.on_profile_save)
        self.btn_prof_rename.clicked.connect(self.on_profile_rename)
        self.btn_prof_delete.clicked.connect(self.on_profile_delete)

        # Marquage dirty
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

        # Charger profils & état
        self.init_profiles_and_load()

    # ----- Dirty helpers -----
    def mark_dirty(self, *args):
        if self._block_dirty:
            return
        self.dirty = True
        self.setWindowTitle("ConcatFiles – Sélection & concaténation*")

    def clear_dirty(self):
        self.dirty = False
        self.setWindowTitle("ConcatFiles – Sélection & concaténation")

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
        name = self.cmb_profile.itemText(idx)
        if self.dirty:
            res = QMessageBox.question(
                self, "Profil modifié",
                "Voulez-vous enregistrer les modifications dans le profil courant avant de changer ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes
            )
            if res == QMessageBox.StandardButton.Cancel:
                self.cmb_profile.blockSignals(True)
                self.cmb_profile.setCurrentIndex(getattr(self, "_last_profile_index", idx))
                self.cmb_profile.blockSignals(False)
                return
            elif res == QMessageBox.StandardButton.Yes:
                old_name = self.cmb_profile.itemText(getattr(self, "_last_profile_index", idx))
                self.save_profile_to_settings(old_name)

        self.load_profile_from_settings(name)
        self._last_profile_index = idx

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

    def on_profile_save(self):
        name = self.current_profile_name()
        if not name:
            QMessageBox.warning(self, "Aucun profil", "Aucun profil sélectionné.")
            return
        self.save_profile_to_settings(name)
        self.clear_dirty()
        QMessageBox.information(self, "Profil enregistré", f"Profil '{name}' mis à jour.")

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

    # ----- Enregistrement / chargement d'un profil -----
    def save_profile_to_settings(self, prof_name: str):
        s = QSettings()
        s.beginGroup(self.profiles_root())
        s.beginGroup(prof_name)

        items = []
        for i in range(self.listw.count()):
            it = self.listw.item(i)
            chk = '1' if it.checkState() == Qt.CheckState.Checked else '0'
            items.append(f"{it.text()}|{chk}")
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
                    it = QListWidgetItem(path)
                    it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    it.setCheckState(Qt.CheckState.Checked if chk == '1' else Qt.CheckState.Unchecked)
                    self.listw.addItem(it)

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

            outp = s.value("out/path")
            if outp:
                self.ed_out.setText(outp)

            geo = s.value("ui/geometry")
            if geo:
                self.restoreGeometry(geo)
            st = s.value("ui/state")
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

            self._last_profile_index = self.cmb_profile.currentIndex()
            self.clear_dirty()
            QSettings().setValue("profiles/current", prof_name)
        finally:
            self._block_dirty = False

    def init_profiles_and_load(self):
        # Organisation et app déjà fixés dans main.py
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
            self.mark_dirty()

    def on_add_dirs(self):
        dirpath = QFileDialog.getExistingDirectory(self, "Choisir un dossier")
        if dirpath:
            self.listw.add_paths([dirpath])
            self.mark_dirty()

    def on_remove_selected(self):
        for item in self.listw.selectedItems():
            self.listw.takeItem(self.listw.row(item))
        self.mark_dirty()

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

    def gather_candidate_files(self, roots: Iterable[str], opts: Options) -> List[str]:
        return gather_candidate_files(roots, opts)

    def _set_progress(self, i: int, total: int):
        pct = int(i * 100 / max(1, total))
        self.progress.setValue(pct)

    def on_concat(self):
        from PySide6.QtWidgets import QApplication
        roots = self.listw.checked_paths()
        if not roots:
            QMessageBox.information(self, "Rien à faire", "Coche au moins un élément (ou ajoutez des fichiers/dossiers).")
            return

        opts = self.current_options()
        out_path = self.ed_out.text().strip()
        if not out_path:
            QMessageBox.warning(self, "Chemin manquant", "Spécifiez un fichier de sortie.")
            return

        files = self.gather_candidate_files(roots, opts)
        if not files:
            QMessageBox.information(self, "Aucun fichier", "Aucun fichier correspondant aux critères.")
            return

        self.progress.setValue(0)
        def cb(i, total):
            self._set_progress(i, total)
            QApplication.processEvents()

        written, skipped = concat_to_file(files, opts, out_path, cb)
        self.progress.setValue(100)

        msg = [
            f"Concaténation terminée : {written} fichier(s) écrit(s).",
            f"Sortie : {out_path}",
        ]
        if skipped:
            msg.append("\nFichiers ignorés :")
            msg.extend([f"- {p} ({why})" for p, why in skipped])

        QMessageBox.information(self, "Terminé", "".join(msg))

    def on_copy_to_clipboard(self):
        from PySide6.QtWidgets import QApplication
        roots = self.listw.checked_paths()
        if not roots:
            QMessageBox.information(self, "Rien à faire", "Coche au moins un élément (ou ajoutez des fichiers/dossiers).")
            return

        opts = self.current_options()
        files = self.gather_candidate_files(roots, opts)
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

    # ----- Sauvegarde à la fermeture -----
    def closeEvent(self, event):
        try:
            if self.dirty:
                name = self.current_profile_name() or "Défaut"
                self.save_profile_to_settings(name)
        finally:
            super().closeEvent(event)