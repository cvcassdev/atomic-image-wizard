#!/usr/bin/env python3
"""
Atomic Image Wizard
A step-by-step GTK4 wizard for creating custom Fedora Atomic / bootc images.
"""
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Pango
import subprocess
import threading
import sys
import os
import re


# =============================================================================
#  Constants / data
# =============================================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

RPM_FUSION_FREE_URL    = "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-{ver}.noarch.rpm"
RPM_FUSION_NONFREE_URL = "https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-{ver}.noarch.rpm"

REPO_DEFINITIONS = {
    "RPM Fusion Free": {
        "description": "Open-source packages not in Fedora (ffmpeg, VLC codecs, etc.)",
        "run": f"dnf install -y {RPM_FUSION_FREE_URL} && dnf clean all",
    },
    "RPM Fusion Non-Free": {
        "description": "Proprietary packages — NVIDIA drivers, Steam, etc.",
        "run": f"dnf install -y {RPM_FUSION_NONFREE_URL} && dnf clean all",
        "requires": "RPM Fusion Free",
    },
}

PRESET_REPOS = [
    ("Tailscale",
     "curl -fsSL https://pkgs.tailscale.com/stable/fedora/tailscale.repo "
     "-o /etc/yum.repos.d/tailscale.repo"),
    ("VS Code",
     "rpm --import https://packages.microsoft.com/keys/microsoft.asc && "
     "curl -fsSL https://packages.microsoft.com/yumrepos/vscode/config.repo "
     "-o /etc/yum.repos.d/vscode.repo"),
    ("Google Chrome",
     "curl -fsSL https://dl.google.com/linux/chrome/rpm/stable/x86_64/google-chrome.repo "
     "-o /etc/yum.repos.d/google-chrome.repo"),
    ("1Password",
     "rpm --import https://downloads.1password.com/linux/keys/1password.asc && "
     "curl -fsSL https://downloads.1password.com/linux/rpm/stable/x86_64/1password.repo "
     "-o /etc/yum.repos.d/1password.repo"),
    ("Docker CE",
     "curl -fsSL https://download.docker.com/linux/fedora/docker-ce.repo "
     "-o /etc/yum.repos.d/docker-ce.repo"),
    ("Brave Browser",
     "curl -fsSL https://brave-browser-rpm-release.s3.brave.com/brave-browser.repo "
     "-o /etc/yum.repos.d/brave-browser.repo"),
]

# ── Fedora version constants — update these when a new release ships ──────────
FEDORA_STABLE  = 43   # current stable release
FEDORA_NEXT    = 44   # beta / branched — increment alongside stable
# Rawhide is always "rawhide", no number needed

# Official Fedora Atomic Desktop images — all at quay.io/fedora-ostree-desktops
# Update this list if Fedora adds or renames a desktop variant
_ATOMIC_DESKTOPS = [
    "silverblue",
    "kinoite",
    "sway-atomic",
    "budgie-atomic",
    "cosmic-atomic",
]

def _build_base_presets() -> list[str]:
    base = "quay.io/fedora-ostree-desktops"
    bootc = "quay.io/fedora/fedora-bootc"
    presets = []
    for tag, label in (
        (FEDORA_STABLE, f"Fedora {FEDORA_STABLE} — stable"),
        (FEDORA_NEXT,   f"Fedora {FEDORA_NEXT} — beta"),
        ("rawhide",     "Rawhide — bleeding edge"),
    ):
        for desktop in _ATOMIC_DESKTOPS:
            presets.append(f"{base}/{desktop}:{tag}")
        presets.append(f"{bootc}:{tag}")
    presets.append(f"{bootc}:latest")
    return presets

BASE_PRESETS = _build_base_presets()

# (label, [packages], requires_rpmfusion_free, requires_rpmfusion_nonfree)
# ── RPM Fusion: media codecs & hardware acceleration ─────────────────────────
# All entries here are pure userspace — they work correctly inside a container
# and take effect on next boot without any kernel module build step.
PACKAGE_PRESETS = [
    ("Multimedia codecs [RF]",
     ["gstreamer1-plugins-base", "gstreamer1-plugins-good",
      "gstreamer1-plugins-bad-free", "gstreamer1-plugins-ugly",
      "gstreamer1-plugin-openh264", "gstreamer1-plugins-bad-freeworld",
      "ffmpeg"], True, True),
    ("FFmpeg [RF]",             ["ffmpeg"], True, True),
    ("libavcodec [RF]",         ["libavcodec-freeworld"], True, True),
    ("VLC [RF]",                ["vlc"], True, True),
    ("DVD playback [RF]",       ["libdvdcss"], True, True),
    # Intel VA-API driver + libva-utils (vainfo) to verify hardware decode works
    ("Intel VA-API driver [RF]", ["intel-media-driver", "libva-utils"], True, False),
    # AMD VA-API driver (Mesa) + libva-utils — Mesa ships in Fedora but
    # libva-utils needs RF Free for the test tool
    ("AMD VA-API utils [RF]",   ["libva-utils"], True, False),
    # ROCm OpenCL — userspace compute, no kernel module required
    ("AMD ROCm OpenCL [RF]",    ["rocm-opencl"], False, True),
    ("Steam [RF-NF]",           ["steam"], True, True),
    # ── CLI tools ─────────────────────────────────────────────────────────────
    # Spartan by design — many tools (podman-compose, etc.) ship in the base image
    ("htop + btop",             ["htop", "btop"], False, False),
    ("zsh",                     ["zsh"], False, False),
    ("fish shell",              ["fish"], False, False),
    ("Distrobox",               ["distrobox"], False, False),
    ("fastfetch",               ["fastfetch"], False, False),
    ("tmux",                    ["tmux"], False, False),
    ("vim",                     ["vim"], False, False),
    ("neovim",                  ["neovim"], False, False),
    ("bat",                     ["bat"], False, False),
    ("eza",                     ["eza"], False, False),
    ("ripgrep",                 ["ripgrep"], False, False),
    ("fd-find",                 ["fd-find"], False, False),
    ("jq",                      ["jq"], False, False),
    ("just",                    ["just"], False, False),
]


# =============================================================================
#  Shared UI helpers
# =============================================================================
def make_header(title: str, subtitle: str) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.set_margin_bottom(16)
    t = Gtk.Label(use_markup=True)
    t.set_markup(f"<b><big>{GLib.markup_escape_text(title)}</big></b>")
    t.set_xalign(0)
    box.append(t)
    s = Gtk.Label(label=subtitle)
    s.set_xalign(0)
    s.add_css_class("dim-label")
    s.set_wrap(True)
    box.append(s)
    sep = Gtk.Separator()
    sep.set_margin_top(8)
    box.append(sep)
    return box


def set_margins(widget, top=0, bottom=0, start=0, end=0):
    """Convenience wrapper — avoids repeating four set_margin_* calls everywhere."""
    widget.set_margin_top(top)
    widget.set_margin_bottom(bottom)
    widget.set_margin_start(start)
    widget.set_margin_end(end)


def clear_listbox(lb: Gtk.ListBox):
    while True:
        row = lb.get_row_at_index(0)
        if row is None:
            break
        lb.remove(row)


def clear_flowbox(fb: Gtk.FlowBox):
    while True:
        child = fb.get_child_at_index(0)
        if child is None:
            break
        fb.remove(child)


def show_error(parent, text: str):
    d = Gtk.MessageDialog(transient_for=parent, modal=True,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.OK, text=text)
    d.connect("response", lambda d, _: d.close())
    d.present()


# =============================================================================
#  Containerfile parser  (extracted from PageBase for clarity and testability)
# =============================================================================
class ContainerfileParser:
    """
    Parses an existing Containerfile into WizardState fields.

    Limitations are surfaced via self.warnings so the UI can show them
    rather than silently dropping unrecognised constructs.
    """

    PERF_PKG_FLAGS = {
        "cachyos-settings":     "perf_cachyos_settings",
        "cachyos-ksm-settings": "perf_ksm_settings",
        "scx-scheds":           "perf_scx_scheds",
        "scx-tools":            "perf_scx_scheds",
    }
    PERF_COPR = "bieszczaders/kernel-cachyos-addons"

    SKIP_TOKENS = {"dnf", "install", "remove", "-y", "clean", "all", "&&", "\\",
                   "--allowerasing", "repoquery", "config-manager", "--add-repo"}

    def __init__(self, path: str):
        self.path     = path
        self.warnings = []   # list of human-readable strings shown to the user

    # ── public ────────────────────────────────────────────────────────────────

    def parse_from(self) -> str:
        """Return the FROM value, or '' if not found."""
        try:
            with open(self.path) as f:
                for line in f:
                    line = line.strip()
                    if line.upper().startswith("FROM "):
                        return line[5:].strip()
        except Exception as e:
            self.warnings.append(f"Could not read Containerfile: {e}")
        return ""

    def apply_to_state(self, state) -> None:
        """
        Parse the full Containerfile and populate *state* in-place.
        Unrecognised RUN commands are noted in self.warnings instead of
        being silently dropped.
        """
        try:
            with open(self.path) as f:
                text = f.read()
        except Exception as e:
            self.warnings.append(f"Could not read Containerfile: {e}")
            return

        self._validate(text)

        # Flatten backslash-newline continuations so each logical RUN is one line
        flat = text.replace("\\\n", " ")

        # RPM Fusion — detected by URL fragment
        if "rpmfusion-free" in flat:
            state.repos.add("RPM Fusion Free")
        if "rpmfusion-nonfree" in flat:
            state.repos.add("RPM Fusion Non-Free")

        for m in re.finditer(r"^RUN (.+)$", flat, re.MULTILINE):
            self._process_run(m.group(1).strip(), state)

    # ── private ───────────────────────────────────────────────────────────────

    def _validate(self, text: str):
        """Basic sanity checks — populate self.warnings with any issues found."""
        stripped = text.strip()
        if not stripped:
            self.warnings.append("Containerfile is empty.")
            return
        has_from = any(
            line.strip().upper().startswith("FROM ")
            for line in stripped.splitlines()
        )
        if not has_from:
            self.warnings.append("Containerfile has no FROM instruction.")

    def _is_pkg_token(self, t: str) -> bool:
        return (
            bool(t)
            and t not in self.SKIP_TOKENS
            and not t.startswith("-")
            and "://" not in t
            and ".rpm" not in t
            and "/" not in t
            and "%" not in t
            and not t.endswith(")")
            and not t.startswith("'")
        )

    def _process_run(self, run_body: str, state) -> None:
        cmds = [c.strip() for c in run_body.split("&&")]
        recognised = False
        for cmd in cmds:
            cmd = cmd.strip()
            if not cmd or cmd in ("dnf clean all",):
                recognised = True
                continue
            recognised |= self._dispatch_cmd(cmd, state)

        if not recognised:
            self.warnings.append(
                f"Unrecognised RUN command (skipped):\n  {run_body[:120]}"
            )

    def _dispatch_cmd(self, cmd: str, state) -> bool:
        """Return True if the command was recognised and handled."""

        # dnf install
        if re.match(r"dnf install -y\b", cmd):
            if "rpmfusion" in cmd:
                return True   # already handled via URL fragment scan
            for token in cmd.split():
                if not self._is_pkg_token(token):
                    continue
                if token in self.PERF_PKG_FLAGS:
                    flag = self.PERF_PKG_FLAGS[token]
                    setattr(state, flag, True)
                    if flag == "perf_scx_scheds" and "scx_loader.service" not in state.systemd_enable:
                        state.systemd_enable.append("scx_loader.service")
                elif token not in state.install_pkgs:
                    state.install_pkgs.append(token)
            return True

        # dnf remove
        if re.match(r"dnf remove -y\b", cmd):
            for token in cmd.split():
                if self._is_pkg_token(token) and token not in state.remove_pkgs:
                    state.remove_pkgs.append(token)
            return True

        # dnf copr enable
        if re.match(r"dnf copr enable\b", cmd):
            repo = cmd.split()[-1]
            if repo == self.PERF_COPR:
                return True   # managed by performance section
            if repo not in state.copr_repos:
                state.copr_repos.append(repo)
            return True

        # dnf-command(copr) install — auto-added by generator, skip
        if "dnf-command(copr)" in cmd:
            return True

        # systemctl enable / disable
        if re.match(r"systemctl enable\b", cmd):
            svc = cmd.split()[-1]
            if svc not in state.systemd_enable:
                state.systemd_enable.append(svc)
            return True
        if re.match(r"systemctl disable\b", cmd):
            svc = cmd.split()[-1]
            if svc not in state.systemd_disable:
                state.systemd_disable.append(svc)
            return True

        # Custom repo setup commands
        if (cmd.startswith("curl") or
                cmd.startswith("rpm --import") or
                cmd.startswith("rpm -i") or
                cmd.startswith("dnf config-manager")):
            if cmd not in state.custom_repos:
                state.custom_repos.append(cmd)
            return True

        # mkdir / printf / rm — generated housekeeping, not user data
        if cmd.startswith(("mkdir", "printf", "rm ")):
            return True

        return False


