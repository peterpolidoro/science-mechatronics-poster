;; guix/manifest.scm
;; Packages for supporting tools (Blender is intentionally *not* included here).
(use-modules (guix profiles)
             (guix packages)
             (guix utils))

(specifications->manifest
 (list
  "freecad"
  "kicad"
  "gimp"
  ;; Handy utilities for image and file manipulation
  "imagemagick"
  "inkscape"
  "zip"
  "git"
  ))
