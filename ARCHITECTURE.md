# OpenRadiomics Application Architecture

## Overview

OpenRadiomics is a cloud-native medical imaging viewer for DICOM files (MRI, CT, etc.) with multi-patient support, user authentication, and annotation capabilities.

---

## Infrastructure (AWS)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AWS CLOUD                                       │
│                                                                              │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────────────┐ │
│  │  CloudFront  │────▶│ API Gateway  │────▶│  Lambda (Flask + Mangum)     │ │
│  │  (CDN/HTTPS) │     │  (REST API)  │     │  - viewer_app.py             │ │
│  └──────────────┘     └──────────────┘     └─────────────┬────────────────┘ │
│                                                          │                   │
│                              ┌───────────────────────────┼───────────────┐   │
│                              │                           │               │   │
│                              ▼                           ▼               │   │
│                   ┌─────────────────────┐    ┌───────────────────┐       │   │
│                   │  RDS PostgreSQL     │    │  S3 Bucket        │       │   │
│                   │  (t3.micro)         │    │  DICOM files      │       │   │
│                   │                     │    │  - /raw/{uid}/    │       │   │
│                   │  See DATABASE.md    │    │  - /processed/    │       │   │
│                   │  for full schema    │    └───────────────────┘       │   │
│                   └─────────────────────┘             ▲                  │   │
│                                                       │                  │   │
│                                             ┌────────┴────────┐         │   │
│                                             │ Lambda (indexer)│◀────────┘   │
│                                             │ S3 trigger      │             │
│  ┌──────────────┐                           └─────────────────┘             │
│  │   Cognito    │                                                           │
│  │  User Pool   │  ◀─── Authentication / JWT tokens                         │
│  └──────────────┘                                                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Services

| Service | Purpose | Estimated Cost |
|---------|---------|----------------|
| **S3** | DICOM file storage | ~$0.023/GB/month |
| **RDS PostgreSQL** | Relational database (t3.micro) | Free tier 12mo, then ~$15/mo |
| **Lambda** | Application compute | Free tier (1M requests) |
| **API Gateway** | REST API routing | Free tier (1M requests) |
| **CloudFront** | CDN + HTTPS termination | Free tier |
| **Cognito** | User authentication | Free tier (50K MAU) |

**Estimated Total: $2-20/month** (depending on storage and post-free-tier)

---

## Database Schema

The database uses PostgreSQL with a normalized schema following the DICOM hierarchy:

```
patients → studies → series → instances
```

**For complete schema documentation, see [DATABASE.md](DATABASE.md).**

### Schema Overview

| Category | Tables | Description |
|----------|--------|-------------|
| **DICOM Hierarchy** | `patients`, `studies`, `series`, `instances` | Normalized DICOM metadata |
| **Users & Auth** | `users` | Application users linked to Cognito |
| **Access Control** | `study_access`, `patient_access`, `share_links` | Row-level access control |
| **Features** | `favorites`, `annotations`, `measurements`, `analysis_results` | User data and AI outputs |

---

## Infrastructure as Code (Terraform)

### Directory Structure

```
infrastructure/
├── terraform/
│   ├── main.tf              # Provider config, backend
│   ├── variables.tf         # Input variables
│   ├── outputs.tf           # Output values
│   ├── s3.tf                # S3 bucket for DICOM files
│   ├── rds.tf               # PostgreSQL database
│   ├── lambda.tf            # Lambda functions
│   ├── api_gateway.tf       # API Gateway config
│   ├── cognito.tf           # User authentication
│   ├── cloudfront.tf        # CDN distribution
│   ├── iam.tf               # IAM roles and policies
│   └── environments/
│       ├── dev.tfvars
│       └── prod.tfvars
└── scripts/
    ├── deploy.sh            # Deployment script
    └── migrate_db.py        # Database migration
```

### Key Terraform Resources

```hcl
# S3 Bucket for DICOM files
resource "aws_s3_bucket" "dicom_storage" {
  bucket = "openradiomics-dicom-${var.environment}"
}

# RDS PostgreSQL
resource "aws_db_instance" "main" {
  identifier        = "openradiomics-${var.environment}"
  engine            = "postgres"
  engine_version    = "15"
  instance_class    = "db.t3.micro"
  allocated_storage = 20
  # ... security groups, subnets, etc.
}

# Lambda for viewer app
resource "aws_lambda_function" "viewer" {
  function_name = "openradiomics-viewer-${var.environment}"
  runtime       = "python3.11"
  handler       = "viewer_app.handler"
  memory_size   = 2048
  timeout       = 30
  # ... environment variables, IAM role, etc.
}
```

---

## S3 Storage Structure

