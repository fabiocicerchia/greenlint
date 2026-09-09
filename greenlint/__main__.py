"""Entry point for `python -m greenlint`.

The `greenlint` console script covers the installed case, but `python -m` is
what runs a checkout without installing it — and what the editor plugins fall
back to. Splitting the module into a package removed the single file that used
to make that work.
"""

from greenlint.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
