"""TCEditor: resizable controls, versioning, and read-only VIS overlays.

Characteristic curves and VIS measurements are separate datasets. Selecting a
VIS curve draws its recorded Q11 vs N11 on the main chart without converting
Time into a characteristic group or modifying the characteristic save target.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from qtpy import QtCore, QtWidgets

from tceditor_3d import _require_pyqtgraph_014
from tceditor_multifile import KIND, PATH, GROUP, MultiFileCharacteristicWindow
from tceditor_vis import parse_vis_file

VERSION_BASE_COMMIT = "7ef877635ddfafaf472b15dfdc5f40f0a1eb18c8"
VIS_KIND = "vis_file"
VIS_CURVE_KIND = "vis_curve"


def build_version() -> tuple[str, str]:
    """Return (version, revision) from this file's Git checkout."""
    directory = Path(__file__).resolve().parent

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(directory), *args],
            capture_output=True, text=True, check=True, timeout=3,
        ).stdout.strip()

    try:
        git("merge-base", "--is-ancestor", VERSION_BASE_COMMIT, "HEAD")
        count = int(git("rev-list", "--count", f"{VERSION_BASE_COMMIT}..HEAD"))
        return f"0.0.{max(count, 1)}", git("rev-parse", "--short=7", "HEAD")
    except (OSError, ValueError, subprocess.SubprocessError):
        return "0.0.1", "Git revision unavailable"


