# dseams.info

Static landing page for [d-SEAMS](https://dseams.info), deployed from
this repository. No HTML5UP / Dimension theme. Analytics is
[Antics](https://antics.turtletech.us/) from TurtleTech ehf.

The page is the suite map: `seams-core` (`seams`), `pydseamslib`
(`import pydseams`), `yodaStruct` (`require("dseams")`),
`dseams-plumed` (`DSEAMS_CAGES`), `linkcell`, and `readcon-core`.
Six repositories live under [github.com/d-SEAMS](https://github.com/d-SEAMS):
`seams-core`, `PydSEAMSlib`, `yodaStruct`, `linkcell`, `wiki`, and
`landing`. Install and API detail live on
[docs.dseams.info](https://docs.dseams.info) and the binding books.
Process and worked examples live on
[wiki.dseams.info](https://wiki.dseams.info).

## Check the site

The standard-library checker validates local links and fragments, HTML
semantics, keyboard access, and the public package/module names:

```bash
python scripts/check-site.py .
```
