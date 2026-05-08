#import "@preview/fletcher:0.5.8" as fletcher: diagram, edge, node

#let vm-box(title, location, gpu) = align(center)[
  #text(weight: "bold", size: 8pt)[#title] \
  #text(size: 7pt, fill: rgb("#444"))[#location] \
  #text(size: 6pt, fill: rgb("#888"))[#gpu]
]

#let hop-label(n, vuln) = align(center)[
  #text(size: 6.5pt, weight: "bold")[Hop #n] \
  #text(size: 6pt, fill: rgb("#555"))[#vuln]
]

#block(inset: (top: 6pt, bottom: 4pt), diagram(
  spacing: (18mm, 0mm),
  node-stroke: 0.7pt + rgb("#444"),
  edge-stroke: 1.2pt + rgb("#3a76ac"),

  node(
    (0, 0),
    vm-box("VM1 (host)", [Canada], [A100]),
    shape: rect,
    width: 26mm,
    fill: rgb("#ddeef6"),
    corner-radius: 3pt,
    name: <vm1>,
  ),

  node(
    (1, 0),
    vm-box("VM2", [US], [A100]),
    shape: rect,
    width: 26mm,
    fill: rgb("#ddeef6"),
    corner-radius: 3pt,
    name: <vm2>,
  ),

  node(
    (2, 0),
    vm-box("VM3", [Finland], [A100]),
    shape: rect,
    width: 26mm,
    fill: rgb("#ddeef6"),
    corner-radius: 3pt,
    name: <vm3>,
  ),

  node(
    (3, 0),
    vm-box("VM4", [India], [H100]),
    shape: rect,
    width: 26mm,
    fill: rgb("#ddeef6"),
    corner-radius: 3pt,
    name: <vm4>,
  ),

  edge(<vm1>, <vm2>, hop-label(1, [authentication bypass]), "->", label-side: left, label-sep: 5pt),
  edge(<vm2>, <vm3>, hop-label(2, [SSTI]), "->", label-side: left, label-sep: 5pt),
  edge(<vm3>, <vm4>, hop-label(3, [SQL injection]), "->", label-side: left, label-sep: 5pt),
))
