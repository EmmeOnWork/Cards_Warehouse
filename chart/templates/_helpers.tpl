{{/* The labels that tie the Service and the Deployment to the app's pods: one definition, so they never drift apart. */}}
{{- define "cards-warehouse.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* The Secret the Infisical operator fills and the Deployment reads: one name for both. */}}
{{- define "cards-warehouse.secretName" -}}
{{ .Release.Name }}-secrets
{{- end }}
