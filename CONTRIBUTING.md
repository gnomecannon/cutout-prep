# Contributing

Small, focused fixes, clearer documentation and independently reviewed tests are
welcome. The maintainer directed this project without independently writing or
auditing its implementation; read [AI_DISCLOSURE.md](AI_DISCLOSURE.md) for context.

For a change:

1. Explain the concrete problem and expected result. For image changes, include
   a redistributable or procedural example with a before/after comparison.
2. Keep originals, existing manual exports and unrelated files protected.
   Preserve the distinction between photo extraction and authored artwork.
3. Add a regression that demonstrates the problem when appropriate, and run
   `python -m unittest discover -s tests -v` from the repository root after
   installing the package in a development environment.
4. State which checks you actually ran and any remaining limits. Be transparent
   about AI-generated changes. AI review and automated tests are not independent
   human code review.

Avoid committing local processing reports, private photographs, camera metadata,
credentials, virtual environments or generated build output. Example content must
have clear redistribution rights and appropriate attribution. Contributions are
provided under this repository's MIT license unless explicitly agreed otherwise;
third-party content must retain its own notices.

The current scope is preparing isolated color-image cutouts. Physical PBR-map
recovery, general scene segmentation, texture atlases and seamless texture
generation need separate design and validation.
