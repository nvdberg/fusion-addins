# Fusion add-ins for CNC woodworking (NM Woodworks)

Two free add-ins for Autodesk Fusion, made for a hobby CNC router.

| Add-in | What it does | Where in Fusion |
|---|---|---|
| **NMJoinery** | Finger joints, tab & slot and mortise & tenon between boards, as editable timeline features with dogbones / T-bones for your bit. Also **NM Drawer** (a whole drawer or bank of drawers in one dialog, with a drawer face inset or overlay), **NM Cabinet** (a whole frameless cabinet with drawers, doors and shelves) and **NM Lay Flat** (flat copies of the boards for CAM). | Solid > Modify > NM Joint; Solid > Create |
| **RotaryUnwrap** | Flatten for Rotary: unrolls a round part into a flat strip for normal 3-axis toolpaths, plus `wrap_y_to_a.py` that turns the posted program into rotary (A-axis) moves. Made for an Avid CNC rotary with Mach4. | Solid > Modify > Flatten for Rotary |

## Install (Mac or Windows)

One line downloads the newest version into Fusion's own add-in folder. Fusion then starts it by itself.
Run the same line again to update; your presets and last settings are kept.

**Mac** (Terminal):
```
curl -fsSL https://raw.githubusercontent.com/nvdberg/fusion-addins/main/install-mac.sh | bash
```

**Windows** (PowerShell):
```
irm https://raw.githubusercontent.com/nvdberg/fusion-addins/main/install-windows.ps1 | iex
```

Then restart Fusion. For RotaryUnwrap put its name after the Mac line (`... | bash -s RotaryUnwrap`).

Rather not use a terminal? Get the zip from **[Releases](https://github.com/nvdberg/fusion-addins/releases)**
(under *Assets*, not the green Code button), unzip it and double-click **Install on Mac.command** or
**Install on Windows.cmd**. By hand: Shift+S > **+** > *Script or add-in from device* > pick the
add-in folder, then switch **Run** on and tick **Run on Startup**.

**[The illustrated guide](https://nvdberg.github.io/fusion-addins/)** shows every step and every NMJoinery
feature. The full notes are in `NMJoinery-README.txt` and `RotaryUnwrap-README.txt` (also in each zip).

## Updates

A while after Fusion starts, each add-in looks here for a newer release. If there is one it asks
whether to install it: **Yes** downloads it and replaces its own files (your presets and settings
stay), then restart Fusion. This works from NMJoinery 0.8.0 / RotaryUnwrap 0.1.2 on, when the add-in
was put in by the installer. It only reads the public releases; nothing is sent and no account is
needed. Running the install line again always works too.

## Note

Free to use, no warranty. Always air-cut a new program first.

## License

Free to use for anything, including in commercial software: copy it, change it, rename it, sell it. No credit needed.
License: [0BSD](LICENSE) (Zero-Clause BSD).
