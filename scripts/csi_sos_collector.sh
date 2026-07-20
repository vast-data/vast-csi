#!/usr/bin/env bash
#═══════════════════════════════════════════════════════════════════════════════
# VAST CSI SOS Collector
#═══════════════════════════════════════════════════════════════════════════════

set -o pipefail

# This script uses bash 4+ features (associative arrays). Fail fast and clearly
# on older shells (e.g. macOS system bash 3.2) instead of a confusing later error.
if [[ -z "${BASH_VERSINFO:-}" ]] || (( BASH_VERSINFO[0] < 4 )); then
    echo "ERROR: bash >= 4 required (current: ${BASH_VERSION:-unknown}). Run with a newer bash." >&2
    exit 1
fi

VERSION="2.15.0"
SCRIPT_NAME=$(basename "$0")

# Default settings
LOG_LINES=1000
LOG_SINCE=""          # optional kubectl logs --since window (e.g. 72h); empty = no time bound
SSH_TIMEOUT=60
SKIP_REMOTE=false
VERBOSE=false
QUIET=false
ALL_LOGS=false
PARALLEL_SSH=false
PARALLEL_WORKERS=20
COLLECT_MODE="all"    # all | nfs | block — which remote node diagnostics to run
NODES_OVERRIDE=""     # comma-separated node names; replaces auto-detected NODE_LIST

# Timing
SCRIPT_START_TIME=""
declare -A STEP_TIMES

# Colors (auto-detect terminal capability)
if [[ -t 1 ]]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
    BLUE='\033[0;34m'; CYAN='\033[0;36m'; MAGENTA='\033[0;35m'
    BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'
else
    RED='' GREEN='' YELLOW='' BLUE='' CYAN='' MAGENTA='' BOLD='' DIM='' NC=''
fi

usage() {
    cat <<EOF

${BOLD}╔══════════════════════════════════════════════════════════════════════════════╗
║                    VAST CSI SOS Collector v${VERSION}                          ║
╚══════════════════════════════════════════════════════════════════════════════╝${NC}

  Comprehensive diagnostics for VAST CSI driver issues with integrated
  NVMe/NVMeoF diagnostics for block storage troubleshooting.

${BOLD}USAGE:${NC}
    ${SCRIPT_NAME} [OPTIONS]

${BOLD}OPTIONS:${NC}
    ${CYAN}-w, --workload-ns${NC} <NS>    Workload namespace
    ${CYAN}-c, --csi-ns${NC} <NS>         CSI driver namespace
    ${CYAN}-l, --log-lines${NC} <N>       Log lines to collect (default: ${LOG_LINES})
    ${CYAN}--since${NC} <DUR>             Also bound pod logs by age (e.g. 72h, 24h); default: none
    ${CYAN}-a, --all-logs${NC}            Collect ALL logs (no line limit)
    ${CYAN}-t, --timeout${NC} <SEC>       SSH timeout (default: ${SSH_TIMEOUT})
    ${CYAN}-s, --skip-remote${NC}         Skip SSH remote collection
    ${CYAN}-p, --parallel${NC}            Enable parallel SSH collection
    ${CYAN}--workers${NC} <N>             Parallel workers (default: ${PARALLEL_WORKERS})
    ${CYAN}-n, --nodes${NC} <LIST>        Comma-separated nodes for remote forensics (replaces auto list)
    ${CYAN}-m, --mode${NC} <MODE>         Remote diag mode: all, nfs, block (default: all)
    ${CYAN}-v, --verbose${NC}             Verbose output with debug info
    ${CYAN}-q, --quiet${NC}               Minimal output
    ${CYAN}-h, --help${NC}                Show this help

${BOLD}FEATURES:${NC}
    • Failed pod analysis with categorized failure types
    • Storage chain tracing (Pod → PVC → PV → VolumeAttachment)
    • Unbound PVC and failed VolumeAttachment detection
    • CSI driver log collection
    • ${MAGENTA}NVMe/NVMeoF diagnostics${NC} (nvme list -v, list-subsys, multipath, path health)
    • ${MAGENTA}NFS diagnostics${NC} (mounts, mountstats, xprt, nfsstat, showmount, rpcinfo, PVC mapping)
    • Remote node forensics via SSH
    • Parallel SSH collection for faster multi-node gathering
    • Progress bars and step timing
    • JSON summary for automation

${BOLD}REMOTE SSH (env vars - never prompts):${NC}
    ${CYAN}CSI_SOS_SSH_USER${NC}   SSH login user on nodes (default: current local user)
    ${CYAN}CSI_SOS_SSH_PASS${NC}   SSH login password (only if SSH key auth fails)
    ${CYAN}CSI_SOS_SUDO_PASS${NC}  sudo password on the node (falls back to SSH pass)

    ${DIM}If SSH key auth + passwordless sudo work, no env vars are needed.${NC}
    ${DIM}With no usable login: remote skipped. With no sudo: partial (no-sudo) data.${NC}

${BOLD}EXAMPLES:${NC}
    ${DIM}# Interactive namespace selection, key-based SSH${NC}
    ${SCRIPT_NAME}

    ${DIM}# Fully automated with parallel SSH (env-supplied passwords)${NC}
    ${DIM}read -rs CSI_SOS_SUDO_PASS; export CSI_SOS_SUDO_PASS${NC}
    ${SCRIPT_NAME} -w default -c vast-csi -p --all-logs

    ${DIM}# Verbose debug output${NC}
    ${SCRIPT_NAME} -v

    ${DIM}# NFS forensics on two nodes only${NC}
    ${SCRIPT_NAME} -n worker-1,worker-2 -m nfs

    ${DIM}# Block/NVMe forensics on explicit nodes${NC}
    ${SCRIPT_NAME} -n worker-3,worker-4 -m block -p

EOF
    exit 0
}

#═══════════════════════════════════════════════════════════════════════════════
# Timing Functions
#═══════════════════════════════════════════════════════════════════════════════

get_timestamp_ms() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        python3 -c 'import time; print(int(time.time() * 1000))' 2>/dev/null || date +%s000
    else
        date +%s%3N 2>/dev/null || date +%s000
    fi
}

format_duration() {
    local ms=$1
    if [[ $ms -ge 60000 ]]; then
        local mins=$((ms / 60000))
        local secs=$(( (ms % 60000) / 1000 ))
        echo "${mins}m ${secs}s"
    elif [[ $ms -ge 1000 ]]; then
        local secs=$((ms / 1000))
        local tenths=$(( (ms % 1000) / 100 ))
        echo "${secs}.${tenths}s"
    else
        echo "${ms}ms"
    fi
}

start_timer() {
    local name="$1"
    STEP_TIMES["${name}_start"]=$(get_timestamp_ms)
}

LAST_DURATION=0

stop_timer() {
    local name="$1"
    local end=$(get_timestamp_ms)
    local start=${STEP_TIMES["${name}_start"]:-$end}
    local duration=$((end - start))

    STEP_TIMES["${name}_duration"]=$duration
    LAST_DURATION=$duration
}

get_timer() {
    local name="$1"
    echo "${STEP_TIMES["${name}_duration"]:-0}"
}


#═══════════════════════════════════════════════════════════════════════════════
# Progress Bar Functions
#═══════════════════════════════════════════════════════════════════════════════

show_progress() {
    local current=$1
    local total=$2
    local label="${3:-Progress}"
    local width=40

    [[ "$QUIET" == true ]] && return
    [[ $total -eq 0 ]] && total=1

    local percent=$((current * 100 / total))
    local filled=$((current * width / total))
    local empty=$((width - filled))

    local bar=""
    for ((i=0; i<filled; i++)); do bar+="█"; done
    for ((i=0; i<empty; i++)); do bar+="░"; done

    printf "\r  [${GREEN}%s${NC}${DIM}%s${NC}] %3d%% %s" \
        "${bar:0:$filled}" "${bar:$filled}" "$percent" "$label"
}

clear_progress() {
    [[ "$QUIET" == true ]] && return
    printf "\r%80s\r" ""
}

#═══════════════════════════════════════════════════════════════════════════════
# Logging Functions (Enhanced with colors)
#═══════════════════════════════════════════════════════════════════════════════

log_info() {
    [[ "$QUIET" == true ]] && return
    echo -e "  ${GREEN}✓${NC} $*"
}

log_warn() {
    echo -e "  ${YELLOW}⚠${NC} $*"
}

log_error() {
    echo -e "  ${RED}✗${NC} $*"
}

log_step() {
    [[ "$QUIET" == true ]] && return
    echo -e "  ${BLUE}→${NC} $*"
}

log_debug() {
    [[ "$VERBOSE" != true ]] && return
    echo -e "    ${DIM}[DEBUG]${NC} $*"
}

log_timed() {
    local msg="$1"
    local duration="$2"
    [[ "$QUIET" == true ]] && return
    local formatted=$(format_duration "$duration")
    local dots_len=$((60 - ${#msg}))
    [[ $dots_len -lt 3 ]] && dots_len=3
    local dots=$(printf '.%.0s' $(seq 1 $dots_len))
    echo -e "  ${BLUE}→${NC} ${msg} ${DIM}${dots}${NC} ${CYAN}${formatted}${NC}"
}

#═══════════════════════════════════════════════════════════════════════════════
# UI Components
#═══════════════════════════════════════════════════════════════════════════════

print_header() {
    [[ "$QUIET" == true ]] && return
    local title="$1" width=78 padding=$(( (78 - ${#1} - 2) / 2 ))
    echo ""
    echo -e "${YELLOW}╔$(printf '═%.0s' $(seq 1 $width))╗${NC}"
    echo -e "${YELLOW}║$(printf ' %.0s' $(seq 1 $padding))${BOLD}$title${NC}${YELLOW}$(printf ' %.0s' $(seq 1 $((width - padding - ${#title}))))║${NC}"
    echo -e "${YELLOW}╚$(printf '═%.0s' $(seq 1 $width))╝${NC}"
}

print_subheader() {
    [[ "$QUIET" == true ]] && return
    echo -e "\n  ${CYAN}┌─────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "  ${CYAN}│${NC} ${BOLD}$1${NC}"
    echo -e "  ${CYAN}└─────────────────────────────────────────────────────────────────────────┘${NC}"
}

print_banner() {
    [[ "$QUIET" == true ]] && return
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}                                                                              ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}   ${BOLD}██╗   ██╗ █████╗ ███████╗████████╗     ██████╗███████╗██╗${NC}               ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}   ${BOLD}██║   ██║██╔══██╗██╔════╝╚══██╔══╝    ██╔════╝██╔════╝██║${NC}               ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}   ${BOLD}██║   ██║███████║███████╗   ██║       ██║     ███████╗██║${NC}               ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}   ${BOLD}╚██╗ ██╔╝██╔══██║╚════██║   ██║       ██║     ╚════██║██║${NC}               ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}   ${BOLD} ╚████╔╝ ██║  ██║███████║   ██║       ╚██████╗███████║██║${NC}               ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}   ${BOLD}  ╚═══╝  ╚═╝  ╚═╝╚══════╝   ╚═╝        ╚═════╝╚══════╝╚═╝${NC}               ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}                                                                              ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}                     ${DIM}SOS Collector v${VERSION}${NC}                                   ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}              ${MAGENTA}with Integrated NVMe/NVMeoF Diagnostics${NC}                        ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}                                                                              ${CYAN}║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

#═══════════════════════════════════════════════════════════════════════════════
# File Formatting Functions
#═══════════════════════════════════════════════════════════════════════════════

format_table() {
    local input_file="$1" output_file="$2"
    [[ ! -s "$input_file" ]] && return 1
    local widths=() num_cols=0
    while IFS='|' read -ra cols; do
        local i=0
        for col in "${cols[@]}"; do
            col="${col## }"; col="${col%% }"
            local len=${#col}
            [[ -z "${widths[$i]}" ]] || (( len > widths[i] )) && widths[$i]=$len
            ((i++))
        done
        num_cols=$i
    done < "$input_file"
    [[ $num_cols -eq 0 ]] && return 1
    {
        local line_num=0
        while IFS='|' read -ra cols; do
            if [[ $line_num -eq 0 ]]; then
                printf "+"; for i in "${!widths[@]}"; do printf -- "-%.0s" $(seq 1 $((widths[i] + 2))); [[ $i -lt $((num_cols - 1)) ]] && printf "+" || printf "+\n"; done
            fi
            printf "|"; local i=0; for col in "${cols[@]}"; do col="${col## }"; col="${col%% }"; printf " %-${widths[$i]}s |" "$col"; ((i++)); done; echo ""
            if [[ $line_num -eq 0 ]]; then
                printf "+"; for i in "${!widths[@]}"; do printf -- "-%.0s" $(seq 1 $((widths[i] + 2))); [[ $i -lt $((num_cols - 1)) ]] && printf "+" || printf "+\n"; done
            fi
            ((line_num++))
        done < "$input_file"
        printf "+"; for i in "${!widths[@]}"; do printf -- "-%.0s" $(seq 1 $((widths[i] + 2))); [[ $i -lt $((num_cols - 1)) ]] && printf "+" || printf "+\n"; done
    } > "$output_file"
    return 0
}

write_section_header() {
    local file="$1" title="$2" timestamp="${3:-$(date '+%Y-%m-%d %H:%M:%S')}"
    local sep="+------------------------------------------------------------------------------+"
    # Build once, then emit. When the target is /dev/stdout we must NOT re-open it
    # via a redirect: callers use `{ write_section_header /dev/stdout; cmd; } > file`,
    # and re-opening /dev/stdout resets the file offset, clobbering ordering. Writing
    # to the inherited stdout keeps the shared offset so output is appended correctly.
    local body
    printf -v body '%s\n|  %-76s|\n|  %-76s|\n%s\n\n' \
        "$sep" "$title" "Generated: $timestamp" "$sep"
    if [[ "$file" == "/dev/stdout" || "$file" == "-" ]]; then
        printf '%s' "$body"
    else
        printf '%s' "$body" > "$file"
    fi
}

write_not_found() {
    local file="$1" resource="$2" reason="$3"
    {
        echo "+------------------------------------------------------------------------------+"
        printf "|  %-76s|\n" "$resource - NOT FOUND"
        echo "+------------------------------------------------------------------------------+"
        printf "|  %-76s|\n" "Reason: $reason"
        echo "+------------------------------------------------------------------------------+"
    } > "$file"
}

# Pointer stub when the same resource was already captured elsewhere.
write_resource_ref() {
    local file="$1" title="$2" ref_path="$3"
    local extra="${4:-}"
    {
        write_section_header "/dev/stdout" "$title" "$TIMESTAMP_HUMAN"
        echo "  Collected once — see: ${ref_path}"
        [[ -n "$extra" ]] && { echo ""; echo "$extra"; }
    } > "$file"
}

#═══════════════════════════════════════════════════════════════════════════════
# Argument Parsing
#═══════════════════════════════════════════════════════════════════════════════

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -w|--workload-ns) WORKLOAD_NS="$2"; shift 2 ;;
            -c|--csi-ns) CSI_NS="$2"; shift 2 ;;
            -l|--log-lines) LOG_LINES="$2"; shift 2 ;;
            --since) LOG_SINCE="$2"; shift 2 ;;
            -a|--all-logs) ALL_LOGS=true; shift ;;
            -t|--timeout) SSH_TIMEOUT="$2"; shift 2 ;;
            -s|--skip-remote) SKIP_REMOTE=true; shift ;;
            -p|--parallel) PARALLEL_SSH=true; shift ;;
            --workers) PARALLEL_WORKERS="$2"; shift 2 ;;
            -n|--nodes) NODES_OVERRIDE="$2"; shift 2 ;;
            -m|--mode)
                case "${2,,}" in
                    all|nfs|block) COLLECT_MODE="${2,,}" ;;
                    *) log_error "Invalid --mode: $2 (use all, nfs, or block)"; exit 1 ;;
                esac
                shift 2
                ;;
            -v|--verbose) VERBOSE=true; shift ;;
            -q|--quiet) QUIET=true; shift ;;
            -h|--help) usage ;;
            *) log_error "Unknown option: $1"; exit 1 ;;
        esac
    done
}

#═══════════════════════════════════════════════════════════════════════════════
# Setup and Cleanup
#═══════════════════════════════════════════════════════════════════════════════

setup_directories() {
    SCRIPT_START_TIME=$(get_timestamp_ms)
    TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ 2>/dev/null || date +%Y%m%d_%H%M%S)
    TIMESTAMP_HUMAN=$(date '+%Y-%m-%d %H:%M:%S')
    OUTPUT_DIR="VAST_CSI_SOS_${TIMESTAMP}"

    GLOBAL_DIR="${OUTPUT_DIR}/01_Cluster_Info"
    POD_DIR="${OUTPUT_DIR}/02_Failed_Pods"
    STORAGE_DIR="${OUTPUT_DIR}/03_Storage_Issues"
    NVME_DIR="${OUTPUT_DIR}/04_NVMe_Diagnostics"
    REMOTE_DIR="${OUTPUT_DIR}/05_Node_Forensics"
    CSI_LOG_DIR="${OUTPUT_DIR}/06_CSI_Logs"
    INTERNAL_DIR="${OUTPUT_DIR}/.internal"

    SUMMARY_FILE="${OUTPUT_DIR}/00_SUMMARY.txt"
    JSON_SUMMARY="${OUTPUT_DIR}/00_SUMMARY.json"
    STATS_FILE="${INTERNAL_DIR}/stats.txt"
    NODE_LIST="${INTERNAL_DIR}/affected_nodes.txt"

    mkdir -p "${GLOBAL_DIR}" \
        "${POD_DIR}/describes" \
        "${STORAGE_DIR}/Unbound_PVCs" "${STORAGE_DIR}/Failed_VAs" "${STORAGE_DIR}/Mount_Chain" \
        "${STORAGE_DIR}/PVC_Details" "${STORAGE_DIR}/PV_Details" \
        "${NVME_DIR}" \
        "${REMOTE_DIR}" \
        "${CSI_LOG_DIR}/Controllers" "${CSI_LOG_DIR}/Node_Daemons" \
        "${INTERNAL_DIR}"

    touch "${STATS_FILE}" "${NODE_LIST}"

    {
        echo "+------------------------------------------------------------------------------+"
        echo "|                    VAST CSI SOS COLLECTOR - SUMMARY                          |"
        echo "+------------------------------------------------------------------------------+"
        printf "|  %-28s %-47s|\n" "Generated:" "$TIMESTAMP_HUMAN"
        printf "|  %-28s %-47s|\n" "Hostname:" "$(hostname)"
        printf "|  %-28s %-47s|\n" "Version:" "$VERSION"
        echo "+------------------------------------------------------------------------------+"
        echo ""
    } > "${SUMMARY_FILE}"
}

