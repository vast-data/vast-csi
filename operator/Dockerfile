FROM quay.io/operator-framework/ansible-operator:v1.0.1

### Required OpenShift Labels
LABEL name="VAST Data Operator" \
      vendor="vastdata" \
      version="v0.0.1" \
      release="1" \
      summary="An operator for VAST Data CSI Driver." \
      description="This operator will deploy VAST Data CSI Driver on your cluster."

# Required Licenses
COPY LICENSE /licenses/vast-csi

COPY requirements.yml ${HOME}/requirements.yml
RUN ansible-galaxy collection install -r ${HOME}/requirements.yml \
	&& chmod -R ug+rwx ${HOME}/.ansible

COPY watches.yaml ${HOME}/watches.yaml
COPY roles/ ${HOME}/roles/
COPY playbooks/ ${HOME}/playbooks/
