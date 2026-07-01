from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from qtpy import QtCore, QtGui, QtWidgets

from characteristic_parser import (
    CharacteristicData,
    CharacteristicGroup,
    parse_characteristic_file,
    write_characteristic_file,
)


class DraggablePointItem(pg.ScatterPlotItem):
    def __init__(
        self,
        point_drag_started_callback,
        point_moved_callback,
        point_drag_finished_callback,
        point_delete_callback,
        point_add_callback,
        point_selected_callback,
    ) -> None:
        super().__init__(
            pxMode=True,
            size=9,
            pen=pg.mkPen("#222222", width=1),
            hoverable=True,
            hoverPen=pg.mkPen("#111111", width=2),
            hoverBrush=pg.mkBrush("#ffd166"),
            tip=self.point_tooltip,
        )
        self.point_drag_started_callback = point_drag_started_callback
        self.point_moved_callback = point_moved_callback
        self.point_drag_finished_callback = point_drag_finished_callback
        self.point_delete_callback = point_delete_callback
        self.point_add_callback = point_add_callback
        self.point_selected_callback = point_selected_callback
        self._drag_data = None

    def mouseDragEvent(self, event) -> None:
        if event.button() != QtCore.Qt.LeftButton:
            event.ignore()
            return

        if event.isStart():
            points = self.pointsAt(event.buttonDownPos())
            if not points:
                event.ignore()
                return
            self._drag_data = points[0].data()
            self.point_selected_callback(self._drag_data)
            self.point_drag_started_callback(self._drag_data)
            event.accept()
            return

        if self._drag_data is None:
            event.ignore()
            return

        event.accept()
        position = event.pos()
        self.point_moved_callback(self._drag_data, position.x(), position.y())
        if event.isFinish():
            self.point_drag_finished_callback(self._drag_data)
            self._drag_data = None

    def mouseClickEvent(self, event) -> None:
        if event.button() not in (QtCore.Qt.LeftButton, QtCore.Qt.RightButton):
            event.ignore()
            return

        points = self.pointsAt(event.pos())
        if not points:
            event.ignore()
            return

        event.accept()
        if event.button() == QtCore.Qt.LeftButton:
            self.point_selected_callback(points[0].data())
            return

        point_data = points[0].data()
        self.point_selected_callback(point_data)
        menu = QtWidgets.QMenu()
        add_action = menu.addAction("Add point")
        delete_action = menu.addAction("Delete point")
        exec_menu = getattr(menu, "exec", None) or getattr(menu, "exec_")
        action = exec_menu(QtGui.QCursor.pos())
        if action == add_action:
            self.point_add_callback(point_data)
        elif action == delete_action:
            self.point_delete_callback(point_data)

    def point_tooltip(self, *args, **kwargs) -> str:
        point_data = kwargs.get("data")
        if point_data is None and len(args) >= 3 and isinstance(args[2], dict):
            point_data = args[2]
        if point_data is None and args:
            candidate = args[0]
            if hasattr(candidate, "data"):
                point_data = candidate.data()

        if not isinstance(point_data, dict):
            return ""

        group_name = point_data.get("group_name")
        if group_name is None and "group" in point_data:
            group_name = point_data["group"].name
        row = int(point_data.get("row", 0)) + 1
        x_channel = str(point_data.get("x_channel", ""))
        y_channel = str(point_data.get("y_channel", ""))
        x_value = point_data.get("x_value", "")
        y_value = point_data.get("y_value", "")
        return (
            f"Group: {group_name}\n"
            f"Row: {row}\n"
            f"{x_channel}: {x_value}\n"
            f"{y_channel}: {y_value}"
        )


class RightAxisViewBox(pg.ViewBox):
    def mouseDragEvent(self, event, axis=None) -> None:
        if event.button() == QtCore.Qt.LeftButton and axis is None:
            event.ignore()
            return
        super().mouseDragEvent(event, axis=axis)


class CharacteristicWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TCEditor")
        self.resize(1200, 760)

        self.data: CharacteristicData | None = None
        self.plot_items: list[pg.GraphicsObject] = []
        self.series_items: list[dict[str, object]] = []
        self.table_rows: dict[tuple[str, int], int] = {}
        self.undo_stack: list[dict[str, object]] = []
        self.redo_stack: list[dict[str, object]] = []
        self.active_drag_original: dict[str, object] | None = None

        self.open_action = QtWidgets.QAction("Open characteristic...", self)
        self.open_action.setShortcut("Ctrl+O")
        self.open_action.triggered.connect(self.open_characteristic)

        self.save_action = QtWidgets.QAction("Save characteristic as...", self)
        self.save_action.setShortcut("Ctrl+S")
        self.save_action.setEnabled(False)
        self.save_action.triggered.connect(self.save_characteristic_as)

        self.undo_action = QtWidgets.QAction("Undo", self)
        self.undo_action.setShortcut("Ctrl+Z")
        self.undo_action.setEnabled(False)
        self.undo_action.triggered.connect(self.undo_last_edit)

        self.redo_action = QtWidgets.QAction("Redo", self)
        self.redo_action.setShortcut("Ctrl+Y")
        self.redo_action.setEnabled(False)
        self.redo_action.triggered.connect(self.redo_last_edit)

        self.clear_action = QtWidgets.QAction("Clear plot", self)
        self.clear_action.triggered.connect(self.clear_plot)

        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.clear_action)
        edit_menu = self.menuBar().addMenu("Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)

        self.open_button = QtWidgets.QPushButton("Open characteristic")
        self.open_button.clicked.connect(self.open_characteristic)

        self.x_axis_combo = QtWidgets.QComboBox()
        self.x_axis_combo.currentTextChanged.connect(self.refresh_plot)

        self.group_list = QtWidgets.QListWidget()
        self.group_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.group_list.itemSelectionChanged.connect(self.refresh_plot)
        self.group_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.group_list.customContextMenuRequested.connect(self.open_group_context_menu)

        self.channel_list = QtWidgets.QListWidget()
        self.channel_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.channel_list.itemSelectionChanged.connect(self.refresh_plot)

        self.metadata_view = QtWidgets.QPlainTextEdit()
        self.metadata_view.setReadOnly(True)
        self.metadata_view.setMaximumBlockCount(1000)

        self.plot = pg.PlotWidget()
        self.plot.setBackground("w")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.legend = self.plot.addLegend(offset=(12, 12))
        self.plot.setLabel("bottom", "N11")
        self.plot.setLabel("left", "Q11")

        self.plot_item = self.plot.getPlotItem()
        self.right_axis = self.plot_item.getAxis("right")
        self.right_axis.setLabel("T11")
        self.plot_item.showAxis("right")
        self.right_view = RightAxisViewBox()
        self.plot_item.scene().addItem(self.right_view)
        self.right_view.setZValue(self.plot_item.vb.zValue() + 1)
        self.right_axis.linkToView(self.right_view)
        self.right_view.setXLink(self.plot_item.vb)
        self.right_view.setMouseEnabled(x=False, y=True)
        self.plot_item.vb.sigResized.connect(self.update_right_view)
        self.update_right_view()

        self.data_table = QtWidgets.QTableWidget()
        self.data_table.setAlternatingRowColors(True)
        self.data_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.data_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.data_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)

        controls = QtWidgets.QWidget()
        controls_layout = QtWidgets.QVBoxLayout(controls)
        controls_layout.setContentsMargins(8, 8, 8, 8)
        controls_layout.addWidget(self.open_button)
        controls_layout.addWidget(QtWidgets.QLabel("X axis"))
        controls_layout.addWidget(self.x_axis_combo)
        controls_layout.addWidget(QtWidgets.QLabel("Groups"))
        controls_layout.addWidget(self.group_list, stretch=2)
        controls_layout.addWidget(QtWidgets.QLabel("Y channels"))
        controls_layout.addWidget(self.channel_list, stretch=2)
        controls_layout.addWidget(QtWidgets.QLabel("Metadata"))
        controls_layout.addWidget(self.metadata_view, stretch=1)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(controls)
        splitter.addWidget(self.plot)
        splitter.addWidget(self.data_table)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([300, 680, 360])
        self.setCentralWidget(splitter)

        self.statusBar().showMessage("Open a characteristic file to plot data")

    def open_characteristic(self) -> None:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Open characteristic",
            "",
            "Characteristic files (*.txt *.dat *.csv);;All files (*.*)",
        )
        if not paths:
            return

        try:
            self.load_characteristic(Path(paths[0]))
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Characteristic Import Error", str(exc))

    def save_characteristic_as(self) -> None:
        if self.data is None:
            QtWidgets.QMessageBox.information(self, "Save characteristic", "No characteristic data loaded.")
            return

        source = self.data.source_file
        default_path = source.with_name(f"{source.stem}_modified{source.suffix}")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save characteristic as",
            str(default_path),
            "Characteristic files (*.txt *.dat *.csv);;All files (*.*)",
        )
        if not path:
            return

        try:
            write_characteristic_file(self.data, path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Save Error", str(exc))
            return

        self.statusBar().showMessage(f"Saved characteristic to {path}")

    def load_characteristic(self, path: Path) -> None:
        self.data = parse_characteristic_file(path)
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.active_drag_original = None
        self.update_undo_action()
        self.save_action.setEnabled(True)
        self.setWindowTitle(f"TCEditor - {path.name}")
        self.populate_controls()
        self.statusBar().showMessage(
            f"Loaded {path.name}: {len(self.data.groups)} groups, {len(self.data.header) - 1} channels"
        )

    def populate_controls(self) -> None:
        if self.data is None:
            return

        self.group_list.blockSignals(True)
        self.channel_list.blockSignals(True)
        self.x_axis_combo.blockSignals(True)
        self.group_list.clear()
        self.channel_list.clear()
        self.x_axis_combo.clear()

        for group in self.data.groups:
            item = QtWidgets.QListWidgetItem(f"{group.name} ({group.row_count} rows)")
            item.setData(QtCore.Qt.UserRole, group.name)
            self.group_list.addItem(item)
            item.setSelected(True)

        channel_names = list(self.data.groups[0].channels.keys()) if self.data.groups else []
        self.x_axis_combo.addItems(channel_names)
        default_x_idx = self._default_x_axis_index(channel_names)
        if default_x_idx >= 0:
            self.x_axis_combo.setCurrentIndex(default_x_idx)

        for channel in channel_names:
            item = QtWidgets.QListWidgetItem(channel)
            item.setData(QtCore.Qt.UserRole, channel)
            self.channel_list.addItem(item)
            item.setSelected(channel != self.x_axis_combo.currentText())

        self.metadata_view.setPlainText("\n".join(self.data.metadata))
        self.group_list.blockSignals(False)
        self.channel_list.blockSignals(False)
        self.x_axis_combo.blockSignals(False)
        self.populate_data_table()
        self.refresh_plot()

    def refresh_plot(self) -> None:
        if self.data is None:
            return

        selected_groups = {
            item.data(QtCore.Qt.UserRole)
            for item in self.group_list.selectedItems()
        }
        selected_channels = {
            item.data(QtCore.Qt.UserRole)
            for item in self.channel_list.selectedItems()
        }
        x_channel = self.x_axis_combo.currentText()
        left_range = self.plot_item.vb.viewRange() if self.plot_items else None
        right_range = self.right_view.viewRange() if self.plot_items else None

        self.clear_plot()
        if not selected_groups or not selected_channels or not x_channel:
            return

        self.plot.setLabel("bottom", x_channel)
        palette = [
            "#1f77b4",
            "#d62728",
            "#2ca02c",
            "#9467bd",
            "#ff7f0e",
            "#17becf",
            "#8c564b",
            "#7f7f7f",
        ]
        curve_idx = 0
        for group in self.data.groups:
            if group.name not in selected_groups:
                continue
            x_values = group.channels.get(x_channel)
            if x_values is None:
                continue
            for channel_name, y_values in group.channels.items():
                if channel_name not in selected_channels:
                    continue
                if channel_name == x_channel:
                    continue
                target_axis = self.axis_for_channel(channel_name)
                pen = pg.mkPen(palette[curve_idx % len(palette)], width=2)
                curve = pg.PlotDataItem(
                    x_values,
                    y_values,
                    pen=pen,
                    name=f"{group.name} / {channel_name}",
                )
                curve.setZValue(10)
                points = DraggablePointItem(
                    self.begin_point_drag,
                    self.move_point,
                    self.finish_point_drag,
                    self.delete_point,
                    self.add_point,
                    self.select_point,
                )
                points.setZValue(20)
                points.setBrush(pg.mkBrush(palette[curve_idx % len(palette)]))
                points.setData(
                    x=x_values,
                    y=y_values,
                    data=[
                        {
                            "group": group,
                            "group_name": group.name,
                            "row": row_idx,
                            "x_channel": x_channel,
                            "y_channel": channel_name,
                            "x_value": self._format_float(x_values[row_idx]),
                            "y_value": self._format_float(y_values[row_idx]),
                        }
                        for row_idx in range(len(y_values))
                    ],
                )
                self.add_series_items(target_axis, curve, points)
                self.plot_items.extend([curve, points])
                self.series_items.append(
                    {
                        "group": group,
                        "x_channel": x_channel,
                        "y_channel": channel_name,
                        "axis": target_axis,
                        "line": curve,
                        "points": points,
                    }
                )
                curve_idx += 1

        if left_range is None:
            self.plot_item.vb.autoRange()
            self.right_view.autoRange()
        else:
            self.plot_item.vb.setRange(xRange=left_range[0], yRange=left_range[1], padding=0)
            if right_range is not None:
                self.right_view.setYRange(right_range[1][0], right_range[1][1], padding=0)

        self.plot_item.vb.enableAutoRange(x=False, y=False)
        self.right_view.enableAutoRange(x=False, y=False)

    def axis_for_channel(self, channel_name: str) -> str:
        return "right" if channel_name.casefold() == "t11" else "left"

    def add_series_items(self, axis: str, curve: pg.PlotDataItem, points: DraggablePointItem) -> None:
        if axis == "right":
            self.right_view.addItem(curve)
            self.right_view.addItem(points)
            self.legend.addItem(curve, curve.name())
            return

        self.plot_item.addItem(curve)
        self.plot_item.addItem(points)
        self.legend.addItem(curve, curve.name())

    def update_right_view(self) -> None:
        self.right_view.setGeometry(self.plot_item.vb.sceneBoundingRect())
        self.right_view.linkedViewChanged(self.plot_item.vb, pg.ViewBox.XAxis)

    def begin_point_drag(self, point_data: dict[str, object]) -> None:
        group = point_data["group"]
        row = int(point_data["row"])
        x_channel = str(point_data["x_channel"])
        y_channel = str(point_data["y_channel"])
        self.active_drag_original = {
            "group": group,
            "row": row,
            "x_channel": x_channel,
            "y_channel": y_channel,
            "old_x": float(group.channels[x_channel][row]),
            "old_y": float(group.channels[y_channel][row]),
        }

    def select_point(self, point_data: dict[str, object]) -> None:
        group = point_data["group"]
        row = int(point_data["row"])
        table_row = self.table_rows.get((group.name, row))
        if table_row is None:
            return

        self.data_table.setCurrentCell(table_row, 0)
        self.data_table.selectRow(table_row)
        self.data_table.scrollToItem(
            self.data_table.item(table_row, 0),
            QtWidgets.QAbstractItemView.PositionAtCenter,
        )

    def move_point(self, point_data: dict[str, object], x: float, y: float) -> None:
        group = point_data["group"]
        row = int(point_data["row"])
        x_channel = str(point_data["x_channel"])
        y_channel = str(point_data["y_channel"])

        group.channels[x_channel][row] = x
        group.channels[y_channel][row] = y
        self.update_series_items(group)
        self.update_table_row(group, row)
        self.statusBar().showMessage(
            f"Moved {group.name} row {row + 1}: {x_channel}={x:.6g}, {y_channel}={y:.6g}"
        )

    def finish_point_drag(self, point_data: dict[str, object]) -> None:
        if self.active_drag_original is None:
            return

        group = point_data["group"]
        row = int(point_data["row"])
        x_channel = str(point_data["x_channel"])
        y_channel = str(point_data["y_channel"])
        new_x = float(group.channels[x_channel][row])
        new_y = float(group.channels[y_channel][row])

        edit = dict(self.active_drag_original)
        edit["type"] = "move_point"
        edit["new_x"] = new_x
        edit["new_y"] = new_y
        self.active_drag_original = None

        if edit["old_x"] == new_x and edit["old_y"] == new_y:
            return
        self.push_edit(edit)

    def delete_point(self, point_data: dict[str, object]) -> None:
        group = point_data["group"]
        row = int(point_data["row"])
        if row < 0 or row >= group.row_count:
            return

        values = self.row_values(group, row)
        edit = {
            "type": "delete_point",
            "group": group,
            "group_index": self.data.groups.index(group) if self.data is not None and group in self.data.groups else None,
            "row": row,
            "values": values,
        }
        self.active_drag_original = None
        self.apply_edit(edit)
        self.push_edit(edit)
        self.statusBar().showMessage(f"Deleted point from {group.name} row {row + 1}")

    def add_point(self, point_data: dict[str, object]) -> None:
        group = point_data["group"]
        row = int(point_data["row"])
        if group.row_count < 2 or row < 0 or row >= group.row_count:
            return

        if row < group.row_count - 1:
            left_row = row
            right_row = row + 1
            insert_at = row + 1
        else:
            left_row = row - 1
            right_row = row
            insert_at = row

        values = {}
        for channel_name, channel_values in list(group.channels.items()):
            midpoint = (float(channel_values[left_row]) + float(channel_values[right_row])) / 2.0
            values[channel_name] = midpoint

        edit = {
            "type": "add_point",
            "group": group,
            "group_index": self.data.groups.index(group) if self.data is not None and group in self.data.groups else None,
            "row": insert_at,
            "values": values,
        }
        self.active_drag_original = None
        self.apply_edit(edit)
        self.push_edit(edit)
        table_row = self.table_rows.get((group.name, insert_at))
        if table_row is not None:
            self.data_table.selectRow(table_row)
        self.statusBar().showMessage(f"Added point to {group.name} at row {insert_at + 1}")

    def open_group_context_menu(self, position) -> None:
        menu = QtWidgets.QMenu(self)
        add_group_action = menu.addAction("Add midpoint characteristic group")
        delete_groups_action = menu.addAction("Delete selected group(s)")
        exec_menu = getattr(menu, "exec", None) or getattr(menu, "exec_")
        action = exec_menu(self.group_list.viewport().mapToGlobal(position))
        if action == add_group_action:
            self.add_midpoint_group()
        elif action == delete_groups_action:
            self.delete_selected_groups()

    def add_midpoint_group(self) -> None:
        if self.data is None:
            QtWidgets.QMessageBox.warning(self, "Add Group Error", "No characteristic data loaded.")
            return

        selected_rows = sorted({self.group_list.row(item) for item in self.group_list.selectedItems()})
        if len(selected_rows) != 2:
            QtWidgets.QMessageBox.warning(
                self,
                "Add Group Error",
                "Select exactly two neighboring characteristic groups.",
            )
            return
        if selected_rows[1] != selected_rows[0] + 1:
            QtWidgets.QMessageBox.warning(
                self,
                "Add Group Error",
                "The selected characteristic groups must be neighbors.",
            )
            return

        left_group = self.data.groups[selected_rows[0]]
        right_group = self.data.groups[selected_rows[1]]
        common_channels = list(left_group.channels)
        required_channels = {"N11", "Q11", "T11"}
        if not required_channels.issubset(common_channels) or set(common_channels) != set(right_group.channels):
            QtWidgets.QMessageBox.warning(
                self,
                "Add Group Error",
                "Both groups must contain the same channels, including N11, Q11, and T11.",
            )
            return

        row_count = max(left_group.row_count, right_group.row_count)
        channels = {
            channel: self.midpoint_channel(
                left_group.channels[channel],
                right_group.channels[channel],
                row_count,
            )
            for channel in common_channels
        }
        group_value = (float(left_group.value) + float(right_group.value)) / 2.0
        value_text = f"{group_value:.12g}"
        new_group = CharacteristicGroup(
            name=f"{self.data.group_column}={value_text}",
            value=group_value,
            x=np.arange(row_count, dtype=float),
            channels=channels,
            row_count=row_count,
        )
        edit = {
            "type": "add_group",
            "group": new_group,
            "group_index": selected_rows[1],
        }
        self.apply_edit(edit)
        self.push_edit(edit)
        for item_index in range(self.group_list.count()):
            item = self.group_list.item(item_index)
            if item.data(QtCore.Qt.UserRole) == new_group.name:
                item.setSelected(True)
                self.group_list.scrollToItem(item)
                break
        self.statusBar().showMessage(f"Added midpoint characteristic group {new_group.name}")

    def delete_selected_groups(self) -> None:
        if self.data is None:
            QtWidgets.QMessageBox.warning(self, "Delete Group Error", "No characteristic data loaded.")
            return

        selected_rows = sorted({self.group_list.row(item) for item in self.group_list.selectedItems()})
        if not selected_rows:
            QtWidgets.QMessageBox.warning(
                self,
                "Delete Group Error",
                "Select at least one characteristic group to delete.",
            )
            return

        groups = [
            {
                "group": self.data.groups[row],
                "group_index": row,
            }
            for row in selected_rows
        ]
        edit = {
            "type": "delete_groups",
            "groups": groups,
        }
        self.apply_edit(edit)
        self.push_edit(edit)
        self.statusBar().showMessage(f"Deleted {len(groups)} characteristic group(s)")

    def midpoint_channel(self, left_values, right_values, row_count: int) -> np.ndarray:
        target = np.linspace(0.0, 1.0, row_count)
        left_position = np.linspace(0.0, 1.0, len(left_values))
        right_position = np.linspace(0.0, 1.0, len(right_values))
        left_resampled = np.interp(target, left_position, np.asarray(left_values, dtype=float))
        right_resampled = np.interp(target, right_position, np.asarray(right_values, dtype=float))
        return (left_resampled + right_resampled) / 2.0

    def push_edit(self, edit: dict[str, object]) -> None:
        self.undo_stack.append(edit)
        self.redo_stack.clear()
        self.update_undo_action()

    def undo_last_edit(self) -> None:
        if not self.undo_stack:
            return

        edit = self.undo_stack.pop()
        self.revert_edit(edit)
        self.redo_stack.append(edit)
        self.update_undo_action()
        self.statusBar().showMessage(f"Undid {self.edit_label(edit)}")

    def redo_last_edit(self) -> None:
        if not self.redo_stack:
            return

        edit = self.redo_stack.pop()
        self.apply_edit(edit)
        self.undo_stack.append(edit)
        self.update_undo_action()
        self.statusBar().showMessage(f"Redid {self.edit_label(edit)}")

    def update_undo_action(self) -> None:
        self.undo_action.setEnabled(bool(self.undo_stack))
        self.redo_action.setEnabled(bool(self.redo_stack))

    def apply_edit(self, edit: dict[str, object]) -> None:
        edit_type = str(edit["type"])

        if edit_type == "delete_groups":
            if self.data is not None:
                for group_item in sorted(edit["groups"], key=lambda item: int(item["group_index"]), reverse=True):
                    group = group_item["group"]
                    if group in self.data.groups:
                        self.data.groups.remove(group)
            self.refresh_after_row_count_change()
            return

        group = edit["group"]

        if edit_type == "add_group":
            group_index = int(edit["group_index"])
            if self.data is not None and group not in self.data.groups:
                self.data.groups.insert(min(group_index, len(self.data.groups)), group)
            self.refresh_after_row_count_change()
            return

        row = int(edit["row"])

        if edit_type == "move_point":
            x_channel = str(edit["x_channel"])
            y_channel = str(edit["y_channel"])
            group.channels[x_channel][row] = float(edit["new_x"])
            group.channels[y_channel][row] = float(edit["new_y"])
            self.update_series_items(group)
            self.update_table_row(group, row)
            return

        if edit_type == "add_point":
            self.insert_group_row(group, row, edit["values"], edit.get("group_index"))
            self.refresh_after_row_count_change()
            return

        if edit_type == "delete_point":
            self.remove_group_row(group, row)
            self.refresh_after_row_count_change()
            return

    def revert_edit(self, edit: dict[str, object]) -> None:
        edit_type = str(edit["type"])

        if edit_type == "delete_groups":
            if self.data is not None:
                for group_item in sorted(edit["groups"], key=lambda item: int(item["group_index"])):
                    group = group_item["group"]
                    group_index = min(int(group_item["group_index"]), len(self.data.groups))
                    if group not in self.data.groups:
                        self.data.groups.insert(group_index, group)
            self.refresh_after_row_count_change()
            return

        group = edit["group"]

        if edit_type == "add_group":
            if self.data is not None and group in self.data.groups:
                self.data.groups.remove(group)
            self.refresh_after_row_count_change()
            return

        row = int(edit["row"])

        if edit_type == "move_point":
            x_channel = str(edit["x_channel"])
            y_channel = str(edit["y_channel"])
            group.channels[x_channel][row] = float(edit["old_x"])
            group.channels[y_channel][row] = float(edit["old_y"])
            self.update_series_items(group)
            self.update_table_row(group, row)
            return

        if edit_type == "add_point":
            self.remove_group_row(group, row)
            self.refresh_after_row_count_change()
            return

        if edit_type == "delete_point":
            self.insert_group_row(group, row, edit["values"], edit.get("group_index"))
            self.refresh_after_row_count_change()
            return

    def row_values(self, group, row: int) -> dict[str, float]:
        return {
            channel_name: float(values[row])
            for channel_name, values in group.channels.items()
        }

    def insert_group_row(self, group, row: int, values: dict[str, float], group_index=None) -> None:
        if self.data is not None and group not in self.data.groups:
            if group_index is None:
                self.data.groups.append(group)
            else:
                self.data.groups.insert(min(int(group_index), len(self.data.groups)), group)
        for channel_name, channel_values in list(group.channels.items()):
            group.channels[channel_name] = np.insert(channel_values, row, float(values[channel_name]))
        object.__setattr__(group, "x", np.arange(group.row_count + 1, dtype=float))
        object.__setattr__(group, "row_count", group.row_count + 1)

    def remove_group_row(self, group, row: int) -> None:
        for channel_name, channel_values in list(group.channels.items()):
            group.channels[channel_name] = np.delete(channel_values, row)
        object.__setattr__(group, "x", np.arange(max(group.row_count - 1, 0), dtype=float))
        object.__setattr__(group, "row_count", max(group.row_count - 1, 0))
        if self.data is not None and group.row_count == 0 and group in self.data.groups:
            self.data.groups.remove(group)

    def refresh_after_row_count_change(self) -> None:
        self.active_drag_original = None
        self.refresh_group_list_labels()
        self.populate_data_table()
        self.refresh_plot()

    def edit_label(self, edit: dict[str, object]) -> str:
        edit_type = str(edit["type"])
        if edit_type == "add_group":
            return f"characteristic group add {edit['group'].name}"
        if edit_type == "delete_groups":
            return f"{len(edit['groups'])} characteristic group delete(s)"
        row = int(edit["row"]) + 1
        if edit_type == "move_point":
            return f"point move at row {row}"
        if edit_type == "add_point":
            return f"point add at row {row}"
        if edit_type == "delete_point":
            return f"point delete at row {row}"
        return edit_type

    def refresh_group_list_labels(self) -> None:
        if self.data is None:
            return
        selected_group_names = {
            item.data(QtCore.Qt.UserRole)
            for item in self.group_list.selectedItems()
        }
        self.group_list.blockSignals(True)
        self.group_list.clear()
        for group in self.data.groups:
            item = QtWidgets.QListWidgetItem(f"{group.name} ({group.row_count} rows)")
            item.setData(QtCore.Qt.UserRole, group.name)
            self.group_list.addItem(item)
            item.setSelected(group.name in selected_group_names or not selected_group_names)
        self.group_list.blockSignals(False)

    def update_series_items(self, moved_group) -> None:
        for series in self.series_items:
            if series["group"] is not moved_group:
                continue
            group = series["group"]
            x_channel = str(series["x_channel"])
            y_channel = str(series["y_channel"])
            x_values = group.channels[x_channel]
            y_values = group.channels[y_channel]
            series["line"].setData(x_values, y_values)
            series["points"].setData(
                x=x_values,
                y=y_values,
                data=[
                    {
                        "group": group,
                        "group_name": group.name,
                        "row": row_idx,
                        "x_channel": x_channel,
                        "y_channel": y_channel,
                        "x_value": self._format_float(x_values[row_idx]),
                        "y_value": self._format_float(y_values[row_idx]),
                    }
                    for row_idx in range(len(y_values))
                ],
            )

    def populate_data_table(self) -> None:
        if self.data is None:
            self.data_table.clear()
            self.data_table.setRowCount(0)
            self.data_table.setColumnCount(0)
            self.table_rows.clear()
            return

        channel_names = list(self.data.groups[0].channels.keys()) if self.data.groups else []
        headers = [self.data.group_column, "Row", *channel_names]
        row_count = sum(group.row_count for group in self.data.groups)

        self.data_table.clear()
        self.data_table.setColumnCount(len(headers))
        self.data_table.setRowCount(row_count)
        self.data_table.setHorizontalHeaderLabels(headers)
        self.table_rows.clear()

        table_row = 0
        for group in self.data.groups:
            for row_idx in range(group.row_count):
                self.table_rows[(group.name, row_idx)] = table_row
                self._write_table_row(table_row, group, row_idx, channel_names)
                table_row += 1

        self.data_table.resizeColumnsToContents()
        header = self.data_table.horizontalHeader()
        header.setStretchLastSection(True)

    def update_table_row(self, group, row_idx: int) -> None:
        if self.data is None:
            return
        table_row = self.table_rows.get((group.name, row_idx))
        if table_row is None:
            return
        channel_names = list(self.data.groups[0].channels.keys()) if self.data.groups else []
        self._write_table_row(table_row, group, row_idx, channel_names)

    def _write_table_row(self, table_row: int, group, row_idx: int, channel_names: list[str]) -> None:
        values = [self._format_float(group.value), str(row_idx + 1)]
        values.extend(self._format_float(group.channels[channel][row_idx]) for channel in channel_names)
        for column, value in enumerate(values):
            item = QtWidgets.QTableWidgetItem(value)
            item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self.data_table.setItem(table_row, column, item)

    def _format_float(self, value: float) -> str:
        return f"{value:.12g}"

    def _default_x_axis_index(self, channel_names: list[str]) -> int:
        for idx, channel in enumerate(channel_names):
            if channel.casefold() == "n11":
                return idx
        return 0 if channel_names else -1

    def clear_plot(self) -> None:
        for item in self.plot_items:
            self.plot_item.removeItem(item)
            self.right_view.removeItem(item)
            if self.legend is not None:
                try:
                    self.legend.removeItem(item)
                except Exception:
                    pass
        self.plot_items.clear()
        self.series_items.clear()


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    pg.setConfigOptions(antialias=True)
    window = CharacteristicWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
