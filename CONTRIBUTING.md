# Contributing

Anyone may fork, clone and propose changes. Open an issue describing the problem, source evidence or desired behavior. For changes, branch from main in your fork and submit a pull request with a concise explanation and reproduction steps. Maintainers review and decide whether to merge; public access does not grant direct push rights.

Keep each change focused. Preserve publication dates and distinguish measured results, source claims and proposals. Cite primary sources, with access dates for changing information. Do not replace a historical test count with a result from a different environment.

Run `python scripts/check_public.py`, the portable example and the affected tests listed in README. For UI changes inspect the affected browser flow at desktop and mobile sizes. The full historical test suite needs dependencies not bundled here; report what you actually ran.

Never commit personal records, credentials, live account configuration, unlicensed assets or private logs. Use synthetic fixtures. Changes to permissions, deployment or data handling need an explicit threat model and counterexample tests. Avoid new executable dependencies unless needed and reviewed.

By contributing, you offer your contribution under this project's MIT licence and confirm you have the necessary rights. Preserve third-party licence notices. No contribution agreement or payment is required.
