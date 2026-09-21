"""Launch the multi-file TCEditor with one vertically resizable control column.

The underlying multi-file loader, mouse-based curve selection, global channel
selection, editing, saving, and 3D views are reused without modification.
"""
from __future__ import annotations

import sys

import pyqtgraph as pg
from qtpy import QtCore, QtWidgets

from tceditor_3d import _require_pyqtgraph_014
from tceditor_multifile import MultiFileCharacteristicWindow


class StackedCharacteristicWindow(MultiFileCharacteristicWindow):
    """Put all controls in one column with independent resize handles."""

    def __init__(self) -> None:
        super().__init__()

        # The original 2D editor has its controls in the first widget of the
        # horizontal splitter. Preserve this widget for the internal, hidden
        # group list used by its editing operations.
        main_splitter = self.centralWidget()
        old_controls = self.group_list.parentWidget()
        old_layout = old_controls.layout()
        self._legacy_controls = old_controls

        # Existing label/widget objects are reused: Qt signal connections,
        # selection state and editing behavior are not recreated or altered.
        x_label = old_layout.itemAt(1).widget()
        channels_label = old_layout.itemAt(5).widget()
        metadata_label = old_layout.itemAt(7).widget()
        for widget in (self.open_button, x_label, self.x_axis_combo,
                       channels_label, self.channel_list,
                       metadata_label, self.metadata_view):
            old_layout.removeWidget(widget)

        # takeWidget() detaches the existing tree without deleting it.
        dock = self.findChild(QtWidgets.QDockWidget, "CharacteristicFilesDock")
        if dock is None:
            raise RuntimeError("Multi-file tree dock was not found.")
        tree = dock.takeWidget()
        if tree is not self.file_tree:
            raise RuntimeError("Unexpected file-tree dock contents.")
        self.removeDockWidget(dock)
        dock.deleteLater()

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

        sidebar_layout.addWidget(vertical, 1)
        self.control_splitter = vertical
        main_splitter.insertWidget(0, sidebar)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setStretchFactor(2, 0)
        main_splitter.setSizes([330, 750, 330])
        vertical.setSizes([410, 180, 175])
        self.setWindowTitle("TCEditor - multi-file")


def main() -> int:
    _require_pyqtgraph_014()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    pg.setConfigOptions(antialias=True)
    window = StackedCharacteristicWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
