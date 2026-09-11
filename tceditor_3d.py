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
    """Display one characteristic channel as a topology-preserving OpenGL surface."""

    DISPLAY_SPANS = np.asarray([12.0, 8.0, 6.0], dtype=float)
    AXIS_TICK_COUNT = 5
    RESAMPLE_COUNT = 150

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
        original_groups = self._collect_group_curves()
        if len(original_groups) < 2:
            raise ValueError("At least two characteristic groups are required for a 3D surface.")

        original_vertices = np.vstack(
            [
                np.column_stack(
                    (
                        group["x"],
                        np.full(len(group["x"]), group["a0"], dtype=float),
                        group["z"],
                    )
                )
                for group in original_groups
            ]
        )
        if len(original_vertices) < 3:
            raise ValueError(
                f"At least three valid N11/a0/{self.z_channel} points are required for a 3D surface."
            )

        raw_mins = original_vertices.min(axis=0)
        raw_maxs = original_vertices.max(axis=0)
        raw_spans = raw_maxs - raw_mins

        resampled_groups = [
            self._resample_curve(group, raw_spans[0], raw_spans[2])
            for group in original_groups
        ]
        raw_mesh_vertices, faces = self._build_regular_strip_mesh(resampled_groups)
        if len(faces) == 0:
            raise ValueError("No valid surface triangles could be generated between neighboring groups.")

        display_vertices = self._scale_vertices_for_display(
            raw_mesh_vertices,
            raw_mins,
            raw_maxs,
        )
        faces_array = np.asarray(faces, dtype=np.uint32)

        mesh_data = gl.MeshData(vertexes=display_vertices, faces=faces_array)
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

        scatter_vertices = self._scale_vertices_for_display(
            original_vertices,
            raw_mins,
            raw_maxs,
        )
        self.scatter_item = gl.GLScatterPlotItem(
            pos=scatter_vertices,
            size=6,
            color=(0.05, 0.05, 0.05, 1.0),
            pxMode=True,
        )
        self.scatter_item.setVisible(self.show_points_check.isChecked())
        self.view.addItem(self.scatter_item)

        self._add_reference_axes(raw_mins, raw_maxs)
        self._fit_camera(display_vertices)

    def _collect_group_curves(self) -> list[dict[str, object]]:
        """Collect valid characteristic curves and keep their original point order."""
        curves: list[dict[str, object]] = []

        for group in self.data.groups:
            n11 = group.channels.get("N11")
            values = group.channels.get(self.z_channel)
            if n11 is None or values is None:
                continue

            x = np.asarray(n11, dtype=float)
            z = np.asarray(values, dtype=float)
            valid = np.isfinite(x) & np.isfinite(z)
            x = x[valid]
            z = z[valid]
            if len(x) < 2:
                continue

            curves.append(
                {
                    "a0": float(group.value),
                    "x": x,
                    "z": z,
                }
            )

        curves.sort(key=lambda item: float(item["a0"]))
        return curves

    def _resample_curve(
        self,
        curve: dict[str, object],
        global_x_span: float,
        global_z_span: float,
    ) -> dict[str, object]:
        """Resample one curve on a common normalized arc-length coordinate."""
        x = np.asarray(curve["x"], dtype=float)
        z = np.asarray(curve["z"], dtype=float)

        x_scale = global_x_span if global_x_span > 1e-12 else 1.0
        z_scale = global_z_span if global_z_span > 1e-12 else 1.0
        dx = np.diff(x) / x_scale
        dz = np.diff(z) / z_scale
        segment_length = np.hypot(dx, dz)
        s = np.concatenate(([0.0], np.cumsum(segment_length)))

        if s[-1] <= 1e-12:
            raise ValueError(f"Characteristic group a0={curve['a0']} has zero curve length.")

        s /= s[-1]

        # np.interp requires strictly increasing sample locations. Remove repeated
        # arc-length stations caused by duplicate consecutive points.
        keep = np.concatenate(([True], np.diff(s) > 1e-12))
        s = s[keep]
        x = x[keep]
        z = z[keep]
        if len(s) < 2:
            raise ValueError(f"Characteristic group a0={curve['a0']} has too few unique points.")

        s_new = np.linspace(0.0, 1.0, self.RESAMPLE_COUNT)
        return {
            "a0": float(curve["a0"]),
            "x": np.interp(s_new, s, x),
            "z": np.interp(s_new, s, z),
        }

    def _build_regular_strip_mesh(
        self,
        groups: list[dict[str, object]],
    ) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
        """Build a regular mesh after all curves share the same arc-length stations."""
        vertices: list[np.ndarray] = []
        for group in groups:
            x = np.asarray(group["x"], dtype=float)
            z = np.asarray(group["z"], dtype=float)
            y = np.full(len(x), float(group["a0"]), dtype=float)
            vertices.append(np.column_stack((x, y, z)))

        mesh_vertices = np.vstack(vertices)
        points_per_group = self.RESAMPLE_COUNT
        faces: list[tuple[int, int, int]] = []

        for group_index in range(len(groups) - 1):
            lower_offset = group_index * points_per_group
            upper_offset = (group_index + 1) * points_per_group
            for point_index in range(points_per_group - 1):
                p00 = lower_offset + point_index
                p01 = lower_offset + point_index + 1
                p10 = upper_offset + point_index
                p11 = upper_offset + point_index + 1
                faces.append((p00, p01, p10))
                faces.append((p01, p11, p10))

        return mesh_vertices, faces

    def _set_scatter_visible(self, visible: bool) -> None:
        if self.scatter_item is not None:
            self.scatter_item.setVisible(visible)

    def _scale_vertices_for_display(
        self,
        vertices: np.ndarray,
        raw_mins: np.ndarray,
        raw_maxs: np.ndarray,
    ) -> np.ndarray:
        """Scale N11, a0 and Z independently so all three dimensions remain visible."""
        spans = raw_maxs - raw_mins
        safe_spans = np.where(spans > 1e-12, spans, 1.0)
        normalized = (vertices - raw_mins) / safe_spans
        return normalized * self.DISPLAY_SPANS

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
