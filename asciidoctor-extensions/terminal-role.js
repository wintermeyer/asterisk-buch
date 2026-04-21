'use strict'

// Tree processor that tags shell/REPL listing blocks with the `terminal`
// CSS role so the UI can render them as a terminal window. A block is
// considered a terminal transcript when any of its non-empty lines starts
// with a common prompt: `$`, `#`, `>>`, `*CLI>`, `debian:`, `asterisk*CLI>`.

module.exports = function register (registry) {
  registry.treeProcessor(function () {
    const self = this
    self.process(function (doc) {
      const blocks = doc.findBy({ context: 'listing' })
      const PROMPT = /^\s*(\$|#|>>|\*CLI>|asterisk\*CLI>|[\w-]+(:[\w\/.~-]*)?[#$]|CLI>)/
      blocks.forEach(function (b) {
        const lines = b.getSource().split(/\r?\n/).filter(function (l) { return l.trim().length })
        if (!lines.length) return
        const hits = lines.filter(function (l) { return PROMPT.test(l) }).length
        if (hits / lines.length >= 0.25) {
          const roles = (b.getAttribute('role') || '').split(/\s+/).filter(Boolean)
          if (roles.indexOf('terminal') === -1) roles.push('terminal')
          b.setAttribute('role', roles.join(' '))
        }
      })
      return doc
    })
  })
}
