from __future__ import annotations

import sys

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from qtpy import QtWidgets

from characteristic_parser import CharacteristicData
from tceditor import CharacteristicWindow


class Surface3DWindow(QtWidgets.QMainWindow):
    """Display one characteristic channel as a triangulated PyQtGraph OpenGL surface."""

    def __init__(self, data: CharacteristicData, z_channel: str) -> None:
        super().__init__()
        self.data = data
        self.z_channel = z_channel
        self.setWindowTitle(f"TCEditor - {z_channel}(N11, a0) 3D surface")
        self.resize(900, 700)

        self.view = gl.GLViewWidget()
        self.view.setBackgroundColor("w")
        self.setCentralWidget(self.view)

        self._build_surface()

    def _build_surface(self) -> None:
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

        triangulation = self._triangulate_xy(x, y)
        if triangulation.size == 0:
            raise ValueError("No valid triangles could be generated from the characteristic points.")

        vertices = np.column_stack((x, y, z)).astype(float)
        faces = np.asarray(triangulation, dtype=np.uint32)

        mesh_data = gl.MeshData(vertexes=vertices, faces=faces)
        mesh = gl.GLMeshItem(
            meshdata=mesh_data,
            smooth=False,
            drawFaces=True,
            drawEdges=True,
            edgeColor=(0.15, 0.15, 0.15, 0.8),
            color=(0.25, 0.55, 0.85, 0.65),
            shader="shaded",
            glOptions="translucent",
        )
        self.view.addItem(mesh)

        self._add_reference_axes(vertices)
        self._fit_camera(vertices)

    def _triangulate_xy(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Return Delaunay triangles in the N11-a0 plane without Matplotlib."""
        try:
            from scipy.spatial import Delaunay
        except ImportError as exc:
            raise RuntimeError(
                "3D triangulation requires scipy. Install it with: pip install scipy"
            ) from exc

        points = np.column_stack((x, y))
        try:
            return Delaunay(points).simplices
        except Exception as exc:
            raise ValueError(f"Unable to triangulate N11/a0 points: {exc}") from exc

    def _add_reference_axes(self, vertices: np.ndarray) -> None:
        mins = vertices.min(axis=0)
        maxs = vertices.max(axis=0)
        spans = np.maximum(maxs - mins, 1e-9)

        axis = gl.GLAxisItem()
        axis.setSize(x=float(spans[0]), y=float(spans[1]), z=float(spans[2]))
        axis.translate(float(mins[0]), float(mins[1]), float(mins[2]))
        self.view.addItem(axis)

        grid_xy = gl.GLGridItem()
        grid_xy.setSize(x=float(spans[0]), y=float(spans[1]))
        grid_xy.setSpacing(
            x=max(float(spans[0]) / 10.0, 1e-9),
            y=max(float(spans[1]) / 10.0, 1e-9),
        )
        grid_xy.translate(
            float((mins[0] + maxs[0]) / 2.0),
            float((mins[1] + maxs[1]) / 2.0),
            float(mins[2]),
        )
        self.view.addItem(grid_xy)

    def _fit_camera(self, vertices: np.ndarray) -> None:
        mins = vertices.min(axis=0)
        maxs = vertices.max(axis=0)
        center = (mins + maxs) / 2.0
        span = float(np.max(maxs - mins))
        if span <= 0.0:
            span = 1.0

        self.view.opts["center"] = pg.Vector(*center)
        self.view.setCameraPosition(distance=span * 2.5, elevation=25, azimuth=-45)


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
