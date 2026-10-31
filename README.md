# Smart Duplicate File Finder

A Windows-friendly Python desktop application for finding identical files, reviewing storage insights, and moving selected extra copies to the Recycle Bin.

## Requirements

- Python 3.10 or newer
- Windows, macOS, or Linux desktop session with Tk support

## Install and launch (Windows PowerShell)

From the project directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

If PowerShell blocks virtual-environment activation, run commands without activation:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## Features

- Six pages: Dashboard, Smart Folder Scanner, Duplicate Detection, Storage Analyzer, Safe Duplicate Removal, and Scan Report.
- SHA-256 content matching, with streaming reads and a background scan thread.
- Optional recursive scanning; symbolic links are skipped.
- Search, extension filtering, sorting, individual selection, and select-extra-copies convenience.
- Storage figures distinguish all data in duplicate groups from reclaimable extra-copy data.
- Light/dark theme toggle persisted in `data/settings.json`.
- CSV and TXT exports include the scan summary and duplicate paths.

## Safety

- Scans do not modify files.
- Files are never permanently deleted by the app. Removal uses `send2trash` to move selected files to the system Recycle Bin/Trash.
- The first sorted file in each content-identical group is retained. Only other copies are eligible for removal.
- Immediately before each move, the application checks that the file still exists, is not a symbolic link, retains its size and SHA-256 digest, and still has a matching retained copy.
- Removal always requires confirmation. Cancel the confirmation dialog to leave files untouched.
- Files inaccessible during scanning are skipped and reported as warnings.

## Notes

The application hashes only files whose sizes match another file in the selected scan, avoiding unnecessary reads of unique-size files. A scan result represents a snapshot; rerun the scan after changing files. Report exports may contain private file paths, so store and share them carefully.
