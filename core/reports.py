from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from core.scanner import ScanResult


def export_csv(result: ScanResult, destination: str | Path, removed: set[Path] | None = None) -> Path:
    target = Path(destination)
    removed = removed or set()
    with target.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["Scan date", "Selected folder", "Files scanned", "Duplicate groups",
             "Extra copies", "Potential savings (bytes)", "Group", "Name", "Size (bytes)",
             "Full path", "Status"]
        )
        scan_date = datetime.now().astimezone().isoformat(timespec="seconds")
        for group_number, group in enumerate(result.duplicate_groups, start=1):
            for record in group:
                writer.writerow([
                    scan_date, str(result.root), result.files_scanned,
                    len(result.duplicate_groups), result.extra_copies, result.savings_bytes,
                    group_number, record.name, record.size, str(record.path),
                    "Moved to Recycle Bin" if record.path in removed else "Found",
                ])
    return target


def export_txt(result: ScanResult, destination: str | Path, removed: set[Path] | None = None) -> Path:
    target = Path(destination)
    removed = removed or set()
    lines = [
        "SMART DUPLICATE FILE FINDER — SCAN REPORT",
        f"Scan date: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Selected folder: {result.root}",
        f"Files scanned: {result.files_scanned}",
        f"Duplicate groups: {len(result.duplicate_groups)}",
        f"Extra copies: {result.extra_copies}",
        f"Potential savings: {format_bytes(result.savings_bytes)}",
        "",
    ]
    for index, group in enumerate(result.duplicate_groups, start=1):
        lines.append(f"Group {index} — {format_bytes(group[0].size)} per copy")
        lines.append(f"  Retained copy: {group[0].path}")
        for record in group[1:]:
            status = " [moved to Recycle Bin]" if record.path in removed else ""
            lines.append(f"  Duplicate: {record.path}{status}")
        lines.append("")
    if result.errors:
        lines.extend(["Scan warnings:", *[f"  {error}" for error in result.errors]])
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def format_bytes(size: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"
