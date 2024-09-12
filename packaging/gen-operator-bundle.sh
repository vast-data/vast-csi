#!/usr/bin/env sh

set -e

ROOT_DIR=$1
CHANNEL=$2
OUT_DIR=$ROOT_DIR/bundle
shift 2  # Shift out the first three arguments (CHART_DIR, OUT_DIR and CHANNEL)

# Store remaining arguments in a variable
HELM_ARGS="$@"

echo "CHANNEL: $CHANNEL"
echo "OUT_DIR: $OUT_DIR"
echo "Helm args: $HELM_ARGS"

CSI_OPERATOR_CHART_PATH=$ROOT_DIR/charts/vastcsi-operator

# Run Helm template command with dynamic arguments
echo "Generate manifests"
helm template --dry-run --debug csi-operator $CSI_OPERATOR_CHART_PATH $HELM_ARGS \
| awk -v out=$OUT_DIR/manifests -F"/" '$0~/^# Source: /{file=out"/"$NF; print "Creating "file; system ("mkdir -p $(dirname "file"); echo -n "" > "file)} $0!~/^#/ && $0!="---"{print $0 >> file}'

echo "Generate metadata"
METADATA_DIR=$OUT_DIR/metadata
mkdir -p $METADATA_DIR
cat <<EOF > $METADATA_DIR/annotations.yaml
annotations:
  operators.operatorframework.io.bundle.channels.v1: ${CHANNEL}
  operators.operatorframework.io.bundle.manifests.v1: manifests/
  operators.operatorframework.io.bundle.mediatype.v1: registry+v1
  operators.operatorframework.io.bundle.metadata.v1: metadata/
  operators.operatorframework.io.bundle.package.v1: vast-csi-operator
  operators.operatorframework.io.metrics.builder: operator-sdk-v1.3.0-ocp
  operators.operatorframework.io.metrics.mediatype.v1: metrics+v1
  operators.operatorframework.io.metrics.project_layout: helm.sdk.operatorframework.io/v1

  # Annotations for testing.
  operators.operatorframework.io.test.mediatype.v1: scorecard+v1
  operators.operatorframework.io.test.config.v1: tests/scorecard/

  # Annotations to specify supported OCP versions.
  com.redhat.openshift.versions: v4.14-v4.15
EOF

echo "Generate scorecard testing template"
TESTS_DIR=$OUT_DIR/tests/scorecard
mkdir -p $TESTS_DIR
cp $CSI_OPERATOR_CHART_PATH/scorecard_config.yaml $TESTS_DIR/config.yaml
