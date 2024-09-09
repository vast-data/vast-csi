
{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "csi-operator.rbac.proxy" -}}
- apiGroups:
  - authentication.k8s.io
  resources:
  - tokenreviews
  verbs:
  - create
- apiGroups:
  - authorization.k8s.io
  resources:
  - subjectaccessreviews
  verbs:
  - create
{{- end }}


{{- define "csi-operator.rbac.manager" -}}
- apiGroups:
  - ""
  resources:
  - namespaces
  verbs:
  - get
- apiGroups:
  - ""
  resources:
  - secrets
  verbs:
  - '*'
- apiGroups:
  - ""
  resources:
  - events
  verbs:
  - create
- apiGroups:
  - rbac.authorization.k8s.io
  resources:
  - clusterrolebindings
  verbs:
  - create
  - delete
  - get
  - list
  - watch
- apiGroups:
  - rbac.authorization.k8s.io
  resources:
  - clusterroles
  verbs:
  - create
  - delete
  - get
  - list
  - watch
- apiGroups:
  - rbac.authorization.k8s.io
  resources:
  - rolebindings
  verbs:
  - create
  - delete
  - get
  - list
  - watch
- apiGroups:
  - rbac.authorization.k8s.io
  resources:
  - roles
  verbs:
  - create
  - delete
  - get
  - list
  - watch
- apiGroups:
  - security.openshift.io
  resourceNames:
  - privileged
  - hostmount-anyuid
  resources:
  - securitycontextconstraints
  verbs:
  - '*'
- apiGroups:
  - storage.vastdata.com
  resources:
  - vastcsidrivers
  - vastcsidrivers/status
  - vastcsidrivers/finalizers
  verbs:
  - create
  - delete
  - get
  - list
  - patch
  - update
  - watch
- apiGroups:
  - storage.vastdata.com
  resources:
  - vaststorages
  - vaststorages/status
  - vaststorages/finalizers
  verbs:
  - create
  - delete
  - get
  - list
  - patch
  - update
  - watch
- apiGroups:
  - storage.vastdata.com
  resources:
  - vastclusters
  - vastclusters/status
  - vastclusters/finalizers
  verbs:
  - create
  - delete
  - get
  - list
  - patch
  - update
  - watch
- apiGroups:
  - storage.k8s.io
  resources:
  - csidrivers
  verbs:
  - '*'
- apiGroups:
  - apiextensions.k8s.io
  resources:
  - customresourcedefinitions
  verbs:
  - '*'
- apiGroups:
  - rbac.authorization.k8s.io
  resources:
  - clusterrolebindings
  - clusterroles
  verbs:
  - '*'
- apiGroups:
  - ""
  resources:
  - serviceaccounts
  verbs:
  - '*'
- apiGroups:
  - rbac.authorization.k8s.io
  resources:
  - rolebindings
  - roles
  verbs:
  - '*'
- apiGroups:
  - apps
  resources:
  - daemonsets
  - deployments
  verbs:
  - '*'
- apiGroups:
  - storage.k8s.io
  resources:
  - storageclasses
  verbs:
  - '*'
- apiGroups:
  - snapshot.storage.k8s.io
  resources:
  - volumesnapshotclasses
  verbs:
  - '*'
- apiGroups:
  - coordination.k8s.io
  resources:
  - leases
  verbs:
  - get
  - list
  - watch
  - create
  - update
  - delete
{{- end }}


{{- define "csi-operator.rbac.leader-election" -}}
- apiGroups:
  - ""
  resources:
  - configmaps
  verbs:
  - get
  - list
  - watch
  - create
  - update
  - patch
  - delete
- apiGroups:
  - ""
  resources:
  - events
  verbs:
  - create
  - patch
{{- end }}


{{- define "csi-operator.manager-deployment.spec" -}}
replicas: 1
selector:
  matchLabels:
    control-plane: controller-manager
template:
  metadata:
    labels:
      control-plane: controller-manager
  spec:
    containers:
    - args:
      - --secure-listen-address=0.0.0.0:8443
      - --upstream=http://127.0.0.1:8080/
      - --logtostderr=true
      - --v=10
      image: {{ .Values.proxyImage }}
      name: kube-rbac-proxy
      ports:
      - containerPort: 8443
        name: https
    - args:
      - --metrics-addr=127.0.0.1:8080
      - --enable-leader-election
      - --leader-election-id=vast-csi-operator
      name: csi-vast-operator
      image: {{ .Values.managerImage | required "Manager image is required" }}
      imagePullPolicy: Always
      env:
        - name: WATCH_NAMESPACE
          valueFrom:
            fieldRef:
              fieldPath: metadata.namespace
        - name: POD_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
      resources:
        limits:
          cpu: 200m
          memory: 300Mi
        requests:
          cpu: 100m
          memory: 100Mi
    {{- if .Values.imagePullSecret }}
    imagePullSecrets:
      - name: {{ .Values.imagePullSecret }}
    {{- end }}
    serviceAccountName: vast-csi-driver-operator-controller-manager
    priorityClassName: "system-cluster-critical"
    terminationGracePeriodSeconds: 10
{{- end }}
