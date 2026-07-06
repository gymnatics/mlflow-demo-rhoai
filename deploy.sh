#!/bin/bash
################################################################################
# Deploy ANZ NZ Governance POC
################################################################################
# Deploys the RAG chat app (Chainlit) and Audit Portal (Streamlit) to OpenShift.
#
# Prerequisites:
#   - RHOAI 3.4 with MLflow operator enabled + MLflow CR deployed
#   - A model endpoint (MaaS inference gateway or InferenceService)
#   - oc CLI authenticated to the cluster
#
# Usage:
#   ./deploy.sh                    # Interactive deployment
#   ./deploy.sh --delete           # Remove everything
################################################################################

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_header() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║ $1${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_step()    { echo -e "${YELLOW}▶ $1${NC}"; }
print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_error()   { echo -e "${RED}✗ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠ $1${NC}"; }
print_info()    { echo -e "${CYAN}ℹ $1${NC}"; }

DELETE_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --delete|--teardown) DELETE_MODE=true; shift ;;
        -h|--help)
            echo "Usage: $0 [--delete]"
            echo ""
            echo "Deploys the ANZ NZ Governance POC:"
            echo "  - RAG Chat App (Chainlit) with MLflow tracing"
            echo "  - Audit Portal (Streamlit) for compliance reporting"
            echo ""
            echo "Options:"
            echo "  --delete    Remove all POC resources"
            exit 0
            ;;
        *) shift ;;
    esac
done

print_header "ANZ NZ Governance POC"

if ! oc whoami &>/dev/null; then
    print_error "Not logged in to OpenShift. Run: oc login <cluster-url>"
    exit 1
fi

CLUSTER_DOMAIN=$(oc get ingress.config cluster -o jsonpath='{.spec.domain}' 2>/dev/null || echo "apps.cluster.example.com")

export NAMESPACE=${NAMESPACE:-anz-governance-poc}
export APP_VERSION=${APP_VERSION:-1.0.0}

if [ "$DELETE_MODE" = true ]; then
    print_step "Removing ANZ POC namespace: $NAMESPACE"
    oc delete project "$NAMESPACE" --ignore-not-found 2>/dev/null || true
    print_success "ANZ POC cleaned up"
    exit 0
fi

# --- Check MLflow ---
print_step "Checking MLflow availability..."
MLFLOW_STATUS_URL=$(oc get mlflow mlflow -o jsonpath='{.status.url}' 2>/dev/null || echo "")
if [ -z "$MLFLOW_STATUS_URL" ]; then
    print_error "MLflow CR not found or not ready. Ensure MLflow operator is enabled and CR is deployed."
    print_info "  oc get mlflow mlflow -o jsonpath='{.status.url}'"
    exit 1
fi
export MLFLOW_TRACKING_URI="${MLFLOW_STATUS_URL}"
print_success "MLflow: $MLFLOW_TRACKING_URI"

# --- Gather configuration ---
print_info "Cluster domain: $CLUSTER_DOMAIN"
echo ""

if [ -z "$LLM_ENDPOINT" ]; then
    GATEWAY_URL="https://inference-gateway.${CLUSTER_DOMAIN}/v1"
    read -rp "LLM endpoint URL [$GATEWAY_URL]: " input_endpoint
    export LLM_ENDPOINT="${input_endpoint:-$GATEWAY_URL}"
fi

if [ -z "$LLM_MODEL" ]; then
    read -rp "LLM model name [qwen35-9b-awq]: " input_model
    export LLM_MODEL="${input_model:-qwen35-9b-awq}"
fi

if [ -z "$LLM_API_KEY" ]; then
    read -rp "LLM API key (or press Enter to use SA token): " input_key
    export LLM_API_KEY="${input_key:-placeholder}"
fi

echo ""
print_info "Configuration:"
print_info "  Namespace:    $NAMESPACE"
print_info "  LLM Endpoint: $LLM_ENDPOINT"
print_info "  LLM Model:    $LLM_MODEL"
print_info "  MLflow URI:   $MLFLOW_TRACKING_URI"
print_info "  App Version:  $APP_VERSION"
echo ""

read -rp "Continue with deployment? (Y/n): " confirm
confirm=${confirm:-Y}
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

