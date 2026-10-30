# Security and privacy

Cutout Prep is a local command-line image-processing utility. It has not had an
independent human security audit and is not designed as an upload service or a
sandbox for hostile files. Its implementation and tests were generated with AI;
see [the development disclosure](AI_DISCLOSURE.md).

Image, RAW and ICC parsing runs through external libraries. Keep dependencies
updated and process files you trust. Large images can require substantial memory
and CPU time. Use an isolated environment if you need to inspect untrusted input.

Settings files are instructions from the local user. They can select output
locations and explicitly reference mask files, including files outside the input
folder. Review settings from other people before running them. File hashes and
managed-output checks help prevent accidental replacement; they do not
authenticate a settings file or processing report. Back up valuable work.

## Privacy

Processing runs locally without an application cloud service or model download.
Reports contain local paths, input filenames, processing settings and source
hashes. Preview images show the processed subjects. Redact reports and confirm
you have rights to images before attaching them to public issues. Original
photographs can contain location and camera metadata even though exported PNGs
strip that metadata.

## Reporting a vulnerability

Use this repository's **Security → Report a vulnerability** option if available.
Otherwise, open a minimal issue requesting a private reporting channel without
posting sensitive files or exploit details. Include the affected version and a
small reproduction when it is safe to share. Security response times and fixes
are not guaranteed.
