from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class CharacteristicGroup:
    name: str
    value: float
    x: np.ndarray
    channels: dict[str, np.ndarray]
    row_count: int


@dataclass(frozen=True)
class CharacteristicData:
    source_file: Path
    header: list[str]
    metadata: list[str]
    group_column: str
    groups: list[CharacteristicGroup]


ENCODINGS = ("utf-8-sig", "cp1250", "latin-1")


def parse_characteristic_file(file_path: str | Path) -> CharacteristicData:
    path = Path(file_path)
    lines = _read_lines(path)
    if not lines:
        raise RuntimeError("Characteristic file is empty.")

    list_start_idx = _find_list_marker(lines)
    metadata, metadata_header = _read_metadata(lines, list_start_idx)
    data_start_idx = (list_start_idx + 1) if list_start_idx is not None else 0

    header, data_start_idx = _find_header(lines, data_start_idx, metadata_header)
    if not header or len(header) < 2:
        raise RuntimeError("Characteristic column header row not found.")

    rows = _read_numeric_rows(lines, data_start_idx, len(header))
    if not rows:
        raise RuntimeError("No valid characteristic data rows found.")

    data = np.asarray(rows, dtype=float)
    group_column = header[0].strip() or "group"
    channel_names = [_clean_channel_name(name, idx) for idx, name in enumerate(header[1:], start=1)]

    groups = _build_groups(data, group_column, channel_names)
    if not groups:
        raise RuntimeError("Characteristic file produced no groups with data channels.")

    return CharacteristicData(
        source_file=path,
        header=header,
        metadata=metadata,
        group_column=group_column,
        groups=groups,
    )


