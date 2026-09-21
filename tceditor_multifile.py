"""Multi-file characteristic editor with global channel selection.

Tree checkboxes select files and constant-y curves; the original Y channels
list selects channels for every visible curve, as in the single-file editor.
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


class NamedSurface3DWindow(Surface3DWindow):
    """Show the true group-column label, rather than hardcoded a0."""

    def _add_reference_axes(self, raw_mins: np.ndarray, raw_maxs: np.ndarray) -> None:
        x_span, y_span, z_span = map(float, self.DISPLAY_SPANS)
        axes = gl.GLAxisItem()
        axes.setSize(x=x_span, y=y_span, z=z_span)
        self.view.addItem(axes)
        grid = gl.GLGridItem()
        grid.setSize(x=x_span, y=y_span)
        grid.setSpacing(x=x_span / 10, y=y_span / 10)
        grid.translate(x_span / 2, y_span / 2, 0)
        self.view.addItem(grid)
        font = QtGui.QFont("Arial", 11)
        title_font = QtGui.QFont("Arial", 13)
        title_font.setBold(True)
        color = (20, 20, 20, 255)
        for axis_index in range(3):
            values = np.linspace(raw_mins[axis_index], raw_maxs[axis_index], self.AXIS_TICK_COUNT)
            positions = np.linspace(0, self.DISPLAY_SPANS[axis_index], self.AXIS_TICK_COUNT)
            for position, value in zip(positions, values):
                xyz = [(float(position), -.38, -.16),
                       (-.58, float(position), -.16),
                       (-.58, -.30, float(position))][axis_index]
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
        self._global_channels_initialized = False
        super().__init__()

        self.file_tree = QtWidgets.QTreeWidget()
        self.file_tree.setHeaderLabels(["Files / constant-y curves"])
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

        # Hide ONLY the obsolete flat group controls. Restore the original
        # shared Y-channel selector, keeping N11 available as an X-axis choice.
        layout = self.group_list.parentWidget().layout()
        layout.itemAt(3).widget().hide()  # Groups label
        self.group_list.hide()
        self.channel_list.show()
        layout.itemAt(5).widget().show()  # Y channels label
        self.channel_list.itemSelectionChanged.connect(self.refresh_plot)

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
                old[(path, group_item.data(0, GROUP))] = self._checked(group_item)
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
                    item = QtWidgets.QTreeWidgetItem([f"{group.name} ({group.row_count} points)"])
                    item.setData(0, KIND, "group")
                    item.setData(0, PATH, path)
                    item.setData(0, GROUP, group.name)
                    item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                    item.setCheckState(0, QtCore.Qt.Checked if old.get((path, group.name), True) else QtCore.Qt.Unchecked)
                    file_item.addChild(item)
                file_item.setExpanded(True)
        finally:
            self.file_tree.blockSignals(False)
            self._rebuilding = False
        self.remove_action.setEnabled(bool(self.files))

    def _selected_channels(self) -> set[str]:
        return {item.data(QtCore.Qt.UserRole) for item in self.channel_list.selectedItems()}

    def _populate_global_channels(self, previous: set[str] | None) -> None:
        channels = []
        for data in self.files.values():
            for group in data.groups:
                for channel in group.channels:
                    if channel not in channels:
                        channels.append(channel)
        self.channel_list.blockSignals(True)
        try:
            self.channel_list.clear()
            for channel in channels:
                item = QtWidgets.QListWidgetItem(channel)
                item.setData(QtCore.Qt.UserRole, channel)
                self.channel_list.addItem(item)
                default_selected = channel != self.x_axis_combo.currentText()
                item.setSelected(default_selected if previous is None else channel in previous)
        finally:
            self.channel_list.blockSignals(False)
        self._global_channels_initialized = True

    def _activate(self, path: str) -> None:
        if path not in self.files:
            return
        selected = self._selected_channels() if self._global_channels_initialized else None
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
        self._populate_global_channels(selected)
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
                item = file_item.child(j)
                if not self._checked(item):
                    continue
                name = item.data(0, GROUP)
                group = next((g for g in self.files[path].groups if g.name == name), None)
                if group is not None:
                    yield path, group

    def _sync_editor_groups(self) -> None:
        if self.data is None or self.active_path is None:
            return
        visible = {group.name for path, group in self._visible_curves() if path == self.active_path}
        self.group_list.blockSignals(True)
        try:
            for i in range(self.group_list.count()):
                item = self.group_list.item(i)
                item.setSelected(item.data(QtCore.Qt.UserRole) in visible)
        finally:
            self.group_list.blockSignals(False)

    def refresh_plot(self) -> None:
        if self._refreshing or self.data is None or not hasattr(self, "file_tree"):
            return
        self._refreshing = True
        try:
            self._sync_editor_groups()
            super().refresh_plot()
            channels = self._selected_channels()
            x_channel = self.x_axis_combo.currentText()
            overlay = False
            for path, group in self._visible_curves():
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
        selected = self._selected_channels()
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
            self._global_channels_initialized = False
        self._rebuild_tree()
        if was_active and self.files:
            self._activate(next(iter(self.files)))
            self._populate_global_channels(selected)
            self.refresh_plot()
        elif self.data is not None:
            self._populate_global_channels(selected)
            self.refresh_plot()
        else:
            self.setWindowTitle("TCEditor - multi-file")
        self.statusBar().showMessage(f"{len(self.files)} characteristic file(s) loaded")

    def show_3d_surface(self, channel: str) -> None:
        if channel not in self._selected_channels():
            QtWidgets.QMessageBox.information(self, "3D surface", f"Select {channel} in the global Y channels list first.")
            return
        groups = []
        columns = set()
        for path, group in self._visible_curves():
            if channel in group.channels and "N11" in group.channels:
                groups.append(group)
                columns.add(self.files[path].group_column)
        if len(groups) < 2:
            QtWidgets.QMessageBox.information(self, "3D surface", "Check at least two curves containing this channel.")
            return
        if len(columns) != 1:
            QtWidgets.QMessageBox.warning(self, "3D surface", "All checked files must have the same constant-value column name.")
            return
        values = [float(group.value) for group in groups]
        if len(set(values)) != len(values):
            QtWidgets.QMessageBox.warning(self, "3D surface", "Duplicate constant-value curves selected. Uncheck duplicates before forming a surface.")
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
