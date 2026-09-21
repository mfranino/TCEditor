# TCEditor

TCEditor is a Python/Qt application for viewing and editing pump-turbine four-quadrant characteristic data. It supports multiple characteristic files in one workspace, selection of constant-opening curves, a shared channel selector, interactive 2D editing, a data table, and OpenGL 3D surfaces.

> **Current launcher:** `tceditor_stacked.py`. The older `tceditor.py`, `tceditor_3d.py`, and `tceditor_multifile.py` launchers are retained but do not provide the complete latest stacked interface.
>
> **Development status:** This is an actively developed tool. Selection/plot synchronization across multiple files is under investigation; check the actual plotted curves and version before relying on a comparison. The 3D surface is a visualization based on interpolation, not a replacement for measured data.

## 1. Installation and running

Install Python 3.10 or newer and the required packages in the *same Python environment* used to run TCEditor:

```powershell
python -m pip install numpy qtpy "pyqtgraph>=0.14.0" PySide6 scipy PyOpenGL
```

From a local Git checkout:

```powershell
cd "C:\Labview aplikacije\TCEditor"
git switch TCEditor-next-changes
git pull origin TCEditor-next-changes
python tceditor_stacked.py
```

Or use Spyder (after restarting its kernel following updates):

```python
%runfile 'C:/Labview aplikacije/TCEditor/tceditor_stacked.py' --wdir
```

You do **not** need to run `tceditor.py` separately. If the displayed application does not match this README, verify the launcher, active branch, and local Git revision.

### Alternative launchers

| File | Purpose |
| --- | --- |
| `tceditor_stacked.py` | Latest multi-file launcher with vertically stacked, resizable controls and version display. **Use this.** |
| `tceditor_multifile.py` | Earlier multi-file interface with a separate dock for the file tree. |
| `tceditor_3d.py` | Single-file editor with 3D windows. |
| `tceditor.py` | Original single-file 2D editor. |

## 2. File format and internal organization

A characteristic file contains metadata, a column header, and numerical rows. Typical layout:

```text
;Optional metadata about the characteristic
<list>
y    N11    Q11    T11
0.5  -100  -0.2  100
0.5   -90  -0.1  110
0.6  -100  -0.3  120
0.6   -90  -0.2  130
</list>
```

These sample values illustrate the format only. The first column is the *grouping variable*, often `y` or `a0`. All rows with a common first-column value form one characteristic curve at that constant opening. The next columns are channels such as `N11`, `Q11`, and `T11`. Each curve may contain a different number of points. The parser preserves the original row order of the points within each group.

Supported file extensions in the file dialog are `.txt`, `.dat`, and `.csv` (the dialog also has an all-files option). The parser tries UTF-8 with BOM, CP1250, and Latin-1 and accepts whitespace, tab, semicolon, or comma delimiters. Metadata lines begin with `;`; the `<list>` section and optional closing `</list>` delimit the data. Invalid/non-numeric rows are skipped by the parser, so inspect the displayed row counts after importing.

## 3. Load several characteristic files

Choose **File → Add characteristic files...** (`Ctrl+O`) or click the **Add characteristic files...** button. Select one or multiple files in the file dialog. Additional imports append to the workspace rather than replacing existing files. An already loaded path is not loaded a second time.

The file tree contains two levels only:

```text
Characteristic_A.txt
    y=0.5 (80 points)
    y=0.6 (84 points)
Characteristic_B.txt
    y=0.5 (78 points)
    y=0.6 (82 points)
```

There are **no N11/Q11/T11 sub-branches** and no per-curve channel checkboxes. The name in parentheses reports how many points belong to that constant-`y` curve.

### Select which curves to plot

In the stacked interface, click a constant-`y` row to select it. The tree uses additive selection: click more rows, including rows in other files, to combine them; click a selected row again to deselect it. Highlighted **curve rows** are intended to define the plotted curves. File headings are organizational containers, not an implicit command to plot every curve. Expanding/collapsing a heading does not change the underlying characteristic data.

**Important:** Cross-file selection/plot synchronization has been reported to display more curves than highlighted in some runs and is not yet confirmed fixed in the user's installation. Until verified, check the legend and rendered curves rather than assuming every visible trace corresponds to a selected row.

The selected *plotting curves* and the **active editing file** are separate concepts (see §6).

## 4. Control column and graph

The stacked launcher places the controls in one sidebar: **Add characteristic files**, **X axis**, **Files / constant-y curves**, **Y channels**, and **Metadata**. Drag the horizontal divider between the file tree, channel list, and metadata to resize these panels vertically. Drag the vertical divider between the sidebar and graph to resize the overall control column; the graph and data table occupy the other side of the main window.

### X axis

