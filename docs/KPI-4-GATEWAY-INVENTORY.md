# KPI 4.1 / 4.2: Application Identification via AI Gateway

**KPI Requirement:** "Run an administrative query or dashboard view to identify active applications/API keys using the AI gateway. Demonstrate the metadata required to link usage back to application owner, business service and CMDB/service records."

## Demo Approach

This KPI is demonstrated through three parts:

1. **Gateway Registry View** -- CLI and dashboard showing subscriptions, models, and access policies
2. **Usage Attribution** -- Observability dashboard showing token usage per subscription
3. **Gap Acknowledgment** -- documented product gap with roadmap reference

No custom application code is needed. This is a platform-native capability demo.

---

## Part 1: Gateway Registry View

### CLI Commands

Run these from a terminal authenticated to the cluster:

```bash
# List all active MaaS subscriptions (who has access)
oc get maassubscription -n models-as-a-service

# List all published models available through the gateway
oc get maasmodelref -A

# List access policies (which groups can access which models)
oc get maasauthpolicy -n models-as-a-service

# Show details of a specific subscription
oc get maassubscription <name> -n models-as-a-service -o yaml
```

**What to point out:**
- Each subscription maps to a group (team/project)
- Subscriptions define which models a group can access
- API keys are scoped to subscriptions, providing per-team isolation

### Dashboard Views

1. **RHOAI Dashboard > Settings > Subscriptions**
   - Shows all active subscriptions with their status
   - Each subscription shows: name, group, models, status, creation date

2. **Gen AI Studio > API Keys**
   - Shows API keys associated with each subscription
   - Keys are the access control mechanism for the gateway

3. **Gen AI Studio > Models**
   - Shows all models published to the gateway
   - Each model shows: name, serving runtime, endpoint, status

---

## Part 2: Usage Attribution (Observability Dashboard)

### Prerequisites

Ensure the observability dashboard is enabled:

```bash
# Verify the MaaS CR has observability enabled
oc get maas maas -o jsonpath='{.spec.observabilityDashboard}' -n models-as-a-service
# Should return: true
```

### Dashboard Views

1. **RHOAI Dashboard > Observability tab**
   - Token usage per subscription and model
   - Request counts and latency per subscription
   - Time-series charts showing usage patterns

2. **Key metrics to highlight:**
   - **Token consumption per subscription** -- shows which teams are using how many tokens
   - **Request volume per model** -- shows which models are most used
   - **Latency percentiles** -- shows performance characteristics per model

**What to point out:**
- Each subscription maps to a group, which maps to a team or application
- Usage is automatically attributed to the subscription that owns the API key
- No manual instrumentation needed -- the gateway handles attribution

---

## Part 3: Gap Acknowledgment and Roadmap

### What Works Today

| Capability | Status | How |
|-----------|--------|-----|
| List active subscriptions | Available | CLI + Dashboard |
| List published models | Available | CLI + Dashboard |
| API key management | Available | Dashboard |
| Token usage per subscription | Available | Observability dashboard |
| Request counts per model | Available | Observability dashboard |
| Group-based access control | Available | MaaS auth policies |

### What's Missing (Product Gap)

| Capability | Status | Reference |
|-----------|--------|-----------|
| Structured app-ID field on subscriptions | Not available | RHAIRFE-2312 |
| CMDB/service record linkage | Not available | Requires app-ID field first |
| Per-key user attribution (structured owner fields) | Not available | RHAIRFE-2312 |
| Business service metadata on API keys | Not available | Future roadmap |

### Key Message

> "If it goes through the gateway, we can observe and control it. Each subscription maps to a group which maps to a team. The structured app-owner and CMDB linkage fields are on the product roadmap (RHAIRFE-2312). Today, the mapping from subscription to team is implicit via group membership. The roadmap adds explicit, structured fields for application ID, business owner, and service record references."

### Workaround (Current State)

Teams can use naming conventions on subscriptions and groups to achieve informal application identification:
- Subscription name: `<team>-<app>-<env>` (e.g., `lending-chatbot-prod`)
- Group name: `<team>-ai-users` (e.g., `lending-ai-users`)

This is a convention-based approach, not a platform-enforced one.

---

## Demo Script (5 minutes)

### Setup

```bash
# Ensure you're logged in
oc login --token=<token> --server=https://api.<CLUSTER_DOMAIN>:6443
```

### Step 1: CLI Inventory (1 min)

```bash
echo "=== Active Subscriptions ==="
oc get maassubscription -n models-as-a-service

echo "=== Published Models ==="
oc get maasmodelref -A

echo "=== Access Policies ==="
oc get maasauthpolicy -n models-as-a-service
```

**Narration:** "From the CLI, an administrator can immediately see every active subscription, which models are published, and what access policies are in place. This is the inventory of who has access to what."

### Step 2: Dashboard Walkthrough (2 min)

1. Open RHOAI Dashboard
2. Navigate to Settings > Subscriptions
3. Show the subscription list and click into one
4. Navigate to Gen AI Studio > API Keys
5. Show key management

**Narration:** "The dashboard gives a visual inventory. Each subscription represents a team or application's access to the AI gateway. API keys are scoped to subscriptions, so every request is attributable."

### Step 3: Usage Metrics (1 min)

1. Navigate to Observability tab
2. Show token usage charts
3. Show request volume per model

**Narration:** "The observability dashboard shows real-time usage. You can see which subscriptions are consuming tokens, request volumes, and latency. This is automatic -- the gateway attributes every request to its subscription."

### Step 4: Gap Acknowledgment (1 min)

**Narration:** "I want to be transparent about what's not yet available. Today, each subscription maps to a group, which maps to a team. But there isn't a structured field on the subscription for application ID, business owner, or CMDB service record. That's a known product gap with an RFE in flight -- RHAIRFE-2312. The roadmap includes structured per-key user attribution and app-owner metadata. The key takeaway: if traffic goes through the gateway, it's observable and controllable. The structured metadata for CMDB integration is coming."
