cmake_minimum_required(VERSION 3.8)
project(humanoid_vision_system)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rclpy REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(vision_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(rosidl_default_generators REQUIRED)

ament_python_install_package(vision_system)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/CameraStatus.msg"
  "msg/CompressedImage.msg" 
  "msg/CompressionInfo.msg"
  DEPENDENCIES builtin_interfaces std_msgs
)

install(PROGRAMS
  vision_system/scripts/vision_system_main.py
  DESTINATION lib/${PROJECT_NAME}
)

install(PROGRAMS
  scripts/compile_proto.sh
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY
  config/
  DESTINATION share/${PROJECT_NAME}/config/
)

install(DIRECTORY
  ${CMAKE_CURRENT_SOURCE_DIR}/../../manual_config/
  DESTINATION share/${PROJECT_NAME}/manual_config/
  OPTIONAL
)

install(DIRECTORY
  proto/
  DESTINATION share/${PROJECT_NAME}/proto/
)

install(FILES
  requirements.txt
  DESTINATION share/${PROJECT_NAME}/
)

install(DIRECTORY
  ${CMAKE_CURRENT_SOURCE_DIR}/../../client_test/
  DESTINATION share/${PROJECT_NAME}/client_test/
  OPTIONAL
)

ament_export_dependencies(
  rclpy
  std_msgs
  sensor_msgs
  geometry_msgs
  tf2_ros
  vision_msgs
  builtin_interfaces
  rosidl_default_runtime
)

ament_package()
