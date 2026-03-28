# Atomic Image Wizard

A step-by-step graphical wizard for creating custom Fedora Atomic / bootc images.

Designed for users new to atomic desktops who want to customise their system image
without writing Containerfiles by hand.

> ⚠ **This project is in active development and has not had a stable release.**
> It is being shared to gather feedback across different Fedora Atomic spins and
> configurations. You should be comfortable using `bootc rollback` and the boot menu
> to recover from a bad deployment before using this tool. Do not use it as your only
> method of managing a machine you cannot afford to lose access to.

## Screenshots

<table>
<tr>
<td align="center" width="50%">
<img src="https://github.com/cvcassdev/atomic-image-wizard/raw/main/startpage.png" alt="Landing page"/>
<br><em>Landing page — load existing build or start fresh</em>
</td>
<td align="center" width="50%">
<img src="https://github.com/cvcassdev/atomic-image-wizard/raw/main/step1.png" alt="Step 1 — Base Image"/>
<br><em>Step 1 — Choose base image from live registry list</em>
</td>
</tr>
<tr>
<td align="center" width="50%">
<img src="https://github.com/cvcassdev/atomic-image-wizard/raw/main/step2.png" alt="Step 2 — Repositories"/>
<br><em>Step 2 — RPM Fusion, Copr, and custom repos</em>
</td>
<td align="center" width="50%">
<img src="https://github.com/cvcassdev/atomic-image-wizard/raw/main/step3.png" alt="Step 3 — Packages"/>
<br><em>Step 3 — Search and queue packages to install or remove</em>
</td>
</tr>
<tr>
<td align="center" width="50%">
<img src="https://github.com/cvcassdev/atomic-image-wizard/raw/main/step4.png" alt="Step 4 — Performance"/>
<br><em>Step 4 — Optional CachyOS performance tweaks</em>
</td>
<td align="center" width="50%">
<img src="https://github.com/cvcassdev/atomic-image-wizard/raw/main/step5.png" alt="Step 5 — Systemd"/>
<br><em>Step 5 — Enable or disable services at boot</em>
</td>
</tr>
<tr>
<td align="center" width="50%">
<img src="https://github.com/cvcassdev/atomic-image-wizard/raw/main/step6.png" alt="Step 6 — Review"/>
<br><em>Step 6 — Review and edit the generated Containerfile</em>
</td>
<td align="center" width="50%">
<img src="https://github.com/cvcassdev/atomic-image-wizard/raw/main/step7.png" alt="Step 7 — Build"/>
<br><em>Step 7 — Build with podman and deploy with bootc</em>
</td>
</tr>
<tr>
<td align="center" colspan="2">
<img src="https://github.com/cvcassdev/atomic-image-wizard/raw/main/step8.png" alt="Reboot prompt after successful deployment"/>
<br><em>Successful deployment — prompted to reboot and apply the new image</em>
</td>
</tr>
</table>

---

## Requirements

* Fedora Atomic desktop (Silverblue, Kinoite, Sway Atomic, Cosmic Atomic, or any bootc-compatible spin) — **Fedora 41 or later required**
* `podman` — present by default on all Fedora Atomic spins
* `bootc` — present by default on all Fedora Atomic spins
* `dnf5` — present by default on Fedora 41+
* Python 3.11+ and GTK4 — present by default on all Fedora Atomic spins
* `python3-gobject` and `gtk4` Python bindings — see note below

> **Note on PyGObject:** If the installer reports missing GTK4 bindings, add the
> following to your Containerfile and rebuild before running the installer:
>
> ```
> RUN dnf5 install -y python3-gobject gtk4 && dnf5 clean all
> ```

> **Minimum supported version:** Fedora 41. Older releases are not supported.
> Fedora 40 and earlier are EOL and pre-date dnf5 being the default on Atomic desktops.

---

## Installation

**One-liner — no git required:**

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/cvcassdev/atomic-image-wizard/main/install.sh)
```

**Or clone the repo if you prefer:**

```bash
git clone https://github.com/cvcassdev/atomic-image-wizard
cd atomic-image-wizard
bash install.sh
```

The installer will:

* Check that all dependencies are present and give clear guidance if anything is missing
* Create `~/bootc/` — this is where the wizard and your Containerfiles will live
* Copy `main.py` and the application icon into `~/bootc/`
* Install the icon to `~/.local/share/icons/`
* Install a `.desktop` entry to `~/.local/share/applications/`

After installation the wizard appears in your app launcher. No terminal needed after that.

If it doesn't appear immediately, log out and back in.

---

## Uninstall

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/cvcassdev/atomic-image-wizard/main/install.sh) --uninstall
```

Or if you still have the repo cloned:

```bash
bash install.sh --uninstall
```

