"""Allow ``python -m cutout_prep`` alongside the installed CLI entry point."""
from .process_images import main

raise SystemExit(main())
