# ANZ New Zealand Data Governance and AI Policy (Sample)

**Document ID:** POL-DGOV-2025-001
**Version:** 2.0
**Classification:** Internal Use Only
**Last Reviewed:** February 2025

## 1. Purpose

This policy establishes the data governance framework for the use of data and artificial intelligence within ANZ Bank New Zealand, ensuring compliance with the Privacy Act 2020, the New Zealand Information Privacy Principles (IPPs), and the Bank's enterprise risk management framework.

## 2. Data Classification

### 2.1 Classification Levels

| Level | Description | Examples | Handling Requirements |
|-------|-------------|----------|----------------------|
| **Restricted** | Data whose unauthorised disclosure would cause significant harm | Customer PII, credit card numbers, account balances, passwords | Encryption at rest and in transit, access restricted to named individuals, no use in non-production environments without masking |
| **Confidential** | Data intended for internal use that could cause harm if disclosed | Internal reports, strategy documents, employee records | Encryption in transit, role-based access control, clean desk policy |
| **Internal** | Data for general internal use | Policies, procedures, operational guides | Access controlled by business unit, no external sharing without approval |
| **Public** | Data approved for external disclosure | Marketing materials, published rates, annual reports | No restrictions on distribution |

### 2.2 Data Handling in AI Systems

- **Restricted data** must not be used as training data for AI models without explicit approval from the Chief Data Officer and Privacy Officer.
- **Personally Identifiable Information (PII)** must be anonymised or pseudonymised before use in model development, testing, or evaluation.
- **Synthetic data** should be used for development and testing purposes wherever feasible.
- All data used in AI systems must have documented provenance, including source, collection date, consent basis, and any transformations applied.

## 3. AI Model Governance

### 3.1 Model Risk Management

All AI models deployed in production must comply with the Bank's Model Risk Management (MRM) framework:

- **Model Registration:** All models must be registered in the enterprise model registry with a unique identifier, owner, business purpose, and risk tier.
- **Model Validation:** Independent validation is required before production deployment. Validation must assess accuracy, fairness, robustness, and explainability.
- **Model Monitoring:** Production models must be monitored for performance drift, data drift, and fairness metrics on an ongoing basis.
- **Model Retirement:** Models that no longer meet performance thresholds or business requirements must be retired through a documented decommissioning process.

### 3.2 Generative AI Controls

The following additional controls apply to Generative AI (GenAI) systems, including Large Language Models (LLMs):

- **Prompt Management:** All prompts used in production GenAI applications must be version-controlled, reviewed, and approved before deployment.
- **Output Monitoring:** GenAI outputs must be logged and available for audit review. Logging must capture the full prompt, model response, model version, and timestamp.
- **Guardrails:** Production GenAI applications must implement input and output guardrails to prevent prompt injection, sensitive data leakage, and generation of harmful or non-compliant content.
- **Human Oversight:** GenAI-generated outputs that inform decisions affecting customers must include a human review step before action is taken.
- **Cost Controls:** Token usage, API costs, and compute resource consumption must be monitored and subject to budget controls. Usage exceeding defined thresholds must trigger alerts.

### 3.3 Model Approval Authority

| Model Risk Tier | Approval Authority | Review Frequency |
|----------------|-------------------|-----------------|
| Tier 1 (Critical) | Executive Risk Committee | Quarterly |
| Tier 2 (High) | Model Risk Committee | Semi-annually |
| Tier 3 (Medium) | Business Unit Risk Manager | Annually |
| Tier 4 (Low) | Model Owner | Annually |

## 4. Data Retention and Disposal

### 4.1 Retention Periods

- **Customer transaction data:** 7 years from the date of the transaction.
- **Customer identification records:** 5 years after the end of the customer relationship.
- **AI model training data:** Retained for the life of the model plus 3 years after retirement.
- **AI model inference logs:** 3 years from the date of the interaction.
- **Model validation and audit records:** 7 years from the date of the record.

### 4.2 Disposal Requirements

- Data disposal must be performed using approved methods that render data unrecoverable.
- Disposal must be documented, including the data destroyed, method used, date, and authorising officer.
- Disposal of Restricted data requires dual authorisation.

## 5. Privacy and Consent

### 5.1 Privacy Act 2020 Compliance

All data processing activities must comply with the 13 Information Privacy Principles (IPPs) under the Privacy Act 2020, including:

- **IPP 1 (Purpose):** Personal information must only be collected for a lawful purpose connected with the Bank's functions.
- **IPP 3 (Collection from subject):** Where reasonably practicable, personal information must be collected directly from the individual concerned.
- **IPP 5 (Storage and security):** Personal information must be protected against loss, misuse, and unauthorised access.
- **IPP 10 (Use):** Personal information must not be used for a purpose other than the purpose for which it was collected, unless an exception applies.
- **IPP 11 (Disclosure):** Personal information must not be disclosed unless the disclosure is for the purpose for which it was collected, or the individual authorises the disclosure.

### 5.2 AI-Specific Privacy Considerations

- Customers must be informed when AI systems are used in decisions that materially affect them.
- Customers have the right to request a human review of any AI-assisted decision.
- Profiling activities using AI must be documented and subject to privacy impact assessment.
- Cross-border data transfers for AI processing must comply with IPP 12 and require Privacy Officer approval.

## 6. Audit and Compliance

### 6.1 Audit Trail Requirements

- All access to Restricted and Confidential data must be logged.
- AI model inference logs must capture: timestamp, model identifier, model version, input data (or hash), output data, and the identity of the requesting application or user.
- Audit logs must be immutable and retained in accordance with the retention schedule.
- Internal Audit must include data governance and AI controls in its annual audit plan.

### 6.2 Regulatory Reporting

- Data breaches involving personal information must be reported to the Office of the Privacy Commissioner within 72 hours of becoming aware of the breach.
- Material AI model failures or incidents must be reported to the relevant risk committee within 24 hours.
- The Bank must maintain a register of all AI systems and their risk classifications, available for inspection by regulators upon request.
