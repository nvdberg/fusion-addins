# Fusion add-ins for CNC woodworking (NM Woodworks)

Two free add-ins for Autodesk Fusion, made for a hobby CNC router.

| Add-in | What it does | Where in Fusion |
|---|---|---|
| **NMJoinery** | Finger joints, tab & slot and mortise & tenon between boards, as editable timeline features with dogbones / T-bones for your bit. Also **NM Drawer** (a whole drawer or bank of drawers in one dialog), **NM Cabinet** (a whole frameless cabinet with drawers, doors and shelves) and **NM Lay Flat** (flat copies of the boards for CAM). | Solid > Modify > NM Joint; Solid > Create |
| **RotaryUnwrap** | Flatten for Rotary: unrolls a round part into a flat strip for normal 3-axis toolpaths, plus `wrap_y_to_a.py` that turns the posted program into rotary (A-axis) moves. Made for an Avid CNC rotary with Mach4. | Solid > Modify > Flatten for Rotary |

## Download

Get the zip from **[Releases](https://github.com/nvdberg/fusion-addins/releases)** (under *Assets*),
not the green Code button.

## Install (Mac or Windows)

1. Unzip and put the add-in folder (`NMJoinery` or `RotaryUnwrap`) somewhere it can stay.
2. In Fusion press **Shift+S** > **Add-Ins** tab > **+** > pick that folder.
3. Select it, click **Run**, tick **Run on Startup**.

The full notes are in `NMJoinery-README.txt` and `RotaryUnwrap-README.txt` (also in each zip).

## Updates

A while after Fusion starts, each add-in looks here for a newer release and asks once whether
to open the download page. It only reads the public release list; nothing is sent and no
account is needed. To update: Stop the add-in, replace its folder with the new one, Run.

## Note

Free to use, no warranty. Always air-cut a new program first.
