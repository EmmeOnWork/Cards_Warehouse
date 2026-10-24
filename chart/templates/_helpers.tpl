{{/* The labels that tie the Service and the Deployment to the app's pods: one definition, so they never drift apart. */}}
{{- define "cards-warehouse.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* The same for the database's pod, with a name of its own: the app's Service must never send traffic to it. */}}
{{- define "cards-warehouse.postgresSelectorLabels" -}}
app.kubernetes.io/name: postgres
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* The StatefulSet of the database and its Service, whose name is the address the app connects to. */}}
{{- define "cards-warehouse.postgresName" -}}
{{ .Release.Name }}-postgres
{{- end }}

{{/* The Secret the Infisical operator fills and the Deployment reads: one name for both. */}}
{{- define "cards-warehouse.secretName" -}}
{{ .Release.Name }}-secrets
{{- end }}

{{/* The restricted Pod Security Standard, enforced by the namespace, for every container of the chart. */}}
{{- define "cards-warehouse.containerSecurityContext" -}}
allowPrivilegeEscalation: false
capabilities:
  drop: [ALL]
readOnlyRootFilesystem: true
{{- end }}

{{/* The environment of the app, the same for the migrations that run before it. The libpq variables lead to the
database; a key missing from the Secret keeps the pod from starting, and the pod events name it. */}}
{{- define "cards-warehouse.appEnv" -}}
- name: PGHOST
  value: {{ include "cards-warehouse.postgresName" . }}
- name: PGDATABASE
  value: {{ .Values.database.name }}
- name: PGUSER
  value: {{ .Values.database.user }}
{{- range .Values.secrets }}
- name: {{ . }}
  valueFrom:
    secretKeyRef:
      name: {{ include "cards-warehouse.secretName" $ }}
      key: {{ . }}
{{- end }}
{{- range .Values.optionalSecrets }}
- name: {{ . }}
  valueFrom:
    secretKeyRef:
      name: {{ include "cards-warehouse.secretName" $ }}
      key: {{ . }}
      optional: true
{{- end }}
{{- end }}
