import csv
import html
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ─────────────────────────────────────────────────────────────
BASE_URL   = "https://api.unifilabs.com"
API_KEY    = os.getenv("UNIFI_API_KEY")
USERNAME   = os.getenv("UNIFI_USERNAME")

HEADERS = {
    "Content-Type":  "application/json",
    "Authorization": API_KEY,
}

# Extensions that map to .rvt, with the prefix to prepend to the filename
RVT_EXTENSIONS = {
    "systemtype": "systemtype_",
    "view":       "view_",
    "schedule":   "schedule_",
    "rvtsheet":   "sheet_",
}

# ── Log CSV columns ───────────────────────────────────────────────────────────
LOG_FIELDNAMES = [
    "Filename",
    "RepositoryFileId",
    "LatestRevisionId",
    "LibraryId",
    "LibraryName",
    "EarliestRevitYear",
    "DownloadStatus",
    "FinalPath",
]

# ── Helpers ───────────────────────────────────────────────────────────────────
def sanitize_path_part(name: str) -> str:
    """Decode HTML entities and replace characters invalid on Windows paths."""
    name = html.unescape(name)
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    return name.strip()

def resolve_filename(raw: str) -> str:
    """
    Decode HTML entities, apply prefix rules, and swap qualifying extensions to .rvt.

    Rules:
      - Extensions in RVT_EXTENSIONS → rename to .rvt and prepend their mapped prefix
        e.g.  'Wall.systemtype'  →  'systemtype_Wall.rvt'
        e.g.  'Sheet.rvtsheet'   →  'sheet_Sheet.rvt'
      - Files already ending in .rvt → prepend 'project_'
        e.g.  'Building.rvt'     →  'project_Building.rvt'
      - All other files → unchanged (after HTML decode + sanitize)
    """
    decoded = html.unescape(raw)
    if "." in decoded:
        base, ext = decoded.rsplit(".", 1)
        ext_lower = ext.lower()
        if ext_lower in RVT_EXTENSIONS:
            prefix  = RVT_EXTENSIONS[ext_lower]
            decoded = f"{prefix}{base}.rvt"
        elif ext_lower == "rvt":
            decoded = f"project_{base}.rvt"
    # Sanitize the result so it is safe as a Windows filename
    return sanitize_path_part(decoded)

def get_signed_url(revision_id: str, repository_file_id: str) -> str:
    """Call the Unifi /downloadfile endpoint and return the signedUrl."""
    payload = {
        "revisionId":       revision_id,
        "repositoryFileId": repository_file_id,
        "username":         USERNAME,
    }
    resp = requests.post(f"{BASE_URL}/downloadfile", headers=HEADERS, json=payload)
    resp.raise_for_status()
    data = resp.json()

    # API may return a plain list — unwrap the first element
    if isinstance(data, list):
        data = data[0] if data else {}

    signed_url = data.get("signedUrl") or data.get("SignedUrl") or data.get("signed_url")
    if not signed_url:
        raise ValueError(f"No signedUrl in response: {json.dumps(data)[:200]}")
    return signed_url

