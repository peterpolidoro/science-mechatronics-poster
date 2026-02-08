# Context for Blender poster development — Park et al., *Neuron* (2025) “Conjoint specification of action by neocortex and striatum”

This file summarizes what we’ve extracted/confirmed so far from the uploaded paper PDF and the work completed in the prior chat, so you can continue in a new chat without re-deriving context.

---

## Paper identity (from the PDF)

- **Title:** Conjoint specification of action by neocortex and striatum  
- **Authors:** Junchol Park, Peter Polidoro, Catia Fortunato, Jon Arnold, Brett Mensh, Juan A. Gallego, Joshua T. Dudman  
- **Journal / date:** *Neuron* 113, 620–636; **February 19, 2025**  
- **Core idea:** Compare neural activity across **similar** actions (small parameter differences) to distinguish “selection” vs “specification” hypotheses; results support **conjoint specification** of movement parameters by **motor cortex (MOp)** and **dorsal striatum (dSTR)**.

---

## What we extracted from the PDF for downstream Blender/poster work

### A) All figure images extracted as PNGs (ready to use)

Files available in this workspace (same folder as this context file):

- `Figure_1.png` … `Figure_8.png`  
- `Figure_S1.png` … `Figure_S8.png`  
- `Table_S1.png`  
- Bundle: `extracted_figures_neuron2025.zip`

**Representative subset for “datasets generated” visuals** (covers behavior, neural recording, inactivation, histology, learning):
- Behavior + task apparatus: `Figure_2.png`
- Inactivation: `Figure_3.png`
- Neural population dynamics & inter-area models: `Figure_4.png`, `Figure_5.png`, `Figure_6.png`
- Learning/experience: `Figure_8.png`
- Histology (viral expression / probe track): `Figure_S4.png`

---

## B) Datasets (what the paper generates/uses) — practical grouping

### Dataset 1 — Behavioral task + kinematics/kinetics (Figure 2; Figure S2)
**Goal:** Quantify reach and pull behavior across **4 trial types** (2 target locations × 2 loads).

**Mechatronic/measurement streams**
- **Actuators:** two stepper-motor axes controlling joystick **yaw** and **pitch**; pitch motor current sets **load requirement**.
- **Sensors:** rotary encoder for joystick motion; two high-speed cameras for 3D kinematics.

**Key behavioral variables used**
- Trial type factors:
  - **Yaw target location:** +5° vs −15° (≈20 mm radial from hand rest)
  - **Required load/force:** 3 g vs 12 g (calibrated from pitch motor holding load)
- Observed/derived outcomes:
  - Pull distance/trajectory; success rate
  - Hand and joystick 3D trajectories (mm)
  - Initial hand position distribution
  - Reach angle
  - (Supplement) reaction time, reach duration, pull duration, reach-to-pull duration, speeds

### Dataset 2 — Behavioral task + simultaneous electrophysiology (Figures 4–6; S2–S3; S6–S7)
**Goal:** Relate neural activity to task parameters and continuous kinematics.
- Recorded from **MOp** and **dSTR** with a **384-channel Neuropixels probe** (and in some sessions **MOs/ACA** with a **64-channel silicon probe**).
- Variables include spike times/firing rates; population activity trajectories (PCA/GPFA/cPCA); decoder outputs.

### Dataset 3 — Optogenetic silencing sessions (Figure 3; Figure 4 panels on inactivation; Figure S4)
**Goal:** Test causal necessity of corticostriatal projections.
- Trial-by-trial **473 nm** laser silencing on ~25% of trials; behavioral reach probability and kinematics affected.

### Dataset 4 — Histology / anatomical verification (Figure S4)
**Goal:** Verify probe tracks and viral expression (e.g., GtACR2 expression; DiI-labeled tracks) using light-sheet imaging.

### Dataset 5 — Learning/novel-parameter sessions (Figure 8)
**Goal:** Examine how decoding performance and cortical contribution relate to experience when animals encounter novel load/location.

### Dataset 6 — Simulations (Figure 1; S1; S8)
**Goal:** Provide model predictions and interpret decoding contributions (not a hardware dataset).

---

## C) Transducers and software (manufacturer/model when explicitly given in the paper)

### Hardware transducers (set or measure task/neural variables)

**Actuators / outputs**
- **Stepper Motor 1:** Pololu product **1204** (used in joystick system)
- **Stepper Motor 2:** Pololu product **2267** (used in joystick system)
- **Auditory cue (tone):** present (device model not specified)
- **Near-infrared LED illumination:** present (model not specified)
- **473 nm laser for silencing:** present (model not specified)
- **Ambient blue masking light:** present (model not specified)
- **Water reward delivery (spout):** present (valve/pump not specified)

**Sensors / measurements**
- **Rotary encoder:** JTEKT Electronics **TRD‑MX1000AD**
- **Cameras (2×):** Teledyne FLIR **FL3‑U3‑13E4M‑C** (Flea3 USB3), with 6–15 mm f/1.4 lenses
- **Neural recording probes:** 384‑channel Neuropixels probe; 64‑channel silicon probe (vendor/model not specified in the paper text we reviewed)
- **Force gauge:** used to calibrate pitch motor holding load (model not specified)
- **Light-sheet microscope:** Zeiss **Lightsheet Z.1** (for cleared brain imaging)

