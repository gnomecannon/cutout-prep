# The image processor fingerprints its readable source for protected exports.
module_collection_mode='pyz+py'
# Alignment is an optional Python API, but its source is part of that fingerprint.
hiddenimports=['cutout_prep.pair_alignment','cutout_prep.desktop_paths','cutout_prep.leaf_batch','cutout_prep.leaf_geometry','cutout_prep.leaf_review']
