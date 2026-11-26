# syntax=docker/dockerfile:1
FROM scratch AS releases
ADD --checksum=sha256:eb9dceba9fc6eddbe93c421a41cd3ddb5959521ba52bfb7055e4614f10940fe4 \
    https://blob.superlogical.com/download/rex/preview/ad122d66146b2d239c0f5f3c297f8318d49b29c9/rex-linux-amd64.tar.gz /rex.tar.gz
ADD --checksum=sha256:63e3b00065ed7f62166d0522e17f663cb866a31d80d03e63365482ed34a1d991 \
    https://github.com/openai/codex/releases/download/rust-v0.172.0/codex-package-x86_64-unknown-linux-musl.tar.gz /codex.tar.gz

FROM debian:trixie-slim

RUN test "$(dpkg --print-architecture)" = amd64 \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl file git ncurses-bin openssh-server \
        procps python3 sudo tini util-linux zsh \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/ssh/ssh_host_* \
    && useradd --uid 1000 --gid users --home-dir /home/rexuser --shell /bin/zsh rexuser \
    && install -d -m 0700 -o rexuser -g users /home/rexuser \
    && install -d -m 0700 /var/lib/rex-ssh \
    && install -d -m 0755 /home/linuxbrew /run/rex-auth /workspace /opt/codex

RUN --mount=type=bind,from=releases,source=/rex.tar.gz,target=/tmp/rex.tar.gz \
    --mount=type=bind,from=releases,source=/codex.tar.gz,target=/tmp/codex.tar.gz \
    set -eu; \
    staging="$(mktemp -d)"; \
    tar -xzf /tmp/rex.tar.gz -C "$staging"; \
    install -m 0755 "$staging/rex" /usr/local/bin/rex; \
    rex version > "$staging/version"; \
    read -r product version rest < "$staging/version"; \
    test "$product" = rex; \
    test "$version" = 0.1.0-preview.24; \
    rex terminfo show > "$staging/xterm-rex"; \
    tic -x -o /etc/terminfo "$staging/xterm-rex"; \
    tar --no-same-owner -xzf /tmp/codex.tar.gz -C /opt/codex; \
    ln -s /opt/codex/bin/codex /usr/local/bin/codex; \
    test "$(codex --version)" = 'codex-cli 0.172.0'; \
    rm -rf "$staging"

RUN set -eu; \
    seed=/opt/homebrew-seed; \
    install -d -m 0755 "$seed/bin" /usr/local/lib/rex-unraid; \
    git -c advice.detachedHead=false clone --quiet --depth=1 --branch 7.0.16 \
        https://github.com/Homebrew/brew.git "$seed/Homebrew"; \
    test "$(git -C "$seed/Homebrew" rev-parse HEAD)" = 7ef183d10e7d6e5620d7124b744b1dfbf69fc108; \
    git -C "$seed/Homebrew" switch --quiet -c stable; \
    git -C "$seed/Homebrew" config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'; \
    git -C "$seed/Homebrew" symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main; \
    ln -s ../Homebrew/bin/brew "$seed/bin/brew"

COPY --chmod=0644 container/sshd_config /etc/ssh/sshd_config.rex
COPY --chmod=0644 container/supervise.py /usr/local/lib/rex-unraid/supervise.py
COPY --chmod=0755 container/init-homebrew /usr/local/lib/rex-unraid/init-homebrew
COPY --chmod=0440 container/rex-sudoers /etc/sudoers.d/rexuser
RUN --mount=type=bind,source=container/zshenv,target=/tmp/rex-zshenv \
    cat /tmp/rex-zshenv >> /etc/zsh/zshenv \
    && visudo -c

ENV LANG=C.UTF-8 SHELL=/bin/zsh REX_AUTOSTART=0 REX_SERVER=/run/rex/server.sock
SHELL ["/bin/zsh", "-c"]
EXPOSE 22/tcp
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s \
    CMD ["/usr/bin/setpriv", "--reuid=rexuser", "--regid=users", "--clear-groups", "--reset-env", "/usr/bin/env", "REX_AUTOSTART=0", "/usr/local/bin/rex", "-S", "/run/rex/server.sock", "server", "status"]
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/bin/python3", "-u", "/usr/local/lib/rex-unraid/supervise.py"]