cleanup() {
    rm -rf "${INTERNAL_DIR}" 2>/dev/null || true
}

interrupt() {
    echo -e "\n${YELLOW}Interrupted${NC}"
    cleanup
    exit 130
}

trap cleanup EXIT
trap interrupt INT TERM

#═══════════════════════════════════════════════════════════════════════════════
# Pre-flight Checks
#═══════════════════════════════════════════════════════════════════════════════

preflight_checks() {
    print_header "Step 0: Pre-flight Checks"
    start_timer "preflight"

    local missing=()
    for cmd in kubectl jq awk zip; do
        log_debug "Checking for command: $cmd"
        command -v "${cmd}" >/dev/null 2>&1 || missing+=("${cmd}")
    done
    (( ${#missing[@]} > 0 )) && { log_error "Missing: ${missing[*]}"; exit 1; }

    log_debug "Testing cluster connectivity..."
    if ! kubectl cluster-info &>/dev/null; then
        log_error "Cannot reach the Kubernetes cluster"
        log_warn  "Check: KUBECONFIG, current context (kubectl config current-context), and VPN/network"
        exit 1
    fi

    log_info "Required tools verified"
    log_info "Cluster connectivity confirmed"

    if [[ "$ALL_LOGS" == true ]]; then
        log_info "Log collection: ${GREEN}ALL available logs${NC}"
    else
        log_info "Log collection: ${LOG_LINES} lines per container"
    fi

    if command -v ssh >/dev/null 2>&1; then
        log_info "SSH available"
        if [[ "$PARALLEL_SSH" == true ]]; then
            log_info "Parallel SSH: ${GREEN}enabled${NC} (${PARALLEL_WORKERS} workers)"
        fi
    else
        log_warn "SSH not found"
        SKIP_REMOTE=true
    fi

    stop_timer "preflight"
    local duration=$LAST_DURATION
    echo ""
    echo -e "  ${BOLD}Output Directory:${NC} ${CYAN}${OUTPUT_DIR}${NC}"
    echo -e "  ${DIM}Pre-flight completed in $(format_duration $duration)${NC}"
    echo ""
}

#═══════════════════════════════════════════════════════════════════════════════
# Namespace Selection
#═══════════════════════════════════════════════════════════════════════════════

select_workload_namespace() {
    print_header "Step 1: Namespace Selection"
    start_timer "namespace"

    if [[ -n "${WORKLOAD_NS:-}" ]]; then
        log_debug "Using provided namespace: $WORKLOAD_NS"
        if kubectl get ns "${WORKLOAD_NS}" &>/dev/null; then
            log_info "Workload namespace: ${CYAN}${WORKLOAD_NS}${NC}"
            stop_timer "namespace" >/dev/null
            return 0
        else
            log_error "Namespace '${WORKLOAD_NS}' not found"
            exit 1
        fi
    fi

    print_subheader "Available Namespaces"

    log_debug "Fetching namespace list..."
    mapfile -t NS_LIST < <(kubectl get ns -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null)
    [[ ${#NS_LIST[@]} -eq 0 ]] && { log_error "No namespaces found"; exit 1; }

    echo ""
    for i in "${!NS_LIST[@]}"; do
        printf "    ${CYAN}%2d${NC}) %s\n" "$((i+1))" "${NS_LIST[$i]}"
    done

    echo ""
    read -rp "  Select WORKLOAD namespace [1-${#NS_LIST[@]}]: " choice

    if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#NS_LIST[@]} )); then
        WORKLOAD_NS="${NS_LIST[$((choice-1))]}"
        echo ""
        log_info "Workload namespace: ${CYAN}${WORKLOAD_NS}${NC}"
    else
        log_error "Invalid selection"
        exit 1
    fi

    stop_timer "namespace" >/dev/null
}

select_csi_namespace() {
    if [[ -n "${CSI_NS:-}" ]]; then
        log_debug "Using provided CSI namespace: $CSI_NS"
        if kubectl get ns "${CSI_NS}" &>/dev/null; then
            log_info "CSI namespace: ${CYAN}${CSI_NS}${NC}"
            return 0
        else
            log_error "Namespace '${CSI_NS}' not found"
            exit 1
        fi
    fi

    print_subheader "CSI Driver Detection"

    log_debug "Auto-detecting CSI namespaces..."
    mapfile -t CSI_LIST < <(kubectl get pods -A -o json 2>/dev/null | jq -r '
        .items[]
        | select(
            (.metadata.name | test("csi.*vast|vast.*csi"; "i")) or
            (.spec.containers[]?.image // "" | test("vast"; "i"))
        )
        | .metadata.namespace
    ' 2>/dev/null | sort -u)

    if [[ ${#CSI_LIST[@]} -eq 0 ]]; then
        log_warn "No CSI namespace auto-detected"
        read -rp "  Enter CSI namespace: " CSI_NS
    elif [[ ${#CSI_LIST[@]} -eq 1 ]]; then
        CSI_NS="${CSI_LIST[0]}"
        log_info "Auto-detected: ${CYAN}${CSI_NS}${NC}"
    else
        echo ""
        for i in "${!CSI_LIST[@]}"; do
            printf "    ${CYAN}%2d${NC}) %s\n" "$((i+1))" "${CSI_LIST[$i]}"
        done
        echo ""
        read -rp "  Select CSI namespace [1-${#CSI_LIST[@]}]: " choice
        if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#CSI_LIST[@]} )); then
            CSI_NS="${CSI_LIST[$((choice-1))]}"
            echo ""
            log_info "CSI namespace: ${CYAN}${CSI_NS}${NC}"
        else
            log_error "Invalid selection"
            exit 1
        fi
    fi
}

#═══════════════════════════════════════════════════════════════════════════════
# CSI Version Detection
#═══════════════════════════════════════════════════════════════════════════════

detect_csi_version() {
    print_header "Step 2: CSI Driver Version"
    start_timer "csi_version"

    local csi_release="UNKNOWN"

    log_debug "Checking Helm releases..."
    if command -v helm >/dev/null 2>&1; then
        local hc=$(helm list -n "$CSI_NS" -o json 2>/dev/null | jq -r '.[] | select(.chart | test("vast"; "i")) | "\(.chart)"' 2>/dev/null | head -1)
        if [[ -n "$hc" && "$hc" != "null" ]]; then
            csi_release="$hc"
            log_info "Helm: ${GREEN}${csi_release}${NC}"
        fi
    fi

    if [[ "$csi_release" == "UNKNOWN" ]]; then
        log_debug "Checking container images..."
        local ci=$(kubectl -n "$CSI_NS" get pods -o json 2>/dev/null | jq -r '[.items[].spec.containers[].image] | map(select(test("vast"; "i"))) | unique | .[0] // empty' 2>/dev/null)
        if [[ -n "$ci" ]]; then
            csi_release="$ci"
            log_info "Image: ${GREEN}${csi_release}${NC}"
        else
            log_warn "Version unknown"
        fi
    fi

    echo "$csi_release" > "${GLOBAL_DIR}/csi_version.txt"
    echo "CSI_VERSION=$csi_release" >> "${STATS_FILE}"

    stop_timer "csi_version"
    local duration=$LAST_DURATION
    log_debug "CSI version detection took $(format_duration $duration)"
}

#═══════════════════════════════════════════════════════════════════════════════
# Cluster Information Collection
#═══════════════════════════════════════════════════════════════════════════════

collect_cluster_info() {
    print_header "Step 3: Cluster Information"
    start_timer "cluster_info"

    local substep_start

    substep_start=$(get_timestamp_ms)
    { write_section_header "/dev/stdout" "CLUSTER NODES" "$TIMESTAMP_HUMAN"
      kubectl get nodes -o wide 2>/dev/null
    } > "${GLOBAL_DIR}/nodes.txt"
    log_timed "Nodes" $(($(get_timestamp_ms) - substep_start))

    substep_start=$(get_timestamp_ms)
    { write_section_header "/dev/stdout" "STORAGE CLASSES" "$TIMESTAMP_HUMAN"
      kubectl get sc -o wide 2>/dev/null
    } > "${GLOBAL_DIR}/storage_classes.txt"
    log_timed "Storage classes" $(($(get_timestamp_ms) - substep_start))

    substep_start=$(get_timestamp_ms)
    { write_section_header "/dev/stdout" "CSI DRIVERS" "$TIMESTAMP_HUMAN"
      kubectl get csidrivers -o wide 2>/dev/null
    } > "${GLOBAL_DIR}/csi_drivers.txt"
    log_timed "CSI drivers" $(($(get_timestamp_ms) - substep_start))

    substep_start=$(get_timestamp_ms)
    kubectl version --short 2>/dev/null > "${GLOBAL_DIR}/k8s_version.txt" || \
        kubectl version 2>/dev/null > "${GLOBAL_DIR}/k8s_version.txt"
    log_timed "Kubernetes version" $(($(get_timestamp_ms) - substep_start))

    # Single nodes fetch, reused for counts and the condition scan below.
    local nodes_json=$(kubectl get nodes -o json 2>/dev/null)
    local nc rc
    nc=$(echo "$nodes_json" | jq '.items | length' 2>/dev/null); nc=${nc:-0}
    rc=$(echo "$nodes_json" | jq '[.items[]
        | select(.status.conditions[]? | .type=="Ready" and .status=="True")] | length' 2>/dev/null)
    rc=${rc:-0}
    echo "NODES_TOTAL=$nc" >> "${STATS_FILE}"
    echo "NODES_READY=$rc" >> "${STATS_FILE}"

    #─────────────────────────────────────────────────────────────────────────────
    # Node condition scan: catch nodes that are crashed/unreachable right now.
    # A node whose Ready condition is False (kubelet says NotReady) or Unknown
    # (kubelet stopped reporting - node likely down) is added to NODE_LIST so
    # remote forensics is attempted (and, once it recovers, journalctl -b -1
    # pulls the previous-boot/crash logs).
    #─────────────────────────────────────────────────────────────────────────────
    substep_start=$(get_timestamp_ms)
    local node_cond_table="${INTERNAL_DIR}/node_conditions.raw"
    echo "NODE|READY|REASON|PRESSURE|LAST_TRANSITION" > "${node_cond_table}"
    local not_ready=0
    while IFS='|' read -r n ready reason pressure last_t; do
        [[ -z "$n" ]] && continue
        echo "${n}|${ready}|${reason:-N/A}|${pressure:-none}|${last_t:-N/A}" >> "${node_cond_table}"
        if [[ "$ready" != "True" ]]; then
            echo "$n" >> "${NODE_LIST}"
            ((not_ready++)) || true
        fi
    done < <(echo "$nodes_json" | jq -r '
        .items[]
        | . as $n
        | ([ $n.status.conditions[]? | select(.type=="Ready") ] | first) as $r
        | ([ $n.status.conditions[]?
             | select(.status=="True" and (.type|test("Pressure$"))) | .type ] | join(",")) as $p
        | "\($n.metadata.name)|\($r.status // "Unknown")|\($r.reason // "")|\($p)|\($r.lastTransitionTime // "")"
    ' 2>/dev/null)

    { write_section_header "/dev/stdout" "NODE CONDITIONS" "$TIMESTAMP_HUMAN"
    } > "${GLOBAL_DIR}/node_conditions.txt"
    format_table "${node_cond_table}" "${INTERNAL_DIR}/node_cond_fmt.txt" 2>/dev/null && \
        cat "${INTERNAL_DIR}/node_cond_fmt.txt" >> "${GLOBAL_DIR}/node_conditions.txt"
    echo "NODES_NOT_READY=${not_ready}" >> "${STATS_FILE}"
    if [[ $not_ready -gt 0 ]]; then
        log_warn "Nodes not Ready: ${RED}${not_ready}${NC} (added to remote forensics list)"
    fi
    log_timed "Node conditions" $(($(get_timestamp_ms) - substep_start))

    stop_timer "cluster_info"
    local duration=$LAST_DURATION
    log_info "Cluster info collected (${GREEN}${rc}/${nc}${NC} nodes ready) ${DIM}[$(format_duration $duration)]${NC}"
}

#═══════════════════════════════════════════════════════════════════════════════
# Failed Pods Analysis
#═══════════════════════════════════════════════════════════════════════════════

collect_failed_pods() {
    print_header "Step 4: Failed Pods Analysis"
    start_timer "failed_pods"

    log_debug "Fetching pods from namespace: $WORKLOAD_NS"
    local pods_json=$(kubectl get pods -n "${WORKLOAD_NS}" -o json 2>/dev/null)
    local total_pods=$(echo "$pods_json" | jq '.items | length')

    local master_table="${INTERNAL_DIR}/failed_pods.raw"
    echo "POD|STATUS|REASON|NODE|RESTARTS|AGE|HAS PVC|FAILURE TYPE" > "$master_table"

    local total_failed=0
    log_step "Scanning ${total_pods} pods for failures..."

    # Single jq pass classifies every pod and emits one pipe-delimited row per
    # FAILED pod: POD|STATUS|REASON|NODE|RESTARTS|AGE|HAS_PVC|FAILURE_TYPE.
    # has_pvc reflects the first volume; age uses >1d / >1h / else buckets.
    local failed_rows="${INTERNAL_DIR}/failed_pods_rows.tmp"
    echo "$pods_json" | jq -r '
        .items[]
        | {
            name:     .metadata.name,
            phase:    (.status.phase // "Unknown"),
            node:     (.spec.nodeName // "unscheduled"),
            created:  (.metadata.creationTimestamp // ""),
            has_pvc:  (if ((.spec.volumes // [])[0].persistentVolumeClaim) then "Yes" else "No" end),
            wait:     ([.status.containerStatuses[]?.state.waiting.reason // empty]    | first // ""),
            term:     ([.status.containerStatuses[]?.state.terminated.reason // empty] | first // ""),
            lastterm: ([.status.containerStatuses[]?.lastState.terminated.reason // empty] | first // ""),
            restarts: ([.status.containerStatuses[]?.restartCount // 0] | add // 0),
            evict:    (.status.reason // ""),
            sched:    ([.status.conditions[]? | select(.type=="PodScheduled" and .status=="False") | .reason] | first // ""),
            msg:      (.status.message // "Evicted")
          }
        | . as $p
        | (
            if   $p.evict == "Evicted"  then {ft:"EVICTED",   rs:($p.msg[0:30]), failed:true}
            elif $p.phase == "Pending"  then
                 (if   $p.wait == "ContainerCreating" then {ft:"MOUNT_ISSUE", rs:"ContainerCreating", failed:true}
                  elif ($p.wait|length) > 0           then {ft:"PENDING",     rs:$p.wait,            failed:true}
                  elif ($p.sched|length) > 0          then {ft:"SCHEDULING",  rs:$p.sched,           failed:true}
                  else {ft:"PENDING", rs:"Unknown", failed:true} end)
            elif $p.phase == "Running"  then
                 (if   $p.wait == "CrashLoopBackOff"                          then {ft:"CRASH_LOOP",    rs:"CrashLoopBackOff",        failed:true}
                  elif ($p.wait == "ImagePullBackOff" or $p.wait == "ErrImagePull") then {ft:"IMAGE_PULL", rs:$p.wait,               failed:true}
                  elif $p.lastterm == "OOMKilled"                            then {ft:"OOM_KILLED",    rs:"OOMKilled",               failed:true}
                  elif $p.restarts >= 5                                      then {ft:"HIGH_RESTARTS", rs:"\($p.restarts) restarts", failed:true}
                  else {ft:"", rs:"", failed:false} end)
            elif $p.phase == "Failed"   then
                 (if   ($p.term == "OOMKilled" or $p.lastterm == "OOMKilled") then {ft:"OOM_KILLED", rs:"OOMKilled", failed:true}
                  elif $p.term == "Error"                                     then {ft:"ERROR",      rs:"Error",     failed:true}
                  else {ft:"FAILED", rs:(if ($p.term|length) > 0 then $p.term else "Unknown" end), failed:true} end)
            elif $p.phase == "Unknown"  then {ft:"UNKNOWN", rs:"Unknown", failed:true}
            else {ft:"", rs:"", failed:false} end
          ) as $r
        | select($r.failed)
        | (if ($p.created | length) == 0 then "?"
           else (now - ($p.created | fromdateiso8601? // now)) as $sec
                | (if   $sec > 86400 then "\(($sec/86400)|floor)d"
                   elif $sec > 3600  then "\(($sec/3600)|floor)h"
                   else "\(($sec/60)|floor)m" end)
           end) as $age
        | [$p.name, $p.phase, $r.rs, $p.node, ($p.restarts|tostring), $age, $p.has_pvc, $r.ft]
        | join("|")
    ' 2>/dev/null > "${failed_rows}"

    # Append rows and run the per-failed-pod side effects (NODE_LIST + describe).
    while IFS='|' read -r f_pod f_phase f_reason f_node f_rest f_age f_haspvc f_ftype; do
        [[ -z "$f_pod" ]] && continue
        echo "${f_pod}|${f_phase}|${f_reason}|${f_node}|${f_rest}|${f_age}|${f_haspvc}|${f_ftype}" >> "$master_table"
        [[ "$f_node" != "unscheduled" && "$f_node" != "null" ]] && echo "$f_node" >> "${NODE_LIST}"
        log_debug "Collecting describe for failed pod: $f_pod"
        kubectl describe pod "$f_pod" -n "${WORKLOAD_NS}" > "${POD_DIR}/describes/${f_pod}.txt" 2>/dev/null
    done < "${failed_rows}"

    total_failed=$(( $(wc -l < "$master_table") - 1 ))

    if [[ $total_failed -le 0 ]]; then
        log_info "No failed pods found (${total_pods} pods checked)"
        echo "FAILED_PODS=0" >> "${STATS_FILE}"
        stop_timer "failed_pods"
        local duration=$LAST_DURATION
        log_debug "Failed pods analysis took $(format_duration $duration)"
        return
    fi

    local breakdown_table="${INTERNAL_DIR}/failure_breakdown.raw"
    echo "FAILURE TYPE|COUNT|DESCRIPTION" > "$breakdown_table"

    tail -n +2 "$master_table" | cut -d'|' -f8 | sort | uniq -c | sort -rn | while read -r count type; do
        local desc=""
        case "$type" in
            MOUNT_ISSUE)     desc="Container waiting for volume mount" ;;
            CRASH_LOOP)      desc="Container crashing repeatedly" ;;
            IMAGE_PULL)      desc="Cannot pull container image" ;;
            OOM_KILLED)      desc="Container killed due to memory limit" ;;
            ERROR)           desc="Container exited with error" ;;
            EVICTED)         desc="Pod evicted from node" ;;
            FAILED)          desc="Pod in Failed phase" ;;
            PENDING)         desc="Pod stuck in Pending" ;;
            SCHEDULING)      desc="Cannot schedule to any node" ;;
            HIGH_RESTARTS)   desc="Container restarting frequently" ;;
            UNKNOWN)         desc="Unknown pod state" ;;
            *)               desc="Other failure" ;;
        esac
        echo "${type}|${count}|${desc}" >> "$breakdown_table"
    done

    {
        write_section_header "/dev/stdout" "FAILED PODS SUMMARY" "$TIMESTAMP_HUMAN"
        echo "  Namespace:         ${WORKLOAD_NS}"
        echo "  Total Pods:        ${total_pods}"
        echo "  Failed Pods:       ${total_failed}"
        echo ""
        echo "  =============================================================================="
        echo "  FAILURE TYPE BREAKDOWN"
        echo "  =============================================================================="
        echo ""
    } > "${POD_DIR}/00_SUMMARY.txt"

    format_table "$breakdown_table" "${INTERNAL_DIR}/breakdown_fmt.txt" && \
        cat "${INTERNAL_DIR}/breakdown_fmt.txt" >> "${POD_DIR}/00_SUMMARY.txt"

    {
        echo ""
        echo "  =============================================================================="
        echo "  ALL FAILED PODS"
        echo "  =============================================================================="
        echo ""
    } >> "${POD_DIR}/00_SUMMARY.txt"

    format_table "$master_table" "${INTERNAL_DIR}/failed_pods_fmt.txt" && \
        cat "${INTERNAL_DIR}/failed_pods_fmt.txt" >> "${POD_DIR}/00_SUMMARY.txt"

    {
        echo ""
        echo "  =============================================================================="
        echo "  NEXT STEPS"
        echo "  =============================================================================="
        echo ""
        echo "  For storage-related issues (MOUNT_ISSUE, pods with HAS PVC=Yes):"
        echo "    -> Check 03_Storage_Issues/ for PVC/PV/VA analysis"
        echo "    -> Check 04_NVMe_Diagnostics/ for NVMe path and volume status"
        echo ""
        echo "  Individual pod descriptions are in:"
        echo "    -> describes/<pod-name>.txt"
        echo ""
    } >> "${POD_DIR}/00_SUMMARY.txt"

    echo "FAILED_PODS=$total_failed" >> "${STATS_FILE}"
    echo "TOTAL_PODS=$total_pods" >> "${STATS_FILE}"

    echo -e "  ${RED}!${NC} Failed pods: ${RED}${total_failed}${NC} out of ${total_pods}"

    print_subheader "Failure Breakdown"
    tail -n +2 "$master_table" | cut -d'|' -f8 | sort | uniq -c | sort -rn | while read -r count type; do
        case "$type" in
            MOUNT_ISSUE)   echo -e "    ${RED}${count}${NC} Mount issues (ContainerCreating)" ;;
            CRASH_LOOP)    echo -e "    ${RED}${count}${NC} CrashLoopBackOff" ;;
            IMAGE_PULL)    echo -e "    ${YELLOW}${count}${NC} ImagePullBackOff" ;;
            OOM_KILLED)    echo -e "    ${RED}${count}${NC} OOMKilled" ;;
            EVICTED)       echo -e "    ${YELLOW}${count}${NC} Evicted" ;;
            HIGH_RESTARTS) echo -e "    ${YELLOW}${count}${NC} High restart count" ;;
            *)             echo -e "    ${DIM}${count}${NC} ${type}" ;;
        esac
    done

    stop_timer "failed_pods"
    local duration=$LAST_DURATION
    echo ""
    echo -e "  ${DIM}Analysis completed in $(format_duration $duration)${NC}"
}

#═══════════════════════════════════════════════════════════════════════════════
# Storage Issues Collection
#═══════════════════════════════════════════════════════════════════════════════

collect_storage_issues() {
    print_header "Step 5: Storage Issues"
    start_timer "storage_issues"

    # Single fetch per resource type — reused across sub-steps below.
    local pvcs_json wl_pods_json vas_json
    pvcs_json=$(kubectl get pvc -n "${WORKLOAD_NS}" -o json 2>/dev/null)
    wl_pods_json=$(kubectl get pods -n "${WORKLOAD_NS}" -o json 2>/dev/null)
    vas_json=$(kubectl get volumeattachments -o json 2>/dev/null)

    # Helper for safe counting
    safe_count() {
        local file="$1"
        if [[ -s "$file" ]]; then
            echo $(( $(wc -l < "$file" 2>/dev/null || echo 1) - 1 ))
        else
            echo 0
        fi
    }

    #─────────────────────────────────────────────────────────────────────────────
    # 5a. PVC-PV Mapping
    #─────────────────────────────────────────────────────────────────────────────
    print_subheader "PVC-PV Mapping"

    local pvc_mapping="${INTERNAL_DIR}/pvc_pv_mapping.raw"
    echo "PVC|STATUS|STORAGE CLASS|SIZE|PV" > "$pvc_mapping"

    log_debug "Fetching PVCs from namespace: $WORKLOAD_NS"

    # Process substitution to avoid subshell variable loss
    while read -r pvc_obj; do
        [[ -z "$pvc_obj" ]] && continue

        local pvc=$(echo "$pvc_obj" | jq -r '.metadata.name // empty')
        local status=$(echo "$pvc_obj" | jq -r '.status.phase // "Unknown"')
        local sc=$(echo "$pvc_obj" | jq -r '.spec.storageClassName // "default"')
        local size=$(echo "$pvc_obj" | jq -r '.spec.resources.requests.storage // "N/A"')
        local pv=$(echo "$pvc_obj" | jq -r '.spec.volumeName // "N/A"')

        echo "${pvc}|${status}|${sc}|${size}|${pv}" >> "$pvc_mapping"

        { write_section_header "/dev/stdout" "PVC: ${pvc}" "$TIMESTAMP_HUMAN"
          kubectl describe pvc "$pvc" -n "${WORKLOAD_NS}" 2>/dev/null
        } > "${STORAGE_DIR}/PVC_Details/${pvc}.txt" 2>/dev/null

        if [[ "$pv" != "N/A" && "$pv" != "null" && -n "$pv" ]]; then
            { write_section_header "/dev/stdout" "PV: ${pv}" "$TIMESTAMP_HUMAN"
              kubectl describe pv "$pv" 2>/dev/null
            } > "${STORAGE_DIR}/PV_Details/${pv}.txt" 2>/dev/null
        fi
    done < <(echo "$pvcs_json" | jq -c '.items[]' 2>/dev/null)

    pvc_count=$(safe_count "$pvc_mapping")
    bound_count=$(grep -c "|Bound|" "$pvc_mapping" 2>/dev/null); bound_count=${bound_count:-0}

    {
        write_section_header "/dev/stdout" "PVC-PV MAPPING" "$TIMESTAMP_HUMAN"
        echo "  Total PVCs: $pvc_count"
        echo "  Bound:      $bound_count"
        echo "  Pending:    $((pvc_count - bound_count))"
        echo ""
    } > "${STORAGE_DIR}/01_pvc_pv_mapping.txt"

    format_table "$pvc_mapping" "${INTERNAL_DIR}/pvc_fmt.txt" 2>/dev/null && \
        cat "${INTERNAL_DIR}/pvc_fmt.txt" >> "${STORAGE_DIR}/01_pvc_pv_mapping.txt"

    log_step "PVC-PV mapping: ${pvc_count} PVCs (${bound_count} bound)"
    echo "PVCS_TOTAL=$pvc_count" >> "${STATS_FILE}"
    echo "PVCS_BOUND=$bound_count" >> "${STATS_FILE}"

    #─────────────────────────────────────────────────────────────────────────────
    # 5b. Unbound PVCs
    #─────────────────────────────────────────────────────────────────────────────
    print_subheader "Unbound PVCs"

    local unbound_dir="${STORAGE_DIR}/Unbound_PVCs"
    local pvc_table="${INTERNAL_DIR}/unbound_pvc.raw"
    echo "PVC|STATUS|STORAGE CLASS|SIZE|REQUESTED BY" > "$pvc_table"

    while read -r pvc_obj; do
        [[ -z "$pvc_obj" ]] && continue

        local pvc=$(echo "$pvc_obj" | jq -r '.metadata.name')
        local status=$(echo "$pvc_obj" | jq -r '.status.phase')
        local sc=$(echo "$pvc_obj" | jq -r '.spec.storageClassName // "default"')
        local size=$(echo "$pvc_obj" | jq -r '.spec.resources.requests.storage')

        log_debug "Found unbound PVC: $pvc (status: $status)"

        local requesting=$(echo "$wl_pods_json" | jq -r --arg pvc "$pvc" '
            [.items[] | select(.spec.volumes[]?.persistentVolumeClaim.claimName == $pvc) | .metadata.name] | join(",")
        ')

        echo "${pvc}|${status}|${sc}|${size}|${requesting:-none}" >> "$pvc_table"

        write_resource_ref "${unbound_dir}/${pvc}.txt" "UNBOUND PVC: ${pvc}" "../PVC_Details/${pvc}.txt" \
            "  Status: ${status}  StorageClass: ${sc}  Size: ${size}  Requested by: ${requesting:-none}"
    done < <(echo "$pvcs_json" | jq -c '.items[] | select(.status.phase != "Bound")' 2>/dev/null)

    unbound_count=$(safe_count "$pvc_table")

    if [[ $unbound_count -gt 0 ]]; then
        { write_section_header "/dev/stdout" "UNBOUND PVCs" "$TIMESTAMP_HUMAN"
          echo "  Found: ${unbound_count} PVC(s) not bound to a PV"
          echo ""
          echo "  Full PVC descriptions: ../PVC_Details/<pvc>.txt"
          echo "  These PVCs are waiting for a PersistentVolume."
          echo "  Common causes: StorageClass misconfiguration, provisioner issues."
        } > "${unbound_dir}/00_SUMMARY.txt"
        format_table "$pvc_table" "${INTERNAL_DIR}/unbound_fmt.txt" 2>/dev/null && \
            cat "${INTERNAL_DIR}/unbound_fmt.txt" >> "${unbound_dir}/00_SUMMARY.txt"
        echo -e "  ${RED}!${NC} Unbound PVCs: ${RED}${unbound_count}${NC}"
    else
        log_info "No unbound PVCs"
    fi
    echo "UNBOUND_PVCS=$unbound_count" >> "${STATS_FILE}"

    #─────────────────────────────────────────────────────────────────────────────
    # 5c. Failed VolumeAttachments
    #─────────────────────────────────────────────────────────────────────────────
    print_subheader "Failed VolumeAttachments"

    local va_dir="${STORAGE_DIR}/Failed_VAs"
    local va_table="${INTERNAL_DIR}/failed_va.raw"
    echo "VOLUMEATTACHMENT|PV|NODE|ATTACHED|ERROR" > "$va_table"

    while read -r va_obj; do
        [[ -z "$va_obj" ]] && continue

        local va=$(echo "$va_obj" | jq -r '.metadata.name')
        local pv=$(echo "$va_obj" | jq -r '.spec.source.persistentVolumeName // "-"')
        local node=$(echo "$va_obj" | jq -r '.spec.nodeName // "-"')
        local attached=$(echo "$va_obj" | jq -r '.status.attached // false')
        local err=$(echo "$va_obj" | jq -r '.status.attachError.message // .status.detachError.message // "pending"')

        [[ "$attached" == "true" && "$err" == "pending" ]] && continue

        log_debug "Found failed VA: $va (attached: $attached)"

        local err_short="${err:0:40}"
        [[ ${#err} -gt 40 ]] && err_short="${err_short}..."

        echo "${va}|${pv}|${node}|${attached}|${err_short}" >> "$va_table"

        [[ "$node" != "-" ]] && echo "$node" >> "${NODE_LIST}"

        { write_section_header "/dev/stdout" "FAILED VA: ${va}" "$TIMESTAMP_HUMAN"
          echo "PV:       ${pv}"
          echo "Node:     ${node}"
          echo "Attached: ${attached}"
          echo "Error:    ${err}"
          echo ""
          kubectl describe volumeattachment "$va" 2>/dev/null
        } > "${va_dir}/${va}_va.txt" 2>/dev/null

        if [[ "$pv" != "-" ]]; then
            if [[ -f "${STORAGE_DIR}/PV_Details/${pv}.txt" ]]; then
                write_resource_ref "${va_dir}/${va}_pv.txt" "PV: ${pv}" "../PV_Details/${pv}.txt"
            else
                { write_section_header "/dev/stdout" "PV: ${pv}" "$TIMESTAMP_HUMAN"
                  kubectl describe pv "$pv" 2>/dev/null
                } > "${va_dir}/${va}_pv.txt" 2>/dev/null
            fi

            local pvc_ref pvc_ns pvc_name
            pvc_ref=$(kubectl get pv "$pv" -o jsonpath='{.spec.claimRef.namespace}/{.spec.claimRef.name}' 2>/dev/null)
            if [[ -n "$pvc_ref" && "$pvc_ref" != "/" ]]; then
                pvc_ns="${pvc_ref%/*}"
                pvc_name="${pvc_ref#*/}"
                if [[ "$pvc_ns" == "$WORKLOAD_NS" && -f "${STORAGE_DIR}/PVC_Details/${pvc_name}.txt" ]]; then
                    write_resource_ref "${va_dir}/${va}_pvc.txt" "PVC: ${pvc_name}" "../PVC_Details/${pvc_name}.txt"
                else
                    { write_section_header "/dev/stdout" "PVC: ${pvc_name}" "$TIMESTAMP_HUMAN"
                      kubectl describe pvc "$pvc_name" -n "${pvc_ns}" 2>/dev/null
                    } > "${va_dir}/${va}_pvc.txt" 2>/dev/null
                fi
            fi
        fi
    done < <(echo "$vas_json" | jq -c '
        .items[] | select(.status.attached != true or .status.attachError != null or .status.detachError != null)
    ' 2>/dev/null)

    va_count=$(safe_count "$va_table")

    if [[ $va_count -gt 0 ]]; then
        { write_section_header "/dev/stdout" "FAILED VOLUMEATTACHMENTS" "$TIMESTAMP_HUMAN"
          echo "  Found: ${va_count} VolumeAttachment(s) with issues"
          echo ""
          echo "  VolumeAttachments bind PVs to Nodes."
          echo "  Errors here indicate storage attachment failures."
        } > "${va_dir}/00_SUMMARY.txt"
        format_table "$va_table" "${INTERNAL_DIR}/va_fmt.txt" 2>/dev/null && \
            cat "${INTERNAL_DIR}/va_fmt.txt" >> "${va_dir}/00_SUMMARY.txt"
        echo -e "  ${RED}!${NC} Failed VAs: ${RED}${va_count}${NC}"
    else
        log_info "No failed VolumeAttachments"
    fi
    echo "FAILED_VAS=$va_count" >> "${STATS_FILE}"

    #─────────────────────────────────────────────────────────────────────────────
    # 5d. Mount Chain Analysis
    #─────────────────────────────────────────────────────────────────────────────
    print_subheader "Mount Chain Analysis"

    local chain_dir="${STORAGE_DIR}/Mount_Chain"
    local chain_table="${INTERNAL_DIR}/mount_chain.raw"
    echo "POD|PVC|PVC STATUS|PV|PV STATUS|VA|VA STATUS|ISSUE" > "$chain_table"

    while read -r pod_obj; do
        [[ -z "$pod_obj" ]] && continue

        local pod=$(echo "$pod_obj" | jq -r '.metadata.name')
        local node=$(echo "$pod_obj" | jq -r '.spec.nodeName // "unscheduled"')

        log_debug "Tracing mount chain for pod: $pod"
        [[ "$node" != "unscheduled" ]] && echo "$node" >> "${NODE_LIST}"

        local pod_chain_dir="${chain_dir}/${pod}"
        mkdir -p "$pod_chain_dir"

        { write_section_header "/dev/stdout" "POD: ${pod}" "$TIMESTAMP_HUMAN"
          if [[ -f "${POD_DIR}/describes/${pod}.txt" ]]; then
              echo "  Collected once — see: ../../../02_Failed_Pods/describes/${pod}.txt"
          else
              kubectl describe pod "$pod" -n "${WORKLOAD_NS}" 2>/dev/null
          fi
        } > "${pod_chain_dir}/01_pod.txt" 2>/dev/null

        local pvc_num=1
        echo "$pod_obj" | jq -r '.spec.volumes[]? | select(.persistentVolumeClaim) | .persistentVolumeClaim.claimName' | while read -r pvc; do
            [[ -z "$pvc" ]] && continue

            local pvc_json
            pvc_json=$(echo "$pvcs_json" | jq -c --arg name "$pvc" '
                [.items[] | select(.metadata.name == $name)] | first // empty
            ' 2>/dev/null)
            local pvc_status=$(echo "$pvc_json" | jq -r '.status.phase // "Unknown"')
            local pv=$(echo "$pvc_json" | jq -r '.spec.volumeName // ""')

            write_resource_ref "${pod_chain_dir}/02_pvc_${pvc_num}.txt" "PVC: ${pvc}" \
                "../../PVC_Details/${pvc}.txt"

            local pv_status="N/A"
            local va_name="N/A"
            local va_status="N/A"
            local issue=""

            if [[ "$pvc_status" != "Bound" ]]; then
                issue="PVC not bound"
                write_not_found "${pod_chain_dir}/03_pv_${pvc_num}.txt" "PV" "PVC is not bound to any PV"
                write_not_found "${pod_chain_dir}/04_va_${pvc_num}.txt" "VA" "No PV exists"
            elif [[ -n "$pv" && "$pv" != "null" ]]; then
                pv_status=$(kubectl get pv "$pv" -o jsonpath='{.status.phase}' 2>/dev/null || echo "?")

                if [[ -f "${STORAGE_DIR}/PV_Details/${pv}.txt" ]]; then
                    write_resource_ref "${pod_chain_dir}/03_pv_${pvc_num}.txt" "PV: ${pv}" \
                        "../../PV_Details/${pv}.txt"
                else
                    { write_section_header "/dev/stdout" "PV: ${pv}" "$TIMESTAMP_HUMAN"
                      kubectl describe pv "$pv" 2>/dev/null
                    } > "${pod_chain_dir}/03_pv_${pvc_num}.txt" 2>/dev/null
                fi

                if [[ "$node" != "unscheduled" ]]; then
                    local va_json=$(echo "$vas_json" | jq -c --arg pv "$pv" --arg node "$node" '
                        [.items[] | select(.spec.source.persistentVolumeName == $pv and .spec.nodeName == $node)] | first // empty
                    ' 2>/dev/null)

                    if [[ -n "$va_json" && "$va_json" != "null" ]]; then
                        va_name=$(echo "$va_json" | jq -r '.metadata.name')
                        local attached=$(echo "$va_json" | jq -r '.status.attached // false')
                        local va_err=$(echo "$va_json" | jq -r '.status.attachError.message // ""')

                        if [[ "$attached" == "true" ]]; then
                            va_status="Attached"
                            issue="Attached but not mounted"
                        elif [[ -n "$va_err" && "$va_err" != "null" ]]; then
                            va_status="ERROR"
                            issue="${va_err:0:25}"
                        else
                            va_status="Pending"
                            issue="VA pending"
                        fi

                        { write_section_header "/dev/stdout" "VOLUMEATTACHMENT: ${va_name}" "$TIMESTAMP_HUMAN"
                          if [[ -f "${STORAGE_DIR}/Failed_VAs/${va_name}_va.txt" ]]; then
                              echo "  Collected once — see: ../../Failed_VAs/${va_name}_va.txt"
                          else
                              kubectl describe volumeattachment "$va_name" 2>/dev/null
                          fi
                        } > "${pod_chain_dir}/04_va_${pvc_num}.txt" 2>/dev/null
                    else
                        va_status="Not Found"
                        issue="No VA exists"
                        write_not_found "${pod_chain_dir}/04_va_${pvc_num}.txt" "VA" "No VolumeAttachment for PV ${pv} on node ${node}"
                    fi
                else
                    issue="Not scheduled"
                    write_not_found "${pod_chain_dir}/04_va_${pvc_num}.txt" "VA" "Pod not scheduled to a node"
                fi
            fi

            echo "${pod}|${pvc}|${pvc_status}|${pv:-N/A}|${pv_status}|${va_name}|${va_status}|${issue}" >> "$chain_table"
            ((pvc_num++))
        done

        # Summary file for this pod
        {
            echo "+------------------------------------------------------------------------------+"
            printf "|  %-76s|\n" "MOUNT CHAIN: ${pod}"
            echo "+------------------------------------------------------------------------------+"
            echo ""
            echo "  Storage chain: POD -> PVC -> PV -> VolumeAttachment"
            echo ""
            echo "  Files (cross-references point to canonical copies):"
            echo "    01_pod.txt       - Pod description or ref to 02_Failed_Pods/describes/"
            echo "    02_pvc_*.txt     - Ref to PVC_Details/"
            echo "    03_pv_*.txt      - Ref to PV_Details/ or NOT FOUND reason"
            echo "    04_va_*.txt      - Ref to Failed_VAs/ or VA description"
            echo ""
        } > "${pod_chain_dir}/00_SUMMARY.txt"
    done < <(echo "$wl_pods_json" | jq -c '
        .items[]
        | select(
            (.status.containerStatuses[]?.state.waiting.reason // "") == "ContainerCreating" or
            .status.phase == "Pending"
        )
        | select(.spec.volumes[]?.persistentVolumeClaim != null)
    ' 2>/dev/null)

    chain_count=$(safe_count "$chain_table")

    if [[ $chain_count -gt 0 ]]; then
        { write_section_header "/dev/stdout" "MOUNT CHAIN ANALYSIS" "$TIMESTAMP_HUMAN"
          echo "  Storage chains for pods with mount issues"
          echo ""
          echo "  Chain: POD -> PVC -> PV -> VolumeAttachment"
        } > "${chain_dir}/00_OVERVIEW.txt"
        format_table "$chain_table" "${INTERNAL_DIR}/chain_fmt.txt" 2>/dev/null && \
            cat "${INTERNAL_DIR}/chain_fmt.txt" >> "${chain_dir}/00_OVERVIEW.txt"
        log_step "Traced ${chain_count} mount chains"
    else
        log_info "No mount chain issues"
    fi
    echo "MOUNT_CHAINS=$chain_count" >> "${STATS_FILE}"

    print_subheader "Attach Topology (affected nodes)"
    local topo_dir="${STORAGE_DIR}/Attach_Topology"
    mkdir -p "${topo_dir}"

    declare -A topo_nodes
    local tn
    while read -r tn; do
        [[ -z "$tn" || "$tn" == "null" ]] && continue
        topo_nodes["$tn"]=1
    done < <(sort -u "${NODE_LIST}" 2>/dev/null)

    if [[ ${#topo_nodes[@]} -eq 0 ]]; then
        log_info "No affected nodes identified - skipping attach topology"
        echo "CSINODES_CHECKED=0" >> "${STATS_FILE}"
        echo "VAS_ON_AFFECTED=0" >> "${STATS_FILE}"
    else
        # CSINode driver-registration per affected node
        local csinode_table="${INTERNAL_DIR}/csinode.raw"
        echo "NODE|VAST DRIVER|NODE ID|ALL DRIVERS" > "${csinode_table}"
        local n cn_line all_drivers vast_reg node_id
        for n in "${!topo_nodes[@]}"; do
            if ! kubectl get csinode "$n" -o yaml > "${topo_dir}/csinode_${n}.yaml" 2>/dev/null; then
                echo "${n}|NOT FOUND|-|-" >> "${csinode_table}"
                continue
            fi
            # Detect the VAST driver by name regex (no hardcoded driver name).
            cn_line=$(kubectl get csinode "$n" -o json 2>/dev/null | jq -r '
                (.spec.drivers // []) as $d
                | ($d | map(.name) | join(",")) as $all
                | ($d | map(select(.name | test("vast"; "i"))) | first) as $v
                | "\(if ($all|length)>0 then $all else "none" end)\t\(if $v then "Yes" else "No" end)\t\($v.nodeID // "N/A")"')
            IFS=$'\t' read -r all_drivers vast_reg node_id <<< "$cn_line"
            echo "${n}|${vast_reg:-No}|${node_id:-N/A}|${all_drivers:-none}" >> "${csinode_table}"
        done
        write_section_header "${topo_dir}/00_CSINODE.txt" "CSINODE DRIVER REGISTRATION" "$TIMESTAMP_HUMAN"
        format_table "${csinode_table}" "${INTERNAL_DIR}/csinode_fmt.txt" 2>/dev/null && \
            cat "${INTERNAL_DIR}/csinode_fmt.txt" >> "${topo_dir}/00_CSINODE.txt"

        # VolumeAttachments whose node is in the affected set (full attach state)
        local va_all_table="${INTERNAL_DIR}/va_all.raw"
        echo "VOLUMEATTACHMENT|PV|NODE|ATTACHED|ATTACHER" > "${va_all_table}"
        local va_count_all=0
        local va_name va_pv va_node va_attached va_attacher
        while IFS='|' read -r va_name va_pv va_node va_attached va_attacher; do
            [[ -z "$va_name" ]] && continue
            [[ -z "${topo_nodes[$va_node]:-}" ]] && continue
            echo "${va_name}|${va_pv}|${va_node}|${va_attached}|${va_attacher}" >> "${va_all_table}"
            kubectl get volumeattachment "$va_name" -o yaml > "${topo_dir}/va_${va_name}.yaml" 2>/dev/null
            ((va_count_all++)) || true
        done < <(echo "$vas_json" | jq -r '
            .items[]
            | [ .metadata.name,
                (.spec.source.persistentVolumeName // "-"),
                (.spec.nodeName // "-"),
                (.status.attached // false | tostring),
                (.spec.attacher // "-") ]
            | join("|")')
        write_section_header "${topo_dir}/01_VOLUMEATTACHMENTS.txt" "VOLUMEATTACHMENTS ON AFFECTED NODES" "$TIMESTAMP_HUMAN"
        format_table "${va_all_table}" "${INTERNAL_DIR}/va_all_fmt.txt" 2>/dev/null && \
            cat "${INTERNAL_DIR}/va_all_fmt.txt" >> "${topo_dir}/01_VOLUMEATTACHMENTS.txt"

        log_info "Attach topology: ${#topo_nodes[@]} node(s), ${va_count_all} VolumeAttachment(s)"
        echo "CSINODES_CHECKED=${#topo_nodes[@]}" >> "${STATS_FILE}"
        echo "VAS_ON_AFFECTED=${va_count_all}" >> "${STATS_FILE}"
    fi

    stop_timer "storage_issues"
    local duration=$LAST_DURATION
    echo ""
    echo -e "  ${DIM}Storage analysis completed in $(format_duration $duration)${NC}"
}

#═══════════════════════════════════════════════════════════════════════════════
# Cluster Events Collection
#
# Events are the only control-plane record of TRANSIENT incidents: a node that
# crashed/rebooted and then recovered still shows up here until the events age
# out (default TTL ~1h, cluster-dependent). We dump events broadly and also
# scan node-scoped events for reboot/OOM/not-ready reasons, adding those nodes
# to NODE_LIST so remote forensics (and journalctl -b -1) runs on them.
#═══════════════════════════════════════════════════════════════════════════════

collect_cluster_events() {
    print_header "Step 6: Cluster Events"
    start_timer "events"

    # One API fetch — table dump + crash/reboot scan (no per-namespace duplicate files).
    local events_json
    events_json=$(kubectl get events -A -o json 2>/dev/null)

    {
        write_section_header "/dev/stdout" "EVENTS - ALL NAMESPACES" "$TIMESTAMP_HUMAN"
        echo "  Workload namespace (${WORKLOAD_NS}) and CSI namespace (${CSI_NS}) events are included."
        echo "  Filter by namespace column below instead of separate files."
        echo ""
        printf '%s\n' "LAST SEEN	NAMESPACE	TYPE	REASON	OBJECT	MESSAGE"
        echo "$events_json" | jq -r '
            [.items[]
             | {
                 last: (.lastTimestamp // .eventTime // ""),
                 ns: (.involvedObject.namespace // ""),
                 age: (.metadata.creationTimestamp // ""),
                 type: (.type // ""),
                 reason: (.reason // ""),
                 obj: "\(.involvedObject.kind // "")/\(.involvedObject.name // "")",
                 msg: (.message // "")
               }
            ]
            | sort_by(.last)
            | .[]
            | [.last, .ns, .type, .reason, .obj, .msg] | @tsv
        ' 2>/dev/null
    } > "${GLOBAL_DIR}/events_all.txt"

    # Node-scoped events that indicate a crash/reboot/pressure. involvedObject.name
    # is the node name; add it to NODE_LIST. (Reasons per kubelet/node-controller.)
    local crash_table="${INTERNAL_DIR}/node_events.raw"
    echo "NODE|REASON|COUNT|LAST_SEEN|MESSAGE" > "${crash_table}"
    local crash_nodes=0
    while IFS='|' read -r n reason count last msg; do
        [[ -z "$n" ]] && continue
        echo "${n}|${reason}|${count}|${last}|${msg:0:50}" >> "${crash_table}"
        echo "$n" >> "${NODE_LIST}"
        ((crash_nodes++)) || true
    done < <(echo "$events_json" | jq -r '
        .items[]
        | select(.involvedObject.kind == "Node")
        | select(.reason | test("Rebooted|NodeNotReady|Starting|SystemOOM|OOMKilling|KernelOops|NodeHasDiskPressure"; "i"))
        | "\(.involvedObject.name)|\(.reason)|\(.count // 1)|\(.lastTimestamp // .eventTime // "")|\((.message // "") | gsub("[|\n]"; " "))"
    ' 2>/dev/null)

    write_section_header "${GLOBAL_DIR}/node_crash_events.txt" "NODE CRASH/REBOOT EVENTS" "$TIMESTAMP_HUMAN"
    {
      echo "  Node-scoped events indicating reboot/crash/OOM/pressure."
      echo "  (Subject to Kubernetes event retention, default ~1h.)"
      echo ""
    } >> "${GLOBAL_DIR}/node_crash_events.txt"
    format_table "${crash_table}" "${INTERNAL_DIR}/node_events_fmt.txt" 2>/dev/null && \
        cat "${INTERNAL_DIR}/node_events_fmt.txt" >> "${GLOBAL_DIR}/node_crash_events.txt"

    echo "NODE_CRASH_EVENTS=${crash_nodes}" >> "${STATS_FILE}"
    if [[ $crash_nodes -gt 0 ]]; then
        log_warn "Node crash/reboot events: ${RED}${crash_nodes}${NC} (nodes added to remote forensics list)"
    else
        log_info "No node crash/reboot events found (within retention window)"
    fi

    stop_timer "events"
    log_info "Events collected ${DIM}[$(format_duration $LAST_DURATION)]${NC}"
}

#═══════════════════════════════════════════════════════════════════════════════
# CSI Logs Collection
#═══════════════════════════════════════════════════════════════════════════════

collect_csi_logs() {
    print_header "Step 7: CSI Driver Logs"
    start_timer "csi_logs"

    if [[ "$ALL_LOGS" == true ]]; then
        log_info "Collecting ${GREEN}ALL${NC} available logs (no line limit)"
    else
        log_step "Collecting last ${LOG_LINES} lines per container"
    fi

    { write_section_header "/dev/stdout" "CSI PODS" "$TIMESTAMP_HUMAN"
      kubectl get pods -n "${CSI_NS}" -o wide 2>/dev/null
    } > "${CSI_LOG_DIR}/csi_pods.txt"

    local csi_pods_json
    csi_pods_json=$(kubectl get pods -n "${CSI_NS}" -o json 2>/dev/null)

    #─────────────────────────────────────────────────────────────────────────────
    # CSI pod health scan (runs FIRST, so it can influence log scoping below)
    #
    # Flag CSI pods that restarted / crashed / OOM'd / are not Ready. For the
    # NODE driver (a DaemonSet - identified by ownerReferences.kind == DaemonSet,
    # not by name) we add the pod's node to NODE_LIST so node forensics runs there,
    # and remember it (unhealthy_daemon_nodes) so we ALWAYS collect that daemon's
    # own logs below even if no workload on that node failed. Controller pods
    # (ReplicaSet-owned) are log-only - they do no kernel-facing work.
    #─────────────────────────────────────────────────────────────────────────────
    local health_table="${INTERNAL_DIR}/csi_health.raw"
    echo "POD|KIND|NODE|RESTARTS|READY|REASON" > "${health_table}"
    local unhealthy=0
    declare -A unhealthy_daemon_nodes
    while IFS='|' read -r pod kind node restarts ready reason; do
        [[ -z "$pod" ]] && continue
        echo "${pod}|${kind}|${node:-N/A}|${restarts}|${ready}|${reason}" >> "${health_table}"
        ((unhealthy++)) || true
        # Only DaemonSet (node driver) pods drive node forensics.
        if [[ "$kind" == "DaemonSet" && -n "$node" && "$node" != "null" ]]; then
            echo "$node" >> "${NODE_LIST}"
            unhealthy_daemon_nodes["$node"]=1
        fi
    done < <(echo "$csi_pods_json" | jq -r '
        .items[]
        | select((.metadata.name | test("vast|csi"; "i")))
        | . as $p
        | (([ $p.status.containerStatuses[]?.restartCount // 0 ] | add) // 0) as $restarts
        | ([ $p.status.containerStatuses[]? | select(.ready != true) ] | length) as $notready
        | ([ $p.status.containerStatuses[]?.state.waiting.reason // empty ] | first // "") as $waiting
        | ([ $p.status.containerStatuses[]?.lastState.terminated.reason // empty ] | first // "") as $lastterm
        | ([ $p.status.containerStatuses[]?.state.terminated.reason // empty ] | first // "") as $term
        # Affected if: restarted, not all ready, OOM/crash/error waiting or terminated, or bad phase.
        | select(
            $restarts > 0
            or ($p.status.phase != "Running" and $p.status.phase != "Succeeded")
            or $notready > 0
            or ($waiting | test("CrashLoopBackOff|ImagePullBackOff|ErrImagePull|CreateContainerError"))
            or ($lastterm | test("OOMKilled|Error"))
            or ($term | test("OOMKilled|Error"))
          )
        | "\($p.metadata.name)|\(($p.metadata.ownerReferences[0].kind) // "Pod")|\($p.spec.nodeName // "")|\($restarts)|\(if $notready>0 then "No" else "Yes" end)|\([ $waiting, $lastterm, $term ] | map(select(. != "")) | first // "running")"
    ' 2>/dev/null)

    if [[ $unhealthy -gt 0 ]]; then
        write_section_header "${CSI_LOG_DIR}/CSI_HEALTH.txt" "CSI POD HEALTH - AFFECTED PODS" "$TIMESTAMP_HUMAN"
        {
          echo "  CSI pods that restarted / crashed / OOM'd / are not Ready."
          echo "  DaemonSet (node driver) pods also trigger node forensics on their host."
          echo ""
        } >> "${CSI_LOG_DIR}/CSI_HEALTH.txt"
        format_table "${health_table}" "${INTERNAL_DIR}/csi_health_fmt.txt" 2>/dev/null && \
            cat "${INTERNAL_DIR}/csi_health_fmt.txt" >> "${CSI_LOG_DIR}/CSI_HEALTH.txt"
        log_warn "Unhealthy CSI pods: ${RED}${unhealthy}${NC} (see 06_CSI_Logs/CSI_HEALTH.txt)"
    else
        log_info "All CSI pods healthy"
    fi
    echo "CSI_PODS_UNHEALTHY=${unhealthy}" >> "${STATS_FILE}"

    #─────────────────────────────────────────────────────────────────────────────
    # Affected-node set = nodes gathered by prior steps (failing pods, storage,
    # node conditions, events) UNION nodes whose CSI node-daemon is unhealthy.
    # Used to scope node-daemon log collection below.
    #─────────────────────────────────────────────────────────────────────────────
    sort -u "${NODE_LIST}" -o "${NODE_LIST}" 2>/dev/null || true
    declare -A affected_nodes
    local affected_count=0 an
    while read -r an; do
        [[ -z "$an" || "$an" == "null" ]] && continue
        affected_nodes["$an"]=1
        ((affected_count++)) || true
    done < "${NODE_LIST}"
    log_info "Affected nodes identified: ${affected_count}"

    #─────────────────────────────────────────────────────────────────────────────
    # CSI pod selection:
    #   Controllers (ReplicaSet-owned) -> ALWAYS collected.
    #   Node DaemonSet pods            -> collected only when their node is in the
    #                                     affected set (which already includes any
    #                                     node running an unhealthy CSI daemon).
    # Pods stored as "name<TAB>node<TAB>owner" so the collection loop needs no
    # extra per-pod kubectl calls to learn node/owner.
    #─────────────────────────────────────────────────────────────────────────────
    local selected="${INTERNAL_DIR}/csi_selected.tsv"
    : > "${selected}"
    local selected_controllers=0 selected_node_pods=0
    local s_pod s_node s_owner
    while IFS=$'\t' read -r s_pod s_node s_owner; do
        [[ -z "$s_pod" ]] && continue
        if [[ "$s_owner" == "ReplicaSet" ]]; then
            printf '%s\t%s\t%s\n' "$s_pod" "$s_node" "$s_owner" >> "${selected}"
            ((selected_controllers++)) || true
        elif [[ "$s_owner" == "DaemonSet" ]]; then
            if [[ -n "${affected_nodes[$s_node]:-}" ]]; then
                printf '%s\t%s\t%s\n' "$s_pod" "$s_node" "$s_owner" >> "${selected}"
                ((selected_node_pods++)) || true
            fi
        fi
    done < <(echo "$csi_pods_json" | jq -r '
        .items[]
        | select(.metadata.name | test("vast|csi"; "i"))
        | [ .metadata.name, (.spec.nodeName // ""), (.metadata.ownerReferences[0].kind // "") ]
        | @tsv')

    local total_pods pod_count=0
    total_pods=$(grep -c . "${selected}" 2>/dev/null); total_pods=${total_pods:-0}

    if [[ "${total_pods}" -eq 0 ]]; then
        log_warn "No CSI pods selected for log collection"
        echo "CSI_PODS=0" >> "${STATS_FILE}"
        stop_timer "csi_logs" >/dev/null
        return
    fi
    log_info "CSI pods selected: ${total_pods} (controllers: ${selected_controllers}, node-daemons: ${selected_node_pods})"

    # Build kubectl logs flags once (avoids duplicating the ALL_LOGS/--since branches).
    local -a tail_arg=() since_arg=()
    [[ "$ALL_LOGS" != true ]] && tail_arg=(--tail="${LOG_LINES}")
    [[ -n "$LOG_SINCE" ]] && since_arg=(--since="${LOG_SINCE}")

    local pod node owner log_dir
    while IFS=$'\t' read -r pod node owner; do
        [[ -z "$pod" ]] && continue
        ((pod_count++)) || true
        show_progress $pod_count $total_pods "Collecting logs from $pod..."

        if [[ "$owner" == "ReplicaSet" ]]; then
            log_dir="${CSI_LOG_DIR}/Controllers"
        else
            log_dir="${CSI_LOG_DIR}/Node_Daemons/${node:-unknown}"
        fi
        mkdir -p "${log_dir}"

        local containers=$(kubectl get pod "$pod" -n "${CSI_NS}" -o jsonpath='{.spec.containers[*].name}' 2>/dev/null)

        for c in ${containers}; do
            log_debug "Collecting logs: $pod / $c"
            {
                echo "+------------------------------------------------------------------------------+"
                printf "|  %-76s|\n" "Pod: $pod"
                printf "|  %-76s|\n" "Container: $c"
                printf "|  %-76s|\n" "Node: ${node:-N/A}"
                echo "+------------------------------------------------------------------------------+"
                echo ""
                kubectl logs "$pod" -n "${CSI_NS}" -c "$c" "${tail_arg[@]}" "${since_arg[@]}" 2>/dev/null \
                    || echo "Failed to get logs"
            } > "${log_dir}/${pod}_${c}.log"

            local rc=$(kubectl get pod "$pod" -n "${CSI_NS}" -o jsonpath="{.status.containerStatuses[?(@.name=='${c}')].restartCount}" 2>/dev/null)
            if [[ -n "${rc}" && "${rc}" -gt 0 ]]; then
                log_debug "Collecting previous logs: $pod / $c (restarts: $rc)"
                {
                    echo "+------------------------------------------------------------------------------+"
                    printf "|  %-76s|\n" "PREVIOUS LOGS (${rc} restarts)"
                    echo "+------------------------------------------------------------------------------+"
                    echo ""
                    kubectl logs "$pod" -n "${CSI_NS}" -c "$c" --previous "${tail_arg[@]}" "${since_arg[@]}" 2>/dev/null \
                        || echo "No previous logs"
                } > "${log_dir}/${pod}_${c}_previous.log"
            fi
        done

        kubectl describe pod "$pod" -n "${CSI_NS}" > "${log_dir}/${pod}_describe.txt" 2>/dev/null
    done < "${selected}"

    clear_progress

    echo "CSI_PODS=$pod_count" >> "${STATS_FILE}"

    stop_timer "csi_logs"
    local duration=$LAST_DURATION
    log_info "Collected from ${GREEN}${pod_count}${NC} CSI pods ${DIM}[$(format_duration $duration)]${NC}"
}

#═══════════════════════════════════════════════════════════════════════════════
# Remote Execution Helper
#
# Runs the NVMe diagnostic script on a remote node. Relies on bash dynamic
# scoping to read auth state set by collect_nvme_diagnostics:
#   ssh_user, ssh_pass (login), sudo_pass (sudo), nvme_script, SSH_TIMEOUT,
#   SSH_USE_PASS, SUDO_KIND
#
# SSH_USE_PASS: true -> login via sshpass (password); false -> login via key
# SUDO_KIND:    nopass -> sudo -n ; pass -> sudo -S (password fed on stdin) ;
#               none   -> run as the login user without sudo
#═══════════════════════════════════════════════════════════════════════════════

exec_remote() {
    local ip="$1" out="$2" err="$3"
    local rc=0 remote_cmd feed

    case "$SUDO_KIND" in
        nopass) remote_cmd='sudo -n bash -s' ;;
        pass)   remote_cmd='sudo -S -p "" bash -s' ;;
        *)      remote_cmd='bash -s' ;;
    esac

    # When sudo needs a password, prepend it as the first stdin line for sudo -S.
    # Uses the dedicated sudo password (separate from the SSH login password).
    if [[ "$SUDO_KIND" == "pass" ]]; then
        feed=$(mktemp)
        { printf '%s\n' "$sudo_pass"; cat "$nvme_script"; } > "$feed"
    else
        feed="$nvme_script"
    fi

    if [[ "$SSH_USE_PASS" == true ]]; then
        # sshpass -e reads the login password from $SSHPASS (not argv) so it is
        # not visible in the process list.
        SSHPASS="${ssh_pass}" timeout "${SSH_TIMEOUT}" sshpass -e ssh \
            -o ConnectTimeout=10 \
            -o StrictHostKeyChecking=accept-new \
            -o LogLevel=ERROR \
            "${ssh_user}@${ip}" "$remote_cmd" < "$feed" > "$out" 2>"$err" || rc=$?
    else
        timeout "${SSH_TIMEOUT}" ssh \
            -o ConnectTimeout=10 \
            -o StrictHostKeyChecking=accept-new \
            -o BatchMode=yes \
            -o LogLevel=ERROR \
            "${ssh_user}@${ip}" "$remote_cmd" < "$feed" > "$out" 2>"$err" || rc=$?
    fi

    [[ "$SUDO_KIND" == "pass" ]] && rm -f "$feed"
    return $rc
}

#═══════════════════════════════════════════════════════════════════════════════
# Node List Selection (--nodes overrides auto-detected affected nodes)
#═══════════════════════════════════════════════════════════════════════════════

finalize_node_list() {
    if [[ -z "$NODES_OVERRIDE" ]]; then
        echo "NODE_LIST_SOURCE=auto" >> "${STATS_FILE}"
        return 0
    fi

    local node invalid=0 count
    : > "${NODE_LIST}"
    IFS=',' read -ra _nodes <<< "$NODES_OVERRIDE"
    for node in "${_nodes[@]}"; do
        node="${node#"${node%%[![:space:]]*}"}"
        node="${node%"${node##*[![:space:]]}"}"
        [[ -z "$node" ]] && continue
        if kubectl get node "$node" &>/dev/null; then
            echo "$node" >> "${NODE_LIST}"
        else
            log_warn "Node not found in cluster, skipping: ${node}"
            ((invalid++)) || true
        fi
    done
    sort -u "${NODE_LIST}" -o "${NODE_LIST}" 2>/dev/null || true
    count=$(grep -c . "${NODE_LIST}" 2>/dev/null); count=${count:-0}
    echo "NODE_LIST_SOURCE=explicit" >> "${STATS_FILE}"
    if [[ $count -eq 0 ]]; then
        log_warn "No valid nodes in --nodes list; skipping remote forensics (K8s collection continues)"
        return 0
    fi
    log_info "Using explicit node list: ${count} node(s)${invalid:+ (${invalid} invalid skipped)}"
    return 0
}

#═══════════════════════════════════════════════════════════════════════════════
# Per-node Collection (safe to run as a background worker)
#
# Writes a tab-separated result line to RESULTS_FILE instead of mutating shared
# counters, so it can be invoked concurrently. Reads globals/caller-locals:
#   NVME_DIR, REMOTE_DIR, INTERNAL_DIR, TIMESTAMP_HUMAN, ssh_user, RESULTS_FILE, COLLECT_MODE
#═══════════════════════════════════════════════════════════════════════════════

collect_node() {
    local node="$1"
    local ip node_start node_nvme_dir node_remote_dir tmp_file ssh_err ssh_rc=0

    ip=$(kubectl get node "${node}" -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null | awk '{print $1}')
    if [[ -z "${ip}" ]]; then
        echo -e "  ${RED}✗${NC} ${node}: No IP address found"
        printf 'FAIL\t-\t%s\n' "$node" >> "${RESULTS_FILE}"
        return 1
    fi

    node_start=$(get_timestamp_ms)

    node_nvme_dir="${NVME_DIR}/${node}"
    node_remote_dir="${REMOTE_DIR}/${node}"
    tmp_file="${INTERNAL_DIR}/nvme_output_${node}.tmp"
    ssh_err="${INTERNAL_DIR}/ssh_error_${node}.log"
    mkdir -p "${node_remote_dir}"
    [[ "$COLLECT_MODE" != "nfs" ]] && mkdir -p "${node_nvme_dir}"

    # The collector runs on the control-plane node, which has no NVMe modules
    # (NVMe/NVMeoF lives on worker nodes where the block pods run). So there is
    # nothing to diagnose locally - skip the node we are running on rather than
    # SSH-ing to ourselves.
    local local_node
    local_node=$(hostname -s 2>/dev/null)
    if [[ -n "$local_node" && ( "$node" == "$local_node" || "$node" == "$(hostname 2>/dev/null)" ) ]]; then
        echo -e "  ${BLUE}▶${NC} ${BOLD}${node}${NC} (${ip}) ${CYAN}[local]${NC}"
        echo -e "    ${YELLOW}↷${NC} ${node}: Local collector node (control-plane, no NVMe) - skipping diagnostics"
        printf 'SKIP\t-\t%s\n' "$node" >> "${RESULTS_FILE}"
        return 0
    fi

    echo -e "  ${BLUE}▶${NC} ${BOLD}${node}${NC} (${ip}) as ${ssh_user}"
    exec_remote "${ip}" "${tmp_file}" "${ssh_err}" || ssh_rc=$?

    if [[ $ssh_rc -eq 0 && -s "${tmp_file}" ]]; then
        # Parse output into separate files (best-effort; never abort collector)
        local parse_rc=0
        awk -v nvmedir="${node_nvme_dir}" -v remotedir="${node_remote_dir}" -v mode="${COLLECT_MODE}" '
            /^===SYSTEM_INFO===/{f=remotedir"/system_info.txt";next}
            /^===NVME_HEALTH_SUMMARY===/{f=(mode=="nfs"?"":nvmedir"/00_health_summary.txt");next}
            /^===NVME_VOLUME_MAPPING===/{f=(mode=="nfs"?"":nvmedir"/01_volume_mapping.raw");next}
            /^===NVME_PATH_STATUS===/{f=(mode=="nfs"?"":nvmedir"/02_path_status.raw");next}
            /^===NVME_MULTIPATH_VIEW===/{f=(mode=="nfs"?"":nvmedir"/03_multipath_view.raw");next}
            /^===NVME_SUBSYSTEMS===/{f=(mode=="nfs"?"":nvmedir"/nvme_subsystems.txt");next}
            /^===NVME_LIST===/{f=(mode=="nfs"?"":nvmedir"/nvme_list.txt");next}
            /^===NVME_LIST_VERBOSE===/{f=(mode=="nfs"?"":nvmedir"/nvme_list_verbose.txt");next}
            /^===NVME_EVENT_HISTORY===/{f=(mode=="nfs"?"":nvmedir"/04_nvme_event_history.raw");next}
            /^===PVC_NVME_MAPPING===/{f=(mode=="nfs"?"":nvmedir"/pvc_nvme_mapping.raw");next}
            /^===LOCAL_NVME_PCIE===/{f=(mode=="nfs"?"":nvmedir"/local_nvme_pcie.raw");next}
            /^===NFS_MOUNTS===/{f=(mode=="block"?"":remotedir"/nfs_mounts.raw");next}
            /^===NFS_RPCINFO===/{f=(mode=="block"?"":remotedir"/nfs_rpcinfo.txt");next}
            /^===NFS_SHOWMOUNT===/{f=(mode=="block"?"":remotedir"/nfs_showmount.txt");next}
            /^===NFS_NFSSTAT===/{f=(mode=="block"?"":remotedir"/nfs_nfsstat.txt");next}
            /^===NFS_NFSSTAT_CLIENT===/{f=(mode=="block"?"":remotedir"/nfs_nfsstat_client.txt");next}
            /^===NFS_MOUNTSTATS===/{f=(mode=="block"?"":remotedir"/nfs_mountstats.txt");next}
            /^===NFS_XPRT_STATS===/{f=(mode=="block"?"":remotedir"/nfs_xprt_stats.raw");next}
            /^===NFS_TCP_CONNECTIONS===/{f=(mode=="block"?"":remotedir"/nfs_tcp_connections.raw");next}
            /^===VAST_CSI_META===/{f=(mode=="block"?"":remotedir"/vast_csi_meta.raw");next}
            /^===NFS_EVENT_HISTORY===/{f=(mode=="block"?"":remotedir"/nfs_event_history.raw");next}
            /^===NETWORK_INTERFACES===/{f=remotedir"/network_interfaces.raw";next}
            /^===LSBLK===/{f=remotedir"/lsblk.txt";next}
            /^===MOUNTS===/{f=remotedir"/mounts.txt";next}
            /^===MULTIPATH===/{f=remotedir"/multipath.txt";next}
            /^===DMESG_NVME===/{f=(mode=="nfs"?"":nvmedir"/dmesg_nvme.txt");next}
            /^===DMESG_STORAGE_ERRORS===/{f=remotedir"/dmesg_storage_errors.txt";next}
            /^===DMESG_FULL===/{f=remotedir"/dmesg_full.txt";next}
            /^===JOURNALCTL_KUBELET===/{f=remotedir"/journalctl_kubelet.txt";next}
            /^===JOURNALCTL_KERNEL===/{f=remotedir"/journalctl_kernel.txt";next}
            /^===JOURNALCTL_KERNEL_PREV===/{f=remotedir"/journalctl_kernel_prev.txt";next}
            /^===JOURNALCTL_SYSTEM===/{f=remotedir"/journalctl_system.txt";next}
            /^===JOURNALCTL_SYSTEM_PREV===/{f=remotedir"/journalctl_system_prev.txt";next}
            /^===JOURNALCTL_STORAGE===/{f=remotedir"/journalctl_storage.txt";next}
            /^===KUBELET_VOLUME_LOGS===/{f=remotedir"/kubelet_volume_logs.txt";next}
            /^===END_NVME_DIAGNOSTICS===/{f="";next}
            f && NF {print > f}
        ' "${tmp_file}" || parse_rc=$?

        if [[ $parse_rc -ne 0 ]]; then
            log_warn "${node}: remote output parse incomplete (awk exit ${parse_rc}); keeping raw capture"
            cp "${tmp_file}" "${node_remote_dir}/remote_output_unparsed.txt" 2>/dev/null || true
        fi

        # Format raw tables
        local raw_file base_name formatted
        shopt -s nullglob
        for raw_file in "${node_nvme_dir}"/*.raw "${node_remote_dir}"/*.raw; do
            [[ ! -f "$raw_file" ]] && continue
            base_name="${raw_file%.raw}"
            formatted="${base_name}.txt"
            if format_table "$raw_file" "${formatted}.tmp" 2>/dev/null; then
                { write_section_header "/dev/stdout" "$(basename "${base_name}" | tr '_' ' ' | tr '[:lower:]' '[:upper:]'): ${node}" "$TIMESTAMP_HUMAN"
                } > "$formatted"
                cat "${formatted}.tmp" >> "$formatted"
                rm -f "${formatted}.tmp"
            else
                mv "$raw_file" "$formatted"
            fi
            rm -f "$raw_file"
        done
        shopt -u nullglob

        if [[ "$COLLECT_MODE" != "block" ]] \
            && [[ ! -s "${node_remote_dir}/nfs_mounts.raw" && ! -s "${node_remote_dir}/nfs_mounts.txt" ]]; then
            log_warn "${node}: no NFS mount data captured (no NFS mounts or NFS tools unavailable — non-fatal)"
        fi

        local health_status node_duration
        health_status=$(grep "^STATUS:" "${node_nvme_dir}/00_health_summary.txt" 2>/dev/null | cut -d: -f2- | xargs)
        node_duration=$(($(get_timestamp_ms) - node_start))
        if [[ "$health_status" == *"HEALTHY"* ]]; then
            echo -e "    ${GREEN}✓${NC} ${node}: Collected - ${GREEN}${health_status}${NC} ${DIM}[$(format_duration $node_duration)]${NC}"
        elif [[ "$health_status" == *"DEGRADED"* ]]; then
            echo -e "    ${YELLOW}⚠${NC} ${node}: Collected - ${YELLOW}${health_status}${NC} ${DIM}[$(format_duration $node_duration)]${NC}"
        else
            echo -e "    ${GREEN}✓${NC} ${node}: Collected ${DIM}[$(format_duration $node_duration)]${NC}"
        fi
        printf 'OK\t-\t%s\n' "$node" >> "${RESULTS_FILE}"
    else
        local node_duration
        node_duration=$(($(get_timestamp_ms) - node_start))
        echo -e "  ${RED}✗${NC} ${node}: Failed (exit: ${ssh_rc}) ${DIM}[$(format_duration $node_duration)]${NC}"

        {
            echo "SSH Collection Failed"
            echo "====================="
            echo "Node: ${node}"
            echo "IP: ${ip}"
            echo "User: ${ssh_user}"
            echo "Exit Code: ${ssh_rc}"
            echo ""
            echo "SSH Error Output:"
            cat "${ssh_err}" 2>/dev/null || echo "No error output captured"
            echo ""
            echo "Troubleshooting:"
            echo " 1. Verify SSH key is set up: ssh-copy-id ${ssh_user}@${ip}"
            echo " 2. Test SSH manually: ssh ${ssh_user}@${ip} hostname"
            echo " 3. Check firewall rules for port 22"
        } > "${node_remote_dir}/COLLECTION_FAILED.txt"
        [[ "$COLLECT_MODE" != "nfs" ]] && \
            cp "${node_remote_dir}/COLLECTION_FAILED.txt" "${node_nvme_dir}/COLLECTION_FAILED.txt" 2>/dev/null || true
        printf 'FAIL\t%s\t%s\n' "$ssh_rc" "$node" >> "${RESULTS_FILE}"
    fi
}

#═══════════════════════════════════════════════════════════════════════════════
# NVMe/NVMe-oF Diagnostics & Node Forensics
# Current User First, Password Fallback, Parallel SSH Support
#═══════════════════════════════════════════════════════════════════════════════

collect_nvme_diagnostics() {
    print_header "Step 8: Node Forensics (SSH) [mode=${COLLECT_MODE}]"
    start_timer "nvme_diag"

    [[ "$SKIP_REMOTE" == true ]] && { log_warn "Skipping (--skip-remote)"; stop_timer "nvme_diag" >/dev/null; return; }
    command -v ssh >/dev/null 2>&1 || { log_warn "SSH unavailable"; stop_timer "nvme_diag" >/dev/null; return; }

    if ! finalize_node_list; then
        log_warn "Node list preparation failed; skipping remote forensics (K8s collection continues)"
        echo "NVME_DIAG_SUCCESS=0" >> "${STATS_FILE}"
        echo "NVME_DIAG_FAILED=0" >> "${STATS_FILE}"
        stop_timer "nvme_diag" >/dev/null
        return 0
    fi

    sort -u "${NODE_LIST}" -o "${NODE_LIST}"
    if [[ ! -s "${NODE_LIST}" ]]; then
        log_info "No nodes for remote collection - skipping (use --nodes or fix failing workloads)"
        echo "NVME_DIAG_SUCCESS=0" >> "${STATS_FILE}"
        echo "NVME_DIAG_FAILED=0" >> "${STATS_FILE}"
        stop_timer "nvme_diag" >/dev/null
        return 0
    fi

    echo "COLLECT_MODE=${COLLECT_MODE}" >> "${STATS_FILE}"


#═══════════════════════════════════════════════════════════════════════════════
# SSH Authentication Strategy (env-var driven, non-interactive)
#
# Passwords/identity are supplied via environment variables - never prompts:
#   CSI_SOS_SSH_USER   SSH LOGIN user on the nodes (default: current `whoami`).
#   CSI_SOS_SSH_PASS   Password for SSH LOGIN (used when SSH key auth fails).
#   CSI_SOS_SUDO_PASS  Password for sudo on the node (used when passwordless
#                      sudo is unavailable). Falls back to CSI_SOS_SSH_PASS.
#
# Login : SSH key if it works, else CSI_SOS_SSH_PASS via sshpass, else skip.
# Sudo  : passwordless if available, else a sudo password if provided,
#         else run WITHOUT sudo (partial data; NVMe /sys data still captured).
#
# NOTE: env-var passwords are visible to root via /proc/<pid>/environ and may
#       land in shell history. Prefer: `read -rs CSI_SOS_SUDO_PASS; export ...`
#═══════════════════════════════════════════════════════════════════════════════
    local CURRENT_USER=$(whoami)
    # SSH login user: explicit override (CSI_SOS_SSH_USER) or the current local user.
    local ssh_user="${CSI_SOS_SSH_USER:-${CURRENT_USER}}"
    if [[ -n "${CSI_SOS_SSH_USER:-}" && "${CSI_SOS_SSH_USER}" != "${CURRENT_USER}" ]]; then
        log_step "Preparing SSH connection (login user: ${ssh_user}, from CSI_SOS_SSH_USER)..."
    else
        log_step "Preparing SSH connection (login user: ${ssh_user})..."
    fi
    local success=0
    local fail=0
    local RESULTS_FILE="${INTERNAL_DIR}/nvme_results.txt"
    : > "${RESULTS_FILE}"

    # Auth state (visible to collect_node/exec_remote via bash dynamic scope)
    local ssh_key_works=false
    local has_sudo=false
    ssh_pass="${CSI_SOS_SSH_PASS:-}"       # login password (sshpass)
    sudo_pass=""                            # sudo password (sudo -S); resolved below
    SSH_USE_PASS=false                      # login via sshpass (password) instead of key
    SUDO_KIND="none"                        # none | nopass | pass

    # 1. Probe SSH key + passwordless sudo on the first node (single, up-front)
    local test_node test_ip local_node
    test_node=$(head -n 1 "${NODE_LIST}")
    test_ip=$(kubectl get node "${test_node}" \
        -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}' \
        2>/dev/null | awk '{print $1}')
    local_node=$(hostname -s 2>/dev/null)

    if [[ -n "$local_node" && ( "$test_node" == "$local_node" || "$test_node" == "$(hostname 2>/dev/null)" ) ]]; then
        # Script is running ON the probe node: no point SSHing to ourselves.
        # Collection for this node happens locally (see collect_node). We still
        # need a sudo decision; probe local sudo directly rather than assuming.
        ssh_key_works=true
        if sudo -n true 2>/dev/null; then has_sudo=true; else has_sudo=false; fi
        log_info "Local node detected (${test_node}) - skipping SSH auth test, using local execution"
    elif [[ -n "$test_ip" ]]; then
        log_debug "Testing SSH key auth as ${ssh_user}..."

        if timeout 8 ssh -o ConnectTimeout=6 -o StrictHostKeyChecking=accept-new \
            -o BatchMode=yes "${ssh_user}@${test_ip}" "sudo -n true" &>/dev/null; then
            ssh_key_works=true; has_sudo=true
            log_info "SSH key access as ${ssh_user} (passwordless sudo)"
        elif timeout 8 ssh -o ConnectTimeout=6 -o StrictHostKeyChecking=accept-new \
            -o BatchMode=yes "${ssh_user}@${test_ip}" "true" &>/dev/null; then
            ssh_key_works=true; has_sudo=false
            log_info "SSH key access as ${ssh_user}"
        else
            log_warn "SSH key auth as ${ssh_user} failed"
        fi
    fi

    # 2. Decide LOGIN method
    if [[ "$ssh_key_works" == true ]]; then
        SSH_USE_PASS=false
    elif [[ -n "$ssh_pass" ]] && command -v sshpass >/dev/null 2>&1; then
        SSH_USE_PASS=true
        log_info "SSH login via CSI_SOS_SSH_PASS (sshpass)"
    else
        log_error "Cannot establish an SSH login to ${ssh_user}@${test_ip} (node: ${test_node})"
        if [[ -z "$ssh_pass" ]]; then
            log_error "Reason: SSH key auth failed and CSI_SOS_SSH_PASS is not set"
            log_warn  "Fix: install an SSH key (ssh-copy-id ${ssh_user}@<node>), OR"
            log_warn  "     export CSI_SOS_SSH_PASS=<login-password> and install 'sshpass'"
        else
            log_error "Reason: CSI_SOS_SSH_PASS is set but 'sshpass' is not installed"
            log_warn  "Fix: install sshpass (e.g. 'yum install sshpass' / 'apt install sshpass'),"
            log_warn  "     OR set up SSH key auth so no password is needed"
        fi
        log_warn "-> Skipping remote node collection; continuing with Kubernetes data only"
        SKIP_REMOTE=true
    fi

    # 3. Decide SUDO method (only if a login method was found)
    if [[ "$SKIP_REMOTE" != true ]]; then
        # When logging in by password, re-probe passwordless sudo over that session.
        # sshpass -e reads the password from $SSHPASS (not argv) so it is not
        # exposed in the process list.
        if [[ "$SSH_USE_PASS" == true ]]; then
            has_sudo=false
            if SSHPASS="${ssh_pass}" sshpass -e ssh -o ConnectTimeout=6 \
                -o StrictHostKeyChecking=accept-new -o LogLevel=ERROR \
                "${ssh_user}@${test_ip}" "sudo -n true" &>/dev/null; then
                has_sudo=true
            fi
        fi

        if [[ "$has_sudo" == true ]]; then
            SUDO_KIND="nopass"
        else
            # Prefer a dedicated sudo password; fall back to the login password
            sudo_pass="${CSI_SOS_SUDO_PASS:-${ssh_pass}}"
            if [[ -n "$sudo_pass" ]]; then
                SUDO_KIND="pass"
            else
                SUDO_KIND="none"
                log_warn "No passwordless sudo and CSI_SOS_SUDO_PASS not set"
                log_warn "-> Collecting WITHOUT sudo: NVMe /sys data is captured, but"
                log_warn "   privileged data (full dmesg, journalctl) may be empty."
                log_warn "   Set CSI_SOS_SUDO_PASS=<sudo-password> for complete forensics."
            fi
        fi
        log_info "Auth (login: $([[ $SSH_USE_PASS == true ]] && echo password || echo key), sudo: ${SUDO_KIND})"
    fi

    if [[ "$SKIP_REMOTE" == true ]]; then
        log_warn "Remote node collection disabled. Continuing with Kubernetes data only."
        stop_timer "nvme_diag" >/dev/null
        return 0
    fi

    # Remote diagnostic script (runs on each worker node, output parsed by markers).
    local nvme_script="${INTERNAL_DIR}/nvme_diag.sh"
    {
    printf '%s\n' '#!/bin/bash' "COLLECT_MODE='${COLLECT_MODE}'"
    cat <<'NVMESCRIPT'
[[ "$COLLECT_MODE" != nfs ]] && RUN_BLOCK=true
[[ "$COLLECT_MODE" != block ]] && RUN_NFS=true
# Best-effort remote forensics: never abort the node script on a single command failure
set +e
set +o pipefail 2>/dev/null || true

_nfs_tmp=""

human_size() {
    if command -v numfmt &>/dev/null; then
        numfmt --to=iec-i --suffix=B "$1" 2>/dev/null && return
    fi
    local bytes=$1
    if [[ $bytes -ge 1073741824 ]]; then
        awk "BEGIN {printf \"%.2f GB\", $bytes/1073741824}"
    elif [[ $bytes -ge 1048576 ]]; then
        awk "BEGIN {printf \"%.2f MB\", $bytes/1048576}"
    else
        echo "${bytes} B"
    fi
}

sysfs_key() {
    local s="$1" key="$2" rest="${s#*${key}=}"
    [[ "$rest" == "$s" ]] && { echo "N/A"; return; }
    echo "${rest%%,*}"
}

get_nguid() {
    local device="$1" nguid=""
    if [[ -f "/sys/block/${device}/nguid" ]]; then
        nguid=$(cat "/sys/block/${device}/nguid" 2>/dev/null | tr -d ' ')
    fi
    if [[ -z "$nguid" || "$nguid" == "00000000-0000-0000-0000-000000000000" ]]; then
        nguid=$(nvme id-ns "/dev/${device}" 2>/dev/null | grep -i nguid | awk '{print $NF}' | tr -d ' ')
    fi
    echo "${nguid:-N/A}"
}

get_source_ip() {
    ip route get "$1" 2>/dev/null | grep -oP 'src \K[0-9.]+' | head -1 || echo "N/A"
}

# ponytail: one read per node; greps reuse these caches
DMESG_T=$(dmesg -T 2>/dev/null || true)
DMESG_PLAIN=$([[ -z "$DMESG_T" ]] && dmesg 2>/dev/null || true)
PROC_MOUNTS=$(cat /proc/mounts 2>/dev/null || true)
JOURNAL_K=""
command -v journalctl &>/dev/null && JOURNAL_K=$(journalctl -k --no-pager -n 5000 2>/dev/null || true)

event_history() {
    local dmesg_pat="$1" journal_pat="$2"
    {
        if [[ -n "$DMESG_T" ]]; then
            grep -iE "$dmesg_pat" <<< "$DMESG_T" \
                | sed -E 's/^\[([^]]+)\][[:space:]]*/\1\tdmesg\t/'
        elif [[ -n "$DMESG_PLAIN" ]]; then
            grep -iE "$dmesg_pat" <<< "$DMESG_PLAIN" \
                | sed -E 's/^/unknown\tdmesg\t/'
        fi
        if [[ -n "$JOURNAL_K" ]]; then
            grep -iE "$journal_pat" <<< "$JOURNAL_K" \
                | sed -E 's/^([A-Za-z]{3}[[:space:]]+[0-9]{1,2}[[:space:]]+[0-9:]{8})[[:space:]]+[^[:space:]]+[[:space:]]+kernel:[[:space:]]*/\1\tkernel\t/'
        fi
    } | awk -F'\t' 'NF>=3 {
        t=$1; src=$2; msg=$3;
        gsub(/[|\t]/, " ", msg);
        m=tolower(msg);
        lvl="INFO";
        if (m ~ /error|fail|timeout|reset|down|cannot|unable|reconnect|stale/) lvl="ERROR";
        else if (m ~ /warn|degrad|retry/) lvl="WARN";
        if (length(msg) > 90) msg=substr(msg,1,90)"...";
        print t"|"lvl"|"src"|"msg;
    }'
}

echo "===SYSTEM_INFO==="
echo "Hostname: $(hostname -f 2>/dev/null || hostname)"
echo "Kernel: $(uname -r)"
echo "Date: $(date '+%Y-%m-%d %H:%M:%S %Z')"
if [[ -f /etc/os-release ]]; then
    echo "OS: $(grep -E '^PRETTY_NAME=' /etc/os-release 2>/dev/null | cut -d'"' -f2)"
fi
echo "Uptime: $(uptime -p 2>/dev/null || uptime | sed 's/.*up /up /' | cut -d',' -f1-2)"
echo ""

if [[ "$RUN_BLOCK" == true ]]; then
echo "===NVME_HEALTH_SUMMARY==="
vast_total=0
vast_live=0
local_count=0
volume_count=0
seen_uuids=""

for ctrl in /sys/class/nvme/nvme*; do
    [[ ! -d "$ctrl" ]] && continue
    address=""
    [[ -f "$ctrl/address" ]] && address=$(cat "$ctrl/address" 2>/dev/null || true)
    if [[ "$address" == *"traddr="* ]]; then
        vast_total=$((vast_total + 1))
        state=$(cat "$ctrl/state" 2>/dev/null || echo "unknown")
        [[ "$state" == "live" ]] && vast_live=$((vast_live + 1))
    else
        local_count=$((local_count + 1))
    fi
done

for ns_path in /sys/block/nvme*n*; do
    [[ ! -d "$ns_path" ]] && continue
    ns_name=$(basename "$ns_path")
    [[ "$ns_name" =~ c[0-9]+n ]] && continue
    ctrl_name=$(echo "$ns_name" | sed 's/n[0-9]*$//')
    ctrl_addr=""
    [[ -f "/sys/class/nvme/${ctrl_name}/address" ]] && ctrl_addr=$(cat "/sys/class/nvme/${ctrl_name}/address" 2>/dev/null || true)
    [[ "$ctrl_addr" != *"traddr="* ]] && continue
    uuid=""
    [[ -f "$ns_path/uuid" ]] && uuid=$(cat "$ns_path/uuid" 2>/dev/null || true)
    [[ -z "$uuid" ]] && continue
    if [[ "$seen_uuids" != *"$uuid"* ]]; then
        seen_uuids="$seen_uuids $uuid"
        volume_count=$((volume_count + 1))
    fi
done

echo "NVMeoF_PATHS_TOTAL: $vast_total"
echo "NVMeoF_PATHS_LIVE: $vast_live"
echo "LOCAL_NVME_DEVICES: $local_count"
echo "VAST_VOLUMES: $volume_count"
if [[ $vast_total -gt 0 ]]; then
    if [[ $vast_live -eq $vast_total ]]; then
        echo "STATUS: HEALTHY - All $vast_total paths live"
    else
        echo "STATUS: DEGRADED - $((vast_total - vast_live))/$vast_total paths not live"
    fi
else
    echo "STATUS: NO_NVMEOF - No NVMeoF paths found"
fi
echo ""

echo "===NVME_VOLUME_MAPPING==="
echo "DEVICE|NSID|UUID|NGUID|SIZE"
seen_uuids=""

for ns_path in /sys/block/nvme*n*; do
    [[ ! -d "$ns_path" ]] && continue

    ns_name=$(basename "$ns_path")
    [[ "$ns_name" =~ c[0-9]+n ]] && continue

    ctrl_name=$(echo "$ns_name" | sed 's/n[0-9]*$//')

    ctrl_addr=""
    [[ -f "/sys/class/nvme/${ctrl_name}/address" ]] && \
        ctrl_addr=$(cat "/sys/class/nvme/${ctrl_name}/address" 2>/dev/null || true)

    [[ "$ctrl_addr" != *"traddr="* ]] && continue

    uuid=""
    [[ -f "$ns_path/uuid" ]] && \
        uuid=$(cat "$ns_path/uuid" 2>/dev/null || true)

    [[ -z "$uuid" ]] && continue

    [[ "$seen_uuids" == *"$uuid"* ]] && continue
    seen_uuids="$seen_uuids $uuid"

    nguid=$(get_nguid "$ns_name")

    nsid="N/A"
    [[ -f "$ns_path/nsid" ]] && \
        nsid=$(cat "$ns_path/nsid" 2>/dev/null)

    size_bytes=0
    [[ -f "$ns_path/size" ]] && \
        size_bytes=$(($(cat "$ns_path/size" 2>/dev/null || echo 0) * 512))

    size_human=$(human_size $size_bytes)

    echo "/dev/${ns_name}|${nsid}|${uuid}|${nguid}|${size_human}"
done

echo ""


# Path Status with HOST_IP detection and TRANSPORT column
echo "===NVME_PATH_STATUS==="
echo "CONTROLLER|TARGET_VIP|HOST_IP|TRANSPORT|STATE"
for ctrl in /sys/class/nvme/nvme*; do
    [[ ! -d "$ctrl" ]] && continue
    ctrl_name=$(basename "$ctrl")
    [[ ! -f "$ctrl/address" ]] && continue
    address=$(cat "$ctrl/address" 2>/dev/null || true)
    [[ "$address" != *"traddr="* ]] && continue
    traddr=$(sysfs_key "$address" "traddr")
    src_addr=$(sysfs_key "$address" "src_addr")
    transport=$(sysfs_key "$address" "trtype")
    [[ -z "$transport" || "$transport" == "N/A" ]] && transport="tcp"
    # If src_addr not in address, get it from routing table
    if [[ -z "$src_addr" || "$src_addr" == "" ]]; then
        src_addr=$(get_source_ip "$traddr")
    fi
    state=$(cat "$ctrl/state" 2>/dev/null || echo "unknown")
    echo "${ctrl_name}|${traddr:-N/A}|${src_addr:-N/A}|${transport}|${state}"
done
echo ""

# Multipath View as a table with column headings
echo "===NVME_MULTIPATH_VIEW==="
echo "VOLUME|UUID|NGUID|PATH_DEVICE|CONTROLLER|TARGET_VIP|STATE|PATHS_LIVE"
tmpfile=$(mktemp)
trap "rm -f $tmpfile" EXIT
for ns_path in /sys/block/nvme*n*; do
    [[ ! -d "$ns_path" ]] && continue
    ns_name=$(basename "$ns_path")
    uuid=""
    [[ -f "$ns_path/uuid" ]] && uuid=$(cat "$ns_path/uuid" 2>/dev/null || true)
    [[ -z "$uuid" ]] && continue
    ctrl_name=""
    ns_num=""
    block_dev="$ns_name"
    if [[ "$ns_name" =~ c[0-9]+n ]]; then
        ctrl_idx=$(echo "$ns_name" | sed 's/.*c\([0-9]*\)n.*/\1/')
        ctrl_name="nvme${ctrl_idx}"
        ns_num=$(echo "$ns_name" | sed 's/.*n//')
    else
        continue
    fi
    [[ -z "$ctrl_name" ]] && continue
    ctrl_state="unknown"
    ctrl_addr=""
    [[ -f "/sys/class/nvme/${ctrl_name}/state" ]] && ctrl_state=$(cat "/sys/class/nvme/${ctrl_name}/state" 2>/dev/null || echo "unknown")
    [[ -f "/sys/class/nvme/${ctrl_name}/address" ]] && ctrl_addr=$(cat "/sys/class/nvme/${ctrl_name}/address" 2>/dev/null || true)
    [[ "$ctrl_addr" != *"traddr="* ]] && continue
    traddr=$(sysfs_key "$ctrl_addr" "traddr")
    echo "${uuid}|n${ns_num}|${ctrl_name}|${traddr}|${ctrl_state}|${block_dev}" >> "$tmpfile"
done
if [[ -s "$tmpfile" ]]; then
    cut -d'|' -f1 "$tmpfile" | sort -u | while read -r uuid; do
        [[ -z "$uuid" ]] && continue
        ns=$(grep "^${uuid}|" "$tmpfile" | head -1 | cut -d'|' -f2)
        paths=$(grep "^${uuid}|" "$tmpfile")
        live_count=$(echo "$paths" | grep -c '|live|'); live_count=${live_count:-0}
        total_count=$(echo "$paths" | wc -l | tr -d ' ')
        first_block=$(echo "$paths" | head -1 | cut -d'|' -f6)
        subsys_name=$(echo "$first_block" | sed 's/c[0-9]*n.*//')
        aggregate_dev="${subsys_name}${ns}"
        nguid=$(get_nguid "${aggregate_dev}")
        paths_status="${live_count}/${total_count}"
        echo "$paths" | sort -t'|' -k3 -V | while IFS='|' read -r _ _ ctrl traddr state block_dev; do
            [[ -z "$ctrl" ]] && continue
            echo "/dev/${aggregate_dev}|${uuid}|${nguid}|/dev/${block_dev}|${ctrl}|${traddr}|${state}|${paths_status}"
        done
    done
fi
rm -f "$tmpfile"
echo ""

echo "===NVME_SUBSYSTEMS==="
nvme list-subsys 2>/dev/null || echo "No NVMe subsystems found or nvme-cli not available"
echo ""

echo "===NVME_LIST==="
nvme list 2>/dev/null || echo "nvme-cli not installed or no NVMe devices"
echo ""

echo "===NVME_LIST_VERBOSE==="
nvme list -v 2>/dev/null || true
echo ""

echo "===PVC_NVME_MAPPING==="
echo "DEVICE|SIZE|PVC|POD_UID|MOUNTPOINT"
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT -n 2>/dev/null | grep -E "^nvme" | while read -r name size type mnt; do
    if [[ "$mnt" == *"/kubernetes.io~csi/"* ]]; then
        pvc=$(echo "$mnt" | grep -oE 'pvc-[a-f0-9-]+' | head -1)
        pod=$(echo "$mnt" | sed -n 's|.*/pods/\([^/]*\)/.*|\1|p')
        echo "${name}|${size}|${pvc:-N/A}|${pod:-N/A}|${mnt}"
    elif [[ -n "$mnt" ]]; then
        echo "${name}|${size}|N/A|N/A|${mnt}"
    else
        echo "${name}|${size}|N/A|N/A|not-mounted"
    fi
done
echo ""

echo "===LOCAL_NVME_PCIE==="
echo "DEVICE|MODEL|SERIAL|SIZE|FIRMWARE"
for ctrl in /sys/class/nvme/nvme*; do
    [[ ! -d "$ctrl" ]] && continue
    ctrl_name=$(basename "$ctrl")
    address=""
    [[ -f "$ctrl/address" ]] && address=$(cat "$ctrl/address" 2>/dev/null)
    [[ "$address" =~ traddr= ]] && continue
    model=$(cat "$ctrl/model" 2>/dev/null | xargs)
    serial=$(cat "$ctrl/serial" 2>/dev/null | xargs)
    firmware=$(cat "$ctrl/firmware_rev" 2>/dev/null | xargs)
    size_human="N/A"
    for ns in "$ctrl"/${ctrl_name}n*; do
        [[ ! -d "$ns" ]] && continue
        ns_name=$(basename "$ns")
        if [[ -f "/sys/block/${ns_name}/size" ]]; then
            size_bytes=$(($(cat "/sys/block/${ns_name}/size") * 512))
            size_human=$(human_size $size_bytes)
        fi
        break
    done
    echo "${ctrl_name}n1|${model}|${serial}|${size_human}|${firmware}"
done
echo ""
fi

echo "===NETWORK_INTERFACES==="
echo "INTERFACE|STATE|MAC|MTU|IP"
ip -o addr show 2>/dev/null | while read -r line; do
    iface=$(echo "$line" | awk '{print $2}')
    ip_addr=$(echo "$line" | awk '{print $4}' | cut -d'/' -f1)
    [[ "$iface" == "lo" ]] && continue
    [[ ! "$ip_addr" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && continue
    state=$(cat "/sys/class/net/${iface}/operstate" 2>/dev/null || echo "unknown")
    mac=$(cat "/sys/class/net/${iface}/address" 2>/dev/null || echo "N/A")
    mtu=$(cat "/sys/class/net/${iface}/mtu" 2>/dev/null || echo "N/A")
    echo "${iface}|${state}|${mac}|${mtu}|${ip_addr}"
done
echo ""

echo "===LSBLK==="
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT 2>/dev/null || lsblk
echo ""

echo "===MOUNTS==="
printf '%s\n' "$PROC_MOUNTS"
echo ""

if [[ "$RUN_NFS" == true ]]; then
NFS_MOUNTS=$(grep -E ' nfs4? ' <<< "$PROC_MOUNTS" || true)
NFS_SERVERS=$(awk '{print $1}' <<< "$NFS_MOUNTS" | sed 's/:.*//' | sort -u)
if _nfs_tmp=$(mktemp -d 2>/dev/null); then
    ( rpcinfo -p > "${_nfs_tmp}/rpcinfo" 2>&1 ) &
    ( nfsstat -m > "${_nfs_tmp}/nfsstat" 2>&1 ) &
    ( nfsstat -c > "${_nfs_tmp}/nfsstat_c" 2>&1 ) &
    _sm_i=0
    while read -r _server; do
        [[ -z "$_server" ]] && continue
        (
            echo "--- showmount -e ${_server} ---"
            showmount -e "${_server}" 2>&1 || echo "showmount failed for ${_server}"
        ) > "${_nfs_tmp}/showmount_${_sm_i}" 2>&1 &
        ((_sm_i++)) || true
    done <<< "$NFS_SERVERS"
else
    _nfs_tmp=""
fi

echo "===NFS_MOUNTS==="
echo "SOURCE|MOUNTPOINT|FSTYPE|OPTIONS|PVC|POD_UID"
if [[ -n "$NFS_MOUNTS" ]]; then
    while read -r dev mnt fst opts _rest; do
        [[ -z "$mnt" ]] && continue
        pvc="N/A"
        pod="N/A"
        if [[ "$mnt" == *"/kubernetes.io~csi/"* ]]; then
            pvc=$(echo "$mnt" | grep -oE 'pvc-[a-f0-9-]+' | head -1 || true)
            pod=$(echo "$mnt" | sed -n 's|.*/pods/\([^/]*\)/volumes/.*|\1|p' || true)
            pvc=${pvc:-N/A}
            pod=${pod:-N/A}
        fi
        echo "${dev}|${mnt}|${fst}|${opts}|${pvc}|${pod}"
    done <<< "$NFS_MOUNTS"
else
    echo "No NFS mounts found in /proc/mounts"
fi
echo ""
fi

echo "===MULTIPATH==="
multipath -ll 2>/dev/null || echo "multipath not available or not configured"
echo ""

if [[ "$RUN_BLOCK" == true ]]; then
echo "===DMESG_NVME==="
if [[ -n "$DMESG_T" ]]; then
    grep -iE "nvme|tcp|nvmeof|vast" <<< "$DMESG_T" | tail -200
elif [[ -n "$DMESG_PLAIN" ]]; then
    grep -iE "nvme" <<< "$DMESG_PLAIN" | tail -100
fi
echo ""
fi

echo "===DMESG_STORAGE_ERRORS==="
if [[ -n "$DMESG_T" ]]; then
    grep -iE "error|fail|timeout|reset" <<< "$DMESG_T" \
        | grep -iE "nvme|scsi|block|storage|disk|nfs|mount.nfs|sunrpc" | tail -100
elif [[ -n "$DMESG_PLAIN" ]]; then
    grep -iE "error|fail|timeout|reset" <<< "$DMESG_PLAIN" \
        | grep -iE "nvme|scsi|block|storage|disk|nfs|mount.nfs|sunrpc" | tail -100
fi
echo ""

echo "===DMESG_FULL==="
if [[ -n "$DMESG_T" ]]; then
    printf '%s\n' "$DMESG_T"
else
    printf '%s\n' "$DMESG_PLAIN"
fi
echo ""

echo "===JOURNALCTL_KUBELET==="
if command -v journalctl &>/dev/null; then
    journalctl -u kubelet --no-pager -n 10000 2>/dev/null || echo "journalctl not available or kubelet service not found"
else
    echo "journalctl not available"
fi
echo ""

echo "===JOURNALCTL_KERNEL==="
if command -v journalctl &>/dev/null; then
    journalctl -k --no-pager -n 10000 2>/dev/null || echo "journalctl not available"
else
    echo "journalctl not available"
fi
echo ""

# Previous boot (post-reboot / crash forensics). Requires a persistent journal
# (Storage=persistent or /var/log/journal present); otherwise -b -1 returns
# "no persistent journal" and we capture that note instead.
echo "===JOURNALCTL_KERNEL_PREV==="
if command -v journalctl &>/dev/null; then
    journalctl -k -b -1 --no-pager -n 10000 2>&1 || echo "previous boot kernel log not available"
else
    echo "journalctl not available"
fi
echo ""

echo "===JOURNALCTL_SYSTEM==="
if command -v journalctl &>/dev/null; then
    journalctl --no-pager -n 10000 --since "24 hours ago" 2>/dev/null || echo "journalctl not available"
else
    echo "journalctl not available"
fi
echo ""

echo "===JOURNALCTL_SYSTEM_PREV==="
if command -v journalctl &>/dev/null; then
    journalctl -b -1 --no-pager -n 10000 2>&1 || echo "previous boot system log not available"
else
    echo "journalctl not available"
fi
echo ""

echo "===JOURNALCTL_STORAGE==="
if command -v journalctl &>/dev/null; then
    journalctl --no-pager -n 5000 -g "nvme|scsi|iscsi|csi|mount|umount|filesystem|xfs|ext4|block|nfs|mount.nfs|nfsstat|showmount|rpcinfo|sunrpc" 2>/dev/null || echo "journalctl grep not available"
else
    echo "journalctl not available"
fi
echo ""

echo "===KUBELET_VOLUME_LOGS==="
if command -v journalctl &>/dev/null && systemctl is-active kubelet &>/dev/null; then
    journalctl -u kubelet --since "24 hours ago" --no-pager 2>/dev/null | \
        grep -iE "volume|mount|attach|detach|csi|vast|nvme|block|nfs|mount.nfs" | tail -200
elif [[ -f /var/log/kubelet.log ]]; then
    tail -1000 /var/log/kubelet.log 2>/dev/null | \
        grep -iE "volume|mount|attach|detach|csi|vast|nvme|block|nfs|mount.nfs" | tail -200
else
    echo "Kubelet logs not accessible"
fi
echo ""

if [[ "$RUN_BLOCK" == true ]]; then
echo "===NVME_EVENT_HISTORY==="
echo "TIME|LEVEL|SOURCE|EVENT"
event_history 'nvme|nvmeof|nvme-tcp|multipath|reset controller|reconnect|controller is down|I/O error|io error' \
    'nvme|nvmeof|nvme-tcp|multipath|reset controller|reconnect|controller is down|I/O error|io error'
echo ""
fi

if [[ "$RUN_NFS" == true ]]; then
echo "===NFS_RPCINFO==="
if [[ -n "$_nfs_tmp" && -d "$_nfs_tmp" ]]; then
    wait 2>/dev/null || true
    cat "${_nfs_tmp}/rpcinfo" 2>/dev/null || echo "rpcinfo not available"
else
    echo "NFS rpcinfo/showmount/nfsstat probes skipped (temp dir unavailable)"
fi
echo ""

echo "===NFS_SHOWMOUNT==="
if [[ -n "$_nfs_tmp" && -d "$_nfs_tmp" && -n "$NFS_SERVERS" ]]; then
    cat "${_nfs_tmp}"/showmount_* 2>/dev/null || echo "showmount output unavailable"
elif [[ -z "$NFS_SERVERS" ]]; then
    echo "No NFS servers found (no NFS mounts in /proc/mounts)"
else
    echo "showmount not collected (NFS probe temp dir unavailable)"
fi
echo ""

echo "===NFS_NFSSTAT==="
if [[ -n "$_nfs_tmp" && -d "$_nfs_tmp" ]]; then
    cat "${_nfs_tmp}/nfsstat" 2>/dev/null || echo "nfsstat not available"
else
    echo "nfsstat not collected (NFS probe temp dir unavailable)"
fi
echo ""

echo "===NFS_NFSSTAT_CLIENT==="
if [[ -n "$_nfs_tmp" && -d "$_nfs_tmp" ]]; then
    cat "${_nfs_tmp}/nfsstat_c" 2>/dev/null || echo "nfsstat -c not available"
else
    echo "nfsstat -c not collected (NFS probe temp dir unavailable)"
fi
echo ""

[[ -n "$_nfs_tmp" && -d "$_nfs_tmp" ]] && rm -rf "${_nfs_tmp}" || true

echo "===NFS_MOUNTSTATS==="
if [[ -r /proc/self/mountstats ]]; then
    awk '/^device / {in_nfs=($0 ~ / nfs/)} in_nfs' /proc/self/mountstats 2>/dev/null \
        || echo "failed to read /proc/self/mountstats"
else
    echo "/proc/self/mountstats not readable"
fi
echo ""

echo "===NFS_XPRT_STATS==="
echo "SWITCH|XPRT|STATE|DSTADDR|SRCADDR|PENDING|BACKLOG|FLAGS"
_xprt_base="/sys/kernel/sunrpc/xprt-switches"
if [[ -d "$_xprt_base" ]]; then
    for _sw in "$_xprt_base"/switch-*; do
        [[ -d "$_sw" ]] || continue
        for _xp in "$_sw"/xprt-*; do
            [[ -d "$_xp" ]] || continue
            _state=$(cat "$_xp/state" 2>/dev/null || cat "$_xp/xprt_state" 2>/dev/null || echo "N/A")
            _dst=$(cat "$_xp/dstaddr" 2>/dev/null || echo "N/A")
            _src="N/A"
            if _src_raw=$(cat "$_xp/srcaddr" 2>/dev/null); then
                _src="$_src_raw"
            elif [[ -f "$_xp/info" ]]; then
                _src=$(grep -oE 'srcaddr=[^,]+' "$_xp/info" 2>/dev/null | head -1 | cut -d= -f2- || echo "N/A")
            fi
            _pending=$(cat "$_xp/pending" 2>/dev/null || echo "N/A")
            _backlog=$(cat "$_xp/backlog" 2>/dev/null || echo "N/A")
            _flags=$(cat "$_xp/flags" 2>/dev/null || echo "N/A")
            echo "$(basename "$_sw")|$(basename "$_xp")|${_state}|${_dst}|${_src}|${_pending}|${_backlog}|${_flags}"
        done
    done
else
    echo "xprt-switches sysfs not available (NFS RPC not loaded or non-Linux)"
fi
echo ""

echo "===NFS_TCP_CONNECTIONS==="
echo "PROTO|STATE|LOCAL|REMOTE"
if command -v ss &>/dev/null; then
    ss -H -tn sport = :2049 2>/dev/null | awk '{print "tcp|" $1 "|" $4 "|" $5}' \
        || ss -H -tn 2>/dev/null | awk '$5 ~ /:2049$/ {print "tcp|" $1 "|" $4 "|" $5}' \
        || echo "no NFS TCP sockets on port 2049"
elif command -v netstat &>/dev/null; then
    netstat -tn 2>/dev/null | awk 'NR>2 && $4 ~ /:2049$/ {print "tcp|" $6 "|" $4 "|" $5}' \
        || echo "no NFS TCP sockets on port 2049"
else
    echo "ss/netstat not available"
fi
echo ""

echo "===VAST_CSI_META==="
echo "MOUNTPOINT|META_CONTENT"
_vast_meta_found=0
while IFS= read -r -d '' _meta_file; do
    _vast_meta_found=1
    _meta_mnt=$(dirname "$_meta_file")
    _meta_body=$(tr '\n' '; ' < "$_meta_file" 2>/dev/null | head -c 1000 || echo "unreadable")
    echo "${_meta_mnt}|${_meta_body}"
done < <(find /var/lib/kubelet/pods -path '*/kubernetes.io~csi/*/.vast-csi-meta' -print0 2>/dev/null || true)
[[ $_vast_meta_found -eq 0 ]] && echo "No .vast-csi-meta files found"
echo ""

echo "===NFS_EVENT_HISTORY==="
echo "TIME|LEVEL|SOURCE|EVENT"
event_history 'nfs|mount\.nfs|nfs4|sunrpc|rpc\.|stale file handle|ETIMEDOUT.*nfs' \
    'nfs|mount\.nfs|nfs4|sunrpc|stale file handle' || echo "NFS event history unavailable"
echo ""
fi

echo "===END_NVME_DIAGNOSTICS==="
NVMESCRIPT
    } > "${nvme_script}"
    chmod +x "${nvme_script}"


    #═══════════════════════════════════════════════════════════════════════════════
    # Process Nodes (sequential, or parallel in batches of PARALLEL_WORKERS)
    #═══════════════════════════════════════════════════════════════════════════════
    local node_count
    node_count=$(grep -c . "${NODE_LIST}" 2>/dev/null); node_count=${node_count:-0}

    # Sanitize worker count (fall back to 20 on non-numeric / empty input).
    [[ "$PARALLEL_WORKERS" =~ ^[0-9]+$ ]] && (( PARALLEL_WORKERS >= 1 )) || PARALLEL_WORKERS=20

    if [[ "$PARALLEL_SSH" == true ]]; then
        print_subheader "Parallel collection from ${node_count} node(s) [${PARALLEL_WORKERS} workers]"
    else
        print_subheader "Collecting from ${node_count} node(s)"
    fi
    echo ""

    if [[ "$PARALLEL_SSH" == true ]]; then
        # `wait -n` (bash >= 4.3) lets us keep a sliding window: as soon as any
        # one worker finishes we launch the next node, so all PARALLEL_WORKERS
        # slots stay busy instead of stalling on the slowest node in a batch.
        local have_wait_n=false
        if (( BASH_VERSINFO[0] > 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] >= 3) )); then
            have_wait_n=true
        fi

        local running=0
        while read -r node; do
            [[ -z "${node}" ]] && continue
            collect_node "${node}" &
            ((running++))
            if (( running >= PARALLEL_WORKERS )); then
                if [[ "$have_wait_n" == true ]]; then
                    wait -n         # sliding window: free ONE slot
                    ((running--))
                else
                    wait            # fallback: drain whole batch
                    running=0
                fi
            fi
        done < "${NODE_LIST}"
        wait                        # drain remaining workers
    else
        while read -r node; do
            [[ -z "${node}" ]] && continue
            collect_node "${node}"
        done < "${NODE_LIST}"
    fi

    # Tally results written by collect_node (works for both modes)
    success=$(grep -c '^OK' "${RESULTS_FILE}" 2>/dev/null); success=${success:-0}
    fail=$(grep -c '^FAIL' "${RESULTS_FILE}" 2>/dev/null); fail=${fail:-0}

    echo ""
    echo "NVME_DIAG_SUCCESS=$success" >> "${STATS_FILE}"
    echo "NVME_DIAG_FAILED=$fail" >> "${STATS_FILE}"
    stop_timer "nvme_diag"
    local duration=$LAST_DURATION

    if [[ $fail -gt 0 ]]; then
        log_warn "Diagnostics: ${GREEN}${success}${NC} collected, ${RED}${fail}${NC} failed ${DIM}[$(format_duration $duration)]${NC}"
    else
        log_info "Diagnostics: ${GREEN}${success}${NC} nodes collected ${DIM}[$(format_duration $duration)]${NC}"
    fi
}


#═══════════════════════════════════════════════════════════════════════════════
# JSON Summary Generation
#═══════════════════════════════════════════════════════════════════════════════

generate_json_summary() {
    log_debug "Generating JSON summary..."

    local total_duration=$1
    local nodes_total=$2
    local nodes_ready=$3
    local failed_pods=$4
    local total_pods=$5
    local pvcs_total=$6
    local pvcs_bound=$7
    local unbound_pvcs=$8
    local failed_vas=$9
    local mount_chains=${10}
    local csi_pods=${11}
    local nvme_success=${12}
    local nvme_failed=${13}
    local csi_version=${14}

    # Get k8s version
    local k8s_version=$(head -1 "${GLOBAL_DIR}/k8s_version.txt" 2>/dev/null | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "unknown")

    cat > "${JSON_SUMMARY}" <<EOF
{
  "version": "${VERSION}",
  "timestamp": "${TIMESTAMP}",
  "timestamp_human": "${TIMESTAMP_HUMAN}",
  "hostname": "$(hostname)",
  "duration_ms": ${total_duration},
  "duration_human": "$(format_duration $total_duration)",
  "namespaces": {
    "workload": "${WORKLOAD_NS}",
    "csi": "${CSI_NS}"
  },
  "cluster": {
    "nodes_total": ${nodes_total},
    "nodes_ready": ${nodes_ready},
    "k8s_version": "${k8s_version}",
    "csi_version": "${csi_version}"
  },
  "pods": {
    "total": ${total_pods:-0},
    "failed": ${failed_pods}
  },
  "storage": {
    "pvcs_total": ${pvcs_total},
    "pvcs_bound": ${pvcs_bound},
    "pvcs_pending": ${unbound_pvcs},
    "failed_volume_attachments": ${failed_vas},
    "mount_chain_issues": ${mount_chains}
  },
  "csi": {
    "pods_collected": ${csi_pods}
  },
  "nvme": {
    "nodes_collected": ${nvme_success},
    "nodes_failed": ${nvme_failed}
  },
  "step_timings": {
    "preflight_ms": $(get_timer "preflight"),
    "namespace_ms": $(get_timer "namespace"),
    "csi_version_ms": $(get_timer "csi_version"),
    "cluster_info_ms": $(get_timer "cluster_info"),
    "failed_pods_ms": $(get_timer "failed_pods"),
    "storage_issues_ms": $(get_timer "storage_issues"),
    "events_ms": $(get_timer "events"),
    "csi_logs_ms": $(get_timer "csi_logs"),
    "nvme_diag_ms": $(get_timer "nvme_diag")
  },
  "archive": "${OUTPUT_DIR}.zip"
}
EOF
}

#═══════════════════════════════════════════════════════════════════════════════
# Finalize Collection
#═══════════════════════════════════════════════════════════════════════════════

finalize() {
    print_header "Finalizing"

    local total_duration=$(($(get_timestamp_ms) - SCRIPT_START_TIME))

    # Read stats BEFORE deleting internal directory
    local nodes_total=$(grep "^NODES_TOTAL=" "${STATS_FILE}" 2>/dev/null | cut -d= -f2 || echo 0)
    local nodes_ready=$(grep "^NODES_READY=" "${STATS_FILE}" 2>/dev/null | cut -d= -f2 || echo 0)
    local failed_pods=$(grep "^FAILED_PODS=" "${STATS_FILE}" 2>/dev/null | cut -d= -f2 || echo 0)
    local total_pods=$(grep "^TOTAL_PODS=" "${STATS_FILE}" 2>/dev/null | cut -d= -f2 || echo 0)
    local pvcs_total=$(grep "^PVCS_TOTAL=" "${STATS_FILE}" 2>/dev/null | cut -d= -f2 || echo 0)
    local pvcs_bound=$(grep "^PVCS_BOUND=" "${STATS_FILE}" 2>/dev/null | cut -d= -f2 || echo 0)
    local unbound_pvcs=$(grep "^UNBOUND_PVCS=" "${STATS_FILE}" 2>/dev/null | cut -d= -f2 || echo 0)
    local failed_vas=$(grep "^FAILED_VAS=" "${STATS_FILE}" 2>/dev/null | cut -d= -f2 || echo 0)
    local mount_chains=$(grep "^MOUNT_CHAINS=" "${STATS_FILE}" 2>/dev/null | cut -d= -f2 || echo 0)
    local csi_pods=$(grep "^CSI_PODS=" "${STATS_FILE}" 2>/dev/null | cut -d= -f2 || echo 0)
    local nvme_success=$(grep "^NVME_DIAG_SUCCESS=" "${STATS_FILE}" 2>/dev/null | cut -d= -f2 || echo 0)
    local nvme_failed=$(grep "^NVME_DIAG_FAILED=" "${STATS_FILE}" 2>/dev/null | cut -d= -f2 || echo 0)
    local csi_version=$(grep "^CSI_VERSION=" "${STATS_FILE}" 2>/dev/null | cut -d= -f2 || echo "unknown")

    # Generate JSON summary (pass the stats we just read)
    generate_json_summary "$total_duration" "$nodes_total" "$nodes_ready" "$failed_pods" \
        "$total_pods" "$pvcs_total" "$pvcs_bound" "$unbound_pvcs" "$failed_vas" \
        "$mount_chains" "$csi_pods" "$nvme_success" "$nvme_failed" "$csi_version"

    # Append timing to text summary
    {
        echo "+------------------------------------------------------------------------------+"
        echo "|  STEP TIMINGS                                                                |"
        echo "+------------------------------------------------------------------------------+"
        printf "|  %-40s %33s|\n" "Step 0: Pre-flight Checks" "$(format_duration $(get_timer "preflight"))"
        printf "|  %-40s %33s|\n" "Step 1: Namespace Selection" "$(format_duration $(get_timer "namespace"))"
        printf "|  %-40s %33s|\n" "Step 2: CSI Driver Version" "$(format_duration $(get_timer "csi_version"))"
        printf "|  %-40s %33s|\n" "Step 3: Cluster Information" "$(format_duration $(get_timer "cluster_info"))"
        printf "|  %-40s %33s|\n" "Step 4: Failed Pods Analysis" "$(format_duration $(get_timer "failed_pods"))"
        printf "|  %-40s %33s|\n" "Step 5: Storage Issues" "$(format_duration $(get_timer "storage_issues"))"
        printf "|  %-40s %33s|\n" "Step 6: Cluster Events" "$(format_duration $(get_timer "events"))"
        printf "|  %-40s %33s|\n" "Step 7: CSI Driver Logs" "$(format_duration $(get_timer "csi_logs"))"
        printf "|  %-40s %33s|\n" "Step 8: NVMe & Node Forensics" "$(format_duration $(get_timer "nvme_diag"))"
        echo "+------------------------------------------------------------------------------+"
        printf "|  %-40s %33s|\n" "TOTAL DURATION" "$(format_duration $total_duration)"
        echo "+------------------------------------------------------------------------------+"
        echo ""
        echo "+------------------------------------------------------------------------------+"
        echo "|  COLLECTION STATISTICS                                                       |"
        echo "+------------------------------------------------------------------------------+"
        while IFS='=' read -r key value; do
            [[ -n "$key" ]] && printf "|  %-35s %-40s|\n" "$key:" "$value"
        done < "${STATS_FILE}"
        echo "+------------------------------------------------------------------------------+"
        echo ""
        echo "+------------------------------------------------------------------------------+"
        echo "|  NAMESPACES                                                                  |"
        echo "+------------------------------------------------------------------------------+"
        printf "|  %-35s %-40s|\n" "Workload Namespace:" "$WORKLOAD_NS"
        printf "|  %-35s %-40s|\n" "CSI Namespace:" "$CSI_NS"
        printf "|  %-35s %-40s|\n" "Collection Mode:" "$COLLECT_MODE"
        echo "+------------------------------------------------------------------------------+"
        echo ""
        echo "+------------------------------------------------------------------------------+"
        echo "|  DIRECTORY STRUCTURE                                                         |"
        echo "+------------------------------------------------------------------------------+"
        echo "|                                                                              |"
        echo "|  ${OUTPUT_DIR}/"
        echo "|  +-- 00_SUMMARY.txt                    <- Start here"
        echo "|  +-- 00_SUMMARY.json                   <- Machine-readable summary"
        echo "|  |"
        echo "|  +-- 01_Cluster_Info/                  <- Cluster overview"
        echo "|  |   +-- nodes.txt"
        echo "|  |   +-- storage_classes.txt"
        echo "|  |   +-- csi_drivers.txt"
        echo "|  |   +-- k8s_version.txt"
        echo "|  |   +-- events_all.txt                  <- all namespaces (filter in-file)"
        echo "|  |   +-- node_crash_events.txt"
        echo "|  +-- 02_Failed_Pods/                   <- ALL pod failures"
        echo "|  |   +-- 00_SUMMARY.txt                <- Failure breakdown"
        echo "|  |   +-- describes/<pod>.txt"
        echo "|  |"
        echo "|  +-- 03_Storage_Issues/"
        echo "|  |   +-- Unbound_PVCs/                 <- PVCs not bound"
        echo "|  |   +-- Failed_VAs/                   <- VolumeAttachment errors"
        echo "|  |   +-- Mount_Chain/                  <- Pod->PVC->PV->VA tracing"
        echo "|  |"
        echo "|  +-- 04_NVMe_Diagnostics/              <- NVMe/NVMeoF (mode: all/block)"
        echo "|  |   +-- <node>/"
        echo "|  |       +-- 00_health_summary.txt"
        echo "|  |       +-- nvme_list_verbose.txt"
        echo "|  |       +-- nvme_subsystems.txt"
        echo "|  |"
        echo "|  +-- 05_Node_Forensics/                <- System + NFS data"
        echo "|  |   +-- <node>/"
        echo "|  |       +-- system_info.txt"
        echo "|  |       +-- mounts.txt"
        echo "|  |       +-- nfs_mounts.txt             <- mode: all/nfs (incl. PVC/POD columns)"
        echo "|  |       +-- nfs_mountstats.txt"
        echo "|  |       +-- nfs_xprt_stats.txt"
        echo "|  |       +-- nfs_tcp_connections.txt"
        echo "|  |       +-- vast_csi_meta.txt"
        echo "|  |       +-- nfs_rpcinfo.txt"
        echo "|  |       +-- nfs_showmount.txt"
        echo "|  |       +-- nfs_nfsstat.txt"
        echo "|  |       +-- nfs_nfsstat_client.txt"
        echo "|  |       +-- nfs_event_history.txt"
        echo "|  |       +-- journalctl_kubelet.txt"
        echo "|  |       +-- journalctl_storage.txt"
        echo "|  |"
        echo "|  +-- 06_CSI_Logs/                      <- CSI driver logs"
        echo "|      +-- csi_pods.txt"
        echo "|      +-- Controllers/"
        echo "|      +-- Node_Daemons/<node>/"
        echo "|                                                                              |"
        echo "+------------------------------------------------------------------------------+"
        echo ""
    } >> "${SUMMARY_FILE}"

    rm -rf "${INTERNAL_DIR}" 2>/dev/null || true

    log_step "Creating archive..."
    if zip -rq "${OUTPUT_DIR}.zip" "${OUTPUT_DIR}" 2>/dev/null; then
        local archive_size=$(du -h "${OUTPUT_DIR}.zip" 2>/dev/null | cut -f1)
        log_info "Archive: ${CYAN}${OUTPUT_DIR}.zip${NC} (${archive_size})"
    else
        log_warn "Archive creation failed"
    fi

    # Count total files
    local total_files=$(find "${OUTPUT_DIR}" -type f 2>/dev/null | wc -l | tr -d ' ')

    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}                      ${GREEN}${BOLD}✓ COLLECTION COMPLETE${NC}                                 ${CYAN}║${NC}"
    echo -e "${CYAN}╠══════════════════════════════════════════════════════════════════════════════╣${NC}"
    printf "${CYAN}║${NC}  ${BOLD}%-15s${NC} %-60s${CYAN}║${NC}\n" "Duration:" "$(format_duration $total_duration)"
    printf "${CYAN}║${NC}  ${BOLD}%-15s${NC} %-60s${CYAN}║${NC}\n" "Total Files:" "${total_files}"
    printf "${CYAN}║${NC}  ${BOLD}%-15s${NC} %-60s${CYAN}║${NC}\n" "Archive:" "${OUTPUT_DIR}.zip"
    printf "${CYAN}║${NC}  ${BOLD}%-15s${NC} %-60s${CYAN}║${NC}\n" "Summary:" "${SUMMARY_FILE}"
    printf "${CYAN}║${NC}  ${BOLD}%-15s${NC} %-60s${CYAN}║${NC}\n" "JSON Report:" "${JSON_SUMMARY}"
    echo -e "${CYAN}╠══════════════════════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${CYAN}║${NC}  ${BOLD}QUICK STATS${NC}                                                                  ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  ──────────────────────────────────────────────────────────────────────────  ${CYAN}║${NC}"

    printf "${CYAN}║${NC}   Nodes: ${GREEN}%s${NC} ready    PVCs: %s (%s bound)    Pods: %s failing           ${CYAN}║${NC}\n" \
        "${nodes_ready}/${nodes_total}" "${pvcs_total}" "${pvcs_bound}" "${failed_pods}"

    if [[ $nvme_failed -gt 0 ]]; then
        printf "${CYAN}║${NC}   NVMe: ${GREEN}%s${NC} healthy, ${RED}%s${NC} failed                                              ${CYAN}║${NC}\n" \
            "${nvme_success}" "${nvme_failed}"
    else
        printf "${CYAN}║${NC}   NVMe: ${GREEN}%s${NC} nodes collected                                                 ${CYAN}║${NC}\n" \
            "${nvme_success}"
    fi

    echo -e "${CYAN}╠══════════════════════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${CYAN}║${NC}  ${GREEN}Share the .zip file with VAST support for analysis.${NC}                      ${CYAN}║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

#═══════════════════════════════════════════════════════════════════════════════
# Main Entry Point
#═══════════════════════════════════════════════════════════════════════════════

# Run a collection phase non-fatally: a failure inside one phase is logged and
# we proceed to the next phase. Keeps the SOS run idempotent/best-effort so a
# single broken step never aborts the whole capture. Setup/precondition phases
# (preflight, namespace selection) are intentionally NOT wrapped — they are
# hard gates and exit directly when the cluster is unusable.
run_phase() {
    local label="$1"; shift
    "$@" || log_warn "Phase '${label}' returned non-zero (exit $?); continuing with next phase"
}

main() {
    parse_args "$@"
    setup_directories
    print_banner
    preflight_checks
    select_workload_namespace
    select_csi_namespace
    run_phase "CSI version"     detect_csi_version
    run_phase "Cluster info"    collect_cluster_info
    run_phase "Failed pods"     collect_failed_pods
    run_phase "Storage issues"  collect_storage_issues
    run_phase "Cluster events"  collect_cluster_events
    run_phase "CSI logs"        collect_csi_logs
    run_phase "Node forensics"  collect_nvme_diagnostics
    run_phase "Finalize"        finalize
}

main "$@"
