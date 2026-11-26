#!/usr/bin/env bash
if [ -z "${BASH_VERSION:-}" ]; then
    printf '\n=== REX SETUP FAILED ===\nRun this script with Bash using bash unraid/setup.sh.\n' >&2
    exit 1
fi
set -euo pipefail
umask 077

step='Check setup settings'
work=
completed=0

finish() {
    local status=$1
    if [[ -n $work ]]; then
        if ! rm -f -- "$work/authorized_keys" "$work/template.xml" || ! rmdir -- "$work"; then
            if (( status == 0 )); then
                step='Remove temporary setup files'
                status=1
            fi
        fi
    fi
    if (( status != 0 || ! completed )); then
        (( status != 0 )) || status=1
        printf '\n=== REX SETUP FAILED ===\n' >&2
        printf 'Stopped at: %s (exit %s).\n' "$step" "$status" >&2
        printf 'Review the output and rerun setup before applying the template.\n' >&2
    fi
    exit "$status"
}

trap 'finish "$?"' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

usage() {
    cat <<'EOF'
Usage: bash unraid/setup.sh [options]

Run without options for interactive setup. Run from an Unraid root shell.

  --name NAME       Container name (default rex)
  --image REF       Image tag or digest for the template
  --appdata PATH    Appdata directory (default /mnt/user/appdata/NAME, or
                    /mnt/cache/appdata/NAME with --podman if cache is mounted)
  --keys FILE       Import one OpenSSH public key per line
  --bind-ip IPv4    Address for SSH (default 127.0.0.1)
  --port PORT       Host SSH port (default 2222, or 2223 with --podman)
  --workspace PATH  Optional writable workspace directory under /mnt
  --podman          Enable nested Podman setup for a development instance
  -h, --help        Show this help

An empty key file allows interactive paste when no keys are already installed.
For Podman appdata, use /mnt/POOL/appdata/NAME, with the pool name shown on
Unraid's Main tab. Workspace and key file paths can still use /mnt/user.
EOF
}

die() {
    printf '\nERROR: %s\n' "$*" >&2
    exit 1
}

prompt() {
    local answer
    printf '%s [%s] ' "$2" "$3" >&2
    IFS= read -r answer || die 'Setup input ended.'
    printf -v "$1" '%s' "${answer:-$3}"
}

