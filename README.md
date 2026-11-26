# Rex on Unraid

Run a personal Rex server and Codex CLI in a Debian 13 container on Unraid 7.4.1. The image targets `linux/amd64`. The Intel Core i3-10105 supports the SSE4.2 instructions required by Rex. The client connects over SSH on the trusted LAN. The image includes Rex `0.1.0-preview.24` and Codex CLI `0.172.0`, both checked against their published release digests. `rexuser` uses zsh and has passwordless sudo inside the container. Homebrew starts at `7.0.16` on a persistent mount. [Rex requirements](https://www.superlogical.com/rex/docs/linux/installation#system-requirements) · [Intel CPU specifications](https://www.intel.com/content/www/us/en/products/sku/201894/intel-core-i310105-processor-6m-cache-up-to-4-40-ghz/specifications.html) · [Codex release](https://github.com/openai/codex/releases/tag/rust-v0.172.0) · [Homebrew release](https://github.com/Homebrew/brew/releases/tag/7.0.16)

## Build or load the image

If you already have the local build archive from `dist/`, use it for the transfer below. A fresh checkout contains the build files and the seccomp profile. Build and export an image to generate the archive.

Build from the repository on a Docker machine with BuildKit.

```sh
docker build --platform linux/amd64 -t rex-unraid:0.1.0-preview.24-codex.0.172.0-r2 .
```

For an off-host build, save a private archive and its checksum.

```sh
mkdir -p dist
archive=rex-unraid-0.1.0-preview.24-codex.0.172.0-r2.tar.gz
docker image save rex-unraid:0.1.0-preview.24-codex.0.172.0-r2 |
  gzip -1 > "dist/$archive"
(cd dist && sha256sum "$archive" > "$archive.sha256")
```

Copy the archive, its `.sha256` file, `container/codex-seccomp.json`, and `unraid/my-rex-unraid.xml` to a folder on an existing Unraid share. For example, `\\<unraid-host>\downloads\rex-install` over SMB is `/mnt/user/downloads/rex-install` in the Unraid terminal. Substitute your share name for `downloads`.

```sh
cd /mnt/user/downloads/rex-install
archive=rex-unraid-0.1.0-preview.24-codex.0.172.0-r2.tar.gz
sha256sum -c "$archive.sha256" && docker image load -i "$archive"
```

### Build and publish with GitHub Actions

Open pull requests against `main` and wait for the **Build image** check before merging. The [Container image workflow](.github/workflows/container-image.yml) builds the `linux/amd64` image when a PR to `main` opens, changes, or reopens, on every push to `main`, and on manual runs. PRs from a branch in this repository publish a preview tagged `pr-<number>-<12-character-merge-sha>` after the build and Podman smoke test. Fork PRs run the checks without publishing. The workflow publishes SemVer tags only for the result of a merged PR targeting `main`.

Configure `main` branch protection to require a pull request and the **Build image** check, including for administrators. Private repositories need a GitHub plan with branch protection. [GitHub branch protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)

Image versions use SemVer for this container project. The [VERSION](VERSION) file starts at `0.1.0`. Each first-parent commit after that version change increments the patch number, so a squash merge or merge commit advances it by one. A rebase merge or an unpublished commit can leave gaps. To start a new minor or major release, change `VERSION` in the PR to a version above the current one, such as `0.2.0`. Each published image uses its SemVer tag and includes the Git commit SHA in its OCI metadata. The run summary shows the image reference.

The workflow uses GitHub’s temporary Actions token to publish to the public `ghcr.io/jasontfox/rex-unraid` package. The repository needs Write permission under **Manage Actions access** in the package settings. [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)

To use a published build, paste its image reference from the run summary into Unraid’s **Repository** field. Unraid can pull the image anonymously when you apply the template. To pull it from the terminal:

```sh
image='ghcr.io/jasontfox/rex-unraid:0.1.0'
docker pull "$image"
```

## Prepare appdata on Unraid

Run in the Unraid terminal. Set the source file to a text file with one SSH **public** key per line. On a client with app-managed SSH keys, export its public key and add it to this list.

```sh
appdata=/mnt/user/appdata/rex
public_keys=/path/to/client-public-keys

install -d -m 0750 -o root -g root "$appdata"
install -d -m 0700 -o 1000 -g 100 "$appdata/home"
install -d -m 0750 -o 1000 -g 100 "$appdata/brew"
install -d -m 0700 -o root -g root "$appdata/ssh"
install -d -m 0755 -o root -g root "$appdata/auth"
install -m 0644 -o root -g root "$public_keys" "$appdata/auth/authorized_keys"
```

The container initializes its SSH host key and Rex machine ID in `appdata/rex/ssh`. Keep this directory and the home directory private. The home contains Rex configuration and saved state, along with Codex settings and login after you authenticate.

## Configure Unraid Docker Manager

### Install with the local template

The [Unraid template](unraid/my-rex-unraid.xml) fills in the image tag, Bridge network, appdata paths, and Codex sandbox options for a new installation. For an existing `rex` container, use **Docker → Edit** and follow the [upgrade instructions](#update-and-roll-back).

Load the image and prepare appdata and authorized keys first. In the Unraid terminal, run these commands from the folder where you copied the files.

```sh
install -m 0644 -o root -g root codex-seccomp.json /mnt/user/appdata/rex/codex-seccomp.json
mkdir -p /boot/config/plugins/dockerMan/templates-user
cp my-rex-unraid.xml /boot/config/plugins/dockerMan/templates-user/
```

1. Open **Docker → Add Container** and select **rex-unraid** under **User templates**.
2. In **Advanced View → Extra Parameters**, replace `127.0.0.1` in the existing publish rule with your Unraid LAN IPv4 address. Keep the IP in the rule, and change `2222` there if you need another host port. The template starts with a loopback binding so it requires an explicit change for LAN access.
3. Set **Workspace** to your chosen share path if you want one. Its default access mode is read-only. Edit the mapping to choose read/write for a workspace you intend to modify.
4. Click **Apply** and follow the [connection checks](#connect-and-check-the-deployment).

The template appears in Docker Manager’s local template menu and uses the preloaded image tag. [Unraid user template storage](https://docs.unraid.net/community-applications/) · [Unraid template picker source](https://github.com/unraid/webgui/blob/master/emhttp/plugins/dynamix.docker.manager/include/CreateDocker.php#L941)

### Configure manually

In **Docker → Add Container**, use the following settings. Use **Advanced View** for Extra Parameters. Replace `192.168.1.10` with your Unraid LAN IPv4 address. Use an unused TCP port if `2222` is taken.

| Field | Value |
| --- | --- |
| Name | `rex` |
| Repository | `rex-unraid:0.1.0-preview.24-codex.0.172.0-r2` |
| Network Type | Bridge |
| Privileged | Off |
| Tailscale | Off |
| Extra Parameters | `--publish 192.168.1.10:2222:22/tcp --stop-timeout 25` |

Add these entries as **Path** mappings. Use the publish rule in Extra Parameters for SSH. An additional Port entry can expose SSH on other interfaces.

| Host path | Container path | Access |
| --- | --- | --- |
| `/mnt/user/appdata/rex/home` | `/home/rexuser` | Read/write |
| `/mnt/user/appdata/rex/brew` | `/home/linuxbrew` | Read/write |
| `/mnt/user/appdata/rex/ssh` | `/var/lib/rex-ssh` | Read/write |
| `/mnt/user/appdata/rex/auth` | `/run/rex-auth` | Read-only |
| `/mnt/user/<share-or-subfolder>` | `/workspace` | Optional. Use read/write for an editable workspace or read-only to browse. |

For a writable workspace, give UID `1000` or GID `100` the required access on the chosen share or subfolder. The container uses that identity and leaves share ownership to Unraid. You can start a session in `/workspace` with `rex -S "$rex_url" new --cwd /workspace`, or run `cd /workspace` from a Rex terminal. If you skip the mount, use the persistent home for files you want to keep. [Unraid Docker path mappings](https://docs.unraid.net/unraid-os/using-unraid-to/run-docker-containers/managing-and-customizing-containers/) · [Rex session options](https://www.superlogical.com/rex/docs/reference/cli)

If you are using the terminal to create the container, this is the equivalent launch. Add the optional workspace mount before the image tag, for example `--mount type=bind,src=/mnt/user/my-project,dst=/workspace`.

```sh
docker run -d --name rex --network bridge --stop-timeout 25 \
  --publish 192.168.1.10:2222:22/tcp \
  --mount type=bind,src=/mnt/user/appdata/rex/home,dst=/home/rexuser \
  --mount type=bind,src=/mnt/user/appdata/rex/brew,dst=/home/linuxbrew \
  --mount type=bind,src=/mnt/user/appdata/rex/ssh,dst=/var/lib/rex-ssh \
  --mount type=bind,src=/mnt/user/appdata/rex/auth,dst=/run/rex-auth,readonly \
  rex-unraid:0.1.0-preview.24-codex.0.172.0-r2
```

## Enable the Codex command sandbox

Codex uses Bubblewrap to sandbox commands on Linux. Docker’s default seccomp profile blocked nested namespaces in the local test. The supplied [profile](container/codex-seccomp.json) lets Bubblewrap run under a restricted Docker profile. It is based on OpenAI’s published profile with two additions for OpenSSH’s pre-authentication chroot and PAM audit socket. The listed capabilities cover startup, SSH privilege separation, child shutdown, and package installation. [Codex sandbox](https://developers.openai.com/codex/concepts/sandboxing) · [Upstream profile](https://github.com/openai/codex-security/blob/23c37b9c98815f3360160e7ad57fdd649f8ac704/docker/codex-security-seccomp.json) · [Docker seccomp configuration](https://docs.docker.com/engine/security/seccomp/)

Install `container/codex-seccomp.json` at `/mnt/user/appdata/rex/codex-seccomp.json` on Unraid as a root-owned file. The local template includes the flags below. For a manual setup, append them to **Extra Parameters** or add them before the image tag in the CLI command.

```text
--security-opt seccomp=/mnt/user/appdata/rex/codex-seccomp.json --cap-drop ALL --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER --cap-add KILL --cap-add NET_BIND_SERVICE --cap-add SETGID --cap-add SETUID --cap-add SYS_CHROOT --cap-add AUDIT_WRITE
```

Keep **Privileged** off. From a Rex terminal, run `codex sandbox -- /bin/true` to confirm the profile works on your host before relying on Codex for tool calls.

When upgrading from the initial image, remove `--security-opt no-new-privileges=true` from the container’s Extra Parameters. That flag prevents the setuid transition sudo needs. Any authorized SSH key holder can use sudo to become root inside this container.

## Test a PR image with rootless Podman

Use **Docker → Add Container** with the local template and name the second container `rex-test`. Set **Repository** to the `ghcr.io/jasontfox/rex-unraid:pr-…` reference in the PR's Actions summary. Keep Bridge mode and use `<UNRAID_LAN_IP>:2223:22/tcp` for the SSH publish rule. [Unraid container settings](https://docs.unraid.net/unraid-os/using-unraid-to/run-docker-containers/managing-and-customizing-containers/)

Follow [the appdata setup](#prepare-appdata-on-unraid) using `/mnt/<pool>/appdata/rex-test` as `appdata`, where `<pool>` is the name of your local pool, often `cache`. Replace the host path for each of the four appdata mounts with the corresponding path under `rex-test`. The `home` directory at `/home/rexuser` holds user settings and Podman's image store. A direct pool path gives Podman a local filesystem for its image layers. Keep this store outside a network share. You can reuse the same client public keys in the test `auth` directory. [Podman rootless storage](https://docs.podman.io/en/stable/markdown/podman.1.html#note-unsupported-file-systems-in-rootless-mode)

For source code, map a separate writable project folder to `/workspace` or clone into `~/src` on the test home mount. Give UID `1000` or GID `100` write access to the folder. Nested containers see paths inside `rex-test`, so a Podman bind mount uses `/workspace` or a path under `$HOME` as its source.

Point the seccomp flag at the profile from the PR, keep the capability flags in the template, and append these options to **Extra Parameters** on `rex-test`:

```text
--security-opt systempaths=unconfined --tmpfs /run/user/1000:uid=1000,gid=100,mode=0700 --env XDG_RUNTIME_DIR=/run/user/1000
```

The system-path exception lets Podman mount a new `/proc` for its nested containers. It removes Docker's default masked and read-only paths for this test container, so use it only on the development instance with trusted code and mounts. Keep the seccomp profile and leave **Privileged** off. [Docker security options](https://docs.docker.com/reference/cli/docker/container/run/#security-opt)

Connect Rex to `ssh://rexuser@<UNRAID_LAN_IP>:2223/run/rex/server.sock` and run the following as `rexuser`. On the fresh test home, configure VFS storage. VFS requires no FUSE device and uses extra disk space for image layers.

```sh
mkdir -p "$HOME/.config/containers"
printf '[storage]\ndriver = "vfs"\n' > "$HOME/.config/containers/storage.conf"
podman info --format '{{.Host.Security.Rootless}} {{.Store.GraphRoot}}'

# Use a directory under $HOME here if you did not map /workspace.
workdir=/workspace/podman-smoke
mkdir -p "$workdir"
podman run --rm --cgroups=disabled --network=none \
  --volume "$workdir:/work:rw" docker.io/library/alpine:3.22 \
  sh -ec 'id; printf "Podman can write here\n" > /work/probe.txt'
cat "$workdir/probe.txt"
```

From a checkout inside the test instance, try `podman build --format=docker --network=host --platform linux/amd64 -t localhost/rex-unraid:dev .`. Docker format preserves the Dockerfile's image health check. For this trusted Dockerfile, `--network=host` shares the outer `rex-test` container's Bridge network namespace so build steps can download dependencies. Run the built image with `podman run --rm --cgroups=disabled --network=none --entrypoint /bin/sh localhost/rex-unraid:dev -ec 'rex version; codex --version'`. Boot the actual PR image in Unraid for tests of SSH, persistent mounts, and Rex session behavior.

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

## Shell and package installation

New Rex terminals start in zsh. Put `.zshenv`, `.zprofile`, and `.zshrc` in the persistent Rex home at `/home/rexuser`. Zsh loads them according to its login and interactive startup rules. To load `.zshrc` for a command launched with the Rex CLI, use `rex run --interactive -- <command>`. [Zsh startup files](https://zsh.sourceforge.io/Doc/Release/Files.html) · [Rex CLI](https://www.superlogical.com/rex/docs/reference/cli)

Run `brew install <formula>` as `rexuser`. The first start seeds Homebrew at `/home/linuxbrew/.linuxbrew`. Later starts reuse the existing installation, including formulae and taps. Keep the Brew mount attached when replacing the container and include it in appdata backups. Use `brew update` and `brew upgrade` to manage that installation. [Homebrew on Linux](https://docs.brew.sh/Homebrew-on-Linux)

Use `sudo apt-get update` and `sudo apt-get install <package>` for Debian packages. Packages installed this way live in the container’s writable layer and are lost when it is recreated. Add Debian packages you need in every replacement to the Dockerfile.

## Update and roll back

Stop the container and back up its appdata before changing versions. Save the old image archive outside Docker’s image storage. For the first upgrade to the Homebrew image, create the `brew` appdata directory, add its mapping to `/home/linuxbrew`, and remove the old `no-new-privileges=true` option if present. Load the new tag and apply it through **Docker → Edit**. A rollback uses the old tag, deployment settings, and corresponding appdata backup. A restart ends running shell processes. For changes to stop timing, verify a WebGUI stop with an active Rex session since Unraid applies its own Docker stop timeout. [Unraid shutdown timeouts](https://docs.unraid.net/unraid-os/troubleshooting/common-issues/unclean-shutdowns/#configuring-shutdown-timeouts)
