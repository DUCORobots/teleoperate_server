#!/usr/bin/env python3
"""格式转换模块"""
import numpy as np
import cv2
from typing import Optional, Tuple
from loguru import logger

class FormatConverter:
    """图像格式转换器"""
    
    def __init__(self, logger: logger):
        self.logger = logger
    
    @staticmethod
    def bgr_to_rgb(image: np.ndarray) -> np.ndarray:
        """BGR转RGB"""
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    
    @staticmethod
    def rgb_to_bgr(image: np.ndarray) -> np.ndarray:
        """RGB转BGR"""
        return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    
    def resize_image(self, image: np.ndarray, new_width: int, new_height: int, 
                    interpolation: int = cv2.INTER_LINEAR) -> np.ndarray:
        """调整图像尺寸"""
        try:
            if image is None or image.size == 0:
                return image
                
            resized = cv2.resize(image, (new_width, new_height), interpolation=interpolation)
            return resized
            
        except Exception as e:
            self.logger.error(f"图像尺寸调整失败: {e}")
            return image
    
    def resize_depth(self, depth_image: np.ndarray, new_width: int, new_height: int) -> np.ndarray:
        """调整深度图尺寸"""
        try:
            if depth_image is None or depth_image.size == 0:
                return depth_image
                
            resized = cv2.resize(depth_image, (new_width, new_height), interpolation=cv2.INTER_NEAREST)
            return resized
            
        except Exception as e:
            self.logger.error(f"深度图尺寸调整失败: {e}")
            return depth_image
    
    def normalize_depth(self, depth_image: np.ndarray, max_depth: float = 10000.0) -> np.ndarray:
        """归一化深度图"""
        try:
            if depth_image is None:
                return depth_image
                
            depth_float = depth_image.astype(np.float32)
            
            # 归一化到0-1范围
            normalized = np.clip(depth_float / max_depth, 0.0, 1.0)
            
            # 转换为16位整数（0-65535）
            normalized_16bit = (normalized * 65535).astype(np.uint16)
            
            return normalized_16bit
            
        except Exception as e:
            self.logger.error(f"深度图归一化失败: {e}")
            return depth_image
    
    def depth_to_colormap(self, depth_image: np.ndarray, 
                         colormap: int = cv2.COLORMAP_JET) -> np.ndarray:
        """深度图转彩色图用于可视化"""
        try:
            if depth_image is None:
                return None
                
            # 归一化深度图
            depth_normalized = cv2.normalize(depth_image, None, 0, 255, cv2.NORM_MINMAX)
            depth_8bit = depth_normalized.astype(np.uint8)
            
            # 应用色彩映射
            colored = cv2.applyColorMap(depth_8bit, colormap)
            
            return colored
            
        except Exception as e:
            self.logger.error(f"深度图色彩映射失败: {e}")
            return None
    
    def crop_image(self, image: np.ndarray, x: int, y: int, width: int, height: int) -> np.ndarray:
        """裁剪图像"""
        try:
            if image is None:
                return None
                
            h, w = image.shape[:2]
            
            x1 = max(0, x)
            y1 = max(0, y)
            x2 = min(w, x + width)
            y2 = min(h, y + height)
            
            if x1 >= x2 or y1 >= y2:
                return image
                
            cropped = image[y1:y2, x1:x2]
            return cropped
            
        except Exception as e:
            self.logger.error(f"图像裁剪失败: {e}")
            return image
    
    def rotate_image(self, image: np.ndarray, angle: float, 
                    center: Optional[Tuple[int, int]] = None) -> np.ndarray:
        """旋转图像"""
        try:
            if image is None:
                return None
                
            h, w = image.shape[:2]
            
            if center is None:
                center = (w // 2, h // 2)
                
            rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated = cv2.warpAffine(image, rotation_matrix, (w, h))
            
            return rotated
            
        except Exception as e:
            self.logger.error(f"图像旋转失败: {e}")
            return image
    
    def convert_to_grayscale(self, image: np.ndarray) -> np.ndarray:
        """转换为灰度图"""
        try:
            if image is None:
                return None
                
            if len(image.shape) == 3:
                grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                grayscale = image
                
            return grayscale
            
        except Exception as e:
            self.logger.error(f"图像灰度转换失败: {e}")
            return image