# --- Create namespace ---
print_step "Creating namespace: $NAMESPACE"
envsubst < "$SCRIPT_DIR/manifests/namespace.yaml" | oc apply -f - 2>/dev/null || \
    oc new-project "$NAMESPACE" --display-name="ANZ Governance POC" 2>/dev/null || true
oc project "$NAMESPACE" 2>/dev/null || true
print_success "Namespace ready"

# --- RBAC (ServiceAccount + MLflow access) ---
print_step "Setting up RBAC for MLflow access..."
envsubst < "$SCRIPT_DIR/manifests/rbac.yaml" | oc apply -f -
print_success "ServiceAccount and MLflow RoleBinding created"

# --- Create secret ---
print_step "Creating API key secret"
oc create secret generic anz-poc-secrets \
    --from-literal=llm-api-key="$LLM_API_KEY" \
    -n "$NAMESPACE" --dry-run=client -o yaml | oc apply -f -
print_success "Secret created"

# --- Create ConfigMap ---
print_step "Creating config..."
envsubst < "$SCRIPT_DIR/manifests/configmap.yaml" | oc apply -f -
print_success "ConfigMap created"

# --- Build images ---
print_step "Building RAG app container image..."
oc new-build --name=anz-rag-app \
    --binary --strategy=docker \
    -n "$NAMESPACE" 2>/dev/null || true
oc start-build anz-rag-app \
    --from-dir="$SCRIPT_DIR/rag-app" \
    --follow -n "$NAMESPACE"
export RAG_APP_IMAGE="image-registry.openshift-image-registry.svc:5000/${NAMESPACE}/anz-rag-app:latest"
print_success "RAG app image built"

print_step "Building Audit Portal container image..."
oc new-build --name=anz-audit-portal \
    --binary --strategy=docker \
    -n "$NAMESPACE" 2>/dev/null || true
oc start-build anz-audit-portal \
    --from-dir="$SCRIPT_DIR/audit-portal" \
    --follow -n "$NAMESPACE"
export AUDIT_PORTAL_IMAGE="image-registry.openshift-image-registry.svc:5000/${NAMESPACE}/anz-audit-portal:latest"
print_success "Audit Portal image built"

# --- Deploy ---
print_step "Deploying RAG app..."
envsubst < "$SCRIPT_DIR/manifests/rag-app.yaml" | oc apply -f -
print_success "RAG app deployed"

print_step "Deploying Audit Portal..."
envsubst < "$SCRIPT_DIR/manifests/audit-portal.yaml" | oc apply -f -
print_success "Audit Portal deployed"

# --- Wait for rollout ---
print_step "Waiting for pods to start..."
oc rollout status deployment/anz-rag-app -n "$NAMESPACE" --timeout=300s 2>/dev/null || \
    print_warning "RAG app rollout still in progress"
oc rollout status deployment/anz-audit-portal -n "$NAMESPACE" --timeout=300s 2>/dev/null || \
    print_warning "Audit Portal rollout still in progress"

# --- Register initial prompt ---
print_step "Registering initial prompt version (v1)..."
oc exec deployment/anz-rag-app -n "$NAMESPACE" -- \
    python -c "from prompt_manager import register_prompt; register_prompt('v1')" 2>/dev/null || \
    print_warning "Could not register prompt (will register on first use)"

# --- Print results ---
echo ""
print_header "Deployment Complete"

RAG_ROUTE=$(oc get route anz-rag-app -n "$NAMESPACE" -o jsonpath='{.status.ingress[0].host}' 2>/dev/null || echo "<pending>")
AUDIT_ROUTE=$(oc get route anz-audit-portal -n "$NAMESPACE" -o jsonpath='{.status.ingress[0].host}' 2>/dev/null || echo "<pending>")

print_success "RAG Chat App:   https://${RAG_ROUTE}"
print_success "Audit Portal:   https://${AUDIT_ROUTE}"
print_success "MLflow UI:      ${MLFLOW_TRACKING_URI}"
echo ""
print_info "Demo runbook: docs/DEMO-RUNBOOK.md"
print_info "OTel docs:    docs/OTEL-SIEM-INTEGRATION.md"
