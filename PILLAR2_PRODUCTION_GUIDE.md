# Pillar 2 — Executive Communications Intelligence
## Full Production Build Guide

**Scope**: Take the email intelligence system from business logic prototype to production, including merging document classification and SharePoint filing (formerly Pillar 3) into the email pipeline.

**End State**: Emails arrive in your Outlook inbox → automatically triaged by urgency and category → attachments classified and filed to governed SharePoint folders → invoices routed to Pillar 1 AP queue → receipts routed to Pillar 4 expense hub → AI-drafted replies queued for your review → all decisions logged and learnable.

**SxS** = Step-by-Step (used throughout this document to denote detailed walkthrough instructions)

---

## Table of Contents

1. [Pre-Flight: What You Need Before We Start](#pre-flight)
   - [Licenses & Subscriptions (SxS)](#licenses-sxs)
   - [Permissions Required (SxS)](#permissions-sxs)
   - [Software to Install Locally (SxS)](#software-sxs)
   - [Pre-Flight Checklist](#preflight-checklist)
2. [Layer 1: Database — Cosmos DB Persistence](#layer-1) ✅ DELIVERED
3. [Layer 2: Azure OpenAI — Real AI Classification & Drafting](#layer-2) ✅ DELIVERED
4. [Layer 3: Microsoft Graph — Outlook Email Ingestion](#layer-3)
5. [Layer 4: Azure Document Intelligence — Text Extraction](#layer-4) ✅ DELIVERED
6. [Layer 5: Classification & Filing Merge from Pillar 3](#layer-5) ✅ DELIVERED
7. [Layer 6: Microsoft Graph — SharePoint File Operations](#layer-6)
8. [Layer 7: Draft Response Review Flow](#layer-7) ✅ DELIVERED
9. [Layer 8: Production Hardening](#layer-8)
10. [Validation Checklist](#validation)

---

<a name="pre-flight"></a>
## Pre-Flight: What You Need Before We Start

<a name="licenses-sxs"></a>
### Licenses & Subscriptions — Step-by-Step (SxS)

#### 1. Azure Subscription (Owner or Contributor role)

**What it is**: The Azure subscription is the billing container for all cloud resources (Function Apps, Cosmos DB, OpenAI, etc.). You need Owner or Contributor role to deploy resources.

**How to confirm you have it:**
1. Open a browser and go to https://portal.azure.com
2. Sign in with your work Microsoft account (e.g., `kmcquire@peak10energy.com`)
3. In the top search bar, type **"Subscriptions"** and click the result
4. You should see at least one subscription listed (e.g., "Peak 10 Energy - Production" or "Pay-As-You-Go")
5. Click on the subscription name → click **"Access control (IAM)"** in the left menu
6. Click **"View my access"** — you should see **Owner** or **Contributor** listed

**If you don't have it:**
1. If you see no subscriptions: Go to https://azure.microsoft.com/free and create one. You get $200 free credit for 30 days. Use your work email.
2. If you see a subscription but don't have Owner/Contributor:
   - Contact whoever set up your Azure tenant (likely your IT admin or the person who originally created the Azure account)
   - Ask them to go to: Subscription → Access control (IAM) → Add role assignment → Role: **Contributor** → Members: search for your email → Review + assign
3. **Cost**: Pay-as-you-go subscription has no fixed cost — you only pay for resources you deploy. Dev costs for this pillar are ~$30-80/month.

**Verification command** (if Azure CLI is installed):
```bash
az account show --query "{Name:name, State:state, Role:user.type}" -o table
```

---

#### 2. Microsoft 365 Business Premium

**What it is**: Your M365 license provides Outlook (email), SharePoint (document storage), and Microsoft Graph API access. Without it, the email pipeline has no mailbox to read and no SharePoint to file documents into.

**How to confirm you have it:**
1. Go to https://admin.microsoft.com (sign in with your work account)
2. Click **"Users" → "Active users"** in the left sidebar
3. Find your account and click on it
4. Click the **"Licenses and apps"** tab
5. You should see **Microsoft 365 Business Premium** (or E3/E5) checked

**If you don't have it:**
1. If you're the admin: Go to https://admin.microsoft.com → **Billing → Purchase services** → search "Microsoft 365 Business Premium" → Buy
2. If someone else is admin: Ask your IT admin to assign you a license
3. **Cost**: ~$22/user/month for Business Premium
4. **Alternative**: Microsoft 365 E3 ($36/user/month) or E5 ($57/user/month) also work — they include everything Business Premium has plus more

**What to check for specifically:**
- Outlook is accessible at https://outlook.office.com
- SharePoint is accessible at `https://[yourtenant].sharepoint.com`
- You can send and receive email from the mailbox you want to monitor

---

#### 3. Azure OpenAI Access

**What it is**: Azure OpenAI is a gated service — Microsoft requires an application before you can use GPT-4o models. This is separate from having a regular Azure subscription.

**How to confirm you have it:**
1. Go to https://portal.azure.com
2. In the top search bar, type **"Azure OpenAI"** and click the result
3. Look at what you see:
   - **If you see a "Create" button**: You have access. Proceed.
   - **If you see a "Request Access" button**: You do NOT have access yet. You need to apply.

**If you need to request access:**
1. Go to https://aka.ms/oai/access
2. Fill out the form:
   - **Subscription ID**: Copy from Azure Portal → Subscriptions → your subscription → Overview → Subscription ID
   - **Company name**: Peak 10 Energy LLC
   - **Use case**: "Enterprise email automation — classify emails, generate draft responses, classify document attachments for an oil and gas company"
   - **Company email**: Use your work email, not a personal one
3. Submit the form
4. **Wait time**: Typically 1-5 business days. You'll get an email when approved.
5. **Check status**: Go back to Azure Portal → search "Azure OpenAI" → if "Create" button appears, you're approved

**IMPORTANT**: This is the single biggest blocker in the pre-flight. Submit this request first, then work on everything else while you wait.

---

#### 4. GitHub Repository Access

**What it is**: Admin access to the `kdmcquire-creator/Peak10-enterprise-automation` repository, needed to set GitHub Actions secrets for CI/CD deployment.

**How to confirm you have it:**
1. Go to https://github.com/kdmcquire-creator/Peak10-enterprise-automation
2. Click **"Settings"** tab at the top of the repo
3. If you can see Settings and navigate to it, you have admin access
4. If there's no Settings tab visible, you need admin access

**If you don't have it:**
- If you're the repo owner (`kdmcquire-creator`), you already have admin access
- If you need to add someone else: Settings → Collaborators and teams → Add people → select "Admin" role

---

#### Cost Summary

| Service | Dev Cost/Month | What It Does |
|---|---|---|
| Azure Function App (Consumption) | Free tier | Runs the email pipeline |
| Azure Cosmos DB (Serverless) | ~$5-15 | Stores triage results, documents, corrections |
| Azure OpenAI (GPT-4o) | ~$5-50 | Email triage, document classification, draft replies |
| Azure AI Document Intelligence | ~$1-10 | Extracts text from PDF/image attachments |
| Storage Account | ~$1 | Blob staging for attachments |
| Key Vault | ~$0.50 | Secrets management |
| Application Insights | Free | Monitoring (5GB/mo included) |
| **Total** | **~$12-77/mo** | |

---

<a name="permissions-sxs"></a>
### Permissions Required — Step-by-Step (SxS)

#### 1. Azure Subscription: Owner or Contributor

**What it controls**: Deploying all Azure resources (Function App, Cosmos DB, OpenAI, Key Vault, etc.)

**SxS to confirm:**
1. Azure Portal → search **"Subscriptions"**
2. Click your subscription
3. Left sidebar → **Access control (IAM)**
4. Click **"View my access"** button
5. Look for **Owner** or **Contributor** in the Role column

**SxS to obtain (if you're the tenant admin):**
1. Azure Portal → Subscriptions → your subscription
2. Access control (IAM) → **+ Add** → **Add role assignment**
3. Role tab: Select **Contributor**
4. Members tab: Click **+ Select members** → search for the user's email → select → click **Select**
5. Review + assign → **Review + assign** (click twice)

**SxS to obtain (if someone else is admin):**
Send them this message:
> "Please add me as a Contributor on our Azure subscription. Go to Azure Portal → Subscriptions → [subscription name] → Access control (IAM) → Add role assignment → Contributor → add my email [your email]."

---

#### 2. Microsoft Entra ID: Application Administrator

**What it controls**: Creating an App Registration for Microsoft Graph API (needed to read email and write to SharePoint programmatically)

**SxS to confirm:**
1. Azure Portal → search **"Microsoft Entra ID"** (formerly Azure Active Directory)
2. Left sidebar → **Roles and administrators**
3. Search for **"Application Administrator"**
4. Click it → check if your account is listed as an assignment

**SxS to obtain:**
1. An existing **Global Administrator** must assign this
2. Ask them to: Entra ID → Roles and administrators → Application Administrator → **+ Add assignments** → search for your email → **Add**
3. Or ask the Global Admin to create the App Registration for you (Layer 3 instructions)

**Alternative**: If you are a Global Administrator, you already have this permission implicitly.

---

#### 3. SharePoint Administrator

**What it controls**: Running the `provision_sharepoint.ps1` script to create the 50+ governed folders, and granting Graph API permission to read/write SharePoint.

**SxS to confirm:**
1. Go to https://admin.microsoft.com
2. Left sidebar → **Roles** → **Role assignments**
3. Search for **"SharePoint Administrator"** (or "SharePoint admin")
4. Click it → check if your account is in the assigned users list

**SxS to obtain:**
1. You need a **Global Administrator** to assign this
2. Ask them to: M365 Admin Center → Roles → SharePoint Administrator → **Assigned** tab → **+ Add** → search for your email → **Add**

**Alternative**: Global Administrators have SharePoint admin rights implicitly.

---

#### 4. Exchange Administrator

**What it controls**: Granting Graph API permission to read the monitored mailbox. Required for admin consent on `Mail.Read`, `Mail.ReadWrite`, `Mail.Send`.

**SxS to confirm:**
1. Go to https://admin.microsoft.com
2. Left sidebar → **Roles** → **Role assignments**
3. Search for **"Exchange Administrator"**
4. Click it → check if your account is listed

**SxS to obtain:**
1. Global Administrator assigns this: M365 Admin Center → Roles → Exchange Administrator → Assigned → + Add → your email
2. Or have the Global Admin grant the Graph API permissions directly (they can do it from Entra ID → App registrations → your app → API permissions → Grant admin consent)

---

#### 5. GitHub Repository Admin

**What it controls**: Setting GitHub Actions repository secrets (Azure deployment credentials for CI/CD)

**SxS to confirm:**
1. Go to https://github.com/kdmcquire-creator/Peak10-enterprise-automation
2. Click **Settings** tab
3. If visible, you have admin access
4. Click **Secrets and variables → Actions** in the left sidebar
5. If you can add/edit secrets, you're confirmed

**SxS to obtain:**
- If you own the repo, you have it automatically
- To add someone: Settings → Collaborators and teams → Add people → Role: **Admin**

---

#### 6. Power Platform Environment Maker (OPTIONAL)

**What it controls**: Only needed if you choose to use Power Automate for email triggers instead of Graph webhooks. We recommend Graph webhooks (no extra license needed).

**SxS to confirm:**
1. Go to https://admin.powerplatform.microsoft.com
2. If you can see Environments and create one, you have access

**SxS to skip:**
- This is optional. The pipeline uses Microsoft Graph webhooks for email notifications, which requires no Power Platform license.

---

<a name="software-sxs"></a>
### Software to Install Locally — Step-by-Step (SxS)

**Shortcut**: Use Azure Cloud Shell (https://shell.azure.com) — it has Azure CLI, PowerShell 7, and Python pre-installed. You'd only need to install PnP.PowerShell. Skip the rest of this section if using Cloud Shell.

#### 1. Azure CLI 2.50+

**What it is**: Command-line tool for managing Azure resources. Used to deploy Bicep templates, manage secrets, and authenticate.

**SxS to install:**

*macOS:*
```bash
brew update
brew install azure-cli
```

*Windows:*
```powershell
winget install Microsoft.AzureCLI
```
Or download the MSI installer from https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows

*Linux:*
```bash
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
```

**SxS to verify:**
```bash
az --version
```
You should see `azure-cli 2.50.0` or higher in the output.

**SxS to sign in:**
```bash
az login
```
A browser window opens. Sign in with your work Microsoft account. After successful login, you'll see your subscription details in the terminal.

**SxS to set your subscription:**
```bash
az account list -o table
az account set --subscription "YOUR_SUBSCRIPTION_NAME_OR_ID"
```

---

#### 2. Azure Functions Core Tools v4

**What it is**: Lets you run and test Azure Functions locally before deploying to the cloud.

**SxS to install:**

*macOS:*
```bash
brew tap azure/functions
brew install azure-functions-core-tools@4
```

*Windows:*
```powershell
winget install Microsoft.Azure.FunctionsCoreTools
```
Or download from https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local

*Linux (Ubuntu/Debian):*
```bash
curl https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > microsoft.gpg
sudo mv microsoft.gpg /etc/apt/trusted.gpg.d/microsoft.gpg
sudo sh -c 'echo "deb [arch=amd64] https://packages.microsoft.com/repos/microsoft-ubuntu-$(lsb_release -cs)-prod $(lsb_release -cs) main" > /etc/apt/sources.list.d/dotnetdev.list'
sudo apt-get update
sudo apt-get install azure-functions-core-tools-4
```

**SxS to verify:**
```bash
func --version
```
You should see `4.x.x` (e.g., `4.0.5571`).

---

#### 3. PowerShell 7+

**What it is**: Required to run the SharePoint folder provisioning script (`provision_sharepoint.ps1`).

**SxS to install:**

*macOS:*
```bash
brew install powershell/tap/powershell
```

*Windows:*
PowerShell 7 may already be installed. Check first:
```powershell
pwsh --version
```
If not installed:
```powershell
winget install Microsoft.PowerShell
```

*Linux (Ubuntu):*
```bash
sudo apt-get install -y powershell
```

**SxS to verify:**
```bash
pwsh --version
```
You should see `PowerShell 7.x.x`.

---

#### 4. PnP.PowerShell Module

**What it is**: PowerShell module for SharePoint Online management. Used by the folder provisioning script to create all 50+ governed folders.

**SxS to install:**
```powershell
pwsh -Command "Install-Module PnP.PowerShell -Scope CurrentUser -Force -AllowClobber"
```

**SxS to verify:**
```powershell
pwsh -Command "Get-Module PnP.PowerShell -ListAvailable"
```
You should see a version number (e.g., `2.4.0`).

**SxS to test connectivity:**
```powershell
pwsh -Command "Connect-PnPOnline -Url 'https://peak10energy.sharepoint.com/sites/Operations' -Interactive"
```
A browser window opens for authentication. After signing in, if you return to the terminal without errors, connectivity is confirmed.

---

<a name="preflight-checklist"></a>
### Pre-Flight Checklist

Run through this before we begin. Every box must be checked.

- [ ] Azure subscription active, you can log into https://portal.azure.com
- [ ] You have Owner or Contributor on the subscription (`az account show` works)
- [ ] Azure OpenAI access confirmed (you see a "Create" button, not "Request Access")
- [ ] M365 tenant active with Outlook (https://outlook.office.com loads your mailbox)
- [ ] SharePoint accessible (`https://[yourtenant].sharepoint.com` loads)
- [ ] Azure CLI installed (`az --version` → 2.50+)
- [ ] Azure CLI signed in (`az login` completed successfully)
- [ ] Functions Core Tools installed (`func --version` → 4.x)
- [ ] PowerShell 7 installed (`pwsh --version` → 7.x)
- [ ] PnP.PowerShell module installed (`Get-Module PnP.PowerShell -ListAvailable` shows version)
- [ ] GitHub repo admin access confirmed (can see Settings tab)
- [ ] You know your SharePoint site URL (e.g., `https://peak10energy.sharepoint.com/sites/Operations`)
- [ ] You know which Outlook mailbox to monitor (e.g., `kmcquire@peak10energy.com`)

**Once all checked, tell Claude "Pre-flight complete" and provide:**
```
SharePoint Site URL:    ___________________________
Mailbox to monitor:     ___________________________
Azure Subscription ID:  ___________________________
```

### Current Code Handoff Checklist

The current backend is already prepared to use these settings once tenant access is available. Please collect or confirm all of them before the final live validation pass:

- Graph app registration client ID
- Graph client secret
- Graph tenant ID
- Mailbox address to monitor
- SharePoint site ID
- SharePoint drive ID
- Azure OpenAI endpoint and deployment name
- Confirmation that `azure-openai-key`, `cognitive-services-key`, `graph-client-id`, `graph-client-secret`, `graph-tenant-id`, `graph-mailbox-address`, `graph-sharepoint-site-id`, and `graph-sharepoint-drive-id` exist in Key Vault

Mailbox polling settings now supported by the deployed code:

- `MAILBOX_POLL_ENABLED` — `true` or `false`
- `MAILBOX_POLL_SCHEDULE` — NCRONTAB schedule, default `0 */1 * * * *`
- `MAILBOX_POLL_TOP` — max unread messages per poll, default `10`
- `MAILBOX_MARK_PROCESSED` — mark processed emails as read/category-tagged, default `true`

---

<a name="layer-1"></a>
## Layer 1: Database — Cosmos DB Persistence ✅ DELIVERED

**Goal**: Replace all in-memory `dict` stores with durable Cosmos DB persistence so nothing is lost on Function App restart.

### What Was Built

| Deliverable | File | Status |
|---|---|---|
| Cosmos DB data access layer | `email_intel/cosmos_client.py` | ✅ Complete |
| In-memory fallback for dev/testing | Built into `cosmos_client.py` | ✅ Complete |
| 4 containers: `triage_results`, `draft_responses`, `documents`, `corrections` | Partition keys configured | ✅ Complete |
| Cosmos DB Bicep resource | `infra/main.bicep` | ✅ Complete |
| Serverless mode for dev | Bicep conditional | ✅ Complete |
| TTL policies | 90 days triage, 30 days drafts | ✅ Complete |
| Full CRUD operations | Save, get, query, delete for all containers | ✅ Complete |
| Unit tests | `tests/test_cosmos_client.py` — 13 tests passing | ✅ Complete |

### Your Work (Azure Portal — Deploy Infrastructure)

**SxS to deploy via Bicep (fastest path):**
1. Open a terminal (or Azure Cloud Shell)
2. Navigate to the repo:
   ```bash
   cd Peak10-enterprise-automation/pillar2-email-intelligence/infra
   ```
3. Create a resource group (if you don't have one):
   ```bash
   az group create --name rg-peak10-email-dev --location southcentralus
   ```
4. Deploy the Bicep template:
   ```bash
   az deployment group create \
     --resource-group rg-peak10-email-dev \
     --template-file main.bicep \
     --parameters environment=dev baseName=peak10email
   ```
5. Wait for deployment (~5-10 minutes). The template provisions:
   - Cosmos DB account (serverless) + database + 4 containers
   - Azure OpenAI resource
   - Document Intelligence (Form Recognizer)
   - Function App + Storage + App Insights + Key Vault
6. After deployment, store the Cosmos DB connection string in Key Vault:
   ```bash
   # Get the Cosmos DB connection string
   COSMOS_CONN=$(az cosmosdb keys list \
     --name cosmos-peak10emaildev \
     --resource-group rg-peak10-email-dev \
     --type connection-strings \
     --query "connectionStrings[0].connectionString" -o tsv)

   # Store it in Key Vault
   az keyvault secret set \
     --vault-name kv-peak10emaildev \
     --name cosmos-connection-string \
     --value "$COSMOS_CONN"
   ```

**SxS to deploy manually (if you prefer portal):**
1. Azure Portal → search **"Azure Cosmos DB"** → **Create** → **Azure Cosmos DB for NoSQL**
2. Settings:
   - Subscription: your subscription
   - Resource group: `rg-peak10-email-dev` (create new if needed)
   - Account name: `cosmos-peak10emaildev`
   - Location: South Central US (or your preferred region)
   - Capacity mode: **Serverless**
3. Click **Review + Create → Create**
4. After creation, go to the resource → **Data Explorer**
5. Click **New Database** → ID: `peak10-email-intelligence`
6. Inside the database, create 4 containers:
   - `triage_results` — partition key: `/partition_date`
   - `draft_responses` — partition key: `/message_id`
   - `documents` — partition key: `/document_id`
   - `corrections` — partition key: `/original_type`
7. Go to **Keys** → copy the **Primary Connection String**
8. Go to your Key Vault → **Secrets → Generate/Import** → Name: `cosmos-connection-string`, Value: paste the connection string

---

<a name="layer-2"></a>
## Layer 2: Azure OpenAI — Real AI Classification & Drafting ✅ DELIVERED

**Goal**: Replace the pass-through `ai_response` parameter with actual Azure OpenAI SDK calls.

### What Was Built

| Deliverable | File | Status |
|---|---|---|
| Azure OpenAI SDK client wrapper | `email_intel/openai_client.py` | ✅ Complete |
| Retry with exponential backoff (3 attempts) | Built-in | ✅ Complete |
| Token usage and cost tracking | `UsageRecord` with per-call logging | ✅ Complete |
| Graceful fallback when unconfigured | Returns None, triage uses rules only | ✅ Complete |
| Email triage integration | `function_app.py` auto-calls OpenAI when rule confidence < 0.85 | ✅ Complete |
| Document classification integration | `function_app.py` classify endpoint calls OpenAI for low-confidence items | ✅ Complete |
| Draft reply generation | `generate_draft_reply()` with tone selection | ✅ Complete |
| Managed identity support | `AZURE_OPENAI_USE_MI=true` option | ✅ Complete |
| JSON response format enforcement | `response_format={"type": "json_object"}` | ✅ Complete |
| Unit tests (offline) | `tests/test_openai_client.py` — 6 tests passing | ✅ Complete |

### Your Work (Azure Portal — Deploy Model & Store Key)

**SxS to deploy the GPT-4o model:**
1. Azure Portal → search **"Azure OpenAI"** → click your resource (`oai-peak10emaildev`)
   - If no resource exists and Bicep hasn't been deployed, create one: Azure OpenAI → Create → fill in details (S0 tier, South Central US)
2. Click **"Model deployments"** in the left sidebar → **"Manage Deployments"** (opens Azure OpenAI Studio)
3. Click **"+ Create new deployment"**
4. Settings:
   - Model: **gpt-4o**
   - Deployment name: **`gpt-4o`** (must match this exactly — it's referenced in the code as the default)
   - Deployment type: Standard
   - Tokens per minute rate limit: **30K** (sufficient; can increase later)
5. Click **Deploy**
6. Wait for status to show **"Succeeded"**

**SxS to store the API key:**
1. Go back to your Azure OpenAI resource in the portal
2. Left sidebar → **Keys and Endpoint**
3. Copy **Key 1** and note the **Endpoint** URL (e.g., `https://oai-peak10emaildev.openai.azure.com/`)
4. Go to Azure Portal → your Key Vault (`kv-peak10emaildev`)
5. Left sidebar → **Secrets** → **+ Generate/Import**
6. Create the secret:
   - Name: `azure-openai-key`
   - Value: paste Key 1
7. Click **Create**

**Give Claude these values when done:**
```
OpenAI Endpoint:         ___________________________
OpenAI Deployment Name:  gpt-4o (or what you chose)
Key stored in Key Vault: yes
```

---

<a name="layer-3"></a>
## Layer 3: Microsoft Graph — Outlook Email Ingestion

**Goal**: Automatically pull new emails from your Outlook inbox into the triage pipeline.

### Your Work (20 minutes)

**SxS to create an App Registration:**
1. Azure Portal → search **"Microsoft Entra ID"** → click it
2. Left sidebar → **App registrations** → **+ New registration**
3. Fill in:
   - Name: **`peak10-email-pipeline`**
   - Supported account types: **Accounts in this organizational directory only** (Single tenant)
   - Redirect URI: Leave blank
4. Click **Register**
5. On the Overview page, copy and save:
   ```
   Application (client) ID:  ___________________________
   Directory (tenant) ID:    ___________________________
   ```

**SxS to create a client secret:**
1. In your app registration, left sidebar → **Certificates & secrets**
2. Click **+ New client secret**
3. Description: `graph-api`
4. Expires: **24 months**
5. Click **Add**
6. **IMMEDIATELY copy the Value** (it will only be shown once):
   ```
   Client secret:            ___________________________
   ```

**SxS to grant API permissions:**
1. Left sidebar → **API permissions**
2. Click **+ Add a permission** → **Microsoft Graph** → **Application permissions**
3. Search and check each of these:
   - `Mail.Read` — Read emails from the monitored mailbox
   - `Mail.ReadWrite` — Move emails, mark as read after processing
   - `Mail.Send` — Send approved draft replies
   - `Files.ReadWrite.All` — Upload/move files in SharePoint
   - `Sites.ReadWrite.All` — Create folders, manage SharePoint metadata
4. Click **Add permissions**
5. Back on the API permissions page, click **"Grant admin consent for [your tenant name]"**
   - You need Application Administrator or Global Administrator role for this
   - A dialog asks "Do you want to grant consent?" → click **Yes**
6. Verify: All 5 permissions now show a **green checkmark** under the "Status" column

**SxS to store credentials in Key Vault:**
1. Azure Portal → your Key Vault → left sidebar → **Secrets**
2. Create each of these secrets (click **+ Generate/Import** for each):
   - Name: `graph-client-id` → Value: the Application (client) ID
   - Name: `graph-client-secret` → Value: the client secret you copied
   - Name: `graph-tenant-id` → Value: the Directory (tenant) ID
   - Name: `graph-mailbox-address` → Value: the email address to monitor (e.g., `kmcquire@peak10energy.com`)

**Give Claude confirmation when done:**
```
App Registration created: yes/no
Admin consent granted:    yes/no
Key Vault secrets stored: graph-client-id, graph-client-secret, graph-tenant-id, graph-mailbox-address
```

### Claude's Work

| Task | Details |
|---|---|
| Add `msgraph-sdk` to requirements | Microsoft Graph Python SDK |
| Build Graph auth client | Client credentials flow using Key Vault secrets |
| Build email ingestion service | Poll mailbox every 60 seconds (configurable), fetch new unread messages with attachments |
| Build attachment downloader | Download attachments to blob staging container |
| Wire into triage pipeline | New email → rule-based triage → AI triage if needed → persist to Cosmos DB |
| Build subscription webhook (upgrade) | Replace polling with Graph change notifications for near-real-time |
| Handle pagination | Large mailboxes, batch processing, delta queries |
| Mark processed emails | Move to processed folder or add category tag in Outlook |
| Write tests | Mock Graph responses, verify email parsing, test attachment handling |

### Deliverable

Emails are automatically pulled from your Outlook inbox, triaged, and persisted. Attachments are downloaded to blob storage for classification in Layer 5.

---

<a name="layer-4"></a>
## Layer 4: Azure Document Intelligence — Text Extraction ✅ DELIVERED

**Goal**: Extract readable text from PDF, Word, and image attachments so the classifier has content to work with.

### What Was Built

| Deliverable | File | Status |
|---|---|---|
| Document Intelligence SDK client | `email_intel/doc_intelligence.py` | ✅ Complete |
| `prebuilt-read` model for general text extraction | `extract_text()` method | ✅ Complete |
| `prebuilt-invoice` model for structured invoice data | `extract_invoice()` method | ✅ Complete |
| `prebuilt-receipt` model for receipt extraction | `extract_receipt()` method | ✅ Complete |
| Key-value pair extraction | Vendor, dates, amounts, reference numbers | ✅ Complete |
| Graceful fallback when unconfigured | Returns empty ExtractionResult | ✅ Complete |
| Document Intelligence in Bicep template | `infra/main.bicep` — Form Recognizer S0 | ✅ Complete |
| Unit tests (offline) | `tests/test_doc_intelligence.py` — 5 tests passing | ✅ Complete |

### Your Work (Azure Portal — Store Key)

**SxS to get and store the Document Intelligence key:**
1. Azure Portal → search **"Document Intelligence"** (or "Form Recognizer") → click your resource (`di-peak10emaildev`)
   - If the resource was deployed via Bicep, it already exists
   - If not: Create one → Name: `di-peak10emaildev`, Region: South Central US, Pricing tier: S0
2. Left sidebar → **Keys and Endpoint**
3. Copy **Key 1** and note the **Endpoint** URL
4. Go to your Key Vault → **Secrets → + Generate/Import**
5. Create secret:
   - Name: `cognitive-services-key`
   - Value: paste Key 1
6. Click **Create**

**Give Claude:**
```
Document Intelligence Endpoint: ___________________________
Key stored in Key Vault:         yes
```

---

<a name="layer-5"></a>
## Layer 5: Classification & Filing Merge from Pillar 3 ✅ DELIVERED

**Goal**: Move document classification, auto-naming, and filing recommendation logic from the standalone Pillar 3 into the email pipeline.

### What Was Built

| Deliverable | File | Status |
|---|---|---|
| Two-tier classification engine | `email_intel/classifier.py` | ✅ Complete |
| 30+ filename rules, 10+ content rules | Specific types before generic patterns | ✅ Complete |
| AI classification fallback | `build_classification_prompt()` + `parse_ai_classification()` | ✅ Complete |
| Auto-naming engine | `email_intel/naming.py` — `YYYY-MM-DD_Type_Identifier.ext` | ✅ Complete |
| Filing recommendation engine | `recommend_filing()` → governed SharePoint path | ✅ Complete |
| Correction logging / continuous learning | `email_intel/corrections.py` | ✅ Complete |
| Document models (27 types, 50+ folder hierarchy) | `email_intel/document_models.py` | ✅ Complete |
| POST /api/documents/classify endpoint | `function_app.py` | ✅ Complete |
| POST /api/documents/correct endpoint | `function_app.py` | ✅ Complete |
| Cosmos DB persistence for classifications + corrections | Wired to `cosmos_client.py` | ✅ Complete |
| Unit tests | `tests/test_classifier.py` (21), `test_naming.py` (8), `test_corrections.py` (5) — 34 tests | ✅ Complete |

### Your Work

None. This layer was built entirely by Claude.

---

<a name="layer-6"></a>
## Layer 6: Microsoft Graph — SharePoint File Operations

**Goal**: Actually move classified files from blob staging into the governed SharePoint folder hierarchy.

### Your Work (15 minutes)

**SxS to provision SharePoint folders:**
1. Open PowerShell 7:
   ```bash
   pwsh
   ```
2. Navigate to the script directory:
   ```powershell
   cd Peak10-enterprise-automation/pillar3-document-ai/scripts
   ```
3. Run the provisioning script:
   ```powershell
   ./provision_sharepoint.ps1 -SiteUrl "https://peak10energy.sharepoint.com/sites/Operations"
   ```
4. A browser window opens — authenticate with your work account
5. The script creates all 50+ folders. Watch the output for any errors.
6. Verify in SharePoint:
   - Go to `https://peak10energy.sharepoint.com/sites/Operations/Shared Documents`
   - You should see: `00_STAGING`, `01_CORPORATE`, `02_OPERATIONS`, `03_DEALS`, `04_GOVERNANCE`
   - Click into each to verify sub-folders exist

**SxS to get your SharePoint Site ID:**

*Option A — Browser:*
1. Navigate to: `https://peak10energy.sharepoint.com/sites/Operations/_api/site/id`
2. The page shows XML — the GUID inside `<d:Id>` tags is your Site ID
3. Copy it

*Option B — Azure CLI (after Graph app registration from Layer 3):*
```bash
# Claude will look this up automatically using the Graph API credentials
```

**Give Claude:**
```
SharePoint folders provisioned: yes/no
SharePoint Site URL:            https://peak10energy.sharepoint.com/sites/Operations
SharePoint Site ID:             ___________________________ (if you looked it up)
```

### Claude's Work

| Task | Details |
|---|---|
| Build SharePoint Graph client | Upload files, create folders, set metadata via Microsoft Graph |
| Build filing execution service | Take filing recommendation → upload to recommended path with standardized name |
| Handle conflicts | Duplicate filenames, locked files, permission errors |
| Build auto-file for high confidence | If classification confidence ≥ 0.85, file automatically without review |
| Build staging queue for low confidence | If confidence < 0.85, park in `00_STAGING/Inbox` and flag for review |
| Set SharePoint metadata | Document type, original sender, received date, classification confidence |
| Wire into email pipeline | Email processed → attachments classified → high-confidence auto-filed, low-confidence staged |
| Write tests | Mock Graph file operations, verify path resolution, test conflict handling |

### Deliverable

Classified attachments are automatically filed to the correct SharePoint folder with standardized names. Low-confidence documents are staged for your manual review.

---

<a name="layer-7"></a>
## Layer 7: Draft Response Review Flow ✅ DELIVERED

**Goal**: AI-drafted email replies are stored and retrievable so you can review, edit, and send them.

### What Was Built

| Deliverable | File | Status |
|---|---|---|
| POST /api/email/draft-reply | Generate + save a draft | ✅ Complete |
| GET /api/email/drafts/{message_id} | List all drafts for an email | ✅ Complete |
| PUT /api/email/drafts/{draft_id} | Edit, approve, change tone | ✅ Complete |
| DELETE /api/email/drafts/{draft_id} | Remove a draft | ✅ Complete |
| Cosmos DB persistence for drafts | `draft_responses` container | ✅ Complete |
| Azure OpenAI draft generation | Tone selection (professional/brief/warm) | ✅ Complete |
| Approval workflow | `approved` flag + `approved_at` timestamp | ✅ Complete |
| Draft lifecycle tracking | needs_review flag auto-managed | ✅ Complete |

### Your Work

None for the API layer. Send-via-Graph (actually sending approved drafts from your mailbox) will be wired in Layer 3 once the Graph credentials are configured.

---

<a name="layer-8"></a>
## Layer 8: Production Hardening

**Goal**: Make the system reliable, observable, and secure.

### Your Work (20 minutes)

**SxS to enable diagnostic logging:**
1. Azure Portal → your Function App (`func-peak10emaildev`)
2. Left sidebar → **Diagnostic settings**
3. Click **+ Add diagnostic setting**
4. Settings:
   - Diagnostic setting name: `email-pipeline-logs`
   - Check: **FunctionAppLogs**
   - Check: **AppServiceHTTPLogs**
   - Check: **AppServiceConsoleLogs**
   - Send to: **Log Analytics workspace** → select your Application Insights workspace (or create one)
5. Click **Save**

**SxS to set up failure alerts:**
1. Azure Portal → your Application Insights resource (`ai-peak10emaildev`)
2. Left sidebar → **Alerts** → **+ Create → Alert rule**
3. Condition:
   - Signal: **Failed requests**
   - Threshold: Greater than **5**
   - Aggregation: Count
   - Evaluation period: **5 minutes**
4. Actions → **+ Create action group**:
   - Action group name: `peak10-email-alerts`
   - Notification type: **Email/SMS/Push/Voice**
   - Email: your email address
5. Details:
   - Alert rule name: `Email Pipeline Failures`
   - Severity: **2 - Warning**
6. Click **Review + Create → Create**

**SxS to review Key Vault access:**
1. Azure Portal → your Key Vault → left sidebar → **Access control (IAM)**
2. Click **Role assignments** tab
3. Verify only these identities have access:
   - Your admin account (Owner/Contributor)
   - The Function App managed identity (Key Vault Secrets User)
4. Remove any entries you don't recognize (click the entry → **Remove**)

### Claude's Work

| Task | Details |
|---|---|
| Add retry logic everywhere | Exponential backoff for Graph, OpenAI, Document Intelligence, Cosmos DB |
| Build dead letter queue | Failed classifications → blob container `dead-letter` with error details |
| Add circuit breaker | If OpenAI fails 5x in a row, fall back to rule-based-only mode and alert |
| Rate limiting | Cap OpenAI calls to budget (configurable tokens/day) |
| Structured logging | Consistent JSON log format, correlation IDs across the pipeline |
| Health check upgrade | `/api/health` verifies all downstream dependencies |
| Auth hardening | Validate Function key on all endpoints, add IP allowlisting option |
| Cost tracking | Log estimated OpenAI spend per email, daily summary |
| Write integration tests | End-to-end: mock email in → verify triage + classification + filing + draft |

### Deliverable

Production-grade reliability. Failures are retried, dead-lettered, and alerted on. Costs are tracked. The system degrades gracefully if any dependency is down.

---

<a name="validation"></a>
## Final Validation Checklist

Run through this after all 8 layers are complete:

### Automated Pipeline
- [ ] Send a test email with subject "Invoice #TEST-001" and a PDF attachment
- [ ] Verify: email is triaged as `vendor_ap` with urgency `STANDARD`
- [ ] Verify: PDF attachment is text-extracted, classified as `invoice`
- [ ] Verify: attachment is filed to `01_CORPORATE/Finance/AP/` with standardized name
- [ ] Verify: triage result persists in Cosmos DB (survives Function App restart)

### Deal Signal Detection
- [ ] Send email with subject "RE: Letter of Intent - Loving County" and body mentioning "data room access"
- [ ] Verify: triaged as `deal_related`, urgency `HIGH`
- [ ] Verify: deal signals detected: `loi_discussion`, `due_diligence`
- [ ] Verify: AI draft reply generated and stored

### Receipt Routing
- [ ] Send email with subject "Your Uber receipt" and a receipt PDF
- [ ] Verify: triaged as `receipt`, urgency `LOW`
- [ ] Verify: attachment classified as `receipt`
- [ ] Verify: routing includes `pillar4:/api/expenses/attach-receipt`

### Document Filing
- [ ] Send email with attached NDA PDF
- [ ] Verify: classified as `nda` with high confidence
- [ ] Verify: auto-filed to `01_CORPORATE/Legal/NDAs/` in SharePoint
- [ ] Verify: standardized filename follows `YYYY-MM-DD_NDA_<Counterparty>.pdf`

### Low Confidence Handling
- [ ] Send email with an ambiguously named attachment (e.g., `doc_12345.pdf`)
- [ ] Verify: Azure OpenAI is called for classification
- [ ] Verify: if still low confidence, parked in `00_STAGING/Inbox`

### Draft Review
- [ ] Verify: draft reply is listed at `GET /api/email/drafts/{message_id}`
- [ ] Edit draft via `PUT /api/email/drafts/{draft_id}`
- [ ] Verify draft marked as approved
- [ ] Verify: email sent from your mailbox with correct threading (after Layer 3 + send integration)

### Failure Scenarios
- [ ] Temporarily revoke OpenAI key → verify system falls back to rule-based mode
- [ ] Send an unsupported attachment (.zip) → verify it lands in `00_STAGING/Errors`
- [ ] Verify Application Insights shows logs for all operations
- [ ] Verify alert fires on simulated failures

---

## Summary: Who Does What, When

| Layer | Your Time | Claude's Time | Status |
|---|---|---|---|
| **Pre-Flight** | 30-60 min | — | ⬜ You |
| **Layer 1: Cosmos DB** | Deploy infra (15 min) | Code complete | ✅ Code delivered, awaiting deploy |
| **Layer 2: Azure OpenAI** | Deploy model + key (15 min) | Code complete | ✅ Code delivered, awaiting deploy |
| **Layer 3: Outlook/Graph** | App registration (20 min) | ~4 hours | ⬜ Awaiting your setup |
| **Layer 4: Doc Intelligence** | Store key (5 min) | Code complete | ✅ Code delivered, awaiting key |
| **Layer 5: Classification merge** | 0 min | Complete | ✅ Fully delivered |
| **Layer 6: SharePoint filing** | Provision folders (15 min) | ~3 hours | ⬜ Awaiting your setup |
| **Layer 7: Draft review** | 0 min | Complete | ✅ Fully delivered |
| **Layer 8: Hardening** | Enable logging (20 min) | ~3 hours | ⬜ Pending |
| **Validation** | 30 min | — | ⬜ After all layers |

### Your Work — Two Sessions

**Session 1** (~45 min) — Do this first:
1. Deploy Bicep template (or manually create resources)
2. Deploy GPT-4o model in Azure OpenAI
3. Store OpenAI key in Key Vault
4. Store Document Intelligence key in Key Vault
5. Create Graph App Registration + grant permissions
6. Store Graph credentials in Key Vault
7. Tell Claude "Session 1 complete" with the configuration values

**Session 2** (~30 min) — After Claude builds Layers 3, 6, 8:
1. Run SharePoint folder provisioning script
2. Enable diagnostic logging on Function App
3. Set up failure alerts in Application Insights
4. Review Key Vault access policies
5. Run validation checklist with Claude

### Current State

```
✅ Layer 1 CODE complete — 13 tests passing
✅ Layer 2 CODE complete — 6 tests passing
⬜ Layer 3 needs your App Registration before Claude can build
✅ Layer 4 CODE complete — 5 tests passing
✅ Layer 5 CODE complete — 34 tests passing
⬜ Layer 6 needs your SharePoint provisioning before Claude can build
✅ Layer 7 CODE complete — included in function_app.py
⬜ Layer 8 pending (depends on Layers 3 + 6)

Total: 87 tests passing across all delivered layers
```

**Next step**: Complete Session 1 above, then tell Claude "Session 1 complete" with your configuration values.
