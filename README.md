# OPENRADIOMICS

Open-source brain MRI analysis and visualization toolkit.

## Features

- **DICOM Indexer** - Catalog DICOM files with 54+ metadata fields into SQLite
- **3D Voxel Viewer** - Interactive Three.js visualization with threshold control
- **Multi-Planar Views** - Axial, Sagittal, and Coronal slice navigation
- **Data Probe** - Click any point to see full metadata (coordinates, MRI parameters, timestamps)
- **Study/Sequence Selection** - Hierarchical dropdown UI

## Screenshot

```
┌─────────────────────────────────┬───────────────────────┐
│                                 │ AXIAL (Z)             │
│      3D Voxel View              │ [slice image]         │
│                                 │ Slice Z: [slider]     │
│  - Rotate: drag                 │ Data Probe: [metadata]│
│  - Zoom: scroll                 ├───────────────────────┤
│  - Pan: right-drag              │ SAGITTAL (X)          │
│                                 │ [slice image]         │
│  Study: [dropdown]              │ Slice X: [slider]     │
│  Sequence: [dropdown]           ├───────────────────────┤
│  Threshold: [slider]            │ CORONAL (Y)           │
│                                 │ [slice image]         │
└─────────────────────────────────┴───────────────────────┘
```

## Quick Start

### 1. Install Dependencies

```bash
pip install flask pydicom numpy scipy tqdm
```

### 2. Index Your DICOM Files

Edit `index_dicom.py` to point to your DICOM directory:

```python
DATA_DIR = Path("/path/to/your/dicom/files")
```

Then run:

```bash
python3 index_dicom.py
```

### 3. Start the Viewer

```bash
python3 viewer_app.py
# Open http://127.0.0.1:5000
```

## File Structure

```
OPENRADIOMICS/
├── README.md              # This file
├── index_dicom.py         # DICOM metadata indexer
├── viewer_app.py          # Flask web server
├── templates/
│   └── viewer.html        # Three.js 3D viewer + multi-planar views
└── .gitignore
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Main viewer page |
| `GET /api/studies` | List all studies |
| `GET /api/sequences/<study_id>` | List sequences for a study |
| `GET /api/volume/<study_id>/<series>` | Get 3D voxel data |
| `GET /api/volume-info/<study_id>/<series>` | Get volume dimensions |
| `GET /api/orthoslice/<study_id>/<series>/<plane>/<index>` | Get 2D slice (axial/sagittal/coronal) |
| `GET /api/voxel-metadata/<study_id>/<series>/<x>/<y>/<z>` | Get metadata for voxel |

## Database Schema

The indexer creates a SQLite database with comprehensive DICOM metadata:

**Patient**: PatientID, PatientName, PatientBirthDate, PatientSex, PatientAge, PatientWeight

**Study**: StudyInstanceUID, StudyDescription, StudyDate, StudyTime, AccessionNumber

**Series**: SeriesInstanceUID, SeriesDescription, SeriesNumber, Modality

**Instance**: SOPInstanceUID, InstanceNumber, AcquisitionDate/Time

**Spatial**: ImagePositionPatient, ImageOrientationPatient, SliceLocation, SliceThickness, PixelSpacing

**MRI Parameters**: MagneticFieldStrength, RepetitionTime (TR), EchoTime (TE), InversionTime (TI), FlipAngle, ScanningSequence, MRAcquisitionType

**Equipment**: Manufacturer, ManufacturerModelName, StationName, InstitutionName

**Display**: WindowCenter, WindowWidth, BitsAllocated, BitsStored

## Usage Examples

### Query the Database

```bash
# List all studies
sqlite3 brain_inventory.db "SELECT DISTINCT StudyDate, StudyDescription FROM dicom_files;"

# Get MRI parameters for a sequence
sqlite3 brain_inventory.db "SELECT DISTINCT RepetitionTime, EchoTime, FlipAngle FROM dicom_files WHERE SeriesDescription = 'YOUR_SEQUENCE';"
```

## Roadmap

- [ ] Radiomics feature extraction (PyRadiomics integration)
- [ ] ROI annotation tools
- [ ] Export to NIfTI format
- [ ] Machine learning integration

## License

MIT License

## Contributing

Contributions welcome! Please open an issue or PR.
