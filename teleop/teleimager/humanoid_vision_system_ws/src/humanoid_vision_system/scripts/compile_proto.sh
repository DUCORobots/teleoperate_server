#!/bin/bash

# 编译 Protocol Buffers 文件

PROTO_DIR="proto"
OUTPUT_DIR="vision_system/proto"

echo "编译 Protocol Buffers..."

# 创建输出目录
mkdir -p $OUTPUT_DIR

# 编译所有 .proto 文件
for proto_file in $PROTO_DIR/*.proto; do
    echo "编译: $proto_file"
    protoc -I=$PROTO_DIR --python_out=$OUTPUT_DIR $proto_file
done

echo "编译完成！输出目录: $OUTPUT_DIR"