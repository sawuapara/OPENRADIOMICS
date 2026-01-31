#!/usr/bin/env python3
"""
Upload DICOM files to S3 and update database with S3 keys.

Usage:
    python upload_dicom_to_s3.py --bucket <bucket-name> --db <database-path>

Example:
    python upload_dicom_to_s3.py --bucket openradiomics-dev-dicom-445305334312 --db ../../brain_inventory.db
"""

import argparse
import hashlib
import os
import sqlite3
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from botocore.exceptions import ClientError


def get_s3_key(file_path: str, patient_id: str, study_uid: str, series_uid: str, sop_uid: str) -> str:
    """
    Generate S3 key following DICOM hierarchy.
    Format: patients/{patient_id}/studies/{study_uid}/series/{series_uid}/{sop_uid}.dcm
    """
    # Sanitize UIDs (remove any problematic characters)
    def sanitize(s):
        return s.replace("/", "_").replace("\\", "_") if s else "unknown"

    return f"patients/{sanitize(patient_id)}/studies/{sanitize(study_uid)}/series/{sanitize(series_uid)}/{sanitize(sop_uid)}.dcm"


def upload_file(s3_client, bucket: str, local_path: str, s3_key: str) -> tuple[bool, str]:
    """Upload a single file to S3. Returns (success, error_message)."""
    try:
        s3_client.upload_file(
            local_path,
            bucket,
            s3_key,
            ExtraArgs={
                "ContentType": "application/dicom",
                "ServerSideEncryption": "AES256"
            }
        )
        return True, ""
    except ClientError as e:
        return False, str(e)
    except FileNotFoundError:
        return False, f"File not found: {local_path}"


def main():
    parser = argparse.ArgumentParser(description="Upload DICOM files to S3")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--db", required=True, help="Path to SQLite database")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--workers", type=int, default=10, help="Number of parallel upload workers")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be uploaded without uploading")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"Error: Database not found: {db_path}")
        sys.exit(1)

    # Connect to database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Check if s3_key column exists, add if not
    cursor.execute("PRAGMA table_info(dicom_files)")
    columns = [row["name"] for row in cursor.fetchall()]

    if "s3_key" not in columns:
        print("Adding s3_key column to database...")
        cursor.execute("ALTER TABLE dicom_files ADD COLUMN s3_key TEXT")
        conn.commit()

    # Get all files that need uploading (where s3_key is NULL)
    cursor.execute("""
        SELECT id, file_path, PatientID, StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID
        FROM dicom_files
        WHERE s3_key IS NULL OR s3_key = ''
    """)
    rows = cursor.fetchall()

    if not rows:
        print("All files already have S3 keys. Nothing to upload.")
        conn.close()
        return

    print(f"Found {len(rows)} files to upload to s3://{args.bucket}")

    if args.dry_run:
        print("\n[DRY RUN] Would upload:")
        for row in rows[:10]:
            s3_key = get_s3_key(
                row["file_path"],
                row["PatientID"],
                row["StudyInstanceUID"],
                row["SeriesInstanceUID"],
                row["SOPInstanceUID"]
            )
            print(f"  {row['file_path']} -> s3://{args.bucket}/{s3_key}")
        if len(rows) > 10:
            print(f"  ... and {len(rows) - 10} more files")
        conn.close()
        return

    # Initialize S3 client
    s3_client = boto3.client("s3", region_name=args.region)

    # Verify bucket exists
    try:
        s3_client.head_bucket(Bucket=args.bucket)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "404":
            print(f"Error: Bucket '{args.bucket}' does not exist")
        elif error_code == "403":
            print(f"Error: Access denied to bucket '{args.bucket}'")
        else:
            print(f"Error: {e}")
        sys.exit(1)

    # Prepare upload tasks
    tasks = []
    for row in rows:
        s3_key = get_s3_key(
            row["file_path"],
            row["PatientID"],
            row["StudyInstanceUID"],
            row["SeriesInstanceUID"],
            row["SOPInstanceUID"]
        )
        tasks.append({
            "id": row["id"],
            "local_path": row["file_path"],
            "s3_key": s3_key
        })

    # Upload in parallel
    uploaded = 0
    failed = 0

    print(f"Uploading with {args.workers} workers...")

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(upload_file, s3_client, args.bucket, task["local_path"], task["s3_key"]): task
            for task in tasks
        }

        for i, future in enumerate(as_completed(futures)):
            task = futures[future]
            success, error = future.result()

            if success:
                # Update database with S3 key
                cursor.execute("UPDATE dicom_files SET s3_key = ? WHERE id = ?", (task["s3_key"], task["id"]))
                uploaded += 1
            else:
                print(f"  Failed: {task['local_path']} - {error}")
                failed += 1

            # Progress update every 100 files
            if (i + 1) % 100 == 0 or (i + 1) == len(tasks):
                print(f"  Progress: {i + 1}/{len(tasks)} ({uploaded} uploaded, {failed} failed)")
                conn.commit()  # Commit in batches

    # Final commit
    conn.commit()
    conn.close()

    print(f"\nComplete: {uploaded} uploaded, {failed} failed")

    if failed > 0:
        print(f"\nWarning: {failed} files failed to upload. Re-run the script to retry.")


if __name__ == "__main__":
    main()
