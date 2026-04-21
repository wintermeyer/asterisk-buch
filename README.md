# Das Asterisk-Buch

Antora source for _Das Asterisk-Buch_ by Stefan Wintermeyer. 
The prose is German. Content lives under
`modules/ROOT/pages/*.adoc`; navigation is declared in
`modules/ROOT/nav.adoc`.

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

## Editing

All prose lives in `modules/ROOT/pages/`. Each chapter / section is a
single `.adoc` page, linked from `modules/ROOT/nav.adoc`. Images go in
`modules/ROOT/images/`.

Shell / CLI transcripts use `[source,bash]` (or `[source,shell]`) and
get the `terminal` CSS role automatically via the Asciidoctor extension
in `asciidoctor-extensions/terminal-role.js`.
