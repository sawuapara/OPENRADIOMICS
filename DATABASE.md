# OpenRadiomics Database Schema

## Overview

OpenRadiomics uses SQLite (`brain_inventory.db`) to store DICOM metadata indexed from medical imaging files. The database enables fast querying of studies, series, and individual slices without reading the raw DICOM files.

---

## Current Tables

### `dicom_files`

The main table storing metadata for each DICOM file (slice).

| Column | Type | Description |
|--------|------|-------------|
| **id** | INTEGER | Primary key, auto-increment |
| **file_path** | TEXT | Absolute path to DICOM file (UNIQUE) |

#### Patient Information
| Column | Type | Description |
|--------|------|-------------|
| PatientID | TEXT | Patient identifier |
| PatientName | TEXT | Patient name |
| PatientBirthDate | TEXT | Birth date (YYYYMMDD) |
| PatientSex | TEXT | M/F/O |
| PatientAge | TEXT | Age at time of study |
| PatientWeight | REAL | Weight in kg |

#### Study Information
| Column | Type | Description |
|--------|------|-------------|
| StudyInstanceUID | TEXT | Unique study identifier |
| StudyDescription | TEXT | Description of the study (e.g., "MRI BRAIN W WO CONTRAST") |
| StudyDate | TEXT | Date of study (YYYYMMDD) |
| StudyTime | TEXT | Time of study (HHMMSS) |
| AccessionNumber | TEXT | Hospital accession number |

#### Series Information
| Column | Type | Description |
|--------|------|-------------|
| SeriesInstanceUID | TEXT | Unique series identifier |
| SeriesDescription | TEXT | Description of the series/sequence (e.g., "AX T2", "C+AX T1 STEALTH") |
| SeriesDate | TEXT | Date of series |
| SeriesTime | TEXT | Time of series |
| SeriesNumber | INTEGER | Series number within study |
| Modality | TEXT | Imaging modality (MR, CT, etc.) |

#### Instance/Slice Information
| Column | Type | Description |
|--------|------|-------------|
| SOPInstanceUID | TEXT | Unique instance identifier |
| InstanceNumber | INTEGER | Slice number within series |
| AcquisitionDate | TEXT | Date of acquisition |
| AcquisitionTime | TEXT | Time of acquisition |
| AcquisitionDateTime | TEXT | Combined date/time |
| AcquisitionNumber | INTEGER | Acquisition number |

#### Spatial Position & Orientation
| Column | Type | Description |
|--------|------|-------------|
| ImagePositionPatient | TEXT | JSON [x, y, z] - 3D position of first voxel |
| ImageOrientationPatient | TEXT | JSON [6 values] - Row/column direction cosines |
| SliceLocation | REAL | Relative position along scan axis (mm) |
| SliceThickness | REAL | Thickness of slice (mm) |
| SpacingBetweenSlices | REAL | Gap between slices (mm) |

#### Image Geometry
| Column | Type | Description |
|--------|------|-------------|
| Rows | INTEGER | Image height in pixels |
| Columns | INTEGER | Image width in pixels |
| PixelSpacing | TEXT | JSON [row, col] - Pixel size in mm |
| ImageType | TEXT | JSON array of image type values |

#### MRI Parameters
| Column | Type | Description |
|--------|------|-------------|
| MagneticFieldStrength | REAL | Field strength in Tesla |
| RepetitionTime | REAL | TR in milliseconds |
| EchoTime | REAL | TE in milliseconds |
| InversionTime | REAL | TI in milliseconds |
| FlipAngle | REAL | Flip angle in degrees |
| EchoTrainLength | INTEGER | Number of echoes |
| NumberOfAverages | REAL | NEX/NSA |
| ImagingFrequency | REAL | Larmor frequency in MHz |

#### MRI Sequence Info
| Column | Type | Description |
|--------|------|-------------|
| ScanningSequence | TEXT | Sequence type (SE, GR, IR, etc.) |
| SequenceVariant | TEXT | Sequence variant |
| SequenceName | TEXT | Manufacturer sequence name |
| MRAcquisitionType | TEXT | 2D or 3D acquisition |

