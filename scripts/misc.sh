#!/usr/bin/env bash

#######################################
# LOGGING
#######################################
# Define color codes
RESET="\e[0m"
BLACK="\e[0;30m"
RED="\e[0;31m"
GREEN="\e[0;32m"
YELLOW="\e[0;33m"
BLUE="\e[0;34m"
MAGENTA="\e[0;35m"
CYAN="\e[0;36m"
WHITE="\e[0;37m"

# Define log levels
INFO="[INFO]"
WARNING="[WARNING]"
ERROR="[ERROR]"

# Log functions for different levels
log_info() {
    echo -e "${GREEN}${INFO}${RESET} $1"
}

log_warning() {
    echo -e "${YELLOW}${WARNING}${RESET} $1"
}

log_error() {
    echo -e "${RED}${ERROR}${RESET} $1"
}

log_debug() {
    echo -e "${CYAN}[DEBUG]${RESET} $1"
}
