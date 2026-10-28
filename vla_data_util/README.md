# VLA Dataset Metadata Conversion Guide

[中文](README_zh.md) | [English](README.md)

Copy the required metadata file(s) to this directory,
then use `python convert.py` to convert the metadata.
Once conversion is complete, the converted metadata file will be saved in this directory.

Command example:

```bash
python convert.py "<metadata file>" "<converted metadata file>"
```

e.g.:

```bash
python convert.py "data.json" "converted_data.json"
```
