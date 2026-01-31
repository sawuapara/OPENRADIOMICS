#!/usr/bin/env python3
"""
DICOM Study Indexer - Comprehensive Metadata Extraction
Indexes DICOM files with all available metadata into a SQLite database.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List

import pydicom
from tqdm import tqdm


DATA_DIR = Path("/Users/samirawuapara/Documents/Personal/Health/brainLession/Test Results/Imaging/DICOM/3rd_CD")
DB_PATH = Path(__file__).parent / "brain_inventory.db"


def create_database(db_path: Path) -> sqlite3.Connection:
    """Create SQLite database with comprehensive schema."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dicom_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL UNIQUE,

            -- Patient Info
            PatientID TEXT,
            PatientName TEXT,
            PatientBirthDate TEXT,
            PatientSex TEXT,
            PatientAge TEXT,
            PatientWeight REAL,

            -- Study Info
            StudyInstanceUID TEXT,
            StudyDescription TEXT,
            StudyDate TEXT,
            StudyTime TEXT,
            AccessionNumber TEXT,

            -- Series Info
            SeriesInstanceUID TEXT,
            SeriesDescription TEXT,
            SeriesDate TEXT,
            SeriesTime TEXT,
            SeriesNumber INTEGER,
            Modality TEXT,

            -- Instance/Slice Info
            SOPInstanceUID TEXT,
            InstanceNumber INTEGER,
            AcquisitionDate TEXT,
            AcquisitionTime TEXT,
            AcquisitionDateTime TEXT,
            AcquisitionNumber INTEGER,

            -- Spatial Position & Orientation
            ImagePositionPatient TEXT,      -- JSON [x, y, z]
            ImageOrientationPatient TEXT,   -- JSON [6 values]
            SliceLocation REAL,
            SliceThickness REAL,
            SpacingBetweenSlices REAL,

            -- Image Geometry
            Rows INTEGER,
            Columns INTEGER,
            PixelSpacing TEXT,              -- JSON [row, col]
            ImageType TEXT,                 -- JSON array

            -- MRI Parameters
            MagneticFieldStrength REAL,
            RepetitionTime REAL,            -- TR (ms)
            EchoTime REAL,                  -- TE (ms)
            InversionTime REAL,             -- TI (ms)
            FlipAngle REAL,
            EchoTrainLength INTEGER,
            NumberOfAverages REAL,
            ImagingFrequency REAL,

            -- MRI Sequence Info
            ScanningSequence TEXT,
            SequenceVariant TEXT,
            SequenceName TEXT,
            MRAcquisitionType TEXT,         -- 2D or 3D

            -- Contrast
            ContrastBolusAgent TEXT,

            -- Equipment
            Manufacturer TEXT,
            ManufacturerModelName TEXT,
            StationName TEXT,
            InstitutionName TEXT,
            SoftwareVersions TEXT,

            -- Display Settings
            WindowCenter REAL,
            WindowWidth REAL,

            -- Pixel Data Info
            BitsAllocated INTEGER,
            BitsStored INTEGER,
            HighBit INTEGER,
            PixelRepresentation INTEGER,
            RescaleIntercept REAL,
            RescaleSlope REAL,

            -- Timestamps
            InstanceCreationDate TEXT,
            InstanceCreationTime TEXT,
            ContentDate TEXT,
            ContentTime TEXT
        )
    """)

    # Create indexes for common queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_study ON dicom_files(StudyInstanceUID)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_series ON dicom_files(SeriesInstanceUID)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_series_desc ON dicom_files(SeriesDescription)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_study_date ON dicom_files(StudyDate)")

    conn.commit()
    return conn


def get_dicom_files(data_dir: Path) -> List[Path]:
    """Find all DICOM files in the data directory."""
    files = []
    for path in data_dir.rglob("*"):
        if path.is_file() and not path.name.startswith("."):
            files.append(path)
    return sorted(files)


def safe_get(dcm, attr, default=None):
    """Safely get a DICOM attribute value."""
    if hasattr(dcm, attr):
        val = getattr(dcm, attr)
        if val is not None:
            return val
    return default


def to_json(val):
    """Convert DICOM sequence/list to JSON string."""
    if val is None:
        return None
    try:
        if hasattr(val, '__iter__') and not isinstance(val, str):
            return json.dumps([float(x) if isinstance(x, (int, float)) else str(x) for x in val])
        return json.dumps(val)
    except (TypeError, ValueError):
        return str(val)


def extract_metadata(dcm: pydicom.Dataset) -> dict:
    """Extract comprehensive metadata from DICOM dataset."""

    def get_str(attr):
        val = safe_get(dcm, attr)
        return str(val) if val is not None else None

    def get_float(attr):
        val = safe_get(dcm, attr)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                return None
        return None

    def get_int(attr):
        val = safe_get(dcm, attr)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                return None
        return None

    def get_json(attr):
        val = safe_get(dcm, attr)
        return to_json(val) if val is not None else None

    return {
        # Patient Info
        "PatientID": get_str("PatientID"),
        "PatientName": get_str("PatientName"),
        "PatientBirthDate": get_str("PatientBirthDate"),
        "PatientSex": get_str("PatientSex"),
        "PatientAge": get_str("PatientAge"),
        "PatientWeight": get_float("PatientWeight"),

        # Study Info
        "StudyInstanceUID": get_str("StudyInstanceUID"),
        "StudyDescription": get_str("StudyDescription"),
        "StudyDate": get_str("StudyDate"),
        "StudyTime": get_str("StudyTime"),
        "AccessionNumber": get_str("AccessionNumber"),

        # Series Info
        "SeriesInstanceUID": get_str("SeriesInstanceUID"),
        "SeriesDescription": get_str("SeriesDescription"),
        "SeriesDate": get_str("SeriesDate"),
        "SeriesTime": get_str("SeriesTime"),
        "SeriesNumber": get_int("SeriesNumber"),
        "Modality": get_str("Modality"),

        # Instance/Slice Info
        "SOPInstanceUID": get_str("SOPInstanceUID"),
        "InstanceNumber": get_int("InstanceNumber"),
        "AcquisitionDate": get_str("AcquisitionDate"),
        "AcquisitionTime": get_str("AcquisitionTime"),
        "AcquisitionDateTime": get_str("AcquisitionDateTime"),
        "AcquisitionNumber": get_int("AcquisitionNumber"),

        # Spatial Position & Orientation
        "ImagePositionPatient": get_json("ImagePositionPatient"),
        "ImageOrientationPatient": get_json("ImageOrientationPatient"),
        "SliceLocation": get_float("SliceLocation"),
        "SliceThickness": get_float("SliceThickness"),
        "SpacingBetweenSlices": get_float("SpacingBetweenSlices"),

        # Image Geometry
        "Rows": get_int("Rows"),
        "Columns": get_int("Columns"),
        "PixelSpacing": get_json("PixelSpacing"),
        "ImageType": get_json("ImageType"),

        # MRI Parameters
        "MagneticFieldStrength": get_float("MagneticFieldStrength"),
        "RepetitionTime": get_float("RepetitionTime"),
        "EchoTime": get_float("EchoTime"),
        "InversionTime": get_float("InversionTime"),
        "FlipAngle": get_float("FlipAngle"),
        "EchoTrainLength": get_int("EchoTrainLength"),
        "NumberOfAverages": get_float("NumberOfAverages"),
        "ImagingFrequency": get_float("ImagingFrequency"),

        # MRI Sequence Info
        "ScanningSequence": get_str("ScanningSequence"),
        "SequenceVariant": get_json("SequenceVariant"),
        "SequenceName": get_str("SequenceName"),
        "MRAcquisitionType": get_str("MRAcquisitionType"),

        # Contrast
        "ContrastBolusAgent": get_str("ContrastBolusAgent"),

        # Equipment
        "Manufacturer": get_str("Manufacturer"),
        "ManufacturerModelName": get_str("ManufacturerModelName"),
        "StationName": get_str("StationName"),
        "InstitutionName": get_str("InstitutionName"),
        "SoftwareVersions": get_str("SoftwareVersions"),

        # Display Settings
        "WindowCenter": get_float("WindowCenter"),
        "WindowWidth": get_float("WindowWidth"),

        # Pixel Data Info
        "BitsAllocated": get_int("BitsAllocated"),
        "BitsStored": get_int("BitsStored"),
        "HighBit": get_int("HighBit"),
        "PixelRepresentation": get_int("PixelRepresentation"),
        "RescaleIntercept": get_float("RescaleIntercept"),
        "RescaleSlope": get_float("RescaleSlope"),

        # Timestamps
        "InstanceCreationDate": get_str("InstanceCreationDate"),
        "InstanceCreationTime": get_str("InstanceCreationTime"),
        "ContentDate": get_str("ContentDate"),
        "ContentTime": get_str("ContentTime"),
    }


def index_dicom_files(data_dir: Path, db_path: Path):
    """Index all DICOM files into the database."""
    print(f"Scanning for DICOM files in: {data_dir}")
    dicom_files = get_dicom_files(data_dir)
    print(f"Found {len(dicom_files)} files to process\n")

    if not dicom_files:
        print("No DICOM files found!")
        return

    conn = create_database(db_path)
    cursor = conn.cursor()

    indexed_count = 0
    error_count = 0
    series_counts = {}
    study_counts = {}

    # Get column names from metadata keys
    sample_metadata = extract_metadata(pydicom.Dataset())
    columns = ["file_path"] + list(sample_metadata.keys())
    placeholders = ", ".join(["?"] * len(columns))
    column_names = ", ".join(columns)

    for file_path in tqdm(dicom_files, desc="Indexing DICOM files", unit="file"):
        try:
            dcm = pydicom.dcmread(file_path, stop_before_pixels=True)
            metadata = extract_metadata(dcm)

            values = [str(file_path.absolute())] + list(metadata.values())

            cursor.execute(f"""
                INSERT OR REPLACE INTO dicom_files ({column_names})
                VALUES ({placeholders})
            """, values)

            series_desc = metadata["SeriesDescription"] or "Unknown"
            series_counts[series_desc] = series_counts.get(series_desc, 0) + 1

            study_desc = metadata["StudyDescription"] or "Unknown"
            study_counts[study_desc] = study_counts.get(study_desc, 0) + 1

            indexed_count += 1

        except Exception as e:
            error_count += 1
            tqdm.write(f"Error processing {file_path.name}: {e}")

    conn.commit()
    conn.close()

    # Print summary
    print("\n" + "=" * 70)
    print("INDEXING SUMMARY")
    print("=" * 70)
    print(f"Database: {db_path}")
    print(f"Total files processed: {indexed_count}")
    print(f"Errors: {error_count}")
    print(f"Unique studies: {len(study_counts)}")
    print(f"Unique sequences: {len(series_counts)}")
    print("\nStudies:")
    print("-" * 50)
    for study, count in sorted(study_counts.items()):
        print(f"  {study}: {count} slices")
    print("\nSequences:")
    print("-" * 50)
    for series, count in sorted(series_counts.items()):
        print(f"  {series}: {count} slices")
    print("=" * 70)


if __name__ == "__main__":
    index_dicom_files(DATA_DIR, DB_PATH)
