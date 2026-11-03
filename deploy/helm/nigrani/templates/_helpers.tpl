{{- define "nigrani.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "nigrani.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "nigrani.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "nigrani.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "nigrani.selectorLabels" -}}
app.kubernetes.io/name: {{ include "nigrani.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "nigrani.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "nigrani.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/* The Secret that holds the admin password: the user's, or the one this chart creates. */}}
{{- define "nigrani.secretName" -}}
{{- default (include "nigrani.fullname" .) .Values.auth.existingSecret }}
{{- end }}

{{- define "nigrani.secretKey" -}}
{{- if .Values.auth.existingSecret }}{{ .Values.auth.existingSecretKey }}{{ else }}NIGRANI_PASSWORD{{ end }}
{{- end }}

{{- define "nigrani.pvcName" -}}
{{- default (include "nigrani.fullname" .) .Values.persistence.existingClaim }}
{{- end }}
