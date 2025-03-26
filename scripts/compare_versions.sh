#!/bin/bash

# Function to compare versions
compare_versions() {
    local ver1=$(echo "$1" | sed 's/^v//')  # Remove 'v' prefix
    local ver2=$(echo "$2" | sed 's/^v//')

    # Use sort -V for natural version sorting
    if [[ "$ver1" == "$ver2" ]]; then
        return 0
    elif [[ "$(printf "%s\n%s" "$ver1" "$ver2" | sort -V | head -n1)" == "$ver1" ]]; then
        return 1
    else
        return 0
    fi
}

# Usage: ./compare_versions.sh v1.2.3 v1.2.4
if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <version1> <version2>"
    exit 1
fi

compare_versions "$1" "$2"
