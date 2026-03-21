# Peak 10 Energy — Deployment & Configuration Guide
**Handoff Document: What You Do (Portal) → What Claude Builds (Code)**

This guide walks you through every portal-side action required to bring the four-pillar platform from code to production. Each step tells you exactly what to do, what to copy/save, and when to hand back to Claude for the next code phase.

---

## Phase 0: Pre-Flight — Purchases, Permissions & Local Setup

Complete everything in this section before touching the Azure Portal. Estimated time: 30–60 minutes (excluding Azure OpenAI approval wait).

### 0.1 — Licenses & Subscriptions Required

| Requirement | What It Is | You Likely Have It? | Cost If Not |
|---|---|---|---|
| **Azure Subscription** | Pay-as-you-go or Enterprise Agreement | Yes, if Peak 10 uses M365 | ~$200-400/mo for this workload on dev |
| **Microsoft 365 Business Premium** | Includes SharePoint, Outlook, Power Automate | Almost certainly yes | $22/user/mo |
| **GitHub account** | Free tier works for private repos | Yes (`kdmcquire-creator`) | Free |

**No additional software purchases are required.** All Azure services are pay-as-you-go and Plaid sandbox is free.

### 0.2 — Azure Service Costs (Dev Environment)

These services are provisioned automatically by the Bicep templates but incur charges:

| Service | Pillar | Dev Cost Estimate | Notes |
|---|---|---|---|
| 4x Azure Functions (Consumption/Y1) | All | **Free** | 1M executions/mo included in free grant |
| 4x Storage Accounts | All | **~$1/mo total** | Minimal usage |
| 4x Application Insights | All | **Free** | 5GB/mo included |
| 4x Key Vaults | All | **~$1/mo total** | Standard tier |
| Azure OpenAI Service | 2 | **~$5-50/mo** | GPT-4o at ~$5/1M input tokens; depends on email volume |
| Azure AI Document Intelligence | 3 | **~$1-10/mo** | S0 tier, per-page pricing |
| Azure SQL Database (Basic) | 4 | **~$5/mo** | TDE-encrypted for Chinese Wall |
| **Total dev environment** | | **~$15-70/mo** | Scales with usage |

Production costs increase when Function Apps move from Consumption (Y1) to Basic (B1) at ~$55/mo each, and SQL moves to Standard (S1) at ~$15/mo.

### 0.3 — External Service Sign-Ups

| Service | Action | Free Tier? | Time to Activate |
|---|---|---|---|
| **Plaid** | Create account at https://dashboard.plaid.com/signup | Sandbox: **free**. Development: 100 live items free. Production: $500+/mo | Immediate |
| **Azure OpenAI** | May need to request access (see blocker check below) | Free to enable; pay per token | 1-5 business days if not already enabled |

#### Potential Blocker: Azure OpenAI Access

Not all Azure subscriptions have Azure OpenAI enabled by default. **Check this now:**

1. Go to **Azure Portal → search "Azure OpenAI"**
2. If you see a **"Create"** button → you're good, skip ahead
3. If you see **"Request Access"** → submit the form at https://aka.ms/oai/access
4. Approval takes **1-5 business days**

**If blocked:** Pillars 1 and 4 have zero dependency on Azure OpenAI. Deploy and use them immediately while waiting. Pillars 2 and 3 will run in rule-based-only mode (no AI fallback) until access is granted.

### 0.4 — Permissions You Need

Confirm you hold (or can get) these roles before starting:

| Permission | Where to Check | Why You Need It |
|---|---|---|
| **Owner** or **Contributor** | Azure Portal → Subscriptions → your sub → Access control (IAM) | Deploy resources, create service principals |
| **Application Administrator** (or Global Admin) | Azure Portal → Microsoft Entra ID → Roles and administrators | Create the service principal in Step 1.2 |
| **SharePoint Administrator** | Microsoft 365 Admin Center → Roles | Run the SharePoint provisioning script, create sites |
| **Power Automate Environment Maker** | Power Platform Admin Center → Environments | Create the Outlook → triage flow in Phase 4 |
| **GitHub Repository Admin** | GitHub → Settings → Collaborators | Set repository secrets for CI/CD |

If you are the CEO and the M365 Global Admin, you already have all of these. If IT manages your tenant, ask them to confirm these roles are assigned to your account before proceeding.

