# Localization scaffold

Offside uses a key-based i18n scaffold so future locales can be added without changing code.

## How it works

- Default locale file: `locales/en.json`
- Template lookup: `{{ t("key") }}`
- Python lookup: `from utils.i18n import t`
- Active locale: `APP_LOCALE` (defaults to `en`)

## Adding a locale

1. Copy the default file:
   - `locales/en.json` -> `locales/es.json` (example)
2. Translate the values while keeping the same keys.
3. Set `APP_LOCALE=es` in the target environment.

## Guidance for new copy

- Add new strings to `locales/en.json`.
- Use `t("key", "fallback")` in Python or templates.
- Avoid hardcoded user-facing strings in new routes/templates.
