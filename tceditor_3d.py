from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from qtpy import QtGui, QtWidgets

from characteristic_parser import CharacteristicData
from tceditor import CharacteristicWindow


def _require_pyqtgraph_014() -> None:
    try:
        raw_version = version("pyqtgraph")
    except PackageNotFoundError as exc:
        raise RuntimeError("PyQtGraph is not installed.") from exc

    numeric = []
    for part in raw_version.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            break
        numeric.append(int(digits))
        if len(numeric) == 2:
            break

    current = tuple(numeric + [0] * (2 - len(numeric)))
    if current < (0, 14):
        raise RuntimeError(
            f"TCEditor 3D requires PyQtGraph 0.14 or newer; found {raw_version}. "
            "Upgrade with: python -m pip install --upgrade \"pyqtgraph>=0.14.0\" PyOpenGL"
        )


class Surface3DWindow(QtWidgets.QMainWindow):
    """Display one characteristic channel as a triangulated PyQtGraph OpenGL surface."""

    DISPLAY_SPANS = np.asarray([12.0, 8.0, 6.0], dtype=float)
    AXIS_TICK_COUNT = 5

    def __init__(self, data: CharacteristicData, z_channel: str) -> None:
        super().__init__()
        self.data = data
        self.z_channel = z_channel
        self.scatter_item = None
        self.setWindowTitle(f"TCEditor - {z_channel}(N11, a0) 3D surface")
        self.resize(900, 700)

        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)

        self.show_points_check = QtWidgets.QCheckBox("Show scattered points")
        self.show_points_check.setChecked(False)
        self.show_points_check.toggled.connect(self._set_scatter_visible)
        layout.addWidget(self.show_points_check)

        self.view = gl.GLViewWidget()
        self.view.setBackgroundColor("w")
        layout.addWidget(self.view, stretch=1)
        self.setCentralWidget(central)

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

        raw_vertices = np.column_stack((x, y, z)).astype(float)
        raw_mins = raw_vertices.min(axis=0)
        raw_maxs = raw_vertices.max(axis=0)
        display_vertices = self._scale_vertices_for_display(raw_vertices)
        faces = np.asarray(triangulation, dtype=np.uint32)

        mesh_data = gl.MeshData(vertexes=display_vertices, faces=faces)
        mesh = gl.GLMeshItem(
            meshdata=mesh_data,
            smooth=False,
            drawFaces=True,
            drawEdges=True,
            edgeColor=(0.15, 0.15, 0.15, 0.85),
            color=(0.25, 0.55, 0.85, 0.72),
            shader="shaded",
            glOptions="translucent",
        )
        self.view.addItem(mesh)

        self.scatter_item = gl.GLScatterPlotItem(
            pos=display_vertices,
            size=6,
            color=(0.05, 0.05, 0.05, 1.0),
            pxMode=True,
        )
        self.scatter_item.setVisible(self.show_points_check.isChecked())
        self.view.addItem(self.scatter_item)

        self._add_reference_axes(raw_mins, raw_maxs)
        self._fit_camera(display_vertices)

    def _set_scatter_visible(self, visible: bool) -> None:
        if self.scatter_item is not None:
            self.scatter_item.setVisible(visible)

    def _scale_vertices_for_display(self, vertices: np.ndarray) -> np.ndarray:
        """Scale N11, a0 and Z independently so all three dimensions remain visible."""
        mins = vertices.min(axis=0)
        spans = vertices.max(axis=0) - mins
        safe_spans = np.where(spans > 1e-12, spans, 1.0)
        normalized = (vertices - mins) / safe_spans
        return normalized * self.DISPLAY_SPANS

    def _triangulate_xy(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Return Delaunay triangles in the real N11-a0 plane."""
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

    def _add_reference_axes(self, raw_mins: np.ndarray, raw_maxs: np.ndarray) -> None:
        """Add normalized OpenGL axes with labels showing the real engineering values."""
        x_span, y_span, z_span = (float(value) for value in self.DISPLAY_SPANS)

        axis = gl.GLAxisItem()
        axis.setSize(x=x_span, y=y_span, z=z_span)
        self.view.addItem(axis)

        grid_xy = gl.GLGridItem()
        grid_xy.setSize(x=x_span, y=y_span)
        grid_xy.setSpacing(x=x_span / 10.0, y=y_span / 10.0)
        grid_xy.translate(x_span / 2.0, y_span / 2.0, 0.0)
        self.view.addItem(grid_xy)

        label_font = QtGui.QFont("Arial", 11)
        title_font = QtGui.QFont("Arial", 13)
        title_font.setBold(True)
        text_color = (20, 20, 20, 255)

        real_ticks = [
            np.linspace(float(raw_mins[axis_index]), float(raw_maxs[axis_index]), self.AXIS_TICK_COUNT)
            for axis_index in range(3)
        ]
        display_ticks = [
            np.linspace(0.0, float(self.DISPLAY_SPANS[axis_index]), self.AXIS_TICK_COUNT)
            for axis_index in range(3)
        ]

        for display_value, real_value in zip(display_ticks[0], real_ticks[0]):
            self._add_text(
                (float(display_value), -0.38, -0.16),
                self._format_axis_value(real_value),
                label_font,
                text_color,
            )

        for display_value, real_value in zip(display_ticks[1], real_ticks[1]):
            self._add_text(
                (-0.58, float(display_value), -0.16),
                self._format_axis_value(real_value),
                label_font,
                text_color,
            )

        for display_value, real_value in zip(display_ticks[2], real_ticks[2]):
            self._add_text(
                (-0.58, -0.30, float(display_value)),
                self._format_axis_value(real_value),
                label_font,
                text_color,
            )

        self._add_text((x_span + 0.45, 0.0, 0.0), "N11", title_font, text_color)
        self._add_text((0.0, y_span + 0.45, 0.0), "a0", title_font, text_color)
        self._add_text((0.0, 0.0, z_span + 0.45), self.z_channel, title_font, text_color)

    def _add_text(
        self,
        position: tuple[float, float, float],
        text: str,
        font: QtGui.QFont,
        color,
    ) -> None:
        item = gl.GLTextItem(
            pos=np.asarray(position, dtype=float),
            text=text,
            color=color,
            font=font,
        )
        self.view.addItem(item)

    def _format_axis_value(self, value: float) -> str:
        return f"{float(value):.5g}"

    def _fit_camera(self, vertices: np.ndarray) -> None:
        mins = vertices.min(axis=0)
        maxs = vertices.max(axis=0)
        center = (mins + maxs) / 2.0
        span = float(np.max(maxs - mins))
        if span <= 0.0:
            span = 1.0

        self.view.opts["center"] = pg.Vector(*center)
        self.view.setCameraPosition(distance=span * 2.1, elevation=24, azimuth=-45)


class CharacteristicWindow3D(CharacteristicWindow):
    """TCEditor main window extended with Q11 and T11 3D surface views."""

    def __init__(self) -> None:
        self.surface_windows: dict[str, Surface3DWindow] = {}
        super().__init__()

        view_menu = self.menuBar().addMenu("View")

        self.q11_3d_action = view_menu.addAction("Q11 3D surface...")
        self.q11_3d_action.triggered.connect(lambda: self.show_3d_surface("Q11"))

        self.t11_3d_action = view_menu.addAction("T11 3D surface...")
        self.t11_3d_action.triggered.connect(lambda: self.show_3d_surface("T11"))

    def _forget_surface_window(self, channel: str) -> None:
        windows = getattr(self, "surface_windows", None)
        if windows is not None:
            windows.pop(channel, None)

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
                lambda _=None, name=channel: self._forget_surface_window(name)
            )
            window.show()
            window.raise_()
            window.activateWindow()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "3D Surface Error", str(exc))


def main() -> int:
    try:
        _require_pyqtgraph_014()
    except RuntimeError as exc:
        print(exc)
        return 1

    app = QtWidgets.QApplication(sys.argv)
    pg.setConfigOptions(antialias=True)
    window = CharacteristicWindow3D()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
