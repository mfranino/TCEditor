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

- Choose **File > Add characteristic files...** or the **Add characteristic files...** button; select several files. Subsequent openings append files without replacing existing data. Opening an already loaded file does not duplicate it.
- The **Characteristic files** tree contains **file > constant-value curve** only. The first file column determines the constant-value grouping (such as `y` or `a0`). Each curve contains its original `N11`, `Q11`, `T11`, and any other imported arrays.
- Check or uncheck file and curve nodes to control which curves are shown. Use the **one global Y channels list** to select `Q11`, `T11`, or other channels for *all checked curves across all loaded files*. There are no repeated per-curve channel checkboxes. Select the X channel from the X-axis dropdown (`N11` by default); `Q11` uses the left axis and `T11` the right axis.
- Click a tree node to make its parent file the **active editing file** (shown in bold). Point dragging, point insertion/deletion, spreadsheet, metadata, undo/redo, and **Save characteristic as...** apply only to the active file; other files are read-only plot overlays until activated. The global Y-channel selection is retained when switching files.
- Right-click a curve to add a midpoint group (select two adjacent curves of the same file first) or delete selected curves from the active file. Right-click a file to remove it from the workspace without deleting it on disk.
- **View > Q11 3D surface...** or **View > T11 3D surface...** uses checked curves across all files. The requested 3D channel must also be selected in the global Y-channel list. Selected files must have the same first-column name and selected curves must have distinct constant values.

## Supported file format

The parser accepts metadata lines beginning with `;`, a `<list>` section, a header such as `y N11 Q11 T11` or `a0 N11 Q11 T11`, and numeric rows. An optional `</list>` marker is supported. It tries `utf-8-sig`, `cp1250`, and `latin-1`; rows may be whitespace-, tab-, semicolon-, or comma-separated.

## Editing and visualization

- Pan and zoom the 2D plot; click a point to select its spreadsheet row and hover to inspect row/channel information.
- Drag points to edit `N11` and the selected Y channel; right-click a point to add a midpoint or delete the row.
- Undo and redo point and group operations with `Ctrl+Z` and `Ctrl+Y`.
- The OpenGL 3D views connect neighboring constant-value curves. Each curve is linearly resampled to 150 normalized arc-length stations for mesh generation; original imported values remain unchanged.
- Each 3D view has real-value axis labels and a **Show scattered points** checkbox (off by default) to toggle the original points.

## Saving

**File > Save characteristic as...** writes only the active file's edited data, including its metadata, `<list>` structure, header, and `</list>` marker. Numeric rows are tab-separated; multiple files are never merged on disk.