### Host / analysis software explicitly referenced
- **Joystick experiment control (host code):** open-source Python package  
  `mouse_joystick_interface_python` (GitHub link provided in paper)
- **CAD for joystick apparatus:** Dropbox link provided in paper (“Mouse joystick apparatus parts (CAD)”)
- **Neural acquisition:** SpikeGLX
- **Spike sorting:** Kilosort + manual curation in Phy
- **3D kinematic extraction:** DeepLabCut + Camera Calibration Toolbox for Matlab + stereo triangulation
- Other analysis tools listed include MATLAB, FIJI/ImageJ, scikit-learn, cPCA/dPCA/GPFA codebases, etc.

### Data/code availability links (from paper)
- Central project page: lab Notion page (link provided in paper)
- FigShare: dataset DOI and analysis software DOI (both provided in paper)

---

## D) Figure 2 deep dive — what it depicts and how data are collected

### Figure 2 purpose
Figure 2 introduces the **robotic reach-to-pull task** and demonstrates a **double dissociation**:
- **Reach angle** varies primarily with **target location** (yaw)
- **Pull force** varies primarily with the **load requirement** (pitch motor “holding load” / force requirement)

### Trial structure and block design (as described in the paper)
- Joystick is robotically positioned to one of two yaw locations, rotated into graspable pitch angle.
- Mouse reaches to the correct yaw location, grabs joystick, pulls along pitch axis past a threshold (**5 mm**) to succeed.
- Four trial types: (yaw +5° or −15°) × (load 3 g or 12 g).
- Sessions include 8 blocks (2 repetitions of each of the 4 conditions).

### Figure 2: which transducers generate each main measurement

**Actuators set the task parameters**
- Yaw stepper motor sets **target location** (+5° / −15°).
- Pitch motor current sets **load requirement** (3 g / 12 g), calibrated using a force gauge.

**Sensors measure behavior**
- Rotary encoder measures joystick movement → infer pull distance/trajectory and detect success threshold crossing.
- Two cameras record synchronized views at **250 Hz** under NIR illumination.
  - DeepLabCut tracks 3 hand points (leftmost finger, rightmost finger, hand centroid) and 2 joystick points (top, middle).
  - Stereo triangulation reconstructs 3D trajectories (mm).

### Camera placement (as specified)
- Two cameras positioned **perpendicularly**:
  - one **in front** of the animal
  - one **to the right** of the animal  
(Exact coordinates/distances are not specified; only relative placement/orientation.)

### UI notes (what is / isn’t described)
- The paper does **not** describe a graphical user interface (GUI) in the text.
- It *does* state the system is controlled via an open-source Python package and points to GitHub/Notion resources for details.

---

## E) Variables inventory work completed earlier (for poster modeling)

### 1) Variables per figure, with “sensor-measured vs actuator-set”
- We produced a figure-by-figure table (Figures 2–8) listing variables and whether they are:
  - measured by sensors (cameras / rotary encoder / brain probe)
  - set by actuators (yaw position, load requirement)
- Figure 1 was excluded from that table because it is conceptual/simulation-only (no sensor-measured or actuator-set variables).

### 2) Which figures use actuator-set load/“torque” and/or actuator-set positions
- Load (force requirement) and/or target location appear across many figures because they define the 4 trial types:
  - **Load / pull-force axis:** Figures 2, 4, 5, 6, 7, 8
  - **Stepper-set position (target location) / joystick kinematics:** Figures 2, 3, 4, 5, 6, 7, 8  
(Important nuance: the paper expresses this as **force requirement / pull force** and **target location**; “torque” wording appears mainly in supplemental discussion/analysis.)

---

## F) Blender poster development pointers (practical)

### Physical scene elements to model (from Figure 2 + methods)
- Head-fixed mouse + right forelimb reaching volume
- Stainless-steel joystick with 2 DOF (pitch + yaw), stepper motor mounts, and rotary encoder on the stepper/shaft
- Hand rest location (for “~20 mm radially from hand rest” geometry)
- Two cameras:
  - camera 1: front view
  - camera 2: right-side view (orthogonal to front)
- NIR illuminator (can be simplified as an IR LED bar/light source)
- Optional: water spout for reward delivery; speaker for cue tone

### Data overlays for a poster
- Use the extracted `Figure_2.png` as the authoritative reference for:
  - axes labels (“lateral/outward”), reach trajectories, and panel layout
- If you want 3D kinematic overlays in Blender, the tracked points are:
  - hand: leftmost finger, rightmost finger, centroid
  - joystick: top, middle

---

## G) Open TODOs (good next steps in the new chat)
- Decide the Blender poster “storyboard”:
  - a single hero 3D render of apparatus + overlaid vectors/angles
  - or a panelized poster that mirrors Figure 2 A–H
- If you need CAD/3D assets:
  - pull the joystick CAD from the Dropbox link in the paper
  - check vendor pages for camera/encoder/motor CAD (STEP) as needed
- If you plan to re-create plots in Blender:
  - decide whether to use the FigShare dataset (paper provides DOI) vs. using the paper’s plotted values directly.

---

## Workspace file inventory (so you can refer to exact filenames)
- Paper PDF: `neuron-2025-extended.pdf`
- Figures: `Figure_1.png` … `Figure_8.png`
- Supplemental: `Figure_S1.png` … `Figure_S8.png`
- Supplemental table image: `Table_S1.png`
- Bundle: `extracted_figures_neuron2025.zip`
