import csv
import re
from datetime import datetime, timezone
import os
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ─────────────────────────────────────────────────────────────
BASE_URL    = "https://api.unifilabs.com"
API_KEY = os.getenv("UNIFI_API_KEY")
ENDPOINT    = "/search"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type":  "application/json",
    "Accept":        "application/json",
}

# ── Helpers ───────────────────────────────────────────────────────────────────
FILE_TYPE_MAP = {
    0:  "Unknown",
    1:  "Family",
    2:  "Material",
    3:  "FillPattern",
    4:  "LinePattern",
    5:  "Object Style",
    6:  "System Family",
    7:  "Tag",
    8:  "Wall",
    9:  "Stacked Wall",
    10: "Curtain Wall",
}

def parse_unifi_date(date_str: str) -> str:
    """Convert Unifi /Date(timestamp+0000)/ format to a readable string."""
    if not date_str:
        return "N/A"
    match = re.search(r"/Date\((\d+)([+-]\d{4})?\)/", date_str)
    if not match:
        return date_str
    ms        = int(match.group(1))
    dt        = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")

def get_file_type_label(file_type: int) -> str:
    return FILE_TYPE_MAP.get(file_type, f"Type {file_type}")

# ── Fetch ─────────────────────────────────────────────────────────────────────
def fetch_files() -> list:
    """Fetch all files from the Unifi API using POST + offset pagination."""
    all_files = []
    page_size = 100
    offset    = 0

    page = 1
    while True:
        print(f"  → Fetching page {page} (offset {offset})...", end=" ", flush=True)
        body = {
            "size":   page_size,
            "offset": offset,
        }
        response = requests.post(BASE_URL + ENDPOINT, headers=HEADERS, json=body)
        response.raise_for_status()
        data = response.json()

        # Handle both plain list responses and wrapped { Items: [...] } responses
        if isinstance(data, list):
            items = data
        else:
            items = data.get("Items") or data.get("items") or []

        print(f"got {len(items)} items.")

        if not items:
            break

        all_files.extend(items)
        print(f"     Running total: {len(all_files)} files fetched.")

        # Stop if fewer results than page size (last page)
        if len(items) < page_size:
            break
        offset += page_size
        page   += 1

    print(f"\n  ✓ Done fetching. Total files retrieved: {len(all_files)}\n")
    return all_files

# ── CSV Export ────────────────────────────────────────────────────────────────
def export_csv(files: list) -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path   = os.path.join(script_dir, f"unifi_report_{timestamp}.csv")

    # Each library gets its own row so IDs and Names are unambiguous
    fieldnames = [
        "Filename",
        "FileType",
        "FileTypeLabel",
        "RepositoryFileId",
        "Created",
        "LatestRevisionId",
        "EarliestBaseFileVersionId",
        "EarliestRevitYear",
        "LibraryId",
        "LibraryName",
    ]

    print(f"Writing CSV to: {out_path}")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for i, file in enumerate(files, start=1):
            filename           = file.get("Filename", "N/A")
            file_type_raw      = file.get("FileType", "N/A")
            file_type_label    = get_file_type_label(file_type_raw)
            repository_file_id = file.get("RepositoryFileId", "N/A")

            active_revision    = file.get("ActiveRevision") or {}
            created            = parse_unifi_date(active_revision.get("Created", ""))

            revisions          = file.get("Revisions") or []
            latest_revision    = max(revisions, key=lambda r: r.get("RevisionNumber", 0), default=None)
            latest_revision_id = latest_revision.get("FileRevisionId", "") if latest_revision else ""

            base_versions      = (latest_revision or {}).get("BaseFileVersions") or []
            earliest_base      = min(base_versions, key=lambda v: v.get("RevitYear", 9999), default=None)
            earliest_version_id = earliest_base.get("FileVersionId", "") if earliest_base else ""
            earliest_revit_year = earliest_base.get("RevitYear", "") if earliest_base else ""

            libraries = file.get("Libraries") or []

            if libraries:
                for lib in libraries:
                    writer.writerow({
                        "Filename":                 filename,
                        "FileType":                 file_type_raw,
                        "FileTypeLabel":            file_type_label,
                        "RepositoryFileId":         repository_file_id,
                        "Created":                  created,
                        "LatestRevisionId":         latest_revision_id,
                        "EarliestBaseFileVersionId": earliest_version_id,
                        "EarliestRevitYear":        earliest_revit_year,
                        "LibraryId":                lib.get("LibraryId", "N/A"),
                        "LibraryName":              lib.get("Name", "N/A"),
                    })
            else:
                writer.writerow({
                    "Filename":                 filename,
                    "FileType":                 file_type_raw,
                    "FileTypeLabel":            file_type_label,
                    "RepositoryFileId":         repository_file_id,
                    "Created":                  created,
                    "LatestRevisionId":         latest_revision_id,
                    "EarliestBaseFileVersionId": earliest_version_id,
                    "EarliestRevitYear":        earliest_revit_year,
                    "LibraryId":                "",
                    "LibraryName":              "",
                })

            if i % 100 == 0:
                print(f"  → Written {i}/{len(files)} rows...")

    print(f"  ✓ CSV complete: {out_path}")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Fetching files from Unifi API...")
    files = fetch_files()
    print(f"Writing {len(files)} files to CSV...")
    export_csv(files)

if __name__ == "__main__":
    main()