# =============================================================================
#  Wizard state
# =============================================================================
class WizardState:
    def __init__(self):
        self.base_image      = BASE_PRESETS[0]
        self.repos           = set()
        self.custom_repos    = []
        self.copr_repos      = []
        self.install_pkgs    = []
        self.remove_pkgs     = []
        self.systemd_enable  = []
        self.systemd_disable = []
        self.image_tag       = "localhost/atomic-custom:latest"
        self.perf_cachyos_settings = False
        self.perf_ksm_settings     = False
        self.perf_scx_scheds       = False

    def _fedora_ver(self) -> str:
        m = re.search(r":(\d+)$", self.base_image)
        return m.group(1) if m else "43"

    def generate_containerfile(self) -> str:
        DIVIDER = "# " + "\u2500" * 62

        def section(n, title):
            return [DIVIDER, f"# {n}. {title}", DIVIDER]

        ver = self._fedora_ver()
        out = [f"FROM {self.base_image}"]

        PERF_PKGS = {"cachyos-settings", "cachyos-ksm-settings", "scx-scheds", "scx-tools"}
        SCX_SVCS  = {"scx", "scx.service", "scx_loader", "scx_loader.service"}

        # ── Section 1: Repositories ───────────────────────────────────────
        repo_parts = []
        copr_repos = [r for r in self.copr_repos if r != "bieszczaders/kernel-cachyos-addons"]

        if copr_repos:
            repo_parts.append("dnf install -y 'dnf-command(copr)'")
            for repo in copr_repos:
                repo_parts.append(f"dnf copr enable -y {repo}")

        for cmd in self.custom_repos:
            repo_parts.append(cmd)

        if "RPM Fusion Free" in self.repos or "RPM Fusion Non-Free" in self.repos:
            rpms = []
            if "RPM Fusion Free" in self.repos:
                rpms.append(RPM_FUSION_FREE_URL.format(ver=ver))
            if "RPM Fusion Non-Free" in self.repos:
                rpms.append(RPM_FUSION_NONFREE_URL.format(ver=ver))
            rpm_lines = " \\\n        ".join(rpms)
            repo_parts.append("dnf install -y \\\n        " + rpm_lines)

        if repo_parts:
            repo_parts.append("dnf clean all")
            out.append("")
            out += section(1, "Add external repositories")
            out.append("RUN " + " \\\n    && ".join(repo_parts))

        # ── Section 2: Remove + Install ───────────────────────────────────
        install_list = [
            p for p in self.install_pkgs
            if "dnf-command" not in p and p not in PERF_PKGS
        ]
        has_remove  = bool(self.remove_pkgs)
        has_install = bool(install_list)

        if has_remove or has_install:
            out.append("")
            if has_remove and has_install:
                out += section(2, "Remove unwanted defaults + install desired packages in one layer")
            elif has_remove:
                out += section(2, "Remove unwanted defaults")
            else:
                out += section(2, "Install desired packages")

            run_parts = []
            if has_remove:
                pkgs = " \\\n        ".join(sorted(self.remove_pkgs))
                run_parts.append("dnf remove -y \\\n        " + pkgs)
            if has_install:
                pkgs = " \\\n        ".join(sorted(install_list))
                run_parts.append("dnf install -y \\\n        " + pkgs)
            run_parts.append("dnf clean all")
            out.append("RUN " + " \\\n    && ".join(run_parts))

        # ── Section 3: Performance tweaks ─────────────────────────────────
        perf_pkgs = []
        if self.perf_cachyos_settings:
            perf_pkgs.append("cachyos-settings")
        if self.perf_ksm_settings:
            perf_pkgs.append("cachyos-ksm-settings")
        if self.perf_scx_scheds:
            perf_pkgs.extend(["scx-scheds", "scx-tools"])

        if perf_pkgs:
            out.append("")
            out += section(3, "Performance tweaks (CachyOS addons \u2014 requires kernel 6.12+)")
            perf_parts = [
                "dnf install -y 'dnf-command(copr)'",
                "dnf copr enable -y bieszczaders/kernel-cachyos-addons",
                "dnf install -y --allowerasing " + " \\\n        ".join(perf_pkgs),
                "dnf clean all",
            ]
            if self.perf_scx_scheds:
                cfg = 'default_sched = "scx_bpfland"\\ndefault_mode = "Auto"\\n'
                perf_parts.append(
                    "mkdir -p /etc/scx_loader"
                    " && printf '" + cfg + "' > /etc/scx_loader/config.toml"
                )
            out.append("RUN " + " \\\n    && ".join(perf_parts))

        # ── Section 4: Enable / disable services ──────────────────────────
        enable  = [s for s in self.systemd_enable if s not in SCX_SVCS]
        disable = list(self.systemd_disable)
        if self.perf_scx_scheds:
            enable.append("scx_loader.service")

        cleanup = []
        if not self.perf_scx_scheds:
            cleanup.append("rm -rf /etc/scx_loader")

        if enable or disable or cleanup:
            out.append("")
            out += section(4, "Enable / disable services")
            parts  = [f"systemctl enable {s}" for s in enable]
            parts += [f"systemctl disable {s}" for s in disable]
            parts += cleanup
            out.append("RUN " + " \\\n    && ".join(parts))

        out.append("")
        return "\n".join(out)

    def validate_for_build(self) -> list[str]:
        """
        Return a list of human-readable problems that should block a build.
        An empty list means the state is safe to build.
        """
        issues = []
        if not self.base_image.strip():
            issues.append("No base image specified (Step 1).")
        if not self.image_tag.strip():
            issues.append("No image tag specified (Review page).")
        if self.perf_scx_scheds and "scx_loader.service" not in self.systemd_enable:
            issues.append(
                "SCX scheduler is enabled but scx_loader.service is not in the enable list."
            )
        return issues


# =============================================================================
#  PAGE 0 - Landing  (only shown when an existing Containerfile is found)
# =============================================================================
class PageLanding(Gtk.Box):
    def __init__(self, state: WizardState, cf_path: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.state   = state
        self.cf_path = cf_path
        set_margins(self, top=0, bottom=0, start=0, end=0)

        # Parse immediately so we can show the detected base image
        parser     = ContainerfileParser(cf_path)
        self._base = parser.parse_from()

        # ── Vertically centred content ────────────────────────────────────
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.set_vexpand(True)
        outer.set_hexpand(True)

        top_spacer = Gtk.Box()
        top_spacer.set_vexpand(True)
        outer.append(top_spacer)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=28)
        inner.set_halign(Gtk.Align.CENTER)
        inner.set_valign(Gtk.Align.CENTER)
        set_margins(inner, top=40, bottom=40, start=60, end=60)

        title = Gtk.Label()
        title.set_markup("<b><big>Atomic Image Wizard</big></b>")
        title.set_halign(Gtk.Align.CENTER)
        inner.append(title)

        found_lbl = Gtk.Label()
        found_lbl.set_markup(
            "An existing build was found.\n"
            f"Base image:  <tt>{GLib.markup_escape_text(self._base or '(unknown)')}</tt>"
        )
        found_lbl.set_halign(Gtk.Align.CENTER)
        found_lbl.add_css_class("dim-label")
        found_lbl.set_wrap(True)
        inner.append(found_lbl)

        # ── Option buttons ────────────────────────────────────────────────
        btn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        btn_box.set_halign(Gtk.Align.CENTER)

        def make_option(title_text, subtitle_text):
            frame = Gtk.Frame()
            frame.set_size_request(460, -1)
            frame.add_css_class("card")
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            set_margins(vbox, top=14, bottom=14, start=20, end=20)
            t = Gtk.Label()
            t.set_markup(f"<b>{GLib.markup_escape_text(title_text)}</b>")
            t.set_xalign(0)
            s = Gtk.Label(label=subtitle_text)
            s.set_xalign(0)
            s.add_css_class("dim-label")
            s.set_wrap(True)
            vbox.append(t)
            vbox.append(s)
            btn = Gtk.Button()
            btn.set_child(frame)
            btn.set_has_frame(False)
            frame.set_child(vbox)
            return btn

        upgrade_btn = make_option(
            "Upgrade / Rebuild",
            "Rebuild the existing image as-is and go to Review before deploying."
        )
        upgrade_btn.add_css_class("suggested-action")
        upgrade_btn.connect("clicked", self._do_upgrade)
        btn_box.append(upgrade_btn)

        add_btn = make_option(
            "Add Software",
            "Load the existing build and jump to Repositories to add or change software."
        )
        add_btn.connect("clicked", self._do_add_software)
        btn_box.append(add_btn)

        new_btn = make_option(
            "New Build",
            "Start completely fresh with a new base image and clean settings."
        )
        new_btn.add_css_class("destructive-action")
        new_btn.connect("clicked", self._do_new_build)
        btn_box.append(new_btn)

        inner.append(btn_box)
        outer.append(inner)

        bot_spacer = Gtk.Box()
        bot_spacer.set_vexpand(True)
        outer.append(bot_spacer)

        self.append(outer)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _load_containerfile(self):
        """Parse the Containerfile into state, show warnings if any."""
        self.state.install_pkgs.clear()
        self.state.remove_pkgs.clear()
        self.state.systemd_enable.clear()
        self.state.systemd_disable.clear()
        self.state.custom_repos.clear()
        self.state.copr_repos.clear()
        self.state.repos.clear()
        self.state.perf_cachyos_settings = False
        self.state.perf_ksm_settings     = False
        self.state.perf_scx_scheds       = False

        parser = ContainerfileParser(self.cf_path)
        base   = parser.parse_from()
        parser.apply_to_state(self.state)

        if base:
            self.state.base_image = base

        if parser.warnings:
            win = self.get_root()
            warn_text = "\n".join(f"• {w}" for w in parser.warnings)
            d = Gtk.MessageDialog(transient_for=win, modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Containerfile loaded with warnings",
                secondary_text=warn_text)
            d.connect("response", lambda d, _: d.close())
            d.present()

    # ── Button handlers ───────────────────────────────────────────────────

    def _do_upgrade(self, *_):
        self._load_containerfile()
        win = self.get_root()
        if hasattr(win, "jump_to_page"):
            win.jump_to_page(win.REVIEW_IDX)

    def _do_add_software(self, *_):
        self._load_containerfile()
        win = self.get_root()
        if hasattr(win, "jump_to_page"):
            win.jump_to_page(win.REPOS_IDX)

    def _do_new_build(self, *_):
        # Clear state and go to base image selector
        self.state.__init__()
        win = self.get_root()
        if hasattr(win, "jump_to_page"):
            win.jump_to_page(win.BASE_IDX)


