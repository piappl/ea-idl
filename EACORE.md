# eacore

Lossless, GUID-keyed access to Enterprise Architect `.qea`/`.qeax` repositories, independent of EA.
Foundation for editing models outside EA.

## Commands

```bash
uv run eacore diff A.qea B.qea                 # what changed, grouped by package
uv run eacore diff --git HEAD~1 HEAD model.qea # one file between two git revisions
uv run eacore diff --format json A.qea B.qea   # machine-readable
uv run eacore diff --ignore-volatile A B       # hide columns EA rewrites on every save
uv run eacore check model.qea                  # integrity check, exit 1 on errors
uv run eacore textconv model.qea               # stable text dump (for git)
uv run eacore history model.qea --out DIR --template tests/data/empty.qea
```

## Readable `git diff` for .qea files

```bash
# .gitattributes
*.qea  diff=eacore
*.qeax diff=eacore

git config diff.eacore.textconv "uv run eacore textconv"
git config diff.eacore.cachetextconv true
```

## Safety

`eacore` writes only the rows and columns that changed, in one transaction. It refuses to write if:
- the file changed since it was loaded, or
- another program (e.g. EA) holds a lock.

Close the model in EA before writing to it.

## Package boundaries

`eacore` never imports `eaidl`. `eaidl` shares its column naming (`eacore.naming.column_key`).
