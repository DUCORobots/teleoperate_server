# 压缩图像消息
string camera_id
uint8 image_type
uint8[] image_data
uint32 original_width
uint32 original_height
CompressionInfo compression_info

# 图像类型枚举
uint8 UNKNOWN=0
uint8 RGB=1
uint8 DEPTH=2
uint8 INFRARED=3