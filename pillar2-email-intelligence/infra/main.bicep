// Peak 10 Energy — Email Intelligence Infrastructure
// Deploys: Function App, Storage, App Insights, Key Vault,
//          Azure OpenAI Service, Cosmos DB, Document Intelligence

@description('Azure region')
param location string = resourceGroup().location

@allowed(['dev', 'staging', 'prod'])
param environment string = 'dev'
param baseName string = 'peak10email'
@description('Azure OpenAI deployment name created inside the Azure OpenAI resource')
param openAIDeploymentName string = 'gpt-4o-email'

var suffix = '${baseName}${environment}'
var functionAppName = 'func-${suffix}'
var storageName = 'st${replace(suffix, '-', '')}'
var appInsightsName = 'ai-${suffix}'
var appServicePlanName = 'plan-${suffix}'
var keyVaultName = 'kv-${suffix}'
var openAIName = 'oai-${suffix}'
var cosmosName = 'cosmos-${suffix}'
var docIntelName = 'di-${suffix}'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: { Application_Type: 'web', RetentionInDays: 90 }
}

resource appServicePlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: appServicePlanName
  location: location
  sku: {
    name: environment == 'prod' ? 'B1' : 'Y1'
    tier: environment == 'prod' ? 'Basic' : 'Dynamic'
  }
  properties: { reserved: true }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
  }
}

resource openAI 'Microsoft.CognitiveServices/accounts@2023-10-01-preview' = {
  name: openAIName
  location: location
  sku: { name: 'S0' }
  kind: 'OpenAI'
  properties: {
    publicNetworkAccess: 'Enabled'
    customSubDomainName: openAIName
  }
}

// ---------------------------------------------------------------------------
// Cosmos DB — persistence for triage results, drafts, documents, corrections
// ---------------------------------------------------------------------------

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2023-11-15' = {
  name: cosmosName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [
      { locationName: location, failoverPriority: 0 }
    ]
    capabilities: environment == 'dev' ? [
      { name: 'EnableServerless' }
    ] : []
  }
}

resource cosmosDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2023-11-15' = {
  parent: cosmosAccount
  name: 'peak10-email-intelligence'
  properties: {
    resource: { id: 'peak10-email-intelligence' }
  }
}

resource triageContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-11-15' = {
  parent: cosmosDatabase
  name: 'triage_results'
  properties: {
    resource: {
      id: 'triage_results'
      partitionKey: { paths: ['/partition_date'], kind: 'Hash' }
      defaultTtl: 7776000 // 90 days
    }
  }
}

resource draftsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-11-15' = {
  parent: cosmosDatabase
  name: 'draft_responses'
  properties: {
    resource: {
      id: 'draft_responses'
      partitionKey: { paths: ['/message_id'], kind: 'Hash' }
      defaultTtl: 2592000 // 30 days
    }
  }
}

resource documentsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-11-15' = {
  parent: cosmosDatabase
  name: 'documents'
  properties: {
    resource: {
      id: 'documents'
      partitionKey: { paths: ['/document_id'], kind: 'Hash' }
    }
  }
}

resource correctionsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-11-15' = {
  parent: cosmosDatabase
  name: 'corrections'
  properties: {
    resource: {
      id: 'corrections'
      partitionKey: { paths: ['/original_type'], kind: 'Hash' }
    }
  }
}

// ---------------------------------------------------------------------------
// Document Intelligence (Form Recognizer)
// ---------------------------------------------------------------------------

resource docIntelligence 'Microsoft.CognitiveServices/accounts@2023-10-01-preview' = {
  name: docIntelName
  location: location
  sku: { name: 'S0' }
  kind: 'FormRecognizer'
  properties: {
    publicNetworkAccess: 'Enabled'
    customSubDomainName: docIntelName
  }
}

// ---------------------------------------------------------------------------
// Function App
// ---------------------------------------------------------------------------

resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      pythonVersion: '3.11'
      linuxFxVersion: 'PYTHON|3.11'
      appSettings: [
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};EndpointSuffix=core.windows.net;AccountKey=${storageAccount.listKeys().keys[0].value}' }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'AzureWebJobsFeatureFlags', value: 'EnableWorkerIndexing' }
        { name: 'APPINSIGHTS_INSTRUMENTATIONKEY', value: appInsights.properties.InstrumentationKey }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'KEY_VAULT_URI', value: keyVault.properties.vaultUri }
        { name: 'AZURE_OPENAI_ENDPOINT', value: openAI.properties.endpoint }
        { name: 'AZURE_OPENAI_API_KEY', value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=azure-openai-key)' }
        { name: 'AZURE_OPENAI_DEPLOYMENT', value: openAIDeploymentName }
        { name: 'AZURE_OPENAI_API_VERSION', value: '2024-06-01' }
        { name: 'COSMOS_CONNECTION_STRING', value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=cosmos-connection-string)' }
        { name: 'AZURE_DI_ENDPOINT', value: docIntelligence.properties.endpoint }
        { name: 'AZURE_DI_KEY', value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=cognitive-services-key)' }
        { name: 'GRAPH_CLIENT_ID', value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=graph-client-id)' }
        { name: 'GRAPH_CLIENT_SECRET', value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=graph-client-secret)' }
        { name: 'GRAPH_TENANT_ID', value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=graph-tenant-id)' }
        { name: 'GRAPH_MAILBOX_ADDRESS', value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=graph-mailbox-address)' }
        { name: 'GRAPH_SHAREPOINT_SITE_ID', value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=graph-sharepoint-site-id)' }
        { name: 'GRAPH_SHAREPOINT_DRIVE_ID', value: '@Microsoft.KeyVault(VaultName=${keyVault.name};SecretName=graph-sharepoint-drive-id)' }
        { name: 'MAILBOX_POLL_ENABLED', value: 'false' }
        { name: 'MAILBOX_POLL_SCHEDULE', value: '0 */1 * * * *' }
        { name: 'MAILBOX_POLL_TOP', value: '10' }
        { name: 'MAILBOX_MARK_PROCESSED', value: 'true' }
        { name: 'ENVIRONMENT', value: environment }
      ]
    }
  }
}

resource kvRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, functionApp.id, 'Key Vault Secrets User')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output functionAppName string = functionApp.name
output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}'
output openAIEndpoint string = openAI.properties.endpoint
output cosmosEndpoint string = cosmosAccount.properties.documentEndpoint
output docIntelligenceEndpoint string = docIntelligence.properties.endpoint
