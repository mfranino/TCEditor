from __future__ import annotations

import sys

import numpy as np
import pyqtgraph as pg
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.tri import Triangulation
from qtpy import QtWidgets

from characteristic_parser import CharacteristicData
from tceditor import CharacteristicWindow


class Surface3DWindow(QtWidgets.QMainWindow):
    """Display one characteristic channel as a triangulated 3D surface."""

    def __init__(self, data: CharacteristicData, z_channel: str) -> None:
        super().__init__()
        self.data = data
        self.z_channel = z_channel
        self.setWindowTitle(f"TCEditor - {z_channel}(N11, a0) 3D surface")
        self.resize(900, 700)

        self.figure = Figure(figsize=(9, 7))
        self.canvas = FigureCanvas(self.figure)
        self.setCentralWidget(self.canvas)
        self.axes = self.figure.add_subplot(111, projection="3d")
        self.refresh_surface()

    def refresh_surface(self) -> None:
        self.figure.clear()
        self.axes = self.figure.add_subplot(111, projection="3d")
        samples: list[tuple[float, float, float]] = []

        for group in self.data.groups:
            n11 = group.channels.get("N11")
            values = group.channels.get(self.z_channel)
            if n11 is None or values is None:
                continue

            for n11_value, z_value in zip(n11, values):
                x = float(n11_value)
                y = float(group.value)
                z = float(z_value)
                if np.isfinite(x) and np.isfinite(y) and np.isfinite(z):
                    samples.append((x, y, z))

        if len(samples) < 3:
            raise ValueError(
                f"At least three valid N11/a0/{self.z_channel} points are required for a 3D surface."
            )

        accumulated: dict[tuple[float, float], list[float]] = {}
        for x_value, y_value, z_value in samples:
            accumulated.setdefault((x_value, y_value), []).append(z_value)

        coordinates = list(accumulated)
        x = np.asarray([point[0] for point in coordinates], dtype=float)
        y = np.asarray([point[1] for point in coordinates], dtype=float)
        z = np.asarray(
            [float(np.mean(accumulated[point])) for point in coordinates],
            dtype=float,
        )

        if len(x) < 3:
            raise ValueError("At least three unique N11/a0 points are required for triangulation.")
        if np.ptp(x) == 0.0 or np.ptp(y) == 0.0:
            raise ValueError("The N11/a0 points are collinear and cannot form a 3D surface.")

        triangulation = Triangulation(x, y)
        if triangulation.triangles.size == 0:
            raise ValueError("No valid triangles could be generated from the characteristic points.")

        surface = self.axes.plot_trisurf(
            triangulation,
            z,
            linewidth=0.35,
            antialiased=True,
            alpha=0.9,
        )
        self.axes.scatter(x, y, z, s=10)

        self.axes.set_xlabel("N11")
        self.axes.set_ylabel("a0")
        self.axes.set_zlabel(self.z_channel)
        self.axes.set_title(f"{self.z_channel}(N11, a0) - triangulated surface")
        self.figure.colorbar(
            surface,
            ax=self.axes,
            shrink=0.68,
            pad=0.1,
            label=self.z_channel,
        )
        self.figure.tight_layout()
        self.canvas.draw_idle()


class CharacteristicWindow3D(CharacteristicWindow):
    """TCEditor main window extended with Q11 and T11 3D surface views."""

    def __init__(self) -> None:
        super().__init__()
        self.surface_windows: dict[str, Surface3DWindow] = {}

        view_menu = self.menuBar().addMenu("View")

        self.q11_3d_action = view_menu.addAction("Q11 3D surface...")
        self.q11_3d_action.triggered.connect(lambda: self.show_3d_surface("Q11"))

        self.t11_3d_action = view_menu.addAction("T11 3D surface...")
        self.t11_3d_action.triggered.connect(lambda: self.show_3d_surface("T11"))

    def show_3d_surface(self, channel: str) -> None:
        if self.data is None:
            QtWidgets.QMessageBox.information(
                self,
                "3D Surface",
                "Open a characteristic file first.",
            )
            return

        if not self.data.groups or "N11" not in self.data.groups[0].channels:
            QtWidgets.QMessageBox.warning(
                self,
                "3D Surface Error",
                "The characteristic data must contain an N11 channel.",
            )
            return

        if channel not in self.data.groups[0].channels:
            QtWidgets.QMessageBox.warning(
                self,
                "3D Surface Error",
                f"The characteristic data does not contain a {channel} channel.",
            )
            return

        try:
            previous = self.surface_windows.get(channel)
            if previous is not None:
                previous.close()

            window = Surface3DWindow(self.data, channel)
            self.surface_windows[channel] = window
            window.destroyed.connect(
                lambda _=None, name=channel: self.surface_windows.pop(name, None)
            )
            window.show()
            window.raise_()
            window.activateWindow()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "3D Surface Error", str(exc))


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    pg.setConfigOptions(antialias=True)
    window = CharacteristicWindow3D()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
