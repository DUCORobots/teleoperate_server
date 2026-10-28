# VLA数据集元数据转换指南

[中文](README_zh.md) | [English](README.md)

拷贝需要的元数据文件到本目录
然后使用`python convert.py`转换元数据
转换完成后，转换后的元数据文件将保存在本目录下
命令示例：
```bash
python convert.py "元数据文件" "转换后的元数据文件"
```
eg：
```bash
python convert.py "data.json" "converted_data.json"
```