Choose the horizontal channel from the **X axis** dropdown; `N11` is selected by default when available. Changing the choice redraws the plot.

### Y channels — one global selection

Select `Q11`, `T11`, or other imported channels in the single **Y channels** list. This selection applies to all plotted characteristic curves, including those from different files. Multi-selection permits `Q11` and `T11` simultaneously. A channel equal to the X-axis channel is not plotted against itself.

- `Q11` appears on the left Y axis.
- `T11` appears on the right Y axis.
- Other channels use the left Y axis in the current implementation.

The channel selector is global; switching the active file should preserve its selection. A channel absent from a particular curve is skipped for that curve.

### 2D plot and legend

The plot overlays the chosen channels against the chosen X channel. Each series uses a colored line, with editable point markers for the active editing file. Series from other files are drawn as read-only overlays until their file becomes active. The legend identifies characteristic groups and channels; overlay entries include a file name. A large number of visible series can crowd the legend and reduce readability.

Pan and zoom using the graph's normal PyQtGraph interactions. Plot refreshes attempt to preserve the previous axis ranges; the initial plot auto-ranges. The **File → Clear plot** menu item removes the displayed graph items; it does not delete imported files or data. A later selection/refresh can draw them again.

## 5. Point editing and data table

The table shows the **active file's complete dataset**, with a row for each original or edited point and columns for the grouping variable, row index, and imported channels. It is a read-only table: make numerical changes through the graph rather than typing into table cells.

On a plotted editable point:

| Action | Result |
| --- | --- |
| Hover | Show group, point row, X value, and Y-channel value in a tooltip. |
| Left-click | Select and scroll to the corresponding row in the data table. |
| Left-drag | Move that point in the plotted X and Y channels; the active file's arrays and table are updated. |
| Right-click → **Add point** | Insert a point between adjacent rows using channel-wise midpoint values. At the last point, insert between the previous and last rows. |
| Right-click → **Delete point** | Remove that point from its characteristic curve in memory. |

Dragging can change both the selected X and Y channel at once. Point insertion interpolates **all channels** at the insertion location, not only the currently plotted channel. Deleting the last point in a curve can remove the empty curve from the active dataset.

### Undo and redo

Use **Edit → Undo** (`Ctrl+Z`) or **Edit → Redo** (`Ctrl+Y`) for point moves, point insertion/deletion, and group insertion/deletion. The multi-file application retains separate undo/redo histories for loaded files, and operations apply to the active editing file. Removing a file from the workspace also discards that file's in-memory history.

## 6. Active editing file and context menu

The tree can contain several loaded files, but **only one file is active for editing and saving at a time**. The active file's name appears in the window title; its file heading is displayed in bold when the tree is rebuilt. Merely choosing curves for plotting is not equivalent to switching the active editing file.

Right-click a file or curve to open its context menu:

| Menu command | What it does |
| --- | --- |
| **Edit this file** | Make the clicked file active. Its dataset is shown in the table and metadata panel; point and group edits and Save As refer to this file. |
| **Add midpoint group between selected curves** | Create a new constant-opening curve halfway between exactly two selected **neighboring** curves of the same file. The implementation resamples each channel linearly on a normalized point-index grid, averages corresponding values, and inserts the midpoint group into the active file. This is an interpolated curve, **not measured data**. |
| **Delete selected curves from active file** | Delete selected constant-opening groups from the active file's in-memory dataset. Undo is supported. The disk file is unchanged until a save. |
| **Remove file from workspace (keep on disk)** | Unload the clicked file and its overlays from the application. This does **not** delete or overwrite the file on disk. Unsaved in-memory changes to that file are lost when it is removed. |

The group-edit commands operate on curves **within one file**; selecting curves from different files does not create a cross-file midpoint group. For the midpoint action, choose two adjacent curves from the target file. The original editor checks that both groups contain the same set of channels, including `N11`, `Q11`, and `T11`.

## 7. Save characteristic as...

**File → Save characteristic as...** (`Ctrl+S`) saves **the complete active editing file only**. It does not save all currently loaded files, combine files, or export only the curves selected for plotting.

Before saving, check the active file's name in the title bar. To save another characteristic, right-click it and choose **Edit this file**, then use Save As. The file dialog proposes a name based on the source with `_modified` appended, and you can choose another path. Saving writes the entire current active dataset—including unplotted curves and all edits—to the chosen output file. It does not automatically replace the originally imported file unless you explicitly choose that path.

The writer includes the metadata prefixed with `;`, `<list>`, column header, tab-separated numeric rows, and `</list>`. Numbers are formatted to roughly 12 significant digits; original whitespace/number formatting is **not** reproduced byte-for-byte. Save each edited file separately.

## 8. Three-dimensional characteristic surfaces