### 0.5 — Software to Install Locally

Install these on whatever machine you'll run the deployment commands from (your laptop, or use Azure Cloud Shell which has Azure CLI and PowerShell pre-installed):

| Tool | Install Instructions | Required For |
|---|---|---|
| **Azure CLI 2.50+** | macOS: `brew install azure-cli` · Windows: `winget install Microsoft.AzureCLI` · All: https://aka.ms/installazurecli | All Bicep deployments (Phases 2-5) |
| **Azure Functions Core Tools v4** | macOS: `brew install azure-functions-core-tools@4` · Windows: `winget install Microsoft.Azure.FunctionsCoreTools` · All: https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local | `func azure functionapp publish` commands |
| **PowerShell 7+** | macOS: `brew install powershell` · Windows: Built-in (run `pwsh` to verify) · All: https://github.com/PowerShell/PowerShell/releases | SharePoint provisioning script (Phase 3) |
| **PnP.PowerShell module** | Inside PowerShell 7: `Install-Module PnP.PowerShell -Scope CurrentUser` | SharePoint folder hierarchy creation |
| **Python 3.11+** *(optional)* | https://www.python.org/downloads/ | Local testing only; not required for deployment |

**Shortcut — Azure Cloud Shell:** If you don't want to install anything locally, open https://shell.azure.com in your browser. It has Azure CLI, PowerShell 7, and Python pre-installed. You'll only need to run `Install-Module PnP.PowerShell` inside Cloud Shell.

### 0.6 — Pre-Flight Checklist

Run through this before starting Phase 1:

- [ ] Azure subscription is active and you can log into https://portal.azure.com
- [ ] You have Owner or Contributor role on the subscription
- [ ] M365 tenant is active with SharePoint and Outlook
- [ ] Azure OpenAI access is confirmed (or request submitted — note the date: _______)
- [ ] Plaid developer account created at https://dashboard.plaid.com
- [ ] Azure CLI installed (`az --version` returns 2.50+)
- [ ] Azure Functions Core Tools installed (`func --version` returns 4.x)
- [ ] PowerShell 7 installed (`pwsh --version` returns 7.x)
- [ ] PnP.PowerShell module installed (`Get-Module PnP.PowerShell -ListAvailable` shows a version)
- [ ] GitHub repo access confirmed (can push to `kdmcquire-creator/Peak10-enterprise-automation`)

Once all boxes are checked, proceed to Phase 1.

### 0.7 — Credential Handoff Packet

Collect these values as you work. When this packet is complete, I can finish the final tenant-wiring pass much faster:

- Azure subscription ID
- Azure tenant ID
- Resource group name
- Pillar 1, 2, 3, and 4 Function App URLs
- Pillar 1, 2, 3, and 4 Function App host keys
- Azure OpenAI endpoint and deployment name
- Document Intelligence endpoint
- SharePoint site URL, site ID, and drive ID
- Outlook mailbox address to monitor
- Confirmation that Graph admin consent has been granted
- Plaid client ID and environment

Key Vault secret names expected by the current code:

- Pillar 2: `azure-openai-key`, `cosmos-connection-string`, `cognitive-services-key`, `graph-client-id`, `graph-client-secret`, `graph-tenant-id`, `graph-mailbox-address`, `graph-sharepoint-site-id`, `graph-sharepoint-drive-id`
- Pillar 4: `sql-connection-string`, `plaid-client-id`, `plaid-secret`, `plaid-environment`

---

## Phase 1: Azure Foundation (30–45 minutes)

### Step 1.1 — Create a Resource Group

1. Go to **Azure Portal → Resource Groups → Create**
2. Settings:
   - **Subscription**: Your Azure subscription
   - **Resource group name**: `rg-peak10-dev`
   - **Region**: `South Central US` (closest to Permian Basin operations)
