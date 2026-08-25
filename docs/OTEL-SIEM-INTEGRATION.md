# OTel / SIEM Integration Pattern

How MLflow traces can be exported to enterprise observability platforms for long-term retention and centralized monitoring.

## Architecture

```
RAG App ──traces──> MLflow Server ──OTLP──> OTel Collector ──> Enterprise SIEM
                         │
                         └──API──> Audit Portal (POC)
```

**POC path:** The Audit Portal queries MLflow API directly. No OTel infrastructure needed.

**Production path:** MLflow exports traces via OTLP to an OpenTelemetry Collector, which forwards to the enterprise observability platform.

## Enabling OTel Export

### Step 1: Deploy the OTel Collector

```bash
export NAMESPACE=gov-rag-poc  # or your deployed namespace
envsubst < manifests/otel-collector.yaml | oc apply -f -
```

### Step 2: Configure MLflow to Export Traces

Set the OTLP endpoint on the MLflow server:

```bash
oc set env deployment/mlflow-server \
  OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.${NAMESPACE}.svc:4317 \
  -n redhat-ods-applications
```

Alternatively, if using the MLflow operator CR:

```yaml
apiVersion: mlflow.opendatahub.io/v1alpha1
kind: MLflowServer
metadata:
  name: mlflow
spec:
  env:
    - name: OTEL_EXPORTER_OTLP_ENDPOINT
      value: "http://otel-collector.${NAMESPACE}.svc:4317"
```

### Step 3: Configure the OTel Collector Exporter

Edit the `otel-collector-config` ConfigMap to add your target backend.

#### Splunk HEC

```yaml
exporters:
  splunk_hec:
    token: "${SPLUNK_HEC_TOKEN}"
    endpoint: "https://splunk-hec.example.com:8088/services/collector"
    source: "rhoai-mlflow"
    sourcetype: "opentelemetry"
    index: "ai_traces"

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [splunk_hec]
```

#### Elasticsearch / OpenSearch

```yaml
exporters:
  elasticsearch:
    endpoints: ["https://elasticsearch.example.com:9200"]
    traces_index: "mlflow-traces"
    user: "admin"
    password: "${ELASTICSEARCH_PASSWORD}"
    tls:
      insecure_skip_verify: false

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [elasticsearch]
```

#### Dynatrace

Dynatrace requires **delta temporality** for metrics. Use the `otlphttp` exporter with the `cumulativetodelta` processor.

Reference:
- [Implement LLM observability with Dynatrace on OpenShift AI](https://developers.redhat.com/articles/2025/05/21/implement-llm-observability-dynatrace-openshift-ai) (Red Hat Developer)
- [RHEcosystemAppEng/dynatrace Helm chart](https://github.com/RHEcosystemAppEng/dynatrace) (reference deployment)

```yaml
processors:
  batch:
    send_batch_size: 1000
    timeout: 10s
  cumulativetodelta:
    include:
      match_type: regexp
      metrics:
        - ".*"

exporters:
  otlphttp/dynatrace:
    endpoint: "https://{your-environment-id}.live.dynatrace.com/api/v2/otlp"
    headers:
      Authorization: "Api-Token ${DYNATRACE_API_TOKEN}"

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlphttp/dynatrace]
    metrics:
      receivers: [otlp]
      processors: [batch, cumulativetodelta]
      exporters: [otlphttp/dynatrace]
```

**Dynatrace setup notes:**
- Generate an API token with `openTelemetryTrace.ingest` and `metrics.ingest` scopes
- The `cumulativetodelta` processor is required because Dynatrace expects delta temporality for cumulative metrics
- For OpenShift, you can deploy the Dynatrace OTel integration via the Helm chart at `RHEcosystemAppEng/dynatrace`
- Traces will appear in Dynatrace under Distributed Traces, with full span attributes visible

#### SCOM (System Center Operations Manager) -- Gap Documentation

**Status: No native OTel-to-SCOM integration exists.**

SCOM is an infrastructure monitoring tool, not a trace-native observability platform. It does not support OTLP ingestion or distributed trace visualization.

**Recommended pattern:**

```
MLflow traces ──OTLP──> OTel Collector ──> Splunk / Dynatrace (primary trace storage)
                                        └──> Azure Monitor bridge ──> SCOM alerts
```

- **Primary trace data** goes to Splunk and/or Dynatrace (both support OTLP natively)
- **SCOM receives infrastructure alerts** about AI system health, not raw trace data
- **Integration options:**
  1. **Azure Monitor bridge**: If SCOM is connected to Azure Monitor, configure OTel Collector to export metrics to Azure Monitor, which forwards alerts to SCOM
  2. **Webhook alerts**: Configure alerting rules in Splunk/Dynatrace to send webhooks to SCOM when anomalous patterns are detected (high latency, error spikes, groundedness drops)
  3. **Log forwarding**: Export OTel Collector health metrics to SCOM via syslog or Windows Event Log for infrastructure-level monitoring

**What SCOM sees:** "The AI system is healthy/unhealthy" (infrastructure alerts)
**What Splunk/Dynatrace sees:** "This specific interaction was not grounded" (trace-level detail)

This is the standard pattern for organisations running SCOM alongside modern observability tools.

#### Jaeger (for development/staging)

```yaml
exporters:
  otlp/jaeger:
    endpoint: "jaeger-collector.observability.svc:4317"
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/jaeger]
```

## RHOAI 3.4 Observability Reference

For the official RHOAI 3.4 observability documentation, see [Chapter 12: Managing observability](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.4/html/managing_openshift_ai/managing-observability_managing-rhoai). This covers:

- Metrics export via the DSCI Custom Resource
- Tracing via Tempo + OTel Collector
- OTLP endpoint configuration for MLflow

## Enterprise Configuration Summary

| Tool | OTel Integration | Status |
|----------|-----------------|--------|
| **Splunk** | `splunk_hec` exporter | Supported -- config above |
| **Dynatrace** | `otlphttp` exporter + `cumulativetodelta` processor | Supported -- config above |
| **SCOM** | No native OTLP support | Gap -- receives alerts via Splunk/Dynatrace/Azure Monitor bridge |

## What Gets Exported

Each MLflow trace exported via OTLP includes:

| Field | Description |
|-------|-------------|
| `trace_id` | Unique W3C trace ID |
| `span_name` | Operation name (e.g., `rag_query`, `retrieve_context`, `llm_generation`) |
| `timestamp` | Start time of the span |
| `duration` | Execution time |
| `attributes.prompt_version` | Prompt registry version used |
| `attributes.model_name` | LLM model identifier |
| `attributes.model_endpoint` | Model serving endpoint URL |
| `attributes.source_documents` | Retrieved document sources |
| `attributes.app_version` | Application release version |
| `span.inputs` | User query / prompt content |
| `span.outputs` | Model response content |

## Mapping to Enterprise Requirements

| Requirement | SIEM Capability |
|----------------|-----------------|
| Prompt and output logging (KPI 1.3) | Full prompt/response captured in trace spans, searchable in SIEM |
| Long-term retention | SIEM retention policies apply to trace data |
| Centralized monitoring | Traces appear alongside other application logs in a single platform |
| Alerting | SIEM rules can trigger on anomalous trace patterns (high latency, errors, unusual token counts) |

## Verification

After enabling, verify traces are flowing:

```bash
# Check OTel Collector logs
oc logs deployment/otel-collector -n ${NAMESPACE}

# Run a test query through the RAG app, then check for traces
oc logs deployment/otel-collector -n ${NAMESPACE} | grep "trace_id"
```
