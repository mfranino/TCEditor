"""MyScope-compatible VIS import and read-only time-series plots for TCEditor.

VIS contains Time + measurement channels, not constant-y characteristic curves.
Keep its data independent of characteristic editing and saving.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from qtpy import QtCore, QtWidgets


@dataclass
class VisMeasurement:
    source_file: Path
    name: str
    time: np.ndarray
    channels: dict[str, np.ndarray]
    units: dict[str, str]
    metadata: dict[str, str]


def parse_vis_file(file_path: str | Path) -> VisMeasurement:
    """Adapt MyScope_import_tools.dataset_from_vis without its SignalDataset dependency.

    Read metadata ($KEY: value), Time/column names, bracketed unit tokens,
    numeric data, duplicate names, non-increasing times, and uniform time base.
    """
    path = Path(file_path)
    lines = None
    last_error = None
    for encoding in ("utf-8-sig", "cp1250", "latin-1"):
        try:
            lines = path.read_text(encoding=encoding).splitlines()
            break
        except UnicodeDecodeError as exc:
            last_error = exc
    if lines is None:
        raise RuntimeError(f"Could not decode VIS file: {last_error}")
    if len(lines) < 9:
        raise ValueError("VIS file is too short.")

    props: dict[str, str] = {}
    header_index = None
    for index, line in enumerate(lines):
        text = line.strip()
        if not text:
            continue
        if text.startswith("$"):
            key, sep, value = text[1:].partition(":")
            props[key.strip()] = value.strip() if sep else ""
            continue
        if "Time" in text and "[" not in text:
            header_index = index
            break
    if header_index is None or header_index + 1 >= len(lines):
        raise ValueError("VIS column header row not found.")

    names = re.findall(r"\S+", lines[header_index].strip())
    unit_tokens = re.findall(r"\[[^\]]*\]", lines[header_index + 1].strip())
    if not names or names[0].lower() != "time":
        raise ValueError("VIS first column must be Time.")
    if len(unit_tokens) != len(names):
        raise ValueError("VIS units row does not match the column count.")
    seen: dict[str, int] = {}
    channels_order: list[str] = []
    for index, raw_name in enumerate(names[1:], 1):
        base = raw_name.strip() or f"col_{index}"
        seen[base] = seen.get(base, 0) + 1
        channels_order.append(base if seen[base] == 1 else f"{base}_{seen[base]}")

    rows: list[list[float]] = []
    for line in lines[header_index + 2:]:
        parts = re.findall(r"\S+", line.strip())
        if len(parts) != len(names):
            continue
        try:
            rows.append([float(token.replace(",", ".")) for token in parts])
        except ValueError:
            continue
    if not rows:
        raise ValueError("No valid VIS data rows found.")
    data = np.asarray(rows, dtype=float)
    # As in MyScope, discard non-increasing timestamps while preserving rows.
    # Compare against the last kept timestamp, not a previously rejected row.
    valid_indices: list[int] = []
    last_time = -np.inf
    for index, value in enumerate(data[:, 0]):
        if np.isfinite(value) and value > last_time:
            valid_indices.append(index)
            last_time = float(value)
    data = data[valid_indices]
    if len(data) < 2:
        raise ValueError("Not enough VIS samples.")

    time = data[:, 0]
    diffs = np.diff(time)
    dt = float(np.median(diffs))
    tol = max(1e-9, abs(dt) * 1e-6)
    trimmed = False
    if np.max(np.abs(diffs - dt)) > tol:
        short_final_step = (len(diffs) > 1 and 0 < diffs[-1] < dt * 0.5
                            and np.max(np.abs(diffs[:-1] - dt)) <= tol)
        if short_final_step:
            data = data[:-1]
            time = data[:, 0]
            trimmed = True
            diffs = np.diff(time)
            dt = float(np.median(diffs))
            tol = max(1e-9, abs(dt) * 1e-6)
        if np.max(np.abs(diffs - dt)) > tol:
            raise ValueError("VIS time is not uniformly sampled; cannot prepare waveform export safely.")
    if trimmed:
        props["TrimmedTrailingPartialSample"] = "1"
    props["SourceFormat"] = "VIS"
    props["SourceFile"] = str(path)

    channels = {}
    units = {}
    for index, name in enumerate(channels_order, 1):
        values = data[:, index].copy()
        if not np.all(np.isnan(values)):
            channels[name] = values
            units[name] = unit_tokens[index][1:-1].strip()
    if not channels:
        raise ValueError("VIS file does not contain any usable signal channels.")
    return VisMeasurement(path, path.stem, time.copy(), channels, units, props)


class VisViewer(QtWidgets.QMainWindow):
    """Inspect any number of VIS imports, selecting files and channels globally."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("TCEditor - VIS measurements (read-only)")
        self.resize(1100, 720)
        self.measurements: dict[str, VisMeasurement] = {}
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        horizontal = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.addWidget(horizontal)
        sidebar = QtWidgets.QWidget()
        side_layout = QtWidgets.QVBoxLayout(sidebar)
        self.open_button = QtWidgets.QPushButton("Add VIS files...")
        self.open_button.clicked.connect(self.open_files)
        side_layout.addWidget(self.open_button)
        self.file_list = QtWidgets.QListWidget()
        self.file_list.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.file_list.itemSelectionChanged.connect(self.refresh_plot)
        self.channel_list = QtWidgets.QListWidget()
        self.channel_list.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.channel_list.itemSelectionChanged.connect(self.refresh_plot)
        self.metadata = QtWidgets.QPlainTextEdit()
        self.metadata.setReadOnly(True)
        self.panels = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        for label, widget in (("VIS files (click to add/remove)", self.file_list),
                              ("Channels (click to add/remove)", self.channel_list),
                              ("File metadata", self.metadata)):
            panel = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(QtWidgets.QLabel(label))
            layout.addWidget(widget)
            self.panels.addWidget(panel)
        self.panels.setChildrenCollapsible(False)
        side_layout.addWidget(self.panels)
        horizontal.addWidget(sidebar)
        self.plot = pg.PlotWidget(background="w")
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.setLabel("bottom", "Time")
        self.plot.addLegend()
        horizontal.addWidget(self.plot)
        horizontal.setSizes([300, 800])
        self.panels.setSizes([280, 190, 190])
        self.statusBar().showMessage("Open a VIS measurement; this viewer never changes or saves original files.")

    def open_files(self) -> None:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Import VIS measurement files", "", "VIS measurements (*.vis *.VIS);;All files (*.*)")
        if paths:
            self.load_files(paths)

    def load_files(self, paths) -> None:
        errors = []
        existing_channels = {item.text() for item in self.channel_list.selectedItems()}
        first_import = not self.measurements
        for raw_path in paths:
            path = Path(raw_path)
            key = str(path.resolve())
            if key in self.measurements:
                continue
            try:
                measurement = parse_vis_file(path)
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")
                continue
            self.measurements[key] = measurement
            item = QtWidgets.QListWidgetItem(path.name)
            item.setData(QtCore.Qt.UserRole, key)
            self.file_list.blockSignals(True)
            self.file_list.addItem(item)
            item.setSelected(True)
            self.file_list.blockSignals(False)
        names = list(dict.fromkeys(name for item in self.measurements.values()
                                   for name in item.channels))
        self.channel_list.blockSignals(True)
        try:
            self.channel_list.clear()
            for name in names:
                item = QtWidgets.QListWidgetItem(name)
                self.channel_list.addItem(item)
                item.setSelected(name in existing_channels or (first_import and not existing_channels))
        finally:
            self.channel_list.blockSignals(False)
        self.refresh_plot()
        if errors:
            QtWidgets.QMessageBox.warning(self, "VIS import errors", "\n".join(errors))
        self.statusBar().showMessage(f"{len(self.measurements)} VIS file(s) loaded")

    def refresh_plot(self) -> None:
        self.plot.clear()
        files = [self.measurements[item.data(QtCore.Qt.UserRole)]
                 for item in self.file_list.selectedItems()]
        channels = {item.text() for item in self.channel_list.selectedItems()}
        for measurement in files:
            for channel in measurement.channels:
                if channel not in channels:
                    continue
                pen = pg.mkPen(pg.intColor(len(self.plot.listDataItems()), hues=16), width=1.5)
                label = f"{measurement.source_file.name} / {channel}"
                unit = measurement.units.get(channel, "")
                if unit:
                    label += f" [{unit}]"
                self.plot.plot(measurement.time, measurement.channels[channel], pen=pen, name=label)
        if files:
            self.metadata.setPlainText("\n".join(f"{key}: {value}" for key, value in files[-1].metadata.items()))
        else:
            self.metadata.clear()
