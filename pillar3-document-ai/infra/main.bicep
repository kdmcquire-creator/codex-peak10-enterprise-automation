// Peak 10 Energy — Document AI Infrastructure
// Deploys: Function App, Storage, App Insights, Key Vault,
//          Cognitive Services (for AI Builder / Document Intelligence)

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Environment name')
@allowed(['dev', 'staging', 'prod'])
param environment string = 'dev'

param baseName string = 'peak10docai'

@description('Hosting plan SKU for the Linux Function App')
@allowed([
  'Y1'
  'B1'
])
param hostingPlanSku string = 'B1'

@description('Existing App Service Plan resource ID to reuse (optional)')
param existingAppServicePlanId string = ''

var suffix = '${baseName}${environment}'
var functionAppName = 'func-${suffix}'
var storageName = 'st${replace(suffix, '-', '')}'
var appInsightsName = 'ai-${suffix}'
var appServicePlanName = 'plan-${suffix}'
var keyVaultName = 'kv-${suffix}'
var cogServicesName = 'cog-${suffix}'
var hostingPlanTier = hostingPlanSku == 'Y1' ? 'Dynamic' : 'Basic'

// ---------------------------------------------------------------------------
// Storage Account
// ---------------------------------------------------------------------------

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

// Blob container for staged documents
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

resource stagingContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'staging-documents'
  properties: {
    publicAccess: 'None'
  }
}

// ---------------------------------------------------------------------------
// Application Insights
// ---------------------------------------------------------------------------

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    RetentionInDays: 90
  }
}

// ---------------------------------------------------------------------------
// App Service Plan
// ---------------------------------------------------------------------------

resource appServicePlan 'Microsoft.Web/serverfarms@2023-01-01' = if (empty(existingAppServicePlanId)) {
  name: appServicePlanName
  location: location
  sku: {
    name: hostingPlanSku
    tier: hostingPlanTier
  }
  properties: { reserved: true }
}

// ---------------------------------------------------------------------------
// Key Vault
// ---------------------------------------------------------------------------

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 30
  }
}

// ---------------------------------------------------------------------------
// Cognitive Services (Azure AI Document Intelligence)
// ---------------------------------------------------------------------------

resource cognitiveServices 'Microsoft.CognitiveServices/accounts@2023-10-01-preview' = {
  name: cogServicesName
  location: location
  sku: { name: 'S0' }
  kind: 'FormRecognizer'
  properties: {
    publicNetworkAccess: 'Enabled'
    customSubDomainName: cogServicesName
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
    serverFarmId: empty(existingAppServicePlanId) ? appServicePlan.id : existingAppServicePlanId
    httpsOnly: true
    siteConfig: {
      pythonVersion: '3.11'
      linuxFxVersion: 'PYTHON|3.11'
      appSettings: [
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};EndpointSuffix=core.windows.net;AccountKey=${storageAccount.listKeys().keys[0].value}' }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'AzureWebJobsFeatureFlags', value: 'EnableWorkerIndexing' }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'ENABLE_ORYX_BUILD', value: 'true' }
        { name: 'APPINSIGHTS_INSTRUMENTATIONKEY', value: appInsights.properties.InstrumentationKey }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'KEY_VAULT_URI', value: keyVault.properties.vaultUri }
        { name: 'COGNITIVE_SERVICES_ENDPOINT', value: cognitiveServices.properties.endpoint }
        { name: 'STAGING_CONTAINER_URL', value: '${storageAccount.properties.primaryEndpoints.blob}staging-documents' }
        { name: 'ENVIRONMENT', value: environment }
      ]
    }
  }
}

// Key Vault access
resource kvRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, functionApp.id, 'Key Vault Secrets User')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output functionAppName string = functionApp.name
output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}'
output cognitiveServicesEndpoint string = cognitiveServices.properties.endpoint
output stagingContainerUrl string = '${storageAccount.properties.primaryEndpoints.blob}staging-documents'