3. Click **Review + Create → Create**
4. Repeat for `rg-peak10-prod` (you'll use this later)

### Step 1.2 — Create an Azure AD App Registration (Service Principal)

This creates the credentials GitHub Actions uses to deploy.

1. Go to **Azure Portal → Microsoft Entra ID → App registrations → New registration**
2. Settings:
   - **Name**: `peak10-github-deployer`
   - **Supported account types**: Single tenant
   - **Redirect URI**: Leave blank
3. Click **Register**
4. On the app's overview page, copy these values and save them in a secure note:
   ```
   Application (client) ID:  ___________________________
   Directory (tenant) ID:    ___________________________
   ```
5. Go to **Certificates & secrets → New client secret**
   - **Description**: `github-actions`
   - **Expires**: 24 months
   - Click **Add**
   - **IMMEDIATELY copy the secret Value** (you cannot see it again):
   ```
   Client secret value:      ___________________________
   ```

### Step 1.3 — Grant the Service Principal Access to Your Resource Group

1. Go to **Resource Groups → rg-peak10-dev → Access control (IAM) → Add role assignment**
2. **Role**: `Contributor`
3. **Members → Select members**: Search for `peak10-github-deployer`, select it
4. Click **Review + assign**

### Step 1.4 — Set the GitHub Repository Secret

1. Go to **GitHub → kdmcquire-creator/Peak10-enterprise-automation → Settings → Secrets and variables → Actions**
2. Click **New repository secret**
3. **Name**: `AZURE_CREDENTIALS`
4. **Value**: Paste this JSON (fill in your values from Step 1.2):
   ```json
   {
     "clientId": "<Application (client) ID>",
     "clientSecret": "<Client secret value>",
     "subscriptionId": "<Your Azure subscription ID>",
     "tenantId": "<Directory (tenant) ID>"
   }
   ```
   To find your **Subscription ID**: Azure Portal → Subscriptions → copy the ID.
5. Click **Add secret**

### Step 1.5 — Create GitHub Environments

1. Still in **GitHub → Settings → Environments**
2. Click **New environment**, name it `dev`, click **Configure environment**
3. No additional protection rules needed for dev
4. Repeat: create a `prod` environment (optionally add required reviewers)

**Checkpoint**: After this phase, your GitHub Actions CI/CD pipelines can authenticate to Azure. Go to the **Actions** tab in GitHub — you should see the 4 workflow files listed (they won't run until code changes hit `main`).

---

## Phase 2: Deploy Pillar 1 — AFA Engine (20 minutes)

### Step 2.1 — Deploy Infrastructure via Bicep

Open a terminal (locally or Azure Cloud Shell):

```bash
# Login to Azure
az login

# Deploy Pillar 1 infrastructure
az deployment group create \
  --resource-group rg-peak10-dev \
  --template-file pillar1-afa-engine/infra/main.bicep \
  --parameters environment=dev
```

This creates:
- Function App: `func-peak10afafdev`
- Storage Account: `stpeak10afafdev`
- Application Insights: `ai-peak10afafdev`
- Key Vault: `kv-peak10afafdev`

### Step 2.2 — Deploy the Function App Code

```bash
cd pillar1-afa-engine
func azure functionapp publish func-peak10afafdev --python
```

Or, merge the branch to `main` and GitHub Actions will auto-deploy.

### Step 2.3 — Verify Deployment

```bash
curl https://func-peak10afafdev.azurewebsites.net/api/health?code=<your-function-key>
```

To get your function key:
1. Azure Portal → Function App → `func-peak10afafdev` → App keys
2. Copy the **default** host key

Expected response:
```json
{"status": "healthy", "service": "afa-engine", "version": "1.0.0"}
```

**Save this for Claude**: Copy the Function App URL and host key. You'll need these when wiring the pillars together.

```
Pillar 1 URL:  https://func-peak10afafdev.azurewebsites.net
Pillar 1 Key:  ___________________________
```

---

## Phase 3: Deploy Pillar 3 — Document AI (30 minutes)

### Step 3.1 — Deploy Infrastructure

```bash
az deployment group create \
  --resource-group rg-peak10-dev \
  --template-file pillar3-document-ai/infra/main.bicep \
  --parameters environment=dev
```

This additionally creates:
- Azure AI Document Intelligence (Cognitive Services): `cog-peak10docaidev`
- Blob container: `staging-documents`

### Step 3.2 — Deploy the Function App Code

```bash
cd pillar3-document-ai
func azure functionapp publish func-peak10docaidev --python
```

### Step 3.3 — Provision the SharePoint Folder Hierarchy

1. Open **PowerShell 7**
2. Run:
   ```powershell
   cd pillar3-document-ai/scripts
   ./provision_sharepoint.ps1 -SiteUrl "https://peak10energy.sharepoint.com/sites/Operations"
   ```
3. A browser window will open for M365 login — authenticate with your admin account
4. The script creates all 50+ folders in the governed hierarchy
5. Verify in SharePoint: navigate to your site → Documents → you should see:
   - `00_STAGING/` (with Inbox, Processing, Errors)
   - `01_CORPORATE/` (with Legal, Finance, Insurance, HR sub-trees)
   - `02_OPERATIONS/` (with Field_Reports, Well_Files, AFEs, etc.)
   - `03_DEALS/` (with Active, Closed, Passed, Pipeline)
   - `04_GOVERNANCE/` (with Board_Minutes, Operating_Agreements, etc.)

### Step 3.4 — Store the Cognitive Services Key in Key Vault

1. Azure Portal → `cog-peak10docaidev` → **Keys and Endpoint**
2. Copy **Key 1**
3. Azure Portal → `kv-peak10docaidev` → **Secrets → Generate/Import**
   - **Name**: `cognitive-services-key`
   - **Value**: Paste Key 1
4. Click **Create**

**Save this for Claude**:
```
Pillar 3 URL:           https://func-peak10docaidev.azurewebsites.net
Pillar 3 Key:           ___________________________
SharePoint Site URL:    https://peak10energy.sharepoint.com/sites/Operations
Cognitive Endpoint:     https://cog-peak10docaidev.cognitiveservices.azure.com
```

---

## Phase 4: Deploy Pillar 2 — Email Intelligence (30 minutes)

### Step 4.1 — Deploy Infrastructure

```bash
az deployment group create \
  --resource-group rg-peak10-dev \
  --template-file pillar2-email-intelligence/infra/main.bicep \
  --parameters environment=dev
```

This additionally creates:
- Azure OpenAI Service: `oai-peak10emaildev`

### Step 4.2 — Deploy a GPT-4o Model in Azure OpenAI

1. Azure Portal → `oai-peak10emaildev` → **Model deployments → Deploy model**
2. Select **gpt-4o**
3. **Deployment name**: `gpt-4o-email` (remember this exact name)
4. **Tokens per minute rate limit**: 30K (sufficient for email triage)
5. Click **Deploy**

### Step 4.3 — Store the OpenAI Key in Key Vault

1. Azure Portal → `oai-peak10emaildev` → **Keys and Endpoint**
2. Copy **Key 1** and the **Endpoint**
3. Azure Portal → `kv-peak10emaildev` → **Secrets → Generate/Import**
   - **Name**: `azure-openai-key`
   - **Value**: Paste Key 1
4. Click **Create**

### Step 4.4 — Deploy the Function App Code

```bash
cd pillar2-email-intelligence
func azure functionapp publish func-peak10emaildev --python
```

### Step 4.5 — Set Up the Outlook Connector (Power Automate)

This connects your Outlook inbox to the triage Function:

1. Go to **Power Automate** (https://make.powerautomate.com)
2. Click **Create → Automated cloud flow**
3. **Flow name**: `Peak10 - Email Triage`
4. **Trigger**: "When a new email arrives (V3)" (Office 365 Outlook)
5. Configure the trigger:
   - **Folder**: Inbox
   - **Include Attachments**: Yes
   - **Only with Attachments**: No
6. Add action: **HTTP**
   - **Method**: POST
   - **URI**: `https://func-peak10emaildev.azurewebsites.net/api/email/triage`
   - **Headers**:
     - `Content-Type`: `application/json`
     - `x-functions-key`: `<your Pillar 2 function key>`
   - **Body**:
     ```json
     {
       "subject": "@{triggerOutputs()?['body/subject']}",
       "sender": "@{triggerOutputs()?['body/from']}",
       "sender_name": "@{triggerOutputs()?['body/from']}",
       "body_preview": "@{triggerOutputs()?['body/bodyPreview']}",
       "body_text": "@{triggerOutputs()?['body/body']}",
       "has_attachments": @{triggerOutputs()?['body/hasAttachments']},
       "attachment_names": @{triggerOutputs()?['body/attachments']}
     }
     ```
7. Add a **Condition** to check the triage response:
   - If `body('HTTP')?['triage']?['urgency']` is less than or equal to 2:
     - **Yes**: Add action → "Send me a mobile notification" with the summary
     - **No**: Continue (log or archive)
8. **Save** the flow
9. **Test** by sending yourself an email with subject "Invoice #TEST-001"

**Save this for Claude**:
```
Pillar 2 URL:           https://func-peak10emaildev.azurewebsites.net
Pillar 2 Key:           ___________________________
OpenAI Endpoint:        https://oai-peak10emaildev.openai.azure.com
OpenAI Deployment Name: gpt-4o-email
Power Automate Flow ID: ___________________________
```

---

## Phase 5: Deploy Pillar 4 — Expense Hub (45 minutes)

### Step 5.1 — Create a Strong SQL Password

Generate a password (at least 16 characters, mixed case, numbers, symbols). Save it:
```
SQL Admin Password: ___________________________
```

### Step 5.2 — Deploy Infrastructure

```bash
az deployment group create \
  --resource-group rg-peak10-dev \
  --template-file pillar4-expense-hub/infra/main.bicep \
  --parameters environment=dev sqlAdminPassword='<your-password>'
```

This additionally creates:
- Azure SQL Server: `sql-peak10expdev`
- Azure SQL Database: `db-expense-hub` (TDE-encrypted for the Chinese Wall)

### Step 5.3 — Store the SQL Connection String in Key Vault

1. Azure Portal → `sql-peak10expdev` → **Connection strings**
2. Copy the **ADO.NET** connection string
3. Replace `{your_password}` in the string with your actual password
4. Azure Portal → `kv-peak10expdev` → **Secrets → Generate/Import**
   - **Name**: `sql-connection-string`
   - **Value**: Paste the full connection string
5. Click **Create**

### Step 5.4 — Set Up Plaid

1. Go to https://dashboard.plaid.com and sign in (or create account)
2. In the **Dashboard → Keys** section, copy:
   ```
   Client ID:    ___________________________
   Sandbox Key:  ___________________________
   ```
3. **Important**: Start in **Sandbox** mode for testing. Switch to **Development** (and later **Production**) after validating.
4. Store Plaid credentials in Key Vault:
   - Azure Portal → `kv-peak10expdev` → Secrets:
     - **Name**: `plaid-client-id` → **Value**: Your client ID
     - **Name**: `plaid-secret` → **Value**: Your sandbox key
     - **Name**: `plaid-environment` → **Value**: `sandbox`

### Step 5.5 — Deploy the Function App Code

```bash
cd pillar4-expense-hub
func azure functionapp publish func-peak10expdev --python
```

### Step 5.6 — Create a Plaid Link Token (for Bank Connection)

This step connects your actual bank account(s). In sandbox, Plaid provides test accounts.

1. When Claude builds the frontend (next phase), it will include a Plaid Link button
2. For now, test via the Plaid Quickstart: https://plaid.com/docs/quickstart/
3. In sandbox, use credentials: `user_good` / `pass_good`

**Save this for Claude**:
```
Pillar 4 URL:          https://func-peak10expdev.azurewebsites.net
Pillar 4 Key:          ___________________________
SQL Server FQDN:       sql-peak10expdev.database.windows.net
SQL Database:          db-expense-hub
Plaid Client ID:       ___________________________
Plaid Environment:     sandbox
```

---

## Phase 6: Wire the Pillars Together (Hand Back to Claude)

Once all four pillars are deployed and you have collected the values above, give Claude the following configuration block. Claude will:

1. Add environment variables to each Function App for cross-pillar API calls
2. Build the Power Apps approval UI for Pillar 1
3. Add the Plaid SDK integration to Pillar 4
4. Wire the Azure OpenAI calls into Pillars 2 and 3
5. Deploy the inter-pillar event triggers (Azure Event Grid or direct HTTP)

**Copy and paste this template to Claude with your values filled in**:

```
Here are my deployed resource details. Please wire the pillars together.

AZURE TENANT:
  Tenant ID:       ___________________________
  Subscription ID: ___________________________
  Resource Group:  rg-peak10-dev

PILLAR 1 — AFA ENGINE:
  URL:  https://func-peak10afafdev.azurewebsites.net
  Key:  ___________________________

PILLAR 2 — EMAIL INTELLIGENCE:
  URL:  https://func-peak10emaildev.azurewebsites.net
  Key:  ___________________________
  OpenAI Endpoint:    https://oai-peak10emaildev.openai.azure.com
  OpenAI Deployment:  gpt-4o-email

PILLAR 3 — DOCUMENT AI:
  URL:  https://func-peak10docaidev.azurewebsites.net
  Key:  ___________________________
  Cognitive Endpoint: https://cog-peak10docaidev.cognitiveservices.azure.com
  SharePoint Site:    https://peak10energy.sharepoint.com/sites/Operations

PILLAR 4 — EXPENSE HUB:
  URL:  https://func-peak10expdev.azurewebsites.net
  Key:  ___________________________
  Plaid Client ID:    ___________________________
  Plaid Environment:  sandbox
```

---

## Phase 7: RBAC & Security Hardening (After Integration Testing)

### Step 7.1 — Define Roles in Entra ID

1. Azure Portal → **Microsoft Entra ID → Groups → New group**
2. Create three security groups:
   - `Peak10-Executives` — K. McQuire + any C-suite
   - `Peak10-Controllers` — Finance/AP team (AP approval access)
   - `Peak10-Employees` — All staff (expense submission access)
3. Add members to each group

### Step 7.2 — Apply RBAC to Function Apps

For each Function App, assign appropriate access:

| Group | Pillar 1 (AFA) | Pillar 2 (Email) | Pillar 3 (Doc AI) | Pillar 4 (Expense) |
|---|---|---|---|---|
| Executives | Full access | Full access | Full access | Own expenses only |
| Controllers | Approve/Export | View triage | File documents | Approve claims |
| Employees | No access | No access | Upload to staging | Submit expenses |

Claude will configure these as Azure Function-level auth policies when you hand back.

### Step 7.3 — Enable Diagnostic Logging

For each Function App:
1. Azure Portal → Function App → **Diagnostic settings → Add diagnostic setting**
2. **Name**: `logs-to-appinsights`
3. Check: **FunctionAppLogs**, **AppServiceHTTPLogs**
4. **Destination**: Send to Application Insights (already created)
5. Save

---

## Quick Reference: All Resources Created

| Resource | Pillar | Name (Dev) |
|---|---|---|
| Resource Group | All | `rg-peak10-dev` |
| Function App | 1 | `func-peak10afafdev` |
| Function App | 2 | `func-peak10emaildev` |
| Function App | 3 | `func-peak10docaidev` |
| Function App | 4 | `func-peak10expdev` |
| Storage Account | 1 | `stpeak10afafdev` |
| Storage Account | 2 | `stpeak10emaildev` |
| Storage Account | 3 | `stpeak10docaidev` |
| Storage Account | 4 | `stpeak10expdev` |
| App Insights | 1 | `ai-peak10afafdev` |
| App Insights | 2 | `ai-peak10emaildev` |
| App Insights | 3 | `ai-peak10docaidev` |
| App Insights | 4 | `ai-peak10expdev` |
| Key Vault | 1 | `kv-peak10afafdev` |
| Key Vault | 2 | `kv-peak10emaildev` |
| Key Vault | 3 | `kv-peak10docaidev` |
| Key Vault | 4 | `kv-peak10expdev` |
| Azure OpenAI | 2 | `oai-peak10emaildev` |
| Cognitive Services | 3 | `cog-peak10docaidev` |
| Azure SQL Server | 4 | `sql-peak10expdev` |
| Azure SQL Database | 4 | `db-expense-hub` |

---

## Estimated Total Time

| Phase | Time | Who |
|---|---|---|
| Phase 1: Azure Foundation | 30–45 min | You (portal) |
| Phase 2: Deploy Pillar 1 | 20 min | You (CLI) |
| Phase 3: Deploy Pillar 3 | 30 min | You (CLI + PowerShell + portal) |
| Phase 4: Deploy Pillar 2 | 30 min | You (CLI + portal + Power Automate) |
| Phase 5: Deploy Pillar 4 | 45 min | You (CLI + portal + Plaid) |
| Phase 6: Wire pillars | — | Claude (code) |
| Phase 7: RBAC & security | 20 min | You (portal) → Claude (code) |
| **Total your time** | **~3 hours** | |
