# Rex on Unraid

Run a personal Rex server and Codex CLI in a Debian 13 container on Unraid 7.4.1. The image targets `linux/amd64`. The Intel Core i3-10105 supports the SSE4.2 instructions required by Rex. The client connects over SSH on the trusted LAN. The image includes Rex `0.1.0-preview.24` and Codex CLI `0.172.0`, both checked against their published release digests. [Rex requirements](https://www.superlogical.com/rex/docs/linux/installation#system-requirements) · [Intel CPU specifications](https://www.intel.com/content/www/us/en/products/sku/201894/intel-core-i310105-processor-6m-cache-up-to-4-40-ghz/specifications.html) · [Codex release](https://github.com/openai/codex/releases/tag/rust-v0.172.0)

## Build or load the image

If you already have the local build archive from `dist/`, use it for the transfer below. A fresh checkout contains the build files and the seccomp profile. Build and export an image to generate the archive.

Build from the repository on a Docker machine with BuildKit.

```sh
docker build --platform linux/amd64 -t rex-unraid:0.1.0-preview.24-codex.0.172.0 .
```

For an off-host build, save a private archive and its checksum.

```sh
mkdir -p dist
archive=rex-unraid-0.1.0-preview.24-codex.0.172.0.tar.gz
docker image save rex-unraid:0.1.0-preview.24-codex.0.172.0 |
  gzip -1 > "dist/$archive"
(cd dist && sha256sum "$archive" > "$archive.sha256")
```

Copy the archive, its `.sha256` file, and `container/codex-seccomp.json` to a folder on an existing Unraid share. For example, `\\<unraid-host>\downloads\rex-install` over SMB is `/mnt/user/downloads/rex-install` in the Unraid terminal. Substitute your share name for `downloads`.

```sh
cd /mnt/user/downloads/rex-install
archive=rex-unraid-0.1.0-preview.24-codex.0.172.0.tar.gz
sha256sum -c "$archive.sha256" && docker image load -i "$archive"
```

## Prepare appdata on Unraid

Run in the Unraid terminal. Set the source file to a text file with one SSH **public** key per line. On a client with app-managed SSH keys, export its public key and add it to this list.

```sh
appdata=/mnt/user/appdata/rex
public_keys=/path/to/client-public-keys

install -d -m 0750 -o root -g root "$appdata"
install -d -m 0700 -o 1000 -g 100 "$appdata/home"
install -d -m 0700 -o root -g root "$appdata/ssh"
install -d -m 0755 -o root -g root "$appdata/auth"
install -m 0644 -o root -g root "$public_keys" "$appdata/auth/authorized_keys"
```

The container initializes its SSH host key and Rex machine ID in `appdata/rex/ssh`. Keep this directory and the home directory private. The home contains Rex configuration and saved state, along with Codex settings and login after you authenticate.

## Configure Unraid Docker Manager

In **Docker → Add Container**, use the following settings. Use **Advanced View** for Extra Parameters. Replace `192.168.1.10` with your Unraid LAN IPv4 address. Use an unused TCP port if `2222` is taken.

| Field | Value |
| --- | --- |
| Name | `rex` |
| Repository | `rex-unraid:0.1.0-preview.24-codex.0.172.0` |
| Network Type | Bridge |
| Privileged | Off |
| Tailscale | Off |
| Extra Parameters | `--publish 192.168.1.10:2222:22/tcp --stop-timeout 25` |

Add these entries as **Path** mappings. Use the publish rule in Extra Parameters for SSH. An additional Port entry can expose SSH on other interfaces.

| Host path | Container path | Access |
| --- | --- | --- |
| `/mnt/user/appdata/rex/home` | `/home/rexuser` | Read/write |
| `/mnt/user/appdata/rex/ssh` | `/var/lib/rex-ssh` | Read/write |
| `/mnt/user/appdata/rex/auth` | `/run/rex-auth` | Read-only |
| `/mnt/user/<share-or-subfolder>` | `/workspace` | Optional. Use read/write for an editable workspace or read-only to browse. |

For a writable workspace, give UID `1000` or GID `100` the required access on the chosen share or subfolder. The container uses that identity and leaves share ownership to Unraid. You can start a session in `/workspace` with `rex -S "$rex_url" new --cwd /workspace`, or run `cd /workspace` from a Rex terminal. If you skip the mount, use the persistent home for files you want to keep. [Unraid Docker path mappings](https://docs.unraid.net/unraid-os/using-unraid-to/run-docker-containers/managing-and-customizing-containers/) · [Rex session options](https://www.superlogical.com/rex/docs/reference/cli)

If you are using the terminal to create the container, this is the equivalent launch. Add the optional workspace mount before the image tag, for example `--mount type=bind,src=/mnt/user/my-project,dst=/workspace`.

```sh
docker run -d --name rex --network bridge --stop-timeout 25 \
  --publish 192.168.1.10:2222:22/tcp \
  --mount type=bind,src=/mnt/user/appdata/rex/home,dst=/home/rexuser \
  --mount type=bind,src=/mnt/user/appdata/rex/ssh,dst=/var/lib/rex-ssh \
  --mount type=bind,src=/mnt/user/appdata/rex/auth,dst=/run/rex-auth,readonly \
  rex-unraid:0.1.0-preview.24-codex.0.172.0
```

## Enable the Codex command sandbox

Codex uses Bubblewrap to sandbox commands on Linux. Docker’s default seccomp profile blocked nested namespaces in the local test. The supplied [profile](container/codex-seccomp.json) lets Bubblewrap run under a restricted Docker profile. It is based on OpenAI’s published profile with two additions for OpenSSH’s pre-authentication chroot and PAM audit socket. The server needs the listed capabilities for startup, SSH privilege separation, and child shutdown. [Codex sandbox](https://developers.openai.com/codex/concepts/sandboxing) · [Upstream profile](https://github.com/openai/codex-security/blob/23c37b9c98815f3360160e7ad57fdd649f8ac704/docker/codex-security-seccomp.json) · [Docker seccomp configuration](https://docs.docker.com/engine/security/seccomp/)

Copy `container/codex-seccomp.json` to Unraid. Install it at `/mnt/user/appdata/rex/codex-seccomp.json` on the host as a root-owned file. Append this line to **Extra Parameters**, or add the same flags before the image tag in the CLI command.

```text
--security-opt seccomp=/mnt/user/appdata/rex/codex-seccomp.json --security-opt no-new-privileges=true --cap-drop ALL --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add KILL --cap-add NET_BIND_SERVICE --cap-add SETGID --cap-add SETUID --cap-add SYS_CHROOT --cap-add AUDIT_WRITE
```

Keep **Privileged** off. From a Rex terminal, run `codex sandbox -- /bin/true` to confirm the profile works on your host before relying on Codex for tool calls.

## Connect and check the deployment

Enter `ssh://rexuser@192.168.1.10:2222/run/rex/server.sock` in **Add Remote Host** on each Rex client. Check the SSH fingerprint shown by the client against the one in `docker logs rex`. Then open a terminal and run `id`, `rex version`, and `codex --version`. [Rex remote hosts over SSH](https://www.superlogical.com/rex/docs/linux/remote-access#ssh)

```sh
# From Unraid
docker inspect -f '{{.State.Health.Status}} {{json .HostConfig.PortBindings}}' rex
docker inspect -f '{{range .Mounts}}{{println .Source .Destination .RW}}{{end}}' rex

# From a LAN client with the Rex CLI and the authorized key
rex_url=ssh://rexuser@192.168.1.10:2222/run/rex/server.sock
rex -S "$rex_url" ls
```

Check that Docker publishes SSH only to the specified IPv4 address and lists the intended mounts. Confirm an unauthorized key fails and an excluded network cannot reach port `2222`. A destination IP binding does not filter clients by source. If other VLANs or VPNs can route to that IP, use your network firewall to limit access to the trusted LAN. Keep WAN ingress closed. Once the real clients work, enable **Auto-Start** in Unraid if desired. [Docker port publishing](https://docs.docker.com/engine/network/port-publishing/) · [Unraid startup controls](https://docs.unraid.net/unraid-os/using-unraid-to/run-docker-containers/managing-and-customizing-containers/#advanced-container-startup)

### Use a named SSH key on Windows

Add a host alias in `%USERPROFILE%\.ssh\config`. The example uses the key named `id_rex_unraid_windows`, the container account `rexuser`, and the example Unraid address and port. [Windows OpenSSH client configuration](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-server-configuration)

```sshconfig
Host rex-unraid
    HostName 192.168.1.10
    User rexuser
    Port 2222
    IdentityFile ~/.ssh/id_rex_unraid_windows
    IdentitiesOnly yes
```

Add the contents of `id_rex_unraid_windows.pub` as a line in `/mnt/user/appdata/rex/auth/authorized_keys`. Keep the private key on Windows. Run `ssh rex-unraid` in PowerShell to check the fingerprint and test your key. If the key has a passphrase, load it into your running Windows SSH agent with `ssh-add "$HOME\.ssh\id_rex_unraid_windows"`. Use `ssh://rexuser@rex-unraid:2222/run/rex/server.sock` in Rex and adjust the URL’s port if you changed the host port. [Rex SSH address syntax](https://www.superlogical.com/rex/docs/linux/remote-access#ssh)

## Use Codex

From a Rex terminal, change to your repository and run `codex`. For browserless sign-in, enable device code login in your ChatGPT security settings and run `codex login --device-auth`. Open the displayed URL on another device and enter the code. Codex uses outbound HTTPS. Login and configuration persist in the container home. [Codex authentication](https://developers.openai.com/codex/auth)

## Update and roll back

Stop the container and back up its appdata before changing versions. Save the old image archive outside Docker’s image storage. Load the new tag and apply it through **Docker → Edit**. A rollback uses the old tag and its corresponding appdata backup. A restart ends running shell processes. For changes to stop timing, verify a WebGUI stop with an active Rex session since Unraid applies its own Docker stop timeout. [Unraid shutdown timeouts](https://docs.unraid.net/unraid-os/troubleshooting/common-issues/unclean-shutdowns/#configuring-shutdown-timeouts)
