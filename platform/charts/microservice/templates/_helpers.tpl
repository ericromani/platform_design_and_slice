{{/*
Naming. Every Kubernetes and AWS name derives from service.name so a service's footprint
is predictable (and greppable) across the cluster and the AWS account.
*/}}
{{- define "ms.name" -}}
{{- required "service.name is required" .Values.service.name -}}
{{- end -}}

{{- define "ms.env" -}}
{{- required "global.environment is injected by the deploy pipeline" .Values.global.environment -}}
{{- end -}}

{{- define "ms.labels" -}}
app.kubernetes.io/name: {{ include "ms.name" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: {{ include "ms.name" . }}
app.kubernetes.io/version: {{ .Values.image.tag | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
platform.example.com/team: {{ .Values.service.team }}
platform.example.com/environment: {{ include "ms.env" . }}
{{- end -}}

{{- define "ms.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ms.name" . }}
{{- end -}}

{{/* Uppercase env-var token from a logical resource name: "order-events" -> "ORDER_EVENTS". */}}
{{- define "ms.envToken" -}}
{{- . | upper | replace "-" "_" -}}
{{- end -}}

{{/* IRSA role: one per service per environment. */}}
{{- define "ms.roleName" -}}
{{- printf "%s-%s" (include "ms.name" .) (include "ms.env" .) -}}
{{- end -}}

{{- define "ms.roleArn" -}}
{{- printf "arn:aws:iam::%s:role/%s" (required "global.accountId is injected by the deploy pipeline" .Values.global.accountId) (include "ms.roleName" .) -}}
{{- end -}}

{{- define "ms.metricsPort" -}}
{{- .Values.metrics.port | default .Values.containerPort -}}
{{- end -}}

{{/* Physical AWS names (also used by the RGDs via the instance spec). */}}
{{- define "ms.sqsName" -}}
{{- $n := printf "%s-%s" (include "ms.name" .root) .item.name -}}
{{- if .item.fifo }}{{ printf "%s.fifo" $n }}{{ else }}{{ $n }}{{ end -}}
{{- end -}}

{{- define "ms.snsName" -}}
{{- $n := printf "%s-%s" (include "ms.name" .root) .item.name -}}
{{- if .item.fifo }}{{ printf "%s.fifo" $n }}{{ else }}{{ $n }}{{ end -}}
{{- end -}}

{{- define "ms.s3Name" -}}
{{- $n := printf "%s-%s-%s" (include "ms.name" .root) .item.name .root.Values.global.accountId -}}
{{- if gt (len $n) 63 }}{{ fail (printf "S3 bucket name %q exceeds 63 characters; shorten service.name or the bucket name" $n) }}{{ end -}}
{{- $n -}}
{{- end -}}

{{- define "ms.simpleName" -}}
{{- printf "%s-%s" (include "ms.name" .root) .item.name -}}
{{- end -}}

{{/*
Environment injected into the container: platform identity, AWS coordinates of every
declared resource, and (local mode only) the IRSA variables that the EKS pod-identity
webhook would otherwise inject.
*/}}
{{- define "ms.platformEnv" -}}
- name: PLATFORM_SERVICE
  value: {{ include "ms.name" . | quote }}
- name: PLATFORM_ENVIRONMENT
  value: {{ include "ms.env" . | quote }}
- name: AWS_REGION
  value: {{ .Values.global.region | quote }}
- name: AWS_DEFAULT_REGION
  value: {{ .Values.global.region | quote }}
{{- if .Values.global.local }}
- name: AWS_ENDPOINT_URL
  value: {{ required "global.awsEndpointUrl is required in local mode" .Values.global.awsEndpointUrl | quote }}
{{- with .Values.global.awsS3EndpointUrl }}
- name: AWS_ENDPOINT_URL_S3
  value: {{ . | quote }}
{{- end }}
{{- if include "ms.hasAws" . }}
- name: AWS_ROLE_ARN
  value: {{ include "ms.roleArn" . | quote }}
- name: AWS_WEB_IDENTITY_TOKEN_FILE
  value: /var/run/secrets/eks.amazonaws.com/serviceaccount/token
- name: AWS_STS_REGIONAL_ENDPOINTS
  value: regional
{{- end }}
{{- end }}
{{- $root := . }}
{{- range .Values.aws.sqs }}
- name: SQS_{{ include "ms.envToken" .name }}_QUEUE_NAME
  value: {{ include "ms.sqsName" (dict "root" $root "item" .) | quote }}
{{- end }}
{{- range .Values.aws.sns }}
- name: SNS_{{ include "ms.envToken" .name }}_TOPIC_ARN
  value: {{ printf "arn:aws:sns:%s:%s:%s" $root.Values.global.region $root.Values.global.accountId (include "ms.snsName" (dict "root" $root "item" .)) | quote }}
{{- end }}
{{- range .Values.aws.s3 }}
- name: S3_{{ include "ms.envToken" .name }}_BUCKET
  value: {{ include "ms.s3Name" (dict "root" $root "item" .) | quote }}
{{- end }}
{{- range .Values.aws.dynamodb }}
- name: DYNAMODB_{{ include "ms.envToken" .name }}_TABLE
  value: {{ include "ms.simpleName" (dict "root" $root "item" .) | quote }}
{{- end }}
{{- range .Values.aws.rds }}
- name: RDS_{{ include "ms.envToken" .name }}_INSTANCE_ID
  value: {{ include "ms.simpleName" (dict "root" $root "item" .) | quote }}
{{- end }}
{{- range $k, $v := .Values.env }}
- name: {{ $k }}
  value: {{ $v | toString | quote }}
{{- end }}
{{- end -}}

{{/* Does this service declare any AWS resource (and therefore need an IAM role)? */}}
{{- define "ms.hasAws" -}}
{{- $a := .Values.aws -}}
{{- if or $a.sqs $a.sns $a.s3 $a.dynamodb $a.rds }}true{{ end -}}
{{- end -}}
