NM Joinery - Fusion add-in (version 0.8.1)
==========================================
CNC-aware box finger joints, tab & slot and mortise & tenon joints.
Each joint is an editable feature in the timeline: double-click it to change it.

INSTALL (Mac or Windows)
Easiest: double-click "Install on Mac.command" or "Install on Windows.cmd" (next to this file).
It copies the add-in into Fusion's own add-in folder; restart Fusion and it starts by itself.
(The first time, a Mac may say the file is from the internet: System Settings > Privacy &
Security > Open Anyway. Windows: More info > Run anyway.)
Or without the zip, one line in Terminal (Mac) or PowerShell (Windows):
  curl -fsSL https://raw.githubusercontent.com/nvdberg/fusion-addins/main/install-mac.sh | bash
  irm https://raw.githubusercontent.com/nvdberg/fusion-addins/main/install-windows.ps1 | iex
Illustrated guide: https://nvdberg.github.io/fusion-addins/

By hand instead:
1. Unzip. You get a folder called "NMJoinery". Put it somewhere it can stay
   (for example Documents/Fusion Add-Ins/NMJoinery).
2. In Fusion: Utilities tab > ADD-INS > Scripts and Add-Ins (or press Shift+S).
3. Click "+" > "Script or add-in from device" and choose the NMJoinery folder.
   (Older Fusion: the "Add-Ins" tab, green plus.)
4. Switch its Run toggle on and tick "Run on Startup".
New buttons: "NM Joint" under SOLID > MODIFY; "NM Lay Flat", "NM Drawer", "NM Cabinet" and
"NM Cut List" under SOLID > CREATE.

USE
- SOLID > MODIFY > NM Joint. Select 2 or more boards (solid bodies).
  Every pair that overlaps or touches gets a joint, so a whole box can be done in one go:
    - boards that overlap at a corner  -> finger joint
    - a board end touching a face      -> tabs & slots, or mortise & tenon (Joint dropdown)
- Hover over any setting for a short explanation. "0" means automatic.
- Double-click a joint in the timeline to edit it; the box at the bottom shows the actual sizes.
- Size by: "x board thickness" (finger / tab width = a multiple of the board, default 2),
  "Count per side" or "Fixed width". NM Drawer and NM Cabinet have the same "Finger x board".