```
openradiomics-dicom-{env}/
├── raw/
│   └── {study_uid}/
│       └── {series_uid}/
│           └── {sop_uid}.dcm          # Original DICOM files
├── processed/
│   └── {series_uid}/
│       └── volume.npy                  # Pre-processed numpy arrays (optional)
└── exports/
    └── {user_id}/
        └── {timestamp}/                # User exports
```

### S3 Key Format

DICOM files are stored with predictable keys for easy access:

```
raw/{study_uid}/{series_uid}/{sop_uid}.dcm
```

The `s3_key` column in the `instances` table stores this path.

---

## Application Components

### Backend (`viewer_app.py`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/studies` | GET | List studies (with access control) |
| `/api/studies/{id}/series` | GET | List series in a study |
| `/api/series/{id}/volume` | GET | Get 3D voxel data |
| `/api/series/{id}/slice/{plane}/{index}` | GET | Get 2D orthoslice |
| `/api/instances/{id}/metadata` | GET | Get voxel metadata |
| `/api/annotations` | GET/POST | List/create annotations |
| `/api/measurements` | GET/POST | List/create measurements |
| `/api/favorites` | GET/POST/DELETE | Manage favorites |

### Indexer (`index_dicom.py`)

- Triggered by S3 upload events
- Parses DICOM metadata using pydicom
- Inserts into PostgreSQL (patients → studies → series → instances)
- Handles deduplication via DICOM UIDs
- Updates `instance_count` in series table

### Frontend (`templates/viewer.html`)

- Three.js for 3D volume rendering
- Multi-planar reconstruction (axial, sagittal, coronal)
- Annotation tools
- Measurement tools
- User authentication UI

---

## Authentication Flow

```
┌────────────┐     ┌──────────────┐     ┌─────────────┐
│   Client   │────▶│   Cognito    │────▶│  API GW +   │
│  (Browser) │     │  User Pool   │     │  Lambda     │
└────────────┘     └──────────────┘     └─────────────┘
      │                   │                    │
      │   1. Login        │                    │
      │──────────────────▶│                    │
      │                   │                    │
      │   2. JWT Token    │                    │
      │◀──────────────────│                    │
      │                   │                    │
      │   3. API Request (Authorization: Bearer {token})
      │───────────────────────────────────────▶│
      │                   │                    │
      │                   │   4. Validate JWT  │
      │                   │◀───────────────────│
      │                   │                    │
      │   5. Response     │                    │
      │◀───────────────────────────────────────│
```

### JWT Claims Used

| Claim | Description |
|-------|-------------|
| `sub` | Cognito user ID (maps to `users.cognito_sub`) |
| `email` | User email address |
| `cognito:groups` | User groups for role-based access |

---

## Implementation Phases

### Phase 1: Database Migration ← **CURRENT**
- [x] Design and finalize PostgreSQL schema (see [DATABASE.md](DATABASE.md))
- [ ] Create Terraform for RDS
- [ ] Write migration script from SQLite
- [ ] Update `viewer_app.py` for PostgreSQL

### Phase 2: S3 Integration
- [ ] Create Terraform for S3 bucket
- [ ] Upload existing DICOM files to S3
- [ ] Update `viewer_app.py` to read from S3
- [ ] Update `index_dicom.py` for S3 triggers

### Phase 3: Lambda Deployment
- [ ] Package application for Lambda
- [ ] Create Terraform for Lambda + API Gateway
- [ ] Deploy and test endpoints

### Phase 4: Authentication
- [ ] Create Terraform for Cognito
- [ ] Add JWT validation to API
- [ ] Implement user registration/login UI
- [ ] Add access control checks

### Phase 5: Features
- [ ] Implement annotations API + UI
- [ ] Implement measurements API + UI
- [ ] Implement favorites

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `S3_BUCKET` | DICOM storage bucket name |
| `AWS_REGION` | AWS region |
| `COGNITO_USER_POOL_ID` | Cognito user pool |
| `COGNITO_CLIENT_ID` | Cognito app client |
| `ENVIRONMENT` | dev/staging/prod |

---

## Security Considerations

- **HIPAA Compliance**: PHI data encrypted at rest (S3, RDS) and in transit (HTTPS)
- **Access Control**: Row-level security via `study_access`/`patient_access` tables (see [DATABASE.md](DATABASE.md))
- **Authentication**: Cognito with MFA option
- **Audit Logging**: CloudTrail for API access, RDS audit logs
- **Network**: VPC with private subnets for RDS, Lambda in VPC

---

## Related Documentation

- **[DATABASE.md](DATABASE.md)** - Complete PostgreSQL schema, table definitions, indexes, and example queries

---

*Last Updated: 2025-01-31*
