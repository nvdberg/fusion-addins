Rotary Unwrap - Fusion add-in (version 0.1.2)
=============================================
Fusion's real rotary toolpaths need the paid Machining Extension. This is the free way round:
draw/model the round part, flatten it, make normal 3-axis toolpaths on the flat strip,
post with your normal post, then wrap the program onto the rotary with wrap_y_to_a.py.

INSTALL (Mac or Windows)
Easiest: double-click "Install on Mac.command" or "Install on Windows.cmd" (next to this file).
It copies the add-in into Fusion's own add-in folder; restart Fusion and it starts by itself.
(The first time, a Mac may say the file is from the internet: System Settings > Privacy &
Security > Open Anyway. Windows: More info > Run anyway.)
Or on a Mac without the zip, in Terminal:
  curl -fsSL https://raw.githubusercontent.com/nvdberg/fusion-addins/main/install-mac.sh | bash -s RotaryUnwrap
By hand instead:
1. Unzip. Put the "RotaryUnwrap" folder somewhere it can stay.
2. In Fusion: Shift+S (Scripts and Add-Ins) > "+" > "Script or add-in from device" > choose the
   RotaryUnwrap folder. (Older Fusion: Add-Ins tab, green plus.)
3. Switch its Run toggle on and tick "Run on Startup". The button "Flatten for Rotary" appears
   under SOLID > MODIFY.

USE
1. SOLID > MODIFY > Flatten for Rotary, pick the round part and enter the blank diameter.
   You get a new component "Flat D=..." with an outline sketch and a relief mesh.
   Flat layout: X along the axis, Y0 = centre line (top of the part at A=0), Z0 = top of the blank.
2. CAM setup on the flat component (WCS on the top face, X0 at the end, Y0 on the centre line).
   Post with your normal 3-axis post (Avid CNC post).
3. Wrap it (needs Python 3):
     python3 wrap_y_to_a.py MyPart.tap --diameter 2in
   Writes MyPart_A.tap next to it. Use the same diameter as in step 1.
   Options: --reverse (flip A if the test comes out mirrored), --zero axis (Fusion Z0 already on
   the axis), -o OUTFILE. Arcs must be I/J/K (the Avid post default).

Made for an Avid CNC rotary (A about X) with Mach4: Y0 = rotation axis, Z0 on the axis.
ALWAYS air-cut a new file first and check it in a G-code viewer. No warranty.

UPDATES
A while after Fusion starts, the add-in looks on GitHub for a newer version
(github.com/nvdberg/fusion-addins/releases). If there is one it asks: Yes = install it now
(then restart Fusion), No = skip this version, Cancel = ask next time. One-click install works
when the add-in was put in by the installer; otherwise it offers the download page.
Only the public releases are read, nothing is sent, no account needed.

REMOVE
Scripts and Add-Ins > Add-Ins > RotaryUnwrap > Stop, then untick Run on Startup or remove it.
