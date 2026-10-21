"""
verify_committed.py - Verify integrity of raw files stored in git HEAD against manifest.csv.

Checks that every raw file listed in manifest.csv:
1. Exists in git HEAD.
2. Has matching SHA-256 digest either directly or matching original Windows CRLF content
   (for early files committed prior to .gitattributes -text normalization).
"""
import sys
import hashlib
import subprocess
from pathlib import Path
import pandas as pd


def main():
    manifest_path = Path("manifest.csv")
    if not manifest_path.exists():
        print("ERROR: manifest.csv not found")
        sys.exit(1)

    df = pd.read_csv(manifest_path)
    raw_df = df[df["layer"] == "raw"]
    total = len(raw_df)
    print(f"Checking {total} raw files in git HEAD against manifest.csv...")

    missing = []
    direct_matches = 0
    crlf_matches = 0
    mismatches = []

    for _, row in raw_df.iterrows():
        fpath = str(row["file_path"]).replace("\\", "/")
        expected_sha = row["sha256"]

        proc = subprocess.run(["git", "show", f"HEAD:{fpath}"], capture_output=True)
        if proc.returncode != 0:
            missing.append(fpath)
            continue

        git_blob = proc.stdout
        direct_sha = hashlib.sha256(git_blob).hexdigest()

        if direct_sha == expected_sha:
            direct_matches += 1
        else:
            # Check if difference is purely git CRLF->LF commit normalization
            crlf_sha = hashlib.sha256(git_blob.replace(b"\n", b"\r\n")).hexdigest()
            if crlf_sha == expected_sha:
                crlf_matches += 1
            else:
                mismatches.append({
                    "file_path": fpath,
                    "expected": expected_sha,
                    "git_blob_sha": direct_sha,
                    "crlf_sha": crlf_sha
                })

    print(f"Direct git HEAD blob SHA-256 matches: {direct_matches}/{total}")
    print(f"Git HEAD matches with original CRLF encoding: {crlf_matches}/{total}")
    print(f"Missing in git HEAD: {len(missing)}")
    print(f"Genuine content mismatches/corruptions: {len(mismatches)}")

    if missing:
        print("ERROR: Missing files in git HEAD:")
        for m in missing[:10]:
            print(f"  {m}")
        sys.exit(1)

    if mismatches:
        print("ERROR: SHA-256 mismatch detected in git HEAD files:")
        for m in mismatches[:10]:
            print(f"  {m['file_path']}: expected {m['expected']}, got {m['git_blob_sha']}")
        sys.exit(1)

    print("SUCCESS: All raw files in git HEAD verified against manifest.csv digests!")
    sys.exit(0)


if __name__ == "__main__":
    main()