# =============================================================================
#  PAGE 1 - Base Image
# =============================================================================
class PageBase(Gtk.Box):
    def __init__(self, state: WizardState):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.state = state
        set_margins(self, top=12, bottom=12, start=16, end=16)

        self.append(make_header(
            "Step 1 — Choose Base Image",
            "Select the starting point for your custom image."
        ))

        self.dropdown = Gtk.DropDown.new_from_strings(BASE_PRESETS)
        self.dropdown.set_selected(0)
        self.dropdown.connect("notify::selected-item", self._on_dropdown)
        self.append(self.dropdown)

        sep_lbl = Gtk.Label(label="— or enter a custom image —")
        sep_lbl.add_css_class("dim-label")
        self.append(sep_lbl)

        self.entry = Gtk.Entry(placeholder_text="registry.example.com/image:tag")
        self.entry.set_text(state.base_image)
        self.entry.connect("changed", self._on_entry)
        self.append(self.entry)

        search_btn = Gtk.Button(label="Search registry with podman search")
        search_btn.connect("clicked", self._do_registry_search)
        self.append(search_btn)

        frame = Gtk.Frame(label=" Preview ")
        frame.set_margin_top(12)
        self.preview = Gtk.Label(label="")
        self.preview.add_css_class("monospace")
        self.preview.set_xalign(0)
        set_margins(self.preview, top=10, bottom=10, start=10, end=10)
        frame.set_child(self.preview)
        self.append(frame)
        self._refresh_preview()

        # ── rpm-ostree status banner (hidden until populated) ─────────────
        self.ostree_banner = Gtk.Frame()
        banner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        set_margins(banner_box, top=8, bottom=8, start=10, end=10)
        self.banner_lbl = Gtk.Label()
        self.banner_lbl.set_xalign(0)
        self.banner_lbl.set_wrap(True)
        banner_box.append(self.banner_lbl)

        # Confirm button — user must explicitly accept the detected state
        self.banner_accept_btn = Gtk.Button(label="Accept detected settings")
        self.banner_accept_btn.add_css_class("suggested-action")
        self.banner_accept_btn.set_halign(Gtk.Align.START)
        self.banner_accept_btn.connect("clicked", self._accept_ostree_detection)
        banner_box.append(self.banner_accept_btn)

        self.ostree_banner.set_child(banner_box)
        self.ostree_banner.set_visible(False)
        self.append(self.ostree_banner)

        # Pending detection results — held until the user clicks Accept
        self._pending_repos    = []
        self._pending_custom   = []
        self._pending_pkgs     = []

    # ── Dropdown / entry ──────────────────────────────────────────────────

    def _on_dropdown(self, dd, _):
        item = dd.get_selected_item()
        if item:
            self.entry.set_text(item.get_string())

    def _on_entry(self, entry):
        self.state.base_image = entry.get_text().strip()
        self._refresh_preview()

    def _refresh_preview(self):
        self.preview.set_text(f"FROM {self.state.base_image}")

    # ── Registry search ───────────────────────────────────────────────────

    def _do_registry_search(self, *_):
        win = self.get_root()
        dlg = Gtk.Window(title="Searching...", modal=True, transient_for=win)
        dlg.set_default_size(280, 80)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        set_margins(box, top=20, bottom=20, start=20, end=20)
        sp = Gtk.Spinner()
        sp.start()
        box.append(sp)
        box.append(Gtk.Label(label="Running podman search..."))
        dlg.set_child(box)
        dlg.present()

        def worker():
            try:
                out = subprocess.check_output(
                    ["podman", "search", "--limit", "40", "--format",
                     "{{.Name}} : {{.Description}}", "fedora-ostree"],
                    text=True, stderr=subprocess.DEVNULL
                )
                results = [l.strip() for l in out.splitlines() if l.strip() and ":" in l]
            except FileNotFoundError:
                GLib.idle_add(lambda: (dlg.close(),
                    show_error(self.get_root(), "podman is not installed or not in PATH.")))
                return
            except Exception as e:
                GLib.idle_add(lambda: (dlg.close(),
                    show_error(self.get_root(), f"podman search failed:\n{e}")))
                return
            GLib.idle_add(lambda: self._show_search_results(dlg, results))

        threading.Thread(target=worker, daemon=True).start()

    def _show_search_results(self, loading_dlg, results):
        loading_dlg.close()
        win = self.get_root()
        rwin = Gtk.Window(title="Registry Search Results", modal=True, transient_for=win)
        rwin.set_default_size(900, 520)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        set_margins(vbox, top=10, bottom=10, start=10, end=10)
        rwin.set_child(vbox)

        if not results:
            vbox.append(Gtk.Label(label="No results returned by podman search."))
            close_btn = Gtk.Button(label="Close")
            close_btn.connect("clicked", lambda _: rwin.close())
            vbox.append(close_btn)
            rwin.present()
            return

        hint = Gtk.Label(label="Click a row to select it, then press Use Selected Image.")
        hint.set_xalign(0)
        vbox.append(hint)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        listbox.add_css_class("boxed-list")
        scroll.set_child(listbox)
        vbox.append(scroll)

        parsed = []
        for r in results:
            parts = r.split(" : ", 1)
            name = parts[0].strip()
            desc = parts[1].strip() if len(parts) > 1 else ""
            parsed.append(name)

            row_box = Gtk.Box(spacing=12)
            set_margins(row_box, top=6, bottom=6, start=8, end=8)
            name_lbl = Gtk.Label()
            name_lbl.set_markup(f"<b>{GLib.markup_escape_text(name)}</b>")
            name_lbl.set_xalign(0)
            name_lbl.set_width_chars(44)
            name_lbl.set_max_width_chars(44)
            name_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            desc_lbl = Gtk.Label(label=desc)
            desc_lbl.set_xalign(0)
            desc_lbl.set_hexpand(True)
            desc_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            desc_lbl.add_css_class("dim-label")
            row_box.append(name_lbl)
            row_box.append(desc_lbl)
            listbox.append(row_box)

        btn_box = Gtk.Box(spacing=8)
        btn_box.set_halign(Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda _: rwin.close())
        use_btn = Gtk.Button(label="Use Selected Image")
        use_btn.add_css_class("suggested-action")
        btn_box.append(cancel_btn)
        btn_box.append(use_btn)
        vbox.append(btn_box)

        def use_selected(*_):
            row = listbox.get_selected_row()
            if row:
                idx = row.get_index()
                if 0 <= idx < len(parsed):
                    self.entry.set_text(parsed[idx])
                    rwin.close()

        use_btn.connect("clicked", use_selected)
        listbox.connect("row-activated", lambda lb, row: use_selected())
        rwin.present()

    # ── rpm-ostree detection ──────────────────────────────────────────────

    def on_enter(self):
        self.entry.set_text(self.state.base_image)
        self._refresh_preview()
        if not self.state.base_image or self.state.base_image == BASE_PRESETS[0]:
            threading.Thread(target=self._detect_ostree_async, daemon=True).start()

    def _detect_ostree_async(self):
        try:
            out = subprocess.check_output(
                ["rpm-ostree", "status", "--booted"],
                text=True, stderr=subprocess.DEVNULL, timeout=10
            )
        except Exception:
            return

        booted_image = ""
        layered_pkgs = []

        for line in out.splitlines():
            line = line.strip()
            m = re.match(r"(?:Image|BaseCommit|ostreespec):\s*(\S+)", line, re.IGNORECASE)
            if not m:
                m = re.match(r"(?:●\s+)?(\S+://\S+|\S+/\S+:\S+)", line)
            if m and not booted_image:
                candidate = m.group(1).rstrip(")")
                if "/" in candidate and ":" in candidate:
                    booted_image = candidate
            if re.match(r"LayeredPackages:", line, re.IGNORECASE):
                pkgs = line.split(":", 1)[1].strip()
                layered_pkgs = [p.strip() for p in pkgs.split() if p.strip()]

        GLib.idle_add(self._apply_ostree_result, booted_image, layered_pkgs)

    def _apply_ostree_result(self, booted_image: str, layered_pkgs: list):
        if booted_image:
            for i, preset in enumerate(BASE_PRESETS):
                if preset == booted_image:
                    self.dropdown.set_selected(i)
                    break
            self.state.base_image = booted_image
            self.entry.set_text(booted_image)
            self._refresh_preview()

        if not layered_pkgs:
            return

        REPO_PKG_MAP = {
            "rpmfusion-free-release":    "RPM Fusion Free",
            "rpmfusion-nonfree-release": "RPM Fusion Non-Free",
        }
        CUSTOM_REPO_MAP = {
            "tailscale":     "curl -fsSL https://pkgs.tailscale.com/stable/fedora/tailscale.repo -o /etc/yum.repos.d/tailscale.repo",
            "code":          "rpm --import https://packages.microsoft.com/keys/microsoft.asc && curl -fsSL https://packages.microsoft.com/yumrepos/vscode/config.repo -o /etc/yum.repos.d/vscode.repo",
            "google-chrome": "curl -fsSL https://dl.google.com/linux/chrome/rpm/stable/x86_64/google-chrome.repo -o /etc/yum.repos.d/google-chrome.repo",
            "1password":     "rpm --import https://downloads.1password.com/linux/keys/1password.asc && curl -fsSL https://downloads.1password.com/linux/rpm/stable/x86_64/1password.repo -o /etc/yum.repos.d/1password.repo",
            "docker-ce":     "curl -fsSL https://download.docker.com/linux/fedora/docker-ce.repo -o /etc/yum.repos.d/docker-ce.repo",
            "brave-browser": "curl -fsSL https://brave-browser-rpm-release.s3.brave.com/brave-browser.repo -o /etc/yum.repos.d/brave-browser.repo",
        }

        # Stage pending changes — don't modify state until user confirms
        self._pending_repos   = []
        self._pending_custom  = []
        self._pending_pkgs    = []

        for pkg in layered_pkgs:
            pkg_lower = pkg.lower()
            if pkg in REPO_PKG_MAP:
                repo_name = REPO_PKG_MAP[pkg]
                if repo_name not in self.state.repos:
                    self._pending_repos.append(repo_name)
            else:
                matched_repo = False
                for frag, cmd in CUSTOM_REPO_MAP.items():
                    if frag in pkg_lower:
                        if cmd not in self.state.custom_repos:
                            self._pending_custom.append((frag, cmd))
                        matched_repo = True
                        break
                if pkg not in self.state.install_pkgs:
                    self._pending_pkgs.append(pkg)

        if not (self._pending_repos or self._pending_custom or self._pending_pkgs):
            return

        parts = []
        if self._pending_pkgs:
            parts.append("Packages to add to Step 3 install list:\n  " +
                         "  ".join(self._pending_pkgs))
        if self._pending_repos:
            parts.append("Repos to enable in Step 2:\n  " +
                         "  ".join(self._pending_repos))
        if self._pending_custom:
            parts.append("Custom repos to add to Step 2:\n  " +
                         "  ".join(f[0] for f in self._pending_custom))

        msg = (
            "<b>rpm-ostree layered packages detected</b>\n"
            "Your current system has layered packages. Review the changes below and\n"
            "click <b>Accept</b> to migrate them into the wizard, or ignore to skip.\n\n"
            "<tt>" + GLib.markup_escape_text("\n".join(parts)) + "</tt>"
        )
        self.banner_lbl.set_markup(msg)
        self.banner_accept_btn.set_visible(True)
        self.ostree_banner.set_visible(True)

    def _accept_ostree_detection(self, *_):
        """Apply pending rpm-ostree detection results to state after user confirms."""
        for repo_name in self._pending_repos:
            self.state.repos.add(repo_name)
        for _frag, cmd in self._pending_custom:
            self.state.custom_repos.append(cmd)
        for pkg in self._pending_pkgs:
            self.state.install_pkgs.append(pkg)

        self._pending_repos   = []
        self._pending_custom  = []
        self._pending_pkgs    = []

        self.banner_accept_btn.set_visible(False)
        self.banner_lbl.set_markup(
            "<b>Settings accepted.</b> Continue through the wizard to review."
        )


# =============================================================================
#  PAGE 2 - Repos
# =============================================================================
class PageRepos(Gtk.Box):
    def __init__(self, state: WizardState):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.state = state
        set_margins(self, top=12, bottom=12, start=16, end=16)

        self.append(make_header(
            "Step 2 — Additional Repositories",
            "Enable extra repos before installing packages."
        ))

        self.checks = {}
        for repo_name, defn in REPO_DEFINITIONS.items():
            row = Gtk.Box(spacing=12)
            row.set_margin_top(4)
            check = Gtk.CheckButton(label=repo_name)
            check.set_active(repo_name in state.repos)
            check.connect("toggled", self._on_rpmfusion_toggled, repo_name)
            desc = Gtk.Label(label=defn["description"])
            desc.add_css_class("dim-label")
            desc.set_xalign(0)
            row.append(check)
            row.append(desc)
            self.append(row)
            self.checks[repo_name] = check

        note = Gtk.Label(
            label="RPM Fusion Non-Free requires Free. Enabling Non-Free will auto-enable Free."
        )
        note.set_wrap(True)
        note.set_xalign(0)
        note.set_margin_top(4)
        note.add_css_class("dim-label")
        self.append(note)

        # ── Copr repositories ─────────────────────────────────────────────
        sep0 = Gtk.Separator()
        set_margins(sep0, top=16, bottom=8)
        self.append(sep0)

        copr_title = Gtk.Label(use_markup=True)
        copr_title.set_markup("<b>Copr Repositories</b>")
        copr_title.set_xalign(0)
        self.append(copr_title)

        copr_sub = Gtk.Label(label="Enter repos as  user/repo  (e.g. lilay/topgrade)")
        copr_sub.set_xalign(0)
        copr_sub.add_css_class("dim-label")
        self.append(copr_sub)

        copr_entry_box = Gtk.Box(spacing=8)
        copr_entry_box.set_margin_top(6)
        self.copr_entry = Gtk.Entry(placeholder_text="user/repo")
        self.copr_entry.set_hexpand(True)
        self.copr_entry.connect("activate", self._add_copr_repo)
        copr_add_btn = Gtk.Button(label="Add Copr")
        copr_add_btn.add_css_class("suggested-action")
        copr_add_btn.connect("clicked", self._add_copr_repo)
        copr_entry_box.append(self.copr_entry)
        copr_entry_box.append(copr_add_btn)
        self.append(copr_entry_box)

        copr_frame = Gtk.Frame(label=" Added Copr repos ")
        copr_frame.set_margin_top(4)
        copr_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        set_margins(copr_inner, top=4, bottom=4, start=4, end=4)
        copr_scroll = Gtk.ScrolledWindow()
        copr_scroll.set_size_request(-1, 80)
        self.copr_listbox = Gtk.ListBox()
        self.copr_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.copr_listbox.add_css_class("boxed-list")
        copr_scroll.set_child(self.copr_listbox)
        copr_remove_btn = Gtk.Button(label="Remove selected")
        copr_remove_btn.connect("clicked", self._remove_copr_repo)
        copr_inner.append(copr_scroll)
        copr_inner.append(copr_remove_btn)
        copr_frame.set_child(copr_inner)
        self.append(copr_frame)

        sep = Gtk.Separator()
        set_margins(sep, top=16, bottom=8)
        self.append(sep)

        custom_title = Gtk.Label(use_markup=True)
        custom_title.set_markup("<b>Custom Repositories</b>")
        custom_title.set_xalign(0)
        self.append(custom_title)

        custom_sub = Gtk.Label(
            label="Add any repo setup command as a RUN layer — "
                  "curl install scripts, dnf config-manager, rpm --import, etc."
        )
        custom_sub.set_xalign(0)
        custom_sub.add_css_class("dim-label")
        custom_sub.set_wrap(True)
        self.append(custom_sub)

        presets_box = Gtk.FlowBox()
        presets_box.set_max_children_per_line(3)
        presets_box.set_selection_mode(Gtk.SelectionMode.NONE)
        set_margins(presets_box, top=8, bottom=4)
        for label, cmd in PRESET_REPOS:
            btn = Gtk.Button(label=f"+ {label}")
            btn.connect("clicked", self._add_preset_repo, cmd)
            presets_box.append(btn)
        self.append(presets_box)

        entry_box = Gtk.Box(spacing=8)
        entry_box.set_margin_top(4)
        self.custom_entry = Gtk.Entry(
            placeholder_text="e.g.  curl -fsSL https://example.com/install.sh | sh"
        )
        self.custom_entry.set_hexpand(True)
        self.custom_entry.connect("activate", self._add_custom_repo)
        add_btn = Gtk.Button(label="Add")
        add_btn.add_css_class("suggested-action")
        add_btn.connect("clicked", self._add_custom_repo)
        entry_box.append(self.custom_entry)
        entry_box.append(add_btn)
        self.append(entry_box)

        added_frame = Gtk.Frame(label=" Added custom repos — order matters (key import before repo file) ")
        added_frame.set_margin_top(6)
        added_frame.set_vexpand(True)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        set_margins(inner, top=4, bottom=4, start=4, end=4)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self.custom_listbox = Gtk.ListBox()
        self.custom_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.custom_listbox.add_css_class("boxed-list")
        scroll.set_child(self.custom_listbox)

        reorder_box = Gtk.Box(spacing=6)
        reorder_box.set_halign(Gtk.Align.END)
        up_btn = Gtk.Button(label="↑ Move up")
        up_btn.connect("clicked", self._move_custom_repo, -1)
        down_btn = Gtk.Button(label="↓ Move down")
        down_btn.connect("clicked", self._move_custom_repo, +1)
        remove_btn = Gtk.Button(label="Remove selected")
        remove_btn.add_css_class("destructive-action")
        remove_btn.connect("clicked", self._remove_custom_repo)
        reorder_box.append(up_btn)
        reorder_box.append(down_btn)
        reorder_box.append(remove_btn)

        inner.append(scroll)
        inner.append(reorder_box)
        added_frame.set_child(inner)
        self.append(added_frame)

    def _make_repo_row(self, cmd: str) -> Gtk.Label:
        lbl = Gtk.Label(label=cmd)
        lbl.set_xalign(0)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.add_css_class("monospace")
        set_margins(lbl, top=5, bottom=5, start=8, end=8)
        return lbl

    def _add_preset_repo(self, _btn, cmd: str):
        if cmd not in self.state.custom_repos:
            self.state.custom_repos.append(cmd)
            self.custom_listbox.append(self._make_repo_row(cmd))

    def _add_custom_repo(self, *_):
        cmd = self.custom_entry.get_text().strip()
        if cmd and cmd not in self.state.custom_repos:
            self.state.custom_repos.append(cmd)
            self.custom_listbox.append(self._make_repo_row(cmd))
            self.custom_entry.set_text("")

    def _remove_custom_repo(self, *_):
        row = self.custom_listbox.get_selected_row()
        if row:
            child = row.get_child()
            cmd = child.get_text() if child else None
            if cmd and cmd in self.state.custom_repos:
                self.state.custom_repos.remove(cmd)
            self.custom_listbox.remove(row)

    def _move_custom_repo(self, _btn, direction: int):
        """Move the selected custom repo up (-1) or down (+1) in the list."""
        row = self.custom_listbox.get_selected_row()
        if not row:
            return
        idx = row.get_index()
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self.state.custom_repos):
            return
        # Swap in state list
        lst = self.state.custom_repos
        lst[idx], lst[new_idx] = lst[new_idx], lst[idx]
        # Rebuild listbox to reflect new order, restore selection
        clear_listbox(self.custom_listbox)
        for cmd in lst:
            self.custom_listbox.append(self._make_repo_row(cmd))
        new_row = self.custom_listbox.get_row_at_index(new_idx)
        if new_row:
            self.custom_listbox.select_row(new_row)

    def _add_copr_repo(self, *_):
        repo = self.copr_entry.get_text().strip().strip("/")
        if not repo or "/" not in repo:
            return
        if repo not in self.state.copr_repos:
            self.state.copr_repos.append(repo)
            lbl = Gtk.Label(label=repo)
            lbl.set_xalign(0)
            set_margins(lbl, top=4, bottom=4, start=8)
            self.copr_listbox.append(lbl)
            self.copr_entry.set_text("")

    def _remove_copr_repo(self, *_):
        row = self.copr_listbox.get_selected_row()
        if row:
            child = row.get_child()
            repo = child.get_text() if child else None
            if repo and repo in self.state.copr_repos:
                self.state.copr_repos.remove(repo)
            self.copr_listbox.remove(row)

    def _on_rpmfusion_toggled(self, check, repo_name):
        if check.get_active():
            if repo_name == "RPM Fusion Non-Free" and "RPM Fusion Free" not in self.state.repos:
                self.state.repos.add("RPM Fusion Free")
                self.checks["RPM Fusion Free"].set_active(True)
            self.state.repos.add(repo_name)
        else:
            self.state.repos.discard(repo_name)
            if repo_name == "RPM Fusion Free" and "RPM Fusion Non-Free" in self.state.repos:
                self.state.repos.discard("RPM Fusion Non-Free")
                self.checks["RPM Fusion Non-Free"].set_active(False)

    def on_enter(self):
        for repo_name, check in self.checks.items():
            check.set_active(repo_name in self.state.repos)
        clear_listbox(self.custom_listbox)
        for cmd in self.state.custom_repos:
            self.custom_listbox.append(self._make_repo_row(cmd))
        clear_listbox(self.copr_listbox)
        for repo in self.state.copr_repos:
            lbl = Gtk.Label(label=repo)
            lbl.set_xalign(0)
            set_margins(lbl, top=4, bottom=4, start=8)
            self.copr_listbox.append(lbl)


