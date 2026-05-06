# Workflows disabled

All workflow files in this directory have been renamed from `*.yml` to
`*.yml.disabled` to stop scheduled cron runs and prevent manual dispatches
that would consume external API credits (Odds API, CFBD, MLB Stats API,
Baseball Savant, ESPN). GitHub Actions only auto-discovers `.yml` / `.yaml`,
so the disabled variants are inert.

The repo is being kept around as a reference. To re-enable a single workflow,
rename it back:

```
git mv path/to/foo.yml.disabled path/to/foo.yml
```

To re-enable everything:

```
cd .github/workflows
for f in *.yml.disabled; do git mv "$f" "${f%.disabled}"; done
```
