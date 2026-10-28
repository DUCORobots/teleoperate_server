import json
import sys

def convert_json(input_file, output_file=None):
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 获取相机映射关系
    camera_mapping = data['info'].get('camera_mapping', {})
    color_mapping = camera_mapping.get('colors', {})
    depth_mapping = camera_mapping.get('depths', {})

    new_data = {
        "info": data["info"],
        "text": data["text"],
        "data": []
    }

    # 处理每一帧
    for frame in data["data"]:
        new_frame = {
            "idx": frame["frame_id"],
            "timestamp": frame["timestamp"],
            "states": frame["states"],
            "actions": frame["actions"],
            "tactiles": frame.get("tactiles"),
            "sim_state": frame.get("sim_state"),
            "audios": frame.get("audios")
        }

        # 转换 images -> colors
        colors_obj = {}
        for color_key, img_key in color_mapping.items():
            if img_key in frame.get("images", {}):
                colors_obj[color_key] = frame["images"][img_key]
        if colors_obj:
            new_frame["colors"] = colors_obj

        # 转换 depths -> depths (对象内字段名根据映射)
        depths_obj = {}
        for depth_key, depth_name in depth_mapping.items():
            if depth_name in frame.get("depths", {}):
                depths_obj[depth_key] = frame["depths"][depth_name]
        if depths_obj:
            new_frame["depths"] = depths_obj

        new_data["data"].append(new_frame)

    # 输出结果
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(new_data, f, indent=4, ensure_ascii=False)
        print(f"转换完成，已保存至 {output_file}")
    else:
        # 直接打印到控制台
        print(json.dumps(new_data, indent=4, ensure_ascii=False))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python convert_json.py <输入文件> [输出文件]")
        sys.exit(1)
    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    convert_json(input_path, output_path)