# Unifi Downloader

A set of Python scripts for exporting and bulk-downloading content from a [Unifi](https://www.unifilabs.com/) library using the Unifi API.

## Scripts

| Script | Purpose |
|---|---|
| `get_report.py` | Queries all files and exports a CSV report |
| `download_files.py` | Reads the CSV report and bulk-downloads all files |

## Requirements

- Python 3.10+
- A Unifi API key with **Content Download** permission

Install dependencies:

```bash
pip install requests python-dotenv
```

## Setup

Create a `.env` file in the project root:

```env
UNIFI_API_KEY=your_api_key_here
UNIFI_USERNAME=your_email@example.com
```

> Never commit your `.env` file. It is already excluded by `.gitignore`.

## Usage

### 1. Generate a file report

```bash
python get_report.py
```

Paginates through the Unifi `/search` endpoint and writes a timestamped CSV (e.g. `unifi_report_20240101_120000.csv`) to the project folder.

**CSV columns:**

| Column | Description |
|---|---|
| `Filename` | Original filename from Unifi |
| `FileType` | Numeric file type enum |
| `FileTypeLabel` | Human-readable file type |
| `RepositoryFileId` | Unique file ID |
| `Created` | Creation date of the active revision |
| `LatestRevisionId` | File revision ID of the most recent revision |
| `EarliestBaseFileVersionId` | File version ID for the earliest supported Revit year |
| `EarliestRevitYear` | Earliest Revit version this file supports |
| `LibraryId` | ID of the library the file belongs to |
| `LibraryName` | Name of the library the file belongs to |

> Files that belong to multiple libraries produce one row per library.

---

### 2. Download files

```bash
python download_files.py unifi_report_20240101_120000.csv
```

Downloads each file into a `downloads/` subfolder organized by library name. Files that appear in multiple libraries are downloaded once and copied.

A timestamped log CSV (e.g. `download_log_20240101_120000.csv`) is written alongside the input CSV, recording the status and final path of every file.

**Log columns:** `Filename`, `RepositoryFileId`, `LatestRevisionId`, `LibraryId`, `LibraryName`, `EarliestRevitYear`, `DownloadStatus`, `FinalPath`

## File Renaming Rules

Unifi stores some Revit content under non-standard extensions. This tool normalizes them on download:

| Original Extension | Renamed To | Prefix Applied |
|---|---|---|
| `.systemtype` | `.rvt` | `systemtype_` |
| `.view` | `.rvt` | `view_` |
| `.schedule` | `.rvt` | `schedule_` |
| `.rvtsheet` | `.rvt` | `sheet_` |
| `.rvt` | `.rvt` | `project_` |
| All others | unchanged | none |

## File Type Reference

| Enum | Description | Extension |
|---|---|---|
| 1 | Revit Loadable Family | `.rfa` |
| 4 | PDF | `.pdf` |
| 8 | Revit Project | `.rvt` |
| 9 | Non-loadable System Families / Model Groups | `.systemtype` |
| 10 | Drafting View | `.view` |
| 11 | Revit Schedule View | `.schedule` |
| 14 | Revit Project Template | `.rte` |
| 23 | Text File | `.txt` |
| 28 | Dynamo Script | `.dyn` |
| 32 | Excel Spreadsheet | `.xlsx` |
| 45 | Image | `.jpg` |
| 48 | Image | `.png` |
| 63 | Autodesk Material Library | `.adsklib` |
| 85 | Video | `.mp4` |
| 88 | Revit Material | `.rfamat` |
| 91 | Revit Sheet | `.rvtsheet` |
| 96 | IES Lighting Definition | `.ies` |

## Known Limitations

- **Revit Materials (`.rfamat`)** — converting to `.rvt` does not produce a valid file. These are downloaded as-is.
- The Unifi `/search` API returns a maximum of 100 results per request; `get_report.py` paginates automatically using `offset`.