def write_characteristic_file(data: CharacteristicData, file_path: str | Path) -> None:
    path = Path(file_path)
    channel_names = [name for name in data.header[1:] if name]
    if not channel_names and data.groups:
        channel_names = list(data.groups[0].channels.keys())

    lines: list[str] = []
    for metadata_line in data.metadata:
        lines.append(f";{metadata_line}")
    lines.append("<list>")
    lines.append("\t".join([data.group_column, *channel_names]))

    for group in data.groups:
        row_count = min([group.row_count, *(len(group.channels[name]) for name in channel_names)])
        for row_idx in range(row_count):
            values = [_format_number(group.value)]
            values.extend(_format_number(group.channels[name][row_idx]) for name in channel_names)
            lines.append("\t".join(values))

    lines.append("</list>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_lines(path: Path) -> list[str]:
    last_error = None
    for encoding in ENCODINGS:
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                return [line.rstrip("\r\n") for line in f]
        except UnicodeDecodeError as exc:
            last_error = exc
    raise RuntimeError(f"Could not decode characteristic file: {last_error}")


def _find_list_marker(lines: list[str]) -> int | None:
    for idx, line in enumerate(lines):
        if line.strip().lower() == "<list>":
            return idx
    return None


def _read_metadata(lines: list[str], list_start_idx: int | None) -> tuple[list[str], list[str] | None]:
    metadata: list[str] = []
    header: list[str] | None = None
    scan_end = list_start_idx if list_start_idx is not None else len(lines)

    for line in lines[:scan_end]:
        stripped = line.strip()
        if not stripped or not stripped.startswith(";"):
            continue
        text = stripped[1:].strip()
        metadata.append(text)
        tokens = split_characteristic_line(text)
        if _looks_like_header(text, tokens):
            header = tokens

    return metadata, header


def _find_header(
    lines: list[str],
    data_start_idx: int,
    metadata_header: list[str] | None,
) -> tuple[list[str] | None, int]:
    for idx in range(data_start_idx, len(lines)):
        stripped = lines[idx].strip()
        if not stripped or stripped.startswith(";"):
            continue
        if stripped.startswith("<"):
            break

        tokens = split_characteristic_line(stripped)
        if not tokens:
            continue
        if _tokens_are_numeric(tokens):
            if metadata_header is not None:
                return metadata_header, idx
            continue
        return tokens, idx + 1

    return metadata_header, data_start_idx


def _read_numeric_rows(lines: list[str], data_start_idx: int, column_count: int) -> list[list[float]]:
    rows: list[list[float]] = []
    for line in lines[data_start_idx:]:
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if stripped.startswith("<"):
            break

        tokens = split_characteristic_line(stripped)
        if len(tokens) != column_count:
            continue
        try:
            rows.append([parse_number(token) for token in tokens])
        except ValueError:
            continue
    return rows


def _build_groups(
    data: np.ndarray,
    group_column: str,
    channel_names: list[str],
) -> list[CharacteristicGroup]:
    grouped_values: list[float] = []
    for value in data[:, 0]:
        if not np.isfinite(value):
            continue
        if not any(np.isclose(value, existing, rtol=1e-9, atol=1e-12) for existing in grouped_values):
            grouped_values.append(float(value))

    if not grouped_values:
        raise RuntimeError("Characteristic first column contains no valid group values.")

    groups: list[CharacteristicGroup] = []
    for group_value in grouped_values:
        mask = np.isclose(data[:, 0], group_value, rtol=1e-9, atol=1e-12)
        group_data = data[mask]
        if group_data.size == 0:
            continue

        x = np.arange(len(group_data), dtype=float)
        channels: dict[str, np.ndarray] = {}
        seen_names: dict[str, int] = {}

        for col_idx, name in enumerate(channel_names, start=1):
            seen_names[name] = seen_names.get(name, 0) + 1
            unique_name = name if seen_names[name] == 1 else f"{name}_{seen_names[name]}"
            y = np.asarray(group_data[:, col_idx], dtype=float)
            if len(y) == 0 or np.all(np.isnan(y)):
                continue
            channels[unique_name] = y

        if channels:
            value_text = f"{group_value:.12g}"
            groups.append(
                CharacteristicGroup(
                    name=f"{group_column}={value_text}",
                    value=group_value,
                    x=x.copy(),
                    channels=channels,
                    row_count=len(group_data),
                )
            )

    return groups


def split_characteristic_line(line: str) -> list[str]:
    if ";" in line or "\t" in line:
        delimiter = _sniff_delimiter(line, candidates=[";", "\t"])
        if delimiter:
            return [token.strip() for token in next(csv.reader([line], delimiter=delimiter)) if token.strip()]
    if "," in line and not _looks_like_decimal_comma_whitespace_row(line):
        return [token.strip() for token in next(csv.reader([line], delimiter=",")) if token.strip()]
    return re.findall(r"\S+", line.strip())


def parse_number(token: str) -> float:
    text = token.strip()
    if "," in text and "." in text:
        text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    return float(text)


def _sniff_delimiter(line: str, candidates: list[str]) -> str | None:
    counts = {delimiter: line.count(delimiter) for delimiter in candidates}
    delimiter, count = max(counts.items(), key=lambda item: item[1])
    return delimiter if count else None


def _looks_like_decimal_comma_whitespace_row(line: str) -> bool:
    whitespace_tokens = re.findall(r"\S+", line.strip())
    if len(whitespace_tokens) < 2:
        return False
    numeric_count = 0
    for token in whitespace_tokens:
        try:
            parse_number(token)
        except ValueError:
            return False
        numeric_count += 1
    return numeric_count >= 2


def _tokens_are_numeric(tokens: list[str]) -> bool:
    try:
        [parse_number(token) for token in tokens]
    except ValueError:
        return False
    return True


def _looks_like_header(text: str, tokens: list[str]) -> bool:
    return bool(tokens) and "=" not in text and ":" not in text and not _tokens_are_numeric(tokens)


def _clean_channel_name(name: str, idx: int) -> str:
    return name.strip() or f"col_{idx}"


def _format_number(value: float) -> str:
    return f"{float(value):.12g}"
