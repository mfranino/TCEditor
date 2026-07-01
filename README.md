# TCEditor

TCEditor is a small QtPy and pyqtgraph application for editing pump-turbine characteristic files. It opens characteristic text files, plots `Q11` and `T11` against `N11`, and keeps the graph and spreadsheet view synchronized while points and groups are edited.

## Installation

Install Python 3.10 or newer, then install the required packages:

```powershell
pip install numpy qtpy pyqtgraph PySide6
```

Run the application:

```powershell
python tceditor.py
```

## Supported File Format

The parser is based on the MyScope characteristic import flow. It supports files with:

- metadata lines starting with `;`
- a `<list>` data section
- a column header such as `a0    N11    Q11    T11`
- numeric rows grouped by the first column
- an optional closing `</list>`

Files are read with `utf-8-sig`, `cp1250`, or `latin-1` encoding. Data rows may be whitespace, tab, semicolon, or comma separated.

## Main Functions

- Open characteristic files with `File > Open characteristic...`.
- Use `N11` as the default X axis.
- Plot `Q11` on the left Y axis and `T11` on the right Y axis.
- Select visible groups and Y channels from the left control panel.
- Pan and zoom the graph manually; refreshes preserve the current view range.
- View all parsed data in the spreadsheet table on the right.
- Click a plotted point to highlight the corresponding spreadsheet row.
- Hover a point to show group, row, `N11`, and selected Y value.
- Drag plotted points to edit `N11` and the selected Y channel.
- Right-click a point to add a midpoint row or delete the selected row.
- Select two neighboring groups, then use the group context menu to add a midpoint characteristic group.
- Use the group context menu to delete one or more selected groups.
- Undo point moves, point add/delete operations, and group add/delete operations with `Ctrl+Z`.
- Redo edits with `Ctrl+Y`.
- Save edited data with `File > Save characteristic as...`.

## Saving

Saved files preserve the characteristic text structure:

- `;` metadata lines
- `<list>`
- tab-separated header and numeric rows
- `</list>`