# =============================================================================
#  PAGE 3 - Packages
# =============================================================================
class PagePackages(Gtk.Box):

    # Packages auto-managed by the wizard — never shown in the queue
    AUTO_MANAGED = {"dnf-command(copr)", "'dnf-command(copr)'"}

    def __init__(self, state: WizardState):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.state = state
        set_margins(self, top=12, bottom=12, start=16, end=16)

        self.append(make_header(
            "Step 3 — Packages",
            "Search for packages to install or remove. Results come from the repos "
            "configured on this host — if a package requires a custom repo (e.g. Tailscale), "
            "add it in Step 2 first, then search by name here."
        ))

        self.notebook = Gtk.Notebook()
        self.notebook.set_vexpand(True)
        self.append(self.notebook)

        # ── Install tab ───────────────────────────────────────────────────
        install_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        set_margins(install_page, top=10, bottom=8, start=8, end=8)

        isearch_box = Gtk.Box(spacing=8)
        self.install_entry = Gtk.Entry(placeholder_text="Search packages to install...")
        self.install_entry.set_hexpand(True)
        self.install_entry.connect("activate", self._do_install_search)
        isearch_btn = Gtk.Button(label="Search")
        isearch_btn.add_css_class("suggested-action")
        isearch_btn.connect("clicked", self._do_install_search)
        self.install_spinner = Gtk.Spinner()
        isearch_box.append(self.install_entry)
        isearch_box.append(isearch_btn)
        isearch_box.append(self.install_spinner)
        install_page.append(isearch_box)

        # ── Search status label — shown when search has no results or errors ──
        self.install_status_lbl = Gtk.Label(label="")
        self.install_status_lbl.set_xalign(0)
        self.install_status_lbl.add_css_class("dim-label")
        self.install_status_lbl.set_visible(False)
        install_page.append(self.install_status_lbl)

        manual_box = Gtk.Box(spacing=8)
        manual_box.set_margin_top(2)
        manual_lbl = Gtk.Label(label="Add manually:")
        self.manual_install_entry = Gtk.Entry(
            placeholder_text="package-name  (for Copr/custom repo packages)")
        self.manual_install_entry.set_hexpand(True)
        self.manual_install_entry.connect("activate", self._add_manual_install)
        manual_add_btn = Gtk.Button(label="Add")
        manual_add_btn.add_css_class("suggested-action")
        manual_add_btn.connect("clicked", self._add_manual_install)
        manual_box.append(manual_lbl)
        manual_box.append(self.manual_install_entry)
        manual_box.append(manual_add_btn)
        install_page.append(manual_box)

        presets_frame = Gtk.Frame(label=" Quick-add popular packages ")
        presets_outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        set_margins(presets_outer, top=6, bottom=6, start=8, end=8)

        presets_note = Gtk.Label()
        presets_note.set_markup(
            '<span size="small" style="italic">'
            'Packages marked [RF] require RPM Fusion — enabling them will also enable '
            'the required repo in Step 2.  '
            'All presets here are pure userspace and work correctly inside a container. '
            'Use <tt>vainfo</tt> after reboot to verify hardware video acceleration.'
            '</span>'
        )
        presets_note.set_xalign(0)
        presets_note.set_wrap(True)
        presets_outer.append(presets_note)

        presets_flow = Gtk.FlowBox()
        presets_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        presets_flow.set_max_children_per_line(6)
        presets_flow.set_row_spacing(4)
        presets_flow.set_column_spacing(4)

        self._preset_buttons = []
        for label, pkgs, needs_free, needs_nonfree in PACKAGE_PRESETS:
            btn = Gtk.Button(label=label)
            btn.connect("clicked", self._add_preset_pkgs, pkgs, needs_free, needs_nonfree)
            presets_flow.append(btn)
            self._preset_buttons.append((btn, pkgs))

        presets_outer.append(presets_flow)
        presets_frame.set_child(presets_outer)
        install_page.append(presets_frame)

        install_results_frame = Gtk.Frame(label=" Search Results ")
        install_results_frame.set_vexpand(True)
        iscroll = Gtk.ScrolledWindow()
        iscroll.set_vexpand(True)
        self.install_listbox = Gtk.ListBox()
        self.install_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        iscroll.set_child(self.install_listbox)
        install_results_frame.set_child(iscroll)
        install_page.append(install_results_frame)

        self.notebook.append_page(install_page, Gtk.Label(label="  Install  "))

        # ── Remove tab ────────────────────────────────────────────────────
        remove_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        set_margins(remove_page, top=10, bottom=8, start=8, end=8)

        rsearch_box = Gtk.Box(spacing=8)
        self.remove_entry = Gtk.Entry(placeholder_text="Search packages to remove...")
        self.remove_entry.set_hexpand(True)
        self.remove_entry.connect("activate", self._do_remove_search)
        rsearch_btn = Gtk.Button(label="Search")
        rsearch_btn.add_css_class("suggested-action")
        rsearch_btn.connect("clicked", self._do_remove_search)
        self.remove_spinner = Gtk.Spinner()
        rsearch_box.append(self.remove_entry)
        rsearch_box.append(rsearch_btn)
        rsearch_box.append(self.remove_spinner)
        remove_page.append(rsearch_box)

        self.remove_status_lbl = Gtk.Label(label="")
        self.remove_status_lbl.set_xalign(0)
        self.remove_status_lbl.add_css_class("dim-label")
        self.remove_status_lbl.set_visible(False)
        remove_page.append(self.remove_status_lbl)

        remove_results_frame = Gtk.Frame(label=" Results ")
        remove_results_frame.set_vexpand(True)
        rscroll = Gtk.ScrolledWindow()
        rscroll.set_vexpand(True)
        self.remove_listbox = Gtk.ListBox()
        self.remove_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        rscroll.set_child(self.remove_listbox)
        remove_results_frame.set_child(rscroll)
        remove_page.append(remove_results_frame)

        self.notebook.append_page(remove_page, Gtk.Label(label="  Remove  "))

        # ── Queued changes summary ────────────────────────────────────────
        sel_frame = Gtk.Frame(label=" Queued Changes ")
        sel_outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        set_margins(sel_outer, top=8, bottom=8, start=8, end=8)

        install_row = Gtk.Box(spacing=8)
        install_row.set_margin_bottom(2)
        install_badge = Gtk.Label(use_markup=True)
        install_badge.set_markup(
            '<span background="#2d6a2d" foreground="white" weight="bold">  +INSTALL  </span>')
        install_badge.set_valign(Gtk.Align.START)
        self.install_chips = Gtk.FlowBox()
        self.install_chips.set_selection_mode(Gtk.SelectionMode.NONE)
        self.install_chips.set_max_children_per_line(30)
        self.install_chips.set_hexpand(True)
        self.install_empty = Gtk.Label(label="(none)")
        self.install_empty.add_css_class("dim-label")
        self.install_chips.append(self.install_empty)
        install_row.append(install_badge)
        install_row.append(self.install_chips)
        sel_outer.append(install_row)

        sel_outer.append(Gtk.Separator())

        remove_row = Gtk.Box(spacing=8)
        remove_row.set_margin_top(2)
        remove_badge = Gtk.Label(use_markup=True)
        remove_badge.set_markup(
            '<span background="#6a2d2d" foreground="white" weight="bold">  -REMOVE  </span>')
        remove_badge.set_valign(Gtk.Align.START)
        self.remove_chips = Gtk.FlowBox()
        self.remove_chips.set_selection_mode(Gtk.SelectionMode.NONE)
        self.remove_chips.set_max_children_per_line(30)
        self.remove_chips.set_hexpand(True)
        self.remove_empty = Gtk.Label(label="(none)")
        self.remove_empty.add_css_class("dim-label")
        self.remove_chips.append(self.remove_empty)
        remove_row.append(remove_badge)
        remove_row.append(self.remove_chips)
        sel_outer.append(remove_row)

        clear_btn = Gtk.Button(label="Clear all selections")
        clear_btn.set_halign(Gtk.Align.END)
        clear_btn.connect("clicked", self._clear_all)
        sel_outer.append(clear_btn)
        sel_frame.set_child(sel_outer)
        self.append(sel_frame)

    # ── search ────────────────────────────────────────────────────────────

    def _add_manual_install(self, *_):
        name = self.manual_install_entry.get_text().strip()
        if not name or name in self.AUTO_MANAGED:
            return
        if name not in self.state.install_pkgs:
            self.state.install_pkgs.append(name)
            self._refresh_labels()
        self.manual_install_entry.set_text("")

    def _add_preset_pkgs(self, btn, pkgs: list, needs_free: bool, needs_nonfree: bool):
        all_present = all(p in self.state.install_pkgs for p in pkgs)
        if all_present:
            for pkg in pkgs:
                if pkg in self.state.install_pkgs:
                    self.state.install_pkgs.remove(pkg)
            btn.remove_css_class("suggested-action")
        else:
            for pkg in pkgs:
                if pkg not in self.state.install_pkgs:
                    self.state.install_pkgs.append(pkg)
            if needs_free:
                self.state.repos.add("RPM Fusion Free")
            if needs_nonfree:
                self.state.repos.add("RPM Fusion Free")
                self.state.repos.add("RPM Fusion Non-Free")
            btn.add_css_class("suggested-action")
        self._refresh_labels()

    def _do_install_search(self, *_):
        query = self.install_entry.get_text().strip()
        if not query:
            return
        clear_listbox(self.install_listbox)
        self.install_status_lbl.set_visible(False)
        self.install_spinner.start()

        def work():
            result, error = self._dnf_search(query)
            GLib.idle_add(self._populate_install, result, error)

        threading.Thread(target=work, daemon=True).start()

    def _do_remove_search(self, *_):
        query = self.remove_entry.get_text().strip()
        if not query:
            return
        clear_listbox(self.remove_listbox)
        self.remove_status_lbl.set_visible(False)
        self.remove_spinner.start()

        def work():
            result, error = self._dnf_search(query)
            GLib.idle_add(self._populate_remove, result, error)

        threading.Thread(target=work, daemon=True).start()

    def _dnf_search(self, query: str) -> tuple[dict, str]:
        """
        Returns (grouped_results, error_message).
        error_message is '' on success or a human-readable explanation on failure.
        grouped_results: {name: [(version, reponame, summary), ...]}
        """
        TIMEOUT = 15

        def ver_key(v):
            return [int(x) if x.isdigit() else x for x in re.split(r'[\.\-]', v)]

        raw = []
        last_error = ""

        # Try dnf5 repoquery first (most detailed output)
        for cache_flag in (["--cacheonly"], []):
            try:
                out = subprocess.check_output(
                    ["dnf5", "repoquery"] + cache_flag + [
                        "--queryformat",
                        r"%{name}\t%{version}-%{release}\t%{reponame}\t%{summary}\n",
                        query],
                    text=True, stderr=subprocess.DEVNULL, timeout=TIMEOUT
                )
                for line in out.splitlines():
                    line = line.strip()
                    if not line or line.startswith(("Updating", "Repo")):
                        continue
                    parts = line.split("\t", 3)
                    if len(parts) == 4:
                        raw.append(tuple(p.strip() for p in parts))
                if raw:
                    break
            except subprocess.TimeoutExpired:
                last_error = "dnf5 timed out. The package cache may need refreshing."
                continue
            except (FileNotFoundError, subprocess.CalledProcessError):
                break

        # Fallback: text search via dnf5 or dnf
        if not raw:
            for cmd in (
                ["dnf5", "search", "--cacheonly", "--quiet", query],
                ["dnf5", "search", "--quiet", query],
                ["dnf",  "search", "--cacheonly", "--quiet", query],
                ["dnf",  "search", "--quiet", query],
            ):
                try:
                    out = subprocess.check_output(
                        cmd, text=True, stderr=subprocess.DEVNULL, timeout=TIMEOUT
                    )
                    for line in out.splitlines():
                        line = line.strip()
                        if not line or line.startswith("Matched fields"):
                            continue
                        if "\t" in line:
                            pkg, _, summary = line.partition("\t")
                            name = re.sub(r"\.(noarch|x86_64|i686|aarch64)$", "", pkg.strip())
                            raw.append((name.strip(), "", "", summary.strip()))
                        else:
                            m = re.match(r"^(\S+?)(?:\.\w+)?\s*:\s*(.+)$", line)
                            if m:
                                raw.append((m.group(1).strip(), "", "", m.group(2).strip()))
                    if raw:
                        last_error = ""
                        break
                except subprocess.TimeoutExpired:
                    last_error = "Package search timed out. Try again or add the package name manually."
                    continue
                except FileNotFoundError:
                    last_error = "Neither dnf5 nor dnf was found on this system."
                    continue
                except subprocess.CalledProcessError as e:
                    last_error = f"Package search returned an error (exit {e.returncode})."
                    continue

        if not raw and not last_error:
            last_error = ""  # genuine empty result — not an error

        # Group by name, keep latest version per (name, repo)
        best = {}
        for name, ver, repo, summary in raw:
            key = (name, repo)
            if key not in best:
                best[key] = (ver, summary)
            else:
                try:
                    if ver_key(ver) > ver_key(best[key][0]):
                        best[key] = (ver, summary)
                except Exception:
                    pass

        grouped = {}
        for (name, repo), (ver, summary) in best.items():
            grouped.setdefault(name, []).append((ver, repo, summary))

        def repo_sort(item):
            repo = item[1].lower()
            if "fedora" in repo and "update" in repo:
                return (0, repo)
            if "fedora" in repo:
                return (1, repo)
            return (2, repo)

        for name in grouped:
            grouped[name].sort(key=repo_sort)

        limited = dict(list(grouped.items())[:60])
        return limited, last_error

    def _populate_install(self, grouped: dict, error: str):
        self.install_spinner.stop()
        clear_listbox(self.install_listbox)
        if error:
            self.install_status_lbl.set_text(f"⚠ {error}")
            self.install_status_lbl.set_visible(True)
        if not grouped:
            lbl = Gtk.Label(label="No packages found." if not error else
                            "No packages found — see message above.")
            set_margins(lbl, top=12, bottom=12)
            self.install_listbox.append(lbl)
            return
        for name, variants in grouped.items():
            self._add_install_row(name, variants)

    def _populate_remove(self, grouped: dict, error: str):
        self.remove_spinner.stop()
        clear_listbox(self.remove_listbox)
        if error:
            self.remove_status_lbl.set_text(f"⚠ {error}")
            self.remove_status_lbl.set_visible(True)
        if not grouped:
            lbl = Gtk.Label(label="No packages found." if not error else
                            "No packages found — see message above.")
            set_margins(lbl, top=12, bottom=12)
            self.remove_listbox.append(lbl)
            return
        for name, variants in grouped.items():
            self._add_remove_row(name, variants)

    def _add_install_row(self, name: str, variants: list):
        if len(variants) == 1 and not variants[0][1]:
            self.install_listbox.append(self._make_simple_row(
                name, variants[0][2],
                checked=name in self.state.install_pkgs,
                chk_label="Install",
                on_toggle=self._on_install_toggled,
                pkg_key=name))
            return

        if len(variants) == 1:
            ver, repo, summary = variants[0]
            self.install_listbox.append(self._make_version_row(
                name, ver, repo, summary,
                checked=name in self.state.install_pkgs,
                chk_label="Install",
                on_toggle=self._on_install_toggled,
                pkg_key=name))
            return

        header = Gtk.Label()
        header.set_markup(f"<b>{GLib.markup_escape_text(name)}</b>")
        header.set_xalign(0)
        set_margins(header, top=6, bottom=2, start=6)
        self.install_listbox.append(header)
        for ver, repo, summary in variants:
            row = self._make_version_row(
                name, ver, repo, summary,
                checked=name in self.state.install_pkgs,
                chk_label="Install",
                on_toggle=self._on_install_toggled,
                pkg_key=name)
            row.set_margin_start(20)
            self.install_listbox.append(row)

    def _add_remove_row(self, name: str, variants: list):
        if len(variants) == 1 and not variants[0][1]:
            self.remove_listbox.append(self._make_simple_row(
                name, variants[0][2],
                checked=name in self.state.remove_pkgs,
                chk_label="Remove",
                on_toggle=self._on_remove_toggled,
                pkg_key=name))
            return

        if len(variants) == 1:
            ver, repo, summary = variants[0]
            self.remove_listbox.append(self._make_version_row(
                name, ver, repo, summary,
                checked=name in self.state.remove_pkgs,
                chk_label="Remove",
                on_toggle=self._on_remove_toggled,
                pkg_key=name))
            return

        header = Gtk.Label()
        header.set_markup(f"<b>{GLib.markup_escape_text(name)}</b>")
        header.set_xalign(0)
        set_margins(header, top=6, bottom=2, start=6)
        self.remove_listbox.append(header)
        for ver, repo, summary in variants:
            row = self._make_version_row(
                name, ver, repo, summary,
                checked=name in self.state.remove_pkgs,
                chk_label="Remove",
                on_toggle=self._on_remove_toggled,
                pkg_key=name)
            row.set_margin_start(20)
            self.remove_listbox.append(row)

    def _make_simple_row(self, name, summary, checked, chk_label, on_toggle, pkg_key):
        row_box = Gtk.Box(spacing=8)
        set_margins(row_box, top=4, bottom=4, start=6, end=6)
        chk = Gtk.CheckButton(label=chk_label)
        chk.set_active(checked)
        chk.set_size_request(100, -1)
        name_lbl = Gtk.Label()
        name_lbl.set_markup(f"<b>{GLib.markup_escape_text(name)}</b>")
        name_lbl.set_xalign(0)
        name_lbl.set_width_chars(26)
        name_lbl.set_max_width_chars(26)
        name_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        sum_lbl = Gtk.Label(label=summary)
        sum_lbl.set_xalign(0)
        sum_lbl.set_hexpand(True)
        sum_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        sum_lbl.add_css_class("dim-label")
        row_box.append(chk)
        row_box.append(name_lbl)
        row_box.append(sum_lbl)
        # Store handler id for safe block/unblock
        hid = chk.connect("toggled", on_toggle, pkg_key)
        chk.set_data("handler_id", hid)
        return row_box

    def _make_version_row(self, name, ver, repo, summary, checked, chk_label, on_toggle, pkg_key):
        row_box = Gtk.Box(spacing=8)
        set_margins(row_box, top=3, bottom=3, start=6, end=6)
        chk = Gtk.CheckButton(label=chk_label)
        chk.set_active(checked)
        chk.set_size_request(100, -1)
        ver_lbl = Gtk.Label()
        ver_lbl.set_markup(f"<tt>{GLib.markup_escape_text(ver)}</tt>")
        ver_lbl.set_xalign(0)
        ver_lbl.set_width_chars(22)
        ver_lbl.set_max_width_chars(22)
        ver_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        repo_lbl = Gtk.Label()
        repo_lbl.set_markup(f'<span foreground="#4a90d9">{GLib.markup_escape_text(repo)}</span>')
        repo_lbl.set_xalign(0)
        repo_lbl.set_width_chars(28)
        repo_lbl.set_max_width_chars(28)
        repo_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        sum_lbl = Gtk.Label(label=summary)
        sum_lbl.set_xalign(0)
        sum_lbl.set_hexpand(True)
        sum_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        sum_lbl.add_css_class("dim-label")
        row_box.append(chk)
        row_box.append(ver_lbl)
        row_box.append(repo_lbl)
        row_box.append(sum_lbl)
        hid = chk.connect("toggled", on_toggle, pkg_key)
        chk.set_data("handler_id", hid)
        return row_box

    def _on_install_toggled(self, chk, name: str):
        if chk.get_active():
            if name not in self.state.install_pkgs and name not in self.AUTO_MANAGED:
                self.state.install_pkgs.append(name)
            if name in self.state.remove_pkgs:
                self.state.remove_pkgs.remove(name)
        else:
            if name in self.state.install_pkgs:
                self.state.install_pkgs.remove(name)
        self._refresh_labels()

    def _on_remove_toggled(self, chk, name: str):
        if chk.get_active():
            if name not in self.state.remove_pkgs:
                self.state.remove_pkgs.append(name)
            if name in self.state.install_pkgs:
                self.state.install_pkgs.remove(name)
        else:
            if name in self.state.remove_pkgs:
                self.state.remove_pkgs.remove(name)
        self._refresh_labels()

    def _clear_all(self, *_):
        self.state.install_pkgs.clear()
        self.state.remove_pkgs.clear()
        clear_listbox(self.install_listbox)
        clear_listbox(self.remove_listbox)
        self._refresh_labels()

    def _make_chip(self, pkg: str, pkg_list: list) -> Gtk.Box:
        chip = Gtk.Box(spacing=2)
        set_margins(chip, top=2, bottom=2, start=3, end=3)
        lbl = Gtk.Label(label=pkg)
        lbl.set_margin_start(4)
        remove_btn = Gtk.Button(label="×")
        remove_btn.set_has_frame(False)
        remove_btn.add_css_class("flat")
        remove_btn.connect("clicked", self._on_chip_remove, pkg, pkg_list)
        chip.append(lbl)
        chip.append(remove_btn)
        return chip

    def _on_chip_remove(self, _btn, pkg: str, pkg_list: list):
        if pkg in pkg_list:
            pkg_list.remove(pkg)
        self._refresh_labels()
        self._untick_search_row(pkg, pkg_list)

    def _untick_search_row(self, pkg: str, pkg_list: list):
        listbox = (self.install_listbox
                   if pkg_list is self.state.install_pkgs
                   else self.remove_listbox)
        on_toggle = (self._on_install_toggled
                     if pkg_list is self.state.install_pkgs
                     else self._on_remove_toggled)
        i = 0
        while True:
            row = listbox.get_row_at_index(i)
            if row is None:
                break
            child = row.get_child()
            if isinstance(child, Gtk.Box):
                first = child.get_first_child()
                if isinstance(first, Gtk.CheckButton):
                    name_widget = first.get_next_sibling()
                    if name_widget and hasattr(name_widget, "get_label"):
                        if name_widget.get_label() == pkg:
                            hid = first.get_data("handler_id")
                            if hid:
                                first.handler_block(hid)
                            first.set_active(False)
                            if hid:
                                first.handler_unblock(hid)
                            break
            i += 1

    def _refresh_chips(self, chips: Gtk.FlowBox, empty_lbl: Gtk.Label, pkgs: list):
        clear_flowbox(chips)
        visible = [p for p in pkgs if p not in self.AUTO_MANAGED]
        if not visible:
            chips.append(empty_lbl)
        else:
            for pkg in visible:
                chips.append(self._make_chip(pkg, pkgs))

    def _refresh_labels(self):
        self._refresh_chips(self.install_chips, self.install_empty, self.state.install_pkgs)
        self._refresh_chips(self.remove_chips,  self.remove_empty,  self.state.remove_pkgs)

    def on_enter(self):
        self._refresh_labels()
        self._sync_preset_buttons()
        self._sync_search_checkboxes()

    def _sync_search_checkboxes(self):
        """Update checkboxes in visible search results to match current queue state."""
        for listbox, pkg_list, on_toggle in (
            (self.install_listbox, self.state.install_pkgs, self._on_install_toggled),
            (self.remove_listbox,  self.state.remove_pkgs,  self._on_remove_toggled),
        ):
            i = 0
            while True:
                row = listbox.get_row_at_index(i)
                if row is None:
                    break
                child = row.get_child()
                if isinstance(child, Gtk.Box):
                    first = child.get_first_child()
                    if isinstance(first, Gtk.CheckButton):
                        name_widget = first.get_next_sibling()
                        if name_widget and hasattr(name_widget, "get_label"):
                            pkg = name_widget.get_label()
                            hid = first.get_data("handler_id")
                            if hid:
                                first.handler_block(hid)
                            first.set_active(pkg in pkg_list)
                            if hid:
                                first.handler_unblock(hid)
                i += 1

    def _sync_preset_buttons(self):
        for btn, pkgs in self._preset_buttons:
            if all(p in self.state.install_pkgs for p in pkgs):
                btn.add_css_class("suggested-action")
            else:
                btn.remove_css_class("suggested-action")


