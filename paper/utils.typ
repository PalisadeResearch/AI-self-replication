#let hide-old-suggestions = false

#let suggest(..args) = context {
  if hide-old-suggestions {
    text(args.pos().at(-1))
  } else {
    let versions = args.pos()
    let count = versions.len()

    if count == 0 {
      text("")
    } else if count == 1 {
      text(fill: rgb("#28a745"), versions.at(0))
    } else {
      let colors = (
        rgb(100, 53, 69),
        rgb(140, 53, 69),
        rgb(180, 53, 69),
        rgb(220, 53, 69),
        rgb(40, 167, 69),
      )
      let result = none
      for (i, version) in versions.enumerate() {
        let color_position = colors.len() - count + i
        let color_index = if color_position < 0 { 0 } else { color_position }
        let color = colors.at(color_index)
        let prefix = if count <= 2 { "" } else { "v" + str(i + 1) + ": " }
        if i < count - 1 {
          result = (
            result + text(fill: color, strike(prefix + version)) + h(0.2em)
          )
        } else {
          result = result + text(fill: color, prefix + version)
        }
      }
      result
    }
  }
}

#let prompt-block(body) = block(
  fill: rgb("#f8f9fa"),
  inset: 12pt,
  radius: 4pt,
  width: 100%,
  [
    #show raw: set text(font: "DejaVu Sans Mono", size: 8pt)
    #body
  ],
)
