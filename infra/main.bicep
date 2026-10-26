// Azure Container Apps demo deployment (ADR 0044).
// Consumption ACA environment + Neon external Postgres + GHCR release images.
//   azd up  →  https://<web-app>.<region>.azurecontainerapps.io
//
// Topology mirrors deploy/docker-compose.yml:
//   web (external ingress :80) → /api → api (internal ingress :8000)
//   api / scheduler / worker share the api image + Azure Files /app/data
//   migrate is a Manual ACA Job (alembic upgrade head)

targetScope = 'resourceGroup'

@minLength(1)
@maxLength(20)
@description('azd environment name — prefixes all resource names.')
param environmentName string

@description('Azure region. Neon should sit in the closest region (e.g. ap-southeast-1).')
param location string = resourceGroup().location

@secure()
@description('postgresql+asyncpg:// URL of the external Postgres (Neon). Use the direct endpoint, not the -pooler host.')
param databaseUrl string

@secure()
@description('Random ≥32 chars. Generate: openssl rand -base64 48')
param jwtSecret string

@secure()
@description('Fernet key. Generate: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"')
param byokEncryptionKey string

@description('Public origin of the web app — seeds instance_settings on first boot (ADR 0026). Set to the planned URL (custom domain or ACA FQDN).')
param webBaseUrl string

@description('CORS origins; defaults to webBaseUrl.')
param corsOrigins string = ''

@description('stub never calls Meta; instagram uses social_accounts.')
param publishAdapter string = 'stub'

@secure()
@description('Optional platform LLM key. Orgs can add BYOK later in the setup wizard.')
param openAiApiKey string = ''

@secure()
@description('Optional Tavily key for session research (ADR 0009).')
param tavilyApiKey string = ''

@description('Demo default: mock image URLs without a provider. Set a real catalog id when a provider key exists.')
param llmImageModel string = 'placeholder'

@description('GHCR namespace and tag of the release images.')
param imagePrefix string = 'ghcr.io/brandon-wsc'
param imageTag string = 'onprem'

@description('''Custom domain bound to web ingress (e.g. demo.unhinted.hk). Empty = ACA default FQDN only.
Requires CNAME <sub> → <web FQDN> and TXT asuid.<sub> → customDomainVerificationId before provision;
the env managed cert validates via CNAME lookup.''')
param customDomainName string = ''

@description('''Managed cert resource name on the env. Defaults to a deterministic cert-<domain> name.
Set to an existing az-generated name (mc-…-5102 style) to adopt that cert in place instead of minting a second one.''')
param customDomainCertName string = ''

var apiImage = '${imagePrefix}/unhinted-api:${imageTag}'
var webImage = '${imagePrefix}/unhinted-web:${imageTag}'
var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, location))
var tags = { 'azd-env-name': environmentName }

// ── Observability + shared volumes ────────────────────────────────────────

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${environmentName}'
  location: location
  tags: tags
  properties: {
    retentionInDays: 30
    sku: { name: 'PerGB2018' }
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${take(replace(environmentName, '-', ''), 12)}${take(resourceToken, 8)}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

// api/scheduler/worker: media + anything else under /app/data (MEDIA_ROOT)
resource appdataShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileService
  name: 'appdata'
  properties: { shareQuota: 32 }
}

// web: stock GHCR nginx image entrypoint envsubsts /etc/nginx/templates/*.template
// into /etc/nginx/conf.d — this share carries the ACA-aware upstream conf.
resource nginxShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileService
  name: 'nginx-conf'
  properties: { shareQuota: 1 }
}

resource managedEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${environmentName}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
    zoneRedundant: false
  }
}

resource appdataStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  parent: managedEnv
  name: 'appdata'
  properties: {
    azureFile: {
      accountName: storage.name
      accountKey: storage.listKeys().keys[0].value
      shareName: appdataShare.name
      accessMode: 'ReadWrite'
    }
  }
}

resource nginxStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  parent: managedEnv
  name: 'nginxconf'
  properties: {
    azureFile: {
      accountName: storage.name
      accountKey: storage.listKeys().keys[0].value
      shareName: nginxShare.name
      accessMode: 'ReadOnly'
    }
  }
}

// Declarative SNI cert + hostname binding for the custom domain. Without this
// every `azd provision` PUT re-asserts webApp.ingress with no customDomains and
// silently wipes the binding (the cert on the env survives; the binding does not).
var resolvedCustomDomainCertName = empty(customDomainCertName)
  ? 'cert-${replace(customDomainName, '.', '-')}'
  : customDomainCertName

resource customDomainCert 'Microsoft.App/managedEnvironments/managedCertificates@2024-03-01' = if (!empty(customDomainName)) {
  parent: managedEnv
  name: resolvedCustomDomainCertName
  location: location
  tags: tags
  properties: {
    subjectName: customDomainName
    domainControlValidation: 'CNAME'
  }
}

// ── Shared backend env (api / worker / scheduler / migrate) ───────────────

var coreSecrets = [
  { name: 'database-url', value: databaseUrl }
  { name: 'jwt-secret', value: jwtSecret }
  { name: 'byok-encryption-key', value: byokEncryptionKey }
]
var optionalSecrets = concat(
  empty(openAiApiKey) ? [] : [{ name: 'openai-api-key', value: openAiApiKey }],
  empty(tavilyApiKey) ? [] : [{ name: 'tavily-api-key', value: tavilyApiKey }]
)
var backendSecrets = concat(coreSecrets, optionalSecrets)