# =============================================================================
#  PAGE 4 - Performance Tweaks
# =============================================================================
class PagePerformance(Gtk.Box):
    COPR_REPO = "bieszczaders/kernel-cachyos-addons"

    TWEAKS = [
        (
            "perf_cachyos_settings",
            "cachyos-settings",
            "General System Performance Tuning",
            "Installs sysctl, udev and modprobe configuration files that tune CPU, I/O "
            "and network behaviour for better desktop responsiveness. No kernel replacement needed.",
        ),
        (
            "perf_ksm_settings",
            "cachyos-ksm-settings",
            "RAM Optimisation via Kernel Samepage Merging",
            "Reduces memory usage by merging identical pages in RAM. Most beneficial on systems "
            "running virtual machines or many containers. Adds a small CPU overhead for page scanning.",
        ),
        (
            "perf_scx_scheds",
            "scx-scheds + scx-tools",
            "Userspace CPU Scheduler via sched-ext BPF",
            "Provides alternative CPU schedulers (scx_bpfland, scx_lavd and others) that can "
            "improve responsiveness and gaming performance. Also installs scx-tools (scxctl) "
            "for managing schedulers. Enables scx_loader.service at boot.",
        ),
    ]

    def __init__(self, state: WizardState):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.state = state
        set_margins(self, top=12, bottom=12, start=16, end=16)
        self._acknowledged = False

        self.append(make_header(
            "Step 4 — Performance Tweaks",
            "Optional system-level performance enhancements from the CachyOS addons repository. "
            "These are independent of the CachyOS kernel and work on the stock Fedora kernel."
        ))

        warn_frame = Gtk.Frame()
        warn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        set_margins(warn_box, top=8, bottom=8, start=10, end=10)
        warn_lbl = Gtk.Label(use_markup=True)
        warn_lbl.set_markup(
            "<b>These tweaks require Linux kernel 6.12 or newer.</b>\n"
            "Fedora 41 and later meet this requirement. "
            "You will be asked to confirm before any tweak is enabled."
        )
        warn_lbl.set_xalign(0)
        warn_lbl.set_wrap(True)
        warn_box.append(warn_lbl)
        warn_frame.set_child(warn_box)
        self.append(warn_frame)

        self._switches = {}
        for attr, pkg, title, desc in self.TWEAKS:
            row_frame = Gtk.Frame()
            row_frame.set_margin_top(4)
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            set_margins(row_box, top=10, bottom=10, start=12, end=12)

            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            text_box.set_hexpand(True)

            title_lbl = Gtk.Label()
            title_lbl.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
            title_lbl.set_xalign(0)

            pkg_lbl = Gtk.Label()
            pkg_lbl.set_markup(
                f'<span size="small"><tt>{GLib.markup_escape_text(pkg)}</tt></span>')
            pkg_lbl.set_xalign(0)
            pkg_lbl.add_css_class("dim-label")

            desc_lbl = Gtk.Label(label=desc)
            desc_lbl.set_xalign(0)
            desc_lbl.set_wrap(True)
            desc_lbl.add_css_class("dim-label")

            text_box.append(title_lbl)
            text_box.append(pkg_lbl)
            text_box.append(desc_lbl)

            switch = Gtk.Switch()
            switch.set_valign(Gtk.Align.CENTER)
            switch.connect("state-set", self._on_toggle, attr)

            self._switches[attr] = switch
            row_box.append(text_box)
            row_box.append(switch)
            row_frame.set_child(row_box)
            self.append(row_frame)

    def _on_toggle(self, switch, state, attr):
        if state and not self._acknowledged:
            switch.handler_block_by_func(self._on_toggle)
            switch.set_active(False)
            switch.handler_unblock_by_func(self._on_toggle)
            self._show_confirm(switch, attr)
            return False
        self._apply_tweak(attr, state)
        return False

    def _show_confirm(self, switch, attr):
        win = self.get_root()
        dlg = Gtk.MessageDialog(
            transient_for=win, modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Kernel 6.12 or newer required",
            secondary_text=(
                "These performance tweaks require Linux kernel 6.12 or newer.\n"
                "Fedora 41 and later meet this requirement.\n\n"
                "Do you want to continue?"
            )
        )
        def on_response(d, response):
            d.close()
            if response == Gtk.ResponseType.OK:
                self._acknowledged = True
                switch.handler_block_by_func(self._on_toggle)
                switch.set_active(True)
                switch.handler_unblock_by_func(self._on_toggle)
                self._apply_tweak(attr, True)
        dlg.connect("response", on_response)
        dlg.present()

    def _apply_tweak(self, attr, state):
        setattr(self.state, attr, state)
        SCX_SVCS = {"scx", "scx.service", "scx_loader", "scx_loader.service"}
        if attr == "perf_scx_scheds":
            if state:
                if "ananicy-cpp" in self.state.install_pkgs:
                    self.state.install_pkgs.remove("ananicy-cpp")
                if "scx_loader.service" not in self.state.systemd_enable:
                    self.state.systemd_enable.append("scx_loader.service")
            else:
                self.state.systemd_enable = [
                    s for s in self.state.systemd_enable if s not in SCX_SVCS
                ]

    def on_enter(self):
        for attr, _, _, _ in self.TWEAKS:
            sw = self._switches[attr]
            sw.handler_block_by_func(self._on_toggle)
            sw.set_active(getattr(self.state, attr))
            sw.handler_unblock_by_func(self._on_toggle)


