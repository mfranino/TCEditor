"""Launch the multi-file TCEditor with resizable controls and commit-based versioning.

Only highlighted constant-y curve rows determine plotted data. File rows are
containers, not implicit selections of all their curves.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pyqtgraph as pg
from qtpy import QtCore, QtWidgets

from tceditor_3d import _require_pyqtgraph_014
from tceditor_multifile import KIND, PATH, GROUP, MultiFileCharacteristicWindow

# The commit immediately BEFORE the versioned series. The first descendant
# commit is 0.0.1; each later commit increments the patch number automatically.
VERSION_BASE_COMMIT = "7ef877635ddfafaf472b15dfdc5f40f0a1eb18c8"


def build_version() -> tuple[str, str]:
    """Return (version, revision) from this script's Git checkout, not the CWD."""
    directory = Path(__file__).resolve().parent

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(directory), *args],
            capture_output=True, text=True, check=True, timeout=3,
        )
        return result.stdout.strip()

    try:
        git("merge-base", "--is-ancestor", VERSION_BASE_COMMIT, "HEAD")
        count = int(git("rev-list", "--count", f"{VERSION_BASE_COMMIT}..HEAD"))
        revision = git("rev-parse", "--short=7", "HEAD")
        return f"0.0.{max(count, 1)}", revision
    except (OSError, ValueError, subprocess.SubprocessError):
        # Zip distributions / machines without Git cannot verify the revision.
        return "0.0.1", "Git revision unavailable"


class StackedCharacteristicWindow(MultiFileCharacteristicWindow):
    """One control column and explicit, additive cross-file curve selection."""

    def __init__(self) -> None:
        super().__init__()

        self.file_tree.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.file_tree.setHeaderLabels(["Files / constant-y curves (click to add/remove)"])
        self.file_tree.setToolTip(
            "Click curve rows to plot them; click again to remove them. "
            "File names are containers, not a plot-all selection."
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
            f"({len(self.files)} files)"
        )

    def _disable_file_row_selection(self) -> None:
        """File headings are navigational containers, never plot-all selectors."""
        self.file_tree.blockSignals(True)
        try:
            for index in range(self.file_tree.topLevelItemCount()):
                item = self.file_tree.topLevelItem(index)
                item.setSelected(False)
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsSelectable)
        finally:
            self.file_tree.blockSignals(False)

    def _rebuild_tree(self) -> None:
        super()._rebuild_tree()
        self._disable_file_row_selection()

    def _visible_curves(self):
        """Plot *only* explicitly selected curve rows from every loaded file."""
        selected = {
            (item.data(0, PATH), item.data(0, GROUP))
            for item in self.file_tree.selectedItems()
            if item.data(0, KIND) == "group"
        }
        for path, data in self.files.items():
            for group in data.groups:
                if (path, group.name) in selected:
                    yield path, group

    def _tree_clicked(self, item, column) -> None:
        """Selecting another curve must never replace the active editing file."""
        self.refresh_plot()

    def _activate(self, path: str) -> None:
        super()._activate(path)
        if hasattr(self, "app_version"):
            self._apply_version_title()

    def _remove_file(self, path: str) -> None:
        super()._remove_file(path)
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
