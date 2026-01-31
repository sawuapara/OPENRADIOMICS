#!/bin/bash
# OpenRadiomics - Deployment Script
# Deploys infrastructure and application to AWS

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TERRAFORM_DIR="$PROJECT_ROOT/infrastructure/terraform"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
echo_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
echo_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check prerequisites
check_prerequisites() {
    echo_info "Checking prerequisites..."

    if ! command -v aws &> /dev/null; then
        echo_error "AWS CLI not found. Install with: brew install awscli"
        exit 1
    fi

    if ! command -v terraform &> /dev/null; then
        # Check user bin
        if [ -f "$HOME/bin/terraform" ]; then
            export PATH="$HOME/bin:$PATH"
        else
            echo_error "Terraform not found. Install with: brew install hashicorp/tap/terraform"
            exit 1
        fi
    fi

    if ! command -v docker &> /dev/null; then
        echo_error "Docker not found. Install Docker Desktop from https://docker.com"
        exit 1
    fi

    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        echo_error "AWS credentials not configured. Run: aws configure"
        exit 1
    fi

    echo_info "All prerequisites satisfied."
}

# Deploy Terraform infrastructure
deploy_infrastructure() {
    echo_info "Deploying Terraform infrastructure..."

    cd "$TERRAFORM_DIR"

    # Initialize if needed
    if [ ! -d ".terraform" ]; then
        terraform init
    fi

    # Check for database password
    if [ -z "$TF_VAR_db_password" ]; then
        echo_warn "TF_VAR_db_password not set. Generating random password..."
        export TF_VAR_db_password=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 20)
        echo_info "Generated password: $TF_VAR_db_password"
        echo_warn "SAVE THIS PASSWORD! You'll need it for database access."
    fi

    # Apply Terraform
    terraform apply -var-file=environments/dev.tfvars -auto-approve

    # Get outputs
    export S3_BUCKET=$(terraform output -raw s3_bucket_name)
    export ECR_REPO=$(terraform output -raw ecr_repository_url)
    export APP_URL=$(terraform output -raw app_url)

    echo_info "Infrastructure deployed successfully."
    echo_info "S3 Bucket: $S3_BUCKET"
    echo_info "ECR Repository: $ECR_REPO"
}

# Build and push Docker image
build_and_push() {
    echo_info "Building Docker image..."

    cd "$PROJECT_ROOT"

    # Get ECR login
    aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "$ECR_REPO"

    # Build image
    docker build -t openradiomics:latest .

    # Tag for ECR
    docker tag openradiomics:latest "$ECR_REPO:latest"

    # Push to ECR
    echo_info "Pushing to ECR..."
    docker push "$ECR_REPO:latest"

    echo_info "Docker image pushed successfully."
}

# Upload DICOM files to S3
upload_dicom() {
    echo_info "Uploading DICOM files to S3..."

    cd "$PROJECT_ROOT"

    # Check if database exists
    if [ ! -f "brain_inventory.db" ]; then
        echo_warn "Database not found. Skipping DICOM upload."
        return
    fi

    python3 "$SCRIPT_DIR/upload_dicom_to_s3.py" \
        --bucket "$S3_BUCKET" \
        --db brain_inventory.db \
        --workers 20

    echo_info "DICOM upload complete."
}

# Main deployment
main() {
    echo "========================================"
    echo "  OpenRadiomics Deployment"
    echo "========================================"
    echo ""

    check_prerequisites

    case "${1:-all}" in
        infra|infrastructure)
            deploy_infrastructure
            ;;
        docker|build)
            # Get ECR URL from Terraform
            cd "$TERRAFORM_DIR"
            export ECR_REPO=$(terraform output -raw ecr_repository_url 2>/dev/null || echo "")
            if [ -z "$ECR_REPO" ]; then
                echo_error "Infrastructure not deployed. Run: ./deploy.sh infra"
                exit 1
            fi
            build_and_push
            ;;
        upload|dicom)
            # Get S3 bucket from Terraform
            cd "$TERRAFORM_DIR"
            export S3_BUCKET=$(terraform output -raw s3_bucket_name 2>/dev/null || echo "")
            if [ -z "$S3_BUCKET" ]; then
                echo_error "Infrastructure not deployed. Run: ./deploy.sh infra"
                exit 1
            fi
            upload_dicom
            ;;
        all)
            deploy_infrastructure
            build_and_push
            upload_dicom
            echo ""
            echo "========================================"
            echo_info "Deployment complete!"
            echo ""
            echo "  App URL: $APP_URL"
            echo ""
            echo "  Note: App Runner may take 2-3 minutes to start."
            echo "========================================"
            ;;
        status)
            cd "$TERRAFORM_DIR"
            echo_info "Current deployment status:"
            terraform output 2>/dev/null || echo "Infrastructure not deployed."
            ;;
        destroy)
            echo_warn "This will destroy all infrastructure!"
            read -p "Are you sure? (yes/no): " confirm
            if [ "$confirm" = "yes" ]; then
                cd "$TERRAFORM_DIR"
                terraform destroy -var-file=environments/dev.tfvars -auto-approve
            fi
            ;;
        *)
            echo "Usage: $0 [command]"
            echo ""
            echo "Commands:"
            echo "  all         - Full deployment (default)"
            echo "  infra       - Deploy infrastructure only"
            echo "  docker      - Build and push Docker image"
            echo "  upload      - Upload DICOM files to S3"
            echo "  status      - Show deployment status"
            echo "  destroy     - Destroy all infrastructure"
            ;;
    esac
}

main "$@"