# =============================================================================
#  PAGE 5 - Systemd
# =============================================================================
class PageSystemd(Gtk.Box):

    PKG_SERVICE_MAP = {
        "tailscale":  ["tailscaled"],
        "docker":     ["docker"],
        "podman":     ["podman.socket"],
        "cups":       ["cups"],
        "bluetooth":  ["bluetooth"],
        "sshd":       ["sshd"],
        "openssh":    ["sshd"],
        "firewalld":  ["firewalld"],
        "avahi":      ["avahi-daemon"],
        "cockpit":    ["cockpit.socket"],
        "libvirt":    ["libvirtd", "virtlogd"],
        "qemu":       ["libvirtd"],
        "nginx":      ["nginx"],
        "httpd":      ["httpd"],
        "mariadb":    ["mariadb"],
        "mysql":      ["mysqld"],
        "postgresql": ["postgresql"],
        "redis":      ["redis"],
        "wireguard":  ["wg-quick@wg0"],
    }

    def __init__(self, state: WizardState):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.state = state
        set_margins(self, top=12, bottom=12, start=16, end=16)

        self.append(make_header(
            "Step 5 — Systemd Services",
            "Enable or disable services at boot. Leave blank if not needed."
        ))

        en_frame = Gtk.Frame(label=" Enable at boot ")
        en_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        set_margins(en_box, top=8, bottom=8, start=8, end=8)
        en_hint = Gtk.Label(label="One service per line, e.g.  sshd  or  docker  or  cups")
        en_hint.set_xalign(0)
        en_hint.add_css_class("dim-label")
        en_box.append(en_hint)
        en_scroll = Gtk.ScrolledWindow()
        en_scroll.set_size_request(-1, 110)
        self.en_buffer = Gtk.TextBuffer()
        en_view = Gtk.TextView(buffer=self.en_buffer)
        en_view.set_monospace(True)
        en_scroll.set_child(en_view)
        en_box.append(en_scroll)
        en_frame.set_child(en_box)
        self.append(en_frame)

        dis_frame = Gtk.Frame(label=" Disable at boot ")
        dis_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        set_margins(dis_box, top=8, bottom=8, start=8, end=8)
        dis_hint = Gtk.Label(label="One service per line, e.g.  NetworkManager-wait-online")
        dis_hint.set_xalign(0)
        dis_hint.add_css_class("dim-label")
        dis_box.append(dis_hint)
        dis_scroll = Gtk.ScrolledWindow()
        dis_scroll.set_size_request(-1, 110)
        self.dis_buffer = Gtk.TextBuffer()
        dis_view = Gtk.TextView(buffer=self.dis_buffer)
        dis_view.set_monospace(True)
        dis_scroll.set_child(dis_view)
        dis_box.append(dis_scroll)
        dis_frame.set_child(dis_box)
        self.append(dis_frame)

        self.en_buffer.connect("changed",  self._sync_enable)
        self.dis_buffer.connect("changed", self._sync_disable)

    def _buf_lines(self, buf):
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        return [l.strip() for l in text.splitlines() if l.strip()]

    def _sync_enable(self, *_):
        self.state.systemd_enable = self._buf_lines(self.en_buffer)

    def _sync_disable(self, *_):
        self.state.systemd_disable = self._buf_lines(self.dis_buffer)

    def _auto_enable_services(self):
        SCX_SVCS = {"scx", "scx.service", "scx_loader", "scx_loader.service"}
        for pkg in self.state.install_pkgs:
            pkg_lower = pkg.lower()
            for fragment, svcs in self.PKG_SERVICE_MAP.items():
                if fragment in pkg_lower:
                    for svc in svcs:
                        if svc not in self.state.systemd_enable and svc not in SCX_SVCS:
                            self.state.systemd_enable.append(svc)

    def on_enter(self):
        self._auto_enable_services()
        self.en_buffer.set_text("\n".join(self.state.systemd_enable))
        self.dis_buffer.set_text("\n".join(self.state.systemd_disable))


# =============================================================================
#  PAGE 6 - Review
# =============================================================================
class PageReview(Gtk.Box):
    def __init__(self, state: WizardState, page_build):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.state      = state
        self.page_build = page_build
        set_margins(self, top=8, bottom=8, start=12, end=12)

        # ── Toolbar: tag + action buttons ─────────────────────────────────
        toolbar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        tag_row = Gtk.Box(spacing=8)
        tag_row.append(Gtk.Label(label="Image tag:"))
        self.tag_entry = Gtk.Entry()
        self.tag_entry.set_text(state.image_tag)
        self.tag_entry.set_hexpand(True)
        self.tag_entry.connect("changed", self._on_tag_changed)
        tag_row.append(self.tag_entry)

        save_btn = Gtk.Button(label="Save Containerfile")
        save_btn.connect("clicked", self._save_only)

        build_btn = Gtk.Button(label="Save and Build")
        build_btn.add_css_class("suggested-action")
        build_btn.connect("clicked", self._save_and_build)

        tag_row.append(save_btn)
        tag_row.append(build_btn)
        toolbar.append(tag_row)

        # Pre-flight issues label
        self.preflight_lbl = Gtk.Label()
        self.preflight_lbl.set_xalign(0)
        self.preflight_lbl.set_wrap(True)
        self.preflight_lbl.set_visible(False)
        toolbar.append(self.preflight_lbl)

        self.append(toolbar)

        # ── Containerfile editor ──────────────────────────────────────────
        cf_frame = Gtk.Frame(label=" Containerfile (editable) ")
        cf_scroll = Gtk.ScrolledWindow()
        cf_scroll.set_size_request(-1, 500)
        cf_scroll.set_vexpand(True)
        self.cf_buffer = Gtk.TextBuffer()
        cf_view = Gtk.TextView(buffer=self.cf_buffer)
        cf_view.set_monospace(True)
        cf_view.set_editable(True)
        cf_scroll.set_child(cf_view)
        cf_frame.set_child(cf_scroll)
        self.append(cf_frame)

    def _on_tag_changed(self, entry):
        self.state.image_tag = entry.get_text().strip()

    def on_enter(self):
        self.cf_buffer.set_text(self.state.generate_containerfile())
        self.tag_entry.set_text(self.state.image_tag)
        self._run_preflight()

    def _run_preflight(self):
        """Check state and Containerfile content for problems before building."""
        issues = self.state.validate_for_build()
        cf_text = self._get_cf()
        cf_stripped = cf_text.strip()

        if not cf_stripped:
            issues.append("Containerfile is empty.")
        elif not any(line.strip().upper().startswith("FROM ")
                     for line in cf_stripped.splitlines()):
            issues.append("Containerfile is missing a FROM instruction.")

        if issues:
            self.preflight_lbl.set_markup(
                "<span foreground='#cc4444'>⚠ Pre-flight issues:\n" +
                "\n".join(f"  • {i}" for i in issues) +
                "</span>"
            )
            self.preflight_lbl.set_visible(True)
        else:
            self.preflight_lbl.set_visible(False)

    def _get_cf(self) -> str:
        return self.cf_buffer.get_text(
            self.cf_buffer.get_start_iter(),
            self.cf_buffer.get_end_iter(), True
        )

    def _save(self) -> bool:
        """Write the Containerfile to disk. Returns True on success."""
        path = os.path.join(SCRIPT_DIR, "Containerfile")
        try:
            with open(path, "w") as f:
                f.write(self._get_cf())
            return True
        except Exception as e:
            show_error(self.get_root(), f"Could not save Containerfile:\n{e}")
            return False

    def _save_only(self, *_):
        if self._save():
            win = self.get_root()
            d = Gtk.MessageDialog(transient_for=win, modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="Containerfile saved.",
                secondary_text=os.path.join(SCRIPT_DIR, "Containerfile"))
            d.connect("response", lambda d, _: d.close())
            d.present()

    def _save_and_build(self, *_):
        # Re-run pre-flight on the current editor contents
        self._run_preflight()
        issues = self.state.validate_for_build()
        cf_text = self._get_cf().strip()
        if not cf_text or not any(
            line.strip().upper().startswith("FROM ")
            for line in cf_text.splitlines()
        ):
            issues.append("Containerfile is missing a valid FROM instruction.")

        if issues:
            show_error(
                self.get_root(),
                "Cannot build — please fix the following issues first:\n\n" +
                "\n".join(f"• {i}" for i in issues)
            )
            return

        if not self._save():
            return

        self.page_build.start_build(
            self.state.image_tag or "localhost/atomic-custom:latest"
        )
        win = self.get_root()
        if hasattr(win, "go_to_build"):
            win.go_to_build()


