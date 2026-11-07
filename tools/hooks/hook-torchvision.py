from PyInstaller.utils.hooks import collect_dynamic_libs,copy_metadata
# Torchvision 0.29 loads stable-ABI extensions by pathname, not Python imports.
# Collect both old and stable names and their platform-specific dependencies.
binaries=collect_dynamic_libs('torchvision',search_patterns=['*.pyd','*.dll','*.so','*.dylib'])
datas=copy_metadata('torchvision')
module_collection_mode='pyz+py'
