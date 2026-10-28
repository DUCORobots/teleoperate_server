# 相机状态消息
string camera_id
uint8 health_status
float64 frame_rate

# 健康状态枚举
uint8 UNKNOWN=0
uint8 HEALTHY=1
uint8 WARNING=2
uint8 ERROR=3
uint8 OFFLINE=4