# OpenRadiomics - Claude Development Notes

## Deployment Environment

**IMPORTANT: This application is deployed to AWS App Runner, NOT running locally.**

- **Live URL**: https://ezj2rdbghf.us-east-1.awsapprunner.com
- **AWS Region**: us-east-1
- **Infrastructure**: Managed via Terraform in `infrastructure/terraform/`

## Deployment Process

### To deploy code changes:
1. Commit changes to the repository
2. Trigger CodeBuild to build and push Docker image:
   ```bash
   aws codebuild start-build --project-name openradiomics-build --region us-east-1
   ```
3. App Runner auto-deploys when new image is pushed to ECR

### To deploy infrastructure changes:
1. Install Terraform (if not available)
2. Run from `infrastructure/terraform/`:
   ```bash
   terraform init
   terraform plan
   terraform apply
   ```

## Architecture

- **Frontend**: Three.js-based MRI viewer (templates/viewer.html)
- **Backend**: Flask API (viewer_app.py)
- **Database**: PostgreSQL on RDS
- **Storage**: S3 for DICOM files
- **Auth**: AWS Cognito (HIPAA-compliant with mandatory MFA)
- **Hosting**: AWS App Runner (auto-scaling container service)

## Key Files

| File | Purpose |
|------|---------|
| `viewer_app.py` | Flask backend API |
| `auth.py` | Authentication module (Cognito JWT validation) |
| `templates/viewer.html` | Main viewer UI |
| `templates/login.html` | Login page |
| `infrastructure/terraform/*.tf` | AWS infrastructure |

## Authentication (HIPAA Compliant)

- Cognito User Pool with mandatory MFA
- 15-minute access tokens, 8-hour refresh tokens
- Session timeout after 15 minutes of inactivity
- All access logged to `audit_log` table

## Environment Variables (App Runner)

- `COGNITO_USER_POOL_ID` - Cognito User Pool ID
- `COGNITO_CLIENT_ID` - Cognito App Client ID
- `COGNITO_DOMAIN` - Cognito hosted UI domain
- `SECRET_KEY` - Flask session secret
- `S3_BUCKET_NAME` - DICOM storage bucket
- `AWS_REGION` - AWS region (us-east-1)

## Testing Changes

Always test against the live URL after deployment:
```bash
curl https://ezj2rdbghf.us-east-1.awsapprunner.com/api/health
```

## DO NOT

- Run the app locally for testing (use the deployed version)
- Make changes without deploying to see results
- Forget that auth requires Cognito infrastructure to be deployed first
