"""Multi-file TCEditor: file -> constant-y group -> channel visibility tree.

Run this launcher to use the existing editor and 3D viewer with several files.
The active file alone is editable and saved; all checked files can be plotted.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from qtpy import QtCore, QtGui, QtWidgets

from characteristic_parser import CharacteristicData, parse_characteristic_file
from tceditor_3d import CharacteristicWindow3D, Surface3DWindow, _require_pyqtgraph_014


ROLE_KIND = QtCore.Qt.UserRole
ROLE_PATH = QtCore.Qt.UserRole + 1
ROLE_GROUP = QtCore.Qt.UserRole + 2
ROLE_CHANNEL = QtCore.Qt.UserRole + 3


class MultiFileCharacteristicWindow(CharacteristicWindow3D):
    """Show many files simultaneously; edit/save one explicitly active file."""

    def __init__(self) -> None:
        # Base class creates the file actions and connects them to the overridden
        # open_characteristic method. Initialize our state first.
        self.files: dict[str, CharacteristicData] = {}
        self.history: dict[str, tuple[list, list]] = {}
        self.active_path: str | None = None
        self._rebuilding = False
        self._refreshing = False
        super().__init__()

        self.file_tree = QtWidgets.QTreeWidget()
        self.file_tree.setHeaderLabels(["Files / constant-y groups / channels"])
        self.file_tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.file_tree.itemChanged.connect(self._tree_changed)
        self.file_tree.itemClicked.connect(self._tree_clicked)
        self.file_tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.file_tree.customContextMenuRequested.connect(self._tree_context_menu)

        dock = QtWidgets.QDockWidget("Characteristic files", self)
        dock.setObjectName("CharacteristicFilesDock")
        dock.setWidget(self.file_tree)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)
        self.resizeDocks([dock], [310], QtCore.Qt.Horizontal)

        # The tree replaces the original flat group/channel selection widgets.
        controls = self.group_list.parentWidget().layout()
        for index in (3, 5):
            widget = controls.itemAt(index).widget()
            if widget is not None:
                widget.hide()
        self.group_list.hide()
        self.channel_list.hide()

        self.open_action.setText("Open characteristic files...")
        self.open_button.setText("Add characteristic files...")
        file_menu = self.menuBar().actions()[0].menu()
        self.remove_file_action = QtWidgets.QAction("Remove active file from workspace", self)
        self.remove_file_action.triggered.connect(self.remove_active_file)
        file_menu.addAction(self.remove_file_action)
        self.remove_file_action.setEnabled(False)
        self.setWindowTitle("TCEditor - multi-file")

    def open_characteristic(self) -> None:
        """Add every selected file; never replace previously loaded files."""
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Add characteristic files", "",
            "Characteristic files (*.txt *.dat *.csv);;All files (*.*)",
        )
        if not paths:
            return
        first_new: str | None = None
        errors: list[str] = []
        for name in paths:
            path = Path(name)
            key = str(path.resolve())
            if key in self.files:
                continue
            try:
                self.files[key] = parse_characteristic_file(path)
                self.history[key] = ([], [])
                if first_new is None:
                    first_new = key
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")
        self._rebuild_tree()
        if first_new is not None:
            self._activate(first_new)
        if errors:
            QtWidgets.QMessageBox.warning(self, "Import errors", "\n".join(errors))
        self.statusBar().showMessage(f"{len(self.files)} characteristic file(s) loaded")

    def load_characteristic(self, path: Path) -> None:
        """Compatibility with callers loading a single path programmatically."""
        key = str(Path(path).resolve())
        if key not in self.files:
            self.files[key] = parse_characteristic_file(path)
            self.history[key] = ([], [])
        self._rebuild_tree()
        self._activate(key)

    def _checked(self, item: QtWidgets.QTreeWidgetItem) -> bool:
        return item.checkState(0) == QtCore.Qt.Checked

    def _rebuild_tree(self) -> None:
        old: dict[tuple, bool] = {}
        root = self.file_tree.invisibleRootItem()
        for i in range(root.childCount()):
            file_item = root.child(i)
            path = file_item.data(0, ROLE_PATH)
            old[(path,)] = self._checked(file_item)
            for j in range(file_item.childCount()):
                group_item = file_item.child(j)
                name = group_item.data(0, ROLE_GROUP)
                old[(path, name)] = self._checked(group_item)
                for k in range(group_item.childCount()):
                    channel_item = group_item.child(k)
                    old[(path, name, channel_item.data(0, ROLE_CHANNEL))] = self._checked(channel_item)

        self._rebuilding = True
        self.file_tree.blockSignals(True)
        try:
            self.file_tree.clear()
            for path, data in self.files.items():
                file_item = QtWidgets.QTreeWidgetItem([Path(path).name])
                file_item.setData(0, ROLE_KIND, "file")
                file_item.setData(0, ROLE_PATH, path)
                file_item.setToolTip(0, path)
                file_item.setFlags(file_item.flags() | QtCore.Qt.ItemIsUserCheckable)
                file_item.setCheckState(0, QtCore.Qt.Checked if old.get((path,), True) else QtCore.Qt.Unchecked)
                self.file_tree.addTopLevelItem(file_item)
                font = file_item.font(0)
                font.setBold(path == self.active_path)
                file_item.setFont(0, font)
                for group in data.groups:
                    group_item = QtWidgets.QTreeWidgetItem([f"{group.name}  ({group.row_count} points)"])
                    group_item.setData(0, ROLE_KIND, "group")
                    group_item.setData(0, ROLE_PATH, path)
                    group_item.setData(0, ROLE_GROUP, group.name)
                    group_item.setFlags(group_item.flags() | QtCore.Qt.ItemIsUserCheckable)
                    group_item.setCheckState(0, QtCore.Qt.Checked if old.get((path, group.name), True) else QtCore.Qt.Unchecked)
                    file_item.addChild(group_item)
                    for channel in group.channels:
                        channel_item = QtWidgets.QTreeWidgetItem([channel])
                        channel_item.setData(0, ROLE_KIND, "channel")
                        channel_item.setData(0, ROLE_PATH, path)
                        channel_item.setData(0, ROLE_GROUP, group.name)
                        channel_item.setData(0, ROLE_CHANNEL, channel)
                        channel_item.setFlags(channel_item.flags() | QtCore.Qt.ItemIsUserCheckable)
                        default = channel != "N11"
                        channel_item.setCheckState(0, QtCore.Qt.Checked if old.get((path, group.name, channel), default) else QtCore.Qt.Unchecked)
                        group_item.addChild(channel_item)
                file_item.setExpanded(True)
        finally:
            self.file_tree.blockSignals(False)
            self._rebuilding = False
        self.remove_file_action.setEnabled(bool(self.files))

    def _activate(self, path: str) -> None:
        if path not in self.files:
            return
        if self.active_path is not None:
            self.history[self.active_path] = (self.undo_stack, self.redo_stack)
        self.clear_plot()
        self.active_path = path
        self.data = self.files[path]
        self.undo_stack, self.redo_stack = self.history[path]
        self.active_drag_original = None
        self.update_undo_action()
        self.save_action.setEnabled(True)
        self.setWindowTitle(f"TCEditor - {Path(path).name} ({len(self.files)} files)")
        self._rebuild_tree()
        # populate_controls calls refresh_plot; the tree is already populated.
        self.populate_controls()
        self._sync_editor_controls()
        self.refresh_plot()

    def _tree_clicked(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        path = item.data(0, ROLE_PATH)
        if path and path != self.active_path:
            self._activate(path)

    def _tree_changed(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        if self._rebuilding:
            return
        self._sync_editor_controls()
        self.refresh_plot()

    def _visible_curves(self):
        for i in range(self.file_tree.topLevelItemCount()):
            file_item = self.file_tree.topLevelItem(i)
            if not self._checked(file_item):
                continue
            path = file_item.data(0, ROLE_PATH)
            for j in range(file_item.childCount()):
                group_item = file_item.child(j)
                if not self._checked(group_item):
                    continue
                name = group_item.data(0, ROLE_GROUP)
                group = next((g for g in self.files[path].groups if g.name == name), None)
                if group is None:
                    continue
                channels = {
                    group_item.child(k).data(0, ROLE_CHANNEL)
                    for k in range(group_item.childCount())
                    if self._checked(group_item.child(k))
                }
                yield path, group, channels

    def _sync_editor_controls(self) -> None:
        if self.data is None or self.active_path is None:
            return
        visible = {
            group.name: channels
            for path, group, channels in self._visible_curves()
            if path == self.active_path
        }
        self.group_list.blockSignals(True)
        self.channel_list.blockSignals(True)
        try:
            for i in range(self.group_list.count()):
                item = self.group_list.item(i)
                item.setSelected(item.data(QtCore.Qt.UserRole) in visible)
            enabled = set().union(*visible.values()) if visible else set()
            for i in range(self.channel_list.count()):
                item = self.channel_list.item(i)
                item.setSelected(item.data(QtCore.Qt.UserRole) in enabled)
        finally:
            self.group_list.blockSignals(False)
            self.channel_list.blockSignals(False)

    def refresh_plot(self) -> None:
        if self._refreshing or self.data is None or not hasattr(self, "file_tree"):
            return
        self._refreshing = True
        try:
            self._sync_editor_controls()
            super().refresh_plot()
            x_channel = self.x_axis_combo.currentText()
            if not x_channel:
                return
            had_overlay = False
            for path, group, channels in self._visible_curves():
                if path == self.active_path:
                    continue
                x = group.channels.get(x_channel)
                if x is None:
                    continue
                for channel in sorted(channels):
                    if channel == x_channel or channel not in group.channels:
                        continue
                    curve = pg.PlotDataItem(
                        x, group.channels[channel],
                        pen=pg.mkPen(pg.intColor(len(self.plot_items) + 3, hues=12), width=1.5),
                        name=f"{Path(path).name} / {group.name} / {channel}",
                    )
                    if self.axis_for_channel(channel) == "right":
                        self.right_view.addItem(curve)
                    else:
                        self.plot_item.addItem(curve)
                    self.legend.addItem(curve, curve.name())
                    self.plot_items.append(curve)
                    had_overlay = True
            if had_overlay and not self.series_items:
                self.plot_item.vb.autoRange()
                self.right_view.autoRange()
        finally:
            self._refreshing = False

    def refresh_after_row_count_change(self) -> None:
        # Keep the file tree synchronized after point/group additions, deletions,
        # and undo/redo operations performed on the active file.
        super().refresh_after_row_count_change()
        if hasattr(self, "file_tree"):
            self._rebuild_tree()
            self._sync_editor_controls()
            self.refresh_plot()

    def _tree_context_menu(self, position) -> None:
        item = self.file_tree.itemAt(position)
        if item is None:
            return
        menu = QtWidgets.QMenu(self)
        active = menu.addAction("Edit this file")
        remove = menu.addAction("Remove file from workspace")
        action = menu.exec(self.file_tree.viewport().mapToGlobal(position))
        path = item.data(0, ROLE_PATH)
        if action == active:
            self._activate(path)
        elif action == remove:
            self._remove_file(path)

    def remove_active_file(self) -> None:
        if self.active_path is not None:
            self._remove_file(self.active_path)

    def _remove_file(self, path: str) -> None:
        if path not in self.files:
            return
        was_active = path == self.active_path
        del self.files[path]
        self.history.pop(path, None)
        if was_active:
            self.active_path = None
            self.data = None
            self.clear_plot()
            self.group_list.clear()
            self.channel_list.clear()
            self.x_axis_combo.clear()
            self.metadata_view.clear()
            self.populate_data_table()
            self.save_action.setEnabled(False)
            self.undo_stack = []
            self.redo_stack = []
            self.update_undo_action()
        self._rebuild_tree()
        if was_active and self.files:
            self._activate(next(iter(self.files)))
        elif self.data is not None:
            self.refresh_plot()
        else:
            self.setWindowTitle("TCEditor - multi-file")
        self.statusBar().showMessage(f"{len(self.files)} characteristic file(s) loaded")

    def show_3d_surface(self, channel: str) -> None:
        """Build one surface from checked groups in all files (not just active)."""
        groups = []
        columns = set()
        for path, group, channels in self._visible_curves():
            if channel in channels and "N11" in group.channels:
                groups.append(group)
                columns.add(self.files[path].group_column)
        if len(groups) < 2:
            QtWidgets.QMessageBox.information(self, "3D surface", "Select at least two constant-y groups with this channel in the file tree.")
            return
        if len(columns) != 1:
            QtWidgets.QMessageBox.warning(self, "3D surface", "Selected files must use the same constant-value group column.")
            return
        values = [float(group.value) for group in groups]
        if len(set(values)) != len(values):
            QtWidgets.QMessageBox.warning(self, "3D surface", "Two selected curves have the same constant-y value. Uncheck duplicates to define an unambiguous surface.")
            return
        groups.sort(key=lambda group: group.value)
        data = CharacteristicData(
            source_file=self.data.source_file,
            header=self.data.header,
            metadata=[],
            group_column=next(iter(columns)),
            groups=groups,
        )
        try:
            previous = self.surface_windows.get(channel)
            if previous is not None:
                previous.close()
            window = Surface3DWindow(data, channel)
            self.surface_windows[channel] = window
            window.destroyed.connect(lambda _=None, name=channel: self._forget_surface_window(name))
            window.show()
            window.raise_()
            window.activateWindow()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "3D surface error", str(exc))


def main() -> int:
    _require_pyqtgraph_014()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    pg.setConfigOptions(antialias=True)
    window = MultiFileCharacteristicWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
