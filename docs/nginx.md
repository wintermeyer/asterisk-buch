# Nginx setup on bremen2 for `/asterisk/book/`

One-time setup. The Asterisk book deploy (see
[`scripts/deploy.sh`](../scripts/deploy.sh)) just refreshes
`/var/www/asterisk-buch/current/`; nginx has to be told to serve that
path under `/asterisk/book/` on the `wintermeyer-consulting.de` vhost.

## 1. Filesystem layout

Run as the deploy user that owns the site (the `eliph` user is the
simplest — it already owns the other book trees under `/var/www/`
and is the one the GitHub Actions runner executes as):

```sh
sudo mkdir -p /var/www/asterisk-buch/{releases,shared}
sudo chown -R eliph:eliph /var/www/asterisk-buch
```

## 2. Nginx location block

Add inside the existing `server { server_name wintermeyer-consulting.de; … }`
on bremen2 (beside the Rails and Phoenix book blocks). The trailing
slash on `alias` is required — without it, URLs like
`/asterisk/book/foo.html` resolve to the wrong filesystem path.

The deploy copies `build/site/` → `current/`, and Antora renders into
`build/site/book/`, so the actual HTML lives at
`/var/www/asterisk-buch/current/book/`.

```nginx
# Asterisk book — static Antora output rebuilt on every push to main.
location /asterisk/book/ {
    alias /var/www/asterisk-buch/current/book/;
    try_files $uri $uri/ /index.html;
    add_header Cache-Control "public, max-age=300";
}

location /asterisk/antora-assets/ {
    alias /var/www/asterisk-buch/current/antora-assets/;
    add_header Cache-Control "public, max-age=3600";
}

location = /asterisk/book {
    return 301 /asterisk/book/;
}
```

Keep these blocks *before* any wincon `location /` proxy block so the
static files win over the Phoenix upstream. `/asterisk` (no trailing
slash, no `/book`) stays proxied to wincon — that route is the
Asterisk landing page served by `WinconWeb.PageController`.

## 3. Reload

```sh
sudo nginx -t && sudo systemctl reload nginx
```

## 4. Smoke test

```sh
curl -I https://wintermeyer-consulting.de/asterisk/book/
curl -I https://wintermeyer-consulting.de/asterisk/book/dialplan.html
```

Both should return `HTTP/2 200` once the first deploy has populated
`current/`.

## Notes

- The first deploy will publish into `releases/<timestamp>/` and
  create `current` → that dir. Until the symlink exists, the location
  block will 404.
- If the eliph runner fails the deploy, roll back by pointing the
  symlink at a previous release:

  ```sh
  ls /var/www/asterisk-buch/releases/
  ln -sfn /var/www/asterisk-buch/releases/<older-ts> \
         /var/www/asterisk-buch/current
  ```