- A whole box made by NM Drawer / Cabinet is one NM Joint feature. Double-click it to change one
  joint, several, or all: tick them (or Tick > All joints, Corners, Every joint of Bottom ...),
  change a setting and only the ticked joints change. "Make all like the one shown" copies every
  setting of the shown joint to the other ticked ones. While the dialog is open the ticked joints
  light up in the model: blue = the joint the fields show (the one most ticked joints are like),
  yellow = the other ticked joints. (While the dialog is open the boards show without this
  feature's joints: Fusion shows the model as it was before the feature.)
  Rebuilding a drawer or cabinet keeps these per-joint changes.
- Corners can be plain, dogbone or T-bone (T-bone = the relief runs along the edge, less visible).

NM DRAWER (SOLID > CREATE > NM Drawer)
- One dialog builds a whole drawer or box: the boards, the parameters and the joints.
- Sizes are outside sizes. Sides run full depth, or front/back run full width (Layout).
- Bottom: between the 4 walls, or a loose panel in a groove.
- Joints: finger joints (CNC), or None = plain panels that butt against each other, to join with a
  Domino, dowels or screws (no CNC needed). The sizes are the same either way.
- Units (top of the dialog, also in NM Cabinet): mm or inches. A plain number you type is in
  these units (Units = inch: 16 means 16"); type the unit to use the other one (300mm or 17.75 in).
  Switching converts every plain size. Parameters keep what the dialog shows.
- OK greyed out? The red line under Units says why (e.g. a size too small for the boards).
- Options: a top (closed box), dividers in dados, a finger pull or hand hole in the front,
  a false front with screw holes, and "Lay flat" (see below).
- Dividers: any number front-to-back and/or left-to-right (a sorting grid). Where they cross they
  half-lap (one notched from the top, the other from the bottom) with the same corner choice as the
  joints (dogbones / T-bones). Stock 1/2" (12 mm) or 1/4" (6 mm) ply: for thin dividers the dados
  and notches are cut as wide as the bit (nmj_bit), since a 1/4" bit can't cut a 6.3 mm slot.
- Presets (top of the dialog): type a name under "Save as" and click Save to keep the whole setup
  (e.g. "Kitchen drawer", "Screw sorter"); pick it from the Preset list next time to fill in every
  field. Saving under the same name updates it; "Delete picked" removes one. "Defaults (built in)"
  puts the add-in's own starting values back. Presets are kept in nm_drawer_presets.json in the
  add-in folder.
- Size from a cabinet opening (Size from: "Cabinet opening + slides"): type the opening width,
  height and depth and pick the slides. The box is the opening minus the slide gap on each side,
  minus the gaps above and below; its depth is the slide length (the longest one that fits the
  opening is picked for you). Lee Valley 61080 soft-close side-mount slides are built in: 12.7 to
  13.5 mm per side, at least 6.4 mm under the drawer, 450/500/550/600 mm, 1 13/16" high.
  Slide position: "Centred on the sides" (default: top of the slide = half the box height + half
  the slide height, and it follows when the box changes) or "Typed" (Lee Valley's sheet uses
  44 mm up). The result message says where both slide members go: the drawer line up from the
  bottom of the box sides (5.2 mm back) and the cabinet line up from the opening bottom
  (= gap below + drawer line, 2 mm back). "Other side-mount" lets you type any gap. The opening sizes become parameters too (drawer_ow, ...).
  "Mark slide lines" (on by default) cuts a shallow groove, 0.5 mm deep and 1 mm high, into the
  outside of both sides with its top edge on the drawer slide line, from the setback to as far
  from the back. It sits under the slide, so it doesn't show; it is in the Lay Flat copy too.
  Cut it with a V-bit or engraving pass, or set drawer_smw to your bit width (e.g. 6.35 mm).
- Bank of drawers (opening mode, "Drawers" more than 1): one opening, several drawers stacked
  with nothing between them. Heights "All the same" or "Graduated" (each drawer taller than the
  one above by "Taller by"). Each drawer gets its share of the opening and its own slides; the
  message lists, per drawer, its box height and where its cabinet slide goes (up from the
  opening bottom). With false fronts on, the fronts cover the whole opening with a "Reveal" gap
  between them (default 3 mm). Parameters: bank_* for the whole bank (bank_oh, bank_step,
  bank_t, bank_rev ...), bank_d1_*, bank_d2_* for each drawer. Change bank_oh or bank_step and
  every drawer follows. Each drawer gets its own Lay Flat copy, side by side.
- Every size becomes a design parameter with the box's name in front (e.g. drawer_w, drawer_h,
  drawer_t). Change them in Modify > Change Parameters and the whole box, joints included, follows.

NM CABINET (SOLID > CREATE > NM Cabinet)
- One dialog builds a whole frameless cabinet: sides, bottom, top, back, base and what goes inside,
  with tab joints between the carcass boards and the back in a groove.
- Joints: tab joints (CNC), or None = plain panels for a Domino, dowels or screws. With None the
  top (or the stretchers) sits on top of the sides and the bottom under them, both full width, so
  a load on top rests on the sides, not on the joints. (With a toe kick notched into the sides,
  the sides run to the floor and the bottom stays between them.) Shelves and the kick board sit
  between the sides. The drawers follow the same choice.
- Base: toe kick notched into the sides, a separate plinth, or none (wall cabinet, legs).
- Top: a full panel, or two stretchers (front and back) to go under a counter top.
- Back: a thin panel (1/4" ply) in a groove, set in from the back edge; or a solid board
  (default the board thickness) between the sides, top and bottom, flush with the back edges,
  tabbed in with tab joints. With stretchers, the back stretcher then sits on the solid back.
- Hanging rails (grooved back, optional): two rails inside at the back, one under the top and
  one on the bottom, board thickness, flush with the back edge, for screwing the cabinet to the
  wall. The grooved back then sits right in front of them. Rail height in the dialog (90 mm).
- Sections (1 to 4, top to bottom), with a fixed shelf between them. Each one holds:
    Drawers       a bank of drawers (NM Drawer) with Lee Valley slides (default), another
                  side-mount slide, or no slides. Heights all the same or graduated.
    Doors         overlay doors over the section: one, two, or Auto (two when wider than 600 mm),
                  with shelves behind them.
    Open shelves  fixed shelves (tabbed into the sides) or loose ones on 5 mm shelf pins
                  (32 mm hole rows, 37 mm from the front and back; a loose shelf sits on the
                  nearest row).
  Type the height of every section but the bottom one; the bottom one gets what is left.
- Doors and drawer fronts cover the carcass edges with a gap between them ("Gap between").
- Every size is a parameter (<name>_w, <name>_h, <name>_d, <name>_s1 ...): change the width or
  depth in Change Parameters and the boards, drawers and fronts follow.
- Lay flat: one flat copy of the carcass and one per drawer, side by side, for CAM.
- Not yet: hinge holes, face frame, wooden runners for drawers without slides.

NM LAY FLAT (SOLID > CREATE > NM Lay Flat)
- Pick boards, or whole components (a cabinet, a drawer): you get a copy of each board laid flat,
  inside face up, long side along X, in a new component next to the model. Use that component for CAM.
- Layout "In a row": the boards one after the other.
- Layout "Nested on sheets": the boards are packed on sheets, one row of sheets per thickness.
  - Sheet: 4 x 8 ft, 5 x 5 ft Baltic birch, 4 x 4 ft, 2 x 4 ft, 2440 x 1220, 2500 x 1250 mm, or Custom size.
  - Bit: the spacing becomes the bit diameter + 2 mm (1/4" bit -> 8.35 mm). Pick "Minimum distance"
    (or just type in Spacing) to set your own distance.
  - Edge margin: kept free along every sheet edge (default 10 mm).
  - Turn boards 90 deg: off = the long side (grain) stays along the sheet length.
  - Leftovers first: pieces you have lying around, used before new sheets, e.g.
    600 x 900; 450 x 1200 x 18   (length x width [x thickness], plain numbers are mm, 24 in x 30 in works).
    Without a thickness a piece can take boards of any thickness (once).
  - Each sheet / leftover is a see-through body "Sheet 1 - 18 mm" under the boards: in CAM pick it as
    stock (Setup > Stock > From solid). Outlines count as rectangles (fingers included).
- The copies follow every size change of the boards (re-nested). Double-click the feature to change
  the layout, sheet, bit, leftovers or spacing.

NM CUT LIST (SOLID > CREATE > NM Cut List)
- A list of every board: part names, quantity, length x width x thickness. Boards of the same
  size in the same component are counted together (Left, Right x 2).
- Pick a cabinet, a drawer or single boards, or nothing for the whole design. Hidden boards
  and Lay Flat copies are left out.
- The size is the blank you cut: fingers and tabs included, length = the longest side.
- Units mm or inch (inch to the nearest 1/32"). Per thickness: the total area and a rough
  sheet count (4 x 8 ft or 5 x 5 ft; area + 15 %, not a nesting).
- Save CSV writes it as a file for Excel, Numbers or Google Sheets.

CLEARANCE (how tight the joint is)
- Gap = clearance per side, default 0.1 mm.
- Global ticked = the joint uses the design parameter nmj_gap. Change nmj_gap in
  Modify > Change Parameters to loosen or tighten every joint at once.
- Change the Gap number on one joint to set that joint on its own.
- Cut a test joint first: too tight -> bigger gap (0.15-0.2 mm), too loose -> smaller.
- The cutter size is nmj_bit (default 1/4" = 6.35 mm); Corners = Dogbones lets a round bit
  make square inside corners.

UPDATES
A while after Fusion starts, the add-in looks on GitHub for a newer version
(github.com/nvdberg/fusion-addins/releases). If there is one it asks:
  Yes = install it now (downloads it, replaces its own files, keeps your presets and last
        settings), then restart Fusion.   No = skip this version.   Cancel = ask next time.
Only the public releases are read, nothing is sent, no account needed.
This works when the add-in was put in by the installer (Fusion's own add-in folder). Added by
hand from another folder: it offers the download page instead; run the installer from the new
zip, or Stop, copy the new files over the old ones (keep nm_drawer_presets.json), and Run.

REMOVE
Scripts and Add-Ins > NMJoinery > Run off, untick Run on Startup. Then quit Fusion and delete the
NMJoinery folder (installer: Mac ~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns,
Windows %APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns).
