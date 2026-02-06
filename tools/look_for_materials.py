print("testing!")

import bpy

print("Current file:", bpy.data.filepath)

hits = []
for m in bpy.data.materials:
    if m.name.startswith("MAT_"):
        hits.append((m.name, "LINKED" if m.library else "LOCAL", m.users))

for row in sorted(hits):
    print(row)

print("Count MAT_*:", len(hits))

