from PyInstaller.utils.hooks import collect_submodules,copy_metadata
hiddenimports=collect_submodules('transformers.models.sam2')
hiddenimports+=collect_submodules('transformers.models.sam2_video')
hiddenimports+=['transformers.models.auto.image_processing_auto','transformers.models.auto.configuration_auto']
datas=copy_metadata('transformers',recursive=True)
datas+=copy_metadata('torchvision')+copy_metadata('Pillow')
# Transformers 5 builds its lazy import registry by scanning its source tree.
module_collection_mode='pyz+py'