def download_to(signed_url: str, dest_path: Path) -> None:
    """Stream-download a file from a signed URL to dest_path."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(signed_url, stream=True) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)

# ── Core logic ────────────────────────────────────────────────────────────────
def load_input_csv(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def group_by_repository_file_id(rows: list[dict]) -> dict[str, list[dict]]:
    """
    Group input rows by RepositoryFileId.
    Each group = one file that may live in multiple libraries.
    We download once and copy to the remaining library folders.
    """
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["RepositoryFileId"], []).append(row)
    return groups

def run(csv_path: str) -> None:
    rows   = load_input_csv(csv_path)
    groups = group_by_repository_file_id(rows)

    downloads_dir = Path(csv_path).parent / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path  = Path(csv_path).parent / f"download_log_{timestamp}.csv"

    total_groups = len(groups)
    total_rows   = len(rows)
    print(f"\n{'═' * 65}")
    print(f"  Input rows      : {total_rows}")
    print(f"  Unique files    : {total_groups}  (duplicates will be copied)")
    print(f"  Downloads dir   : {downloads_dir}")
    print(f"  Log file        : {log_path}")
    print(f"{'═' * 65}\n")

    log_entries: list[dict] = []

    for idx, (repo_file_id, group_rows) in enumerate(groups.items(), start=1):
        primary     = group_rows[0]
        revision_id = primary["LatestRevisionId"]
        safe_name   = resolve_filename(primary["Filename"])

        print(f"[{idx}/{total_groups}] {safe_name}")
        print(f"  RepositoryFileId : {repo_file_id}")
        print(f"  RevisionId       : {revision_id}")
        print(f"  Libraries ({len(group_rows):>2})   : "
              + ", ".join(r["LibraryName"] for r in group_rows))

        # ── Step 1: Get signed URL ─────────────────────────────────────────
        try:
            print(f"  → Requesting signed URL ...", end=" ", flush=True)
            signed_url = get_signed_url(revision_id, repo_file_id)
            print("OK")
        except Exception as e:
            print(f"FAILED\n  ✗ {e}")
            for row in group_rows:
                log_entries.append({
                    "Filename":          safe_name,
                    "RepositoryFileId":  repo_file_id,
                    "LatestRevisionId":  revision_id,
                    "LibraryId":         row["LibraryId"],
                    "LibraryName":       row["LibraryName"],
                    "EarliestRevitYear": row.get("EarliestRevitYear", ""),
                    "DownloadStatus":    f"FAILED (signed URL): {e}",
                    "FinalPath":         "",
                })
            print()
            continue

        # ── Step 2: Download to the first library folder ───────────────────
        first_lib   = group_rows[0]["LibraryName"]
        first_dir   = downloads_dir / sanitize_path_part(first_lib)
        first_path  = first_dir / safe_name
        download_ok = False

        try:
            print(f"  → Downloading to: {first_path} ...", end=" ", flush=True)
            download_to(signed_url, first_path)
            size_kb = first_path.stat().st_size / 1024
            print(f"OK  ({size_kb:.1f} KB)")
            download_ok = True
        except Exception as e:
            print(f"FAILED\n  ✗ {e}")
            for row in group_rows:
                log_entries.append({
                    "Filename":          safe_name,
                    "RepositoryFileId":  repo_file_id,
                    "LatestRevisionId":  revision_id,
                    "LibraryId":         row["LibraryId"],
                    "LibraryName":       row["LibraryName"],
                    "EarliestRevitYear": row.get("EarliestRevitYear", ""),
                    "DownloadStatus":    f"FAILED (download): {e}",
                    "FinalPath":         "",
                })
            print()
            continue

        # ── Step 3: Copy to any additional library folders ─────────────────
        paths_by_library: dict[str, str] = {
            group_rows[0]["LibraryId"]: str(first_path)
        }

        for row in group_rows[1:]:
            dest_dir  = downloads_dir / sanitize_path_part(row["LibraryName"])
            dest_path = dest_dir / safe_name
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
                print(f"  → Copying to:     {dest_path} ...", end=" ", flush=True)
                shutil.copy2(first_path, dest_path)
                print("OK")
                paths_by_library[row["LibraryId"]] = str(dest_path)
            except Exception as e:
                print(f"FAILED\n  ✗ {e}")
                paths_by_library[row["LibraryId"]] = f"COPY FAILED: {e}"

        # ── Step 4: Write one log row per input CSV row ────────────────────
        for row in group_rows:
            lib_id     = row["LibraryId"]
            final_path = paths_by_library.get(lib_id, "")
            status     = "SUCCESS" if download_ok and not final_path.startswith("COPY FAILED") else "FAILED"
            log_entries.append({
                "Filename":          safe_name,
                "RepositoryFileId":  repo_file_id,
                "LatestRevisionId":  revision_id,
                "LibraryId":         lib_id,
                "LibraryName":       row["LibraryName"],
                "EarliestRevitYear": row.get("EarliestRevitYear", ""),
                "DownloadStatus":    status,
                "FinalPath":         final_path,
            })

        print()

    # ── Write log CSV ──────────────────────────────────────────────────────────
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDNAMES)
        writer.writeheader()
        writer.writerows(log_entries)

    successes = sum(1 for e in log_entries if e["DownloadStatus"] == "SUCCESS")
    failures  = sum(1 for e in log_entries if e["DownloadStatus"] != "SUCCESS")

    print(f"{'═' * 65}")
    print(f"  ✓ Finished processing {total_groups} unique files.")
    print(f"    Successful : {successes}")
    print(f"    Failed     : {failures}")
    print(f"    Log saved  : {log_path}")
    print(f"{'═' * 65}\n")

# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python download_files.py <path_to_input.csv>")
        sys.exit(1)
    run(sys.argv[1])
