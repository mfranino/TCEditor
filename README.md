# TCEditor

TCEditor is a QtPy/pyqtgraph editor for pump-turbine characteristic files. It plots `Q11` and `T11` against `N11`, synchronizes graph/table point editing, and provides 3D surface views.

## Installation

Install Python 3.10 or newer:

```powershell
pip install numpy qtpy "pyqtgraph>=0.14.0" PySide6 scipy PyOpenGL
```

Launch the **multi-file editor with 2D and 3D views** (recommended):

```powershell
python tceditor_multifile.py
```

Legacy launchers remain available: `python tceditor.py` (single-file 2D) and `python tceditor_3d.py` (single-file 2D + 3D).

## Multi-file workflow

- Choose **File > Add characteristic files...** or the **Add characteristic files...** button; select several files in the dialog. Further openings append files instead of replacing the current workspace. Opening a file already loaded does not duplicate it.
- The **Characteristic files** tree is organized as **file > constant-value curve > channels**. The first file column determines the constant-value grouping (e.g. `y` or `a0`). Each group contains its original `N11`, `Q11`, and `T11` arrays (and any other imported channels).
- Check or uncheck file nodes, individual curve nodes, and individual channel nodes to show/hide their corresponding 2D curves. Checked curves from different files are overlaid on the same axes. `N11` is the default X axis, with `Q11` on the left and `T11` on the right.
- Click any tree node to make its parent file the **active editing file** (shown in bold). Point dragging, point insertion/deletion, the spreadsheet, metadata, undo/redo, and **Save characteristic as...** apply only to this active file. Other files appear as read-only overlay curves until activated.
- Right-click a curve in the tree to add a midpoint group (select two adjacent curves of the same file first) or to delete selected curves from the active file. Right-click a file to remove it from the workspace; this does not delete the disk file.
- **View > Q11 3D surface...** or **View > T11 3D surface...** builds one surface from the checked curves in all loaded files. The selected files must share the same first-column name and the checked curves must have distinct constant values; uncheck duplicates if necessary.

## Supported file format

The parser accepts metadata lines beginning with `;`, a `<list>` section, a column header such as `y N11 Q11 T11` or `a0 N11 Q11 T11`, and numeric rows. The optional `</list>` marker is supported. File encodings `utf-8-sig`, `cp1250`, and `latin-1` are tried; rows can be separated by whitespace, tabs, semicolons, or commas.

## Editing and visualization

- Pan and zoom the 2D plot. Click a plotted point to select its corresponding spreadsheet row; hover to see channel and row information.
- Drag points to edit `N11` and the selected Y channel. Right-click a point to add a midpoint or delete that row.
- Undo/redo point and group operations using `Ctrl+Z` and `Ctrl+Y`.
- The 3D OpenGL views use a topology-preserving mesh between neighboring constant-value groups. Each curve is linearly resampled at 150 equally spaced normalized arc-length stations for meshing; imported measurement points remain unchanged.
- Each 3D view has actual numerical axis labels and a **Show scattered points** checkbox (off by default) to toggle the original imported data points.

## Saving

**File > Save characteristic as...** writes only the active file's edited data, preserving its `;` metadata, `<list>` structure, header, and `</list>` marker. Rows in the saved file are tab-separated. Loading multiple files does not combine their data on disk.