var coreEnv = [
  { name: 'APP_ENV', value: 'production' }
  { name: 'DEPLOYMENT_MODE', value: 'onprem' }
  { name: 'DATABASE_URL', secretRef: 'database-url' }
  { name: 'JWT_SECRET', secretRef: 'jwt-secret' }
  { name: 'BYOK_ENCRYPTION_KEY', secretRef: 'byok-encryption-key' }
  { name: 'MEDIA_ROOT', value: '/app/data/media' }
  { name: 'WEB_BASE_URL', value: webBaseUrl }
  { name: 'CORS_ORIGINS', value: empty(corsOrigins) ? webBaseUrl : corsOrigins }
  { name: 'REFRESH_COOKIE_SECURE', value: 'true' }
  { name: 'PUBLISH_ADAPTER', value: publishAdapter }
  { name: 'LLM_IMAGE_MODEL', value: llmImageModel }
]
var optionalEnv = concat(
  empty(openAiApiKey) ? [] : [{ name: 'OPENAI_API_KEY', secretRef: 'openai-api-key' }],
  empty(tavilyApiKey) ? [] : [{ name: 'TAVILY_API_KEY', secretRef: 'tavily-api-key' }]
)
var backendEnv = concat(coreEnv, optionalEnv)

var appdataVolume = { name: 'appdata', storageType: 'AzureFile', storageName: 'appdata' }
var appdataMount = { volumeName: 'appdata', mountPath: '/app/data' }

// ── api (internal ingress) ────────────────────────────────────────────────

resource apiApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${environmentName}-api'
  location: location
  tags: union(tags, { 'azd-service-name': 'api' })
  dependsOn: [appdataStorage]
  properties: {
    managedEnvironmentId: managedEnv.id
    configuration: {
      secrets: backendSecrets
      ingress: {
        external: false
        targetPort: 8000
        transport: 'auto'
        // Plain HTTP inside the env — TLS is terminated at web's external
        // ingress. allowInsecure=false 301s to HTTPS, which nginx proxy_pass
        // does not follow.
        allowInsecure: true
      }
    }
    template: {
      containers: [
        {
          name: 'api'
          image: apiImage
          env: backendEnv
          resources: { cpu: json('1.0'), memory: '2Gi' }
          volumeMounts: [appdataMount]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/api/health', port: 8000 }
              periodSeconds: 15
              failureThreshold: 3
              initialDelaySeconds: 10
            }
          ]
        }
      ]
      volumes: [appdataVolume]
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

// ── web (external ingress; nginx envsubst template from nginx-conf share) ──

resource webApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${environmentName}-web'
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  dependsOn: [nginxStorage]
  properties: {
    managedEnvironmentId: managedEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 80
        transport: 'auto'
        allowInsecure: false
        customDomains: empty(customDomainName) ? [] : [
          {
            name: customDomainName
            certificateId: customDomainCert.id
            bindingType: 'SniEnabled'
          }
        ]
      }
    }
    template: {
      containers: [
        {
          name: 'web'
          image: webImage
          env: [
            {
              name: 'API_UPSTREAM'
              value: apiApp.properties.configuration.ingress.fqdn
            }
          ]
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          volumeMounts: [{ volumeName: 'nginxconf', mountPath: '/etc/nginx/templates' }]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/', port: 80 }
              periodSeconds: 30
              failureThreshold: 3
            }
          ]
        }
      ]
      volumes: [{ name: 'nginxconf', storageType: 'AzureFile', storageName: 'nginxconf' }]
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

// ── scheduler + worker (no ingress; singleton replicas — ADR 0039) ─────────

resource schedulerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${environmentName}-scheduler'
  location: location
  tags: union(tags, { 'azd-service-name': 'scheduler' })
  dependsOn: [appdataStorage]
  properties: {
    managedEnvironmentId: managedEnv.id
    configuration: { secrets: backendSecrets }
    template: {
      containers: [
        {
          name: 'scheduler'
          image: apiImage
          command: ['python', '-m', 'cmd.scheduler']
          env: backendEnv
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

resource workerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${environmentName}-worker'
  location: location
  tags: union(tags, { 'azd-service-name': 'worker' })
  dependsOn: [appdataStorage]
  properties: {
    managedEnvironmentId: managedEnv.id
    configuration: { secrets: backendSecrets }
    template: {
      containers: [
        {
          name: 'worker'
          image: apiImage
          command: ['python', '-m', 'cmd.worker', 'serve']
          env: backendEnv
          resources: { cpu: json('1.0'), memory: '2Gi' }
          volumeMounts: [appdataMount]
        }
      ]
      volumes: [appdataVolume]
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

// ── migrate (Manual job; started by deploy/azure/postprovision.sh) ─────────

resource migrateJob 'Microsoft.App/jobs@2024-03-01' = {
  name: '${environmentName}-migrate'
  location: location
  tags: tags
  properties: {
    environmentId: managedEnv.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 900
      replicaRetryLimit: 1
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      secrets: backendSecrets
    }
    template: {
      containers: [
        {
          name: 'migrate'
          image: apiImage
          command: ['alembic', 'upgrade', 'head']
          env: backendEnv
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
    }
  }
}

// ── Outputs (azd hoists these into hook env vars) ──────────────────────────

output RESOURCE_GROUP_NAME string = resourceGroup().name
output MANAGED_ENV_NAME string = managedEnv.name
output WEB_APP_NAME string = webApp.name
output WEB_FQDN string = webApp.properties.configuration.ingress.fqdn
output API_INTERNAL_FQDN string = apiApp.properties.configuration.ingress.fqdn
output MIGRATE_JOB_NAME string = migrateJob.name
output STORAGE_ACCOUNT_NAME string = storage.name
output NGINX_SHARE_NAME string = nginxShare.name
