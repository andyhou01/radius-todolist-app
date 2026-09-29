extension radius

param application string
param environment string
param image string
param ownershipLabels object = {
  'plane-demo/project': 'radplanes'
}
param gatewayPhase string = 'challenge'
param certificateSecretUri string = ''
@description('Deploy the per-pair agentgateway and its deterministic mock LLM backend.')
param llmGateway bool = false
param agentgatewayImage string = ''
@description('Optional in-cluster OTLP collector host:port for agentgateway traces.')
param otlpHost string = ''

resource redis 'Applications.Datastores/redisCaches@2023-10-01-preview' = {
  name: 'redis'
  properties: {
    application: application
    environment: environment
  }
}

module api '../modules/workload.bicep' = {
  name: 'data-api'
  params: {
    application: application
    environment: environment
    name: 'data-api'
    image: image
    ownershipLabels: ownershipLabels
    entrypoint: 'plane_demo.data.api'
    serviceAccount: 'data-api'
    runtimeServiceAccount: 'data-api-runtime'
    runtimeSecretName: 'data-api-runtime'
    api: true
    automountToken: true
    settings: llmGateway ? {
      LLM_GATEWAY_URL: {
        value: 'http://agentgateway:4000'
      }
    } : {}
    connections: {
      redis: {
        source: redis.id
      }
    }
  }
}

module reconciler '../modules/workload.bicep' = {
  name: 'data-reconciler'
  params: {
    application: application
    environment: environment
    name: 'data-reconciler'
    image: image
    ownershipLabels: ownershipLabels
    entrypoint: 'plane_demo.data.reconciler'
    serviceAccount: 'data-reconciler'
    runtimeSecretName: 'data-reconciler-runtime'
    automountToken: true
    settings: llmGateway ? union({
      LLM_BACKEND_HOST: {
        value: 'mock-llm:8088'
      }
      LLM_FILTERS_HOST: {
        value: 'llm-filters:8088'
      }
    }, empty(otlpHost) ? {} : {
      LLM_OTLP_HOST: {
        value: otlpHost
      }
    }) : {}
  }
}

module mockLlm '../modules/workload.bicep' = if (llmGateway) {
  name: 'data-mock-llm'
  params: {
    application: application
    environment: environment
    name: 'mock-llm'
    image: image
    ownershipLabels: ownershipLabels
    entrypoint: 'plane_demo.data.mock_llm'
    serviceAccount: 'mock-llm'
    api: true
  }
}

// PreRouting / PostRouting extAuthz filters: passport, plan policy, metering and audit.
module filters '../modules/workload.bicep' = if (llmGateway) {
  name: 'data-llm-filters'
  params: {
    application: application
    environment: environment
    name: 'llm-filters'
    image: image
    ownershipLabels: ownershipLabels
    entrypoint: 'plane_demo.data.filters'
    serviceAccount: 'llm-filters'
    api: true
    connections: {
      redis: {
        source: redis.id
      }
    }
  }
}

module agentgateway '../modules/agentgateway.bicep' = if (llmGateway) {
  name: 'data-agentgateway'
  params: {
    application: application
    environment: environment
    image: agentgatewayImage
    ownershipLabels: ownershipLabels
  }
}

module challenge '../modules/challenge.bicep' = {
  name: 'data-challenge'
  params: {
    application: application
    environment: environment
    image: image
    ownershipLabels: ownershipLabels
  }
}

module gateway '../modules/gateway.bicep' = {
  name: 'data-gateway'
  params: {
    application: application
    environment: environment
    apiService: 'data-api'
    phase: gatewayPhase
    certificateSecretUri: certificateSecretUri
  }
}
