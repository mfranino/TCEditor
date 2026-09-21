"""TCEditor multi-file launcher: file -> constant-value curve -> channels.

Checked files plot together. Only the active file is edited or saved.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from qtpy import QtCore, QtGui, QtWidgets

from characteristic_parser import CharacteristicData, parse_characteristic_file
from tceditor_3d import CharacteristicWindow3D, Surface3DWindow, _require_pyqtgraph_014

KIND = QtCore.Qt.UserRole
PATH = QtCore.Qt.UserRole + 1
GROUP = QtCore.Qt.UserRole + 2
CHANNEL = QtCore.Qt.UserRole + 3


class NamedSurface3DWindow(Surface3DWindow):
    """Label the constant-value axis using the actual first column (e.g. y)."""

    def _add_reference_axes(self, raw_mins: np.ndarray, raw_maxs: np.ndarray) -> None:
        x_span, y_span, z_span = map(float, self.DISPLAY_SPANS)
        axes = gl.GLAxisItem()
        axes.setSize(x=x_span, y=y_span, z=z_span)
        self.view.addItem(axes)
        grid = gl.GLGridItem()
        grid.setSize(x=x_span, y=y_span)
        grid.setSpacing(x=x_span / 10.0, y=y_span / 10.0)
        grid.translate(x_span / 2.0, y_span / 2.0, 0)
        self.view.addItem(grid)
        font = QtGui.QFont("Arial", 11)
        title_font = QtGui.QFont("Arial", 13)
        title_font.setBold(True)
        color = (20, 20, 20, 255)
        ticks = [np.linspace(raw_mins[i], raw_maxs[i], self.AXIS_TICK_COUNT) for i in range(3)]
        positions = [np.linspace(0, self.DISPLAY_SPANS[i], self.AXIS_TICK_COUNT) for i in range(3)]
        for axis_index in range(3):
            for position, value in zip(positions[axis_index], ticks[axis_index]):
                xyz = [(float(position), -0.38, -0.16),
                       (-0.58, float(position), -0.16),
                       (-0.58, -0.30, float(position))][axis_index]
                self._add_text(xyz, self._format_axis_value(value), font, color)
        self._add_text((x_span + .45, 0, 0), "N11", title_font, color)
        self._add_text((0, y_span + .45, 0), self.data.group_column, title_font, color)
        self._add_text((0, 0, z_span + .45), self.z_channel, title_font, color)


class MultiFileCharacteristicWindow(CharacteristicWindow3D):
    def __init__(self) -> None:
        self.files: dict[str, CharacteristicData] = {}
        self.history: dict[str, tuple[list, list]] = {}
        self.active_path: str | None = None
        self._rebuilding = False
        self._refreshing = False
        super().__init__()

        self.file_tree = QtWidgets.QTreeWidget()
        self.file_tree.setHeaderLabels(["Files / constant-value curves / channels"])
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

        # Keep the original flat widgets as internal editing controls. The tree
        # replaces them for selecting files, curves and individual channels.
        layout = self.group_list.parentWidget().layout()
        for index in (3, 5):
            widget = layout.itemAt(index).widget()
            if widget is not None:
                widget.hide()
        self.group_list.hide()
        self.channel_list.hide()
        self.open_action.setText("Add characteristic files...")
        self.open_button.setText("Add characteristic files...")
        file_menu = self.menuBar().actions()[0].menu()
        self.remove_action = QtWidgets.QAction("Remove active file from workspace", self)
        self.remove_action.triggered.connect(self.remove_active_file)
        self.remove_action.setEnabled(False)
        file_menu.addAction(self.remove_action)
        self.setWindowTitle("TCEditor - multi-file")

    def open_characteristic(self) -> None:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Add characteristic files", "",
            "Characteristic files (*.txt *.dat *.csv);;All files (*.*)")
        if not paths:
            return
        first_new = None
        errors = []
        for name in paths:
            key = str(Path(name).resolve())
            if key in self.files:
                continue
            try:
                self.files[key] = parse_characteristic_file(name)
                self.history[key] = ([], [])
                if first_new is None:
                    first_new = key
            except Exception as exc:
                errors.append(f"{Path(name).name}: {exc}")
        self._rebuild_tree()
        if first_new is not None:
            self._activate(first_new)
        if errors:
            QtWidgets.QMessageBox.warning(self, "Import errors", "\n".join(errors))
        self.statusBar().showMessage(f"{len(self.files)} characteristic file(s) loaded")

    def load_characteristic(self, path: Path) -> None:
        key = str(Path(path).resolve())
        if key not in self.files:
            self.files[key] = parse_characteristic_file(path)
            self.history[key] = ([], [])
        self._rebuild_tree()
        self._activate(key)

    @staticmethod
    def _checked(item: QtWidgets.QTreeWidgetItem) -> bool:
        return item.checkState(0) == QtCore.Qt.Checked

    def _rebuild_tree(self) -> None:
        old = {}
        for i in range(self.file_tree.topLevelItemCount()):
            file_item = self.file_tree.topLevelItem(i)
            path = file_item.data(0, PATH)
            old[(path,)] = self._checked(file_item)
            for j in range(file_item.childCount()):
                group_item = file_item.child(j)
                group_name = group_item.data(0, GROUP)
                old[(path, group_name)] = self._checked(group_item)
                for k in range(group_item.childCount()):
                    child = group_item.child(k)
                    old[(path, group_name, child.data(0, CHANNEL))] = self._checked(child)
        self._rebuilding = True
        self.file_tree.blockSignals(True)
        try:
            self.file_tree.clear()
            for path, data in self.files.items():
                file_item = QtWidgets.QTreeWidgetItem([Path(path).name])
                file_item.setData(0, KIND, "file")
                file_item.setData(0, PATH, path)
                file_item.setToolTip(0, path)
                file_item.setFlags(file_item.flags() | QtCore.Qt.ItemIsUserCheckable)
                file_item.setCheckState(0, QtCore.Qt.Checked if old.get((path,), True) else QtCore.Qt.Unchecked)
                self.file_tree.addTopLevelItem(file_item)
                font = file_item.font(0)
                font.setBold(path == self.active_path)
                file_item.setFont(0, font)
                for group in data.groups:
                    group_item = QtWidgets.QTreeWidgetItem([f"{group.name} ({group.row_count} points)"])
                    group_item.setData(0, KIND, "group")
                    group_item.setData(0, PATH, path)
                    group_item.setData(0, GROUP, group.name)
                    group_item.setFlags(group_item.flags() | QtCore.Qt.ItemIsUserCheckable)
                    group_item.setCheckState(0, QtCore.Qt.Checked if old.get((path, group.name), True) else QtCore.Qt.Unchecked)
                    file_item.addChild(group_item)
                    for channel in group.channels:
                        item = QtWidgets.QTreeWidgetItem([channel])
                        item.setData(0, KIND, "channel")
                        item.setData(0, PATH, path)
                        item.setData(0, GROUP, group.name)
                        item.setData(0, CHANNEL, channel)
                        item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                        default = channel != "N11"
                        item.setCheckState(0, QtCore.Qt.Checked if old.get((path, group.name, channel), default) else QtCore.Qt.Unchecked)
                        group_item.addChild(item)
                file_item.setExpanded(True)
        finally:
            self.file_tree.blockSignals(False)
            self._rebuilding = False
        self.remove_action.setEnabled(bool(self.files))

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
        self.populate_controls()
        self._sync_editor_controls()
        self.refresh_plot()

    def _tree_clicked(self, item, column) -> None:
        path = item.data(0, PATH)
        if path and path != self.active_path:
            self._activate(path)

    def _tree_changed(self, item, column) -> None:
        if not self._rebuilding:
            self.refresh_plot()

    def _visible_curves(self):
        for i in range(self.file_tree.topLevelItemCount()):
            file_item = self.file_tree.topLevelItem(i)
            if not self._checked(file_item):
                continue
            path = file_item.data(0, PATH)
            for j in range(file_item.childCount()):
                group_item = file_item.child(j)
                if not self._checked(group_item):
                    continue
                name = group_item.data(0, GROUP)
                group = next((g for g in self.files[path].groups if g.name == name), None)
                if group is None:
                    continue
                channels = {group_item.child(k).data(0, CHANNEL)
                            for k in range(group_item.childCount())
                            if self._checked(group_item.child(k))}
                yield path, group, channels

    def _sync_editor_controls(self) -> None:
        if self.data is None or self.active_path is None:
            return
        visible = {group.name: channels for path, group, channels in self._visible_curves()
                   if path == self.active_path}
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
            selected = {(group.name, channel) for path, group, channels in self._visible_curves()
                        if path == self.active_path for channel in channels}
            # The legacy plot selector has one channel selection shared by every
            # curve. Remove combinations unchecked at the individual tree node.
            for series in list(self.series_items):
                if (series["group"].name, series["y_channel"]) in selected:
                    continue
                for key in ("line", "points"):
                    item = series[key]
                    self.plot_item.removeItem(item)
                    self.right_view.removeItem(item)
                    if item in self.plot_items:
                        self.plot_items.remove(item)
                try:
                    self.legend.removeItem(series["line"])
                except Exception:
                    pass
                self.series_items.remove(series)
            x_channel = self.x_axis_combo.currentText()
            overlay = False
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
                        name=f"{Path(path).name} / {group.name} / {channel}")
                    if self.axis_for_channel(channel) == "right":
                        self.right_view.addItem(curve)
                    else:
                        self.plot_item.addItem(curve)
                    self.legend.addItem(curve, curve.name())
                    self.plot_items.append(curve)
                    overlay = True
            if overlay and not self.series_items:
                self.plot_item.vb.autoRange()
                self.right_view.autoRange()
        finally:
            self._refreshing = False

    def refresh_after_row_count_change(self) -> None:
        super().refresh_after_row_count_change()
        if hasattr(self, "file_tree"):
            self._rebuild_tree()
            self.refresh_plot()

    def _tree_context_menu(self, position) -> None:
        item = self.file_tree.itemAt(position)
        if item is None:
            return
        menu = QtWidgets.QMenu(self)
        active = menu.addAction("Edit this file")
        add = menu.addAction("Add midpoint group between selected curves")
        delete = menu.addAction("Delete selected curves from active file")
        remove = menu.addAction("Remove file from workspace (keep on disk)")
        action = menu.exec(self.file_tree.viewport().mapToGlobal(position))
        path = item.data(0, PATH)
        if action == active:
            self._activate(path)
        elif action == remove:
            self._remove_file(path)
        elif action in (add, delete):
            names = [node.data(0, GROUP) for node in self.file_tree.selectedItems()
                     if node.data(0, KIND) == "group" and node.data(0, PATH) == path]
            if not names and item.data(0, KIND) == "group":
                names = [item.data(0, GROUP)]
            if path != self.active_path:
                self._activate(path)
            self.group_list.blockSignals(True)
            try:
                for i in range(self.group_list.count()):
                    group_item = self.group_list.item(i)
                    group_item.setSelected(group_item.data(QtCore.Qt.UserRole) in names)
            finally:
                self.group_list.blockSignals(False)
            if action == add:
                self.add_midpoint_group()
            else:
                self.delete_selected_groups()

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
            self.undo_stack, self.redo_stack = [], []
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
        """Use checked curves from all files in one surface, without merging source data."""
        groups = []
        columns = set()
        for path, group, channels in self._visible_curves():
            if channel in channels and "N11" in group.channels:
                groups.append(group)
                columns.add(self.files[path].group_column)
        if len(groups) < 2:
            QtWidgets.QMessageBox.information(
                self, "3D surface", "Check at least two curves containing this channel.")
            return
        if len(columns) != 1:
            QtWidgets.QMessageBox.warning(
                self, "3D surface", "All checked files must have the same constant-value column name.")
            return
        values = [float(group.value) for group in groups]
        if len(set(values)) != len(values):
            QtWidgets.QMessageBox.warning(
                self, "3D surface", "Duplicate constant-value curves selected. Uncheck duplicates before forming a surface.")
            return
        groups.sort(key=lambda group: group.value)
        data = CharacteristicData(
            source_file=self.data.source_file, header=self.data.header, metadata=[],
            group_column=next(iter(columns)), groups=groups)
        try:
            previous = self.surface_windows.get(channel)
            if previous is not None:
                previous.close()
            window = NamedSurface3DWindow(data, channel)
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