This removes the desktop entry and icon. You will be asked separately whether to
remove `~/bootc/` — it will not be deleted without confirmation since your saved
Containerfiles live there.

---

## What it does

Walks you through seven steps to produce a custom bootc image based on any Fedora
Atomic base:

1. **Base Image** — choose from a dynamically fetched list of official Fedora Atomic images, or enter any custom registry URL
2. **Repositories** — enable RPM Fusion, Copr repos, or any custom repo setup command
3. **Packages** — search for and queue packages to install or remove
4. **Performance** — optional CachyOS kernel addons (requires kernel 6.12+, Fedora 41+)
5. **Systemd** — enable or disable services at boot
6. **Review** — edit the generated Containerfile before building
7. **Build** — build the image with podman, then deploy it with bootc

The wizard saves your Containerfile to `~/bootc/Containerfile`. On next launch it
will detect any existing Containerfile and offer to load it as a starting point for
a rebuild, modification, or upgrade.

After using this tool, podman will start to accumulate build cache and dangling image
layers that consume disk space. The landing page includes **disk cleanup utilities**
that safely remove these without touching your named images.

---

## Using custom or community base images

The base image field accepts any bootc-compatible image — not just the official Fedora
presets. This makes the wizard useful as a customisation layer on top of community
images such as:

* **[Universal Blue](https://universal-blue.org/)** (`ghcr.io/ublue-os/`) — images with NVIDIA drivers pre-baked, Bazzite, Aurora, and others
* **[Origami](https://origami.wf/)** — community Fedora Atomic spins with additional defaults
* Any other bootc-compatible image published to a public registry

This is particularly useful if you need something the official Fedora images don't
provide out of the box — for example, NVIDIA driver support. Point the wizard at a
community base image that already has drivers baked in, then use the wizard to add
your personal software preferences on top.

> **NVIDIA note:** Traditional akmod-nvidia does not work inside a container build.
> The recommended approach is to use a base image that already includes the drivers,
> such as those published by Universal Blue. COSMIC Atomic + NVIDIA does not yet have
> a pre-built community base image available, but this is expected to improve as
> COSMIC Atomic matures.

---

## Image list

The wizard fetches the available Fedora Atomic image list directly from the Quay.io
registry on first launch and caches it locally at
`~/.cache/atomic-image-wizard/presets.json`. The cache is refreshed automatically
every 7 days, or manually via the **↺ Refresh list** button on the Base Image page.

This means the image list stays current as new Fedora releases ship without requiring
a wizard update.

---

## Generated Containerfile syntax

All generated Containerfiles use **dnf5** syntax exclusively. This is correct for
Fedora 41+ Atomic images, where dnf5 is the default package manager inside the
container. Example output:

```dockerfile
FROM quay.io/fedora-ostree-desktops/silverblue:43

# ──────────────────────────────────────────────────────────────────
# 1. Add external repositories
# ──────────────────────────────────────────────────────────────────
RUN curl -fsSL https://pkgs.tailscale.com/stable/fedora/tailscale.repo \
        -o /etc/yum.repos.d/tailscale.repo \
    && dnf5 install -y \
        https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-43.noarch.rpm \
    && dnf5 clean all

# ──────────────────────────────────────────────────────────────────
# 2. Install desired packages
# ──────────────────────────────────────────────────────────────────
RUN dnf5 install -y \
        tailscale \
        zsh \
    && dnf5 clean all

# ──────────────────────────────────────────────────────────────────
# 4. Enable / disable services
# ──────────────────────────────────────────────────────────────────
RUN systemctl enable tailscaled
```

---

## Current status

Actively developed and tested on **Fedora 44 beta / Cosmic Atomic**. Builds and
deploys successfully on current Fedora Atomic spins.

Behaviour on other spins (Silverblue, Kinoite, Sway Atomic) may differ slightly —
particularly around default package sets and systemd service auto-detection. Feedback
from other spins is especially welcome.

---

## Known limitations

* Package search uses dnf5 exclusively and requires Fedora 41+. If searches time out
  or return no results, run `dnf5 makecache` in a terminal first.
* The Containerfile parser handles common patterns well but may not recognise every
  custom RUN command — unrecognised commands are flagged with a warning rather than
  silently dropped.
* Performance tweaks (CachyOS addons) require Linux kernel 6.12 or newer.
  Fedora 41 and later meet this requirement.
* NVIDIA driver support via akmod is not possible inside a container build. Use a
  community base image with drivers pre-baked instead (see above).
* The image list cache requires network access on first launch or after 7 days.
  If the registry is unreachable the wizard falls back to a built-in preset list.

---

## Reporting issues

Please include:

* Which Fedora Atomic spin and version you are running
* What you were doing when the issue occurred
* The contents of your Containerfile if relevant (Review page → Save Containerfile)
* Any error messages shown

---

## License

MIT
