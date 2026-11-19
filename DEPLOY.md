# Deploying dseams.info

The site is the files on `master`: `index.html`, the images, and the
other static files in this repository. The README says the page is
deployed from this repository. `.github/workflows/site.yml` does not
publish it.

## What Actions runs

`site.yml` runs on a push to `master` and on pull requests.
`permissions` is `contents: read`. The only token is `GITHUB_TOKEN`,
and the workflow uses it for the link checker. It does not push a
branch, and this repository does not configure GitHub Pages in the
workflow. There is no `gh-pages` publish step and no Netlify config in
the tree.

The `check` job runs on Python 3.10 and 3.13:

```text
python3 -m unittest scripts/test_check_site.py
python3 scripts/check-site.py .
python3 scripts/check-cross-nav.py
python3 scripts/check-registries.py
```

The `links` job checks `index.html` and `README.md` with
`lycheeverse/lychee-action` (`lychee.toml`, `GITHUB_TOKEN`) and then:

```text
python3 scripts/check-dois.py index.html README.md
```

`lychee.toml` sets the retries and the timeout. The action fails the
job when a link fails.

## When Actions is queued or starved

Run the same checks on the commit you want to publish. When they pass,
push `master`. That push is the publish: the site is this branch, and a
credential that can push to `d-SEAMS/landing` is the same write access a
`GITHUB_TOKEN` uses when a workflow is allowed to push. Do not add
another secret to `site.yml`. The workflow stays `contents: read`.

```text
python3 -m unittest scripts/test_check_site.py
python3 scripts/check-site.py .
python3 scripts/check-cross-nav.py
python3 scripts/check-registries.py
python3 scripts/check-dois.py index.html README.md
git push origin master
```

`git push origin master` was not run against GitHub from the checkout
that wrote this file. The checks above were run in that checkout.
