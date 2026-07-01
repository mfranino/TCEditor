# TCEditor

Small QtPy + pyqtgraph application for opening characteristic data files and plotting XY channel data.

## Run

```powershell
pip install -r requirements.txt
python tceditor.py
```

## Characteristic Import

The parser is based on the MyScope characteristic import flow:

- reads `utf-8-sig`, `cp1250`, or `latin-1`
- supports optional `<list>` data sections
- preserves leading `;` metadata lines
- uses the first column as the grouping column
- uses `N11` as the default X-axis channel when present
- plots selected numeric Y channels against the selected X-axis channel
- uses the left Y-axis for `Q11` and the right Y-axis for `T11`
- preserves the current zoom/pan when plotted data is refreshed
- lets you drag plotted points to edit the in-memory X/Y values on the chart
- highlights the corresponding spreadsheet row when a plotted point is selected
- lets you select two neighboring groups and use the group context menu to add a midpoint characteristic group
- lets you delete one or more selected groups from the group context menu
- lets you right-click a point and choose `Add point` to insert a midpoint between neighboring rows
- lets you right-click a point and choose `Delete point`
- supports undo for point moves/adds/deletes and group additions/deletions with `Ctrl+Z`
- supports redo with `Ctrl+Y`
- shows the loaded data values in a spreadsheet-style table on the right side
- saves edited characteristic data as metadata, `<list>`, tab-separated header/data rows, and `</list>`

Unlike the current MyScope sample, this parser also accepts common delimited data rows such as comma, semicolon, and tab-separated files.