#### Contrast
| Column | Type | Description |
|--------|------|-------------|
| ContrastBolusAgent | TEXT | Contrast agent used |

#### Equipment
| Column | Type | Description |
|--------|------|-------------|
| Manufacturer | TEXT | Scanner manufacturer |
| ManufacturerModelName | TEXT | Scanner model |
| StationName | TEXT | Scanner station name |
| InstitutionName | TEXT | Hospital/facility name |
| SoftwareVersions | TEXT | Software version |

#### Display Settings
| Column | Type | Description |
|--------|------|-------------|
| WindowCenter | REAL | Default window center |
| WindowWidth | REAL | Default window width |

#### Pixel Data Info
| Column | Type | Description |
|--------|------|-------------|
| BitsAllocated | INTEGER | Bits per pixel allocated |
| BitsStored | INTEGER | Bits per pixel actually used |
| HighBit | INTEGER | Most significant bit position |
| PixelRepresentation | INTEGER | 0=unsigned, 1=signed |
| RescaleIntercept | REAL | Value to add to pixel |
| RescaleSlope | REAL | Value to multiply pixel |

#### Timestamps
| Column | Type | Description |
|--------|------|-------------|
| InstanceCreationDate | TEXT | Date instance was created |
| InstanceCreationTime | TEXT | Time instance was created |
| ContentDate | TEXT | Date of content |
| ContentTime | TEXT | Time of content |

---

## Indexes

| Index Name | Column(s) | Purpose |
|------------|-----------|---------|
| idx_study | StudyInstanceUID | Fast study lookups |
| idx_series | SeriesInstanceUID | Fast series lookups |
| idx_series_desc | SeriesDescription | Query by sequence name |
| idx_study_date | StudyDate | Sort/filter by date |

---

## Planned Tables

### `favorites` (TODO)
Store user-favorited studies and sequences.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| type | TEXT | 'study' or 'sequence' |
| study_uid | TEXT | StudyInstanceUID |
| series_desc | TEXT | SeriesDescription (for sequence favorites) |
| created_at | TEXT | Timestamp when favorited |
| notes | TEXT | Optional user notes |

### `annotations` (TODO)
Store user annotations/markings on images.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| study_uid | TEXT | StudyInstanceUID |
| series_desc | TEXT | SeriesDescription |
| slice_index | INTEGER | Slice number |
| x | INTEGER | X coordinate |
| y | INTEGER | Y coordinate |
| z | INTEGER | Z coordinate |
| label | TEXT | Annotation label |
| notes | TEXT | User notes |
| created_at | TEXT | Timestamp |

### `measurements` (TODO)
Store measurement data (distances, areas, volumes).

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| study_uid | TEXT | StudyInstanceUID |
| series_desc | TEXT | SeriesDescription |
| type | TEXT | 'distance', 'area', 'volume' |
| points | TEXT | JSON array of coordinates |
| value | REAL | Calculated measurement |
| unit | TEXT | mm, mm², mm³ |
| created_at | TEXT | Timestamp |

---

## Usage Examples

### List all studies
```sql
SELECT DISTINCT StudyInstanceUID, StudyDescription, StudyDate,
       COUNT(*) as total_slices
FROM dicom_files
GROUP BY StudyInstanceUID
ORDER BY StudyDate DESC;
```

### List sequences in a study
```sql
SELECT SeriesDescription, COUNT(*) as slice_count
FROM dicom_files
WHERE StudyInstanceUID = ?
GROUP BY SeriesDescription
ORDER BY slice_count DESC;
```

### Get slices for a series (ordered)
```sql
SELECT file_path, InstanceNumber, SliceLocation
FROM dicom_files
WHERE StudyInstanceUID = ? AND SeriesDescription = ?
ORDER BY InstanceNumber;
```

### Get MRI parameters for a sequence
```sql
SELECT DISTINCT RepetitionTime, EchoTime, FlipAngle,
       MagneticFieldStrength, PixelSpacing, SliceThickness
FROM dicom_files
WHERE StudyInstanceUID = ? AND SeriesDescription = ?
LIMIT 1;
```
