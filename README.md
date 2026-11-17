# dseams.info

Static landing page for [d-SEAMS](https://dseams.info/), deployed from
this repository. No external CDNs, no third-party fonts, and no tracking
scripts.

The page introduces the `seams-core` ice, clathrate, and ring topology
engine with an interactive raw-versus-CHILL+ interface comparison,
install tabs and documentation links across Python (`pydseamslib`),
CLI / C++ (`seams-core`), Rust (`dseams`), Julia (`Dseams.jl`), R
(`dseams-r`), Lua (`yodaStruct`), Fortran (`dseams-fortran`), PLUMED
(`dseams-plumed`), and `linkcell`, real CLI outputs paired with Cycles
renders, and citation metadata for
[doi:10.1021/acs.jcim.0c00031](https://doi.org/10.1021/acs.jcim.0c00031).

## Check the site

```bash
python3 scripts/check-site.py .
python3 scripts/check-cross-nav.py
python3 scripts/check-registries.py
python3 scripts/check-images.py .
lychee --config lychee.toml --root-dir "$PWD" index.html README.md
python3 scripts/check-dois.py index.html README.md
```
