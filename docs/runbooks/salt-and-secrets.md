# The salt, and other secrets

`.dwh/salt` is a random value mixed into every hashed (masked) value and protected key. It is
created on the first build and never committed.

- **Back it up** outside git (password manager, secrets vault) as soon as a pipeline is built.
- **Same salt → same hashed ids.** Rebuilding with a new salt gives different hashed ids (joins
  still work inside one build; comparisons with an earlier build's ids do not). KPI values do not
  depend on it.
- **Never commit it.** `.gitignore` and the pre-commit guard refuse `.dwh/` and files named `salt`.

Credentials for sources are given as environment-variable **names** in the specs, never values; the
kernel refuses to record a token. The guard also refuses files that look like keys or passwords.
