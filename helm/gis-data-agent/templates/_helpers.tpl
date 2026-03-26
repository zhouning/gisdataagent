{{/*
Expand the name of the chart.
*/}}
{{- define "gis-data-agent.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fullname
*/}}
{{- define "gis-data-agent.fullname" -}}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "gis-data-agent.labels" -}}
app.kubernetes.io/name: {{ include "gis-data-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "gis-data-agent.selectorLabels" -}}
app.kubernetes.io/name: {{ include "gis-data-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