storage_path() {
    local path mount_name
    [[ $1 == /mnt/*/* && ! $1 =~ [[:cntrl:]] ]] || die "Use a directory under /mnt for $1."
    path=$(realpath -m -- "$1")
    [[ $path == /mnt/*/* ]] || die "Path resolves outside Unraid storage: $1"
    mount_name=${path#/mnt/}
    mountpoint -q -- "/mnt/${mount_name%%/*}" || die "Start the array or mount /mnt/${mount_name%%/*} first."
    printf '%s\n' "$path"
}

appdata_path() {
    local path
    [[ -n $1 ]] || die 'Enter a direct pool appdata path, such as /mnt/<pool>/appdata/rex-test.'
    path=$(storage_path "$1") || return 1
    if (( podman )) && [[ $path == /mnt/user/* || $path == /mnt/user0/* ]]; then
        die 'Use a direct pool path for Podman appdata, such as /mnt/cache/appdata/rex-test. Workspace and key file paths can still use /mnt/user.'
    fi
    printf '%s\n' "$path"
}

xml_replacement() {
    printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' \
        -e 's/"/\&quot;/g' -e "s/'/\&apos;/g" -e 's/[\\&|]/\\&/g'
}

install_file() {
    local source=$1 destination=$2 mode=${3:-} staged
    [[ ! -L $destination && ( ! -e $destination || -f $destination ) ]] \
        || die "Expected a regular file at $destination."
    if cmp -s -- "$source" "$destination"; then
        if [[ -n $mode && $(stat -c '%u:%g:%a' -- "$destination") != "0:0:${mode#0}" ]]; then
            chown 0:0 -- "$destination"
            chmod "$mode" -- "$destination"
        fi
        return
    fi
    staged=$(mktemp -- "$destination.XXXXXXXX")
    if ! { cat -- "$source" > "$staged" \
        && { [[ -z $mode ]] || { chown 0:0 -- "$staged" && chmod "$mode" -- "$staged"; }; } \
        && mv -fT -- "$staged" "$destination"; }; then
        rm -f -- "$staged"
        die "Could not install $destination."
    fi
}

add_public_key() {
    local line=${1%$'\r'} type blob comment fingerprint
    [[ $line =~ ^[[:space:]]*(#|$) ]] && return 0
    read -r type blob comment <<< "$line"
    [[ $type == ssh-* || $type == ecdsa-* || $type == sk-* ]] \
        || die 'Use an OpenSSH public key line such as ssh-ed25519 followed by its key and comment.'
    [[ -n $blob ]] || die 'The supplied public key is incomplete.'
    fingerprint=$(ssh-keygen -lf /dev/stdin <<< "$line" 2>/dev/null | awk 'NR == 1 {print $2}') \
        || die 'The supplied public key could not be read.'
    [[ -n $fingerprint ]] || die 'The supplied public key could not be read.'
    if [[ ! -v 'installed_keys[$fingerprint]' ]]; then
        printf '%s\n' "$line" >> "$work/authorized_keys"
        installed_keys[$fingerprint]=1
    fi
}

name=rex
image=
appdata=
keys=
bind_ip=127.0.0.1
port=
workspace=
podman=0
interactive=0
if (( $# == 0 )); then
    [[ -t 0 ]] || die 'Run with a terminal for prompts or supply options. See --help.'
    interactive=1
fi
while (( $# )); do
    case $1 in
        -h|--help) usage; completed=1; exit 0 ;;
        --podman) podman=1; shift; continue ;;
        --name|--image|--appdata|--keys|--bind-ip|--port|--workspace)
            (( $# >= 2 )) && [[ $2 != --* ]] || die "Missing value for $1."
            option=${1#--}
            printf -v "${option//-/_}" '%s' "$2"
            shift 2 ;;
        *) die "Unknown option $1. See --help." ;;
    esac
done

(( EUID == 0 )) || die 'Run from the Unraid root shell.'
[[ -d /boot/config ]] || die 'Unraid boot configuration is unavailable at /boot/config.'
assets=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
template="$assets/my-rex-unraid.xml"
profile="$assets/../container/codex-seccomp.json"
[[ -r $template && -s $profile ]] || die 'Keep unraid/ and container/ together from the same checkout.'

if (( interactive )); then
    prompt name 'Container name' "$name"
    prompt image 'Image tag or digest' ''
    prompt nested 'Enable nested Podman (y/N)' 'n'
    case $nested in
        y|Y|yes|YES) podman=1 ;;
        n|N|no|NO) ;;
        *) die 'Answer y or n for Podman.' ;;
    esac
fi

[[ $name =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]+$ ]] || die 'Enter a valid Docker container name.'
[[ $image =~ ^[a-zA-Z0-9][a-zA-Z0-9_.:/@-]*$ ]] || die 'Specify a Docker image reference with --image.'
default_appdata="/mnt/user/appdata/$name"
default_port=2222
if (( podman )); then
    default_port=2223
    default_appdata=
    if mountpoint -q -- /mnt/cache; then
        default_appdata="/mnt/cache/appdata/$name"
    fi
fi
if (( interactive )); then
    while true; do
        prompt appdata 'Appdata path (direct pool path for Podman)' "$default_appdata"
        if resolved_appdata=$(appdata_path "$appdata"); then
            appdata=$resolved_appdata
            break
        fi
        printf 'Try another appdata path. Setup is still running.\n' >&2
    done
    prompt bind_ip 'SSH bind IPv4 address' "$bind_ip"
    prompt port 'SSH host port' "$default_port"
    prompt workspace 'Writable workspace path (optional)' ''
    prompt keys 'Public key file path (optional)' ''
else
    appdata=$(appdata_path "${appdata:-$default_appdata}")
fi
port=${port:-$default_port}
[[ $port =~ ^[1-9][0-9]{0,4}$ ]] && (( port <= 65535 )) || die 'Use a port from 1 to 65535.'
[[ $bind_ip =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ && $bind_ip != 0.0.0.0 ]] \
    || die 'Use a specific IPv4 address for SSH.'
IFS=. read -r -a octets <<< "$bind_ip"
for octet in "${octets[@]}"; do
    [[ $octet == 0 || $octet != 0* ]] && (( octet <= 255 )) || die 'Invalid SSH IPv4 address.'
done
if [[ -n $workspace ]]; then
    workspace=$(storage_path "$workspace")
fi
[[ -z $keys || ( -f $keys && -r $keys ) ]] || die "Could not read public keys from $keys."

step='Acquire the setup lock'
mkdir -p -- /run/lock
exec 9>"/run/lock/rex-unraid-$name.lock"
flock -x 9
work=$(mktemp -d)

step='Prepare SSH public keys'
authorized="$appdata/auth/authorized_keys"
for path in "$appdata/home" "$appdata/brew" "$appdata/ssh" "$appdata/auth" "$authorized"; do
    [[ ! -L $path ]] || die "Use a real file or directory at $path."
done
[[ ! -e $authorized || -f $authorized ]] || die "Expected a regular file at $authorized."
declare -A installed_keys=()
: > "$work/authorized_keys"
if [[ -s $authorized ]]; then
    if grep -q -- '^-----BEGIN .*PRIVATE KEY-----' "$authorized"; then
        die "Remove private key material from $authorized before rerunning setup."
    fi
    awk '1' "$authorized" > "$work/authorized_keys"
    while read -r _ fingerprint _; do
        [[ -z $fingerprint ]] || installed_keys[$fingerprint]=1
    done < <(ssh-keygen -lf "$authorized" 2>/dev/null || true)
fi
if [[ -n $keys ]]; then
    while IFS= read -r line || [[ -n $line ]]; do
        add_public_key "$line"
    done < "$keys"
fi
if (( ${#installed_keys[@]} == 0 )); then
    [[ -t 0 ]] || die 'Pass --keys FILE with a public key or rerun in a terminal to paste one.'
    printf 'Paste one OpenSSH public key (the contents of a .pub file), then press Enter.\n' >&2
    IFS= read -r line || die 'No public key was entered.'
    add_public_key "$line"
    (( ${#installed_keys[@]} > 0 )) || die 'No public key was entered.'
fi

step="Prepare appdata at $appdata"
install -d -m 0750 -o 0 -g 0 -- "$appdata"
install -d -m 0700 -o 1000 -g 100 -- "$appdata/home"
install -d -m 0750 -o 1000 -g 100 -- "$appdata/brew"
install -d -m 0700 -o 0 -g 0 -- "$appdata/ssh"
install -d -m 0755 -o 0 -g 0 -- "$appdata/auth"
install_file "$work/authorized_keys" "$authorized" 0644
install_file "$profile" "$appdata/codex-seccomp.json" 0644

if [[ -n $workspace && ! -d $workspace ]]; then
    step="Create the workspace at $workspace"
    install -d -m 0750 -o 1000 -g 100 -- "$workspace"
fi

podman_args=
if (( podman )); then
    step="Prepare Podman storage at $appdata/home"
    podman_args=' --security-opt systempaths=unconfined --tmpfs /run/user/1000:uid=1000,gid=100,mode=0700 --env XDG_RUNTIME_DIR=/run/user/1000'
    # Write only as rexuser, even if an existing home contains symlinks.
    (
        cd -- "$appdata/home"
        setpriv --reuid=1000 --regid=100 --clear-groups bash -eu -c '
            mkdir -p .config/containers
            config=.config/containers/storage.conf
            if [[ ! -e $config && ! -L $config ]]; then
                set -o noclobber
                printf "[storage]\ndriver = \"vfs\"\n" > "$config"
            fi
        '
    )
fi

step='Render the Docker template'
printf -v seccomp_arg '%q' "seccomp=$appdata/codex-seccomp.json"
appdata_xml=$(xml_replacement "$appdata")
image_xml=$(xml_replacement "$image")
seccomp_xml=$(xml_replacement "$seccomp_arg")
workspace_xml=$(xml_replacement "$workspace")
template_marker='<!-- Generated by rex-unraid setup.sh -->'
sed \
    -e "1a\\$template_marker" \
    -e "s|<Name>rex</Name>|<Name>$name</Name>|" \
    -e "s|<Repository>.*</Repository>|<Repository>$image_xml</Repository>|" \
    -e 's|<Overview>.*</Overview>|<Overview>Rex server with Codex CLI, zsh, sudo, and persistent Homebrew.</Overview>|' \
    -e "/<Config /s|/mnt/user/appdata/rex/|$appdata_xml/|g" \
    -e "/<ExtraParams>/s|127.0.0.1:2222:22/tcp|$bind_ip:$port:22/tcp|" \
    -e "/<ExtraParams>/s|seccomp=/mnt/user/appdata/rex/codex-seccomp.json|$seccomp_xml|" \
    -e "/<ExtraParams>/s|</ExtraParams>|$podman_args</ExtraParams>|" \
    "$template" > "$work/template.xml"
if [[ -n $workspace ]]; then
    sed -i \
        -e "/Target=\"\/workspace\"/s|Default=\"\" Mode=\"ro\"|Default=\"$workspace_xml\" Mode=\"rw\"|" \
        -e "/Target=\"\/workspace\"/s|/>|>$workspace_xml</Config>|" \
        "$work/template.xml"
fi

template_dir=/boot/config/plugins/dockerMan/templates-user
template_path="$template_dir/my-$name.xml"
step="Install the Docker template at $template_path"
mkdir -p -- "$template_dir"
[[ ! -L $template_path && ( ! -e $template_path || -f $template_path ) ]] \
    || die "Expected a regular template file at $template_path."
if [[ -s $template_path ]] && ! grep -Fxq -- "$template_marker" "$template_path"; then
    printf '\n=== REX SETUP COMPLETE ===\n'
    printf 'Prepared %s. Kept the existing Unraid template at %s.\n' "$appdata" "$template_path"
    printf 'Review or change its settings in the Unraid Docker tab.\n'
    completed=1
    exit 0
fi
install_file "$work/template.xml" "$template_path"
[[ -s $template_path ]] || die "The installed template is missing or empty at $template_path."

printf '\n=== REX SETUP COMPLETE ===\n'
printf 'Prepared %s and installed %s.\n' "$appdata" "$template_path"
printf 'In Docker → Add Container, select %s under User templates and click Apply.\n' "$name"
printf 'Rex connection URL: ssh://rexuser@%s:%s/run/rex/server.sock\n' "$bind_ip" "$port"
if [[ $bind_ip == 127.0.0.1 ]]; then
    printf 'The default SSH bind address allows connections from Unraid itself. Use --bind-ip for LAN access.\n'
fi
completed=1
