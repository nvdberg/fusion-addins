NM Joinery - Fusion add-in (version 0.7.0)
==========================================
CNC-aware box finger joints, tab & slot and mortise & tenon joints.
Each joint is an editable feature in the timeline: double-click it to change it.

INSTALL (Mac or Windows)
1. Unzip. You get a folder called "NMJoinery". Put it somewhere it can stay
   (for example Documents/Fusion Add-Ins/NMJoinery).
2. In Fusion: Utilities tab > ADD-INS > Scripts and Add-Ins (or press Shift+S).
3. Open the "Add-Ins" tab, click the "+" (green plus) and choose the NMJoinery folder.
4. Select "NMJoinery" in the list, click Run, and tick "Run on Startup".
   New buttons: "NM Joint" under SOLID > MODIFY, "NM Drawer", "NM Cabinet" and "NM Lay Flat"
   under SOLID > CREATE.

USE
- SOLID > MODIFY > NM Joint. Select 2 or more boards (solid bodies).
  Every pair that overlaps or touches gets a joint, so a whole box can be done in one go:
    - boards that overlap at a corner  -> finger joint
    - a board end touching a face      -> tabs & slots, or mortise & tenon (Joint dropdown)
- Hover over any setting for a short explanation. "0" means automatic.
- Double-click a joint in the timeline to edit it; the box at the bottom shows the actual sizes.
- Corners can be plain, dogbone or T-bone (T-bone = the relief runs along the edge, less visible).

NM DRAWER (SOLID > CREATE > NM Drawer)
- One dialog builds a whole drawer or box: the boards, the parameters and the joints.
- Sizes are outside sizes. Sides run full depth, or front/back run full width (Layout).
- Bottom: finger-jointed into the sides, or a loose panel in a groove.
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

NM CABINET (SOLID > CREATE > NM Cabinet)  - new in 0.7.0, first version
- One dialog builds a whole frameless cabinet: sides, bottom, top, back, base and what goes inside,
  with tab joints between the carcass boards and the back in a groove.
- Base: toe kick notched into the sides, a separate plinth, or none (wall cabinet, legs).
- Top: a full panel, or two stretchers (front and back) to go under a counter top.
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
- Pick boards: you get a copy of each one laid flat, inside face up, long side along X,
  in a new component next to the model. Use that component for CAM.
- The copies follow every size change of the boards. Double-click the feature to change the spacing.

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
(github.com/nvdberg/fusion-addins/releases). If there is one, it asks once whether to open the
download page. Only the public release list is read, nothing is sent, no account needed.
To update: Scripts and Add-Ins > NMJoinery > Stop, replace the NMJoinery folder with the new one
from the zip, then Run.

REMOVE
Scripts and Add-Ins > Add-Ins > NMJoinery > Stop, then untick Run on Startup or remove it from the list.
