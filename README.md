# Das Asterisk-Buch

Antora source for _Das Asterisk-Buch_ by Stefan Wintermeyer —
Evergreen-Ausgabe. The prose is German. Content lives under
`modules/ROOT/pages/*.adoc`; navigation is declared in
`modules/ROOT/nav.adoc`.

## Philosophie

This is an _evergreen_ edition of the book, deliberately not pinned
to a specific Asterisk version. Instead of freezing the content for
one release, it is maintained continuously:

- Core concepts (dialplan, contexts, channels, bridges, ARI ideas)
  are written to apply across versions.
- Version-specific details (e.g. "since Asterisk 21, `chan_sip` is
  gone") are explicitly flagged.
- For fast-moving reference material (complete lists of applications,
  functions, AMI/AGI commands), we link to the upstream docs at
  https://docs.asterisk.org rather than embedding stale snapshots.

The book covers PJSIP (not `chan_sip`), ConfBridge (not MeetMe),
ARI, WebRTC, modern security practices — everything that was missing
or obsolete in the previous edition.

## Build

```
npm install
npx antora --fetch antora-local-playbook.yml
```

The rendered site lands in `build/site/book/index.html`.

## Deployment

Push to `main` → the `.github/workflows/deploy.yml` workflow runs on a
self-hosted runner, which executes `scripts/deploy.sh`. Each release is
materialised under `/var/www/asterisk-buch/releases/<timestamp>/` and
the `current` symlink is swapped atomically. Nginx serves the site at
`/asterisk/book/`.

Before the swap the deploy pre-compresses every text asset
(`.html`, `.css`, `.js`, `.svg`, `.xml`, `.json`, `.mjs`, `.txt`,
`.map`) into `.br` (brotli q11) and `.gz` (gzip -9) siblings so
nginx's `brotli_static` / `gzip_static` can serve them with zero
CPU on the hot path.

## Editing

All prose lives in `modules/ROOT/pages/`. Each chapter / section is a
single `.adoc` page, linked from `modules/ROOT/nav.adoc`. Images go in
`modules/ROOT/images/`.

Shell / CLI transcripts use `[source,bash]` (or `[source,shell]`) and
get the `terminal` CSS role automatically via the Asciidoctor extension
in `asciidoctor-extensions/terminal-role.js`.

## Contributing

Pull requests welcome. For larger changes, please open an issue first
to discuss the direction. Feedback via email to
<sw@wintermeyer-consulting.de> also works.
