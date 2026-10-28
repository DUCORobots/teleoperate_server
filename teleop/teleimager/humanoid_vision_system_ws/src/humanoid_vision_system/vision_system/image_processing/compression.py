#!/usr/bin/env python3
"""
图像压缩模块 - 负责彩色图和深度图的压缩
彩色图使用JPEG压缩,深度图使用12位量化 + ZSTD压缩
支持多通道差异化压缩策略:JPEG有损压缩、ZSTD无损压缩
"""

import numpy as np
import cv2
import zstandard
from typing import Optional, Tuple, Dict, Any
import time
from loguru import logger
from ..proto.vision_messages_pb2 import CompressionInfo

class ImageCompressor:
    """图像压缩器类"""
    
    def __init__(self, logger: logger):
        self.logger = logger
        
    def compress_rgb(self, image: np.ndarray, quality: int = 80,
                     format: str = "JPEG", **kwargs) -> Tuple[Optional[bytes], CompressionInfo]:
        """压缩彩色图像"""
        compression_info = CompressionInfo()

        try:
            if image.dtype != np.uint8:
                image = image.astype(np.uint8)

            format_upper = format.upper()

            if format_upper == "JPEG":
                compression_info.compression_type = CompressionInfo.JPEG
                # JPEG压缩期望BGR格式（OpenCV默认）
                if len(image.shape) == 3 and image.shape[2] == 3:
                    image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
                else:
                    image_bgr = image

                # JPEG压缩
                encode_param = [cv2.IMWRITE_JPEG_QUALITY, quality]
                success, encoded_data = cv2.imencode('.jpg', image_bgr, encode_param)
                
            elif format_upper == "PNG":
                compression_info.compression_type = CompressionInfo.PNG
                # PNG压缩（无损）
                encode_param = [cv2.IMWRITE_PNG_COMPRESSION, min(9, quality // 10)]
                success, encoded_data = cv2.imencode('.png', image, encode_param)
                
            else:
                self.logger.error(f"不支持的RGB压缩格式: {format}")
                return None, compression_info
                
            if not success:
                self.logger.error(f"{format}压缩失败")
                return None, compression_info
                
            compressed_data = encoded_data.tobytes()
            return compressed_data, compression_info
            
        except Exception as e:
            self.logger.error(f"RGB压缩异常: {e}")
            return None, compression_info

    def compress_depth(self, depth_image: np.ndarray, quantization_bits: int = 12,
                       zstd_level: int = 3, **kwargs) -> Tuple[Optional[bytes], CompressionInfo]:
        """
        压缩深度图：支持有损量化+ZSTD压缩和无损ZSTD压缩
        
        Args:
            depth_image: 深度图，单位通常为毫米
            quantization_bits: 量化位数(12-16),16表示无损
            zstd_level: ZSTD压缩级别(1-22)
        """
        compression_info = CompressionInfo()
        
        try:
            if depth_image.dtype not in [np.uint16, np.float32, np.float64]:
                depth_image = depth_image.astype(np.uint16)
                
            if quantization_bits == 16:
                compression_info.compression_type = CompressionInfo.ZSTD_LOSSLESS
                quantized_data = depth_image.astype(np.uint16)
            else:
                compression_info.compression_type = CompressionInfo.ZSTD_LOSSY
                
                if depth_image.dtype == np.uint16:
                    quantized_data = depth_image
                else:
                    depth_mm = np.clip(depth_image, 0, 65535).astype(np.uint16)
                    quantized_data = depth_mm
                    
                if quantization_bits < 16:
                    max_value = (1 << quantization_bits) - 1
                    depth_min = np.min(quantized_data)
                    depth_max = np.max(quantized_data)
                    
                    if depth_max - depth_min > 0:
                        normalized_depth = (quantized_data - depth_min) / (depth_max - depth_min)
                        quantized_data = (normalized_depth * max_value).astype(np.uint16)
                    else:
                        quantized_data = np.zeros_like(quantized_data)
            
            byte_data = quantized_data.tobytes()
            compressed_data = zstandard.compress(byte_data, level=zstd_level)

            return compressed_data, compression_info
            
        except Exception as e:
            self.logger.error(f"深度图压缩异常: {e}")
            return None, compression_info

    def decompress_rgb(self, compressed_data: bytes) -> Optional[np.ndarray]:
        """解压缩JPEG图像"""
        try:
            encoded_data = np.frombuffer(compressed_data, dtype=np.uint8)
            image = cv2.imdecode(encoded_data, cv2.IMREAD_COLOR)
            if image is not None:
                image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            return image
        except Exception as e:
            self.logger.error(f"JPEG解压缩异常: {e}")
            return None
            
    def decompress_depth(self, compressed_data: bytes, original_shape: Tuple[int, int],
                         quantization_params: Optional[dict] = None) -> Optional[np.ndarray]:
        """解压缩深度图"""
        try:
            decompressed_data = zstandard.decompress(compressed_data)
            depth_array = np.frombuffer(decompressed_data, dtype=np.uint16).reshape(original_shape)
            
            if quantization_params:
                bits = quantization_params.get('bits', 16)
                if bits < 16:
                    max_value = (1 << bits) - 1
                    depth_min = quantization_params['min']
                    depth_max = quantization_params['max']
                    # 反量化
                    depth_array = depth_array.astype(np.float32)
                    depth_array = depth_array / max_value * (depth_max - depth_min) + depth_min
                    depth_array = depth_array.astype(np.uint16)
                    
            return depth_array
        except Exception as e:
            self.logger.error(f"深度图解压缩异常: {e}")
            return None