Choose **View → Q11 3D surface...** or **View → T11 3D surface...**. The 3D viewer places `N11` on X, the constant-opening value (`y` or `a0`, as determined by the file's first-column name) on Y, and `Q11` or `T11` on Z.

The combined 3D view considers the currently selected constant-opening curves across files, subject to these conditions:

- At least two usable curves must be selected.
- The requested Z channel must be selected in the global **Y channels** list and exist in the curves, together with `N11`.
- The selected files must use the same grouping-column name.
- Selected curves must have **distinct opening values**. If the same `y` value occurs in two selected files, deselect one before constructing a single surface.

### Mesh generation

For every original curve, the viewer calculates normalized cumulative arc length from the `N11` and Z-channel coordinates, after scaling the two spans. Duplicate consecutive stations are removed. `numpy.interp` then **linearly** resamples each curve onto 150 evenly spaced arc-length stations. Corresponding points on neighboring opening curves are connected into quadrilateral strips, each split into two triangles. This avoids the earlier global Delaunay links between unrelated parts of folded curves, but it is still an interpolation and its shape depends on curve ordering/correspondence.

The three plot dimensions are independently normalized for display so that a small opening range does not flatten the surface. Numeric axis labels report the **original engineering values**, rather than the normalized display coordinates. Rotate/zoom using the 3D view's PyQtGraph mouse controls.

The **Show scattered points** checkbox in each 3D window is off by default. Toggle it to overlay the **original imported/edited characteristic points** on the interpolated mesh. Mesh resampling never modifies the source arrays. Opening a 3D window uses the current in-memory values at that time; reopen it after further edits or selection changes to regenerate the surface.

A combined surface is suitable for visual inspection, but it does not resolve ambiguous correspondences, duplicated opening values, or physical discontinuities automatically.

## 9. Version information and updates

The stacked launcher reports a version and abbreviated Git revision in **three places**: the title bar, the status bar, and the Spyder/terminal console. Example:

```text
TCEditor v0.0.1 [edbcdae]
```

The version series starts at `0.0.1` at the first commit after base commit `7ef8776`. The implementation counts commits from this base to the **local `HEAD`** and uses that count as the patch number. Thus each subsequent commit on the branch increments `0.0.N` when the user pulls it. Documentation-only commits increment it too; this is a **commit counter, not semantic versioning**.

When Git, the base commit, or the relevant history cannot be accessed, the script falls back to `0.0.1 [Git revision unavailable]`. That fallback does **not** confirm that the installation is current. A local modified checkout can share a version number with its unmodified `HEAD`, so check `git status` as well when troubleshooting.

To update and confirm your local revision:

```powershell
cd "C:\Labview aplikacije\TCEditor"
git switch TCEditor-next-changes
git pull origin TCEditor-next-changes
git status
git log -1 --oneline
```

Then **close the previous TCEditor window, restart the Spyder kernel**, and run `tceditor_stacked.py` again. Spyder `%runfile` can reuse Python/Qt/OpenGL state without a kernel restart.

## 10. Common problems and limitations

| Symptom | Check or action |
| --- | --- |
| Old checkbox tree, missing layout or no version | Confirm you run `tceditor_stacked.py`, pull the branch, close old windows and restart Spyder's kernel. |
| Selected only a few curves but many are still plotted | This is a reported selection/plot synchronization issue; confirm the exact version/revision and share a screenshot and selected rows. Do not assume it is fixed solely because rows highlight correctly. |
| Missing `Q11`/`T11` or blank plot | Confirm the global Y channels selection, X-axis choice, imported channel names and selected constant-`y` rows. |
| 3D window refuses selected curves from different files | Check duplicate opening values and consistent first-column names. |
| OpenGL shader error | Use PyQtGraph 0.14+ and PyOpenGL in Spyder's actual Python environment; restart the kernel. Graphics drivers/contexts can also affect OpenGL. |
| Need to preserve an imported file | Use Save As with a different filename. Removing a file from the workspace never deletes its disk copy, but unsaved in-memory edits are not retained on removal. |

## 11. Project files

| File | Responsibility |
| --- | --- |
| `characteristic_parser.py` | Read, group and write characteristic text data. |
| `tceditor.py` | Original 2D graph, point/group editing, table and undo/redo. |
| `tceditor_3d.py` | OpenGL mesh viewer and single-file 3D launcher. |
| `tceditor_multifile.py` | Multi-file workspace, plot overlays and active-file bookkeeping. |
| `tceditor_stacked.py` | Recommended launcher: vertically resizable controls, explicit curve selection and version display. |

**Safety reminder:** Imported files are not automatically overwritten. The plotting selection controls visibility, while the active editing file controls what is modified and saved. Verify the active file and output path before saving.