class StackedCharacteristicWindow(MultiFileCharacteristicWindow):
    """Resizable multi-file characteristic editor with VIS comparison datasets."""

    def __init__(self) -> None:
        self.vis_files = {}
        self._rendering_vis = False
        super().__init__()

        self.file_tree.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.file_tree.setHeaderLabels(["Datasets / curves (click to add/remove)"])
        self.file_tree.setToolTip(
            "Select constant-y characteristic curves and VIS Q11(N11) curves. "
            "File headings are containers."
        )
        self._disable_file_row_selection()

        main_splitter = self.centralWidget()
        old_controls = self.group_list.parentWidget()
        old_layout = old_controls.layout()
        self._legacy_controls = old_controls
        x_label = old_layout.itemAt(1).widget()
        channels_label = old_layout.itemAt(5).widget()
        metadata_label = old_layout.itemAt(7).widget()
        for widget in (self.open_button, x_label, self.x_axis_combo,
                       channels_label, self.channel_list,
                       metadata_label, self.metadata_view):
            old_layout.removeWidget(widget)

        dock = self.findChild(QtWidgets.QDockWidget, "CharacteristicFilesDock")
        if dock is None or dock.widget() is not self.file_tree:
            raise RuntimeError("Multi-file tree dock was not found.")
        self.removeDockWidget(dock)
        dock.hide()
        old_controls.setParent(None)
        old_controls.hide()

        sidebar = QtWidgets.QWidget()
        sidebar.setMinimumWidth(240)
        sidebar_layout = QtWidgets.QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(5, 5, 5, 5)
        sidebar_layout.setSpacing(5)
        sidebar_layout.addWidget(self.open_button)
        sidebar_layout.addWidget(x_label)
        sidebar_layout.addWidget(self.x_axis_combo)

        vertical = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        vertical.setObjectName("ResizableControlColumn")
        vertical.setChildrenCollapsible(False)
        self.file_tree.setMinimumHeight(100)
        vertical.addWidget(self.file_tree)

        channel_panel = QtWidgets.QWidget()
        channel_layout = QtWidgets.QVBoxLayout(channel_panel)
        channel_layout.setContentsMargins(0, 0, 0, 0)
        channel_layout.addWidget(channels_label)
        channel_layout.addWidget(self.channel_list, 1)
        channel_panel.setMinimumHeight(75)
        vertical.addWidget(channel_panel)

        metadata_panel = QtWidgets.QWidget()
        metadata_layout = QtWidgets.QVBoxLayout(metadata_panel)
        metadata_layout.setContentsMargins(0, 0, 0, 0)
        metadata_layout.addWidget(metadata_label)
        metadata_layout.addWidget(self.metadata_view, 1)
        metadata_panel.setMinimumHeight(75)
        vertical.addWidget(metadata_panel)

        dock.deleteLater()
        sidebar_layout.addWidget(vertical, 1)
        self.control_splitter = vertical
        main_splitter.insertWidget(0, sidebar)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setStretchFactor(2, 0)
        main_splitter.setSizes([330, 750, 330])
        vertical.setSizes([410, 180, 175])

        self.vis_action = QtWidgets.QAction("Import VIS measurement files...", self)
        self.vis_action.triggered.connect(self.import_vis_files)
        file_menu = self.menuBar().actions()[0].menu()
        file_menu.insertAction(self.save_action, self.vis_action)

        self.app_version, self.app_revision = build_version()
        self.version_label = QtWidgets.QLabel(
            f"v{self.app_version}  |  {self.app_revision}"
        )
        self.statusBar().addPermanentWidget(self.version_label)
        self._apply_version_title()

    def _apply_version_title(self) -> None:
        file_name = Path(self.active_path).name if self.active_path else "multi-file"
        self.setWindowTitle(
            f"TCEditor v{self.app_version} [{self.app_revision}] - {file_name} "
            f"({len(self.files)} characteristic, {len(self.vis_files)} VIS files)"
        )

    def _disable_file_row_selection(self) -> None:
        """File headings are navigation containers, not 'plot all' commands."""
        self.file_tree.blockSignals(True)
        try:
            for index in range(self.file_tree.topLevelItemCount()):
                item = self.file_tree.topLevelItem(index)
                item.setSelected(False)
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsSelectable)
        finally:
            self.file_tree.blockSignals(False)

    def _rebuild_tree(self) -> None:
        # The base rebuilds characteristic nodes. Restore VIS selection after
        # adding each read-only VIS dataset as its own parent/child pair.
        previous_vis = set()
        if hasattr(self, "file_tree"):
            previous_vis = {
                item.data(0, PATH) for item in self.file_tree.selectedItems()
                if item.data(0, KIND) == VIS_CURVE_KIND
            }
        super()._rebuild_tree()
        self.file_tree.blockSignals(True)
        try:
            for path, measurement in self.vis_files.items():
                heading = QtWidgets.QTreeWidgetItem([f"{Path(path).name} [VIS, read-only]"])
                heading.setData(0, KIND, VIS_KIND)
                heading.setData(0, PATH, path)
                heading.setToolTip(0, path)
                heading.setFlags(heading.flags() & ~QtCore.Qt.ItemIsSelectable)
                self.file_tree.addTopLevelItem(heading)
                x = self._vis_channel(measurement, "N11")
                y = self._vis_channel(measurement, "Q11")
                if x is not None and y is not None:
                    child = QtWidgets.QTreeWidgetItem([f"Q11 vs N11 ({len(measurement.time)} points)"])
                    child.setData(0, KIND, VIS_CURVE_KIND)
                    child.setData(0, PATH, path)
                    heading.addChild(child)
                    child.setSelected(path in previous_vis)
                heading.setExpanded(True)
        finally:
            self.file_tree.blockSignals(False)
        self._disable_file_row_selection()

    @staticmethod
    def _vis_channel(measurement, name: str):
        return next((values for channel, values in measurement.channels.items()
                     if channel.casefold() == name.casefold()), None)

    def import_vis_files(self) -> None:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Import VIS measurements", "",
            "VIS measurement files (*.vis *.VIS);;All files (*.*)")
        if paths:
            self.load_vis_files(paths)

    def load_vis_files(self, paths) -> None:
        """Import into independent read-only datasets; select new VIS curves."""
        added = []
        errors = []
        for filename in paths:
            path = Path(filename).resolve()
            key = str(path)
            if key in self.vis_files:
                continue
            try:
                data = parse_vis_file(path)
                if self._vis_channel(data, "N11") is None or self._vis_channel(data, "Q11") is None:
                    raise ValueError("Required N11 and Q11 channels not found in VIS file.")
                self.vis_files[key] = data
                added.append(key)
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")

        if added and self.data is None:
            # Allow a VIS file to be the first/only imported dataset.
            self.x_axis_combo.blockSignals(True)
            self.channel_list.blockSignals(True)
            try:
                if self.x_axis_combo.findText("N11") < 0:
                    self.x_axis_combo.addItem("N11")
                self.x_axis_combo.setCurrentText("N11")
                if not any(self.channel_list.item(i).data(QtCore.Qt.UserRole) == "Q11"
                           for i in range(self.channel_list.count())):
                    item = QtWidgets.QListWidgetItem("Q11")
                    item.setData(QtCore.Qt.UserRole, "Q11")
                    self.channel_list.addItem(item)
                    item.setSelected(True)
            finally:
                self.x_axis_combo.blockSignals(False)
                self.channel_list.blockSignals(False)

        self._rebuild_tree()
        self.file_tree.blockSignals(True)
        try:
            for index in range(self.file_tree.topLevelItemCount()):
                parent = self.file_tree.topLevelItem(index)
                if parent.data(0, KIND) == VIS_KIND and parent.data(0, PATH) in added:
                    if parent.childCount():
                        parent.child(0).setSelected(True)
        finally:
            self.file_tree.blockSignals(False)
        self.refresh_plot()
        if hasattr(self, "app_version"):
            self._apply_version_title()
        if errors:
            QtWidgets.QMessageBox.warning(self, "VIS import errors", "\n".join(errors))
        self.statusBar().showMessage(
            f"Imported {len(added)} VIS dataset(s); {len(self.vis_files)} VIS file(s) loaded. "
            "VIS imports are read-only."
        )

    def _visible_curves(self):
        """Characteristic plotting and meshing use characteristic rows only."""
        selected = {
            (item.data(0, PATH), item.data(0, GROUP))
            for item in self.file_tree.selectedItems()
            if item.data(0, KIND) == "group"
        }
        for path, data in self.files.items():
            for group in data.groups:
                if (path, group.name) in selected:
                    yield path, group

    def refresh_plot(self) -> None:
        if (self._rendering_vis or self._rebuilding or
                not hasattr(self, "file_tree") or not hasattr(self, "plot_item")):
            return
        self._rendering_vis = True
        try:
            # The existing editor clears/rebuilds its original characteristic
            # curves and other-file overlays; VIS is added afterwards.
            if self.data is None:
                self.clear_plot()
            else:
                super().refresh_plot()
            if self.x_axis_combo.currentText().casefold() != "n11":
                return
            if "q11" not in {channel.casefold() for channel in self._selected_channels()}:
                return
            selected_vis = {
                item.data(0, PATH) for item in self.file_tree.selectedItems()
                if item.data(0, KIND) == VIS_CURVE_KIND
            }
            count = 0
            for path, measurement in self.vis_files.items():
                if path not in selected_vis:
                    continue
                x = self._vis_channel(measurement, "N11")
                y = self._vis_channel(measurement, "Q11")
                if x is None or y is None:
                    continue
                mask = np.isfinite(x) & np.isfinite(y)
                if not np.any(mask):
                    continue
                curve = pg.PlotDataItem(
                    x[mask], y[mask],
                    pen=pg.mkPen(pg.intColor(len(self.plot_items) + count + 2, hues=16), width=2),
                    name=f"VIS: {measurement.source_file.name} / Q11",
                )
                self.plot_item.addItem(curve)
                self.legend.addItem(curve, curve.name())
                self.plot_items.append(curve)
                count += 1
            if count:
                self.plot.setLabel("bottom", "N11")
                self.plot_item.vb.autoRange()
                self.right_view.autoRange()
        finally:
            self._rendering_vis = False

    def _tree_clicked(self, item, column) -> None:
        """Selecting curves never silently changes the active save target."""
        self.refresh_plot()

    def _tree_context_menu(self, position) -> None:
        item = self.file_tree.itemAt(position)
        if item is not None and item.data(0, KIND) in {VIS_KIND, VIS_CURVE_KIND}:
            menu = QtWidgets.QMenu(self)
            remove = menu.addAction("Remove VIS dataset from workspace (keep on disk)")
            action = menu.exec(self.file_tree.viewport().mapToGlobal(position))
            if action == remove:
                path = item.data(0, PATH)
                self.vis_files.pop(path, None)
                self._rebuild_tree()
                self.refresh_plot()
                self._apply_version_title()
            return
        super()._tree_context_menu(position)

    def _activate(self, path: str) -> None:
        super()._activate(path)
        if hasattr(self, "app_version"):
            self._apply_version_title()

    def _remove_file(self, path: str) -> None:
        super()._remove_file(path)
        if hasattr(self, "app_version"):
            self._apply_version_title()


def main() -> int:
    _require_pyqtgraph_014()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    pg.setConfigOptions(antialias=True)
    window = StackedCharacteristicWindow()
    print(f"TCEditor v{window.app_version} [{window.app_revision}]")
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
