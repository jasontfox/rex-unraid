# Rex on Unraid

Run a personal Rex server and Codex CLI in Docker on Unraid 7.4.1. The first version serves one user on several client platforms over SSH on the trusted LAN. Rex launches shells and programs inside the container, with an optional Unraid share at `/workspace`. Running jobs may end at restart. Tailscale is a later phase.

## LAN deployment design

- **Image.** Use Debian 13 slim and target `linux/amd64`. The Intel Core i3-10105 supports SSE4.2 and the host has 8 GB of RAM. Pin the Rex preview archive and the complete Codex CLI package by version and vendor digest. Install Rex’s terminfo entry, validate both executable versions, and keep login material in the mounted home. [Rex Linux installation](https://www.superlogical.com/rex/docs/linux/installation) · [Intel CPU specifications](https://www.intel.com/content/www/us/en/products/sku/201894/intel-core-i310105-processor-6m-cache-up-to-4-40-ghz/specifications.html) · [Codex release](https://github.com/openai/codex/releases/tag/rust-v0.172.0)
- **Processes.** Run `rex server run` in the foreground as a dedicated non-root account, provisionally `rexuser`. Use an explicit owner-only socket at `/run/rex/server.sock` and a persistent state directory under the account’s home. An init and supervisor manage Rex and foreground OpenSSH, stop the container if either essential process exits unexpectedly, and forward SIGTERM so Rex can save its sessions. Capture both services in Docker logs. Check readiness with a real Rex request as the service user on the exact socket and set `REX_AUTOSTART=0` in the probe and the server-side SSH command environment. [Rex server modes](https://www.superlogical.com/rex/docs/linux/server-modes) · [Rex foreground server](https://www.superlogical.com/rex/docs/reference/cli#rex-server-run)
- **Access.** Publish only container SSH on a Docker bridge, using `<UNRAID_LAN_IP>:2222:22` as the proposed mapping. Connect from Rex using `ssh://rexuser@<UNRAID_LAN_IP>:2222/run/rex/server.sock`. Allow only designated public keys for that one account, disable password and root login, and verify the SSH host key fingerprint on first connection. Limit source access at the network boundary where multiple networks can route to Unraid and keep router ingress closed. Binding to a LAN address constrains the destination, so verify the intended source restrictions and IPv6 separately. A valid SSH key grants command execution as the container account. [Rex SSH access](https://www.superlogical.com/rex/docs/linux/remote-access#ssh) · [OpenSSH configuration](https://man.openbsd.org/sshd_config) · [Docker port publishing](https://docs.docker.com/engine/network/port-publishing/)
- **Storage.** Use dedicated appdata paths under `/mnt/user/appdata/rex` for the Rex and Codex home, the per-deployment SSH host key and machine ID, and a read-only authorized keys file managed by the operator. Keep SSH identity and authorization outside the Rex account’s writable home. Use UID `1000` and GID `100` for the workload. Mount the selected Unraid share or subdirectory at `/workspace`. Keep the Docker socket, Unraid system paths, and host privileges outside the container. [Unraid Docker storage and mappings](https://docs.unraid.net/unraid-os/using-unraid-to/run-docker-containers/managing-and-customizing-containers/) · [Rex machine identity](https://www.superlogical.com/rex/docs/linux/server-modes#shared-home-directories)

## Build and deployment plan

1. Confirm the available Rex package and client versions, Unraid version and CPU, reachable networks, and the programs and data needed inside the container. Verify the vendor package can be obtained privately through an authorized route. Record the release and the verified artifact identity. [Rex client availability](https://www.superlogical.com/rex/docs/installation) · [Rex iOS SSH settings](https://www.superlogical.com/rex/docs/reference/ios-settings#remote-hosts)
2. Create the Dockerfile, startup and supervision configuration, SSH configuration, and a smoke-test procedure. Build a versioned image on a Docker-capable machine or on Unraid. Test startup against empty appdata and verify the package, permission checks, readiness, and shutdown on a disposable instance. Validate the SSH configuration with `sshd -t` and a real public-key login. Verify the intended Rex client works with the SSH forwarding settings.
3. Load a private image archive with `docker load` if built off-host. Configure Unraid Docker Manager with the exact loaded image tag, explicit IP-bound publish rule, and appdata mappings. Inspect the effective port bindings and mounts for wildcard publishes or implicit share mounts. Verify Add Container and Edit/Apply on the target Unraid version. Use a documented Docker CLI launch if the target WebGUI cannot use the local image or express the required publish rule. [Unraid Docker overview](https://docs.unraid.net/unraid-os/using-unraid-to/run-docker-containers/overview/) · [Docker image save](https://docs.docker.com/reference/cli/docker/image/save/) · [Unraid WebGUI source](https://github.com/unraid/webgui/blob/master/emhttp/plugins/dynamix.docker.manager/include/CreateDocker.php#L2468)
4. Run the acceptance checks below on the target before enabling Unraid Auto-Start. Record the final UID/GID, port and mount settings, and client versions verified. For updates, back up stopped appdata, retain the old image archive outside Docker’s image storage, load the new tag, and apply the new configuration through Edit. Unraid’s update action attempts a registry pull. Roll back using the previous tag and its matching appdata snapshot. [Unraid WebGUI update source](https://github.com/unraid/webgui/blob/master/emhttp/plugins/dynamix.docker.manager/include/CreateDocker.php#L2627) · [Rex upgrade behavior](https://www.superlogical.com/rex/docs/linux/upgrading)

## Acceptance checks

| Check | Expected result |
| --- | --- |
| Real client and PTY | The intended Rex app connects over the explicit SSH URL, opens a terminal, and runs as the expected non-root UID. A client disconnect and reconnect reaches the same live session. A terminal program renders and resizes correctly with the configured terminfo. |
| One Rex instance | The in-container and LAN CLI reach the same server instance and see the same test session. A wrong socket fails without starting a second server. The health check reports failure when Rex is unavailable. |
| Access boundaries | A trusted LAN client with its authorized key connects. Unknown keys, password login, and root login fail. Excluded networks and IPv6 paths cannot reach the port. Check Docker’s actual bindings and routes. |
| Ownership and persistence | The Rex account writes to its own home and requested writable mounts. It has read-only access to any read-only share and cannot alter SSH authorization or host keys. Recreation preserves the home, configuration, Rex host ID, saved layout where supported, and SSH fingerprint. |
| Codex CLI | The CLI starts as the Rex user, and `codex sandbox -- /bin/true` runs inside the command sandbox. Validate the per-container seccomp profile on Unraid before relying on Codex tool calls. |
| Process and shutdown behavior | In a disposable test, either essential process exiting takes the container down and leaves it eligible for its configured restart. Unraid WebGUI Stop gives Rex enough time to save state. Live shell processes end when the server stops. Verify stop timing again for the host or Docker service shutdown path when it can be tested. |
| Upgrade and rollback | Start a new version with backed-up state, verify the intended client, and restore the previous image and state snapshot in a rehearsal. |

[Rex API server status](https://www.superlogical.com/rex/docs/reference/api#serverstatus) · [Rex session stop behavior](https://www.superlogical.com/rex/docs/reference/cli#rex-server-stop) · [Unraid shutdown timeouts](https://docs.unraid.net/unraid-os/troubleshooting/common-issues/unclean-shutdowns/#configuring-shutdown-timeouts)

## Tailscale phase

For one user, evaluate Rex’s built-in Tailscale as a separate tailnet device using the same foreground server and persistent state. Confirm client compatibility, MagicDNS, HTTPS certificates, owner-only access, and enrollment persistence. Revisit how access maps to accounts if several people need separate identities. [Rex remote access](https://www.superlogical.com/rex/docs/linux/remote-access#built-in-tailscale)

## Goldfish review

- **Goldfish 1** reviewed Rex and client behavior. The plan now verifies the real SSH transport and exact socket, checks client compatibility and terminfo, and tests both server instance and persistent identity.
- **Goldfish 2** reviewed Unraid integration. The plan treats an IP-bound port as a destination restriction, checks the effective firewall and WebGUI behavior, and includes versioned local image handling.
- **Goldfish 3** reviewed operations. The plan now tests process failures, preserves SSH host identity, measures shutdown with active sessions, and rehearses a rollback with the matching state snapshot.

## Deployment inputs

- Set the Unraid LAN IPv4 address and available host port. Test access from your actual trusted and excluded networks.
- Choose the workspace path and its write permissions when adding the optional mount.
- The Windows key has been created. On Unraid, authorize its public half and any additional client keys. Record the client platforms and versions confirmed during acceptance.

## Implementation status

The LAN image was built and tested on November 25, 2026 in Ubuntu WSL with Docker Engine 29.9.2. It uses Rex `0.1.0-preview.24` and Codex CLI `0.172.0`. The local image archive was reloaded and verified against its adjacent SHA-256 file. Generated archives and checksums belong in the ignored `dist/` directory. [Docker build and transfer](README.md#build-or-load-the-image)

The disposable Bridge test reached the foreground Rex instance through its explicit Unix socket over SSH. It accepted the authorized key, rejected an unknown key and root login, and rejected forwarding to unrelated TCP or Unix socket destinations. A Rex session wrote to `/workspace`. Recreation restored the saved session and kept the Rex host identity and SSH fingerprint. A forced OpenSSH exit caused the supervisor to stop Rex and exit with an error.

The WSL Docker default seccomp profile blocked Codex’s nested user namespace. The supplied Docker profile passed `codex sandbox -- /bin/true` as `rexuser` with the documented capability set and no-new-privileges flag. [Codex Docker settings](README.md#enable-the-codex-command-sandbox)

Pending on Unraid 7.4.1 are the Docker Manager installation, host firewall and mount checks, Codex sandbox and account login, connections from the intended Rex apps, and a WebGUI shutdown with an active session. Rehearse image and appdata rollback before the first upgrade. Start the Tailscale phase after the LAN deployment passes acceptance.
