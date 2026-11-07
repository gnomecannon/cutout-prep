from PyInstaller.utils.hooks import collect_dynamic_libs,collect_delvewheel_libs_directory,copy_metadata
binaries=collect_dynamic_libs('pi_heif')
datas=copy_metadata('pi-heif')
datas,binaries=collect_delvewheel_libs_directory('pi_heif',datas=datas,binaries=binaries)
