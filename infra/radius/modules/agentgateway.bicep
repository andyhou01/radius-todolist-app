extension radius

param application string
param environment string
param image string
param ownershipLabels object = {
  'plane-demo/project': 'radplanes'
}
param name string = 'agentgateway'
param workloadIdentity bool = false

var account = {
  apiVersion: 'v1'
  kind: 'ServiceAccount'
  metadata: {
    name: name
  }
}

// The data reconciler writes agentgateway-config; the gateway only reads the mounted file.
resource gateway 'Applications.Core/containers@2023-10-01-preview' = {
  name: name
  properties: {
    application: application
    environment: environment
    container: {
      image: image
      args: [
        '-f'
        '/config/config.yaml'
      ]
      ports: {
        http: {
          containerPort: 4000
        }
      }
      livenessProbe: {
        kind: 'tcp'
        containerPort: 4000
        initialDelaySeconds: 5
        periodSeconds: 20
        failureThreshold: 3
        timeoutSeconds: 5
      }
    }
    extensions: [
      {
        kind: 'manualScaling'
        replicas: 1
      }
      {
        kind: 'kubernetesMetadata'
        labels: union(ownershipLabels, {
          'azure.workload.identity/use': workloadIdentity ? 'true' : 'false'
          'plane-demo/component': name
        })
      }
    ]
    runtimes: {
      kubernetes: {
        base: string(account)
        pod: {
          serviceAccountName: name
          automountServiceAccountToken: false
          securityContext: {
            runAsNonRoot: true
            runAsUser: 65532
            runAsGroup: 65532
            fsGroup: 65532
            fsGroupChangePolicy: 'OnRootMismatch'
            seccompProfile: {
              type: 'RuntimeDefault'
            }
          }
          containers: [
            {
              name: name
              volumeMounts: [
                {
                  name: 'config'
                  mountPath: '/config'
                  readOnly: true
                }
              ]
              resources: {
                requests: {
                  cpu: '100m'
                  memory: '64Mi'
                }
                limits: {
                  cpu: '1'
                  memory: '256Mi'
                }
              }
              securityContext: {
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem: true
                capabilities: {
                  drop: [
                    'ALL'
                  ]
                }
              }
            }
          ]
          volumes: [
            {
              name: 'config'
              configMap: {
                name: 'agentgateway-config'
              }
            }
          ]
        }
      }
    }
  }
}

output id string = gateway.id
