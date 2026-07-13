# Basic Example

What it shows: greenlint flagging energy-wasteful patterns in a small sample.

## Run

```sh
greenlint examples/basic/
```

You should see findings for the busy loop in `sample.py` and the `SELECT *`
query — each with the rule id, severity, and what to do instead.