# =============================================================================
#  PAGE 7 - Build
# =============================================================================
class PageBuild(Gtk.Box):
    def __init__(self, state: WizardState, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.state          = state
        self.app            = app
        self._pull_timer_id = None
        self._pull_start    = None
        self._outer_scroll  = None   # set by WizardWindow after construction
        set_margins(self, top=12, bottom=12, start=16, end=16)

        self.log_frame = Gtk.Frame(label=" Output Log ")
        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_size_request(-1, 350)
        log_scroll.set_vexpand(True)
        self.log_buffer = Gtk.TextBuffer()
        self.log_view = Gtk.TextView(buffer=self.log_buffer)
        self.log_view.set_monospace(True)
        self.log_view.set_editable(False)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        log_scroll.set_child(self.log_view)
        self.log_frame.set_child(log_scroll)
        self.append(self.log_frame)

        # ── Copy-log button ───────────────────────────────────────────────
        copy_btn = Gtk.Button(label="Copy log to clipboard")
        copy_btn.set_halign(Gtk.Align.END)
        copy_btn.set_margin_top(4)
        copy_btn.connect("clicked", self._copy_log)
        self.append(copy_btn)

        status_bar = Gtk.Box(spacing=8)
        status_bar.set_margin_top(6)
        self.status_spinner = Gtk.Spinner()
        self.status_lbl = Gtk.Label(label="")
        self.status_lbl.set_xalign(0)
        self.status_lbl.set_hexpand(True)
        status_bar.append(self.status_spinner)
        status_bar.append(self.status_lbl)
        self.append(status_bar)

        # ── Deployment status panel — sits just above the Deploy button ───
        # Populated on demand via Refresh so it doesn't trigger a polkit
        # prompt on page entry. User clicks Refresh after a build, when
        # polkit is already warm from the build itself.
        deploy_status_frame = Gtk.Frame(label=" Current Deployment Status ")
        deploy_status_frame.set_margin_top(10)
        deploy_status_grid = Gtk.Grid()
        deploy_status_grid.set_column_spacing(12)
        deploy_status_grid.set_row_spacing(4)
        set_margins(deploy_status_grid, top=8, bottom=8, start=12, end=12)

        def _status_label(text, dim=False, markup=False):
            lbl = Gtk.Label()
            if markup:
                lbl.set_markup(text)
            else:
                lbl.set_label(text)
            lbl.set_xalign(0)
            lbl.set_hexpand(True)
            lbl.set_wrap(True)
            if dim:
                lbl.add_css_class("dim-label")
            return lbl

        deploy_status_grid.attach(_status_label("<b>Booted:</b>", markup=True),       0, 0, 1, 1)
        self._booted_lbl   = _status_label("—", dim=True)
        deploy_status_grid.attach(self._booted_lbl,   1, 0, 1, 1)

        deploy_status_grid.attach(_status_label("<b>Rollback:</b>", markup=True),     0, 1, 1, 1)
        self._rollback_lbl = _status_label("—", dim=True)
        deploy_status_grid.attach(self._rollback_lbl, 1, 1, 1, 1)

        deploy_status_grid.attach(_status_label("<b>Will deploy as:</b>", markup=True), 0, 2, 1, 1)
        self._new_image_lbl = _status_label("", dim=True)
        deploy_status_grid.attach(self._new_image_lbl, 1, 2, 1, 1)

        # Refresh button inline with the grid
        refresh_btn = Gtk.Button(label="↺  Refresh status")
        refresh_btn.set_halign(Gtk.Align.END)
        refresh_btn.set_margin_top(4)
        refresh_btn.set_margin_bottom(4)
        refresh_btn.set_margin_end(8)
        refresh_btn.connect("clicked", self._refresh_deploy_status)
        deploy_status_grid.attach(refresh_btn, 1, 3, 1, 1)

        deploy_status_frame.set_child(deploy_status_grid)
        self.append(deploy_status_frame)

        self.deploy_btn = Gtk.Button(label="Deploy / Switch image")
        self.deploy_btn.add_css_class("destructive-action")
        self.deploy_btn.set_margin_top(6)
        self.deploy_btn.connect("clicked", self._deploy)
        self.deploy_btn.set_visible(False)
        self.append(self.deploy_btn)

    def on_enter(self):
        self._new_image_lbl.set_text(self.state.image_tag or "localhost/atomic-custom:latest")

    def _refresh_deploy_status(self, *_):
        """Called by the Refresh button — fetches bootc status in a background thread."""
        self._booted_lbl.set_text("Reading…")
        self._booted_lbl.add_css_class("dim-label")
        self._rollback_lbl.set_text("Reading…")
        self._rollback_lbl.add_css_class("dim-label")
        threading.Thread(target=self._fetch_deploy_status_async, daemon=True).start()

    def _fetch_deploy_status_async(self):
        """Fetch bootc status via pkexec and populate the deployment status panel.
        This is the single privileged call for the whole Build page — the credential
        it establishes with polkit covers the subsequent build command too."""
        try:
            import json, shutil
            prefix = ["pkexec"] if shutil.which("pkexec") else ["sudo"]
            out = subprocess.check_output(
                prefix + ["bootc", "status", "--json"],
                text=True, stderr=subprocess.DEVNULL, timeout=15
            )
            data = json.loads(out)
            self.state.bootc_status_cache = data
            spec = data.get("status", {})

            def _parse_image(node):
                if not node:
                    return None, None
                # actual path: node.image.image.image (tag string)
                #              node.image.timestamp   (ISO timestamp)
                img_outer = node.get("image", {})
                tag = img_outer.get("image", {}).get("image", "") or ""
                tag = tag.replace("containers-storage:", "").strip()
                ts  = img_outer.get("timestamp", "") or ""
                # timestamp is like "2026-03-15T23:20:16.373179659Z"
                date = ts[:16].replace("T", " ") if ts else ""
                return tag, date

            booted_tag,   booted_date   = _parse_image(spec.get("booted"))
            rollback_tag, rollback_date = _parse_image(spec.get("rollback"))
            GLib.idle_add(self._apply_deploy_status,
                          booted_tag, booted_date,
                          rollback_tag, rollback_date)
        except Exception:
            GLib.idle_add(self._apply_deploy_status, None, None, None, None)

    def _apply_deploy_status(self, booted_tag, booted_date, rollback_tag, rollback_date):
        # ── Booted ────────────────────────────────────────────────────────
        if booted_tag:
            text = booted_tag
            if booted_date:
                text += f"  (built {booted_date})"
            self._booted_lbl.set_text(text)
            self._booted_lbl.remove_css_class("dim-label")
        else:
            self._booted_lbl.set_text("Unable to read — is bootc installed?")
            self._booted_lbl.add_css_class("dim-label")

        # ── Rollback ──────────────────────────────────────────────────────
        if rollback_tag:
            text = rollback_tag
            if rollback_date:
                text += f"  (built {rollback_date})"
            text += "  ✓"
            self._rollback_lbl.set_markup(
                f"{GLib.markup_escape_text(text)}"
            )
            self._rollback_lbl.remove_css_class("dim-label")
        else:
            self._rollback_lbl.set_markup(
                "<span foreground='#cc8800'>⚠ None — this may be your first switch. "
                "Your original Fedora image is still selectable from the boot menu.</span>"
            )
            self._rollback_lbl.remove_css_class("dim-label")

    def _copy_log(self, *_):
        text = self.log_buffer.get_text(
            self.log_buffer.get_start_iter(),
            self.log_buffer.get_end_iter(), True
        )
        display = self.get_display()
        if display:
            display.get_clipboard().set(text)

    def start_build(self, tag: str):
        import shutil
        self.deploy_btn.set_visible(False)
        self.log_buffer.set_text("")

        path = os.path.join(SCRIPT_DIR, "Containerfile")
        if shutil.which("pkexec"):
            build_cmd = ["pkexec", "podman", "build", "--pull", "-t", tag, "-f", path, SCRIPT_DIR]
        else:
            build_cmd = ["sudo", "podman", "build", "--pull", "-t", tag, "-f", path, SCRIPT_DIR]

        self._log(f"Building:  {' '.join(build_cmd)}\n\n")
        self._set_status("Authenticating — please respond to the password prompt…", spinning=True)

        def worker():
            try:
                first_output = True
                proc = subprocess.Popen(
                    build_cmd,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                )
                for line in proc.stdout:
                    if first_output:
                        GLib.idle_add(self._set_status, "Building…", True)
                        first_output = False
                    GLib.idle_add(self._log, line)
                proc.wait()
                if proc.returncode == 0:
                    GLib.idle_add(self._build_success, tag)
                else:
                    GLib.idle_add(self._log, f"\nBuild failed (exit {proc.returncode})\n")
                    GLib.idle_add(self._set_status, f"Build failed (exit {proc.returncode})")
            except FileNotFoundError:
                GLib.idle_add(self._log, "\npodman not found. Is it installed?\n")
                GLib.idle_add(self._set_status, "Error: podman not found")
            except Exception as e:
                GLib.idle_add(self._log, f"\nError: {e}\n")
                GLib.idle_add(self._set_status, f"Error: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _build_success(self, tag: str):
        self._log(f"\nBuild complete!  Image: {tag}\n")
        self._set_status(f"Build complete: {tag} — inspecting image…", spinning=True)
        threading.Thread(target=self._inspect_image_async, args=(tag,), daemon=True).start()

    def _inspect_image_async(self, tag: str):
        """Run podman image inspect and surface size/layers/date in the log."""
        try:
            import json
            out = subprocess.check_output(
                ["podman", "image", "inspect", tag],
                text=True, stderr=subprocess.DEVNULL, timeout=15
            )
            data = json.loads(out)
            if data:
                info   = data[0]
                size   = info.get("Size", 0)
                size_mb = f"{size / 1_048_576:.1f} MB"
                layers  = len(info.get("RootFS", {}).get("Layers", []))
                created = info.get("Created", "unknown")[:19].replace("T", " ")
                summary = (
                    f"\n── Image info ──────────────────────────\n"
                    f"  Size:    {size_mb}\n"
                    f"  Layers:  {layers}\n"
                    f"  Created: {created}\n"
                    f"────────────────────────────────────────\n"
                )
                GLib.idle_add(self._log, summary)
        except Exception:
            pass   # inspect failure is non-fatal
        GLib.idle_add(self._finish_build_success, tag)

    def _finish_build_success(self, tag: str):
        self._set_status(f"Build complete: {tag} — ready to deploy.")
        self.deploy_btn.set_visible(True)

    def _deploy(self, *_):
        tag = self.state.image_tag or "localhost/atomic-custom:latest"
        win = self.get_root()

        # Explicit confirmation dialog with clear consequence language
        dlg = Gtk.Window(title="Deploy Image", modal=True, transient_for=win)
        dlg.set_default_size(520, 320)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        set_margins(outer, top=24, bottom=24, start=24, end=24)

        icon_lbl = Gtk.Label()
        icon_lbl.set_markup("<span size='xx-large'>⚠</span>")
        icon_lbl.set_halign(Gtk.Align.CENTER)
        outer.append(icon_lbl)

        title_lbl = Gtk.Label()
        title_lbl.set_markup("<b><big>Deploy Image to This Machine</big></b>")
        title_lbl.set_halign(Gtk.Align.CENTER)
        outer.append(title_lbl)

        desc_lbl = Gtk.Label()
        desc_lbl.set_markup(
            f"Image: <tt>{GLib.markup_escape_text(tag)}</tt>\n\n"
            "<b>Upgrade</b> — the image tag is already deployed; stage the new build as an update.\n"
            "  <tt>sudo bootc upgrade</tt>\n\n"
            "<b>Switch</b> — first time deploying this tag, or changing to a new one.\n"
            f"  <tt>sudo bootc switch --transport containers-storage {GLib.markup_escape_text(tag)}</tt>\n\n"
            "⚠  <b>A reboot is required to apply the change.</b>\n"
            "Your previous deployment is kept as a rollback — you can return to it with\n"
            "<tt>sudo bootc rollback</tt> or by selecting it in the boot menu.\n"
            "<b>Keep at least one known-good deployment before deploying to a production machine.</b>"
        )
        desc_lbl.set_xalign(0)
        desc_lbl.set_wrap(True)
        outer.append(desc_lbl)

        btn_box = Gtk.Box(spacing=12)
        btn_box.set_halign(Gtk.Align.END)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda _: dlg.close())

        upgrade_btn = Gtk.Button(label="Upgrade (already deployed)")
        upgrade_btn.add_css_class("suggested-action")
        upgrade_btn.connect("clicked", self._do_upgrade, tag, dlg)

        switch_btn = Gtk.Button(label="Switch (first time / new tag)")
        switch_btn.add_css_class("destructive-action")
        switch_btn.connect("clicked", self._do_switch, tag, dlg)

        btn_box.append(cancel_btn)
        btn_box.append(upgrade_btn)
        btn_box.append(switch_btn)
        outer.append(btn_box)

        dlg.set_child(outer)
        dlg.present()

    def _do_upgrade(self, _btn, tag, dlg):
        dlg.close()
        self._run_bootc(["bootc", "upgrade"], "Upgrade complete. Reboot to apply.")

    def _do_switch(self, _btn, tag, dlg):
        dlg.close()
        self._run_bootc(
            ["bootc", "switch", "--transport", "containers-storage", tag],
            "Switch complete. Reboot to apply."
        )

    def _run_bootc(self, bootc_cmd: list, success_msg: str):
        import shutil
        prefix = ["pkexec"] if shutil.which("pkexec") else ["sudo"]
        cmd = prefix + bootc_cmd
        self._log(f"\nRunning: {' '.join(cmd)}\n\n")
        self._set_status("Authenticating — please respond to the password prompt…", spinning=True)
        self._pull_timer_id = None
        self._pull_start    = None

        def start_pull_ticker(size_info: str):
            import time
            self._pull_start = time.monotonic()
            self._set_status(f"Downloading layers ({size_info})... 0s elapsed", spinning=True)
            def tick():
                if self._pull_timer_id is None:
                    return False
                elapsed = int(time.monotonic() - self._pull_start)
                self._set_status(
                    f"Downloading layers ({size_info})... {elapsed}s elapsed", spinning=True)
                return True
            self._pull_timer_id = GLib.timeout_add(1000, tick)

        def stop_pull_ticker():
            if self._pull_timer_id is not None:
                GLib.source_remove(self._pull_timer_id)
                self._pull_timer_id = None

        def worker():
            import pty, os as _os, select
            try:
                full_output = ""
                first_output = True
                if prefix == ["pkexec"]:
                    proc = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    for line in proc.stdout:
                        if first_output:
                            GLib.idle_add(self._set_status, "Running…", True)
                            first_output = False
                        full_output += line
                        GLib.idle_add(self._log, line)
                        m = re.search(r"layers needed:\s*\d+\s*\(([^)]+)\)", line)
                        if m:
                            GLib.idle_add(start_pull_ticker, m.group(1))
                        if "Deploying" in line:
                            GLib.idle_add(stop_pull_ticker)
                            GLib.idle_add(self._set_status, "Deploying...", True)
                    proc.wait()
                else:
                    master_fd, slave_fd = pty.openpty()
                    proc = subprocess.Popen(
                        cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, close_fds=True)
                    _os.close(slave_fd)
                    buf = b""
                    while True:
                        try:
                            r, _, _ = select.select([master_fd], [], [], 0.1)
                        except (ValueError, OSError):
                            break
                        if r:
                            try:
                                chunk = _os.read(master_fd, 4096)
                                if not chunk:
                                    break
                                buf += chunk
                                text = buf.decode("utf-8", errors="replace")
                                buf = b""
                                if first_output:
                                    GLib.idle_add(self._set_status, "Running…", True)
                                    first_output = False
                                full_output += text
                                GLib.idle_add(self._log, text)
                                m = re.search(r"layers needed:\s*\d+\s*\(([^)]+)\)", text)
                                if m:
                                    GLib.idle_add(start_pull_ticker, m.group(1))
                                if "Deploying" in text:
                                    GLib.idle_add(stop_pull_ticker)
                                    GLib.idle_add(self._set_status, "Deploying...", True)
                            except OSError:
                                break
                        elif proc.poll() is not None:
                            break
                    try:
                        _os.close(master_fd)
                    except OSError:
                        pass
                    proc.wait()

                GLib.idle_add(stop_pull_ticker)
                if proc.returncode == 0:
                    if "No update available." in full_output:
                        msg = "No update available — image is already up to date."
                        GLib.idle_add(self._log, f"\n{msg}\n")
                        GLib.idle_add(self._set_status, msg)
                    else:
                        GLib.idle_add(self._log, f"\n{success_msg}\n")
                        GLib.idle_add(self._set_status, success_msg)
                        GLib.idle_add(self._offer_reboot)
                else:
                    GLib.idle_add(self._log, f"\nCommand failed (exit {proc.returncode})\n")
                    GLib.idle_add(self._set_status, f"Failed (exit {proc.returncode})")
            except Exception as e:
                GLib.idle_add(stop_pull_ticker)
                GLib.idle_add(self._log, f"\nError: {e}\n")

        threading.Thread(target=worker, daemon=True).start()

    def _offer_reboot(self):
        win = self.get_root()
        dlg = Gtk.MessageDialog(
            transient_for=win, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Reboot now?",
            secondary_text="The new image is staged. A reboot is required to apply it."
        )
        def on_response(d, response):
            d.close()
            if response == Gtk.ResponseType.YES:
                subprocess.Popen(["systemctl", "reboot"])
        dlg.connect("response", on_response)
        dlg.present()

    def _set_status(self, text: str, spinning: bool = False):
        self.status_lbl.set_text(text)
        if spinning:
            self.status_spinner.start()
        else:
            self.status_spinner.stop()

    def _log(self, text: str):
        self.log_buffer.insert(self.log_buffer.get_end_iter(), text)
        # Scroll the log's own inner ScrolledWindow to follow output
        self.log_view.scroll_to_iter(self.log_buffer.get_end_iter(), 0.0, False, 0, 0)
        # Also scroll the outer page ScrolledWindow so the status bar and
        # deploy button stay visible as the log grows
        if self._outer_scroll:
            adj = self._outer_scroll.get_vadjustment()
            adj.set_value(adj.get_upper())


# =============================================================================
#  Wizard window
# =============================================================================
class WizardWindow(Gtk.ApplicationWindow):
    STEPS = [
        ("Base Image",   "1"),
        ("Repositories", "2"),
        ("Packages",     "3"),
        ("Performance",  "4"),
        ("Systemd",      "5"),
        ("Review",       "6"),
        ("Build",        "7"),
    ]

    def __init__(self, app):
        super().__init__(application=app, title="Atomic Image Wizard")
        self.set_default_size(1100, 800)
        self.maximize()
        self.state = WizardState()

        # ── Detect existing Containerfile ─────────────────────────────────
        cf_path = os.path.join(SCRIPT_DIR, "Containerfile")
        self._has_landing = os.path.exists(cf_path)

        page_build  = PageBuild(self.state, app)
        page_review = PageReview(self.state, page_build)

        # Wizard pages — indices are stable regardless of landing presence
        wizard_pages = [
            PageBase(self.state),        # 0 in wizard = index BASE_IDX overall
            PageRepos(self.state),
            PagePackages(self.state),
            PagePerformance(self.state),
            PageSystemd(self.state),
            page_review,
            page_build,
        ]

        if self._has_landing:
            self.pages = [PageLanding(self.state, cf_path)] + wizard_pages
            self.LANDING_IDX = 0
            self.BASE_IDX    = 1
            self.REPOS_IDX   = 2
            self.REVIEW_IDX  = 6
            self.current     = 0   # start on landing page
        else:
            self.pages       = wizard_pages
            self.LANDING_IDX = None
            self.BASE_IDX    = 0
            self.REPOS_IDX   = 1
            self.REVIEW_IDX  = 5
            self.current     = 0   # start on base image page

        # ── Header bar ────────────────────────────────────────────────────
        hb = Gtk.HeaderBar()
        self.step_label = Gtk.Label()
        self.step_label.set_markup("<b>Atomic Image Wizard</b>")
        hb.set_title_widget(self.step_label)
        self.back_btn = Gtk.Button(label="Back")
        self.back_btn.connect("clicked", self._go_back)
        self.next_btn = Gtk.Button(label="Next")
        self.next_btn.add_css_class("suggested-action")
        self.next_btn.connect("clicked", self._go_next)
        hb.pack_start(self.back_btn)
        hb.pack_end(self.next_btn)
        self.set_titlebar(hb)

        # ── Root layout ───────────────────────────────────────────────────
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.set_child(root)

        # Sidebar — hidden on landing page
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.sidebar.set_size_request(185, -1)
        self.sidebar.set_hexpand(False)
        self.sidebar.set_vexpand(True)
        set_margins(self.sidebar, top=12, bottom=12, start=8, end=8)

        sidebar_title = Gtk.Label()
        sidebar_title.set_markup("<b>Steps</b>")
        sidebar_title.set_margin_bottom(4)
        self.sidebar.append(sidebar_title)

        # Start button — returns to landing page (if present) or Step 1
        self.start_btn = Gtk.Button(label="⟵  Start")
        self.start_btn.set_has_frame(False)
        self.start_btn.set_hexpand(True)
        self.start_btn.connect("clicked", self._go_start)
        self.sidebar.append(self.start_btn)

        sep = Gtk.Separator()
        sep.set_margin_top(4)
        sep.set_margin_bottom(6)
        self.sidebar.append(sep)

        self.step_btns = []
        for i, (name, num) in enumerate(self.STEPS):
            btn = Gtk.Button(label=f"{num}.  {name}")
            btn.set_has_frame(False)
            btn.set_hexpand(True)
            btn.connect("clicked", self._on_step_btn, i)
            self.sidebar.append(btn)
            self.step_btns.append(btn)

        self.sidebar_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        root.append(self.sidebar)
        root.append(self.sidebar_sep)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.set_hexpand(True)
        content.set_vexpand(True)
        root.append(content)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        for i, page in enumerate(self.pages):
            self.stack.add_named(page, str(i))

        self.outer_scroll = Gtk.ScrolledWindow()
        self.outer_scroll.set_hexpand(True)
        self.outer_scroll.set_vexpand(True)
        self.outer_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.outer_scroll.set_child(self.stack)
        content.append(self.outer_scroll)

        page_build._outer_scroll = self.outer_scroll

        self._update_ui()

    def jump_to_page(self, index: int):
        self.current = max(0, min(index, len(self.pages) - 1))
        self._update_ui()

    def go_to_build(self):
        self.current = len(self.pages) - 1
        self._update_ui()

    def _go_start(self, *_):
        """Return to the landing page if one exists, otherwise go to Step 1."""
        self.current = self.LANDING_IDX if self._has_landing else self.BASE_IDX
        self._update_ui()

    def _on_step_btn(self, _btn, index):
        # Sidebar buttons use wizard-step indices — offset by 1 if landing present
        target = index + (1 if self._has_landing else 0)
        self.current = target
        self._update_ui()

    def _go_back(self, *_):
        if self.current > 0:
            self.current -= 1
            self._update_ui()

    def _go_next(self, *_):
        if self.current >= len(self.pages) - 1:
            self.close()
            return
        self.current += 1
        self._update_ui()

    def _update_ui(self):
        page = self.pages[self.current]
        if hasattr(page, "on_enter"):
            page.on_enter()
        self.stack.set_visible_child_name(str(self.current))
        self.outer_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        on_landing = self._has_landing and self.current == self.LANDING_IDX

        # Hide sidebar and nav buttons on the landing page
        self.sidebar.set_visible(not on_landing)
        self.sidebar_sep.set_visible(not on_landing)
        self.back_btn.set_visible(not on_landing)
        self.next_btn.set_visible(not on_landing)

        # Start button only makes sense when there is a landing page to go back to
        self.start_btn.set_visible(self._has_landing)

        if on_landing:
            self.step_label.set_markup("<b>Atomic Image Wizard</b>")
            return

        # Work out which wizard step we're on (0-based within wizard pages)
        wizard_idx = self.current - (1 if self._has_landing else 0)
        name = self.STEPS[wizard_idx][0]
        num  = self.STEPS[wizard_idx][1]
        self.step_label.set_markup(
            f"<b>Atomic Image Wizard</b>  —  Step {num}: {GLib.markup_escape_text(name)}"
        )
        self.back_btn.set_sensitive(self.current > (1 if self._has_landing else 0))

        review_idx = len(self.pages) - 2
        build_idx  = len(self.pages) - 1
        on_action_page = self.current in (review_idx, build_idx)
        self.next_btn.set_visible(not on_action_page)
        if not on_action_page:
            self.next_btn.set_label("Next")
            self.next_btn.set_sensitive(True)

        for i, btn in enumerate(self.step_btns):
            if i == wizard_idx:
                btn.add_css_class("suggested-action")
            else:
                btn.remove_css_class("suggested-action")


# =============================================================================
#  Application
# =============================================================================
class WizardApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.example.atomicimagewizard")

    def do_activate(self):
        win = WizardWindow(self)
        win.present()


if __name__ == "__main__":
    app = WizardApp()
    sys.exit(app.run(sys.argv))
