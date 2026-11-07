"""Safe default result locations for the desktop's one-folder workflow."""
from pathlib import Path


def create_results_folder(photo_folder, label):
    """Reserve a fresh sibling folder without reusing or overwriting old work."""
    source = Path(photo_folder).resolve()
    if not source.is_dir():
        raise ValueError('Choose a folder containing photographs.')
    base = source.parent / f'{source.name} - {label}'
    for number in range(1, 10000):
        candidate = base if number == 1 else base.with_name(f'{base.name} ({number})')
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise ValueError('Choose a different location for the results.')
